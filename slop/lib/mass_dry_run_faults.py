from __future__ import annotations

DRY_NO_SEND = ("a dry run sends nothing: no OF queue frame, no OF list write, no mass_runs or out "
               "messages row; every dry run's stats say dry_run, sent 0")
DRY_LIST = ("a dry run's would_send is who the real run reaches or None: a list run's = None + reason "
            "list_audience (its roster is never read), an explicit run's = roster - contact guard - fences - "
            "excluded_users = the real send's userIds")


def _ignored() -> None:
    from automations import send_mass_decide as smd

    smd.is_dry_run = lambda payload: False


def _list_claims_reach() -> None:
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
