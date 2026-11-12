"""The mass message dry run's break-it-once faults (service/automations/send_mass_message.py `run`,
its pure half send_mass_decide.py): lib/faults.py merges `register(Fault)` into FAULTS. Each patches
one send_mass_decide attribute inside the relay; the sender calls both through the module, so the
run performs what the patched one says. The check names live here and
scenarios/2026-10-31-mass-placeholder-echo.py imports them, so a target can never name a check that
does not exist.

  mass-dry-run-ignored      slop/run 2026-10-31-mass-placeholder-echo --break --fault=mass-dry-run-ignored
  mass-dry-run-list-claims-reach  slop/run 2026-10-31-mass-placeholder-echo --break --fault=mass-dry-run-list-claims-reach
"""
from __future__ import annotations

DRY_NO_SEND = ("a dry run sends nothing: no OF queue frame, no OF list write, no mass_runs or out "
               "messages row; every dry run's stats say dry_run, sent 0")
DRY_LIST = ("a dry run's would_send is who the real run reaches or None: a list run's = None + reason "
            "list_audience (its roster is never read), an explicit run's = roster - contact guard - fences - "
            "excluded_users = the real send's userIds")


def _ignored() -> None:
    """The pre-O3 lane (PR #80's open finding): `dry_run` is not read, so a dry run sends for real."""
    from automations import send_mass_decide as smd

    smd.is_dry_run = lambda payload: False


def _list_claims_reach() -> None:
    """The dry branch answers a list run as if it knew its reach: `p.recipients` (the known
    explicit fans, empty for a pure list) and no reason, instead of None + `list_audience`. An
    explicit audience is unaffected."""
    from automations import send_mass_decide as smd

    real = smd.dry_run_result

    def patched(p):
        out = real(p)
        if out.get("reason") != "list_audience":
            return out
        out = {k: v for k, v in out.items() if k != "reason"}
        return {**out, "would_send": list(p.recipients), "would_send_count": len(p.recipients)}

    smd.dry_run_result = patched


def register(Fault) -> dict:
    return {
        "mass-dry-run-ignored": Fault(_ignored, (DRY_NO_SEND, DRY_LIST)),
        "mass-dry-run-list-claims-reach": Fault(_list_claims_reach, (DRY_LIST,)),
    }
