# Creators change Cells by clone and whole-session-folder removal, never by merge

**Status: proposed** (2026-11-26, `.scratch/agency-scale-out/phased-plan.md` Phases 3–5, Fable round-2 amendment 1; tickets 11, 13; nothing built yet).

Today's single Box must become Cells (Entry cut), and later a Hot cell must be cut in two while it runs (Carve). We decided both work by cloning, never by merging: the Entry cut is one stopped N-way clone of today's Box into N data cells plus a Control cell, drilled on a DB copy and one-way; a Carve clones one running data cell into two. Each copy gets Session-folder quarantine of every Creator it does not own (the whole `sessions/accounts/<id>/` folder, since `_initialise_account_from_sessions` rebuilds `latest.json` from any leftover `session_*.json`, m `accounts.py:117-144`), its own `OI_ACCOUNTS`, and a `cell_owned()` filter on reads, jobs and pumps; a Carve bumps both Owner epochs, hands Creator reservations over in one write, refuses open S4S legs, and from then on refuses any pre-carve restore. Deleting the non-owned rows (`carve-prune`) is optional and offline. We chose this because the owner picked clone + delete over merge (OWNER-DECISIONS 2026-11-25), a clone keeps every row and foreign key whole, and "no session folder" is a proof a Cell cannot act as a Creator. The cost: until pruned, each copy carries other Creators' rows, so a missing `cell_owned()` filter double-counts sales or shows a master the wrong Creators; and Cells can only be cut, never joined back.

ASSUMPTION: the Entry cut belongs in Release 1; overturned if Cells are only for new Agencies (falls: Phases 3 and 5).

## Considered Options

- **Merging Cells.** Rejected by the owner; cell-local autoincrement ids would collide.
- **Removing only `SESSION_FILES`.** Rejected: leftover session files rebuild the login.
- **The Entry cut as repeated Carves.** Rejected: a Carve never creates the Control cell.
