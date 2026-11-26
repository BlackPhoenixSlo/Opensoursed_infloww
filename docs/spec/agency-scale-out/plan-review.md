# Plan review — agency-scale-out

Plan: `.scratch/agency-scale-out/phased-plan.md` (+ Fable amendments, `OWNER-DECISIONS.md`). Specs: `phase-00-can-one-relay-carry-the-agency.md` … `phase-06-etcd-automation.md`. Glossary: `CONTEXT.md › Cell mode`. ADRs 0058–0064 (0063's D3 note Accepted 2026-11-26: B). Tickets: `.scratch/agency-scale-out/issues/`. Date: 2026-11-26.

ASSUMPTION: specs live in `docs/spec/agency-scale-out/` with this file beside them (rung 3: `docs/spec/creator-badges/` + its `plan-review.md`). Overturned by: an owner or house rule for flat `docs/spec/phase-*` names; then rename all eight files together.

## Re-plan 2026-11-26

Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1–R8); plan top `phased-plan.md` "Re-plan 2026-11-26". Goal: 1,000 models / 1,000 chatters. A ticket waits only on its own or an earlier path. 25 (GATE) blocks nothing.

### Workstreams by path

| Path | Tickets | Ends with |
|---|---|---|
| demo | P0 15, 18–24 (19 by edge) · P1 27–37 · P2 38–42, 44–48 · P3 49–54, 58–60, 64 trimmed · P4 66–71, 75 short, 76–78, 118–120 | AE on box A (R9/R10): shadow, canary wave 1 (Cell 2), full cut wave 2 (Cell 1), Cell 2 relocated to a new slot |
| scale | P0 16, 17, 25, 26 · P3 55, 56 (WireGuard, front Boxes, cross-box move), 57, 63, 65 · P4 72–74, 79 · P6 96–104, 107, 108 · `phase-07-hold-1000.md` | 1,000 models held; 7-day proof; Release 3 |
| later | P2 43 · P3 61, 62 · P4 80, 81 · P5 82–95 · P6 105, 106 | carve, Fansly/Fanvue, rest |

- 22 is resized to 125 stub streams + 125 fetches; a fail brings in gateway fan-in (ADR-0061, Phase 7).
- Grant changes go as deltas at ~100 Cells (ADR-0064); deploys run box-parallel at ~100 Cells (Phase 7).
- Phase 6 is required for 1,000 (ADR-0059). Its entry conditions gate 108 only.
- Honest wording (R5): the demo shows 2 Cells on one box (R9). It is not proof of 1,000.

### Needs the human now (R7 only)

- confirm the 6 lowest-revenue canary models; turn off the standby bundle (R9/R10).
- Offline prod DB copy (60).
- Sign the Feature table.
- Run or approve shadow (119), canary (120), full cut (77) and the Cell 2 relocation (78).
- Paid boxes for 65, 95, 108 (scale and later paths, not now).

D3 is no longer here: decided B.

### Assumptions added

ASSUMPTION: the owner wanted B for D3 (R2). Overturned by: the owner picking power-stop (A); then 47, 53, 78, 92 park again.
ASSUMPTION: a kernel or disk fault on box A takes all of AE down; AMBER for the demo (owner R9, replaces R3's two-box layout). Overturned by: the owner wanting a second Box; then 56 rejoins the demo.
ASSUMPTION: low-value canary models are OK to risk (owner R10). Overturned by: the owner naming none; then one test model only.
ASSUMPTION: disk ≥ 3–4× data and RAM ≥ 2× old relay peak RSS are guesses (g). Overturned by: the shadow stage measuring box A.
ASSUMPTION: 19 and 67 are demo, since demo tickets 38 and 68 wait on them. Overturned by: 38 or 68 dropping that edge.
ASSUMPTION: the Witness runs from the owner's laptop for the demo, with no spare (spare check AMBER). Overturned by: a demo step needing the Witness up while the laptop is off.
ASSUMPTION: the demo needs no live power drill (R9: one Box, no power fence); 23's live run is scale. Overturned by: a demo step that power-stops a VM.
ASSUMPTION: the `witness` drill splits into journal resume (demo) and paging (scale). Overturned by: paging that cannot be cut from the drill; then 57 joins the demo.
ASSUMPTION: the demo's live move counts as the 7-day window's move; the 7 days count after the demo. Overturned by: the owner wanting a second move inside the counted week.
ASSUMPTION: carve (P5) waits until after 1,000, because moves and new Cells rebalance. Overturned by: a Cell over budget that no move can fix.
ASSUMPTION: building P6 before its entry conditions hold is safe, since act mode stays off until 108. Overturned by: the owner wanting no etcd code on main first.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 0 — Can one Relay carry the Agency? (gate; 0a–0j) | `phase-00-can-one-relay-carry-the-agency.md` | None; human P/DB copy, KVM 8, throwaway VM |
| 2 | 1 — Cells on a laptop, read-only | `phase-01-cells-on-a-laptop-read-only.md` | P0 `GATE build` (superseded 2026-11-26, see Re-plan) |
| 3 | 2 — No double sends, Fence, Cell hold | `phase-02-no-double-sends-fence-holds.md` | P0, P1 (code can build beside P1; lands after) |
| 4 | 3 — Moves, Failover, Entry cut | `phase-03-moves-failover-entry-cut.md` | P0, P1, P2 (D3 decided B, 2026-11-26) |
| 5 | 4 — Release 1 live | `phase-04-release-1-live.md` | P0–P3; owner go-live |
| 6 | 5 — Carve a running Cell (Release 2) | `phase-05-carve-a-running-cell.md` | P1–P4 (later path, 2026-11-26) |
| 7 | 6 — etcd automation (Release 3) | `phase-06-etcd-automation.md` | P0–P4; entry conditions gate 108 only; P5 edge dropped (2026-11-26) |

Every Phase is ticketed. Every P1–P6 ticket is Blocked-by `GATE build`; a Defer parks them. (superseded 2026-11-26, see Re-plan). P1 and P3 are several tickets each, not new specs (P1: Placement + env render, relay cell mode + route guard, Agency copy + Actor token, app fan-out; P3: move, Failover + restore, Entry cut, deploy + Hot cell, benchmark).

## Adversary

codex (partly blind), 2026-11-26, one pass per first draft. Each line's status is in the spec's `## Review`. Not re-run on the six-hats revisions (no network this run).

- P0: accept 15, partial 4, reject 2 (D11 counted in both accept and partial). Needs-human: none.
- P1: accept 15, partial 5, reject 5. Needs-human: none.
- P2: accept 16, partial 5, reject 1. Needs-human: none.
- P3: accept 16, partial 4, reject 2. Needs-human: B3, D3 (move Fence kind; decided B 2026-11-26).
- P4: accept 14, partial 5, reject 4. Needs-human: none.
- P5: accept 11, partial 6, reject 4. Needs-human: none.
- P6: accept 10, partial 5, reject 3. Needs-human: none.

## Six hats

Per-spec lines sit under `### Plan review (six hats), 2026-11-26` in each spec, ending with a "Rests on D3:" line. Set-level lines:

- White (c) ticket 05's etcd line stale — **accept**: struck, marked superseded by ADR-0060 (etcd never holds claims).
- White (c) Send permit missing from CONTEXT — **accept**: Send permit, Sending paused (`writes_paused`), Box lease and Cell hold added to `CONTEXT.md › Cell mode`.
- White (c) P and the gate verdict unknown — **accept** as stated: P is a P0 human input; the verdict is P0's output.
- Red top-heavy before the gate — **partial**: all Phases stay specced and ticketed, but nothing past 0a–0j can start before `GATE build`. (superseded 2026-11-26, see Re-plan).
- Red specs contradict each other — **accept**: one consistency pass done (Blue 1): P6 Fence → `down`, `cells-acceptance.sh`, Control `${OI_ACCOUNTS?}` in P1, one Cell hold, Entry cut fence order in P3/P4/ADR-0063.
- Black (b) Entry cut fences after the boundary, original boots fail-open, P4 sees it late — **accept**: P3 power-fences today's Box at step 3, moves session folders aside, refuses `oi-cell-open` without the confirmed FenceResult; P4 post-cut stays as second check.
- Black contradictions (P6 order, script name, `OI_ACCOUNTS` template) — **accept** all three (P6, P1, P1/P3).
- Black (d) P1/P3 too big — **partial**: split into tickets, not specs.
- Black (d) P3 needs 8–11 paid Boxes — **reject**: already a needs-human manual line with a scaled run that names what it does not prove.
- Black (d) three holds drift — **partial**: one term (Cell hold), one store (`cell_holds`, P2), one refusal (`cell_held`); kinds differ in scope, what they block and who releases, so three `why` values, not one behaviour.
- Yellow (safety core, env-unset byte diff, P0 gate, extras flagged) — no change; kept.
- Green (a) pick B by ticket 10 as rung 2 — **reject** the rung: ticket 10 and ADR-0063 were written by this run. D3 stays needs-human, default B flagged ASSUMPTION, ADR-0063 notes it. (superseded 2026-11-26, see Re-plan); D3 decided B.
- Green (b) power fence for the Entry cut — **accept** (with Black (b)); one Box, no siblings, so not on D3.
- Green doing-less: ticket only P0 — **partial** (see Red). Split P1/P3 into 4 — **partial** (tickets). Merge holds — **partial** (see Black (d)). P6 drops its P5 dependency — **reject**: plan orders Release 2 before 3 (rung 2) and `carve` moves onto the etcd writer key in P6. (superseded 2026-11-26, see Re-plan); accepted, carve is later.
- Blue (1) one docs consistency pass — **accept**, done here. Blue (2) ticket P0 0a–0j only — **partial** (see Red). Blue (3) split P1/P3 after `GATE build` — **accept** at ticket time, as tickets.
- Recommendation (consistency pass, gate first, split later) — **partial**: adopted except "ticket only P0"; the gate block gives the same protection.

## Cut (YAGNI)

- Merging Cells back or returning to one Box: refused (ADR-0062, owner chose clone).
- Cross-cell S4S: closed in Release 1; carve refuses.
- Carving the Control cell: never.
- Auto regroup, hot-cell rebalancer, auto Planned moves or Carves: a human applies every plan; Release 3 automates Box death only.
- Automating the proxy fence: stays human until the open-tunnel drill passes.
- Send claims in etcd or any etcd role in sends: ADR-0060; one SQLite claim store, no fallback.
- Send claims in single-Box mode; folding old funnel/followup markers into `send_ops`: ticket 05 fog.
- Op ids for feed posts and stories; pausing writes outside `dispatch()`: no Op ID in v1; power Fence still stops a stale Box.
- Rejected designs: gateway service, signed Placement, per-row generation columns, SharedWorker (unless their trigger fires).
- Crypto signature on the Feature table: P0g's `signed` block is the signature.
- A second Witness or Conductor; a second page contact; the Witness provider: one per Agency, 03 fog, owner's call.
- Postgres, Kubernetes: owner.
- Pruning after the Entry cut; data generation bump on prune; per-table copy checksum: not needed for safety; file hashes prove the copy.
- Turning Browserbase off in a carve: drain + identity recheck suffices.
- Dropping `sessions.cookies_json`: no runtime reader; not this effort's question.
- Moving `last_seen` writes off Cells: local columns (ticket 07).
- Wizard copy change: waits for ticket 12's release boundary.
- Cross-cell reads beyond All inbox, roster, recent seed (analytics, CSV, sales, payroll gate, auto clock-out, public slugs): `cell_scope_closed` in Release 1.
- Queue edit as reschedule; Fansly CLI; Browserbase on provider proxies: ticket 04/05 fog.
- Starting with a new Agency instead of cutting the existing one: plan names the Entry cut.
- Slop or volume runs for Release 1: proof is 7 live days + Seam 4.
- Measuring P from a live Box: never prod.

## Not yet specified

- Front-door uptime target: P4 asks the owner at T-7 d, but no spec turns the number into a check, alert or design (i).
- Fansly/Fanvue Cells: wait on MP mixed-platform restore drill and Fansly proxy support (gate only, in P4).
- Bio in Cell mode; comparing rows changed after a snapshot (ticket 03/10 fog).
- Ticket split of P1/P3: named per spec, written at ticket time.

## Open questions

Every ASSUMPTION in the specs, sharpest first, with what falls if it is wrong.

1. (Decided 2026-11-26: B; R2 ASSUMPTION in Re-plan.) P3: a Planned move with a reachable source uses a `cell` Fence (B) until D3. Falls: under A, P2 story 24 (move part), P3 stories 1/5/30, P4 story 22, P5 stories 7/14 + step h; every move/carve greys 2–3 sibling Cells.
2. P0: P = 200 until the owner gives one or a DB copy. Falls: N, the ladder, the gate verdict; 0c reruns. (superseded 2026-11-26, see Re-plan); target is 1,000 models.
3. P2: a full 4xx from OF means not accepted. Falls: the attempt rule; a retry double-sends.
4. P3: a powered-on original stays closed by moving session folders aside, not cell-mode env. Falls: Entry cut abort safety; original could egress beside the Cells.
5. P3: today's VM power-fenced at step 3 and kept frozen. Falls: rollback path; reuse needs re-image after every Cell is live. (superseded by R9/R10 2026-11-26: the old relay container is cell-fenced on A, data dir kept aside; no re-image.)
6. P2 (evidence blocked): providers offer per-Cell credentials or a revoke API. Falls: the proxy fence; unreachable Boxes need power only.
7. P0: shards stand in for Cells. Falls: the gate; Front door/Agency copy overhead measured only in P3.
8. P0: Build needs 3/3 misses. Falls: gate verdict on a 2/3 miss. (superseded 2026-11-26, see Re-plan); the gate blocks nothing.
9. P2: restore, move, carve pauses are one Cell hold in one DB table. Falls: P2 story 16, P3 move pause, P5 story 6, if a hold must outlive the DB.
10. P5: hold is P2's `cell_holds` row, not a `data/` file. Falls: carve hold on a Cell whose DB cannot be written while stopped.
11. P2: one local SQLite claim write per send is fast enough. Falls: Cell budget if claim p99 > 100 ms.
12. P2: FenceResult expires 10 min after confirmation. Falls: a stale fence opening a target after a Hostinger restart.
13. P2: 180 s confirm window, 5 s read gap. Falls: P3 recovery time.
14. P3: Failover publishes `down` only after a confirmed Fence. Falls: owner wanting a `down` page state first; P2 story 25 must change.
15. P4: a Creator failing admission blocks the whole Entry cut. Falls: owner accepting a leftover single Box; runbook gains a second login.
16. P1: past max Grant age a Cell refuses every human request, owners included. Falls: owner service through a long control outage.
17. P6: pause signal is a per-Box lease plus a local Send permit file. Falls: P6 stories 11–16 if the permit lags the lease.
18. P6: Send claims stay in Cell SQLite in Release 3. Falls: an owner want for etcd claims; ADR-0060.
19. P3: Entry cut is once and stopped; data Cells boot in parallel after Control. Falls: grey over a quiet hour; open in waves.
20. P3: Entry-cut grey ≤15 min (g). Falls: quiet-hour fit; prod-copy drill timing decides.
21. P1: Relay enforces `X-Cell-Gen` against its own `data_gen`. Falls: tickets 06, 10 if a write path skips the Front door.
22. P1: "read-only" = no upstream sends/publishes; local writes and mark-read/like/pin work. Falls: Phase 1 scope if the owner wants all model writes refused.
23. P1: boot-time Placement check does not break ADR-0059. Falls: the check; env-only fallback.
24. P1: Control renders `${OI_ACCOUNTS?}`. Falls: P3 Entry cut step 4 if a role-aware template replaces it.
25. P6: during quorum loss manual `fleet.py` cannot publish. Falls: break-glass needs its own fenced path.
26. P6: one writer key for Conductor and manual verbs, refused not queued. Falls: P6 story 8.
27. P6: trigger ≥2 min probe fail + lease gone; TTL 30 s, renew 5 s, permit 15 s (g). Falls: drill timings.
28. P6: published generation = `gen_base` + revision + 1. Falls: generation monotonicity after a cluster rebuild.
29. P6: "fan writes" = `dispatch()` sends, `_proxy_message_write`, automation ticks. Falls: pause scope if the owner wants feed posts or mark-read paused.
30. P5: hold refuses every mutating route via P1's route guard. Falls: per-endpoint gaps (promo, S4S accept).
31. P5: hold also blocks new remote logins. Falls: step-d recheck if mid-carve logins must be allowed.
32. P5: frozen original gets P3's Cell fence, not power. Falls: under A the source half must land on another Box.
33. P5: source half keeps its Cell id at `e{N+1}`; new half gets a new id. Falls: route re-keying if Placement needs both renamed.
34. P5: pre-carve restore refusal is a bucket carve record checked by epoch. Falls: if manifest v2 already carries membership.
35. P5: staged G+1, live G+2. Falls: if P1's startup check accepts an absent Cell.
36. P5: S4S open-leg checks read SQLite `mode=ro` live and frozen. Falls: missed committed WAL rows; frozen recheck then carries it.
37. P5: grey p95 ≤120 s (g). Falls: drill timings.
38. P5: local container drill is the laptop proof; 10/10 box run needs owner yes. Falls: if owner waives the box run.
39. P5: Browserbase stays on. Falls: if a login itself harms.
40. P4: Fansly gate needs Fansly proxy support as well as the MP drill. Falls: owner-accepted direct-egress Fence for Fansly.
41. P4: Phase 2 `digest` equals the hash of the synced body. Falls: match on `upstream_id` only; digest misses AMBER.
42. P4: P3's pager writes the delivery record. Falls: P4 adds the write, or reads P3's own record.
43. P4: same-body-within-60 s pairs are AMBER. Falls: RED if P0e baseline shows 0 pairs.
44. P4: planner's DB copy is `sqlite3 .backup` on the Box. Falls: runbook step if `oi-backup` gains a DB file.
45. P4: Restore manifest and backup freshness bar 1 h. Falls: P3's measured backup lag.
46. P4: quietest hour from 4 weeks of DM + `actions` rows. Falls: owner names an hour.
47. P4: 7 UTC days from Entry cut end, red day restarts. Falls: owner's own exit rule.
48. P4: `cell_release_proof` WATCH line only for AE. Falls: owner wanting it for any go-live.
49. P3: preflight refuses a non-admitted account rather than leaving it out. Falls: owner signing those Creators off; `--leave` quarantines.
50. P3: relay gains per-route p95 and pool-wait metrics (i). Falls: benchmark evidence if no exporter.
51. P3: 60 s drain, 3 parallel restores, 24 h peek, thresholds (g). Falls: benchmark.
52. P3: N/N+1 smoke's N+1 is a throwaway drill commit. Falls: a real format change in the same window replaces it.
53. P3: prod-copy drill uses synthetic session folders. Falls: drill realism, never safety.
54. P3: this Phase owns WireGuard/front-route rendering. Falls: P1/P3 ticket boundary.
55. P2: blanket restore hold stands in for P3's per-thread peek. Falls: hold scope narrows when P3 lands.
56. P2: P2's append-only fence record is adopted by P3's Witness journal. Falls: P3 journal format.
57. P2: "6 gap kinds". Falls: kill matrix finds a seventh unanchored.
58. P2: mutants via test `--break`, fence mutants on cp-backed copy. Falls: a mutant needing a `service/` hook.
59. P1: all Cells share control's VAPID key pair. Falls: push, if marked off in the Feature table.
60. P1: publish refusal is P1-only. Falls: if P2 puts publishing behind `dispatch()`.
61. P1: wait-for-all over flooring from responders. Falls: staff creation with a Cell down.
62. P1: `OI_CELL_ROLE` env names control vs data. Falls: startup check shape.
63. P1: cell-mode tables created at cell-mode boot, not main migrations. Falls: if the migration runner cannot skip them.
64. P1: acceptance imports FakeOF from `slop/lib/of_wire.py` standalone. Falls: a copy moves to fleet tests.
65. P1: script is `deploy/fleet/tests/cells-acceptance.sh`. Falls: rename in P1–P3 together.
66. P0: distinct senders per 15 min stand in for "online at once". Falls: N undercounts readers.
67. P0: N/4 steps. Falls: locating a bend between steps.
68. P0: "more per Relay" = ≥1 ladder step margin (g). Falls: noise larger than a step.
69. P0: no Cell-scope enforcement in P0. Falls: nothing; P1 wires it on Build.
70. P0: Feature table draft states (off cheaper to turn on). Falls: owner marking any needed at launch.
71. P0: OF fan ids fit SQLite int64. Falls: grouping for ids above 2^63 rests on the Python post-check.
72. P0: grouping script lands with P1's `fleet.toml`. Falls: owner wanting it before the gate.
73. P0: subprocess 100-load test separates fixed from reverted. Falls: only the Box run guards 0a.
74. P0: stream spike lives in `.scratch`. Falls: if P1 reuses it as is.
75. P0: drill scripts live beside fleet.py. Falls: P2 lifts the confirm rule in.
76. P6: etcd on Witness + 2 voter Boxes across ≥2 providers. Falls: cost.
77. P6: etcd via HTTP/JSON gateway with stdlib. Falls: `etcdctl` if keepalive streaming is missing.
78. P6: observe week, morning summary, owner go-live added default-off. Falls: P6 story 20 and two manual lines if skipped.

## Needs the human

- **P0:** P or a prod DB copy; written yes + slop-cap waiver; an uncontended KVM 8 (superseded 2026-11-26, see Re-plan); a throwaway Hostinger VM (0i power drill 10/10); Webshare/IPRoyal sub-user / revoke check; signing the Feature table; `prod-install-watchdog.sh apply` after 0j.
- **P1:** none beyond P0's gate; owner looks at settled screenshots.
- **P2:** none new; proxy fence stays "unavailable" until P0i's provider check + an open-tunnel drill.
- **P3:** prod DB copy for the Entry cut drill; 8–11 throwaway Boxes + a Witness box (scale path); yes + slop-cap waiver for held load (superseded 2026-11-26, see Re-plan).
- **P4:** max Grant age (15 vs ~5.5 min); Front-door uptime target (superseded 2026-11-26, see Re-plan); Feature table signature; Boxes, spare, Witness, per-Cell proxy credentials; DB copy + applying the grouping plan; the go-live.
- **P5:** 10/10 box run + yes (or waiver); first live carve.
- **P6:** entry conditions (P4 proof, power drill 10/10, 90 days Witness logs on ≥5 Boxes, ≥2 slow deaths or owner rejects human response); etcd image pull; 7-day observe; act-mode go-live.
- Optional: re-run the adversary on the revised specs before `--execute`.
