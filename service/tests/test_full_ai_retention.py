#!/usr/bin/env python3
"""Full AI ledger retention (ticket 72, spec phase-04a › Retention, ADR-0034), in db_retention.evict_audit_logs_once:
non-test `ai_decisions` rows older than FULL_AI_JSON_RETAIN_S (default 90 days) lose `jev_json` + `reply_json` and
stay; never a `sending` row nor the newest row of its (account, fan, mode). Test rows' shipped 7-day delete pinned.
W30 #11: a tease-priced row keeps `reply_json.chat_tease.cents` (and nothing else), so `full_ai_test.is_tease` still
counts it: the live loader folds every row of the Fan (`teases_sent_of`, Spacing), not a 90-day window.

Run: ./venv/bin/python service/tests/test_full_ai_retention.py   (prints "all cases passed")
"""
import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import importlib  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import db_retention  # noqa: E402
from db.engine import get_session  # noqa: E402
from automations import full_ai_test  # noqa: E402
from db.models import Account, AiDecision  # noqa: E402

AID = "acct_fa_json_retention"
JEV, REPLY = '{"answers": {"q": 0.9}, "state": {"asked": 1}}', '{"scene": {"n": 2, "stage": "tease"}, "parts": ["hi"]}'
_key = iter(range(10**6))


def _now() -> datetime:
    """Naive UTC, as db_retention and the stored column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _reset():
    async with get_session() as s:
        await s.execute(AiDecision.__table__.delete())
        if not await s.get(Account, AID):
            s.add(Account(id=AID))
        await s.commit()


async def _add(fan, mode, status, age: timedelta, **kw) -> int:
    async with get_session() as s:
        k, at = next(_key), _now() - age
        row = AiDecision(account_id=AID, fan_id=fan, mode=mode, trigger_kind="inbound", trigger_key=f"k{k}",
                         route="sell", heat=2, route_row="wants_content", question_version="v4",
                         router_model="jev-1", writer_model="w-1", jev_json=JEV, jev_ms=812,
                         reply_json=kw.pop("reply_json", REPLY),
                         status=status, created_at=at, updated_at=at,
                         offer_price_cents=1500, offer_list_cents=2000, offer_media_json='{"locked": [1]}',
                         offer_item_ref='{"ref": 1}', offer_message_id=1000 + k, outcome="bought",
                         outcome_at=at, join_src="live", **kw)
        s.add(row)
        await s.commit()
        return row.id


async def _rows() -> dict[int, dict]:
    async with get_session() as s:
        return {r["id"]: dict(r) for r in (await s.execute(select(AiDecision.__table__))).mappings()}


def _nulled(before: dict, after: dict) -> bool:
    """JSON gone, every other column as it was."""
    rest = lambda r: {k: v for k, v in r.items() if k not in ("jev_json", "reply_json")}  # noqa: E731
    return after["jev_json"] is None and after["reply_json"] is None and rest(after) == rest(before)


D = timedelta(days=1)


async def case_old_terminal_rows_lose_json_and_stay():
    """Shadow `planned` and live sent / no_send / failed / unconfirmed rows at 91 days, each with a newer row for
    the Fan: both JSON NULL, every other column unchanged, row count unchanged. The same at 89 days: untouched."""
    await _reset()
    old = []
    for fan, (mode, status) in enumerate([("shadow", "planned"), ("live", "sent"), ("live", "no_send"),
                                          ("live", "failed"), ("live", "unconfirmed")], start=1):
        old.append(await _add(fan, mode, status, 91 * D))
        await _add(fan + 100, mode, status, 89 * D)    # 89 days: untouched
        await _add(fan, mode, "sent", 1 * D)          # the newer row of each Fan / Mode
        await _add(fan + 100, mode, "sent", 1 * D)
    before = await _rows()
    res = await db_retention.evict_audit_logs_once()
    after = await _rows()
    assert res["ai_decisions_json"] == 5, res
    assert set(after) == set(before), "a row was deleted"
    for i in old:
        assert _nulled(before[i], after[i]), (before[i], after[i])
    for i in set(before) - set(old):
        assert after[i] == before[i], (i, before[i], after[i])


async def case_newest_row_kept_until_a_newer_one_lands():
    """The Fan's newest live row at 200 days: untouched; a newer row added: the next pass NULLs it."""
    await _reset()
    lone = await _add(7, "live", "sent", 200 * D)
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions_json"] == 0 and (await _rows())[lone]["jev_json"] == JEV, res
    await _add(7, "live", "sent", timedelta(minutes=1))
    before = await _rows()
    res = await db_retention.evict_audit_logs_once()
    after = await _rows()
    assert res["ai_decisions_json"] == 1 and _nulled(before[lone], after[lone]), (res, after[lone])


async def case_sending_row_untouched():
    await _reset()
    i = await _add(8, "live", "sending", 91 * D)
    await _add(8, "live", "sent", 1 * D)
    before = await _rows()
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions_json"] == 0 and (await _rows())[i] == before[i], res


async def case_newest_per_mode_both_kept():
    """A Fan's newest Shadow row and newest live row (both old) keep their JSON; an older Shadow row of the Fan
    does not; another Fan's rows do not count as newer."""
    await _reset()
    old_shadow = await _add(9, "shadow", "planned", 300 * D)
    new_shadow = await _add(9, "shadow", "planned", 200 * D)
    new_live = await _add(9, "live", "sent", 150 * D)
    other = await _add(10, "live", "sent", 150 * D)      # another Fan's lone row: its own newest
    await _add(11, "live", "sent", 1 * D)
    res = await db_retention.evict_audit_logs_once()
    after = await _rows()
    assert res["ai_decisions_json"] == 1, res
    assert after[old_shadow]["jev_json"] is None
    assert all(after[i]["jev_json"] == JEV and after[i]["reply_json"] == REPLY for i in (new_shadow, new_live, other))


async def case_test_rows_deleted_at_7_days_never_nulled():
    """Shipped: test rows 8 days old deleted, 6 days old kept (with JSON)."""
    await _reset()
    gone = await _add(12, "test", "sent", 8 * D)
    kept = await _add(12, "test", "sent", 6 * D)
    await _add(12, "test", "sent", 1 * D)
    res = await db_retention.evict_audit_logs_once()
    after = await _rows()
    assert res["ai_decisions"] == 1 and gone not in after, res
    assert after[kept]["jev_json"] == JEV and after[kept]["reply_json"] == REPLY, after[kept]


async def case_second_pass_changes_nothing():
    await _reset()
    for fan in (13, 14):
        await _add(fan, "live", "sent", 120 * D)
        await _add(fan, "live", "sent", 1 * D)
    assert (await db_retention.evict_audit_logs_once())["ai_decisions_json"] == 2
    before = await _rows()
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions_json"] == 0 and await _rows() == before, res


async def case_batches_until_done():
    """More rows than a batch: one pass NULLs them all."""
    await _reset()
    db_retention._FULL_AI_JSON_BATCH = 2
    try:
        for fan in range(20, 25):
            await _add(fan, "shadow", "planned", 100 * D)
            await _add(fan, "shadow", "planned", 1 * D)
        res = await db_retention.evict_audit_logs_once()
    finally:
        db_retention._FULL_AI_JSON_BATCH = 2000
    assert res["ai_decisions_json"] == 5, res
    async with get_session() as s:
        left = (await s.execute(select(func.count()).where(AiDecision.jev_json.isnot(None)))).scalar_one()
    assert left == 5, left


async def case_env_window_and_zero_disables():
    """FULL_AI_JSON_RETAIN_S=60 in the environment: a 2-minute-old non-newest row is NULLed (a test row of the same
    age is not: deleted at 7 days, never NULLed and kept). 0 disables the NULLing."""
    await _reset()
    live = await _add(30, "live", "sent", timedelta(minutes=2))
    await _add(30, "live", "sent", timedelta(seconds=5))
    test = await _add(31, "test", "sent", timedelta(minutes=2))
    await _add(31, "test", "sent", timedelta(seconds=5))
    old_env = os.environ.get("FULL_AI_JSON_RETAIN_S")
    try:
        os.environ["FULL_AI_JSON_RETAIN_S"] = "0"
        importlib.reload(db_retention)
        assert "ai_decisions_json" not in await db_retention.evict_audit_logs_once()
        os.environ["FULL_AI_JSON_RETAIN_S"] = "60"
        importlib.reload(db_retention)
        res = await db_retention.evict_audit_logs_once()
    finally:
        if old_env is None:
            os.environ.pop("FULL_AI_JSON_RETAIN_S", None)
        else:
            os.environ["FULL_AI_JSON_RETAIN_S"] = old_env
        importlib.reload(db_retention)
    after = await _rows()
    assert res["ai_decisions_json"] == 1 and after[live]["jev_json"] is None, res
    assert after[test]["jev_json"] == JEV, after[test]
    assert db_retention._FULL_AI_JSON_RETAIN_S == 90 * 24 * 60 * 60


async def case_old_tease_row_stays_a_tease():
    """W30 #11: an old offer_moment row priced by the tease price Jev (and a free one, cents 0) keeps only
    `reply_json.chat_tease.cents`: `is_tease` and `teases_sent_of` read the same before and after; a malformed
    reply_json is NULLed as before; a second pass changes nothing."""
    await _reset()
    tease = await _add(40, "live", "sent", 120 * D, reply_json='{"chat_tease": {"cents": 300, "options": [0, 300]},'
                       ' "ride": true, "parts": ["hey"]}')
    free = await _add(40, "live", "sent", 110 * D, reply_json='{"chat_tease": {"cents": 0}, "parts": ["x"]}')
    bad = await _add(40, "live", "sent", 100 * D, reply_json="not json")
    await _add(40, "live", "sent", 1 * D)
    async with get_session() as s:
        rows = list((await s.execute(select(AiDecision).where(AiDecision.id.in_((tease, free))))).scalars())
    assert all(full_ai_test.is_tease(r) for r in rows)
    res = await db_retention.evict_audit_logs_once()
    after = await _rows()
    assert res["ai_decisions_json"] == 3, res
    assert after[tease]["reply_json"] == '{"chat_tease":{"cents":300}}', after[tease]["reply_json"]
    assert after[free]["reply_json"] == '{"chat_tease":{"cents":0}}', after[free]["reply_json"]
    assert after[bad]["reply_json"] is None and all(after[i]["jev_json"] is None for i in (tease, free, bad))
    async with get_session() as s:
        rows = list((await s.execute(select(AiDecision).where(AiDecision.account_id == AID)
                                     .order_by(AiDecision.id))).scalars())
    assert [full_ai_test.is_tease(r) for r in rows] == [True, True, False, False], rows
    assert len(full_ai_test.teases_sent_of(rows)) == 2, full_ai_test.teases_sent_of(rows)
    before = await _rows()
    res = await db_retention.evict_audit_logs_once()
    assert res["ai_decisions_json"] == 0 and await _rows() == before, res


_harness.run(
    case_old_tease_row_stays_a_tease,
    case_old_terminal_rows_lose_json_and_stay,
    case_newest_row_kept_until_a_newer_one_lands,
    case_sending_row_untouched,
    case_newest_per_mode_both_kept,
    case_test_rows_deleted_at_7_days_never_nulled,
    case_second_pass_changes_nothing,
    case_batches_until_done,
    case_env_window_and_zero_disables,
)
