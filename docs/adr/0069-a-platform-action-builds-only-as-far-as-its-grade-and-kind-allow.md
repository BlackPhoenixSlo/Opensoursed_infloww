# A Platform action builds only as far as its Grade and its kind allow

**Status: proposed** (2026-11-27, `.scratch/multi-platform-p2/plan.md` Phase 02a; tickets 00, 01, 11; nothing built yet).

Fansly's Capture session 1126 recorded actions at mixed strength: UI clicks on the wire, bodies we sent, inferences, bundle reads, and often a single row, while Phase 1 asked only "captured or not". We decided every action carries a Grade, its Provenance (M, W, I, B) and Coverage (the observed cases), taken from its weakest input, and the Evidence bar maps Grade and kind to an outcome: an observed read builds for its observed cases and maps every Unseen value to unknown; an observed Reversible write builds, a W one only with Stateful-fake proof, and an M one merges with no Live check; an observed Fan-facing write builds only as a Live-check method (ADR-0070); an unobserved case of any of these refuses; I or B stays Blocked whatever the kind; money stays refused (ADR-0055). A read proven to change state is a write. We chose this because a wrong Fan-facing write cannot be recalled (a fired broadcast has no undo) and bundle reads have described requests the site never sends, while a refused action costs one owner capture or Live check. The cost: captured but narrow actions stay refused (`search_users`, broadcast exclusion lists, the earnings chart), and each new Fan-facing method needs an owner session before it lifts.

ASSUMPTION: an M-graded, observed Reversible write merges without a Live check (rung 4, undo exists); overturned if the owner wants every Fansly write checked once, then ticket 01's list add and rename go behind a grant.

## Considered Options

- **One grade with single-row as a level.** Rejected: it mixes how a request was seen with which cases were seen.
- **Build I or B actions behind a Live check.** Rejected: one Live check proves one case, not an unseen request shape.
- **A Live check for every write.** Rejected for now: list add and rename have a captured undo and no Fan-visible effect.
