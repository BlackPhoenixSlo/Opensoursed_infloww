#!/usr/bin/env python3
"""test_full_ai_owner_io — `full_ai_owner_io.load` / `claimed_ids` over a temp DB (spec 04b ticket 75).

  case_off_rule              rule off or gone -> off_rule; on -> off_mode while `_live` is false; None when live
  case_off_global            FULL_AI_CHAT_OFF on (env, and a set_override set then cleared) -> off_global,
                             even with the rule off (row order)
  case_hard_skip             blacklist, each HARD_SKIP_REASONS member, unreachable, a muted creator -> hard;
                             a graduation skip_list reason, a muted non-creator -> not
  case_audience              audience_allows_fan(kind="full_ai_live") refusing -> audience_ok false
  case_walk_advancing        pending + walker rule on -> true (reply_mass_funnel and a registered walker's runs);
                             held, not pending, another account's run, walker rule off -> false
  case_spend                 spend = fans.lifetime_spend_cents (no row = 0); top_spend_cents off the checkpoint;
                             0 never stops, equal stops; a bad stored value reads the default
  case_claimed_ids           empty for every input while `_live` is false; live + rule on -> the Fans given;
                             rule off or the global switch on -> empty
  case_no_lane_edits         no funnel / dispatch file differs from origin/main

Run: ./venv/bin/python service/tests/test_full_ai_owner_io.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime  # noqa: E402

import runtime_switches  # noqa: E402
from automations import _funnel_walkers  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations._skiplist import HARD_SKIP_REASONS  # noqa: E402
from automations.full_ai_owner import Stop, who_owns  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, Blacklist, Fan, FunnelState, MassRun, SkipList,
)

ANCHOR = datetime(2026, 11, 15, 12, 0, 0)
_n = 0


async def _account(*, rule: bool | None = True, kinds: tuple[str, ...] = ()) -> str:
    """A fresh account; its full_ai_chat rule on / off / absent (None); other enabled rules `kinds`."""
    global _n
    _n += 1
    aid = f"acc-owner-{_n}"
    async with get_session() as s:
        s.add(Account(id=aid))
        if rule is not None:
            s.add(AutomationRule(account_id=aid, name="Full AI Chat", kind="full_ai_chat",
                                 trigger_json="{}", steps_json="{}", is_enabled=rule))
        for k in kinds:
            s.add(AutomationRule(account_id=aid, name=k, kind=k, trigger_json="{}", steps_json="{}",
                                 is_enabled=True))
    return aid


@contextlib.contextmanager
def _live(on: bool = True):
    real = io._live

    async def fake(account_id):
        return on
    io._live = fake
    try:
        yield
    finally:
        io._live = real


async def _rule(aid: str, *, enabled: bool | None) -> None:
    """Switch the account's full_ai_chat rule on / off, or delete it (None)."""
    from sqlalchemy import delete, update
    async with get_session() as s:
        if enabled is None:
            await s.execute(delete(AutomationRule).where(AutomationRule.account_id == aid,
                                                         AutomationRule.kind == "full_ai_chat"))
        else:
            await s.execute(update(AutomationRule).where(AutomationRule.account_id == aid,
                                                         AutomationRule.kind == "full_ai_chat")
                            .values(is_enabled=enabled))


async def case_off_rule():
    aid = await _account()
    assert (await io.load(aid, 1, ANCHOR)).off == "off_mode"
    with _live():
        assert (await io.load(aid, 1, ANCHOR)).off is None
        await _rule(aid, enabled=False)
        assert (await io.load(aid, 1, ANCHOR)).off == "off_rule"
        await _rule(aid, enabled=None)
        assert (await io.load(aid, 1, ANCHOR)).off == "off_rule"
    assert (await io.load(aid, 1, ANCHOR)).off == "off_rule"      # rule before Mode


async def case_off_global():
    aid = await _account()
    off_rule = await _account(rule=False)
    assert "FULL_AI_CHAT_OFF" in runtime_switches.BY_NAME
    sw = runtime_switches.BY_NAME["FULL_AI_CHAT_OFF"]
    assert (sw.label, sw.kind, sw.default) == ("Full AI Chat off", "bool", False), sw
    assert sw.effect == ("On: Full AI Chat sends nothing on any Creator; its Fans go back to the other "
                         "automations."), sw.effect
    with _live():
        assert (await io.load(aid, 1, ANCHOR)).off is None
        os.environ["FULL_AI_CHAT_OFF"] = "1"
        try:
            assert (await io.load(aid, 1, ANCHOR)).off == "off_global"
            assert (await io.load(off_rule, 1, ANCHOR)).off == "off_global"
        finally:
            del os.environ["FULL_AI_CHAT_OFF"]
        assert (await io.load(aid, 1, ANCHOR)).off is None
        await runtime_switches.set_override("FULL_AI_CHAT_OFF", True, by="test")
        try:
            assert (await io.load(aid, 1, ANCHOR)).off == "off_global"
        finally:
            await runtime_switches.set_override("FULL_AI_CHAT_OFF", None, by="test")
        assert (await io.load(aid, 1, ANCHOR)).off is None


async def case_hard_skip():
    aid = await _account()
    fans = {"blacklist": 10, "unreachable": 11, "muted": 12, "graduated": 13, "muted_fan": 14, "clear": 15}
    hard = {r: 20 + i for i, r in enumerate(sorted(HARD_SKIP_REASONS))}
    async with get_session() as s:
        s.add(Blacklist(fan_id=fans["blacklist"], reason="test"))
        s.add(SkipList(account_id=aid, fan_id=fans["unreachable"], reason="unreachable"))
        s.add(SkipList(account_id=aid, fan_id=fans["graduated"], reason="too_long"))
        for r, f in hard.items():
            s.add(SkipList(account_id=aid, fan_id=f, reason=r))
        s.add(Fan(account_id=aid, fan_id=fans["muted"], is_muted=True, source="creator_we_follow"))
        s.add(Fan(account_id=aid, fan_id=fans["muted_fan"], is_muted=True, source="onlyfans"))
    want = {fans["blacklist"]: True, fans["unreachable"]: True, fans["muted"]: True, fans["graduated"]: False,
            fans["muted_fan"]: False, fans["clear"]: False, **dict.fromkeys(hard.values(), True)}
    for f, w in want.items():
        assert (await io.load(aid, f, ANCHOR)).hard_skip is w, (f, w)
    # graduation reasons other than too_long: each its own fan
    for i, reason in enumerate(("info", "spent", "gathered")):
        async with get_session() as s:
            s.add(SkipList(account_id=aid, fan_id=40 + i, reason=reason))
        assert (await io.load(aid, 40 + i, ANCHOR)).hard_skip is False, reason
    # the blacklist is global: another account sees it too
    other = await _account()
    assert (await io.load(other, fans["blacklist"], ANCHOR)).hard_skip is True
    with _live():
        assert who_owns(await io.load(aid, fans["unreachable"], ANCHOR)) == Stop("hard_skip")


async def case_audience():
    aid = await _account()
    asked = []
    real = io.audience_allows_fan

    async def refuse(account_id, fan_id, *, kind, policy=None):
        asked.append((account_id, int(fan_id), kind))
        return False, "outside_audience"
    assert (await io.load(aid, 1, ANCHOR)).audience_ok is True       # audience off = allowed
    io.audience_allows_fan = refuse
    try:
        f = await io.load(aid, 1, ANCHOR)
    finally:
        io.audience_allows_fan = real
    assert f.audience_ok is False and asked == [(aid, 1, "full_ai_live")], (f, asked)
    with _live():
        io.audience_allows_fan = refuse
        try:
            assert who_owns(await io.load(aid, 1, ANCHOR)) == Stop("audience")
        finally:
            io.audience_allows_fan = real


async def _walk(aid: str, fan: int, *, run_kind: str | None = None, status: str = "pending",
                last_error: str | None = None) -> None:
    async with get_session() as s:
        run = MassRun(account_id=aid, automation_kind=run_kind)
        s.add(run)
        await s.flush()
        s.add(FunnelState(mass_run_id=run.id, fan_id=fan, status=status, last_error=last_error))


# A walker of its own, registered the way a walker module does at import.
SIDE_RUN, SIDE_WALKER, SIDE_HOLD = "side_stream_run", "side_walker", "side_hold"
_funnel_walkers.register_walker({SIDE_RUN}, SIDE_WALKER, hold_mark=SIDE_HOLD)


async def case_walk_advancing():
    aid = await _account(kinds=("reply_mass_funnel", SIDE_WALKER))
    await _walk(aid, 1)                                              # reply_mass_funnel walk
    await _walk(aid, 2, last_error=SIDE_HOLD)                        # held
    await _walk(aid, 3, last_error=SIDE_HOLD + ":4th")               # held with a reason
    await _walk(aid, 4, status="done")                               # not pending
    await _walk(aid, 5, run_kind=SIDE_RUN)                           # the side walk, its walker on
    await _walk(aid, 6, last_error="send failed")                    # an error that is not a hold
    other = await _account(kinds=("reply_mass_funnel",))
    await _walk(other, 7)                                            # another account's run
    want = {1: True, 2: False, 3: False, 4: False, 5: True, 6: True, 7: False, 8: False}
    for f, w in want.items():
        assert (await io.load(aid, f, ANCHOR)).walk_advancing is w, (f, w)
    # walker rule off: a reply_mass_funnel walk on an account with only the side walker, and the reverse
    only_side = await _account(kinds=(SIDE_WALKER,))
    await _walk(only_side, 1)
    await _walk(only_side, 2, run_kind=SIDE_RUN)
    assert (await io.load(only_side, 1, ANCHOR)).walk_advancing is False
    assert (await io.load(only_side, 2, ANCHOR)).walk_advancing is True
    only_rmf = await _account(kinds=("reply_mass_funnel",))
    await _walk(only_rmf, 1, run_kind=SIDE_RUN)
    assert (await io.load(only_rmf, 1, ANCHOR)).walk_advancing is False
    with _live():
        assert who_owns(await io.load(aid, 1, ANCHOR)) == Stop("funnel_walk")
        assert who_owns(await io.load(aid, 2, ANCHOR)) is None


async def _config(aid: str, checkpoint: dict) -> None:
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, full_ai_config_json=json.dumps(
            {"checkpoint": checkpoint, "draft": {**checkpoint, "top_spend_cents": 1}, "rev": 1})))


async def case_spend():
    aid = await _account()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=1, lifetime_spend_cents=100000))
        s.add(Fan(account_id=aid, fan_id=2, lifetime_spend_cents=99999))
    f0 = await io.load(aid, 3, ANCHOR)                               # no Fan row
    assert (f0.spend_cents, f0.top_spend_cents) == (0, 100000), f0
    with _live():
        assert who_owns(await io.load(aid, 1, ANCHOR)) == Stop("top_spend")    # equal stops
        assert who_owns(await io.load(aid, 2, ANCHOR)) is None
    off = await _account()
    await _config(off, {"top_spend_cents": 0})                       # the checkpoint, not the draft
    async with get_session() as s:
        s.add(Fan(account_id=off, fan_id=1, lifetime_spend_cents=10**9))
    f = await io.load(off, 1, ANCHOR)
    assert (f.spend_cents, f.top_spend_cents) == (10**9, 0), f
    with _live():
        assert who_owns(await io.load(off, 1, ANCHOR)) is None       # 0 never stops
    bad = await _account()
    await _config(bad, {"top_spend_cents": "lots"})
    assert (await io.load(bad, 1, ANCHOR)).top_spend_cents == 100000


async def case_claimed_ids():
    aid = await _account()
    for ids in ([], [1], [1, 2, 3], {4, 5}):
        assert await io.claimed_ids(aid, ids) == set(), ids
    with _live():
        assert await io.claimed_ids(aid, [1, 2, "3"]) == {1, 2, 3}
        assert await io.claimed_ids(aid, []) == set()
        os.environ["FULL_AI_CHAT_OFF"] = "true"
        try:
            assert await io.claimed_ids(aid, [1, 2]) == set()
        finally:
            del os.environ["FULL_AI_CHAT_OFF"]
        await _rule(aid, enabled=False)
        assert await io.claimed_ids(aid, [1, 2]) == set()
        assert await io.claimed_ids(await _account(rule=None), [1]) == set()


def case_no_lane_edits():
    files = ["service/automations/reply_mass_funnel.py", "service/webhook_dispatch.py"]
    r = subprocess.run(["git", "diff", "--quiet", "origin/main", "--", *files], cwd=_harness._REPO_ROOT)
    assert r.returncode == 0, "a funnel / dispatch file differs from origin/main"


if __name__ == "__main__":
    _harness.run()
