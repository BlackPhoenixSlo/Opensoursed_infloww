"""The mass message dry run's break-it-once faults (service/automations/send_mass_message.py `run`,
its pure half send_mass_decide.py): lib/faults.py merges `register(Fault)` into FAULTS. Each patches
one send_mass_decide attribute inside the relay; the sender calls both through the module, so the
run performs what the patched one says. The check names live here and
scenarios/2026-10-31-mass-placeholder-echo.py imports them, so a target can never name a check that
does not exist.

  mass-dry-run-ignored      slop/run 2026-10-31-mass-placeholder-echo --break --fault=mass-dry-run-ignored
  mass-dry-run-skips-guard  slop/run 2026-10-31-mass-placeholder-echo --break --fault=mass-dry-run-skips-guard
"""
from __future__ import annotations

DRY_NO_SEND = ("a dry run sends nothing: no OF queue frame, no OF list write, no mass_runs or out "
               "messages row; every dry run's stats say dry_run, sent 0")
DRY_LIST = ("a dry run's would_send is who the real run reaches: a list run's = roster - contact guard - "
            "fence - excluded_users (non-empty), an explicit run's = the real send's userIds")


def _ignored() -> None:
    """The pre-O3 lane (PR #80's open finding): `dry_run` is not read, so a dry run sends for real."""
    from automations import send_mass_decide as smd

    smd.is_dry_run = lambda payload: False


def _skips_guard() -> None:
    """The dry branch answers the raw roster: the excludes a real list run puts on Auto_Exclude and
    AUTOFENCE (contact guard, MASSdmEXCLUDE, excluded_users, fans outside the include list) are not
    subtracted. An explicit audience is unaffected (plan already dropped them)."""
    from automations import send_mass_decide as smd

    smd.dry_excludes = lambda p, fence: []


def register(Fault) -> dict:
    return {
        "mass-dry-run-ignored": Fault(_ignored, (DRY_NO_SEND, DRY_LIST)),
        "mass-dry-run-skips-guard": Fault(_skips_guard, (DRY_LIST,)),
    }
