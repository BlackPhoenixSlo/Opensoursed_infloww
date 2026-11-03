"""The composer's mass queue break-it-once fault (scenarios/2026-10-31-mass-placeholder-echo.py):
lib/faults.py merges `register(Fault)` into FAULTS. It patches the pure decide (and the audience
resolver) inside the relay; service/mass_queue_api.py calls both through their modules, so the route
performs what the patched ones say. The check name lives here and the scenario imports it, so the
target can never name a check that does not exist.

  mass-queue-excluded-kept   slop/run 2026-10-31-mass-placeholder-echo --break --fault=mass-queue-excluded-kept
"""
from __future__ import annotations

EXCL = ("excluded fans get no placeholder, no out row, no OF wire userId; "
        "mass_runs.recipient_count = sent ids")


def _excluded_kept() -> None:
    """The body's `excluded_users` stay in `user_ids`: mass_queue_decide.strip_excluded is the
    identity AND audiences.resolve_mass_audience (the route imports it at call time) hands back
    the caller's own excluded ids among `included_users`, in the caller's order. Both, because
    `final_audience` inside the resolver already subtracts them: strip_excluded alone is a no-op on
    this route (measured: NOT CAUGHT). of_sends still drops them from the wire `userIds`, so OF
    never sends them: only the DB record lies (phantom stubs, recipient_count), i.e. EXCL alone.
    The wrapper rebuilds `included_users` from the caller's list, so it drops any id the resolver
    ADDED (recent-chat / unread / thresholded): fine for this scenario only (explicit `user_ids`, no
    such knob); a scenario using those knobs needs a wrapper that keeps them."""
    import audiences
    import mass_queue_decide as d

    d.strip_excluded = lambda user_ids, excluded: user_ids
    real = audiences.resolve_mass_audience

    async def resolve_mass_audience(*a, included_users=None, excluded_users=None, **kw):
        out = await real(*a, included_users=included_users, excluded_users=excluded_users, **kw)
        keep = {int(u) for u in out["included_users"]} | {int(x) for x in (excluded_users or [])}
        out["included_users"] = [u for u in (included_users or []) if int(u) in keep]
        return out

    audiences.resolve_mass_audience = resolve_mass_audience


def register(Fault) -> dict:
    return {
        "mass-queue-excluded-kept": Fault(_excluded_kept, (EXCL,)),
    }
