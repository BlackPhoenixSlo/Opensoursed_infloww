#!/usr/bin/env python3
"""test_full_ai_settle_live — a real purchase settles the live Offer row (phase 05, ticket 85).

Pure:
  case_plan_table                 settle_plan rules 1 + 2 (id / no id, paid / unpaid, claimed,
                                  slack 60 / 61 s, price, settled, price 0, tease, contested)
  case_plan_now_fallback          paid, no notice, no purchased_at -> outcome_at = now
DB (temp, seeded; purchases feed = a `test_purchase_notifications._FakeClient` twin driving the
real `purchase_notifications.poll_purchases`; that module runs its cases on import):
  case_real_path_equals_fake_buy  feed -> settle_pull 1 -> row == `full_ai_test._settle` twin
                                  except join_src / outcome_at (+ identity columns)
  case_folds_equal_twin           owned_of / open_offer_of / bought_of / purchases_of /
                                  pending_tease_of / teases_sent_of live == twin
  case_twice_and_concurrent       rerun changes 0; two concurrent calls settle once (the guard)
  case_test_and_shadow_untouched  a test-Mode row and a Shadow row keep every column
  case_old_and_superseded_settle  > 24 h old and haggled-over Offers still settle
  case_account_wide_scope         no fan: every Fan of the account, no other account
  case_heuristic_link_via_db      unconfirmed row links to its sole message; two candidates: none
  case_foreign_and_stale_not_linked  in-flight row vs another lane's PPV at its price: no link; stale row unread

Run: nice -n 10 venv/bin/python service/tests/test_full_ai_settle_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

import purchase_notifications as pn  # noqa: E402
from automations import full_ai_settle as fs  # noqa: E402
from automations import full_ai_test as ft  # noqa: E402
from automations.full_ai_settle import Settle  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AiDecision, Fan, Message  # noqa: E402
from sqlalchemy import select  # noqa: E402

ACC, OTHER = "acc_fs", "acc_fs_b"
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=3)   # past the 2 h announce gate, no followup poke; inside LINK_LOAD_S
S = timedelta(seconds=1)
# Columns that differ by construction between a live row and its test twin.
IDENTITY = {"id", "fan_id", "mode", "trigger_kind", "trigger_key", "offer_message_id"}


class _FakeClient:
    """As test_purchase_notifications._FakeClient: only `get_json`, the notifications envelope."""
    def __init__(self, items): self.items = items
    def get_json(self, path):
        assert "type=purchases" in path, path
        return {"list": self.items}


_NID = iter(range(900_000_000, 999_999_999))


def _notif(fan: int, mid: int, at: datetime, cents: int) -> dict:
    return {"id": next(_NID), "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
            "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "replacePairs": {"{NAME}": "D", "{AMOUNT}": f"${cents / 100:.2f}",
                             "{MESSAGE_LINK}": f"/chats/chat/{fan}?firstId={mid}"}}


async def _feed(acc: str, *items) -> dict:
    return await pn.poll_purchases(acc, _FakeClient(list(items)))


# ── Seeding ──────────────────────────────────────────────────────────

def _cols(at, *, price, media=(), previews=(), ref=1, kind="offer", over=None, route="sell_now",
          route_row="sell", desc=None, his="hi", text="for u") -> dict:
    item = {"ref": ref, "subject": "anything", "format": "photo", "lane": "L1", "kind": kind,
            **({"over": over} if over is not None else {}), **({"desc": desc} if desc else {})}
    part = {"text": text}
    if kind != "tease":
        part["ppv"] = {"ref": ref, "price_cents": price, "media": list(media), "previews": list(previews)}
    return dict(route=route, heat=2, route_row=route_row, question_version="v", status="sent",
                created_at=at, updated_at=at, jev_json=json.dumps({"state": {"fan_new_messages": [his]}}),
                reply_json=json.dumps({"parts": [part]}), offer_price_cents=None if kind == "tease" else price,
                offer_list_cents=price, offer_item_ref=json.dumps(item),
                offer_media_json=json.dumps({"locked": list(media), "previews": list(previews)}))


def _live(acc: str, fan: int, n: int, mid: int | None, **kw) -> AiDecision:
    return AiDecision(account_id=acc, fan_id=fan, mode="live", trigger_kind="inbound",
                      trigger_key=str(n), offer_message_id=mid, **_cols(**kw))


def _twin(acc: str, pair: str, n: int, **kw) -> AiDecision:
    return AiDecision(account_id=acc, fan_id=ft.test_fan_id(pair), mode="test", trigger_kind="test",
                      trigger_key=ft.trigger_key(ft.session_key(pair, "draft"), n), **_cols(**kw))


def _msg(acc: str, fan: int, mid: int, at: datetime, price: int, paid: bool = False) -> Message:
    return Message(account_id=acc, fan_id=fan, message_id=mid, direction="out", price_cents=price,
                   is_paid=paid, purchased_at=at + 5 * S if paid else None, created_at=at)


async def _add(acc: str, fans, *objs) -> list[int]:
    async with get_session() as s:
        if await s.get(Account, acc) is None:
            s.add(Account(id=acc))
        for f in fans:
            if await s.get(Fan, (acc, f)) is None:
                s.add(Fan(account_id=acc, fan_id=f))
        for o in objs:
            s.add(o)
        await s.commit()
        return [o.id for o in objs if isinstance(o, AiDecision)]


async def _rows(*ids) -> list[AiDecision]:
    async with get_session() as s:
        got = {r.id: r for r in (await s.execute(select(AiDecision).where(AiDecision.id.in_(ids)))).scalars()}
    return [got[i] for i in ids]


def _snap(r: AiDecision) -> dict:
    return {c.name: getattr(r, c.name) for c in AiDecision.__table__.columns}


# ── Pure: settle_plan ────────────────────────────────────────────────

def _r(rid=1, *, at=T0, price=1000, mid=None, outcome=None):
    return NS(id=rid, created_at=at, offer_price_cents=price, offer_message_id=mid, outcome=outcome)


def _m(mid=10, *, at=T0 + 5 * S, price=1000, paid=False, bought_at=None, kind=None, emp=None):
    return NS(message_id=mid, created_at=at, price_cents=price, is_paid=paid, purchased_at=bought_at,
              automation_kind=kind, sent_by_employee_id=emp)


T1, T2 = T0 + timedelta(minutes=3), T0 + timedelta(minutes=2)
PAID = dict(paid=True, bought_at=T1)
_TABLE = [
    # name, rows, msgs, notices, claimed, want
    ("id + paid + notice", [_r(mid=10)], [_m(**PAID)], {10: T2}, set(), [Settle(1, 10, T2, "notice")]),
    ("id + paid, no notice", [_r(mid=10)], [_m(**PAID)], {}, set(), [Settle(1, 10, T1, "is_paid")]),
    ("id + unpaid", [_r(mid=10)], [_m()], {}, set(), []),
    ("id, message not landed", [_r(mid=10)], [], {}, set(), []),
    ("no id, one candidate, paid", [_r()], [_m(**PAID)], {}, set(), [Settle(1, 10, T1, "heuristic")]),
    ("no id, one candidate, paid + notice", [_r()], [_m(**PAID)], {10: T2}, set(),
     [Settle(1, 10, T2, "heuristic")]),
    ("no id, one candidate, unpaid: link only", [_r()], [_m()], {}, set(), [Settle(1, 10, None, None)]),
    ("no id, two candidates", [_r()], [_m(**PAID), _m(11, **PAID)], {}, set(), []),
    ("candidate claimed by another row", [_r()], [_m(**PAID)], {}, {10}, []),
    ("candidate on another row of the plan", [_r(1, mid=10), _r(2)], [_m(**PAID)], {}, set(),
     [Settle(1, 10, T1, "is_paid")]),
    ("claimed one, free one: links the free one", [_r()], [_m(**PAID), _m(11, **PAID)], {}, {10},
     [Settle(1, 11, T1, "heuristic")]),
    ("candidate 61 s older than the row", [_r()], [_m(at=T0 - 61 * S, **PAID)], {}, set(), []),
    ("candidate 60 s older than the row", [_r()], [_m(at=T0 - 60 * S, **PAID)], {}, set(),
     [Settle(1, 10, T1, "heuristic")]),
    ("price mismatch", [_r()], [_m(price=900, **PAID)], {}, set(), []),
    ("candidate 900 s after the row", [_r()], [_m(at=T0 + 900 * S, **PAID)], {}, set(),
     [Settle(1, 10, T1, "heuristic")]),
    ("candidate 901 s after the row (a later send)", [_r()], [_m(at=T0 + 901 * S, **PAID)], {}, set(), []),
    ("mass copy at +2 h, same price", [_r()], [_m(at=T0 + timedelta(hours=2), kind="reply_mass_funnel", **PAID)],
     {}, set(), []),
    ("another lane's candidate (funnel kind)", [_r()], [_m(kind="reply_mass_funnel", **PAID)], {}, set(), []),
    ("a chatter's candidate", [_r()], [_m(emp=5, **PAID)], {}, set(), []),
    ("Full AI's own attributed candidate", [_r()], [_m(kind="full_ai_chat", **PAID)], {}, set(),
     [Settle(1, 10, T1, "heuristic")]),
    ("foreign + ours: links ours", [_r()], [_m(kind="reply_mass_funnel", **PAID), _m(11, **PAID)], {}, set(),
     [Settle(1, 11, T1, "heuristic")]),
    ("already settled row", [_r(mid=10, outcome="bought")], [_m(**PAID)], {}, set(), []),
    ("price-0 row", [_r(price=0, mid=10)], [_m(price=0, **PAID)], {}, set(), []),
    ("price-0 row, no id", [_r(price=0)], [_m(price=0, **PAID)], {}, set(), []),
    ("tease row (price NULL)", [_r(price=None)], [_m(**PAID)], {}, set(), []),
    ("two unlinked rows, one sole candidate: contested", [_r(1), _r(2, at=T0 + 2 * S)], [_m(at=T0 + 9 * S, **PAID)],
     {}, set(), []),
]


def case_plan_table():
    for name, rows, msgs, notices, claimed, want in _TABLE:
        got = fs.settle_plan(rows, msgs, notices, claimed)
        assert got == want, f"{name}: {got} != {want}"


def case_plan_now_fallback():
    before = datetime.utcnow()
    (got,) = fs.settle_plan([_r(mid=10)], [_m(paid=True)], {}, set())
    assert got[:2] == (1, 10) and got.join_src == "is_paid", got
    assert before <= got.outcome_at <= datetime.utcnow(), got


# ── DB, real path ────────────────────────────────────────────────────

async def case_real_path_equals_fake_buy():
    fan, mid, pair = 7001, 9_001_001, "fs-twin"
    offer = dict(at=T0, price=1000, media=[11, 12], previews=[13], ref=101)
    live_id, twin_id = await _add(ACC, [fan], _live(ACC, fan, 1, mid, **offer), _twin(ACC, pair, 1, **offer),
                                  _msg(ACC, fan, mid, T0 + 3 * S, 1000))
    bought_at = T0 + timedelta(minutes=10)
    assert (await _feed(ACC, _notif(fan, mid, bought_at, 1000)))["flipped"] == 1
    assert await fs.settle_pull(ACC, fan) == 1
    await ft._settle(ACC, pair, "draft", twin_id, "bought")
    live, twin = await _rows(live_id, twin_id)
    a, b = _snap(live), _snap(twin)
    diff = {k: (a[k], b[k]) for k in a if k not in IDENTITY | {"join_src", "outcome_at"} and a[k] != b[k]}
    assert not diff, diff
    assert (live.outcome, live.join_src, live.outcome_at, live.offer_message_id) == (
        "bought", "notice", bought_at, mid), _snap(live)
    assert (twin.outcome, twin.join_src) == ("bought", "test"), _snap(twin)


async def case_folds_equal_twin():
    """Same session live and as a twin: an ignored $20 Offer, a bought $3 Chat tease photo, a
    bought $10 Offer, then a Pending tease. The $10 buy lands after the tease (ends it)."""
    fan, pair = 7002, "fs-folds"
    tease_at = T0 + timedelta(minutes=20)
    spec = [  # (n, mid, cols, bought at)
        (1, 9_002_001, dict(at=T0, price=2000, media=[21], ref=201), None),
        (2, 9_002_002, dict(at=T0 + timedelta(minutes=5), price=300, media=[1], ref=202,
                            route_row="chat_tease"), T0 + timedelta(minutes=6)),
        (3, 9_002_003, dict(at=T0 + timedelta(minutes=10), price=1000, media=[11, 12], previews=[13],
                            ref=203, desc="mirror set"), tease_at + timedelta(minutes=2)),
        (4, None, dict(at=tease_at, price=None, media=[31], ref=204, kind="tease", route="tease"), None),
    ]
    objs = []
    for n, mid, cols, _ in spec:
        objs += [_live(ACC, fan, n, mid, **cols), _twin(ACC, pair, n, **cols)]
        if mid:
            objs.append(_msg(ACC, fan, mid, cols["at"] + 3 * S, cols["price"]))
    ids = await _add(ACC, [fan], *objs)
    live_ids, twin_ids = ids[0::2], ids[1::2]
    now = tease_at + timedelta(minutes=5)

    async def folds():
        live, twin = await _rows(*live_ids), await _rows(*twin_ids)
        at = {t.id: lr.outcome_at for lr, t in zip(live, twin)}     # forced difference: the buy time
        twin = [NS(**{**_snap(t), "outcome_at": at[t.id] if t.outcome else None}) for t in twin]
        # pending_tease_of's Mode constant goes in ticket 70: read live rows as that fold will.
        live = [NS(**{**_snap(r), "mode": ft.MODE}) for r in live]
        pos = {r.id: i for i, r in enumerate(live)} | {r.id: i for i, r in enumerate(twin)}
        out = []
        for rows in (live, twin):
            oo, pt = ft.open_offer_of(rows), ft.pending_tease_of(rows, now)
            out.append((ft.owned_of(rows), oo and pos[oo.id], [(b.kind, b.amount_cents, b.occurred_at)
                        for b in ft.bought_of(rows)], ft.purchases_of(rows), pt and pos[pt.id],
                        ft.teases_sent_of(rows)))
        return out

    before_live, before_twin = await folds()
    assert before_live == before_twin and before_live[4] == 3, (before_live, before_twin)
    got = await _feed(ACC, *(_notif(fan, mid, at, c["price"]) for _, mid, c, at in spec if at))
    assert got["flipped"] == 2, got
    assert await fs.settle_pull(ACC, fan) == 2
    for tid, (_, _, _, at) in zip(twin_ids, spec):
        if at:
            await ft._settle(ACC, pair, "draft", tid, "bought")
    live, twin = await folds()
    assert live == twin, (live, twin)
    assert live[0] == {1, 11, 12} and live[1] == 0 and live[4] is None, live
    assert live[3] == ["bought 1 photo for $3 (lane L1)", "bought 2 photos for $10 (lane L1): mirror set"], live
    assert live[5] == ["$3 photo, he bought it"], live


async def case_twice_and_concurrent():
    fan = 7003
    ids = await _add(ACC, [fan], _live(ACC, fan, 1, 9_003_001, at=T0, price=500, media=[41]),
                     _msg(ACC, fan, 9_003_001, T0 + S, 500, paid=True))
    assert await fs.settle_pull(ACC, fan) == 1
    first = _snap((await _rows(*ids))[0])
    assert await fs.settle_pull(ACC, fan) == 0
    assert _snap((await _rows(*ids))[0]) == first
    # Concurrent: both calls read the unsettled row before either writes; the guard settles once.
    fan2 = 7004
    (rid,) = await _add(ACC, [fan2], _live(ACC, fan2, 1, 9_004_001, at=T0, price=500, media=[42]),
                        _msg(ACC, fan2, 9_004_001, T0 + S, 500, paid=True))
    real, gate = fs._load, asyncio.Barrier(2)

    async def load(*a):
        got = await real(*a)
        await gate.wait()
        return got
    fs._load = load
    try:
        a, b = await asyncio.gather(fs.settle_pull(ACC, fan2), fs.settle_pull(ACC, fan2))
    finally:
        fs._load = real
    assert sorted((a, b)) == [0, 1], (a, b)
    assert (await _rows(rid))[0].outcome == "bought"


async def case_test_and_shadow_untouched():
    fan, pair = 7005, "fs-modes"
    test_row = _twin(ACC, pair, 1, at=T0, price=500, media=[51])
    shadow = AiDecision(account_id=ACC, fan_id=fan, mode="shadow", trigger_kind="inbound", trigger_key="1",
                        route="sell_now", heat=2, route_row="sell", question_version="v", status="planned",
                        created_at=T0, updated_at=T0)
    ids = await _add(ACC, [fan], test_row, shadow, _live(ACC, fan, 2, 9_005_001, at=T0, price=500, media=[52]),
                     _msg(ACC, fan, 9_005_001, T0 + S, 500, paid=True),
                     _msg(ACC, fan, 9_005_002, T0 + 2 * S, 500, paid=True))
    before = [_snap(r) for r in await _rows(*ids[:2])]
    assert await fs.settle_pull(ACC) >= 1          # account-wide: the live row (+ other cases' leftovers)
    assert [_snap(r) for r in await _rows(*ids[:2])] == before
    assert (await _rows(ids[2]))[0].outcome == "bought"


async def case_old_and_superseded_settle():
    fan = 7006
    old_at = datetime.utcnow() - timedelta(days=3)
    old = _live(ACC, fan, 1, 9_006_001, at=old_at, price=700, media=[61])
    sup = _live(ACC, fan, 2, 9_006_002, at=old_at + timedelta(hours=1), price=2000, media=[62])
    ids = await _add(ACC, [fan], old, sup, _msg(ACC, fan, 9_006_001, old_at + S, 700),
                     _msg(ACC, fan, 9_006_002, old_at + timedelta(hours=1, seconds=1), 2000))
    hag = _live(ACC, fan, 3, 9_006_003, at=old_at + timedelta(hours=2), price=1500, media=[62], over=ids[1])
    ids += await _add(ACC, [fan], hag, _msg(ACC, fan, 9_006_003, old_at + timedelta(hours=2, seconds=1), 1500))
    rows = await _rows(*ids)
    assert ft.open_offer_of(rows).id == ids[2], "the haggle row is the open Offer; the superseded one is not"
    now = datetime.utcnow() - timedelta(hours=3)
    got = await _feed(ACC, _notif(fan, 9_006_001, now, 700), _notif(fan, 9_006_002, now, 2000))
    assert got["flipped"] == 2, got
    assert await fs.settle_pull(ACC, fan) == 2
    a, b, c = await _rows(*ids)
    assert (a.outcome, b.outcome, c.outcome) == ("bought", "bought", None), (a.outcome, b.outcome, c.outcome)
    assert a.join_src == b.join_src == "notice", (a.join_src, b.join_src)


async def case_account_wide_scope():
    f1, f2 = 7101, 7102
    acc = "acc_fs_wide"
    ids = await _add(acc, [f1, f2], _live(acc, f1, 1, 9_101_001, at=T0, price=500, media=[71]),
                     _live(acc, f2, 1, 9_102_001, at=T0, price=900, media=[72]),
                     _msg(acc, f1, 9_101_001, T0 + S, 500, paid=True),
                     _msg(acc, f2, 9_102_001, T0 + S, 900, paid=True))
    # The other account: same Fan id, same message shape, paid.
    (other,) = await _add(OTHER, [f1], _live(OTHER, f1, 1, 9_101_001, at=T0, price=500, media=[71]),
                          _msg(OTHER, f1, 9_101_001, T0 + S, 500, paid=True))
    assert await fs.settle_pull(acc) == 2
    assert [r.outcome for r in await _rows(*ids)] == ["bought", "bought"]
    assert (await _rows(other))[0].outcome is None
    assert await fs.settle_pull(acc) == 0


async def case_heuristic_link_via_db():
    fan = 7201
    one = _live(ACC, fan, 1, None, at=T0, price=1200, media=[81])
    ids = await _add(ACC, [fan], one, _msg(ACC, fan, 9_201_001, T0 + 4 * S, 1200))
    assert await fs.settle_pull(ACC, fan) == 1                      # link only, unpaid
    (r,) = await _rows(*ids)
    assert (r.offer_message_id, r.outcome, r.join_src) == (9_201_001, None, None), _snap(r)
    assert await fs.settle_pull(ACC, fan) == 0
    assert (await _feed(ACC, _notif(fan, 9_201_001, T0 + timedelta(minutes=9), 1200)))["flipped"] == 1
    assert await fs.settle_pull(ACC, fan) == 1                      # now rule 1 via the notice
    (r,) = await _rows(*ids)
    assert (r.outcome, r.join_src) == ("bought", "notice"), _snap(r)
    # Paid before linking: heuristic in one step. Two candidates: nothing.
    fan2, fan3 = 7202, 7203
    ids2 = await _add(ACC, [fan2, fan3], _live(ACC, fan2, 1, None, at=T0, price=800, media=[82]),
                      _live(ACC, fan3, 1, None, at=T0, price=800, media=[83]),
                      _msg(ACC, fan2, 9_202_001, T0 + S, 800, paid=True),
                      _msg(ACC, fan3, 9_203_001, T0 + S, 800, paid=True),
                      _msg(ACC, fan3, 9_203_002, T0 + 2 * S, 800, paid=True))
    assert await fs.settle_pull(ACC, fan2) == 1 and await fs.settle_pull(ACC, fan3) == 0
    a, b = await _rows(*ids2)
    assert (a.offer_message_id, a.outcome, a.join_src) == (9_202_001, "bought", "heuristic"), _snap(a)
    assert (b.offer_message_id, b.outcome) == (None, None), _snap(b)



async def case_foreign_and_stale_not_linked():
    """An in-flight Full AI row and another lane's PPV at its price 30 s before: no link (send_priced would
    otherwise see an id and send nothing). A row older than LINK_LOAD_S is not looked at."""
    fan, fan2 = 7301, 7302
    now = datetime.utcnow().replace(microsecond=0)
    foreign = _msg(ACC, fan, 9_301_001, now - 30 * S, 1500, paid=True)
    foreign.automation_kind = "reply_mass_funnel"
    stale_at = now - timedelta(seconds=fs.LINK_LOAD_S + 3600)
    ids = await _add(ACC, [fan, fan2], _live(ACC, fan, 1, None, at=now, price=1500, media=[91]), foreign,
                     _live(ACC, fan2, 1, None, at=stale_at, price=1500, media=[92]),
                     _msg(ACC, fan2, 9_302_001, stale_at + 5 * S, 1500, paid=True))
    assert await fs.settle_pull(ACC, fan) == 0 and await fs.settle_pull(ACC, fan2) == 0
    for r in await _rows(*ids):
        assert (r.offer_message_id, r.outcome) == (None, None), _snap(r)


_harness.run()
