# Cell mode runs one Agency as SQLite Cells, never a shared database

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Goal and Phase 0; tickets 02, 07, 12; nothing built yet).

Today one Relay with one SQLite runs one Agency, and an Agency of ~200 Creators may outgrow one Box (unmeasured: the only post-fix number is one contended run, `.scratch/kvm8-shadow-test/RUN.md:114,145`). We decided the way out is optional Cell mode: each Cell is a Relay changed as little as possible, with its own SQLite and 8–15 Creators (up to 50 small ones), grouped by chatter team; agency-scope data lives on the Control cell and reaches data cells as a read-only Agency copy (ADR-0064); we run the Boxes ourselves. No Postgres, no Kubernetes, and with `OI_CELL_MAP` unset no new code path runs. Cell mode is built only if Phase 0's Go/no-go gate says one Box cannot carry the Agency at 1.25×P and two Cells carry more per Relay; otherwise it is parked and re-gated when P grows 1.5×. We chose this because the owner wants to stay on boxes he runs (OWNER-DECISIONS 2026-11-25), it keeps the single-Box default and almost all Relay code as is, and a Box death hurts only its Cells. The cost: no transaction spans Cells, so stats, sales and payroll become Cross-cell reads, cross-cell S4S is closed in Release 1, every route, table, file and job needs a Cell scope row, and up to ~1 s of Own data is lost on a Box death (owner accepted).

ASSUMPTION (g): P = 200 and the 1.25×P bar; overturned by a measured P (falls: Phase 0, ticket 02 sizing).

## Considered Options

- **One shared Postgres for all Relays.** Rejected by the owner for now; a later option, not v1.
- **Kubernetes to schedule Relays.** Rejected by the owner; we run the Boxes ourselves.
- **Build Cells without measuring.** Rejected: if one Box carries the Agency, Cells only buy blast radius at a large cost (ticket 12).
- **Cells of ~5 or ~20–25 Creators** (PLAN.md, reviews). Replaced by the owner's 8–15, up to 50 small.
