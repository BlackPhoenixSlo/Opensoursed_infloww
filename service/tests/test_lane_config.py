#!/usr/bin/env python3
"""
`lane_config` — the durable store behind the Concurrency panel. Plain-assert,
no pytest (repo convention).

Why this suite exists. This module took the relay's concurrency ceilings from
"env var, applied at boot" to "settable over an UNAUTHENTICATED HTTP endpoint",
which reverses a decision `admission.describe()` had written down as
deliberate. A reversal like that is only safe while the properties that made it
defensible actually hold, and every one of them is a claim this suite has to
keep honest:

  • the env var still wins, so a bad saved value is one restart from recovered
    without anyone opening a file inside a container;
  • a corrupt or missing store BOOTS on code defaults rather than refusing to
    boot, because a tuning number must never be able to take the process down;
  • the write is atomic, because a half-written file lands in the bullet above
    and would silently reset every ceiling at once;
  • `describe()["source"]` tells the truth, because the panel disables an input
    on it — a wrong answer means a UI that accepts an edit it cannot deliver.

What is deliberately NOT asserted: an upper bound. There is none. The operator
asked for the ceiling to be theirs to set on a friends-only deployment, and a
silent clamp would be a cap wearing a text box's clothes. `case_no_upper_bound`
pins that as intended behaviour so a future reader does not "fix" it.

Cases:
  case_precedence_env_beats_stored_beats_default
  case_none_deletes_the_override
  case_floor_is_one_like_the_env_vars_it_replaced
  case_unknown_knob_and_non_int_are_refused
  case_corrupt_store_boots_on_defaults
  case_write_is_atomic_and_survives_reimport
  case_no_upper_bound
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _harness  # noqa: E402


# The knobs these cases exercise, with the defaults their real owners pass.
# Stated here because a fresh import has an EMPTY registry — `resolve()` is what
# populates it, and in production that call comes from the module that owns the
# ceiling. `_fresh` replays that, so every case runs against a registry built the
# way the real one is.
_OWNERS = {
    "IMG_FETCH_CONCURRENCY": 8,
    "STORYBOARD_BUILD_CONCURRENCY": 2,
    "HEALTH_ALL_CONCURRENCY": 4,
    "AUTOMATION_MAX_CONCURRENT_RUNS": 4,
    "RELAY_EXECUTOR_THREADS": 192,
    "ACCOUNT_LANE_BACKGROUND": 2,
}


def _fresh(tmp: Path, env: dict[str, str] | None = None, register: bool = True):
    """A lane_config bound to `tmp`, re-imported so module-scope `_PATH` is
    recomputed. The real module resolves its path ONCE at import — same as the
    lanes it feeds — so a test that only cleared the cache would be testing a
    module that cannot exist in production.

    `register=False` gives the un-resolved state a module sees before any owner
    has called in, which is the only way to prove the registry is derived."""
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

        # The escape hatch. If this ever stops holding, a value saved from an
        # open HTTP endpoint can wedge the process with no way back in.
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
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 4) == 16
        lc.set_many({"HEALTH_ALL_CONCURRENCY": None})
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 4) == 4, "null => back to default"
        assert "HEALTH_ALL_CONCURRENCY" not in lc.stored(), "and gone from the file"


def case_floor_is_one_like_the_env_vars_it_replaced():
    # Every call site this replaced did `max(1, int(...))`. A cap of 0 is a
    # deadlock, not a tuning choice.
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
    # The whole process imports this module before logging is configured. If a
    # truncated file raised here, the relay would not start — and the thing it
    # died on would be a tuning number.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        p.write_text('{"IMG_FETCH_CONCURRENCY": 12', encoding="utf-8")   # truncated
        lc = _fresh(p)
        assert lc.stored() == {}, "corrupt store must read as empty"
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 8, "…and fall back to the default"

        p.write_text('["not", "an", "object"]', encoding="utf-8")
        lc = _fresh(p)
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 8, "wrong JSON type, same answer"

        # A key that is no longer a knob (renamed, retired) must not break the
        # rest of the file — only that key is dropped.
        p.write_text('{"RETIRED_KNOB": 3, "IMG_FETCH_CONCURRENCY": 12}', encoding="utf-8")
        lc = _fresh(p)
        assert lc.resolve("IMG_FETCH_CONCURRENCY", 8) == 12, "a stale key must not poison siblings"


def case_write_is_atomic_and_survives_reimport():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "nested" / "lc.json"      # parent does not exist yet
        lc = _fresh(p)
        lc.set_many({"AUTOMATION_MAX_CONCURRENT_RUNS": 16, "IMG_FETCH_CONCURRENCY": 12})

        on_disk = json.loads(p.read_text("utf-8"))
        assert on_disk == {"AUTOMATION_MAX_CONCURRENT_RUNS": 16,
                           "IMG_FETCH_CONCURRENCY": 12}, on_disk
        # Derived from the store's own name, NOT the literal ".lane_config.*".
        # `atomic_json.write_atomic` prefixes the temp with the TARGET's name so
        # a leftover is traceable to the write that died — and a hardcoded glob
        # here silently stopped matching when that changed, which left this
        # assertion passing against a write that leaked its temp and was not
        # atomic at all. Review caught it; do not re-hardcode the prefix.
        assert not list(p.parent.glob("." + p.name + ".*")), (
            "temp file must not survive the write"
        )

        lc2 = _fresh(p)          # a "restart"
        assert lc2.resolve("AUTOMATION_MAX_CONCURRENT_RUNS", 4) == 16, (
            "the whole point: a value saved from the panel must be there after a restart"
        )


def case_no_upper_bound():
    # Pinned deliberately. The endpoint is unauthenticated by explicit operator
    # choice; adding a clamp here would be a gate they declined, applied in the
    # one place they would not think to look for it.
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        assert lc.set_many({"RELAY_EXECUTOR_THREADS": 5000})["RELAY_EXECUTOR_THREADS"] == 5000


def case_the_registry_is_derived_not_declared():
    """The panel's knob list comes from what `resolve()` was actually called
    with — there is no declared table. This is what makes a stale default
    impossible: the owner passes its default and nothing else restates it."""
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

        # The owner's default is the ONLY default. If a second table restated
        # it, this is the assert that would catch the two disagreeing.
        lc = _fresh(p, register=False)
        lc.resolve("IMG_FETCH_CONCURRENCY", 99)
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert row["default"] == 99, row
        assert row["value"] == 99, row


def case_live_and_pending_track_the_running_process():
    """`pending` drives the "restart to apply" banner, so a knob whose live
    value went unrecorded would silently report False — the exact failure a
    hand-written live-value map produced."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lc.json"
        lc = _fresh(p)

        rows = {r["name"]: r for r in lc.describe()}
        assert set(rows) == set(_OWNERS), "every resolved knob must appear"
        for r in rows.values():
            assert r["live"] is not None, f"{r['name']} has no live value: {r}"
            assert not r["pending"], "nothing saved yet, so nothing can be pending"

        # Save while "running": live must stay put, value must move, and the two
        # disagreeing is precisely what `pending` means.
        lc.set_many({"IMG_FETCH_CONCURRENCY": 12})
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert (row["live"], row["value"], row["pending"]) == (8, 12, True), row

        # …and after a restart the two agree again.
        lc = _fresh(p)
        row = next(r for r in lc.describe() if r["name"] == "IMG_FETCH_CONCURRENCY")
        assert (row["live"], row["value"], row["pending"]) == (12, 12, False), row


def case_record_live_covers_a_clamped_knob():
    """ACCOUNT_LANE_BACKGROUND is clamped below total AFTER resolving, so the
    number enforced is not the number resolved. Without `record_live` the panel
    reports a pending change no restart will ever deliver."""
    with tempfile.TemporaryDirectory() as d:
        lc = _fresh(Path(d) / "lc.json")
        lc.set_many({"ACCOUNT_LANE_BACKGROUND": 9})
        lc.resolve("ACCOUNT_LANE_BACKGROUND", 2)     # a "restart"
        lc.record_live("ACCOUNT_LANE_BACKGROUND", 4)  # …clamped to total-1
        row = next(r for r in lc.describe() if r["name"] == "ACCOUNT_LANE_BACKGROUND")
        assert row["live"] == 4, row
        assert row["pending"] is True, (
            "9 was saved but 4 is enforced — the panel must say so rather than "
            "pretend the save landed"
        )


def case_a_knob_read_at_use_is_live_from_the_save():
    """A ceiling read where it is used (resolve_live: the release floor, the
    DM rate) applies at its next use, so a save is
    live at once, before that use; a knob read once at import stays pending."""
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
    """A switch (resolve_switch, ADR 0025): 0 is legal and survives a reload
    (the ceilings' floor of 1 does not apply), 2 is refused, an env var may say
    off/on, and the panel row says it is a switch. A ceiling hand-written as 0
    in the file still reads as 1."""
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
        raw["HEALTH_ALL_CONCURRENCY"] = 0                 # hand-edited
        f.write_text(json.dumps(raw))
        lc = _fresh(f)                                    # a restart
        assert lc.resolve_switch(knob, True) is False, "a stored 0 must survive the reload"
        assert lc.resolve("HEALTH_ALL_CONCURRENCY", 4) == 1
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
        os.environ[knob] = "sometimes"                    # unparsable: falls through to stored (0)
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
