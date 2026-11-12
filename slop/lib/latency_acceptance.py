"""Owner 2026-11-10: 120-user acceptance; 200-user latency is a stretch goal.

Only relay-admission and Vault items use this policy. Correctness/resource checks
remain mandatory. Small runs retain their original regression budgets.
"""
import math

SCENARIOS = frozenset(('2026-11-05-relay-admission', '2026-11-01-vault-pro-20k'))
ACCEPTANCE_USERS = 120
ACCEPTANCE_MS = 700
STRETCH_USERS = 200
STRETCH_MS = 500


def volume_knobs(name, default):
    if name in SCENARIOS:
        return ['--scale=medium', '--users=120', '--no-ui']
    return list(default)


def latency_check(ctx, name, values, legacy_limits):
    """Report every latency, enforce acceptance per action, never call a goal PASS."""
    users = ctx.users
    stretch = users >= STRETCH_USERS
    limit = STRETCH_MS if stretch else ACCEPTANCE_MS
    limits = {k: limit for k in values} if users >= ACCEPTANCE_USERS else legacy_limits
    valid = bool(values) and all(v is not None and math.isfinite(v) and v > 0 for v in values.values())
    met = valid and all(v <= limits[k] for k, v in values.items())
    ctx.metric('latency_contract', dict(users=users, profile='stretch' if stretch else
               'acceptance' if users >= ACCEPTANCE_USERS else 'regression',
               p95_ms=values, limits_ms=limits, target_met=met))
    if stretch and valid:
        ctx.skip(name, f'advisory 200-user/500ms stretch target; target_met={met}; see latency_contract')
    else:
        ctx.check(name, met, users=users, p95_ms=values, limits_ms=limits,
                  acceptance_load_met=users >= ACCEPTANCE_USERS)
    return stretch
