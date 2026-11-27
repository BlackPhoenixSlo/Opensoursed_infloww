#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()
_harness.make_client()

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from send_site_inventory import inventory  # noqa: E402

import accounts  # noqa: E402
import _send_kill as sk  # noqa: E402
import _send_kill_anchors  # noqa: E402
import _send_kill_held
import _send_kill_cell  # noqa: E402
import _send_kill_chat  # noqa: E402
import _send_kill_closing  # noqa: E402
import _send_kill_hold  # noqa: E402
import _send_kill_http  # noqa: E402
import _send_kill_jobs  # noqa: E402
import _send_kill_manual  # noqa: E402
import _send_kill_markers  # noqa: E402
import _send_kill_paused  # noqa: E402

accounts.get_account = lambda aid: {"id": aid, "nickname": aid}
accounts.get_platform = lambda aid: "onlyfans"

KINDS = [*_send_kill_http.DRIVERS, *_send_kill_jobs.DRIVERS, *_send_kill_markers.DRIVERS,
         *_send_kill_chat.DRIVERS]
_store: dict = {}


def _case(d: sk.Driver):
    async def case():
        got = {cut: await sk.run_cell(d, cut) for cut in sk.CUTS}
        sk.check_kind(d, got, _store)
    case.__name__ = f"case_{d.kind}"
    return case


SITE_DRIVERS = {
    "automations/mass_premade.py:run:send_mass_run": ("mass_premade",),
    "automations/lifecycle_messages.py:sweep:send_dropping_bad_media_sync": ("lifecycle_initial",),
    "automations/autoreply.py:run:send_message": ("autoreply",),
    "automations/full_ai_live.py:_dm:send_message": ("full_ai_live",),
    "automations/full_ai_live.py:send_ppv:send_priced": ("full_ai_ppv",),
    "automations/full_ai_ppv.py:send_priced.post:send_dropping_bad_media": ("full_ai_ppv",),
    "automations/lifecycle_messages.py:run_follow_up:send_message": ("lifecycle",),
    "automations/nudge_online_fire.py:run:send_dropping_bad_media": ("nudge",),
    "automations/priority_mass.py:_leg:send_message": ("priority_mass",),
    "automations/purchase_followup.py:run:send_dropping_bad_media_sync": ("purchase_followup",),
    "automations/reply_mass_funnel.py:_send_step:send_message": ("funnel",),
    "automations/scheduled_send.py:run:send_message": ("scheduled_send",),
    "automations/send_followup.py:run:send_dropping_bad_media": ("followup",),
    "automations/send_mass_message.py:_run:send_mass_message": ("mass_job",),
    "automations/send_welcome.py:_send_bubble:send_dropping_bad_media": ("send_welcome",),
    "automations/welcome_chatter_for_info.py:_turn_send_bubbles:send_message": ("welcome_chatter",),
    "automations/welcome_chatter_for_info.py:_send_closing_ppv.send:send_message": ("welcome_closing_ppv",),
    "mass_queue_api.py:of_send_or_schedule_mass:_send_or_schedule_mass": ("manual_mass_send", "manual_mass_schedule"),
    "mass_queue_api.py:_send_or_schedule_mass:schedule_mass_message": ("manual_mass_schedule",),
    "mass_queue_api.py:_send_or_schedule_mass:send_mass_message": ("manual_mass_send",),
    "server.py:send_message.send:send_message": ("composer_shim",),
    "server.py:send_message.send:post_message": ("composer",),
    "server.py:of_publish_schedule.send:publish_schedule": ("publish_now",),
    "server.py:of_restrict_user:send_message": ("restrict_ack",),
    "server.py:of_schedule_message.send:schedule_message": ("native_schedule",),
    "vault_upload.py:_send:materialize_via_message": ("vault_send",),
}
SITE_EXCEPTIONS = {
    "automations/_send_failure.py:send_dropping_bad_media._post:send_message": (1, "shared media fallback"),
    "automations/_send_failure.py:send_dropping_bad_media_sync:send_message": (2, "normal and media fallback transports"),
    "automations/full_ai_catchup.py:run_pass:catchup_queue": (1, "enqueues only; full_ai_live drives the consumer"),
    "automations/full_ai_ppv.py:send_priced.post:send_message": (1, "text-only branch of the priced-send driver"),
    "automations/send_welcome.py:_send_bubble:send_message": (1, "GIF branch of the welcome driver"),
    "automations/welcome_chatter_for_info.py:_turn_send_sticker:send_message": (1, "sticker variant of the chatter welcome"),
    "mass_queue_api.py:of_save_mass_for_later:of_send_or_schedule_mass": (1, "delegates to the manual schedule route"),
    "of_sends.py:send_message:post_message": (1, "shared OF transport"),
    "of_upload.py:materialize_via_message:send_message": (1, "transport driven by the vault send driver"),
}


def case_production_send_sites_have_a_driver_or_exception():
    actual = inventory().calls
    assert SITE_DRIVERS.keys().isdisjoint(SITE_EXCEPTIONS)
    expected = dict.fromkeys(SITE_DRIVERS, 1) | {k: n for k, (n, _) in SITE_EXCEPTIONS.items()}
    differences = {k: (expected.get(k), actual.get(k)) for k in actual.keys() | expected.keys()
                   if expected.get(k) != actual.get(k)}
    assert not differences, differences
    assert {d.kind for d in KINDS} == {k for kinds in SITE_DRIVERS.values() for k in kinds}


def case_aliased_send_import_is_inventoried():
    from collections import Counter
    from send_site_inventory import scan

    calls: Counter = Counter()
    scan("automations/fixture.py", "async def run():\n    await go()\n"
                                   "from automations._mass import send_mass_run as go\n", calls)
    assert calls == Counter({"automations/fixture.py:run:send_mass_run": 1}), calls


def case_unknown_selected_kind_is_refused():
    known = {d.kind for d in KINDS}
    for value, want in (("composre", ["composre"]), ("composer,", [""]), (",", [""]), ("composer", [])):
        with patch.dict(os.environ, {"SEND_KILL_KINDS": value}):
            assert sk.unknown_kinds(known) == want, (value, sk.unknown_kinds(known))


def case_golden_names_exactly_the_kinds():
    if sk.writing() or os.environ.get("SEND_KILL_KINDS"):
        return
    assert sorted(sk.golden()) == sorted(d.kind for d in KINDS), (
        sorted(sk.golden()), sorted(d.kind for d in KINDS))


async def case_cell_mode_composer_send_goes_out_once():
    if sk.writing():
        return
    failed = _send_kill_cell.report(await _send_kill_cell.run_all())
    assert not failed, f"Cell mode composer checks red: {failed}"


async def case_cell_mode_automations_send_once_from_saved_anchors():
    if sk.writing():
        return
    only = os.environ.get("SEND_KILL_KINDS")
    pick = (lambda ks: [k for k in ks if k in only.split(",")]) if only else (lambda ks: list(ks))
    anchored, gaps = pick(_send_kill_anchors.ANCHORED), pick(_send_kill_anchors.GAPS)
    if not anchored and not gaps:
        print("[skip] filter selected no Cell automation kinds")
        return
    failed = _send_kill_cell.report(await _send_kill_anchors.run_all(anchored, gaps))
    assert not failed, f"Cell mode automation checks red: {failed}"


async def case_cell_mode_manual_sends_go_out_once():
    if sk.writing():
        return
    failed = _send_kill_cell.report(await _send_kill_manual.run_all())
    assert not failed, f"Cell mode manual send checks red: {failed}"


async def case_cell_mode_closing_ppv_goes_out_once():
    if sk.writing():
        return
    failed = _send_kill_cell.report(await _send_kill_closing.run_all())
    assert not failed, f"Cell mode closing PPV checks red: {failed}"


async def case_cell_mode_lapsed_permit_writes_paused():
    if sk.writing():
        return
    failed = _send_kill_cell.report(await _send_kill_paused.run())
    assert not failed, f"Cell mode send permit checks red: {failed}"


async def case_restore_copy_holds_automations_until_release():
    if sk.writing():
        return
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        failed = _send_kill_cell.report(await _send_kill_hold.run_all(Path(tmp)))
    assert not failed, f"restore Cell hold checks red: {failed}"


async def case_retry_refusal_is_recorded():
    driver = next(d for d in KINDS if d.kind == "funnel")
    aid = "sk_retry_inflight"
    wire = sk.Wire("accepted", None)
    ctx = await driver.setup(aid, wire)
    with sk._install(ctx):
        assert await sk._maybe(driver.first, ctx)
        count, refusals = await sk._retry_all(aid)
    assert count == 0 and refusals == ["funnel:409"], (count, refusals)


async def case_async_update_probe_waits_for_the_durable_marker():
    from db.engine import get_session
    from sqlalchemy import text

    aid = "sk_async_probe"
    await sk.seed_account(aid)
    wire = sk.Wire("after_update", None)
    wire.hit("fixture")

    async def updated():
        return sk.db_row("SELECT nickname FROM accounts WHERE id=?", (aid,)) == ("updated",)

    async def write(_):
        async with get_session() as session:
            await session.commit()
            await session.execute(text("UPDATE accounts SET nickname='updated' WHERE id=:aid"), {"aid": aid})
            await session.commit()

    with sk._cut_after_update(wire, updated):
        assert await sk._maybe(write, None)
    assert await updated() and wire.killed_at == "after_update"


def case_na_snapshot_tracks_new_account_tables():
    import sqlite3

    table = "send_cut_snapshot_fixture"
    aid = "sk_snapshot"
    with sqlite3.connect(_harness.DB_PATH) as conn:
        conn.execute(f"CREATE TABLE {table} (account_id TEXT, marker TEXT)")
        try:
            before = sk._durable_send_state(aid)
            conn.execute(f"INSERT INTO {table} VALUES (?, ?)", ("another_account", "claimed"))
            conn.commit()
            assert sk._durable_send_state(aid) == before
            conn.execute(f"INSERT INTO {table} VALUES (?, ?)", (aid, "claimed"))
            conn.commit()
            assert sk._durable_send_state(aid) != before
        finally:
            conn.execute(f"DROP TABLE {table}")


async def case_scheduled_resubmit_uses_one_wire_op():
    import automation_executor as ax
    import dm_rate
    import server
    from types import SimpleNamespace

    cell = _send_kill_cell
    await cell._seed()
    cell.restart()
    at = "2000-01-01T12:00:00Z"
    for fallback in (False, True):
        fan = next(cell._fans)
        req = cell.request({"x-op-id": f"same-schedule-{fallback}"})
        http = cell.FakeHttp()
        with cell.cells(), cell.route(req, cell.client(http)), patch.object(ax, "_make_client", lambda _: cell.client(http)):
            if fallback:
                platform = SimpleNamespace(
                    lacks={server.platforms.Lack.SERVER_SCHEDULE},
                    backend=SimpleNamespace(check_sendable=lambda **_: None, Shim=SimpleNamespace(send_refusal=lambda _: None)))
                with patch.object(server.platforms, "for_account", return_value=platform):
                    for _ in range(2):
                        await server.of_schedule_message(fan, req, server._ScheduleMessageBody(text="once", scheduled_date=at))
            else:
                for _ in range(2):
                    await server.create_scheduled_send(req, server._ScheduledSendBody(fan_id=fan, text="once", run_at=at))
            dm_rate._reset()
            _send_kill_jobs._ungate(cell.AID)
            result = await ax.run_once(cell.AID, "scheduled_send", job_only=True)
            assert result.get("status") == "ok", result
            assert await ax.run_once(cell.AID, "scheduled_send", job_only=True) == {
                "status": "skipped", "reason": "no_job"}
        assert len(http.accepts) == 1, (fallback, http.calls)


async def case_cancelled_schedule_resubmit_cannot_deliver():
    import asyncio
    import automation_executor as ax
    import dm_rate
    import server
    from types import SimpleNamespace

    cell = _send_kill_cell
    await cell._seed()
    cell.restart()
    at = "2000-01-01T12:00:00Z"
    for fallback in (False, True):
        fan = next(cell._fans)
        req = cell.request({"x-op-id": f"cancel-schedule-{fallback}"})
        http = cell.FakeHttp()
        with cell.cells(), cell.route(req, cell.client(http)), patch.object(ax, "_make_client", lambda _: cell.client(http)):
            if fallback:
                platform = SimpleNamespace(
                    lacks={server.platforms.Lack.SERVER_SCHEDULE},
                    backend=SimpleNamespace(check_sendable=lambda **_: None, Shim=SimpleNamespace(send_refusal=lambda _: None)))
                with patch.object(server.platforms, "for_account", return_value=platform):
                    first, second = await asyncio.gather(*(server.of_schedule_message(
                        fan, req, server._ScheduleMessageBody(text="once", scheduled_date=at)) for _ in range(2)))
            else:
                first, second = await asyncio.gather(*(server.create_scheduled_send(
                    req, server._ScheduledSendBody(fan_id=fan, text="once", run_at=at)) for _ in range(2)))
            cancelled = await server.cancel_scheduled_send(req, second["job_id"])
            dm_rate._reset()
            _send_kill_jobs._ungate(cell.AID)
            await ax.run_once(cell.AID, "scheduled_send")
        assert cancelled["cancelled"] and first["job_id"] == second["job_id"] and not http.accepts, (
            fallback, first, second, cancelled, http.calls)


async def case_resubmit_after_cancel_schedules_again():
    import automation_executor as ax
    import dm_rate
    import server

    cell = _send_kill_cell
    await cell._seed()
    cell.restart()
    fan = next(cell._fans)
    req = cell.request({"x-op-id": "resubmit-after-cancel"})
    http = cell.FakeHttp()
    body = server._ScheduledSendBody(fan_id=fan, text="again", run_at="2000-01-01T12:00:00Z")
    with cell.cells(), cell.route(req, cell.client(http)), patch.object(ax, "_make_client", lambda _: cell.client(http)):
        first = await server.create_scheduled_send(req, body)
        cancelled = await server.cancel_scheduled_send(req, first["job_id"])
        second = await server.create_scheduled_send(req, body)
        third = await server.create_scheduled_send(req, body)
        dm_rate._reset()
        _send_kill_jobs._ungate(cell.AID)
        await ax.run_once(cell.AID, "scheduled_send")
    assert cancelled["cancelled"] and second["job_id"] != first["job_id"], (first, second)
    assert third["job_id"] == second["job_id"] and len(http.accepts) == 1, (second, third, http.calls)


async def case_cancelled_wire_and_stale_claim_are_held():
    import asyncio
    import send_ops

    cell = _send_kill_cell
    await cell._seed()
    cell.restart()

    async def cancel():
        raise asyncio.CancelledError

    with cell.cells():
        try:
            await send_ops.adispatch("onlyfans", cell.AID, "cancelled", "composer", "8", "digest", cancel)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed")
        assert any(row["op_id"] == "cancelled" for row in send_ops.uncertain(cell.AID))

        send_ops.begin("onlyfans", cell.AID, "stale", "composer", "9", "digest")
        with send_ops._connect() as db:
            assert db.execute("PRAGMA synchronous").fetchone() == (2,)
            db.execute("UPDATE send_ops SET updated_at='2000-01-01' WHERE account=? AND op_id='stale'", (cell.AID,))
        assert any(row["op_id"] == "stale" for row in send_ops.uncertain(cell.AID))
        with send_ops._connect() as db:
            plan = db.execute("EXPLAIN QUERY PLAN SELECT target FROM send_ops"
                              " WHERE account=? AND state IN ('uncertain','claimed')", (cell.AID,)).fetchall()
        assert any("send_ops_held" in row[-1] for row in plan), plan
        try:
            send_ops.begin("onlyfans", cell.AID, "automated", "send_welcome", "9", "digest")
        except send_ops.SendRefused as e:
            assert e.detail["error"] == "fan_held"
        else:
            raise AssertionError("stale claim did not hold its fan")


async def case_explicit_broadcast_excludes_held_fan():
    import send_ops

    aid = "broadcast_held_fan"
    cell = _send_kill_cell
    wire = sk.Wire("clean", None)
    driver = next(d for d in KINDS if d.kind == "mass_job")
    cell.restart()
    with cell.cells(accounts=f"onlyfans:{aid}"):
        ctx = await driver.setup(aid, wire)
        send_ops.begin("onlyfans", aid, "held-recipient", "composer", str(_send_kill_jobs.FAN), "digest")
        http = _send_kill_anchors._WireHttp(wire)
        with _send_kill_anchors._real_sends(http), sk._install(ctx):
            result = await driver.first(ctx)
    assert result.get("reason") == "fan_held" and not wire.accepts, (result, wire.accepts)
    assert sk.db_row("SELECT status FROM automation_runs WHERE id=?", (result["run_id"],)) == ("skipped",)
    assert sk.db_row("SELECT status FROM scheduled_jobs WHERE id=?", (ctx["job"],)) == ("done",)


async def case_paid_online_broadcast_excludes_held_fan():
    import automation_executor as ax
    import send_ops

    aid = "broadcast_online_held_fan"
    cell = _send_kill_cell
    wire = sk.Wire("clean", None)
    driver = next(d for d in KINDS if d.kind == "mass_job")
    held, clear = _send_kill_jobs.FAN, _send_kill_jobs.FAN + 1
    cell.restart()
    with cell.cells(accounts=f"onlyfans:{aid}"):
        await sk.seed_account(aid)
        await ax.enqueue_job(aid, "send_mass_message", payload={
            "text": "paid online", "included_users": [held, clear], "online_only": True, "price": 10})
        send_ops.begin("onlyfans", aid, "held-online", "composer", str(held), "digest")
        http = cell.FakeHttp()
        with patch.object(ax, "_make_client", return_value=cell.client(http)):
            result = await driver.first({"aid": aid, "kind": "send_mass_message"})
    assert http.calls and http.calls[-1][2]["userIds"] == [clear], (result, http.calls)


async def case_no_anchor_closes_due_job_and_records_skip():
    import automation_executor as ax
    from datetime import datetime

    aid = "no_anchor_due_job"
    await sk.seed_account(aid)
    with _send_kill_cell.cells(accounts=f"onlyfans:{aid}"):
        empty = await ax.run_once(aid, "send_followup")
        assert empty == {"status": "skipped", "reason": "no_anchor"}, empty
        assert sk.db_row("SELECT count(*) FROM automation_runs WHERE account_id=?", (aid,)) == (0,)
        job = await ax.enqueue_job(aid, "send_followup", run_at=datetime(2000, 1, 1))
        result = await ax.run_once(aid, "send_followup")
    assert result.get("reason") == "no_anchor" and result.get("run_id"), result
    assert sk.db_row("SELECT status FROM scheduled_jobs WHERE id=?", (job,)) == ("done",)
    assert sk.db_row("SELECT status FROM automation_runs WHERE id=?", (result["run_id"],)) == ("skipped",)


async def case_lifecycle_releases_event_claim_while_fan_is_held():
    from fastapi import HTTPException
    import send_ops

    cell = _send_kill_cell
    for kind, event_claimed in (("lifecycle", _send_kill_jobs._lifecycle_claimed),
                                ("lifecycle_initial", _send_kill_jobs._initial_claim)):
        aid = f"held_{kind}"
        driver = next(d for d in KINDS if d.kind == kind)
        wire = sk.Wire("clean", None)
        cell.restart()
        with cell.cells(accounts=f"onlyfans:{aid}"):
            ctx = await driver.setup(aid, wire)

            def timeout():
                raise TimeoutError("reply lost")

            try:
                send_ops.dispatch("onlyfans", aid, "held-event", "composer", str(_send_kill_jobs.FAN), "d", timeout)
            except HTTPException as exc:
                assert exc.status_code == 502 and exc.detail["op_state"] == "uncertain", exc.detail
            else:
                raise AssertionError("transport timeout was swallowed")
            assert str(_send_kill_jobs.FAN) in send_ops.held_targets(aid)
            with _send_kill_anchors._real_sends(_send_kill_anchors._WireHttp(wire)), sk._install(ctx):
                await driver.first(ctx)
            assert not event_claimed(ctx) and not wire.accepts, kind


def case_wrapped_send_refusal_classification():
    import send_ops

    for reason, skip in (("fan_held", "fan_held"), ("writes_paused", None), ("not_a_refusal", None)):
        try:
            try:
                raise send_ops.SendRefused(409, reason)
            except send_ops.SendRefused as exc:
                raise RuntimeError("wrapped") from exc
        except RuntimeError as wrapped:
            if reason == "writes_paused":
                try:
                    send_ops.skip_fan(wrapped)
                except RuntimeError as exc:
                    assert exc is wrapped
                else:
                    raise AssertionError("run refusal did not propagate")
            else:
                assert send_ops.skip_fan(wrapped) == skip


async def case_resolved_send_replays_a_single_internal_marker():
    import send_ops

    cell = _send_kill_cell
    await cell._seed()
    cell.restart()
    with cell.cells():
        platform, op, target, dig = send_ops._automated_op(cell.AID, "full_ai_ppv", "45", "88", 0, None)
        send_ops.begin(platform, cell.AID, op, "full_ai_ppv", target, dig)
        cell.restart()
        assert send_ops.resolve(cell.AID, op, True, "test")
        assert send_ops.reconciled(cell.AID, "full_ai_ppv", target, "88")
        result, replay = send_ops.begin(platform, cell.AID, op, "full_ai_ppv", target, dig)
        assert replay and not isinstance(result, dict), result
        assert send_ops.is_reconciled(result)


if __name__ == "__main__":
    if "--break" in sys.argv:
        mutant = sys.argv[sys.argv.index("--break") + 1]
        if mutant.startswith("manual:"):
            sys.exit(_send_kill_manual.run_mutant(mutant.removeprefix("manual:")))
        mod = _send_kill_anchors if mutant in _send_kill_anchors.MUTANTS else _send_kill_cell
        sys.exit(mod.run_mutant(mutant))
    assert len({d.kind for d in KINDS}) == len(KINDS), "duplicate kind"
    if unknown := sk.unknown_kinds({d.kind for d in KINDS}):
        raise SystemExit(f"SEND_KILL_KINDS names no send kind: {unknown}")
    _harness.run(case_production_send_sites_have_a_driver_or_exception, case_aliased_send_import_is_inventoried,
                 case_unknown_selected_kind_is_refused, case_golden_names_exactly_the_kinds,
                 *(_case(d) for d in KINDS if sk.selected(d.kind)), case_retry_refusal_is_recorded,
                 case_async_update_probe_waits_for_the_durable_marker, case_na_snapshot_tracks_new_account_tables,
                 case_cell_mode_composer_send_goes_out_once, case_cell_mode_closing_ppv_goes_out_once,
                 case_cell_mode_manual_sends_go_out_once, case_cell_mode_lapsed_permit_writes_paused,
                 case_scheduled_resubmit_uses_one_wire_op, case_cancelled_schedule_resubmit_cannot_deliver,
                 case_resubmit_after_cancel_schedules_again,
                 case_cancelled_wire_and_stale_claim_are_held,
                 case_explicit_broadcast_excludes_held_fan, case_paid_online_broadcast_excludes_held_fan,
                 _send_kill_held.case_stale_resolution_cannot_release_new_attempt,
                 _send_kill_paused.case_single_box_ignores_leftover_permit,
                 case_no_anchor_closes_due_job_and_records_skip,
                 case_lifecycle_releases_event_claim_while_fan_is_held,
                 case_restore_copy_holds_automations_until_release, case_wrapped_send_refusal_classification,
                 case_resolved_send_replays_a_single_internal_marker,
                 case_cell_mode_automations_send_once_from_saved_anchors)
    sk.write_golden(_store)
