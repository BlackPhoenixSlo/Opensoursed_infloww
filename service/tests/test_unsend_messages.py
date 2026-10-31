#!/usr/bin/env python3
"""unsend_messages must delete on OF only the account's OWN rows past the policy
age: a dry run calls no OF DELETE, a re-run deletes nothing new, and a mass-only
policy never touches a chatter's manual message or another Creator's broadcast.
Plus tables: pure `sweep_policy` / `mass_targets` / `next_history_page`, and the
sweep rule itself (`_sweep_targets` / `_sweep_mass_targets`) against seeded rows.
Mocked OnlyFans only (FakeClient via ax._make_client); nothing reaches the network.

Run: ./venv/bin/python service/tests/test_unsend_messages.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from dataclasses import replace as replace_  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as un  # noqa: E402 — module under test (registers)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, MassBroadcastCache, MassRun, Message  # noqa: E402

KIND = "unsend_messages"
NOW = datetime(2026, 6, 1, 12, 0, 0)


class FakeClient:
    """Records every OF DELETE (per-chat unsend / mass queue cancel) and history pull."""
    def __init__(self):
        self.unsend_calls: list[tuple[int, int]] = []
        self.cancel_calls: list[int] = []
        self.history_calls = 0

    def unsend_message(self, message_id, with_user_id=None):
        self.unsend_calls.append((int(message_id), with_user_id))
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.cancel_calls.append(int(queue_id))
        return {"success": True}

    def mass_message_history(self, **kw):
        self.history_calls += 1
        return {"items": [], "hasMore": False}


def _use_fake() -> FakeClient:
    fake = FakeClient()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_cast(aid: str, qid: int, *, hours_old: float, is_free=True, media_count=0,
                    is_tip=False, is_canceled=False, can_unsend=True) -> None:
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=qid, sent_at=datetime.utcnow() - timedelta(hours=hours_old),
            body_text="hey babe", is_free=is_free, media_count=media_count, is_tip=is_tip,
            is_canceled=is_canceled, can_unsend=can_unsend, fetched_at=datetime.utcnow()))


async def _add_run(aid: str, qid: int, *, hours_old: float) -> int:
    sent = datetime.utcnow() - timedelta(hours=hours_old)
    async with get_session() as s:
        r = MassRun(account_id=aid, queue_id=qid, automation_kind="mass_premade",
                    audience_filter="{}", recipient_count=1, status="ok",
                    completed_at=sent, body="hey babe", sent_at=sent)
        s.add(r)
        await s.flush()
        return int(r.id)


async def _add_msg(aid: str, fan: int, mid: int, *, hours_old: float, mass_run_id=None,
                   body: str = "hey babe", media_count=0, direction="out",
                   is_unsent=False) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction=direction,
                      body=body, media_count=media_count, mass_run_id=mass_run_id,
                      is_unsent=is_unsent,
                      created_at=datetime.utcnow() - timedelta(hours=hours_old)))


async def _unsent(aid: str, fan: int, mid: int) -> bool:
    async with get_session() as s:
        return bool((await s.get(Message, (aid, fan, mid))).is_unsent)


async def _canceled(aid: str, qid: int) -> bool:
    async with get_session() as s:
        return bool((await s.get(MassBroadcastCache, (aid, qid))).is_canceled)


async def _actions(aid: str) -> list[Action]:
    async with get_session() as s:
        return list((await s.execute(select(Action).where(Action.account_id == aid))).scalars())


# ── pure tables ───────────────────────────────────────────────────────

def case_sweep_policy_table():
    rows = [  # (policy, per_chat, mass, text_h, media_h, m_text, m_media, m_price, floored)
        ({}, True, False, 9.0, None, None, None, None, None),
        ({"text_hours": 3, "media_hours": 12}, True, False, 3.0, 12.0, None, None, None, None),
        ({"text_hours": 0, "media_hours": "x"}, True, False, 9.0, None, None, None, None, None),
        ({"mass_text": True}, False, True, 9.0, None, 8.0, None, None, None),
        ({"mass_text_hours": 4}, False, True, 9.0, None, 4.0, None, None, None),
        ({"mass_text_hours": 4, "text_hours": 9}, True, True, 9.0, None, 4.0, None, None, None),
        ({"mass_media_hours": 6}, False, True, 9.0, None, None, 6.0, None, None),
        ({"mass_price_hours": 2}, False, True, 9.0, None, None, None, 24.0, 2.0),
        ({"mass_price_hours": 30}, False, True, 9.0, None, None, None, 30.0, None),
        ({"mass_text_hours": -1}, True, False, 9.0, None, None, None, None, None),
    ]
    for pol, pc, mass, th, mh, mt, mm, mp, fl in rows:
        p = un.sweep_policy(pol)
        got = (p.per_chat, p.mass, p.text_hours, p.media_hours, p.mass_text_hours,
               p.mass_media_hours, p.mass_price_hours, p.price_floored_from)
        assert got == (pc, mass, th, mh, mt, mm, mp, fl), (pol, got)


def case_mass_targets_table():
    rows = [  # (name, (queue_id, run_id) rows oldest first, want targets)
        ("empty", [], []),
        ("shape + no run", [(10, None)],
         [{"kind": "mass", "queue_id": 10, "mass_run_id": None, "from_cache": True}]),
        ("dup queue first wins", [(10, 1), (10, 2), (11, 3)],
         [{"kind": "mass", "queue_id": 10, "mass_run_id": 1, "from_cache": True},
          {"kind": "mass", "queue_id": 11, "mass_run_id": 3, "from_cache": True}]),
    ]
    for name, inp, want in rows:
        assert un.mass_targets(inp) == want, (name, un.mass_targets(inp))


def _m(mid, h, **kw):
    return ("msg", mid, h, kw)


def _c(qid, h, **kw):
    return ("cast", qid, h, kw)


async def _seed_rule(aid: str, other: str, spec: tuple) -> None:
    kind, ident, h, kw = spec
    kw = dict(kw)
    acc = other if kw.pop("other", False) else aid
    if kind == "msg":
        if kw.pop("mass_copy", False):  # a placeholder copy of a real mass run
            kw["mass_run_id"] = await _add_run(acc, 900 + ident, hours_old=h)
        await _add_msg(acc, 7, ident, hours_old=h, **kw)
        return
    runs = kw.pop("runs", 0)
    await _add_cast(acc, ident, hours_old=h, **kw)
    for _ in range(runs):
        await _add_run(acc, ident, hours_old=h)


async def case_sweep_rule_table():
    """The real rule: SQL WHERE + ORDER BY + LIMIT in the two sweeps, on seeded rows."""
    chat = un.sweep_policy({"text_hours": 9})
    media = un.sweep_policy({"text_hours": 9, "media_hours": 12})
    mass = un.sweep_policy({"mass_text_hours": 8, "mass_media_hours": 6,
                            "mass_price_hours": 2})             # price floored to 24h
    rows = [  # (name, seed specs, plan, want ids: chat message_ids then mass queue_ids)
        ("text past age", [_m(1, 10)], chat, [1]),
        ("text too young", [_m(1, 8)], chat, []),
        ("past 24h window", [_m(1, 25)], chat, []),
        ("another Creator's row", [_m(1, 10, other=True)], chat, []),
        ("inbound", [_m(1, 10, direction="in")], chat, []),
        ("already unsent", [_m(1, 10, is_unsent=True)], chat, []),
        ("mass placeholder row", [_m(1, 10, mass_copy=True)], chat, []),
        ("media off by default", [_m(1, 13, media_count=1)], chat, []),
        ("media opt-in", [_m(1, 13, media_count=1), _m(2, 11, media_count=1)], media, [1]),
        ("oldest first", [_m(2, 10), _m(1, 20)], chat, [1, 2]),
        ("mass text past age", [_c(10, 9)], mass, [10]),
        ("mass text young", [_c(10, 7)], mass, []),
        ("mass other Creator", [_c(10, 99, other=True)], mass, []),
        ("mass tip / canceled / locked", [_c(10, 99, is_tip=True), _c(11, 99, is_canceled=True),
                                          _c(12, 99, can_unsend=False)], mass, []),
        ("free image class", [_c(10, 7, media_count=2), _c(11, 5, media_count=2)], mass, [10]),
        ("price floor 24h", [_c(10, 23, is_free=False), _c(11, 25, is_free=False)], mass, [11]),
        ("priced image waits for price", [_c(10, 7, is_free=False, media_count=2)], mass, []),
        ("mass oldest first", [_c(11, 9), _c(10, 30)], mass, [10, 11]),
        ("dup runs on one queue once", [_c(10, 9, runs=2)], mass, [10]),
        ("mass row under chat-only plan", [_c(10, 99)], chat, []),
        ("chat row under mass-only plan", [_m(1, 10)], mass, []),
    ]
    for i, (name, specs, plan, want) in enumerate(rows):
        aid, other = f"un_rule{i}", f"un_rule{i}_b"
        await _seed_account(aid)
        await _seed_account(other)
        for sp in specs:
            await _seed_rule(aid, other, sp)
        got = []
        if plan.per_chat:
            got += await un._sweep_targets(aid, plan)
        got += await un._sweep_mass_targets(aid, plan)
        ids = [t.get("message_id") or t.get("queue_id") for t in got]
        assert ids == want, (name, got)
    # shapes
    await _seed_account("un_shape")
    await _add_msg("un_shape", 7, 1, hours_old=10)
    assert await un._sweep_targets("un_shape", chat) == [
        {"kind": "chat", "fan_id": 7, "message_id": 1}]
    # _MAX_SWEEP cap, oldest kept
    await _seed_account("un_cap")
    async with get_session() as s:
        for i in range(un._MAX_SWEEP + 5):
            s.add(Message(account_id="un_cap", fan_id=7, message_id=i + 1, direction="out",
                          body="hey", media_count=0,
                          created_at=datetime.utcnow() - timedelta(hours=10, minutes=i)))
    got = await un._sweep_targets("un_cap", chat)
    assert len(got) == un._MAX_SWEEP and got[0]["message_id"] == un._MAX_SWEEP + 5, got[:2]


def _it(q, h=None):
    d = {"id": q}
    if h is not None:
        d["date"] = (NOW - timedelta(hours=h)).isoformat() + "+00:00"
    return d


def case_next_history_page_table():
    start = NOW - timedelta(hours=72)
    PC = un._PageCursor
    base = PC(end_cursor=NOW)
    seen12 = PC(end_cursor=NOW, offset=2, seen_qids=frozenset({1, 2}))
    dm = PC(end_cursor=NOW, date_mode=True)
    page = lambda *items, more=True: {"items": list(items), "hasMore": more}  # noqa: E731
    rows = [  # (name, cursor, resp, want fresh ids, want next cursor | None)
        ("fresh + more → stride by rows returned", base, page(_it(1, 1), _it(2, 2)), [1, 2],
         PC(end_cursor=NOW, offset=2, seen_qids=frozenset({1, 2}))),
        ("repeated page → date mode, endDate=oldest-1s", seen12, page(_it(1, 1), _it(2, 2)), [],
         PC(end_cursor=NOW - timedelta(hours=2, seconds=1), offset=0, date_mode=True,
            fruitless=1, seen_qids=frozenset({1, 2}))),
        ("second fruitless page → stop", replace_(seen12, fruitless=1), page(_it(1, 1)), [], None),
        ("last page keeps fresh rows", base, page(_it(3, 1), more=False), [3], None),
        ("non-dict → stop", base, None, [], None),
        ("empty items → stop", base, page(), [], None),
        ("oldest at/before window start → stop", dm, page(_it(4, 80)), [4], None),
        ("undateable page → stop", dm, page(_it(6)), [6], None),
        ("non-shrinking cursor → stop", PC(end_cursor=NOW - timedelta(hours=3), date_mode=True),
         page(_it(7, 1)), [7], None),
        ("bad ids skipped", base, page({"id": "x"}, _it(5, 1), more=False), [5], None),
    ]
    for name, cur, resp, want_ids, want_next in rows:
        fresh, nxt = un.next_history_page(cur, resp, start)
        assert [f["id"] for f in fresh] == want_ids and nxt == want_next, (name, fresh, nxt)


# ── real runs through run_once ─────────────────────────────────────────

async def case_dry_run_calls_no_of_delete():
    aid = "un_dry"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 2001, hours_old=10)
    await _add_msg(aid, 21, 2101, hours_old=10)
    for pol in ({"mass_text_hours": 8}, {"text_hours": 9}):
        r = await run_once(aid, KIND, payload={"policy": pol, "dry_run": True})
        assert r["dry_run"] is True and r["unsent"] == 0 and r["targets"] == 1, r
    assert fake.cancel_calls == [] and fake.unsend_calls == [] and fake.history_calls == 0
    assert not await _canceled(aid, 2001) and not await _unsent(aid, 21, 2101)
    assert await _actions(aid) == []


async def case_idempotent_rerun_deletes_nothing_new():
    aid = "un_idem"
    await _seed_account(aid)
    fake = _use_fake()
    run_id = await _add_run(aid, 3001, hours_old=10)
    await _add_cast(aid, 3001, hours_old=10)
    await _add_msg(aid, 31, 3101, hours_old=10, mass_run_id=run_id)   # its placeholder copy
    await _add_msg(aid, 32, 3201, hours_old=10)                       # a per-chat bubble
    pol = {"policy": {"mass_text_hours": 8, "text_hours": 9}}
    r1 = await run_once(aid, KIND, payload=pol)
    assert sorted(fake.cancel_calls) == [3001] and fake.unsend_calls == [(3201, 32)], r1
    assert r1["unsent"] == 2, r1
    assert await _canceled(aid, 3001) and await _unsent(aid, 31, 3101) and await _unsent(aid, 32, 3201)
    n_actions = len(await _actions(aid))
    r2 = await run_once(aid, KIND, payload=pol)
    assert r2["targets"] == 0 and r2["unsent"] == 0, r2
    assert sorted(fake.cancel_calls) == [3001] and fake.unsend_calls == [(3201, 32)]
    assert len(await _actions(aid)) == n_actions


async def case_only_own_mass_is_targeted():
    aid, other = "un_own", "un_other"
    await _seed_account(aid)
    await _seed_account(other)
    fake = _use_fake()
    await _add_cast(aid, 4001, hours_old=10)            # own mass → unsent
    await _add_cast(other, 4002, hours_old=10)          # another Creator's mass → never
    # A chatter's manual reply → never. (Its own words: a row with the BLAST's body
    # near its send time is treated as an untagged copy, by mark_queue_copies_unsent.)
    await _add_msg(aid, 41, 4101, hours_old=10, body="omg yes tell me more")
    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})
    assert fake.cancel_calls == [4001] and fake.unsend_calls == [], (r, fake.cancel_calls)
    assert await _canceled(aid, 4001), "own cache row not flipped"
    assert not await _canceled(other, 4002), "another Creator's broadcast flipped"
    assert not await _unsent(aid, 41, 4101), "chatter's manual message unsent"
    acts = [a.action for a in await _actions(aid)]
    assert acts == ["unsend_mass"], acts
    assert await _actions(other) == [], "action row on another Creator"


_harness.run()
