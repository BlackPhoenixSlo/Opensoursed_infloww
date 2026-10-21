#!/usr/bin/env python3
"""Share links (link_share_api): a public read-only report on some of a
Creator's free trial links or tracking links, for 7 days. OF is faked.

Locks:
  • The report carries per link only the name, date created, OF's counts and,
    with "Include earnings", the net Earnings / Fans who spent / fans counted:
    no fan, no account id, no URL, cost, source or tag.
  • The URL's secret is checked (wrong secret or id: 404); revoked or expired:
    410; the public route reads its row and calls nothing (no OF client).
  • /share/ passes the share-token gate with no cookie; /admin/link-shares
    does not, and is owner-only (a chatter 403, another agency 403).
  • Create stores the rows pending (`ready` false); the owner's next read of
    the links fills them and every later one rebuilds them; a link no longer
    read keeps its last row, one never read is left out; a read with OF down
    rebuilds nothing; a revoked or expired share is left alone.
  • At most MAX_ACTIVE live shares per Creator.
  • No log keeps a share URL's secret (our access log, uvicorn's).

Run: ./venv/bin/python service/tests/test_link_share.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402
import link_metrics as lm  # noqa: E402
import link_share_api as lsa  # noqa: E402
import of_tracking_api as ot  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import LinkShare, Transaction  # noqa: E402

IDS = fx.seed_two_agencies()
AID = IDS["creator_a"]
_anon = _harness.make_client()
_owner = fx.login_owner("agency_a_owner")
_T0 = datetime(2026, 9, 1, 12, 0, 0)

_spawned: list = []
lm._spawn = _spawned.append        # the list's background refresh runs only when a case runs it


class FakeOF:
    def __init__(self):
        self.trials = [
            {"id": 501, "trialLinkName": "Reddit trial", "url": "https://of/t501", "claimCounts": 2,
             "clicksCounts": 40, "isFinished": False, "createdAt": "2026-09-01T00:00:00+00:00"},
            {"id": 502, "trialLinkName": "Other trial", "url": "https://of/t502", "claimCounts": 0,
             "clicksCounts": 3, "isFinished": False},
        ]
        self.fans = [
            {"id": 9001, "name": "Secret Fan", "username": "secretfan",
             "subscribedOnData": {"subscribeAt": _T0.isoformat() + "+00:00", "totalSumm": 8}},
            {"id": 9002, "name": "Quiet Fan", "username": "quietfan",
             "subscribedOnData": {"subscribeAt": _T0.isoformat() + "+00:00", "totalSumm": 0}},
        ]
        self.campaigns = [{"id": 7001, "campaignCode": 11, "campaignName": "IG bio", "countTransitions": 100,
                           "countSubscribers": 1, "createdAt": "2026-08-01T00:00:00+00:00"}]

    def me(self):
        return {"username": "creator"}

    def trial_links(self, *, offset=0, limit=100):
        return {"list": self.trials[offset:offset + limit], "hasMore": False}

    def offer_claims(self, offer_id, kind, *, limit=20, offset=0):
        return {"list": self.fans[offset:offset + limit] if int(offer_id) == 501 else [], "hasMore": False}

    def tracking_links(self, *, limit=None, offset=0, with_deleted=False):
        return {"list": self.campaigns[offset:], "hasMore": False}

    def campaign_claimers(self, campaign_id, *, limit=50, offset=0):
        return {"list": [{"id": 9001, "name": "Secret Fan", "username": "secretfan"}][offset:], "hasMore": False}


def _use() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    ot._COMPUTED.clear()
    ot._CLAIMERS_CACHE.clear()
    lm._REFRESHING.clear()
    lm._FAILED_AT.clear()
    while _spawned:
        _spawned.pop().close()
    return f


def _seed_spend():
    async def go():
        async with get_session() as s:
            s.add(Transaction(account_id=AID, fan_id=9001, kind="ppv_message", amount_cents=1000, net_cents=800,
                              occurred_at=_T0 + timedelta(days=1), status="cleared", currency="USD",
                              source="ledger"))
    asyncio.run(go())
    asyncio.run(lm.refresh(AID, "trial", [(501, 2, None), (502, 0, None)]))


_use()
_seed_spend()


def _read(kind="trial"):
    """The owner's read of the links, as the page makes it right after a create."""
    ot._COMPUTED.clear()
    path = "/admin/trial-links" if kind == "trial" else "/admin/of-tracking-links/earnings"
    assert _owner.get(f"{path}?account_id={AID}").status_code == 200


def _create(client=None, *, read=True, **body):
    body = {"account_id": AID, "kind": "trial", "name": "For Bob", "of_ids": [501], "include_earnings": True, **body}
    r = (client or _owner).post("/admin/link-shares", json=body)
    if read and r.status_code == 200:
        _read(body["kind"])
    return r


def _key(share: dict) -> str:
    return share["path"].removeprefix("/share/")


def _report(share: dict):
    return _anon.get(f"/share/{_key(share)}/data")


def _set(share_id: int, **values):
    async def go():
        async with get_session() as s:
            await s.execute(update(LinkShare).where(LinkShare.id == share_id).values(**values))
    asyncio.run(go())


# ── The report ──

def case_create_is_pending_until_the_owners_read():
    _use()
    r = _create(read=False, of_ids=[501, 999])
    assert r.status_code == 200, r.text
    share = r.json()
    assert share["status"] == "preparing" and share["updated_at"] is None, share
    d = _report(share).json()
    assert d["ready"] is False and d["links"] == [], d
    _read()
    d = _report(share).json()
    assert d["ready"] is True and [l["name"] for l in d["links"]] == ["Reddit trial"], "999 was never read: left out"
    # A share none of whose links the read returns stays pending, not "updated".
    lone = _create(of_ids=[999]).json()
    assert _report(lone).json()["ready"] is False
    listed = {s["id"]: s for s in _owner.get(f"/admin/link-shares?account_id={AID}&kind=trial").json()["shares"]}
    assert listed[lone["id"]]["status"] == "preparing" and listed[lone["id"]]["updated_at"] is None


def case_report_has_link_figures_and_no_fan():
    _use()
    r = _create()
    assert r.status_code == 200, r.text
    share = r.json()
    assert share["status"] == "preparing" and share["of_ids"] == [501] and share["include_earnings"] is True
    exp = datetime.fromisoformat(share["expires_at"].rstrip("Z")) - datetime.fromisoformat(share["created_at"].rstrip("Z"))
    assert exp == timedelta(days=7), exp
    r = _report(share)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["name"] == "For Bob" and d["kind"] == "trial" and d["include_earnings"] is True
    row = d["links"][0]
    assert set(row) == {"name", "created_at", "claims", "clicks", "earnings_cents", "fans_who_spent",
                        "fans_counted"}, row
    assert row["name"] == "Reddit trial" and row["claims"] == 2 and row["clicks"] == 40
    assert row["earnings_cents"] == 800 and row["fans_who_spent"] == 1 and row["fans_counted"] == 2, row
    text = r.text
    for leak in ("secretfan", "Secret Fan", "9001", AID, "https://of/t501"):
        assert leak not in text, (leak, text)


def case_without_earnings_has_no_figures():
    _use()
    share = _create(include_earnings=False).json()
    row = _report(share).json()["links"][0]
    assert set(row) == {"name", "created_at", "claims", "clicks"}, row


def case_tracking_link_report():
    _use()
    r = _create(kind="campaign", of_ids=[7001])
    assert r.status_code == 200, r.text
    row = _report(r.json()).json()["links"][0]
    assert row["name"] == "IG bio" and row["clicks"] == 100 and row["subscribers"] == 1, row
    assert set(row) == {"name", "created_at", "clicks", "subscribers", "earnings_cents", "fans_who_spent",
                        "fans_counted"}, row
    assert row["fans_counted"] == 1, row


def case_wrong_secret_or_id_is_404():
    _use()
    share = _create().json()
    sid, secret = _key(share).split(".", 1)
    for key in (f"{sid}.{secret[:-1]}x", f"{int(sid) + 1000}.{secret}", sid, f"{sid}.", f".{secret}", "abc.def",
                f"{sid}.{secret}é", f"².{secret}", f"{sid}².{secret}"):
        r = _anon.get(f"/share/{key}/data")
        assert r.status_code == 404, (key, r.status_code, r.text)


def case_expired_and_revoked_are_410():
    _use()
    share = _create().json()
    _set(share["id"], expires_at=datetime.utcnow() - timedelta(seconds=1))
    assert _report(share).status_code == 410
    listed = {s["id"]: s for s in _owner.get(f"/admin/link-shares?account_id={AID}&kind=trial").json()["shares"]}
    assert listed[share["id"]]["status"] == "expired"

    share = _create().json()
    assert _report(share).status_code == 200
    r = _owner.delete(f"/admin/link-shares/{share['id']}?account_id={AID}")
    assert r.status_code == 200, r.text
    assert _report(share).status_code == 410
    listed = _owner.get(f"/admin/link-shares?account_id={AID}&kind=trial").json()["shares"]
    assert share["id"] not in {s["id"] for s in listed}
    assert _owner.delete(f"/admin/link-shares/{share['id']}?account_id={AID}").status_code == 404


def case_public_report_calls_no_onlyfans():
    _use()
    share = _create().json()

    def boom(account_id):
        raise AssertionError("the public report must not reach OnlyFans")
    ax._make_client = boom  # type: ignore[attr-defined]
    assert _report(share).status_code == 200


# ── The gates ──

def case_share_prefix_passes_the_share_token_gate_admin_does_not():
    import server
    _use()
    share = _create().json()
    saved = server.SHARE_TOKEN
    server.SHARE_TOKEN = "gate-on"
    try:
        assert _report(share).status_code == 200
        assert _anon.get("/share/1.nope/data").status_code == 404
        assert _anon.get(f"/admin/link-shares?account_id={AID}&kind=trial").status_code == 401
    finally:
        server.SHARE_TOKEN = saved


def case_owner_only_and_per_agency():
    _use()
    share = _create().json()
    assert _anon.get(f"/admin/link-shares?account_id={AID}&kind=trial").status_code == 401
    assert _create(client=_anon).status_code == 401
    chatter = fx.login_chatter("chatter_a")
    assert _create(client=chatter).status_code == 403
    assert chatter.get(f"/admin/link-shares?account_id={AID}&kind=trial").status_code == 403
    assert chatter.delete(f"/admin/link-shares/{share['id']}?account_id={AID}").status_code == 403
    other = fx.login_owner("agency_b_owner")
    assert _create(client=other).status_code == 403
    assert other.get(f"/admin/link-shares?account_id={AID}&kind=trial").status_code == 403
    # Agency B naming its own Creator cannot reach agency A's share.
    r = other.delete(f"/admin/link-shares/{share['id']}?account_id={IDS['creator_b']}")
    assert r.status_code == 404, r.text
    assert _report(share).status_code == 200


def case_validation_and_cap():
    _use()
    assert _create(name="  ").status_code == 422
    assert _create(of_ids=[]).status_code == 422
    assert _create(kind="promo").status_code == 422
    assert _create(of_ids=list(range(1, lsa.MAX_LINKS + 2))).status_code == 422
    saved = lsa.MAX_ACTIVE
    try:
        live = sum(s["status"] != "expired" for s in
                   _owner.get(f"/admin/link-shares?account_id={AID}&kind=trial").json()["shares"])
        live += sum(s["status"] != "expired" for s in
                    _owner.get(f"/admin/link-shares?account_id={AID}&kind=campaign").json()["shares"])
        lsa.MAX_ACTIVE = live + 1
        assert _create().status_code == 200
        r = _create()
        assert r.status_code == 422 and "share links" in r.text, r.text
    finally:
        lsa.MAX_ACTIVE = saved


# ── Fresh from the owner's reads ──

def case_owner_read_refreshes_live_shares_only():
    f = _use()
    live = _create(of_ids=[501, 502], include_earnings=False).json()
    gone = _create(of_ids=[501], include_earnings=False).json()
    _set(gone["id"], revoked_at=datetime.utcnow())
    f.trials[0]["clicksCounts"] = 55
    f.trials = [f.trials[0]]            # 502 no longer in OF's answer (and has no mirror row)
    assert _owner.get(f"/admin/trial-links?account_id={AID}").status_code == 200
    rows = _report(live).json()["links"]
    assert rows[0]["clicks"] == 55, rows
    assert rows[1]["name"] == "Other trial" and rows[1]["clicks"] == 3, "a link not read keeps its last row"

    async def stored():
        async with get_session() as s:
            return json.loads((await s.get(LinkShare, gone["id"])).rows_json)
    assert asyncio.run(stored())[0]["clicks"] == 40, "a revoked share is not rebuilt"


def case_a_read_with_onlyfans_down_keeps_the_report():
    f = _use()
    share = _create(include_earnings=False).json()
    before = _report(share).json()
    assert before["links"][0]["clicks"] == 40

    def down(**_):
        raise RuntimeError("OF down")
    f.trial_links = down
    d = _owner.get(f"/admin/trial-links?account_id={AID}").json()
    assert d["of_available"] is False
    after = _report(share).json()
    assert after == before, (before, after)


def case_no_log_keeps_the_share_secret():
    import logging
    import server
    line = "http://testserver/share/12.AbC-_x9/data?x=1"
    assert server.redact_share_secret(line) == "http://testserver/share/12.<secret>/data?x=1"
    assert server.redact_share_secret("/share-for-share/a.b") == "/share-for-share/a.b"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', (
        "1.2.3.4:5", "GET", "/share/12.AbC-_x9/data", "1.1", 200), None)
    for flt in logging.getLogger("uvicorn.access").filters:
        flt.filter(rec)
    assert "AbC" not in rec.getMessage() and "/share/12.<secret>/data" in rec.getMessage(), rec.getMessage()


def case_tracking_earnings_read_refreshes_its_shares():
    f = _use()
    share = _create(kind="campaign", of_ids=[7001]).json()
    f.campaigns[0]["countTransitions"] = 250
    ot._COMPUTED.clear()
    assert _owner.get(f"/admin/of-tracking-links/earnings?account_id={AID}").json()["available"] is True
    assert _report(share).json()["links"][0]["clicks"] == 250


_harness.run(
    case_create_is_pending_until_the_owners_read,
    case_report_has_link_figures_and_no_fan,
    case_without_earnings_has_no_figures,
    case_tracking_link_report,
    case_wrong_secret_or_id_is_404,
    case_expired_and_revoked_are_410,
    case_public_report_calls_no_onlyfans,
    case_share_prefix_passes_the_share_token_gate_admin_does_not,
    case_owner_only_and_per_agency,
    case_validation_and_cap,
    case_owner_read_refreshes_live_shares_only,
    case_a_read_with_onlyfans_down_keeps_the_report,
    case_no_log_keeps_the_share_secret,
    case_tracking_earnings_read_refreshes_its_shares,
)
