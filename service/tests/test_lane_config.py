#!/usr/bin/env python3
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402


_OWNERS = {
    "IMG_FETCH_CONCURRENCY": 8,
    "STORYBOARD_BUILD_CONCURRENCY": 3,
    "HEALTH_ALL_CONCURRENCY": 24,
    "AUTOMATION_MAX_CONCURRENT_RUNS": 4,
    "RELAY_EXECUTOR_THREADS": 378,
    "ACCOUNT_LANE_BACKGROUND": 2,
}


def _fresh(tmp: Path, env: dict[str, str] | None = None, register: bool = True):
    for k in list(_OWNERS):
        os.environ.pop(k, None)
    os.environ["LANE_CONFIG_PATH"] = str(tmp)
    os.environ.update(env or {})
    sys.modules.pop("lane_config", None)
    lc = importlib.import_module("lane_config")
    if register:
        for env_var, default in _OWNERS.items():
            lc.resolve(env_var, default)
    return lc


def case_precedence_env_beats_stored_beats_default():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"

        lc = _fresh(p)
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 8, "no store, no env => default"
        assert next(r["source"] for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY") == "default"

        lc.set_many({"IMG_FETCH_CONCURRENCY": 12})
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 12, "stored beats default"
        assert next(r["source"] for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY") == "stored"

        lc = _fresh(p, {"IMG_FETCH_CONCURRENCY": "3"})
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 3, "env MUST beat stored"
        assert next(r["source"] for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY") == "env"
        assert lc.stored()["IMG_FETCH_CONCURRENCY"] == 12, (
            "the env var overrides the stored value, it does not erase it — "
            "unsetting it must restore what the panel saved"
        )


def case_none_deletes_the_override():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        lc.set_many({"HEALTH_ALL_CONCURRENCY": 16})
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 24) == 16
        lc.set_many({"HEALTH_ALL_CONCURRENCY": None})
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 24) == 24, "null => back to default"
        assert "HEALTH_ALL_CONCURRENCY" not in lc.stored(), "and gone from the file"


def case_floor_is_one_like_the_env_vars_it_replaced():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        assert lc.set_many({"STORYBOARD_BUILD_CONCURRENCY": 0})["STORYBOARD_BUILD_CONCURRENCY"] == 1
        assert lc.set_many({"STORYBOARD_BUILD_CONCURRENCY": -5})["STORYBOARD_BUILD_CONCURRENCY"] == 1


def case_unknown_knob_and_non_int_are_refused():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        for bad, why in ((
            {"TOTALLY_MADE_UP": 4}, "an unknown knob would be stored forever and never read"
        ), (
            {"IMG_FETCH_CONCURRENCY": "abc"}, "a non-int would poison the next boot"
        )):
            try:
                lc.set_many(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"set_many accepted {bad} — {why}")
        assert lc.stored() == {}, "a refused write must leave the store untouched"


def case_corrupt_store_boots_on_defaults():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        p.write_text('{"IMG_FETCH_CONCURRENCY": 12', encoding="utf-8")
        lc = _fresh(p)
        assert lc.stored() == {}, "corrupt store must read as empty"
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 8, "…and fall back to the default"

        p.write_text('["not", "an", "object"]', encoding="utf-8")
        lc = _fresh(p)
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 8, "wrong JSON type, same answer"

        p.write_text('{"RETIRED_KNOB": 3, "IMG_FETCH_CONCURRENCY": 12}', encoding="utf-8")
        lc = _fresh(p)
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 12, "a stale key must not poison siblings"


def case_write_is_atomic_and_survives_reimport():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "nested" / "lc.json"
        lc = _fresh(p)
        lc.set_many({"AUTOMATION_MAX_CONCURRENT_RUNS": 16, "IMG_FETCH_CONCURRENCY": 12})

        on_disk = json.loads(p.read_text("utf-8"))
        assert on_disk == {"AUTOMATION_MAX_CONCURRENT_RUNS": 16,
                           "IMG_FETCH_CONCURRENCY": 12}, on_disk
                # Derive the glob from p.name: a hardcoded prefix once stopped matching and masked a leaked temp file.
        assert not list(p.parent.glob("." + p.name + ".*")), (
            "temp file must not survive the write"
        )

        lc2 = _fresh(p)
        assert lc2.resolve("AUTOMATION_MAX_CONCURRENT_RUNS", 4) == 16, (
            "the whole point: a value saved from the panel must be there after a restart"
        )


# Deliberately unclamped: the endpoint is unauthenticated by owner choice; a clamp would be a gate they declined.
def case_no_upper_bound():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        assert lc.set_many({"RELAY_EXECUTOR_THREADS": 5000})["RELAY_EXECUTOR_THREADS"] == 5000


def case_the_registry_is_derived_not_declared():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"

        lc = _fresh(p, register=False)
        assert lc.describe() == [], "nothing resolved => nothing to show"
        assert lc.knob_names() == frozenset(), "…and nothing settable"
        try:
            lc.set_many({"IMG_FETCH_CONCURRENCY": 12})
        except ValueError:
            pass
        else:
            raise AssertionError(
                "storing a knob nothing reads writes a key no boot will consult"
            )

        lc = _fresh(p, register=False)
        lc.resolve("IMG_FETCH_CONCURRENCY", 99)
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert row["default"] == 99, row
        assert row["value"] == 99, row


def case_live_and_pending_track_the_running_process():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        lc = _fresh(p)

        rows = {r["name"]: r for r in lc.describe()}
        assert set(rows) == set(_OWNERS), "every resolved knob must appear"
        for r in rows.values():
            assert r["live"] is not None, f"{r['name']} has no live value: {r}"
            assert not r["pending"], "nothing saved yet, so nothing can be pending"

        lc.set_many({"IMG_FETCH_CONCURRENCY": 12})
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert (row["live"], row["value"], row["pending"]) == (8, 12, True), row

        lc = _fresh(p)
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert (row["live"], row["value"], row["pending"]) == (12, 12, False), row


def case_record_live_covers_a_clamped_knob():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        lc.set_many({"ACCOUNT_LANE_BACKGROUND": 9})
        lc.resolve("ACCOUNT_LANE_BACKGROUND", 2)
        lc.record_live("ACCOUNT_LANE_BACKGROUND", 4)
        row = next(r for r in lc.describe() if r["name"] == "ACCOUNT_LANE_BACKGROUND")
        assert row["live"] == 4, row
        assert row["pending"] is True, (
            "9 was saved but 4 is enforced — the panel must say so rather than "
            "pretend the save landed"
        )


def case_a_knob_read_at_use_is_live_from_the_save():
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        assert lc.resolve_live("AUTOMATION_RELEASE_SLOT_MIN_HOLD_S", 3) == 3
        lc.set_many({"AUTOMATION_RELEASE_SLOT_MIN_HOLD_S": 6, "IMG_FETCH_CONCURRENCY": 12})
        rows = {r["name"]: r for r in lc.describe()}
        row = rows["AUTOMATION_RELEASE_SLOT_MIN_HOLD_S"]
        assert (row["live"], row["value"], row["pending"]) == (6, 6, False), row
        assert not row["switch"], row
        assert rows["IMG_FETCH_CONCURRENCY"]["pending"] is True, rows["IMG_FETCH_CONCURRENCY"]
        assert lc.resolve_live("AUTOMATION_RELEASE_SLOT_MIN_HOLD_S", 3) == 6


def case_a_switch_holds_zero_and_one_and_nothing_else():
    knob = "AUTOMATION_RELEASE_SLOT_ON_HOLD"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "lc.json"
        os.environ.pop(knob, None)
        lc = _fresh(f)
        assert lc.resolve_switch(knob, True) is True
        assert lc.set_many({knob: 0})[knob] == 0
        for bad in (2, -1, "maybe"):
            try:
                lc.set_many({knob: bad})
            except ValueError as e:
                assert "switch" in str(e), e
            else:
                raise AssertionError(f"{bad!r} was accepted for a switch")
        assert lc.set_many({"STORYBOARD_BUILD_CONCURRENCY": 0})["STORYBOARD_BUILD_CONCURRENCY"] == 1
        raw = json.loads(f.read_text())
        raw["HEALTH_ALL_CONCURRENCY"] = 0
        f.write_text(json.dumps(raw))
        lc = _fresh(f)
        assert lc.resolve_switch(knob, True) is False, "a stored 0 must survive the reload"
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 24) == 1
        row = next(r for r in lc.describe() if r["name"] == knob)
        assert row["switch"] and row["default"] == 1 and row["value"] == row["live"] == 0, row
        assert not row["pending"], row
        assert not next(r for r in lc.describe() if r["name"] == "HEALTH_ALL_CONCURRENCY")["switch"]
        for word, want in (("on", True), ("1", True), ("false", False), ("OFF", False)):
            os.environ[knob] = word
            try:
                assert lc.resolve_switch(knob, False) is want, word
            finally:
                del os.environ[knob]
        os.environ[knob] = "sometimes"
        try:
            assert lc.resolve_switch(knob, True) is False
        finally:
            del os.environ[knob]


_harness.run(
    case_precedence_env_beats_stored_beats_default,
    case_none_deletes_the_override,
    case_floor_is_one_like_the_env_vars_it_replaced,
    case_unknown_knob_and_non_int_are_refused,
    case_corrupt_store_boots_on_defaults,
    case_write_is_atomic_and_survives_reimport,
    case_no_upper_bound,
    case_the_registry_is_derived_not_declared,
    case_live_and_pending_track_the_running_process,
    case_record_live_covers_a_clamped_knob,
    case_a_knob_read_at_use_is_live_from_the_save,
    case_a_switch_holds_zero_and_one_and_nothing_else,
)
