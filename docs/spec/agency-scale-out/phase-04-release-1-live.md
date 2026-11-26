# Phase 04 — Release 1 live

**Objective.** The tools and runbook exist for the owner to take one Agency from today's single Box into Cell mode in one quiet hour, admitting only OnlyFans Creators with a proxy, and to prove Release 1 over 7 days (0 duplicates, 0 leaks, every page delivered, one live Planned move); Fansly and Fanvue stay refused by an admission gate until their MP conditions hold. Plan: `.scratch/agency-scale-out/phased-plan.md` Phase 4, amendments 1–2; tickets 12, 13, 14, 04, 02.

Amended 2026-11-26 (R9/R10): Release 1 = AE on one Box (box A, today's KVM 8). Three stages: shadow (Control + Cells read-only on copies beside the live relay), canary wave 1 (the 6 lowest-revenue models into a small Cell 2), full cut wave 2 (the rest into Cell 1). Later Cell 2 relocates whole to a new slot on A. Demo done = both waves + post-cut + real-path + the relocation; the 7-day proof runs after the demo. See Further Notes.

## Problem Statement
- Phases 1–3 drill Cell mode on throwaway Boxes. Nothing tells the owner whether *their* Agency is ready: which live rules, jobs and links stop working, whether every Box, page and Fence is in place.
- The Entry cut is one-way (plan amendment 1): no merge back, gaps are fixed only forward.
- Release 1 admits only OnlyFans Creators with a proxy (04): in Cell mode "no proxy" means refuse, and Fansly always goes direct (m, ticket 04 item 4). Phase 1 refuses them at the Relay and Phase 3's cut refuses them at its own preflight; nothing tells the owner days ahead.
- Nothing prints a Placement from a DB copy (Phase 3's review moved story 23 here); nor the quiet hour, admission, cross-cell S4S or a pasteable `fleet.toml` block the go-live needs.
- "7 days, 0 duplicates, 0 leaks, every page delivered" has no counter that reads a live Cell, and an incident-free week raises no page to count.

## Solution
- Before: this Phase's grouping plan (`cell_plan.py`) from a DB copy, with release-1 columns; a read-only **preflight** on the Witness box in two stages: `pre-cut` (T-1 d, T-0) and `post-cut` (after the Entry cut, before chatters).
- During: the owner runs Phase 3's Entry cut once, in the quiet hour, from **runbook** `docs/runbooks/cell-mode-release-1.md`.
- After: a daily **`cell-report`** writes one proof record per UTC day to the Witness; `cell-report --done` declares Release 1 only on 7 contiguous green days that include a completed live move and 7 confirmed test pages. The go-live itself is the owner's (needs-human).

## User Stories
1. As the owner, I want the grouping plan (Placement; Phase 3's moved story 23), run on a copy of my box, to also print the quietest hour over 4 weeks, so that the Entry cut greys the fewest chats. [parallel-safe now]
2. As the owner, I want every Creator's admission (Platform, proxy bound) printed in that plan, so that I fix gaps a week before the cut. [parallel-safe now]
3. As the owner, I want S4S deals whose two Creators land in different Cells flagged in the plan, so that I keep partners together (cross-cell S4S is closed in Release 1). [parallel-safe now]
4. As the owner, I want an optional `fleet.toml` accounts block printed that fleet.py renders unchanged, so that I paste it instead of typing ids. [parallel-safe now]
5. As the owner, I want fleet.py to refuse a Placement holding a Fansly or Fanvue Creator, so that a non-admitted Platform never runs in a Cell. [parallel-safe now]
6. As the owner, I want preflight to go RED on any source-Box Creator that is not OnlyFans-with-proxy or is missing from Placement, so that the cut never refuses mid-window. [parallel-safe now]
7. As a reviewer, I want lifting the Fansly gate to need a code change that cites the MP mixed-platform restore drill and Fansly proxy support, so that it cannot be flipped by a config edit. [waits for MP mixed-platform restore drill merged]
8. As a reviewer, I want lifting the Fanvue gate to need a code change after MP Phase 2 merged, so that the third Platform enters the same way. [waits for MP Phase 2 merged]
9. As the owner, I want preflight to refuse when the Feature table is unsigned, edited since signing, or built from another Cell scope, so that I never go live on a table I did not read. [parallel-safe now]
10. As the owner, I want preflight to list every live rule, enabled job, queued send, tracking link, share link, bio host and send kind that maps to an "off" row, so that nothing I use stops silently. [parallel-safe now]
11. As the owner, I want "partial" rows that are in live use listed but not blocking, so that I know what degrades. [parallel-safe now]
12. As the owner, I want pre-cut preflight to check every target Box has the release image loaded, the same SHA everywhere, `min_cell_proto` met, and its `vm_id`, IP and provider account matching the provider's read-only view, so that no Box starts on old code and a Fence stops the right VM. [parallel-safe now]
13. As the owner, I want pre-cut preflight to check the Egress gate on every Box, an empty spare, the Witness heartbeat, a writable bucket and a fresh source backup, so that a Box death right after the cut is recoverable. [parallel-safe now]
14. As the owner, I want preflight to check every proxy each Cell can use, bound or pool, is on provider credentials no other Cell holds, so that one Cell's proxy failover cannot reach another's Creators and a proxy fence cuts one Cell only. [parallel-safe now]
15. As the owner, I want preflight to refuse when Phase 3's demo proof records (entry-cut drill report) are missing or red, so that I never go live on an unproven design. [parallel-safe now]
16. As the owner, I want preflight to send one test page and the runbook to ask me to confirm it arrived, so that "every page delivered" starts true. [parallel-safe now]
17. As the owner, I want the Entry cut done once, stopped, in the quiet hour, with the grey timed, so that the agency is down for one known window. [parallel-safe now]
18. As the owner, I want the runbook to say abort before the cut's rollback boundary means restarting today's Box and after it only forward, so that I never attempt a merge. [parallel-safe now]
19. As the owner, I want post-cut preflight to check every Cell answers `PLACEMENT-OK` with the current generation and hash, runs the release SHA, has a Restore manifest v2 at its current Owner epoch, and that the source Box was fenced before any Cell's egress opened, so that no Box starts on old rules or overlaps the old owner. [parallel-safe now]
20. As the owner, I want a real-path check after the cut (my login, All inbox spans Cells, a restricted chatter sees only their Creators, one send per Cell to the sandbox Fan, the `sent` row in the owning Cell), so that I see it working before chatters arrive. [parallel-safe now]
21. As the owner, I want a daily `cell-report` with duplicates, leaks, pages raised vs delivered, today's confirmed test page and open Unconfirmed sends, so that the 7-day proof is counted, not felt. [parallel-safe now]
22. As the owner, I want one live Planned move during the 7 days, at a quiet hour, with its grey and hashes in the Witness journal, so that "one command moves a group" is proven on real Boxes. [parallel-safe now]
23. As the owner, I want Release 1 declared done only by `cell-report --done` over 7 contiguous green days covering every Cell, so that the next Platform waits on evidence. [parallel-safe now]
24. As a chatter, I want one login and all my Creators in one All inbox after the cut, so that my work does not change. [parallel-safe now]
25. As the owner, I want `deploy-here.sh`, ae-deploy and deploy-all to refuse a Box that carries the cell-mode marker, mixed state included, so that a routine deploy never restarts the old relay over a Cell. [parallel-safe now]
26. As the owner, I want a shadow stage: Control and Cells on box A, egress closed, on `.backup` copies refreshed on a timer, so that I click through the new system with no OnlyFans contact. [parallel-safe now]
27. As the owner, I want the shadow on its own hostname and cookie scope, every write refused at the Front door, and a "shadow, read-only" banner with the copy's age, so that nobody mistakes it for the live system. [parallel-safe now]
28. As the owner, I want a canary wave: the 6 lowest-revenue models' sessions move from the old relay into a small Cell 2 behind a fence proof for those accounts, grant edits frozen, rollback = sessions back, so that the risk is a few models, not the agency. [parallel-safe now]
29. As the owner, I want pre-cut preflight to check free disk, free RAM against the old relay's peak, a disjoint wave split, the standby bundle off and the deploy marker present, so that one Box can hold both systems. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - The whole grouping script `deploy/fleet/cell_plan.py` (ticket 66): grouping, budget, no-fit, own-cell and ≤2-Cells output (ticket 02 item 3, Phase 3's moved story 23), plus `--quiet-hour`, admission column, cross-cell S4S flag, `--toml`. Stdlib only, read-only (`mode=ro`).
  - fleet.py: admission check in Placement render; `preflight --stage pre-cut|post-cut` and `cell-report [--done]` subcommands.
  - `oi-shard-stat`: new read-only subcommands `preflight` and `proof` (house precedent: `stat`/`audit`/`manifest` already read a shard dir read-only, m `deploy/fleet/bin/oi-shard-stat:1-13`).
  - `docs/runbooks/cell-mode-release-1.md` (new) and `deploy/fleet/tests/release1-rehearsal.sh`.
  - R9/R10: the cell-mode deploy refuse marker in `deploy/deploy-here.sh`, the ae-deploy and deploy-all skills (118); `fleet.py shadow` and its Front-door write refusal (119); `fleet.py entry-cut --accounts` for the canary wave (120, on Phase 3's tool).
- **Interfaces.**
  - Grouping script: input is a DB copy plus the source Box's `proxies.json` and session-folder list (`sessions/accounts/<id>/` names), all on the laptop.
  - `fleet.py preflight --stage pre-cut|post-cut` → one line per check `OK|RED|AMBER <check> <detail> <fix>`; exit 0 only with no RED.
  - `fleet.py cell-report [--since <utc>] [--page-received yes|no]` → one line per Cell plus a total; appends one proof record to `/var/lib/oi-witness/<agency>/proof/<YYYY-MM-DD>.json`; exit 1 on any red counter.
  - `fleet.py cell-report --done` → reads the proof records and the Witness journal; exit 0 only per the Done rule below.
  - `oi-shard-stat preflight <dir>` / `proof <dir> --since <utc>` → one JSON line each, like `audit`.
- **Schema.** None. No table or migration. Reads `send_ops`, `creator_reservations`, synced `messages`, the Witness journal and pager record that Phases 1–3 add.
- **Contracts.**
  - Admission: `ADMITTED_PLATFORMS = {"onlyfans"}` in fleet.py, checked at render (the Witness box has only `fleet.toml`). A test pins it equal to Phase 1's relay-side admitted set, so the two cannot drift and lifting needs a reviewed code change (rung 5). The proxy half needs the Box's `proxies.json`, so preflight checks it from Box facts (same rule as `oi-shard-stat` direct egress, m `oi-shard-stat:9-10`).
  - Feature table: Phase 0g's `service/cell_features.json` as written there (`scope_sha256`, `signed: {by, at, sha256}`, `features{name:{state, routes, jobs, send_kinds}}`). Preflight RED when `signed` is null, when `signed.sha256` ≠ sha256 of the table's `features` object (an edit after signing), or when `scope_sha256` ≠ the deployed `cell_scope.json`.
  - Box facts (`oi-shard-stat preflight`): accounts with session folders and their Platform; per account the bound proxy; every proxy in the pool with its provider credential id; enabled rules and jobs grouped by send kind and job name; queued scheduled sends by kind; live tracking slugs, open share links, bio hosts; open S4S legs with both Creators; loaded and running image SHA; `min_cell_proto`; Egress gate loaded; last backup time.
  - Proof facts (`oi-shard-stat proof`): per Send op, synced outbound messages in its thread with its digest after its `created_at` (>1 = duplicate); ops with `attempts > 1` and their recorded last error; same Fan and body within 60 s not tied to one op; `unclaimed_send` tripwire count; session-folder accounts vs `OI_ACCOUNTS`; open Unconfirmed sends. The Witness adds pages raised vs delivered, accounts in two Cells, and Creator reservations vs Placement.
  - Pager record: one line per page `{id, raised_at, cause, channel, http_status, delivered_at|null}` in `/var/lib/oi-witness/<agency>/pages.jsonl`, written by Phase 3's Witness pager after `notify.sh` returns (Phase 0j makes it fail loudly).
  ASSUMPTION: Phase 3's pager writes this record; if its spec does not, this Phase adds the write to the pager (additive, rung 4). Overturned by Phase 3 naming its own delivery record; `cell-report` reads that instead.
- **Entry cut is once, stopped, one-way** (plan amendment 1, rung 2). Ticket 12's "cell by cell" is replaced by the amendment. Phase 3 builds and drills the cut tool; this Phase only runs it, behind preflight, in the quiet hour. No merge, no map back.
- **Admission blocks the cut, not just new Creators.** The Entry cut clones the whole Box, so preflight is RED while any Creator on the source Box fails admission or is missing from Placement (the source set is session folders ∪ `user_accounts`, the same set Phase 3's cut checks). The human gives it a proxy, waits for its Platform's gate, or removes it from the Agency first.
- **Preflight `pre-cut` checks** (each RED unless noted):
  - signed Feature table: present, unedited since signing, scope sha matches;
  - live rule, enabled job, queued send, link, share, bio host or send kind on an "off" row (RED), on "partial" (AMBER);
  - S4S leg across planned Cells;
  - admission and Placement coverage over the source set, on the source Box's real files;
  - Placement valid (03 rules);
  - release image loaded on every target Box, one SHA, `min_cell_proto` met;
  - `vm_id`, IPv4 and provider account match the provider's read-only VM view for every Box incl. the source (04's pre-stop check, no stop sent);
  - Egress gate loaded on every target Box, spare Box empty;
  - Witness heartbeat fresh, bucket readable and writable (write-then-delete a probe object), source Box backup newer than 1 h;
  - every proxy a Cell can use (bound and pool) on provider credentials no other Cell holds (04 item 3); AMBER on the demo (R9: no proxy revoke, each model keeps its own proxy);
  - one Box (R9/R10): free disk ≥ 3–4× data (g); free RAM ≥ 2× the old relay's peak RSS (g); wave accounts disjoint from every open Cell; the ae-backup standby bundle off or excluding moved sessions; deploy refuse marker present (story 25);
  - every Phase 3 demo proof record present and green (paths in `fleet.toml`; `GATE build` no longer checked, superseded 2026-11-26);
  - test page sent; owner confirms arrival in the runbook.
- **Preflight `post-cut` checks** (each RED):
  - `PLACEMENT-OK gen sha256` from every Cell, matching the current Placement;
  - running SHA = release SHA on every Cell;
  - a Restore manifest v2 per Cell, newer than 1 h, at that Cell's current Owner epoch;
  - Witness journal for the cut: source Fence confirmed before the first target Egress gate lifted (ADR-0063); the old relay still fenced (R9): container gone on two `docker inspect` reads and data dir aside after wave 2; account list without the canary accounts after wave 1;
  - folders == `OI_ACCOUNTS` == Placement == reservations per Cell (Phase 3 story 25, re-read live).
- **Duplicates** (ADR-0060 allows a second attempt after a full 4xx or a pre-tunnel proxy refusal).
  - RED: any op with >1 synced outbound message carrying its digest; any `attempts > 1` whose last error is not a 4xx or `proxy_refused`.
  - AMBER: same-body-within-60 s pairs not tied to one op. Each needs an owner note (`cell-report --explain <pair> "<why>"`, stored in the proof record); `--done` refuses while any pair is unexplained.
  ASSUMPTION: Phase 2's `digest` equals the hash of the body as it lands in synced `messages` (i). Overturned by Phase 2 hashing pre-shaping text; then match on `upstream_id` only and list digest misses as AMBER.
- **Leaks.** RED on: any account in two Cells' session scans, session folders ≠ `OI_ACCOUNTS` ≠ Placement, reservations ≠ Placement, any `unclaimed_send`. `not_owner` answers are expected from stale tabs and only counted. Rows a restricted chatter should not see are tested on the real path (story 20) and in Seam 4, not counted daily (no daily signal exists without new relay logging; rung 5).
- **Pages.** RED on any `pages.jsonl` line with `delivered_at` null or a non-2xx status, or a missing record for a page the Witness journal says was raised. HTTP success does not prove the phone got it, so each day's report also needs `--page-received yes` for that day's test page (the report sends one).
- **Done rule** (`cell-report --done`): 7 proof records on consecutive UTC dates, each covering the whole previous 24 h with no gap between `since` and the previous record's `until`; each record lists every Cell in the Placement current at that time; every record green; every AMBER pair explained; every day's test page confirmed; a Witness journal `move` op in the window with `status: done`, equal per-account hashes and a recorded grey. A red day restarts the count.
- **Runbook steps** (OWNER on phone, AGENT on laptop, house shape of `docs/runbooks/ae-failover-drill.md`):
  1. T-7 d: owner decides max Grant age and the Front-door uptime target (plan "Needs the human"). DB copy: `sqlite3 <live db> ".backup <copy>"` on the Box (online-safe read), plus `proxies.json` and the session-folder list, copied to the laptop; never the live DB on the laptop. Grouping script with release-1 flags; owner edits `fleet.toml`.
  2. T-1 d: Witness, image staged, deploy marker set, standby bundle off; shadow stage run and clicked through (stories 26, 27); `fleet.py preflight --stage pre-cut` green.
  3. T-0 quiet hour, once per wave (canary wave 1, then full cut wave 2): pre-cut preflight again; Entry cut wave (Phase 3 tool, fresh `.backup`); `fleet.py preflight --stage post-cut` green; timed grey.
  4. Real path: owner login; All inbox spans Cells; a restricted test chatter sees exactly their Creators and none from another Cell; one send per Cell to the confirmed sandbox Fan; settled screenshots; the `sent` row in the owning Cell.
  5. Days 1–7: `fleet.py cell-report --page-received yes|no` daily; one Planned move at a quiet hour (Cell 2 to a new slot on A, R9).
  6. Day 7: `fleet.py cell-report --done` exits 0 → Release 1 done. Then Fansly, then Fanvue, each by its gate.
  Abort: before a wave's rollback boundary, put the old relay back (wave 1: sessions back, Cell 2 notes lost; wave 2: data dir renamed back) and start it; after it, forward only (move or Failover), never merge.
- **Post-deploy watch.** If the go-live Agency is AE, the repo rule binds: one `WATCH_CHECKS` entry `cell_release_proof` that runs `cell-report`, one `WATCH.md` line at go-live.

## Testing Decisions
- **Seam 1, fleet.py CLI** (`deploy/fleet/tests/test_release1.py`, pytest, house style of `test_fleet.py`/`test_failover.py`): admission through `render`; `preflight` and `cell-report` through `main()` with `ssh_run` returning fixture JSON lines and the Hostinger API stubbed from `tests/api_stubs.py`. Tables:
  - each check flips one fact → exactly that line goes RED (incl. a source Creator missing from Placement, right `vm_id` with wrong IP, right generation with wrong hash, one pool proxy credential shared by two Cells, a Feature table edited after signing, a fence after egress open);
  - all green → exit 0; all green plus one AMBER → exit 0 and the AMBER line printed;
  - Fansly or Fanvue account → render refused; `ADMITTED_PLATFORMS == {"onlyfans"}` and equal to Phase 1's set;
  - duplicates: an op with `attempts=2` after a 4xx → OK; after a timeout → RED; two synced messages with one digest → RED;
  - pages: delivered → OK; `delivered_at` null → RED; raised in the journal with no record → RED; `--page-received no` → RED;
  - `--done`: 7 green contiguous → 0; a 1 h gap, a missing Cell, a red day, an unexplained pair, no completed move, or 6 days → 1.
- **Seam 2, `oi-shard-stat preflight|proof`** against fixture shard dirs (SQLite built in the test, `proxies.json`, `sessions/accounts/<id>/`), extending the shard-dir fixtures used by `backup-restore-local.sh`. Ids > 2^53 as strings.
- **Seam 3, grouping script** against a synthetic SQLite: grouping rules, quiet hour, admission column, cross-cell S4S flag; `--toml` output fed to `fleet.py render` gives the same Placement.
- **Seam 4, container go-live rehearsal**: after Phase 3's `cell-recovery-in-containers.sh --drill entry-cut` stack is up (FakeOF, real Caddy, real images), run `preflight --stage post-cut` and `cell-report` against it, then a restricted chatter's browser path (positive and negative account assertions on list and SSE, using the Phase 1 acceptance seam). `--break dup-send|leak-folder|drop-page|cross-cell-read` must turn the matching line RED.
- **Runbook rehearsal** `release1-rehearsal.sh --lint-only`: `bash -n` on every runbook shell block (precedent `kvm8-campaign-rehearsal.sh --lint-only`).
- Prior art: `cmd_audit`/`audit_report` (fleet facts over SSH → report), `test_fleet.py::test_audit_report_flags_duplicates_and_capacity`.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
nice -n 10 uvx --python venv/bin/python pytest -q \
  deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_failover.py \
  deploy/fleet/tests/test_release1.py deploy/fleet/tests/test_cell_plan_release1.py
nice -n 10 deploy/fleet/tests/release1-rehearsal.sh --lint-only
nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut --release1
for m in dup-send leak-folder drop-page cross-cell-read; do
  nice -n 10 deploy/fleet/tests/cell-recovery-in-containers.sh --drill entry-cut --release1 --break "$m"
done
venv/bin/python deploy/fleet/fleet.py preflight --help >/dev/null
venv/bin/python deploy/fleet/fleet.py cell-report --help >/dev/null
test -f docs/runbooks/cell-mode-release-1.md
venv/bin/python scripts/comment_budget.py --check
```
Needs-human, each leaves a file the next step reads:
- owner signs the Feature table (Phase 0g's `signed` block on main);
- owner confirms the 6 lowest-revenue canary models, turns off the standby bundle, runs and approves shadow, canary and full cut (R9/R10; one Box; spare and Witness box are scale path);
- owner takes the DB copy, runs the grouping script, applies the plan to `fleet.toml`;
- `preflight --stage pre-cut` and `--stage post-cut` green on the Witness box (output saved with the proof records); test page confirmed;
- Entry cut in the quiet hour; grey in the Witness journal;
- real-path check: owner login, All inbox, restricted chatter positive/negative, one sandbox send per Cell, the owning Cell's `sent` row, settled screenshots;
- Cell 2 relocated whole to a new slot on box A, in the Witness journal (demo done here);
- after the demo: `fleet.py cell-report --done` exits 0 (scale path).

## Depends on
- Phase 0: 0f Cell scope; 0g signed Feature table in its `signed {by, at, sha256}` shape; 0j notify delivery fixes. (Gate verdict and measured Cell budget dropped 2026-11-26; budget is an input with a default, ticket 66.)
- Phase 1: `OI_ACCOUNTS`, Placement render + `PLACEMENT-OK gen sha256`, `min_cell_proto`, Front door, Creator reservations, relay-side admission and "no proxy" = refuse, Send tripwire, the restricted-chatter browser seam.
- Phase 2: `send_ops` claims (`digest`, `attempts`, last error) and Unconfirmed sends, Fence with `vm_id` and IP, Egress gate, epoch write refusing a second Cell instance.
- Phase 3: Planned move, Witness journal and pager (with the pager record above), Restore manifest v2, per-Cell deploy by image SHA, Entry cut tool and its container drill. Its cut fences the old relay container with the `cell` kind right after the final copy (R9; power fence on scale) and refuses any target `oi-cell-open` without that confirmed FenceResult (Phase 3 cut steps 3 and 8, ADR-0063 names clone activation); this Phase's post-cut check re-reads both from the journal and goes RED if the order is wrong.
- Human decisions from the plan: max Grant age, Front-door uptime target, signing the Feature table, the go-live.

## Out of Scope
- Building the Entry cut, move, Failover or Fence logic: Phase 3 / Phase 2 own them. Grouping is this Phase's (`cell_plan.py`).
- Fansly proxy support: MP's work; only the gate that waits for it is here.
- Carve: Phase 5. etcd: Phase 6.
- Automatic regrouping or a hot-cell rebalancer: a human applies every plan (02).
- Merge back to one Box: refused (ADR-0062).
- Starting with a new Agency instead of cutting the existing one: the plan names the Entry cut (amendment 1).
- A crypto signature on the Feature table: Phase 0g's `signed` block from the owner's written yes is the signature.
- Running the go-live, buying Boxes, proxy panels, live sends: needs-human.
- Slop or volume runs: not needed; the proof is 7 live days plus Seam 4.

## Further Notes
- Entry cut once vs cell by cell: plan amendment 1 (rung 2) wins over ticket 12's older wording.

ASSUMPTION: a Creator failing admission blocks the whole Entry cut rather than staying behind on a single Box (rung 4: refuse is undoable; a split Agency needs two logins). Overturned by the owner accepting a leftover single Box; the runbook gains a second-login step.

ASSUMPTION: Fansly's gate needs Fansly proxy support as well as the MP drill, since Fansly goes direct and Cell mode refuses "no proxy" (04 item 4, 04 fog). Overturned by an owner-accepted direct-egress Fence for Fansly.

ASSUMPTION: quietest hour = fewest inbound DMs plus `actions` rows per 60 min over 4 weeks from the DB copy (rung 5). Overturned by the owner naming an hour.

ASSUMPTION: Restore manifest and source-backup freshness bar 1 h (rung 5, matches the hourly session backup, deploy/fleet/README.md). Overturned by Phase 3's measured backup lag.

ASSUMPTION: same-body-within-60 s pairs are AMBER needing an owner note, not RED, because legitimate repeat sends exist on today's single Box (i). Overturned if Phase 0e's baseline shows 0 such pairs; then RED.

ASSUMPTION: `cell_release_proof` WATCH check is added only if the go-live Agency is on AE (repo CLAUDE.md scopes the rule to AE prod). Overturned by the owner wanting watch lines for any Cell-mode go-live.

ASSUMPTION: the 7 days are UTC calendar days counted from the end of the Entry cut, and a red day restarts the count (rung 4). Overturned by the owner's own exit rule. (2026-11-26: counting starts after the demo; see Re-plan block.)

ASSUMPTION: the planner's DB copy is a `sqlite3 .backup` taken on the Box, not `oi-backup` (rung 1: `oi-backup` without `--drill` only runs restic and leaves no DB file, m `deploy/fleet/bin/oi-backup:48-51`; `--drill` restores to `$OI_ROOT/drill/` on the Box, `:61-71`). Overturned by Phase 3 shipping a copy-out command.

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1–R4, R7, R8). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Paths.**
  - demo: 66 (stories 1–4), 67 (5), 68 (6), 69 (9–11), 70 (12–16, 29, trimmed), 71 (19), 75 short (17, 18), 76 (20, 24), 77, 78 (22), 118 (25), 119 (26, 27), 120 (28).
  - scale: 72–74, 79 (21, 23: daily `cell-report` and the 7-day `--done`).
  - later: 80, 81 (7, 8: Fansly and Fanvue gates lift).
  - No ticket waits on 25 (GATE).
  ASSUMPTION: 67 is demo, since 68 waits on it (rung 1 edge). Overturned by: 67's ticket showing 68 can run without it.
- **Release 1 = AE, one Box (R9/R10).** Old relay, Control, Cell 1 and Cell 2 all on box A. Shadow (119) → canary wave 1 (120, Cell 2) → full cut wave 2 (77, Cell 1). After every Cell's restore test, Cell 2 relocates whole to a new slot on A (78, story 22). Box B, re-imaging A and cross-box moves are gone from the demo (superseded by R9/R10 2026-11-26).
  ASSUMPTION: a kernel or disk fault on A takes all of AE down; accepted as AMBER for the demo (owner R9). Overturned by the owner wanting a second Box; then cross-box moves (56) rejoin the demo.
  ASSUMPTION: low-value canary models are OK to risk (owner R10, picks them). Overturned by the owner naming no model low-value; then the canary uses one test model only.
- **Grouping script:** this Phase owns all of `cell_plan.py`; ticket 66 builds it (Phase 3 review moved story 23 here). Cell budget is an input with a default until 26 measures it.
- **Pre-cut trims (70).**
  - Spare Box: AMBER on the demo, not RED. There is no spare.
  - Witness heartbeat: checked by hand (R8). The Witness runs from the owner's laptop.
  - Gate verdict: not checked.
  ASSUMPTION: the demo runs with no spare and a laptop Witness (rung 5). Overturned by: the owner buying a spare or Witness box; then both go back to RED.
- **76 trimmed:** the `dup-send` and `drop-page` breaks wait for 72/73 (scale). Post-cut preflight, restricted chatter, `cross-cell-read` and `leak-folder` stay.
- **77:** its 26 and 65 edges are dropped (those tickets are on the scale path).
- **D3 = B:** the live move fences Cell 2 only; Control and Cell 1 keep sending (i).
- **7-day proof after the demo.** The demo is done when the cut, post-cut, real path and live move are all green. `cell-report --done` (79) then counts 7 days from the end of the cut.
  ASSUMPTION: the demo's live move counts as the 7-day window's move (rung 5). Overturned by: the owner wanting a second move inside the counted week.
- **Honest wording (R5):** the demo shows 2 Cells on one box (R9). It does not prove 1,000 models; that is `phase-07-hold-1000.md`.
- **Human (R7, R9/R10):** confirm the 6 lowest-revenue canary models; turn off the standby bundle; run and approve shadow (119), canary (120) and full cut (77); sign the Feature table; approve the relocation (78).

## Review
codex (gpt, high effort), 2026-11-26, partly blind (reviewer read `.scratch` tickets through git objects). Blind call B1–B10, draft call D1–D13.
- B1 alternative "defer, keep one Relay": **reject** — that is Phase 0's gate; this Phase now requires `GATE build` (see D6). (superseded 2026-11-26: no gate)
- B2 cut once, stage per Cell: **reject** — already the decision (amendment 1).
- B3 start with a new Agency: **reject** — plan Phase 4 names the Entry cut; added to Out of Scope.
- B4 bind preflight to agency use (jobs, payroll, clock-out, queued sends, per-Creator disposition): **accept** — Box facts and pre-cut check now include enabled jobs and queued sends against Feature-table `jobs`/`send_kinds`; every source Creator must be placed and admitted.
- B5 point of no return, source stays fenced, which fence: **partial** — rollback boundary and fence are Phase 3's; post-cut check now verifies fence-before-egress and source VM `stopped`.
- B6 continuity limits (grant age, front-door uptime, recovery budget, re-login): **partial** — grant age and uptime target added as T-7 d human decisions and Depends on (plan "Needs the human"); recovery budget is Phase 3's benchmark; rest out of scope.
- B7 `oi-epoch` double-accept and `notify.sh` rc=0 on 503 (measured): **partial** — fixes belong to Phase 2 (epoch refuse) and 0j; both now named in Depends on; pager delivery record defined (D4).
- B8 test through the real browser path with FakeOF: **accept** — Seam 4 on Phase 3's container stack with restricted-chatter browser assertions and four `--break` mutants.
- B9 an incident-free week gives zero page observations: **accept** — one owner-confirmed test page per day, required by `--done`.
- B10 premise falsifiers (single Relay passes, HTTP/1.1, cross-cell atomic write): **reject** — Phase 0 gate and 0h spike own these; this Phase consumes their verdict.
- D1 seven green outputs ≠ seven days: **accept** — Done rule with contiguous coverage, every Cell, completed journal move, `--done` subcommand and tests.
- D2 `attempts > 1` RED contradicts ADR-0060; row cannot show two accepts: **accept** — duplicates now counted from synced outbound messages per digest; `attempts > 1` RED only without a 4xx/`proxy_refused` last error; unexplained AMBER pairs block `--done`.
- D3 leak counter misses cloned-row exposure to a restricted chatter: **accept** — real-path step and Seam 4 add positive/negative account assertions on list and SSE; daily counter limits stated.
- D4 page records no phase promises; HTTP ≠ arrival: **accept** — pager record contract defined (ASSUMPTION if Phase 3 lacks it) and daily confirmed test page.
- D5 Feature table format contradicts Phase 0g; table edits undetected: **accept** — consumes 0g's `signed {by, at, sha256}`, checks sha over `features`; old ASSUMPTION removed.
- D6 missing Phase 0/3 proof only AMBER: **accept** — now RED.
- D7 pre-cut preflight needs artifacts the cut creates: **accept** — split into `pre-cut` (staged image, bucket writable, source backup) and `post-cut` (`PLACEMENT-OK`, running SHA, manifest at current epoch).
- D8 admission per Placement misses omitted Creators; no IP; no Placement hash: **accept** — source set coverage, IPv4 match, `PLACEMENT-OK gen sha256`; tests added.
- D9 distinct proxy ids can share credentials; pool proxies ignored: **accept** — check is per provider credential over the whole usable pool.
- D10 Phase 3 cut may open targets before fencing the source (ADR-0063): **partial** — this Phase cannot reorder Phase 3; Depends on now states the requirement and post-cut goes RED on the wrong order. Phase 3's spec should state it (coordinator). (Done 2026-11-26 by the plan review: Phase 3 steps 3 and 8.)
- D11 grouping script owned by Phase 3; admission by Phase 1; Fanvue story added the Fansly drill: **accept** — this Phase adds only release-1 flags to Phase 3's script (superseded: Phase 3's D12 moved story 23 here; this Phase owns the whole script, ticket 66); admission set pinned equal to Phase 1's; Fanvue story now waits on MP Phase 2 only.
- D12 `oi-backup` makes no DB copy: **accept** — runbook uses `sqlite3 .backup` on the Box plus `proxies.json` and the session list (ASSUMPTION added).
- D13 Acceptance passes with stories unexercised; no fail-fast: **partial** — `set -euo pipefail`, Seam 4 and its mutants, `--toml` round trip, AMBER-exit, page and `--done` tests added; live go-live steps stay human by nature, now each leaving a file `--done` reads.

### Plan review (six hats), 2026-11-26
- Black (b) Phase 4 only detects the source-fence order after the fact — **accept**: Phase 3 now fences the source before the boundary and refuses `oi-cell-open` without the confirmed FenceResult; post-cut stays as the second check; Depends on and D10 updated.
- Red: every P4 ticket is Blocked-by Phase 0's `GATE build` (superseded 2026-11-26: no gate edge); go-live stays the owner's.
- Rests on D3 (unparked 2026-11-26, D3 = B: the live move greys Cell 2 only): story 22 (the one live Planned move uses whichever Fence kind D3 picks; under A it greys the whole source Box, so the runbook must pick a Box with one Cell or accept that grey). Objective's "one live Planned move" with it.
