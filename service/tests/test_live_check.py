#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
from unittest.mock import patch  # noqa: E402

import accounts  # noqa: E402
import automation_executor  # noqa: E402
import automation_registry  # noqa: E402
import fansly_backend  # noqa: E402
import platforms  # noqa: E402
import side_effect_gate as gate  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402
from fansly_shim import marker_calls, platform_live_check  # noqa: E402
from side_effect_gate import FanTarget, ListAudience, ListTarget  # noqa: E402

AID, OTHER = "acc_live", "acc_other"
FAN, FAN2 = "fan_1", "fan_2"
LACKS = "platform_lacks:poke_fan"


async def _account() -> None:
    async with get_session() as s:
        s.add(Account(id=AID, nickname=AID))


asyncio.run(_account())


def _env(value: str | None):
    return _unset() if value is None else patch.dict(os.environ, {"PLATFORM_LIVE_CHECK": value})


@contextlib.contextmanager
def _unset():
    saved = os.environ.pop("PLATFORM_LIVE_CHECK", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["PLATFORM_LIVE_CHECK"] = saved


def case_live_check_table():
    rows = [
        ("no grant", None, "poke_fan", frozenset({FAN}), LACKS),
        ("bare entry", f"{AID}:poke_fan", "poke_fan", frozenset({FAN}), LACKS),
        ("target-less entry", f"{AID}:poke_fan:fan=", "poke_fan", frozenset({FAN}), LACKS),
        ("whitespace around separators", f"{AID} : poke_fan : fan = {FAN}", "poke_fan", frozenset({FAN}), LACKS),
        ("upper-case kind", f"{AID}:poke_fan:FAN={FAN}", "poke_fan", frozenset({FAN}), LACKS),
        ("upper-case method", f"{AID}:Poke_Fan:fan={FAN}", "Poke_Fan", frozenset({FAN}), "platform_lacks:Poke_Fan"),
        ("id with a colon", f"{AID}:poke_fan:fan=a:b", "poke_fan", frozenset({"a:b"}), LACKS),
        ("id with an equals sign", f"{AID}:poke_fan:fan=a=b", "poke_fan", frozenset({"a=b"}), LACKS),
        ("list= on a non-delete_list method", f"{AID}:poke_fan:list=L1", "poke_fan",
         ListAudience("L1", frozenset({FAN}), True), LACKS),
        ("another account", f"{OTHER}:poke_fan:fan={FAN}", "poke_fan", frozenset({FAN}), LACKS),
        ("another method", f"{AID}:block_user:fan={FAN}", "poke_fan", frozenset({FAN}), LACKS),
        ("another fan", f"{AID}:poke_fan:fan={FAN2}", "poke_fan", frozenset({FAN}), LACKS),
        ("two fans", f"{AID}:poke_fan:fan={FAN}", "poke_fan", frozenset({FAN, FAN2}), LACKS),
        ("empty audience", f"{AID}:poke_fan:fan={FAN}", "poke_fan", frozenset(), LACKS),
        ("unknown audience", f"{AID}:poke_fan:fan={FAN}", "poke_fan", [FAN], LACKS),
        ("list read holds two fans", f"{AID}:poke_fan:fan={FAN}", "poke_fan",
         ListAudience("L1", frozenset({FAN, FAN2}), True), LACKS),
        ("list read holds only another fan", f"{AID}:poke_fan:fan={FAN}", "poke_fan",
         ListAudience("L1", frozenset({FAN2}), True), LACKS),
        ("incomplete list read", f"{AID}:poke_fan:fan={FAN}", "poke_fan",
         ListAudience("L1", frozenset({FAN}), False), LACKS),
        ("truthy non-bool complete", f"{AID}:poke_fan:fan={FAN}", "poke_fan",
         ListAudience("L1", frozenset({FAN}), "False"), LACKS),
        ("list read members as a list", f"{AID}:poke_fan:fan={FAN}", "poke_fan",
         ListAudience("L1", [FAN], True), LACKS),
        ("list read of exactly the fan", f" {AID}:poke_fan:fan={FAN} ", "poke_fan",
         ListAudience("L1", frozenset({FAN}), True), None),
        ("exact single fan", f"x:y:fan=z, {AID}:poke_fan:fan={FAN}", "poke_fan", frozenset({FAN}), None),
        ("list= wrong list id", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}", "delete_list",
         ListAudience("L2", frozenset({FAN}), True), "platform_lacks:delete_list"),
        ("list= member outside granted fans", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}",
         "delete_list", ListAudience("L1", frozenset({FAN, FAN2}), True), "platform_lacks:delete_list"),
        ("list= fan granted on another account", f"{AID}:delete_list:list=L1,{OTHER}:poke_fan:fan={FAN}",
         "delete_list", ListAudience("L1", frozenset({FAN}), True), "platform_lacks:delete_list"),
        ("list= incomplete read", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}", "delete_list",
         ListAudience("L1", frozenset({FAN}), False), "platform_lacks:delete_list"),
        ("list= members as a list", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}", "delete_list",
         ListAudience("L1", [FAN], True), "platform_lacks:delete_list"),
        ("list= on a fan-id audience", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}", "delete_list",
         frozenset({FAN}), "platform_lacks:delete_list"),
        ("fan= on delete_list", f"{AID}:delete_list:fan={FAN}", "delete_list",
         frozenset({FAN}), "platform_lacks:delete_list"),
        ("list= members all granted", f"{AID}:delete_list:list=L1,{AID}:poke_fan:fan={FAN}", "delete_list",
         ListAudience("L1", frozenset({FAN}), True), None),
        ("list= on an empty Complete list", f"{AID}:delete_list:list=L1", "delete_list",
         ListAudience("L1", frozenset(), True), None),
    ]
    for name, env, method, audience, want in rows:
        with _env(env):
            got = gate.live_check(AID, method, audience)
        assert got == want, (name, got, want)


def case_unset_between_calls_takes_effect_without_restart():
    with _env(f"{AID}:poke_fan:fan={FAN}"):
        assert gate.live_check(AID, "poke_fan", frozenset({FAN})) is None
    with _env(None):
        assert gate.live_check(AID, "poke_fan", frozenset({FAN})) == LACKS
        assert gate.live_check_targets(AID, "poke_fan") == frozenset()
        assert gate.live_check_methods(AID) == frozenset()


def case_targets_and_methods_agree_with_live_check():
    env = (f"{AID}:poke_fan:fan={FAN}, {AID}:poke_fan:fan={FAN2},{AID}:delete_list:list=L1,"
           f"{AID}:block_user,{AID}:nudge_online:list=L9,{AID}:delete_list:fan={FAN},{OTHER}:block_user:fan={FAN}")
    with _env(env):
        assert gate.live_check_targets(AID, "poke_fan") == {FanTarget(FAN), FanTarget(FAN2)}
        assert gate.live_check_targets(AID, "delete_list") == {ListTarget("L1")}
        assert gate.live_check_targets(AID, "block_user") == frozenset()
        assert gate.live_check_targets(AID, "nudge_online") == frozenset()
        assert gate.live_check_methods(AID) == {"poke_fan", "delete_list"}
        assert gate.live_check_methods(OTHER) == {"block_user"}
        for method in ("poke_fan", "delete_list", "block_user", "nudge_online"):
            for t in gate.live_check_targets(AID, method):
                audience = frozenset({t.fan_id}) if isinstance(t, FanTarget) else ListAudience(
                    t.list_id, frozenset({FAN}), True)
                assert gate.live_check(AID, method, audience) is None, (method, t)
            assert gate.live_check(AID, method, frozenset({"fan_x"})) == f"platform_lacks:{method}", method


def case_an_inert_entry_warns_once():
    seen: list[str] = []

    class _Catch(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = _Catch(level=logging.WARNING)
    logging.getLogger("side_effect_gate").addHandler(handler)
    try:
        with _env(f"{AID}:warn_probe,{AID}:warn_probe:list=L1,{AID}:warn_probe:fan=a:b"):
            for _ in range(3):
                gate.live_check(AID, "warn_probe", frozenset({FAN}))
                gate.live_check_methods(AID)
    finally:
        logging.getLogger("side_effect_gate").removeHandler(handler)
    assert len(seen) == 3 and all("warn_probe" in m for m in seen), seen


class _LiveShim(fansly_backend.Shim):
    @platform_live_check("poke_fan: live check pending")
    def poke_fan(self, fan_id):
        REQUESTS.append(fan_id)
        return {"ok": True}


REQUESTS: list[str] = []


@contextlib.contextmanager
def _fansly_live_shim():
    with patch.object(fansly_backend, "Shim", _LiveShim), \
            patch.object(accounts, "get_platform", lambda aid: "fansly"):
        yield


def case_is_live_check_name_covers_marked_methods_and_lanes():
    unknown = platforms.get("myspace")
    assert not gate.is_live_check_name(platforms.FANSLY, "poke_fan")
    with _fansly_live_shim():
        assert gate.is_live_check_name(platforms.FANSLY, "poke_fan")
        assert not gate.is_live_check_name(platforms.FANSLY, "send_message")
        assert not gate.is_live_check_name(platforms.ONLYFANS, "poke_fan")
        assert not gate.is_live_check_name(unknown, "poke_fan")
    assert gate.LIVE_CHECK_LANES == frozenset({"priority_mass"})
    assert gate.is_live_check_name(platforms.FANSLY, "priority_mass")
    assert not gate.is_live_check_name(platforms.ONLYFANS, "priority_mass")
    with patch.object(gate, "LIVE_CHECK_LANES", frozenset({"test_lane"})):
        assert gate.is_live_check_name(platforms.FANSLY, "test_lane")
        assert not gate.is_live_check_name(platforms.ONLYFANS, "test_lane")
        assert not gate.is_live_check_name(unknown, "test_lane")
        assert not gate.is_live_check_name(platforms.FANSLY, "other_lane")


@automation_registry.register("live_check_probe")
async def _probe(aid, payload, *, run_id):
    if gate.is_live_check_name(platforms.for_account(aid), "poke_fan") and (
            reason := gate.live_check(aid, "poke_fan", frozenset({payload["fan"]}))):
        return {"reason": reason}
    _LiveShim.__new__(_LiveShim).poke_fan(payload["fan"])
    await automation_executor.enqueue_job(aid, "live_check_probe_follow_up")
    return {"sent": 1}


def _row_counts() -> dict[str, int]:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


async def _run(env: str | None) -> tuple[dict, dict[str, int], list[str]]:
    REQUESTS.clear()
    calls: list[str] = []
    token = marker_calls.set(calls)
    try:
        with _fansly_live_shim(), _env(env):
            await automation_executor.enqueue_job(AID, "live_check_probe", payload={"fan": FAN})
            before = _row_counts()
            result = await automation_executor.run_once(AID, "live_check_probe")
            after = _row_counts()
    finally:
        marker_calls.reset(token)
    delta = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
    return result, delta, calls


async def case_run_once_without_the_grant_persists_a_skipped_run_and_writes_nothing():
    result, delta, calls = await _run(f"{AID}:poke_fan:fan={FAN2}")
    assert (result["status"], result["reason"]) == ("skipped", LACKS), result
    assert delta == {"automation_runs": 1}, delta
    assert REQUESTS == [] and calls == [], (REQUESTS, calls)
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        status, stats = c.execute("SELECT status, stats_json FROM automation_runs WHERE id=?",
                                  (result["run_id"],)).fetchone()
        job = c.execute("SELECT status FROM scheduled_jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
    assert (status, json.loads(stats)["reason"], job) == ("skipped", LACKS, "done"), (status, stats, job)


async def case_run_once_with_the_exact_grant_proceeds():
    result, delta, calls = await _run(f"{AID}:poke_fan:fan={FAN}")
    assert result["status"] == "ok" and result["sent"] == 1, result
    assert delta == {"automation_runs": 1, "scheduled_jobs": 1}, delta
    assert REQUESTS == [FAN] and calls == ["poke_fan"], (REQUESTS, calls)


if __name__ == "__main__":
    _harness.run()
