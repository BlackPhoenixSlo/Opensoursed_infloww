# The app's Platform table is static and a Drift test holds it to each Shim, not a catalog the Relay serves

**Status: proposed** (2026-11-24, `.scratch/multi-platform-p1/plan.md` Phase 1c; ticket 02; nothing built yet).

The app must know, per Creator, which controls its Platform can back. The blind adversary pass preferred a Relay-served catalog. We decided the Capabilities live in one static `PLATFORMS` table (key, label, lacks) in `app/lib/platform.ts`, read through `can(platform, cap)` and `useCan(accountId, cap)` on the Creator's own Platform, and a Relay-side Drift test reads that file (as `test_role_enforcement.py` reads `nav.ts`) and fails unless each Capability is in `lacks` exactly when every Shim method it maps to is missing or marked Unsupported or Blocked. While a Creator's Platform is unresolved, gated controls are not rendered, so nothing flashes on a Fansly Thread; a loaded Creator with no `platform` is OnlyFans. We chose this because app and Relay ship from one tree, the chatter roster has no slot for a catalog (`service/chatters.py:373`), the flags answer reads `undefined` while pending (`useFlags.ts:11-14`), and each Platform needs a logo and login card in the app regardless. The cost: a Shim change that adds a method is not live in the app until the table is edited, and the Drift test is the only thing tying them.

ASSUMPTION: no Deployment runs an app and a Relay from different commits (rung 3: every target ships one tree); overturned by one, then the Relay serves the catalog.

## Considered Options

- **A catalog served by the Relay.** Rejected: needs a new roster field and a pending state for every gated control, to cover a split deploy no target has.
- **Reflection over the Shim at runtime.** Rejected: it would call two stubs and the gated broadcast supported.
