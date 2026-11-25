#!/usr/bin/env python3
from __future__ import annotations

import _harness

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
    _res, r = await _one_turn("fa_yes_nooffer", 72, ({**QUIET, "says_yes_to_offer": 1.0}, 1.0))
    jj = json.loads(r.jev_json)
    assert jj["answers"]["says_yes_to_offer"] == 1.0 and jj["state"]["pending_offer"] == "none", jj
    assert (r.route, r.route_row) == ("chat", "otherwise"), (r.route, r.route_row)
    _res, r = await _one_turn("fa_yes_offer", 72, ({**QUIET, "says_yes_to_offer": 1.0}, 1.0), offer=True)
    assert (r.route, r.route_row) == ("sell_now", "sell"), (r.route, r.route_row)


async def case_gif_fits_leaves_route_unchanged():
    for i, (base, want) in enumerate(((QUIET, ("chat", "otherwise")),
                                      ({**QUIET, "sexual_now": .9}, ("sext", "sexual_now")))):
        for g in (1.0, 0.0):
            _res, r = await _one_turn(f"fa_gif_{i}_{int(g)}", 73, ({**base, "gif_fits": g}, 1.0))
            assert (r.route, r.route_row) == want, (i, g, r.route, r.route_row)
            assert json.loads(r.jev_json)["answers"]["gif_fits"] == g


async def case_every_row_carries_route_row_fired_arm():
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
    ok = jj["answers"] is not None
    fired = rj.fired(jj["answers"]) if ok else frozenset()
    assert sorted(fired) == jj["fired"], (sorted(fired), jj["fired"])
    return full_ai_decide.decide_turn(full_ai_decide.Facts(
        fired=fired, intensity=jj["intensity"]["score"] if ok else 0.0,
        pending_offer=jj["state"]["pending_offer"] != "none", pending_tease=False, jev_ok=ok))


async def case_replay_reproduces_route_row_heat():
    verdicts = (
        (({**QUIET, "promo": .9}, 0.0), False, ("no_send", "promo")),
        (({**QUIET, "complains_now": .6, "stop": .9}, 1.0), False, ("make_right", "complains_now")),
        (({**QUIET, "says_yes_to_offer": .8}, 1.5), True, ("sell_now", "sell")),
        (({**QUIET, "says_yes_to_offer": .8}, 1.5), False, ("chat", "otherwise")),
        (({**QUIET, "declines_buying": .97, "sexual_now": .9}, 3.6), False, ("sext", "sexual_now")),
        (({**QUIET, "sexual_now": .9}, 2.5), False, ("sext", "sexual_now")),
        (RuntimeError("jev down"), False, ("chat", "jev_failed")),
    )
    for i, (verdict, offer, want) in enumerate(verdicts):
        _res, r = await _one_turn(f"fa_replay_{i}", 74, verdict, offer=offer)
        assert (r.route, r.route_row) == want, (i, r.route, r.route_row)
        d = _replayed(json.loads(r.jev_json))
        assert (d.route, d.row, d.heat) == (r.route, r.route_row, r.heat), (i, d, r.route, r.route_row, r.heat)


async def case_only_gate_error_is_a_jev_failure():
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
    zone = ZoneInfo("Pacific/Kiritimati")
    since = (datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc).replace(tzinfo=None))
    await _decision(aid, fan, "y1", since - timedelta(minutes=1), route="no_send")
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
    want = {"chat": 1, "sext": 1, "sell_now": 1, "tease": 1, "make_right": 0, "ai_dare": 0, "no_send": 0}
    assert (live.route, live.route_row) == ("sext", "sexual_now"), (live.route, live.route_row)
    assert got["counts"] == want and got["jev_failed"] == 1, got
    rows = sorted(got["rows"], key=lambda r: r["created_at"], reverse=True)
    assert got["rows"] == rows and len(rows) == 4, got["rows"]
    assert [(x["route"], x["fan_name"]) for x in rows if x["test"]] == [("sell_now", None)], rows
    r = next(r for r in rows if r["id"] == live.id)
    assert r == {"id": live.id, "created_at": r["created_at"], "fan_id": str(fan), "fan_name": "Garrett",
                 "route": "sext", "heat": live.heat, "row": "sexual_now", "jev_ms": live.jev_ms,
                 "jev_failed": False, "test": False, "live": False}, r
    assert [x["jev_failed"] for x in rows if x["jev_ms"] is None] == [True], rows
    for i in range(55):
        await _decision(aid, fan + 1, f"n{i}", datetime.utcnow() - timedelta(seconds=i))
    got = await _today(aid)
    utc0 = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    assert got["since"] == utc0.isoformat() + "Z", got["since"]
    assert len(got["rows"]) == 50 and got["counts"]["chat"] >= 55, got["counts"]
    stamps = [x["created_at"] for x in got["rows"]]
    assert stamps == sorted(stamps, reverse=True), stamps
    assert {x["fan_name"] for x in got["rows"] if x["fan_id"] == str(fan + 1)} == {None}


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


async def case_today_read_counts_test_rows():
    aid, fan = "fa_today_test_rows", 81
    await _seed(aid, rule=True, gate=False)
    now = datetime.utcnow()
    for i, route in enumerate(("chat", "sext", "chat")):
        await _decision(aid, fan, f"s{i}", now - timedelta(seconds=30 - i), route=route)
    before = await _today(aid)
    for i, route in enumerate(full_ai_api.ROUTES):
        await _decision(aid, -fan, f"test:p-L:{i + 1}", now + timedelta(seconds=i), route=route, mode="test",
                        error="jev down" if i == 0 else None)
    after = await _today(aid)
    assert before["counts"]["chat"] == 2 and before["counts"]["sext"] == 1 and len(before["rows"]) == 3, before
    assert after["counts"] == {r: n + 1 for r, n in before["counts"].items()}, (before, after)
    assert after["jev_failed"] == before["jev_failed"] + 1, after
    test = [x for x in after["rows"] if x["test"]]
    assert [x["route"] for x in test] == list(reversed(full_ai_api.ROUTES)), test
    assert {x["fan_name"] for x in test} == {None} and [x["jev_failed"] for x in test][-1] is True, test
    assert [x for x in after["rows"] if not x["test"]] == before["rows"], (before, after)


async def case_test_photo_duplicate_post_shares_one_describe():
    import asyncio
    from automations import full_ai_photo, full_ai_turn
    import inbound_describe
    calls, fail = [], []

    async def _describe(account_id, still, his_words=""):
        calls.append((account_id, still, his_words))
        await asyncio.sleep(0.05)
        if fail:
            raise RuntimeError("vision down")
        return "a red bikini", "vision-model"

    async def _cfg(account_id):
        return {side: {full_ai_photo.KEY: True} for side in ("checkpoint", "draft")}

    async def _opt_in(kind, account_id):
        return None
    saved = (full_ai_api.assert_account_owned, full_ai_api.require_opt_in_kind, full_ai_photo.upload_still,
             full_ai_turn.stored_config, inbound_describe.describe_upload)
    full_ai_api.assert_account_owned = lambda aid: None
    full_ai_api.require_opt_in_kind = _opt_in
    full_ai_photo.upload_still = lambda img: ("still", "data:image/jpeg;base64,AA")
    full_ai_turn.stored_config = _cfg
    inbound_describe.describe_upload = _describe
    try:
        body = full_ai_api.TestPhoto(account_id="fa_photo_dup", image="data:image/png;base64,AA", text="hi")
        a, b = await asyncio.gather(full_ai_api.full_ai_test_photo(body), full_ai_api.full_ai_test_photo(body))
        assert len(calls) == 1 and a == b and a["desc"] == "a red bikini", (calls, a, b)
        assert full_ai_api._photos_running == {}, full_ai_api._photos_running
        await full_ai_api.full_ai_test_photo(body)
        assert len(calls) == 2, "no cache after the first ended"
        other = full_ai_api.TestPhoto(account_id="fa_photo_dup", image="data:image/png;base64,AA", text="yo")
        await asyncio.gather(full_ai_api.full_ai_test_photo(body), full_ai_api.full_ai_test_photo(other))
        assert len(calls) == 4, "other text: its own call"
        fail.append(1)
        got = await asyncio.gather(full_ai_api.full_ai_test_photo(body), full_ai_api.full_ai_test_photo(body),
                                   return_exceptions=True)
        assert len(calls) == 5 and all(isinstance(e, RuntimeError) for e in got), got
        assert full_ai_api._photos_running == {}, full_ai_api._photos_running
    finally:
        (full_ai_api.assert_account_owned, full_ai_api.require_opt_in_kind, full_ai_photo.upload_still,
         full_ai_turn.stored_config, inbound_describe.describe_upload) = saved


_harness.run()
