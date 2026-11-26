# The Control cell owns sign-in and agency writes; Cells verify signed Actor tokens against a read-only Agency copy

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phase 1; tickets 06, 07, 08; nothing built yet).

Every Cell needs to know who a request is and what they may see, but people, grants and settings belong to the whole Agency. We decided the Control cell alone signs people in and takes every agency-scope write (Employees, grants, settings, shifts, clock, payroll, Creator reservations, Mirror Employees created with the grant). It mints an Ed25519-signed Actor token (≤15 min); Cells hold only the public key. Each data cell long-polls the Control cell for the Agency copy, applies whole sections in one transaction, copies grant rows unfiltered, and write-block triggers refuse local writes except a few touch columns. No chat-path write is forwarded synchronously to the Control cell. Past the max grant age (15 min) a Cell stops serving chatters. We chose this because a shared `SESSION_SECRET` would let one broken Cell mint owner sessions, filtering grant rows per Cell would widen access (no restriction row means every Creator, m `chatters.py:143-164`), and chatting must survive a short Control cell outage. The cost: a Control cell down longer than the max grant age stops chatters on every Cell, ~120 agency calls route to it, and the copied tables, local columns and triggers must stay in step with Cell scope.

Amended 2026-11-26: at ~100 Cells a grant edit sent as whole sections to every Cell costs sections × 100 (i), so grant changes go as deltas or finer sections (re-plan R6, Phase 7, after the demo). The 2-Cell demo keeps whole sections. "Delta sync" below is reopened for grant tables only.

ASSUMPTION: 15 min max grant age, not ~5.5 min; overturned by the owner choosing faster revocation over chatting through a Control outage.

## Considered Options

- **A shared session secret in every Cell.** Rejected: any Cell could mint any session.
- **Grant rows filtered to each Cell's Creators.** Rejected: widens access.
- **Agency writes forwarded from Cells to the Control cell on the chat path.** Rejected: a Control outage would stop chatting.
- **Delta sync.** Rejected: whole sections with a sha each are simpler to check.
