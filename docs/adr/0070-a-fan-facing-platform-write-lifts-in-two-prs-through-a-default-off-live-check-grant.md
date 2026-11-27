# A Fan-facing Platform write lifts in two PRs through a default-off Live-check grant checked at the caller

**Status: proposed** (2026-11-27, `.scratch/multi-platform-p2/plan.md` Phases 02a, 02b, 02f; tickets 00, 01, 04, 14, 11; nothing built yet).

A Shim method cannot see its audience or the claims, DM groups and enqueues its callers make before it is reached (`mass_premade.py:76-107` can enqueue the rest before returning), and the only existing guard, `confirm_live_broadcast`, is a kwarg no `service/` caller passes. We decided a Fan-facing write is first built as a Live-check method and every caller runs `side_effect_gate.live_check(aid, method, audience)` before any claim, group creation, enqueue or write; it reads the default-off env var `PLATFORM_LIVE_CHECK` (entries `<aid>:<method>[:<target id>]`) and refuses unless the effective audience is exactly the one named Fan, or one list whose Complete read holds only him, re-read just before a broadcast POST. The class-level `platform_live_check` marker only counts the method; `confirm_live_broadcast` folds in; the Relay advertises the Capability only for an account holding a grant, so the composer lights for that one Creator. No compose file passes the variable through, so PR 1 merges and deploys with today's outcome; the owner runs the Live check on a local Relay; PR 2 records `Live check <date>, Relay <sha>` and drops the requirement for that method and Branch. We chose an env var because it is the cheapest to undo, a chatter cannot flip it from the UI, and the house already gates `ALLOW_ANONYMOUS_ADMIN` this way (`auth.py:173`); we chose the caller because audience and side effects live there. The cost: every lift is two PRs, and each new caller must remember the call, which the Verdict table's zero-effect cases catch.

ASSUMPTION: an env var, not a DB or admin toggle (rung 4); overturned if the owner wants a UI toggle, then the grant moves to a stored setting with the same caller check.

## Considered Options

- **Authorize at the Shim marker.** Rejected: the marker has no audience and runs after the caller's claims.
- **Keep `confirm_live_broadcast`.** Rejected: no caller passes it, and it covers broadcast only.
- **Lift on the owner's word with one PR.** Rejected: the code that runs the Live check must be on main before the check, so the pass has a Relay sha to record.
