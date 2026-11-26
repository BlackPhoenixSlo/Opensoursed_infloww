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
    failed = _send_kill_cell.report(await _send_kill_anchors.run_all(
        pick(_send_kill_anchors.ANCHORED), pick(_send_kill_anchors.GAPS)))
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
                 case_restore_copy_holds_automations_until_release,
                 case_cell_mode_automations_send_once_from_saved_anchors)
    sk.write_golden(_store)
