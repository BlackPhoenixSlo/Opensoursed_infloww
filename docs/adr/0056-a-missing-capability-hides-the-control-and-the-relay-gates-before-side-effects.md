# A missing Capability hides its control, and the Relay still refuses before any side effect

**Status: accepted** (2026-11-25, `.scratch/multi-platform-p1/plan.md` Phases 1b and 1c; tickets 02 and 04; Relay side built in issues 08–14).

Fansly's Shim answers many OnlyFans methods with stubs, and three Relay paths turn that into fake success: restrict sends the `.` ack DM and marks read before the Shim refuses (`service/server.py:5889-5908`), vault remove commits `removed_at` after the Shim's `success:false`, and mass send opens a run and reports the Shim's skip as sent. The OF Manager answers its own gaps with a disabled control and the Not-yet title. We decided the Fansly UI shows only what works: a missing Capability hides its control outright, Block included, with no disabled state or reason (owner: "features we can use"). Hiding is never the guard: every Shim method is built, Unsupported or Blocked, and each caller of an Unsupported or Blocked one passes a Side-effect gate before it sends, claims (`lifecycle_messages._claim`) or writes local state, answering 501 or a typed error instead of an empty success. Only `add_users_to_lists` is built now; the rest wait on a Capture session or stay Unsupported. We chose this because a chatter acting on a fake "sent" or "removed" is worse than a missing button, and stale app state or a direct call must not reach the write. The cost: a Fansly chatter cannot discover a control exists until it works, and every new gated method needs its gate written at the caller, not just its flag.

ASSUMPTION: hide, never disable-with-reason, even for moderation controls (rung 2, owner's words); overturned if the owner wants Block visible on Fansly.

## Considered Options

- **Disable with a reason, as the OF Manager's Not-yet title does.** Rejected: the owner asked for features that can be used, not a list of ones that cannot.
- **Hide only, trusting the UI.** Rejected: the three fake-success paths are reachable from automations and stale tabs.
- **A capped 200-message scan for Fansly chat media.** Rejected: backfill reads `hasMore:false` as complete (`vault_sends_api.py:605-619`).
