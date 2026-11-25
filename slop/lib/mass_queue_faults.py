from __future__ import annotations

EXCL = ("excluded fans get no placeholder, no out row, no OF wire userId; "
        "mass_runs.recipient_count = sent ids")


def _excluded_kept() -> None:
    import audiences
    import mass_queue_decide as d

    # strip_excluded alone is a no-op on this route (measured: NOT CAUGHT): the resolver already subtracts them
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
