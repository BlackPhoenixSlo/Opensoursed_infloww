#!/usr/bin/env python3
"""Free trial links' and Profile promotions' per-link figures (link_metrics):
OF's claimers per link x our transactions ledger, cached in link_claimers, and
the Edit dialog's Promo cost / Source / Tag in link_meta. OF is faked.

Locks:
  • The walk pages by 20 (the most OF reads per call: above 20 it skips fans,
    live 2026-10-18) and moves the offset by the page size, not by the rows
    returned: OF answered offset 0 with 9 fans and offset 10 with 10 more, both
    hasMore:true (HAR 2026-10-18). It ends on an empty page, hasMore:false, or
    a short page past the claim count; an offset OF ignores cannot loop it.
  • Promotion claimers carry subscribedOnData like trial ones (captured shape,
    app/lib/__fixtures__/of/offer-fans-promo.json); a row without it falls back.
  • subscribeAt is kept from first sight, never moved later.
  • A link is re-walked only when OF's claim count for it moved, or, for
    Lifetime, when its Details open past an hour after the last walk (in the
    background, once, not while the account's lock is held or backed off).
  • The list returns the cache; past an hour (or never checked) it starts one
    background refresh per account and kind; an OF failure backs off.
  • Spend = TRACKED_STATUSES ledger rows at/after subscribeAt; refunds and
    chargebacks are not revenue; a fan on several links: the latest claim wins.
  • A re-armed promotion folds its earlier OF promos into one row (the
    re-arm's record: test_promo_reactivate.case_reactivates_finished).
  • A claimer with no subscribedOnData: first-seen shown, spend "—".
  • PUT /admin/link-meta validates and stores locally; per-account throughout.
  • List: OF's add-to-list runs once on the first save, again only when the
    claim count grows; an OF error stops the pass and backs off.
  • Create stores Source / Promo cost / Tag / List for the new tracking link
    and the new free trial link (count 0 counts as added); no id: meta_saved
    false; a bad field: 422 before OF.
  • Profile promotion's "Add fans to list" is one account-level setting: off
    adds nothing; on, each promotion with claims goes in once, then on growth;
    a new list takes each once; an OF error stops the pass and backs off.
  • Pre-warm reads tracking, trial and promotion figures by the same rules
    (only a moved count re-reads claimers, an expired claimers TTL alone does
    not; a backed-off kind is skipped), so the page then opens from cache; it
    runs for every OnlyFans account with a session, dead sessions skipped.

Run: ./venv/bin/python service/tests/test_link_metrics.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

# Feature logic, not the account gate (test_account_isolation_gate's job).
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import link_metrics as lm  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, LinkClaimer, LinkMeta, PromoCampaign, Transaction  # noqa: E402

_client = _harness.make_client()
lm._PAGE_SLEEP_S = 0

_T0 = datetime(2026, 9, 1, 12, 0, 0)


def _of_time(dt: datetime) -> str:
    return dt.isoformat() + "+00:00"


def _fan(fid, subscribe_at=None, *, total=0.0, data=True):
    u = {"id": fid, "name": f"Fan {fid}", "username": f"u{fid}"}
    if data:
        u["subscribedOnData"] = {
            "subscribeAt": _of_time(subscribe_at or _T0), "totalSumm": total, "subscribesSumm": 0,
            "postsSumm": 0, "messagesSumm": total, "streamsSumm": 0, "tipsSumm": 0}
    return u


class FakeOF:
    """/trials, /promotions and /subscriptions/subscribers?filter[...] as OF answers them."""

    def __init__(self):
        self.trials: list[dict] = []
        self.promos: list[dict] = []
        self.claimers: dict[tuple[str, int], list[dict]] = {}
        self.hidden: dict[tuple[str, int], set[int]] = {}    # fans OF drops from a page after the limit
        self.claim_calls: list[tuple[str, int, int, int]] = []
        self.fail: set[tuple[str, int]] = set()
        self.ignore_offset = False
        self.has_more: bool | None = True                     # OF's hasMore: true even on a short page

    def trial(self, tid, fans, *, count=None):
        self.claimers[("trial", tid)] = fans
        self.trials.append({"id": tid, "trialLinkName": f"Trial {tid}", "url": f"https://of/t{tid}",
                            "claimCounts": len(fans) if count is None else count, "isFinished": False})

    def promo(self, pid, fans, *, finished=False):
        self.claimers[("promo", pid)] = fans
        self.promos.append({"id": pid, "message": f"Promo {pid}", "price": 5, "claimsCount": len(fans),
                            "isFinished": finished, "canClaim": not finished})

    def count(self, kind, of_id, n):
        rows = self.trials if kind == "trial" else self.promos
        key = "claimCounts" if kind == "trial" else "claimsCount"
        next(r for r in rows if r["id"] == of_id)[key] = n

    def trial_links(self, *, offset=0, limit=100):
        return {"list": self.trials[offset:offset + limit], "hasMore": False}

    def promotions(self, *, offset=0, limit=100):
        return {"items": self.promos[offset:offset + limit], "hasMore": True}

    list_calls: list[tuple[str, str, int]]
    list_fail = False

    def add_link_claimers_to_list(self, list_id, kind, link_id):
        if not hasattr(self, "list_calls"):
            self.list_calls = []
        self.list_calls.append((str(list_id), kind, int(link_id)))
        if self.list_fail:
            raise RuntimeError("429 Too Many Requests")
        return {"count": 1}

    def offer_claims(self, offer_id, kind, *, limit=20, offset=0):
        self.claim_calls.append((kind, int(offer_id), limit, offset))
        if (kind, int(offer_id)) in self.fail:
            raise RuntimeError("429 Too Many Requests")
        fans = self.claimers.get((kind, int(offer_id)), [])
        start = 0 if self.ignore_offset else offset
        page = [f for f in fans[start:start + limit] if f["id"] not in self.hidden.get((kind, int(offer_id)), ())]
        out = {"list": page}
        if self.has_more is not None:
            out["hasMore"] = self.has_more if page else False
        return out


_spawned: list = []
lm._spawn = _spawned.append        # a refresh runs when the case runs it, not in the TestClient's loop


def _use(fake=None):
    fake = fake or FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    fake.list_calls = []
    lm._REFRESHING.clear()
    lm._FAILED_AT.clear()
    lm._REWALKING.clear()
    lm._LIST_QUEUED.clear()
    lm._LIST_FAILED_AT.clear()
    _drop_spawned()
    return fake


def _drop_spawned():
    while _spawned:
        _spawned.pop().close()


def _run_spawned():
    while _spawned:
        asyncio.run(_spawned.pop(0))


_n = 0


def _acct() -> str:
    global _n
    _n += 1
    aid = f"link_metrics_{_n}"

    async def go():
        async with get_session() as s:
            s.add(Account(id=aid, nickname=aid))
    asyncio.run(go())
    return aid


def _tx(aid, fan, kind, cents, when, *, status="cleared", net=None):
    async def go():
        async with get_session() as s:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents,
                              net_cents=net if net is not None else cents * 8 // 10,
                              occurred_at=when, status=status, currency="USD", source="ledger"))
    asyncio.run(go())


def _trials(aid):
    r = _client.get(f"/admin/trial-links?account_id={aid}")
    assert r.status_code == 200, r.text
    d = r.json()
    return d, {l["of_trial_id"]: l for l in d["links"]}


def _promos(aid):
    r = _client.get(f"/admin/promotions?account_id={aid}")
    assert r.status_code == 200, r.text
    d = r.json()
    return d, {c["of_promo_id"]: c for c in d["campaigns"]}


def _fans(aid, kind, of_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = _client.get(f"/admin/link-metrics/fans?account_id={aid}&kind={kind}&of_id={of_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def _claimers(aid, kind, of_id):
    async def go():
        async with get_session() as s:
            return {c.fan_id: c for c in (await s.execute(select(LinkClaimer).where(
                LinkClaimer.account_id == aid, LinkClaimer.kind == kind,
                LinkClaimer.of_id == of_id))).scalars().all()}
    return asyncio.run(go())


def _age_walks(aid, minutes):
    async def go():
        async with get_session() as s:
            await s.execute(update(LinkMeta).where(LinkMeta.account_id == aid, LinkMeta.walked_at.is_not(None))
                            .values(walked_at=datetime.utcnow() - timedelta(minutes=minutes)))
    asyncio.run(go())


def _meta(aid, kind, of_id):
    async def go():
        async with get_session() as s:
            return (await s.execute(select(LinkMeta).where(
                LinkMeta.account_id == aid, LinkMeta.kind == kind, LinkMeta.of_id == of_id))).scalar_one_or_none()
    return asyncio.run(go())


def _age_checks(aid, minutes):
    async def go():
        async with get_session() as s:
            await s.execute(update(LinkMeta).where(LinkMeta.account_id == aid)
                            .values(checked_at=datetime.utcnow() - timedelta(minutes=minutes)))
    asyncio.run(go())


# ── The walk ──

def case_walk_moves_offset_by_page_past_a_short_page():
    f = FakeOF()
    fans = [_fan(800_000 + i) for i in range(40)]
    f.claimers[("trial", 11)] = fans
    f.hidden[("trial", 11)] = {800_003}          # OF answers 19 on the first page, hasMore:true
    got = lm.walk(f, "trial", 11, 40)
    assert [c[3] for c in f.claim_calls] == [0, 20, 40], f.claim_calls
    assert len(got) == 39 and 800_039 in {x["fan_id"] for x in got}, len(got)
    assert all(c[2] == 20 for c in f.claim_calls), "pages of 20: OF skips fans above it"


def case_walk_reads_a_20_row_page_then_a_short_page():
    f = FakeOF()
    f.claimers[("trial", 15)] = [_fan(805_000 + i) for i in range(25)]
    got = lm.walk(f, "trial", 15, 25)
    assert [(c[2], c[3]) for c in f.claim_calls] == [(20, 0), (20, 20)], f.claim_calls
    assert len(got) == 25 and len({x["fan_id"] for x in got}) == 25


def case_walk_reads_the_captured_shape():
    """The captured trial claimers (app/lib/__fixtures__/of/offer-fans-trial.json, synthetic values): 9 then 10
    fans, hasMore true on both. Every fan is read; subscribeAt and the lifetime sums parse."""
    import json
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "app", "lib", "__fixtures__", "of",
                                     "offer-fans-trial.json")))
    calls = []

    rows = [u for p in fx["pages"] for u in p["list"]]   # OF's rows in order; served 20 at a time

    class Captured:
        def offer_claims(self, offer_id, kind, *, limit=20, offset=0):
            calls.append((offer_id, kind, limit, offset))
            return {"list": rows[offset:offset + limit], "hasMore": True}
    got = lm.walk(Captured(), "trial", 4242, fx["totals"]["fans"])
    assert [c[3] for c in calls] == [0], "19 fans: one page of 20, short past the count"
    assert len(got) == fx["totals"]["fans"] == 19
    assert sum(f["lifetime"]["total"] for f in got) == round(fx["totals"]["total"] * 100)
    assert sum(1 for f in got if f["lifetime"]["total"] > 0) == fx["totals"]["spent"]
    assert got[0]["subscribe_at"] == datetime(2026, 9, 1, 11, 0), got[0]["subscribe_at"]


def case_walk_stops_on_has_more_false_and_on_short_page_past_count():
    f = FakeOF()
    f.claimers[("trial", 12)] = [_fan(810_000 + i) for i in range(45)]
    f.has_more = None                             # OF sends no hasMore at all
    assert len(lm.walk(f, "trial", 12, 45)) == 45
    assert [c[3] for c in f.claim_calls] == [0, 20, 40], "short page past the count ends it"
    f2 = FakeOF()
    f2.claimers[("trial", 13)] = [_fan(820_000 + i) for i in range(30)]
    f2.has_more = False
    assert len(lm.walk(f2, "trial", 13, 30)) == 20 and len(f2.claim_calls) == 1, "hasMore:false ends it"
    f3 = FakeOF()
    f3.claimers[("promo", 16)] = []                # an old promotion: claim count 2, no rows at any limit
    assert lm.walk(f3, "promo", 16, 2) == [] and len(f3.claim_calls) == 1, "an empty first page ends it"


def case_walk_cannot_loop_on_an_ignored_offset():
    f = FakeOF()
    f.claimers[("trial", 14)] = [_fan(830_000 + i) for i in range(20)]
    f.ignore_offset = True
    got = lm.walk(f, "trial", 14, 20)
    assert len(got) == 20, "fans are deduped"
    assert len(f.claim_calls) == 1 + lm._MAX_EXTRA_PAGES, f.claim_calls
    try:
        lm.walk(type("Bad", (), {"offer_claims": lambda *a, **k: {"error": "x"}})(), "trial", 1, 5)
    except ValueError:
        pass
    else:
        raise AssertionError("an unusable payload must raise, not read as no fans")


# ── Cache: subscribeAt, re-walk on count change ──

def case_subscribe_at_is_kept_from_first_sight():
    aid = _acct()
    f = _use()
    f.trial(21, [_fan(840_001, _T0, total=5), _fan(840_002, _T0)])
    _trials(aid)
    _run_spawned()
    first = _claimers(aid, "trial", 21)
    assert first[840_001].subscribe_at == _T0 and first[840_001].lifetime_total_cents == 500
    # The fan re-subscribes later: OF now reports a later subscribeAt. A third fan claims.
    f.claimers[("trial", 21)] = [_fan(840_001, _T0 + timedelta(days=9), total=12),
                                 _fan(840_002, _T0 - timedelta(hours=1)), _fan(840_003, _T0)]
    f.count("trial", 21, 3)
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    now = _claimers(aid, "trial", 21)
    assert now[840_001].subscribe_at == _T0, "subscribeAt must never move later"
    assert now[840_001].lifetime_total_cents == 1200, "lifetime sums follow OF"
    assert now[840_002].subscribe_at == _T0 - timedelta(hours=1), "an earlier one is the first claim"
    assert now[840_001].first_seen_at == first[840_001].first_seen_at
    assert set(now) == {840_001, 840_002, 840_003}


def case_rewalk_only_when_claim_count_moves():
    aid = _acct()
    f = _use()
    f.trial(31, [_fan(850_001)])
    f.trial(32, [_fan(850_002), _fan(850_003)])
    _trials(aid)
    _run_spawned()
    walked = {c[1] for c in f.claim_calls}
    assert walked == {31, 32}, walked
    f.claim_calls.clear()
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert f.claim_calls == [], f"nothing moved, nothing re-walked: {f.claim_calls}"
    f.claimers[("trial", 32)].append(_fan(850_004))
    f.count("trial", 32, 3)
    _age_checks(aid, 61)
    d, by = _trials(aid)
    assert d["metrics_refreshing"] is True
    _run_spawned()
    assert {c[1] for c in f.claim_calls} == {32}, f.claim_calls
    _, by = _trials(aid)
    assert by[32]["metrics"]["claimers"] == 3


def case_refresh_after_an_hour_once_and_backs_off_on_failure():
    aid = _acct()
    f = _use()
    f.trial(41, [_fan(860_001)])
    d, by = _trials(aid)
    assert d["metrics_updated_at"] is None and d["metrics_refreshing"] is True
    assert by[41]["metrics"]["earnings_cents"] is None, "never walked: '—', not $0"
    assert len(_spawned) == 1
    _trials(aid)
    assert len(_spawned) == 1, "one refresh per account and kind at a time"
    _run_spawned()
    d, _ = _trials(aid)
    assert d["metrics_updated_at"] and d["metrics_refreshing"] is False and not _spawned, "fresh: cache only"
    _age_checks(aid, 59)
    _trials(aid)
    assert not _spawned, "under an hour is fresh"
    _age_checks(aid, 61)
    f.fail.add(("trial", 41))
    f.count("trial", 41, 2)
    _trials(aid)
    assert len(_spawned) == 1
    _run_spawned()
    assert (aid, "trial") in lm._FAILED_AT
    _trials(aid)
    assert not _spawned, "an OF failure backs off instead of retrying every list call"


def case_refresh_waits_for_the_account_lock():
    aid = _acct()
    f = _use()
    f.trial(51, [_fan(870_001)])

    async def go():
        lock = lm._lock(aid)
        await lock.acquire()
        task = asyncio.create_task(lm.refresh(aid, "trial", [(51, 1, None)]))
        await asyncio.sleep(0.05)
        assert f.claim_calls == [], "no OF call while another walk holds the account's lock"
        lock.release()
        await task
        assert len(f.claim_calls) == 1
    asyncio.run(go())
    lm._LOCKS.pop(aid, None)


def case_details_while_locked_returns_cache_flagged():
    aid = _acct()
    f = _use()
    f.trial(52, [_fan(870_101)])

    async def hold():
        await lm._lock(aid).acquire()
    asyncio.run(hold())
    d = _fans(aid, "trial", 52, count=1)
    assert d["refreshing"] is True and d["fans"] == [] and f.claim_calls == []
    lm._LOCKS.pop(aid, None)
    d = _fans(aid, "trial", 52, count=1)
    assert [x["fan_id"] for x in d["fans"]] == [870_101], "unlocked: walked on demand"


# ── Figures ──

def case_earnings_from_the_ledger_since_claim_without_refunds():
    aid = _acct()
    f = _use()
    a, b = 880_001, 880_002
    f.trial(61, [_fan(a, _T0, total=99), _fan(b, _T0)])
    _trials(aid)
    _run_spawned()
    _tx(aid, a, "tip", 4000, _T0 - timedelta(days=1))                      # before the claim
    _tx(aid, a, "subscription", 1000, _T0 + timedelta(minutes=1), net=800)
    _tx(aid, a, "ppv_message", 500, _T0 + timedelta(days=1), status="pending", net=400)
    _tx(aid, a, "ppv_post", 700, _T0 + timedelta(days=2), status="refunded")
    _tx(aid, a, "tip", 300, _T0 + timedelta(days=3), status="chargedback")
    _, by = _trials(aid)
    m = by[61]["metrics"]
    assert m["earnings_cents"] == 1500 and m["earnings_net_cents"] == 1200, m
    assert m["fans_who_spent"] == 1 and m["fans_counted"] == 2 and m["claimers"] == 2, m
    d = _fans(aid, "trial", 61)
    row = {x["fan_id"]: x for x in d["fans"]}
    assert row[a]["since"]["subs_net_cents"] == 800 and row[a]["since"]["messages_net_cents"] == 400
    assert row[a]["since"]["posts_cents"] == 0 and row[a]["since"]["tips_cents"] == 0
    assert row[a]["lifetime"]["total_cents"] == 9900, "Lifetime = OF's totalSumm"
    assert row[b]["since"]["total_cents"] == 0
    assert d["fans"][0]["fan_id"] == a, "the biggest spender first"
    assert d["ledger_since"].startswith("2026-08-31")


def case_fan_on_two_links_latest_claim_wins():
    aid = _acct()
    f = _use()
    fid = 890_001
    f.trial(71, [_fan(fid, _T0)])
    f.promo(72, [_fan(fid, _T0 + timedelta(days=5))])
    _trials(aid)
    _promos(aid)
    _run_spawned()
    _tx(aid, fid, "tip", 1000, _T0 + timedelta(days=1))
    _tx(aid, fid, "tip", 2500, _T0 + timedelta(days=6))
    _, tby = _trials(aid)
    _, pby = _promos(aid)
    assert tby[71]["metrics"]["earnings_cents"] == 1000, tby[71]["metrics"]
    assert pby[72]["metrics"]["earnings_cents"] == 2500, pby[72]["metrics"]


def case_promo_rearm_folds_into_one_campaign_row():
    aid = _acct()
    f = _use()
    old, new = 910_001, 910_002
    f.promo(old, [_fan(920_001, _T0)], finished=True)
    f.promo(new, [_fan(920_002, _T0 + timedelta(days=10))])

    async def seed():
        async with get_session() as s:
            c = PromoCampaign(account_id=aid, of_promo_id=new, name="Weekend", discount_percent=50,
                              status="active", auto_reactivate=True, reactivate_count=1)
            s.add(c)
            await s.flush()
            s.add(LinkMeta(account_id=aid, kind="promo", of_id=old, campaign_id=c.id))
            return c.id
    cid = asyncio.run(seed())
    _promos(aid)
    _run_spawned()
    _tx(aid, 920_001, "ppv_message", 1500, _T0 + timedelta(days=1))
    _tx(aid, 920_002, "tip", 500, _T0 + timedelta(days=11))
    d, by = _promos(aid)
    assert old not in by, "the earlier OF promo folds into the campaign's row"
    m = by[new]["metrics"]
    assert by[new]["id"] == cid and m["earnings_cents"] == 2000 and m["fans_who_spent"] == 2, m
    det = _fans(aid, "promo", new, campaign_id=cid)
    assert {x["fan_id"] for x in det["fans"]} == {920_001, 920_002}


def case_claimer_without_subscribed_on_data_is_unknown_not_zero():
    aid = _acct()
    f = _use()
    f.promo(93, [_fan(930_001, data=False), _fan(930_002, data=False)])
    _promos(aid)
    _run_spawned()
    _tx(aid, 930_001, "tip", 1000, datetime.utcnow() + timedelta(days=1))
    _, by = _promos(aid)
    m = by[93]["metrics"]
    assert m["earnings_cents"] is None and m["claimers"] == 2 and m["spend_unknown"] == 2, m
    d = _fans(aid, "promo", 93)
    x = d["fans"][0]
    assert x["subscribe_at"] is None and x["first_seen_at"] and x["since"] is None and x["lifetime"] is None


def case_promo_claimers_read_the_captured_shape():
    """The captured promotion claimers (offer-fans-promo.json, synthetic values): subscribeAt and the lifetime
    sums come through for a promo fan; the row without subscribedOnData falls back to first-seen, "—"."""
    import json
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "app", "lib", "__fixtures__", "of",
                                     "offer-fans-promo.json")))
    aid = _acct()
    f = _use()
    pid = fx["request"]["of"]["params"][0]["filter[promoId]"]
    f.promo(pid, [u for p in fx["pages"] for u in p["list"]])
    f.has_more = False
    _promos(aid)
    _run_spawned()
    d = _fans(aid, "promo", pid, count=fx["totals"]["fans"])
    row = {x["fan_id"]: x for x in d["fans"]}
    assert len(row) == fx["totals"]["fans"] == 3, row
    a = row[71_000_001]
    assert a["subscribe_at"] == "2026-08-04T09:30:00Z", a
    assert a["lifetime"] == {"total_cents": 1250, "subs_cents": 0, "posts_cents": 0, "messages_cents": 750,
                             "streams_cents": 0, "tips_cents": 500}, a["lifetime"]
    assert a["since"] is not None and a["since"]["total_cents"] == 0, "has a claim time: $0 since, not '—'"
    assert sum((x["lifetime"] or {}).get("total_cents", 0) for x in d["fans"]) == round(fx["totals"]["total"] * 100)
    c = row[71_000_003]
    assert c["subscribe_at"] is None and c["first_seen_at"] and c["lifetime"] is None and c["since"] is None, c


def case_zero_claims_is_zero_not_dash_and_not_walked():
    aid = _acct()
    f = _use()
    f.trial(95, [])
    _trials(aid)
    _run_spawned()
    assert f.claim_calls == [], "a link with no claims costs no OF call"
    d = _fans(aid, "trial", 95, count=0)
    assert d["fans"] == [] and f.claim_calls == []


# ── Promo cost, Source, Tag ──

def _put(**body):
    return _client.put("/admin/link-meta", json=body)


def case_link_meta_save_and_suggestions():
    aid = _acct()
    f = _use()
    f.trial(101, [])
    r = _put(account_id=aid, kind="trial", of_id=101, promo_cost=12.5, source="  Reddit ",
             tags=["Spring", "spring", " ", "Ads"])
    assert r.status_code == 200, r.text
    assert r.json() == {"kind": "trial", "of_id": 101, "promo_cost_cents": 1250,
                        "link_source": "Reddit", "tags": ["Spring", "Ads"], "list_id": None, "list_name": None}, r.json()
    assert _put(account_id=aid, kind="campaign", of_id=555, source="Twitter", tags=["ads"]).status_code == 200
    d, by = _trials(aid)
    assert by[101]["promo_cost_cents"] == 1250 and by[101]["link_source"] == "Reddit"
    assert by[101]["source"] == "onlyfans", "the row's own `source` (mirror/onlyfans) is untouched"
    assert d["sources"] == ["Reddit", "Twitter"] and d["tags"] == ["Ads", "Spring"], d
    # Clearing: no cost, blank source, no tags.
    r = _put(account_id=aid, kind="trial", of_id=101, promo_cost=None, source=" ", tags=[])
    assert r.json()["promo_cost_cents"] is None and r.json()["link_source"] is None and r.json()["tags"] == []


def case_link_meta_validation():
    aid = _acct()
    ok = {"account_id": aid, "kind": "trial", "of_id": 7}
    for bad in ({"kind": "promo"}, {"kind": "tracking"}, {"of_id": 0}, {"promo_cost": -1},
                {"promo_cost": 100_000_000}, {"source": "x" * 101}, {"tags": ["x" * 101]},
                {"tags": [f"t{i}" for i in range(21)]}, {"list_id": "12a"}, {"list_id": "1" * 21},
                {"list_name": "x" * 65}):
        r = _put(**{**ok, **bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert _put(**{**ok, "promo_cost": 99_999_999.99}).json()["promo_cost_cents"] == 9_999_999_999


def case_link_meta_batch_sets_only_the_fields_sent():
    aid, other = _acct(), _acct()
    _put(account_id=aid, kind="trial", of_id=201, promo_cost=5, source="Reddit", tags=["a"], list_id="77",
         list_name="VIP")
    _put(account_id=other, kind="trial", of_id=201, source="Theirs")
    batch = lambda **b: _client.put("/admin/link-meta/batch", json={"account_id": aid, "kind": "trial", **b})
    r = batch(of_ids=[201, 202, 202], source=" Twitter ")
    assert r.status_code == 200 and r.json() == {"kind": "trial", "of_ids": [201, 202], "fields": ["source"]}, r.text
    m = _meta(aid, "trial", 201)
    assert m.source == "Twitter" and m.promo_cost_cents == 500 and m.tags_json == '["a"]', "only Source changed"
    assert m.list_id == "77" and m.list_name == "VIP", "the List is never batch-edited"
    assert _meta(aid, "trial", 202).source == "Twitter"
    assert _meta(other, "trial", 201).source == "Theirs", "per account"
    assert batch(of_ids=[201], promo_cost=None, tags=[]).json()["fields"] == ["promo_cost", "tags"]
    m = _meta(aid, "trial", 201)
    assert m.promo_cost_cents is None and m.tags_json is None and m.source == "Twitter"
    assert _meta(aid, "campaign", 201) is None
    for bad in ({"of_ids": [201]}, {"of_ids": [], "source": "x"}, {"of_ids": [0], "source": "x"},
                {"of_ids": [201], "kind": "promo", "source": "x"}, {"of_ids": [201], "promo_cost": -1},
                {"of_ids": [201], "list_id": "5"}, {"of_ids": list(range(1, 502)), "source": "x"}):
        r = batch(**bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)


def case_tracking_list_carries_link_meta():
    import of_tracking_api

    class Track(FakeOF):
        def me(self):
            return {"username": "creator"}

        def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
            return {"list": [{"id": 4242, "campaignCode": 1, "campaignName": "IG",
                              "countTransitions": 10, "countSubscribers": 2}][offset:], "hasMore": False}
    aid = _acct()
    _use(Track())
    of_tracking_api._COMPUTED.clear()
    _put(account_id=aid, kind="campaign", of_id=4242, promo_cost=20, source="IG", tags=["bio"])
    r = _client.get(f"/admin/of-tracking-links?account_id={aid}")
    row = r.json()["links"][0]
    assert row["promo_cost_cents"] == 2000 and row["link_source"] == "IG" and row["tags"] == ["bio"], row
    assert r.json()["sources"] == ["IG"]


# ── List: OF's add-to-list ──

def case_add_to_list_paths_are_ofs():
    """The URLs OF answered live (2026-10-18 campaign, 2026-10-19 trial and
    promo: .scratch/growth-followup/capture.md); replies scrubbed."""
    import of_client
    posted = []
    replies = iter([{"count": 1}, {"count": 1}, {"count": 2}])   # a repeat answers {"count": 0}
    me = type("C", (), {"post_json": lambda self, path: posted.append(path) or next(replies)})()
    add = of_client.OFClient.add_link_claimers_to_list
    assert add(me, "900051", "campaign", 4343) == {"count": 1}
    assert add(me, 900051, "trial", 21) == {"count": 1}
    assert add(me, "900051", "promo", 72) == {"count": 2}
    base = of_client.API_BASE
    assert posted == [f"{base}/lists/900051/users/campaign/4343/claimers", f"{base}/lists/900051/users/trial/21/claims",
                      f"{base}/lists/900051/users/promo/72/claims"], posted
    for bad in (("fans", "campaign", 1), ("1/../2", "campaign", 1), ("9", "tracking", 1)):
        try:
            add(me, *bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} must be refused")
    assert len(posted) == 3


def case_list_first_save_adds_once_then_only_when_the_count_grows():
    aid = _acct()
    f = _use()
    f.trial(201, [_fan(950_001), _fan(950_002), _fan(950_003)])
    _trials(aid)
    _run_spawned()
    r = _put(account_id=aid, kind="trial", of_id=201, list_id="900001", list_name=" VIP ")
    assert r.status_code == 200 and r.json()["list_id"] == "900001" and r.json()["list_name"] == "VIP", r.text
    assert len(_spawned) == 1 and f.list_calls == [], "the add runs in the background, not in the save"
    _run_spawned()
    assert f.list_calls == [("900001", "trial", 201)], f.list_calls
    assert _meta(aid, "trial", 201).list_added_count == 3
    _put(account_id=aid, kind="trial", of_id=201, list_id="900001", list_name="VIP", source="Reddit")
    assert not _spawned, "saving the same List again adds nobody"
    _, by = _trials(aid)
    assert by[201]["list_name"] == "VIP" and by[201]["list_id"] == "900001"
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert len(f.list_calls) == 1, "same count: no OF call"
    f.claimers[("trial", 201)].append(_fan(950_004))
    f.count("trial", 201, 4)
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert f.list_calls == [("900001", "trial", 201)] * 2, f.list_calls
    assert _meta(aid, "trial", 201).list_added_count == 4
    # Another List: one add to it; cleared: no more adds.
    _put(account_id=aid, kind="trial", of_id=201, list_id="900002", list_name="Whales")
    _run_spawned()
    assert f.list_calls[-1] == ("900002", "trial", 201) and len(f.list_calls) == 3
    _put(account_id=aid, kind="trial", of_id=201, list_id=None)
    m = _meta(aid, "trial", 201)
    assert m.list_id is None and m.list_name is None and not _spawned
    f.claimers[("trial", 201)].append(_fan(950_005))
    f.count("trial", 201, 5)
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert len(f.list_calls) == 3, "no List: no add"


def case_list_changed_during_its_first_add_is_added_to_the_new_list():
    aid = _acct()
    f = _use()
    f.trial(205, [_fan(950_101), _fan(950_102)])
    _trials(aid)
    _run_spawned()
    real = f.add_link_claimers_to_list

    def add_then_change(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if len(f.list_calls) == 1:
            r = _put(account_id=aid, kind="trial", of_id=205, list_id="900032", list_name="New")
            assert r.status_code == 200, r.text
        return out
    f.add_link_claimers_to_list = add_then_change
    _put(account_id=aid, kind="trial", of_id=205, list_id="900031", list_name="Old")
    _run_spawned()
    assert f.list_calls == [("900031", "trial", 205), ("900032", "trial", 205)], f.list_calls
    m = _meta(aid, "trial", 205)
    assert (m.list_id, m.list_added_count) == ("900032", 2), (m.list_id, m.list_added_count)


def case_list_cleared_during_another_links_add_makes_no_add_to_the_old_list():
    aid = _acct()
    f = _use()
    f.trial(206, [_fan(950_201)])
    f.trial(207, [_fan(950_301)])
    _trials(aid)
    _run_spawned()
    _put(account_id=aid, kind="trial", of_id=206, list_id="900041", list_name="A")
    _put(account_id=aid, kind="trial", of_id=207, list_id="900042", list_name="B")
    _run_spawned()
    assert sorted(f.list_calls) == [("900041", "trial", 206), ("900042", "trial", 207)], f.list_calls
    # Both grow: the refresh's pass is due on both; the first add clears the other link's List.
    f.claimers[("trial", 206)].append(_fan(950_202))
    f.claimers[("trial", 207)].append(_fan(950_302))
    f.count("trial", 206, 2)
    f.count("trial", 207, 2)
    f.list_calls.clear()
    real = f.add_link_claimers_to_list
    cleared = []

    def add_then_clear_the_other(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if not cleared:
            other = 207 if int(link_id) == 206 else 206
            assert _put(account_id=aid, kind="trial", of_id=other, list_id=None).status_code == 200
            cleared.append(other)
        return out
    f.add_link_claimers_to_list = add_then_clear_the_other
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert len(f.list_calls) == 1 and f.list_calls[0][2] != cleared[0], f"no add for the cleared List: {f.list_calls}"
    assert _meta(aid, "trial", cleared[0]).list_id is None


def case_a_save_after_the_task_took_the_lock_keeps_its_queue_mark():
    """A save during a first add (or a promo pass) queues its own; the running task's cleanup must not drop that
    mark, or one more save before it runs would queue a second, duplicate task."""
    aid = _acct()
    f = _use()
    f.trial(208, [_fan(950_401)])
    _trials(aid)
    _run_spawned()
    real = f.add_link_claimers_to_list

    def add_then_save(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if len(f.list_calls) == 1:
            assert _put(account_id=aid, kind="trial", of_id=208, list_id="900052", list_name="B").status_code == 200
        return out
    f.add_link_claimers_to_list = add_then_save
    _put(account_id=aid, kind="trial", of_id=208, list_id="900051", list_name="A")
    asyncio.run(_spawned.pop(0))             # the first add only; the save it made is queued
    assert (aid, "trial", 208) in lm._LIST_QUEUED and len(_spawned) == 1, (lm._LIST_QUEUED, _spawned)
    _put(account_id=aid, kind="trial", of_id=208, list_id="900053", list_name="C")
    assert len(_spawned) == 1, "already queued: no second task"
    _run_spawned()
    assert f.list_calls == [("900051", "trial", 208), ("900053", "trial", 208)], f.list_calls
    # The promotion List's pass, the same way.
    f.add_link_claimers_to_list = real
    f.list_calls.clear()
    f.promo(311, [_fan(950_501)])
    _promos(aid)
    _run_spawned()

    def pass_then_save(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if len(f.list_calls) == 1:
            assert _promo_list(aid, enabled=True, list_id="900062", list_name="Q").status_code == 200
        return out
    f.add_link_claimers_to_list = pass_then_save
    _promo_list(aid, enabled=True, list_id="900061", list_name="P")
    asyncio.run(_spawned.pop(0))
    assert (aid, "promo", 0) in lm._LIST_QUEUED and len(_spawned) == 1, (lm._LIST_QUEUED, _spawned)
    _promo_list(aid, enabled=True, list_id="900063", list_name="R")
    assert len(_spawned) == 1, "already queued: no second pass"
    _run_spawned()
    assert f.list_calls == [("900061", "promo", 311), ("900063", "promo", 311)], f.list_calls


def case_list_of_error_stops_the_pass_and_backs_off():
    aid = _acct()
    f = _use()
    f.trial(211, [_fan(951_001)])
    f.trial(212, [_fan(951_002)])
    _trials(aid)
    _run_spawned()
    f.list_fail = True
    _put(account_id=aid, kind="trial", of_id=211, list_id="900011", list_name="A")
    _put(account_id=aid, kind="trial", of_id=212, list_id="900012", list_name="B")
    _run_spawned()
    assert len(f.list_calls) == 1, f"the first error backs the account off: {f.list_calls}"
    assert aid in lm._LIST_FAILED_AT and _meta(aid, "trial", 211).list_added_count is None, "still due"

    async def sync():
        return await lm.sync_lists(aid, "trial", f, {211: 1, 212: 1})
    assert asyncio.run(sync()) == 0 and len(f.list_calls) == 1, "inside the back-off: no call"
    # Past the back-off, a refresh's pass stops on the first error (no storm), and backs off again.
    lm._LIST_FAILED_AT.clear()
    _age_checks(aid, 61)
    _trials(aid)
    _run_spawned()
    assert len(f.list_calls) == 2, f.list_calls
    assert (aid, "trial") in lm._FAILED_AT and aid in lm._LIST_FAILED_AT
    _trials(aid)
    assert not _spawned, "the refresh backs off too"
    # OF answers again: both are added, paced, one call each.
    f.list_fail = False
    lm._LIST_FAILED_AT.clear()

    async def sync2():
        async with lm._lock(aid):
            return await lm.sync_lists(aid, "trial", None, {211: 1, 212: 1})
    assert asyncio.run(sync2()) == 2 and [c[2] for c in f.list_calls[-2:]] == [211, 212], f.list_calls
    lm._LOCKS.pop(aid, None)


def case_list_on_a_tracking_link_follows_its_subscribers():
    import of_tracking_api

    class Track(FakeOF):
        subs = 2

        def me(self):
            return {"username": "creator"}

        def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
            return {"list": [{"id": 4343, "campaignCode": 1, "campaignName": "IG",
                              "countTransitions": 10, "countSubscribers": self.subs}][offset:], "hasMore": False}
    aid = _acct()
    f = _use(Track())
    of_tracking_api._COMPUTED.clear()
    of_tracking_api._CLAIMERS_CACHE.clear()
    _put(account_id=aid, kind="campaign", of_id=4343, list_id="900021", list_name="IG fans")
    _run_spawned()
    assert f.list_calls == [("900021", "campaign", 4343)], "the save's first add"
    row = _client.get(f"/admin/of-tracking-links?account_id={aid}").json()["links"][0]
    assert row["list_id"] == "900021" and row["list_name"] == "IG fans", row
    earnings = f"/admin/of-tracking-links/earnings?account_id={aid}"
    _client.get(earnings)          # 2 subscribers > the 0 known at the save: one more add
    assert len(f.list_calls) == 2 and _meta(aid, "campaign", 4343).list_added_count == 2, f.list_calls
    of_tracking_api._COMPUTED.clear()
    _client.get(earnings)
    assert len(f.list_calls) == 2, "same subscriber count: no add"
    f.subs = 3
    of_tracking_api._COMPUTED.clear()
    _client.get(earnings)
    assert len(f.list_calls) == 3 and _meta(aid, "campaign", 4343).list_added_count == 3, f.list_calls
    of_tracking_api._COMPUTED.clear()


def case_create_stores_the_fields_for_the_new_link():
    import of_tracking_api

    class Track(FakeOF):
        reply: dict = {}

        def me(self):
            return {"username": "creator"}

        def create_tracking_link(self, *, name):
            return self.reply

        def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
            return {"list": [], "hasMore": False}
    aid = _acct()
    f = _use(Track())
    f.reply = {"id": 7777, "campaignCode": 5, "campaignName": "Reddit May"}
    r = _client.post("/admin/of-tracking-links", json={
        "account_id": aid, "name": "Reddit May", "promo_cost": 40, "source": " Reddit ", "tags": ["may", "May"],
        "list_id": "900031", "list_name": "Reddit"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["meta_saved"] is True and d["promo_cost_cents"] == 4000 and d["link_source"] == "Reddit", d
    assert d["tags"] == ["may"] and d["list_id"] == "900031" and d["list_name"] == "Reddit", d
    m = _meta(aid, "campaign", 7777)
    assert m.promo_cost_cents == 4000 and m.list_added_count == 0, "a new link has nobody to add yet"
    assert not _spawned and f.list_calls == []
    # Nothing to store: no row.
    f.reply = {"id": 7778, "campaignCode": 6, "campaignName": "Plain"}
    d = _client.post("/admin/of-tracking-links", json={"account_id": aid, "name": "Plain"}).json()
    assert d["meta_saved"] is True and d["promo_cost_cents"] is None and _meta(aid, "campaign", 7778) is None
    # OF's reply without an id: created, fields not saved, and said so.
    f.reply = {}
    d = _client.post("/admin/of-tracking-links", json={"account_id": aid, "name": "Lost", "source": "X"}).json()
    assert d["meta_saved"] is False, d
    # A bad field is refused before OF creates anything.
    created = []
    f.create_tracking_link = lambda *, name: created.append(name) or {"id": 1}
    r = _client.post("/admin/of-tracking-links", json={"account_id": aid, "name": "Bad", "tags": ["x" * 101]})
    assert r.status_code == 422 and created == [], r.text
    del f.create_tracking_link
    # Per account: the create is gated on the account it names.
    seen = []
    real = of_tracking_api.assert_account_owned
    of_tracking_api.assert_account_owned = seen.append
    try:
        f.reply = {"id": 7779}
        _client.post("/admin/of-tracking-links", json={"account_id": aid, "name": "Gate", "source": "Y"})
    finally:
        of_tracking_api.assert_account_owned = real
    assert seen == [aid] and _meta(aid, "campaign", 7779).source == "Y"


def case_trial_create_stores_the_fields_for_the_new_link():
    import trial_links_api

    class Trials(FakeOF):
        reply: dict = {}
        created: list = []

        def create_trial_link(self, *, name, subscribe_days, subscribe_counts, expired_at=None, expire_days=None):
            self.created.append(name)
            return self.reply
    aid = _acct()
    f = _use(Trials())
    f.created = []
    f.reply = {"id": 8801, "trialLinkName": "Reddit May", "url": "https://of/t8801", "claimCounts": 0}
    r = _client.post("/admin/trial-links", json={
        "account_id": aid, "name": "Reddit May", "subscribe_days": 7, "promo_cost": 25.5, "source": " Reddit ",
        "tags": ["may", "May"], "list_id": "900091", "list_name": "Reddit"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["of_trial_id"] == 8801 and d["meta_saved"] is True, d
    assert d["promo_cost_cents"] == 2550 and d["link_source"] == "Reddit" and d["tags"] == ["may"], d
    assert d["list_id"] == "900091" and d["list_name"] == "Reddit", d
    m = _meta(aid, "trial", 8801)
    assert m.promo_cost_cents == 2550 and m.list_id == "900091" and m.list_added_count == 0, \
        "a new link has nobody to add yet: its first claim brings the first add"
    assert not _spawned and f.list_calls == []
    _, by = _trials(aid)
    _drop_spawned()
    assert by[8801]["link_source"] == "Reddit" and by[8801]["list_name"] == "Reddit", by[8801]
    # Nothing to store: no row, still meta_saved.
    f.reply = {"id": 8802, "trialLinkName": "Plain"}
    d = _client.post("/admin/trial-links", json={"account_id": aid, "name": "Plain"}).json()
    assert d["meta_saved"] is True and d["promo_cost_cents"] is None and d["list_id"] is None, d
    assert _meta(aid, "trial", 8802) is None
    # OF's reply without an id: created, the fields not saved, and said so; no row.
    f.reply = {}
    d = _client.post("/admin/trial-links", json={"account_id": aid, "name": "Lost", "source": "X",
                                                 "list_id": "900092"}).json()
    assert d["meta_saved"] is False and d["of_trial_id"] is None, d
    # A bad field is refused before OF creates anything.
    n = len(f.created)
    for bad in ({"tags": ["x" * 101]}, {"promo_cost": -1}, {"list_id": "12a"}, {"source": "x" * 101}):
        r = _client.post("/admin/trial-links", json={"account_id": aid, "name": "Bad", **bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert len(f.created) == n, "no OF call for a refused body"
    # Gated on the account it names, before OF.
    seen = []
    real = trial_links_api.assert_account_owned
    trial_links_api.assert_account_owned = seen.append
    try:
        f.reply = {"id": 8803}
        _client.post("/admin/trial-links", json={"account_id": aid, "name": "Gate", "source": "Y"})
    finally:
        trial_links_api.assert_account_owned = real
    assert seen == [aid] and _meta(aid, "trial", 8803).source == "Y"


def case_trial_create_for_another_agency_is_refused_before_onlyfans():
    import _agency_fixtures as fx
    ids = fx.seed_two_agencies()

    class Trials(FakeOF):
        created: list = []

        def create_trial_link(self, **kw):
            self.created.append(kw)
            return {"id": 8890}
    f = _use(Trials())
    f.created = []
    owner_b = fx.login_owner("agency_b_owner")
    r = owner_b.post("/admin/trial-links", json={"account_id": ids["creator_a"], "name": "X", "source": "S"})
    assert r.status_code in (403, 404), (r.status_code, r.text)
    assert f.created == [] and _meta(ids["creator_a"], "trial", 8890) is None


# ── Profile promotion: "Add fans to list" (account-level) ──

def _promo_list(aid, **body):
    return _client.put("/admin/promo-list", json={"account_id": aid, **body})


def _promo_setup(aid, f):
    f.promo(301, [_fan(954_001), _fan(954_002)])
    f.promo(302, [])
    f.promo(303, [_fan(954_003)])
    _promos(aid)
    _run_spawned()


def _refresh_promos(aid):
    _age_checks(aid, 61)
    _promos(aid)
    _run_spawned()


def case_promo_list_off_adds_nothing():
    aid = _acct()
    f = _use()
    _promo_setup(aid, f)
    assert _client.get(f"/admin/promo-list?account_id={aid}").json() == {
        "enabled": False, "list_id": None, "list_name": None}
    f.claimers[("promo", 301)].append(_fan(954_004))
    f.count("promo", 301, 3)
    _refresh_promos(aid)
    assert f.list_calls == [], "no setting: no add"
    r = _promo_list(aid, enabled=False, list_id="900061", list_name="Promo fans")
    assert r.status_code == 200 and r.json()["enabled"] is False and not _spawned, r.text
    _refresh_promos(aid)
    assert f.list_calls == [], "a list picked but switched off: no add"


def case_promo_list_on_adds_each_promotion_once_then_on_growth_and_on_a_new_list():
    aid = _acct()
    f = _use()
    _promo_setup(aid, f)
    r = _promo_list(aid, enabled=True, list_id="900061", list_name=" Promo fans ")
    assert r.status_code == 200 and r.json() == {"enabled": True, "list_id": "900061", "list_name": "Promo fans"}
    assert len(_spawned) == 1 and f.list_calls == [], "the add runs in the background, not in the save"
    _run_spawned()
    assert sorted(f.list_calls) == [("900061", "promo", 301), ("900061", "promo", 303)], \
        f"one add per promotion with claims, none for 0: {f.list_calls}"
    assert _meta(aid, "promo", 301).list_added_count == 2 and _meta(aid, "promo", 303).list_added_count == 1
    assert _client.get(f"/admin/promo-list?account_id={aid}").json()["list_id"] == "900061"
    _promo_list(aid, enabled=True, list_id="900061", list_name="Promo fans")
    assert not _spawned, "saving the same list again adds nobody"
    _refresh_promos(aid)
    assert len(f.list_calls) == 2, "same counts: no OF call"
    f.claimers[("promo", 301)].append(_fan(954_004))
    f.count("promo", 301, 3)
    _refresh_promos(aid)
    assert f.list_calls[2:] == [("900061", "promo", 301)], f"the count grew: one more: {f.list_calls}"
    # Another list: each promotion with claims goes in once.
    _promo_list(aid, enabled=True, list_id="900062", list_name="Whales")
    _run_spawned()
    assert sorted(f.list_calls[3:]) == [("900062", "promo", 301), ("900062", "promo", 303)], f.list_calls
    _refresh_promos(aid)
    assert len(f.list_calls) == 5, "nothing grew: no add"
    # Off: new claims add nobody.
    _promo_list(aid, enabled=False, list_id=None)
    assert not _spawned
    f.claimers[("promo", 303)].append(_fan(954_005))
    f.count("promo", 303, 2)
    _refresh_promos(aid)
    assert len(f.list_calls) == 5, "off: no add"
    # On again with the same list: only what grew while off. A new (re-armed) promotion: on its first walk.
    _promo_list(aid, enabled=True, list_id="900062", list_name="Whales")
    _run_spawned()
    assert f.list_calls[5:] == [("900062", "promo", 303)], f.list_calls
    f.promo(304, [_fan(954_006)])
    _refresh_promos(aid)
    assert f.list_calls[6:] == [("900062", "promo", 304)], f.list_calls
    assert _meta(aid, "promo", 304).list_added_count == 1


def case_promo_list_of_error_stops_the_pass_and_backs_off():
    aid = _acct()
    f = _use()
    _promo_setup(aid, f)
    f.list_fail = True
    _promo_list(aid, enabled=True, list_id="900071", list_name="P")
    _run_spawned()
    assert len(f.list_calls) == 1, f"the first error stops the pass: {f.list_calls}"
    assert aid in lm._LIST_FAILED_AT
    assert {_meta(aid, "promo", o).list_added_count for o in (301, 303)} == {None}, "both still due"
    _refresh_promos(aid)
    assert len(f.list_calls) == 1, "inside the back-off: no call"
    f.list_fail = False
    lm._LIST_FAILED_AT.clear()
    _refresh_promos(aid)
    assert sorted(f.list_calls[1:]) == [("900071", "promo", 301), ("900071", "promo", 303)], f.list_calls


def case_promo_list_saved_mid_pass_stops_adds_to_the_old_list():
    """Off (or another list) saved while a pass is adding: the rest of that pass adds nobody to the old list."""
    aid = _acct()
    f = _use()
    _promo_setup(aid, f)
    _promo_list(aid, enabled=True, list_id="900071", list_name="P")
    real = f.add_link_claimers_to_list

    def add_then_switch_off(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if len(f.list_calls) == 1:
            r = _promo_list(aid, enabled=False, list_id="900071", list_name="P")
            assert r.status_code == 200, r.text
        return out
    f.add_link_claimers_to_list = add_then_switch_off
    _run_spawned()
    assert len(f.list_calls) == 1, f"turned off after the first add: {f.list_calls}"
    # Back on with another list mid-pass: the remaining promotion goes to the new list only.
    f.list_calls.clear()

    def add_then_switch_list(list_id, kind, link_id):
        out = real(list_id, kind, link_id)
        if len(f.list_calls) == 1:
            assert _promo_list(aid, enabled=True, list_id="900072", list_name="Q").status_code == 200
        return out
    f.add_link_claimers_to_list = add_then_switch_list
    _promo_list(aid, enabled=True, list_id="900071", list_name="P")
    _run_spawned()
    old = [c for c in f.list_calls if c[0] == "900071"]
    new = sorted(c for c in f.list_calls if c[0] == "900072")
    assert len(old) == 1, f"the old list stops after the switch: {f.list_calls}"
    assert new == [("900072", "promo", 301), ("900072", "promo", 303)], f"the new list gets every promotion: {f.list_calls}"


def case_promo_list_validation():
    aid = _acct()
    _use()
    for bad in ({"enabled": True}, {"enabled": True, "list_id": ""}, {"enabled": True, "list_id": "12a"},
                {"list_id": "1" * 21}, {"list_id": "5", "list_name": "x" * 65}):
        r = _promo_list(aid, **bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert not _spawned
    d = _promo_list(aid, enabled=False, list_id=None, list_name="orphan").json()
    assert d == {"enabled": False, "list_id": None, "list_name": None}, d


def case_promo_list_is_per_account():
    import _agency_fixtures as fx
    ids = fx.seed_two_agencies()
    a, b = ids["creator_a"], ids["creator_b"]
    _use()
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    r = owner_a.put("/admin/promo-list", json={"account_id": a, "enabled": True, "list_id": "900081",
                                               "list_name": "A"})
    assert r.status_code == 200, r.text
    _drop_spawned()
    for r in (owner_b.get(f"/admin/promo-list?account_id={a}"),
              owner_b.put("/admin/promo-list", json={"account_id": a, "enabled": False})):
        assert r.status_code in (403, 404), (r.status_code, r.text)
    assert owner_b.get(f"/admin/promo-list?account_id={b}").json()["enabled"] is False, "b's own: off"
    assert owner_a.get(f"/admin/promo-list?account_id={a}").json()["list_id"] == "900081", "a's is untouched"

    async def sync():
        async with lm._lock(b):
            return await lm.sync_lists(b, "promo", FakeOF(), {301: 5})
    assert asyncio.run(sync()) == 0, "b's pass never reads a's setting"
    lm._LOCKS.pop(b, None)
    # Each on its own list, with the same OnlyFans promotion ids: every add carries its own account's list.
    fa, fb = FakeOF(), FakeOF()
    for fk in (fa, fb):
        fk.list_calls = []
        fk.promo(301, [_fan(955_001), _fan(955_002)])
        fk.promo(302, [_fan(955_003)])
    ax._make_client = lambda account_id: {a: fa, b: fb}[account_id]  # type: ignore[attr-defined]
    r = owner_b.put("/admin/promo-list", json={"account_id": b, "enabled": True, "list_id": "900082", "list_name": "B"})
    assert r.status_code == 200, r.text
    _run_spawned()
    for owner, acct in ((owner_a, a), (owner_b, b)):
        assert owner.get(f"/admin/promotions?account_id={acct}").status_code == 200
    _run_spawned()
    assert sorted(fa.list_calls) == [("900081", "promo", 301), ("900081", "promo", 302)], fa.list_calls
    assert sorted(fb.list_calls) == [("900082", "promo", 301), ("900082", "promo", 302)], fb.list_calls


# ── Lifetime: a stale walk ──

def case_stale_lifetime_rewalks_once_in_the_background():
    aid = _acct()
    f = _use()
    f.trial(221, [_fan(952_001, _T0, total=5)])
    d = _fans(aid, "trial", 221, count=1)
    assert d["refreshing"] is False and len(f.claim_calls) == 1
    d = _fans(aid, "trial", 221, count=1)
    assert d["refreshing"] is False and not _spawned and len(f.claim_calls) == 1, "fresh: the cache"
    # Past an hour, same count: the cache now, one walk in the background, the page polls.
    f.claimers[("trial", 221)] = [_fan(952_001, _T0 + timedelta(days=3), total=17)]
    _age_walks(aid, 61)
    d = _fans(aid, "trial", 221, count=1)
    assert d["refreshing"] is True and d["fans"][0]["lifetime"]["total_cents"] == 500, d
    assert len(_spawned) == 1 and len(f.claim_calls) == 1, "not walked in the request"
    d = _fans(aid, "trial", 221, count=1)
    assert d["refreshing"] is True and len(_spawned) == 1, "queued once"
    _run_spawned()
    assert len(f.claim_calls) == 2
    d = _fans(aid, "trial", 221, count=1)
    x = d["fans"][0]
    assert d["refreshing"] is False and x["lifetime"]["total_cents"] == 1700, "Lifetime follows OF"
    assert x["subscribe_at"] == _iso(_T0), "subscribeAt is kept from first sight"


def _iso(dt):
    return dt.isoformat() + "Z"


def case_stale_rewalk_not_while_locked_or_backed_off():
    aid = _acct()
    f = _use()
    f.trial(231, [_fan(953_001)])
    _fans(aid, "trial", 231, count=1)
    _age_walks(aid, 61)

    async def hold():
        await lm._lock(aid).acquire()
    asyncio.run(hold())
    d = _fans(aid, "trial", 231, count=1)
    assert d["refreshing"] is False and not _spawned and len(f.claim_calls) == 1, "a walk holds the lock: no second"
    lm._LOCKS.pop(aid, None)
    import time
    lm._FAILED_AT[(aid, "trial")] = time.monotonic()
    d = _fans(aid, "trial", 231, count=1)
    assert d["refreshing"] is False and not _spawned, "inside the back-off: no walk"
    lm._FAILED_AT.clear()
    f.fail.add(("trial", 231))
    d = _fans(aid, "trial", 231, count=1)
    assert d["refreshing"] is True and len(_spawned) == 1
    _run_spawned()
    assert (aid, "trial") in lm._FAILED_AT and not lm._REWALKING, "a failed re-walk backs off, then frees the link"
    d = _fans(aid, "trial", 231, count=1)
    assert d["refreshing"] is False and [x["fan_id"] for x in d["fans"]] == [953_001], "the cache stays"


# ── Per account ──

def case_accounts_never_mix():
    a1, a2 = _acct(), _acct()
    f = _use()
    f.trial(111, [_fan(940_001, _T0)])
    _trials(a1)
    _run_spawned()
    _tx(a1, 940_001, "tip", 1000, _T0 + timedelta(days=1))
    _tx(a2, 940_001, "tip", 9000, _T0 + timedelta(days=1))
    _put(account_id=a1, kind="trial", of_id=111, promo_cost=5, source="Mine", tags=["a1"], list_id="900041")
    _run_spawned()
    assert f.list_calls == [("900041", "trial", 111)]
    _, by1 = _trials(a1)
    assert by1[111]["metrics"]["earnings_cents"] == 1000, "only the account's own ledger"
    _drop_spawned()
    d2, by2 = _trials(a2)
    assert by2[111]["metrics"]["earnings_cents"] is None, "a2 has not walked the link: '—'"
    assert by2[111]["promo_cost_cents"] is None and d2["sources"] == [] and d2["tags"] == []
    assert by2[111]["list_id"] is None, "a1's List is not a2's"

    async def sync():
        async with lm._lock(a2):
            return await lm.sync_lists(a2, "trial", f, {111: 9})
    assert asyncio.run(sync()) == 0 and len(f.list_calls) == 1, "a2's pass never adds a1's links"
    lm._LOCKS.pop(a2, None)
    seen = []
    real = lm.assert_account_owned
    lm.assert_account_owned = seen.append
    try:
        _fans(a2, "trial", 111, count=0)
        _put(account_id=a2, kind="trial", of_id=111)
    finally:
        lm.assert_account_owned = real
    assert seen == [a2, a2], seen


# ── Pre-warm ──

def case_prewarm_reads_every_kind_and_the_page_opens_from_cache():
    import time
    import of_tracking_api

    class Track(FakeOF):
        subs = 1
        campaign_calls: list[int] = []

        def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
            return {"list": [{"id": 4545, "campaignCode": 1, "campaignName": "IG", "createdAt": _of_time(_T0),
                              "countTransitions": 10, "countSubscribers": self.subs}][offset:], "hasMore": False}

        def campaign_claimers(self, campaign_id, *, limit=50, offset=0):
            self.campaign_calls.append(int(campaign_id))
            return {"list": [{"id": 950_001}][offset:], "hasMore": False}
    aid = _acct()
    f = _use(Track())
    f.campaign_calls = []
    of_tracking_api._COMPUTED.clear()
    of_tracking_api._CLAIMERS_CACHE.clear()
    f.trial(121, [_fan(950_002)])
    f.promo(122, [_fan(950_003)])

    async def seed():
        async with get_session() as s:
            c = PromoCampaign(account_id=aid, of_promo_id=122, name="Spring", discount_percent=50, status="active")
            s.add(c)
            await s.flush()
            return c.id
    cid = asyncio.run(seed())
    # A tracking link never read since boot waits for its page; trial and promo links are walked.
    asyncio.run(lm.prewarm(aid))
    assert f.campaign_calls == [], f.campaign_calls
    assert {c[:2] for c in f.claim_calls} == {("trial", 121), ("promo", 122)}, f.claim_calls
    assert _meta(aid, "promo", 122).campaign_id == cid, "a promotion walk keeps its campaign"
    d, by = _trials(aid)
    assert d["metrics_updated_at"] and d["metrics_refreshing"] is False and not _spawned, "the page reads the cache"
    assert by[121]["metrics"]["claimers"] == 1, by[121]["metrics"]
    d, _ = _promos(aid)
    assert d["metrics_updated_at"] and not _spawned
    # The page reads the tracking link's claimers once; past their TTL with the count unchanged,
    # a pass re-reads nothing (no trial / promo walk either) and the cache is renewed.
    asyncio.run(of_tracking_api._compute(aid))
    assert f.campaign_calls == [4545], f.campaign_calls
    key = (aid, 4545)
    n, _at, fans = of_tracking_api._CLAIMERS_CACHE[key]
    of_tracking_api._CLAIMERS_CACHE[key] = (n, time.monotonic() - 3 * of_tracking_api._CLAIMERS_TTL, fans)
    f.claim_calls.clear()
    f.campaign_calls.clear()
    asyncio.run(lm.prewarm(aid))
    assert f.claim_calls == [] and f.campaign_calls == [], (f.claim_calls, f.campaign_calls)
    assert time.monotonic() - of_tracking_api._CLAIMERS_CACHE[key][1] < 60, "a held count renews the cache"
    # A moved count is re-read.
    f.subs = 2
    asyncio.run(lm.prewarm(aid))
    assert f.campaign_calls == [4545], f.campaign_calls
    # A kind backed off by an OF failure is skipped, moved count or not.
    f.count("trial", 121, 2)
    lm._FAILED_AT[(aid, "trial")] = time.monotonic()
    asyncio.run(lm.prewarm(aid))
    assert not [c for c in f.claim_calls if c[0] == "trial"], f.claim_calls
    of_tracking_api._COMPUTED.clear()
    of_tracking_api._CLAIMERS_CACHE.clear()


def case_links_of_promos_folds_earlier_rearms_into_their_campaign():
    from types import SimpleNamespace
    fetched = [{"of_promo_id": 122, "subscriber_count": 3}, {"of_promo_id": 123, "subscriber_count": 2},
               {"of_promo_id": 124, "subscriber_count": "x"}, {"of_promo_id": None}]
    got = lm.links_of_promos(fetched, [SimpleNamespace(id=7, of_promo_id=122)], {7: [123]})
    assert got == [(122, 3, 7), (123, 2, 7), (124, 0, None)], got
    assert lm.links_of_trials([{"of_trial_id": 5, "claim_counts": 4}, {"of_trial_id": None}]) == [(5, 4, None)]


def case_prewarm_all_skips_dead_sessions_and_non_onlyfans_accounts():
    from account_health import mark_session_dead
    live, dead, fansly, none = _acct(), _acct(), _acct(), _acct()
    asyncio.run(mark_session_dead(dead, "test"))
    rows = [{"id": "first", "has_session": True, "platform": "onlyfans"},
            {"id": live, "has_session": True, "platform": "onlyfans"},
            {"id": dead, "has_session": True, "platform": "onlyfans"},
            {"id": fansly, "has_session": True, "platform": "fansly"},
            {"id": none, "has_session": False, "platform": "onlyfans"}]
    seen: list[str] = []

    async def fake_prewarm(aid):
        seen.append(aid)
        raise RuntimeError("one account failing must not stop the pass")
    real = (lm.account_registry.list_accounts, lm.prewarm, lm._PREWARM_SPREAD_S)
    lm.account_registry.list_accounts, lm.prewarm, lm._PREWARM_SPREAD_S = (lambda: rows), fake_prewarm, 0
    try:
        asyncio.run(lm.prewarm_all())
    finally:
        lm.account_registry.list_accounts, lm.prewarm, lm._PREWARM_SPREAD_S = real
    assert seen == ["first", live], seen


_harness.run(
    case_walk_moves_offset_by_page_past_a_short_page,
    case_walk_reads_a_20_row_page_then_a_short_page,
    case_walk_reads_the_captured_shape,
    case_walk_stops_on_has_more_false_and_on_short_page_past_count,
    case_walk_cannot_loop_on_an_ignored_offset,
    case_subscribe_at_is_kept_from_first_sight,
    case_rewalk_only_when_claim_count_moves,
    case_refresh_after_an_hour_once_and_backs_off_on_failure,
    case_refresh_waits_for_the_account_lock,
    case_details_while_locked_returns_cache_flagged,
    case_earnings_from_the_ledger_since_claim_without_refunds,
    case_fan_on_two_links_latest_claim_wins,
    case_promo_rearm_folds_into_one_campaign_row,
    case_claimer_without_subscribed_on_data_is_unknown_not_zero,
    case_promo_claimers_read_the_captured_shape,
    case_zero_claims_is_zero_not_dash_and_not_walked,
    case_link_meta_save_and_suggestions,
    case_link_meta_validation,
    case_link_meta_batch_sets_only_the_fields_sent,
    case_tracking_list_carries_link_meta,
    case_add_to_list_paths_are_ofs,
    case_list_first_save_adds_once_then_only_when_the_count_grows,
    case_list_changed_during_its_first_add_is_added_to_the_new_list,
    case_list_cleared_during_another_links_add_makes_no_add_to_the_old_list,
    case_a_save_after_the_task_took_the_lock_keeps_its_queue_mark,
    case_list_of_error_stops_the_pass_and_backs_off,
    case_list_on_a_tracking_link_follows_its_subscribers,
    case_create_stores_the_fields_for_the_new_link,
    case_trial_create_stores_the_fields_for_the_new_link,
    case_trial_create_for_another_agency_is_refused_before_onlyfans,
    case_promo_list_off_adds_nothing,
    case_promo_list_on_adds_each_promotion_once_then_on_growth_and_on_a_new_list,
    case_promo_list_of_error_stops_the_pass_and_backs_off,
    case_promo_list_saved_mid_pass_stops_adds_to_the_old_list,
    case_promo_list_validation,
    case_promo_list_is_per_account,
    case_stale_lifetime_rewalks_once_in_the_background,
    case_stale_rewalk_not_while_locked_or_backed_off,
    case_accounts_never_mix,
    case_prewarm_reads_every_kind_and_the_page_opens_from_cache,
    case_links_of_promos_folds_earlier_rearms_into_their_campaign,
    case_prewarm_all_skips_dead_sessions_and_non_onlyfans_accounts,
)
