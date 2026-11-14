#!/usr/bin/env python3
"""test_full_ai_routes — Full AI Chat's Route table on the inbound path.

`webhook_dispatch.on_inbound_message` then `automation_executor.run_once` on
the _harness temp DB, Jev faked at `_router_jev._client` (`_full_ai_fixtures`).
The table itself is pure-tested in test_full_ai_decide.py; these cases prove
what a written Decision row carries.

  case_jev_failure_is_chat_heat_1         raising, out of range, NaN, a missing answer
                                          or Score, no key: chat, Heat 1, `jev_failed`
  case_says_yes_without_offer_kept_not_counted  raw answer kept, Route unchanged
  case_gif_fits_leaves_route_unchanged    gif_fits 1.0 or 0.0: same Route
  case_every_row_carries_route_row_fired_arm  route_row, fired, Arm, salt_ver; both Arms
  case_replay_reproduces_route_row_heat   decide_turn over a row's jev_json gives
                                          its route, route_row and heat
  case_only_gate_error_is_a_jev_failure   any other error from `ask`: error run, no row
  case_today_read_counts_by_route_in_the_report_zone  GET /admin/full-ai/today: every
                                          Route counted (zeros too) + jev_failed, since the zone's
                                          midnight, shadow only, newest 50 rows with Fan name;
                                          the run emits rule_run_finished kind full_ai_chat
  case_today_read_refuses_a_creator_not_owned  403, and 401 with no session

Run: ./venv/bin/python service/tests/test_full_ai_routes.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from _full_ai_fixtures import (  # noqa: E402
    QUIET, T0, FakeJev, _dm, _one_turn, _raw, _rows, _run, _seed,
)
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_decide  # noqa: E402
import auth  # noqa: E402
import events  # noqa: E402
import full_ai_api  # noqa: E402
import stats  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Fan  # noqa: E402


async def case_jev_failure_is_chat_heat_1():
    """Any Jev failure (raising, an out-of-range answer or Score, NaN, a missing
    answer or Score, no key) is route chat, Heat 1, row `jev_failed` with the
    error, in an ok run: never a no_send, so an outage mutes no Fan."""
    missing = {k: v for k, v in QUIET.items() if k != "stop"}
    cases = (
        ("raise", RuntimeError("jev down")),
        ("range", ({**QUIET, "promo": 1.5}, 1.0)),
        ("score_range", ({**QUIET, "promo": .99}, 4.5)),
        ("nan", ({**QUIET, "says_under_18": float("nan")}, 1.0)),
        ("missing", (missing, 1.0)),
        ("no_score", _raw({**QUIET, "promo": .99}, {})),
    )
    for name, verdict in cases:
        aid, fan = f"fa_jevfail_{name}", 71
        res, r = await _one_turn(aid, fan, verdict)
        assert res["status"] == "ok", (name, res)
        assert (r.route, r.heat, r.route_row) == ("chat", 1, "jev_failed"), (name, r.route, r.heat, r.route_row)
        assert r.jev_error, name
        assert (r.arm, r.salt_ver) == (full_ai_decide.arm_of(aid, fan), 1), name
        assert json.loads(r.jev_json)["state"]["fan_new_messages"] == ["hey you"], name
    saved = os.environ.pop("TYPESAFE_API_KEY")
    try:
        fake = FakeJev()
        await _seed("fa_jevfail_nokey", rule=True, gate=False)
        await _dm("fa_jevfail_nokey", 71, 7001, "hey you", T0)
        res, _ = await _run("fa_jevfail_nokey", fake)
    finally:
        os.environ["TYPESAFE_API_KEY"] = saved
    (r,) = await _rows("fa_jevfail_nokey")
    assert res["status"] == "ok" and fake.calls == [], (res, fake.calls)
    assert (r.route, r.heat, r.route_row) == ("chat", 1, "jev_failed"), (r.route, r.heat, r.route_row)
    assert "TypeSafe key" in r.jev_error, r.jev_error


async def case_says_yes_without_offer_kept_not_counted():
    """says_yes_to_offer at 1.0 with no Pending offer: its raw answer is kept,
    the Route unchanged (chat); with a Pending offer the same answer sells."""
    _res, r = await _one_turn("fa_yes_nooffer", 72, ({**QUIET, "says_yes_to_offer": 1.0}, 1.0))
    jj = json.loads(r.jev_json)
    assert jj["answers"]["says_yes_to_offer"] == 1.0 and jj["state"]["pending_offer"] == "none", jj
    assert (r.route, r.route_row) == ("chat", "otherwise"), (r.route, r.route_row)
    _res, r = await _one_turn("fa_yes_offer", 72, ({**QUIET, "says_yes_to_offer": 1.0}, 1.0), offer=True)
    assert (r.route, r.route_row) == ("sell_now", "sell"), (r.route, r.route_row)


async def case_gif_fits_leaves_route_unchanged():
    """gif_fits at 1.0 or 0.0: the same Route, quiet or sexual."""
    for i, (base, want) in enumerate(((QUIET, ("chat", "otherwise")),
                                      ({**QUIET, "sexual_now": .9}, ("sext", "sexual_now")))):
        for g in (1.0, 0.0):
            _res, r = await _one_turn(f"fa_gif_{i}_{int(g)}", 73, ({**base, "gif_fits": g}, 1.0))
            assert (r.route, r.route_row) == want, (i, g, r.route, r.route_row)
            assert json.loads(r.jev_json)["answers"]["gif_fits"] == g


async def case_every_row_carries_route_row_fired_arm():
    """Every row carries `route_row`, the fired set and the Arm and `salt_ver`
    `arm_of` gives; a holdout Fan and a treatment Fan both get rows."""
    holdout = next(f for f in range(100, 10_000) if full_ai_decide.arm_of("fa_arm_h", f) == "holdout")
    treated = next(f for f in range(100, 10_000) if full_ai_decide.arm_of("fa_arm_t", f) == "treatment")
    verdict = ({**QUIET, "price": .8, "sexual_now": .8, "gif_fits": .7}, 2.0)
    for aid, fan, arm in (("fa_arm_h", holdout, "holdout"), ("fa_arm_t", treated, "treatment")):
        res, r = await _one_turn(aid, fan, verdict)
        assert res["status"] == "ok", res
        assert (r.route, r.route_row, r.heat) == ("tease", "tease_price", 3), (r.route, r.route_row, r.heat)
        assert json.loads(r.jev_json)["fired"] == ["gif_fits", "price", "sexual_now"], r.jev_json
        assert (r.arm, r.salt_ver) == (arm, 1), (aid, r.arm, r.salt_ver)


def _replayed(jj: dict) -> full_ai_decide.Decision:
    """`decide_turn` over the Facts rebuilt from a stored row's `jev_json` alone."""
    ok = jj["answers"] is not None
    fired = rj.fired(jj["answers"]) if ok else frozenset()
    assert sorted(fired) == jj["fired"], (sorted(fired), jj["fired"])
    return full_ai_decide.decide_turn(full_ai_decide.Facts(
        fired=fired, intensity=jj["intensity"]["score"] if ok else 0.0,
        pending_offer=jj["state"]["pending_offer"] != "none", pending_tease=False, jev_ok=ok))


async def case_replay_reproduces_route_row_heat():
    """R9: `decide_turn` over a stored row's `jev_json` reproduces its `route`,
    `route_row` and `heat`, so rows can be re-routed under a later table."""
    verdicts = (
        (({**QUIET, "promo": .9}, 0.0), False, ("no_send", "promo")),
        (({**QUIET, "complains_now": .6, "stop": .9}, 1.0), False, ("make_right", "complains_now")),
        (({**QUIET, "says_yes_to_offer": .8}, 1.5), True, ("sell_now", "sell")),
        (({**QUIET, "says_yes_to_offer": .8}, 1.5), False, ("chat", "otherwise")),
        (({**QUIET, "declines_buying": .6, "sexual_now": .9}, 3.6), False, ("tease", "tease_decline")),
        (({**QUIET, "sexual_now": .9}, 2.5), False, ("sext", "sexual_now")),
        (RuntimeError("jev down"), False, ("chat", "jev_failed")),
    )
    for i, (verdict, offer, want) in enumerate(verdicts):
        _res, r = await _one_turn(f"fa_replay_{i}", 74, verdict, offer=offer)
        assert (r.route, r.route_row) == want, (i, r.route, r.route_row)
        d = _replayed(json.loads(r.jev_json))
        assert (d.route, d.row, d.heat) == (r.route, r.route_row, r.heat), (i, d, r.route, r.route_row, r.heat)


async def case_only_gate_error_is_a_jev_failure():
    """Only `GateError` is read as a Jev failure: any other exception from
    `ask` (a bug, not Jev) ends the run in error and writes no row."""
    aid, fan = "fa_not_gate", 75
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 7001, "hey you", T0)
    real = rj.ask

    async def _bug(st, account_id=None):
        raise RuntimeError("a bug, not Jev")
    rj.ask = _bug  # type: ignore[assignment]     # the runner reads `router.ask`
    try:
        res, _ = await _run(aid, FakeJev())
    finally:
        rj.ask = real  # type: ignore[assignment]
    assert res["status"] == "error", res
    assert await _rows(aid) == []


async def _today(aid: str, *, owns: tuple[str, ...] | None = None) -> dict:
    tok = auth._request_user.set(auth.AuthedUser("u_fa", "fa_owner", frozenset(owns or (aid,))))
    try:
        return await full_ai_api.full_ai_today(account_id=aid)
    finally:
        auth._request_user.reset(tok)


async def _decision(aid: str, fan: int, key: str, at: datetime, *, route: str = "chat",
                    mode: str = "shadow", error: str | None = None) -> None:
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=fan, mode=mode, trigger_kind="inbound", trigger_key=key,
                         route=route, heat=2, route_row="otherwise", question_version="v",
                         jev_ms=None if error else 40, jev_error=error, status="planned",
                         created_at=at))


async def case_today_read_counts_by_route_in_the_report_zone():
    """One DM through the inbound path, plus rows either side of the report
    zone's midnight: the read counts today's shadow rows per Route, every
    Route present (zeros too, in Route order), Jev failures apart, newest
    first, at most 50, each with its Fan's name. The run emits
    `rule_run_finished` with its kind, which refetches the page's read."""
    aid, fan = "fa_today", 76
    q = await events.subscribe("all", accounts=frozenset({aid}))
    try:
        res, live = await _one_turn(aid, fan, ({**QUIET, "sexual_now": .9}, 2.5))
        got = []
        while not q.empty():
            got.append(q.get_nowait())
    finally:
        await events.unsubscribe("all", q)
    finished = [e["rule_run_finished"] for e in got if "rule_run_finished" in e]
    assert [(f["kind"], f["run_id"], f["status"]) for f in finished] == [("full_ai_chat", res["run_id"], "ok")], got
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Garrett"))
    zone = ZoneInfo("Pacific/Kiritimati")       # UTC+14: its midnight is never UTC's
    since = (datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc).replace(tzinfo=None))
    await _decision(aid, fan, "y1", since - timedelta(minutes=1), route="no_send")   # yesterday there
    await _decision(aid, fan, "t1", since + timedelta(seconds=1), route="tease")
    await _decision(aid, fan, "f1", since + timedelta(seconds=2), error="jev down")
    await _decision(aid, fan, "m1", since + timedelta(seconds=3), route="sell_now", mode="test")
    await _decision("fa_jevfail_raise", fan, "o1", since + timedelta(seconds=3), route="ai_dare")
    real = stats._report_zone

    async def _zone(account_id):
        return zone
    stats._report_zone = _zone  # type: ignore[assignment]
    try:
        got = await _today(aid)
    finally:
        stats._report_zone = real  # type: ignore[assignment]
    assert got["since"] == since.isoformat() + "Z", got["since"]
    assert list(got["counts"]) == ["chat", "sext", "sell_now", "tease", "make_right", "ai_dare", "no_send"]
    want = {"chat": 1, "sext": 1, "sell_now": 0, "tease": 1, "make_right": 0, "ai_dare": 0, "no_send": 0}
    assert (live.route, live.route_row) == ("sext", "sexual_now"), (live.route, live.route_row)
    assert got["counts"] == want and got["jev_failed"] == 1, got
    rows = sorted(got["rows"], key=lambda r: r["created_at"], reverse=True)
    assert got["rows"] == rows and len(rows) == 3, got["rows"]
    r = next(r for r in rows if r["id"] == live.id)
    assert r == {"id": live.id, "created_at": r["created_at"], "fan_id": str(fan), "fan_name": "Garrett",
                 "route": "sext", "heat": live.heat, "row": "sexual_now", "jev_ms": live.jev_ms,
                 "jev_failed": False}, r
    assert [x["jev_failed"] for x in rows if x["jev_ms"] is None] == [True], rows
    # No report zone: UTC midnight. At most 50 rows, newest first.
    for i in range(55):
        await _decision(aid, fan + 1, f"n{i}", datetime.utcnow() - timedelta(seconds=i))
    got = await _today(aid)
    utc0 = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    assert got["since"] == utc0.isoformat() + "Z", got["since"]
    assert len(got["rows"]) == 50 and got["counts"]["chat"] >= 55, got["counts"]
    stamps = [x["created_at"] for x in got["rows"]]
    assert stamps == sorted(stamps, reverse=True), stamps
    assert {x["fan_name"] for x in got["rows"] if x["fan_id"] == str(fan + 1)} == {None}   # no Fan row


async def case_today_read_refuses_a_creator_not_owned():
    await _seed("fa_today_mine", rule=True, gate=False)
    await _seed("fa_today_theirs", rule=True, gate=False)
    try:
        await _today("fa_today_theirs", owns=("fa_today_mine",))
    except HTTPException as e:
        assert e.status_code == 403, e.status_code
    else:
        raise AssertionError("a Creator the session does not own was served")
    try:
        await full_ai_api.full_ai_today(account_id="fa_today_mine")
    except HTTPException as e:
        assert e.status_code == 401, e.status_code
    else:
        raise AssertionError("no session was served")


_harness.run()
