#!/usr/bin/env python3
"""
vault_import_decide — table tests over the pure rules the vault import routes
(vault_import_api) hand off. The routes themselves are walked by
test_vault_import_extras, test_vault_drive_configured and test_http_hooks.

  case_batch_body_refusal_table:  411 no / junk / zero length (no disk read),
                                  413 over the room, two copies on one device,
                                  the free floor, the run cap.
  case_fan_mismatch_table:        same fan, other id, id without name, neither.
  case_metas_for_parts_table:     metas shorter / longer than parts, nameless
                                  parts skipped without shifting.
  case_status_body_table:         a count per real item status, an unknown
                                  status counted nowhere but `total`, and the
                                  route's final key order (run fields + card).

No DB, no OF. Run: venv/bin/python service/tests/test_vault_import_decide.py
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from types import SimpleNamespace  # noqa: E402

import vault_import_decide as d  # noqa: E402
from vault_upload import ITEM_STATUSES  # noqa: E402

_GB = 10 ** 9


def _table(rows, fn) -> None:
    """Run every row, collect every mismatch, fail once naming them all."""
    bad = [f"{rid}: {got!r} != {want!r}" for rid, args, want in rows if (got := fn(*args)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def _disk(free, same_device):
    return lambda: (free, same_device)


def _caps(min_free=0, max_files=40, max_dl=100 * _GB):
    return lambda: SimpleNamespace(min_free_bytes=min_free, max_files=max_files, max_download_bytes=max_dl)


def _no_disk():
    raise AssertionError("measured the disk")


def _status(length, measure, limits=_caps()):
    got = d.batch_body_refusal(length, measure, limits)
    return got and got[0]


def case_batch_body_refusal_table():
    _table([
        ("no length header -> 411, no disk read", (None, _no_disk, _no_disk), 411),
        ("empty length -> 411", ("", _no_disk, _no_disk), 411),
        ("invalid length -> 411", ("abc", _no_disk, _no_disk), 411),
        ("zero length -> 411", ("0", _no_disk, _no_disk), 411),
        ("negative length -> 411", ("-5", _no_disk, _no_disk), 411),
        ("two devices, fits -> in", (str(4 * _GB), _disk(10 * _GB, False)), None),
        ("two devices, exactly the room -> in", (str(10 * _GB), _disk(10 * _GB, False)), None),
        ("two devices, over the room -> 413", (str(11 * _GB), _disk(10 * _GB, False)), 413),
        ("one device, two copies over half -> 413", (str(6 * _GB), _disk(10 * _GB, True)), 413),
        ("one device, two copies at half -> in", (str(5 * _GB), _disk(10 * _GB, True)), None),
        ("free floor taken off -> 413", (str(9 * _GB), _disk(10 * _GB, False), _caps(2 * _GB)), 413),
        ("floor past free, room 0 -> 413", ("1", _disk(_GB, False), _caps(2 * _GB)), 413),
        ("run cap tighter than disk -> 413", ("11", _disk(10 * _GB, False), _caps(0, 2, 5)), 413),
    ], _status)
    # Texts byte-identical to the pre-move server.py.
    assert d.batch_body_refusal(None, _no_disk, _no_disk) == (411, (
        "this upload needs a content-length — the server has to know how big a batch is before it starts "
        "writing it to disk, and a chunked body cannot be measured until it has already landed there. Send it "
        "as a normal form upload, or (if a proxy in front of the relay re-encodes the body) import from Google "
        "Drive links instead."))
    assert d.batch_body_refusal(str(int(12.34 * _GB)), _disk(10 * _GB, True), _caps()) == (413, (
        "that batch is 12.3 GB; this server can stage at most 5.0 GB right now. Import it in smaller batches, "
        "or from Google Drive links, which are fetched one file at a time."))


def case_fan_mismatch_table():
    fan = {"id": 42, "username": "amy", "name": "Amy"}
    other = ("@amy is not the fan account that was checked "
             "— check the username again before importing")
    _table([
        ("checked id matches", (fan, "42"), None),
        ("checked id matches, padded", (fan, " 42\n"), None),
        ("fan renamed / other id -> refuse", (fan, "43"), other),
        ("fan resolved but no checked id -> refuse", (fan, ""), other),
        ("checked id without a username -> refuse", (None, "42"), "fan_id without fan_username"),
        ("carrier path: no fan, no id", (None, ""), None),
        ("carrier path: blank id", (None, "  "), None),
    ], d.fan_mismatch)


def case_metas_for_parts_table():
    a, b, c = {"notes": "a"}, {"notes": "b"}, {"notes": "c"}
    _table([
        ("one meta per part", (["x", "y"], [a, b]), [a, b]),
        ("metas shorter than parts -> None for the rest", (["x", "y", "z"], [a]), [a, None, None]),
        ("metas longer than parts -> extra ignored", (["x"], [a, b, c]), [a]),
        ("no metas -> None each", (["x", "y"], []), [None, None]),
        ("nameless part skipped, nobody shifts", (["x", "", "z"], [a, b, c]), [a, c]),
        ("None-named part skipped, nobody shifts", ([None, "y"], [a, b]), [b]),
        ("no parts", ([], [a]), []),
    ], d.metas_for_parts)


# The status route's answer for a run, key for key, as the pre-move server.py built it.
_ROUTE_KEYS = ["running", "run_id", "status", "phase", "error", "filing_error", "details_saved", "fan_id",
               "finished_at", "total", *ITEM_STATUSES, "carriers_undeletable", "carriers_unrecorded", "items",
               "drive_import_configured", "upload_limits", "details_saved_here"]


def case_status_body_table():
    assert "uploading" in ITEM_STATUSES, ITEM_STATUSES
    items = [{"name": "a", "status": "done"}, {"name": "b", "status": "done"},
             {"name": "c", "status": "failed"}, {"name": "d", "status": "uploading"},
             {"name": "e", "status": "not-a-status"}]
    state = {"run_id": "r1", "account_id": "1", "status": "running", "phase": "upload", "items": items,
             "fan_id": 9, "finished_at": None}
    body = d.status_body(state, ITEM_STATUSES, (3, 1))
    _table([
        ("pending counted (none)", ("pending",), 0),
        ("uploading counted", ("uploading",), 1),
        ("done counted", ("done",), 2),
        ("failed counted", ("failed",), 1),
        ("skipped counted (none)", ("skipped",), 0),
        ("total includes the unknown status", ("total",), 5),
        ("running from run status", ("running",), True),
        ("run_id passed through", ("run_id",), "r1"),
        ("fan_id passed through", ("fan_id",), 9),
        ("missing field -> None", ("error",), None),
        ("carriers undeletable from the roll-up", ("carriers_undeletable",), 3),
        ("carriers unrecorded from the roll-up", ("carriers_unrecorded",), 1),
    ], body.get)
    assert "not-a-status" not in body and body["items"] is items
    # The route appends the card's fields; the final order is the pre-move one.
    card = {"drive_import_configured": True, "upload_limits": {"max_file_mb": 200, "max_files": 40},
            "details_saved_here": False}
    assert list({**body, **card}) == _ROUTE_KEYS, list({**body, **card})
    empty = d.status_body({"status": "done", "items": None}, ITEM_STATUSES, (0, 0))
    assert empty["total"] == 0 and empty["items"] == [] and empty["running"] is False
    assert all(empty[s] == 0 for s in ITEM_STATUSES), empty


_harness.run()
