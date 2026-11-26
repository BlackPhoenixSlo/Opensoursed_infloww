# Phase 06 — Release 3: etcd automation

**Objective.** A dead Box's Cells come back on the spare without a human, through the same Fence and Failover steps as Release 1, with Placement and the Witness journal behind etcd compare-and-set, and a Box that loses quorum keeps serving authorized reads while it stops new fan writes.

Plan: `.scratch/agency-scale-out/phased-plan.md` Phase 6. Tickets: 03 (item 9 + conditions), 04, 05, 10, 12. Codex #2 (accepted, binding). ADRs: 0059, 0060, 0063 (no new ADR).

Amended 2026-11-26: required for 1,000 models (scale path; ADR-0059 amended). Human Failover is a stopgap for the demo. Building 96–104 and 107 does not wait for the conditions below; they gate turning it on live (108).

## Entry conditions (gate turning it on live, ticket 108; amended 2026-11-26, was: gate starting this Phase)
- Release 1 live (Phase 4) and its 7-day proof passed.
- Ticket 03's three: real power-off drill 10/10 (Phase 0 item 0i); ≥90 days of Witness incident logs across ≥5 Boxes; ≥2 unplanned Box deaths in 90 days with page → Failover start >10 min, or the owner rejects human response times.
- Numbers (g), from 03.

## Problem Statement
In Release 1 a dead Box pages the owner every 15 min with the `fleet.py failover` command, and its Creators stay grey until the owner runs it. After the slow nights the entry condition counts, the owner's response time is the outage (i). The owner wants Box deaths fixed without being woken, never at the cost of a duplicate send or two sessions on one account.

## Solution
- A **Conductor** on the Witness box runs Release 1's exact Failover (03 item 5, 04 Fence, 10 journal) itself when a Box is silent to the probe and its etcd lease has expired. If the Fence cannot be confirmed it acts on nothing and pages, as in Release 1.
- etcd (Witness box + 2 voter Boxes) holds Placement and the Witness journal; every write is a compare-and-set.
- Each Box's lease agent keeps a short-lived **Send permit** per Cell. Lost lease or lost quorum lets it lapse: reads and live updates go on, new fan sends and automations pause with a "sending paused" reason. Cells never talk to etcd; claims stay in Cell SQLite. No peer-majority rule, no local fallback.

## User Stories
1. As the owner, I want Cell mode automation to start only after 03's entry conditions are met and recorded, so that etcd is added for counted Box deaths, not by default. [parallel-safe now]
2. As the owner, I want a dead Box's Cells live on the spare without my action, so that night-time Box deaths no longer wait for me. [parallel-safe now]
3. As the owner, I want automatic Failover to run only when the Witness probe has failed for 2 min **and** the Box's etcd lease has expired, so that a short network blip never powers off a healthy Box. [parallel-safe now]
4. As the owner, I want the Conductor to take over only after a confirmed power Fence (ticket 04: action `success`, two `stopped` reads ≥5 s apart with matching IP, re-read after the Owner epoch write), so that automation is never less safe than me running the command. [parallel-safe now]
5. As the owner, I want the proxy fence to stay a human step in Release 3, so that automation never acts on a fence no drill has proven. [parallel-safe now]
6. As the owner, when the provider's fence API is broken or slow, I want no takeover, no Placement write, the Cells kept down, and a page saying "target stayed closed, source unknown" with evidence and the resume command, so that I decide. [parallel-safe now]
7. As the owner, I want Placement under one etcd key, written only by compare-and-set on its revision, with the published generation derived from the etcd revision (no counter or lock of its own) and still above every Release 1 generation, so that two writers can never both publish and Boxes keep refusing a lower one. [parallel-safe now]
8. As the owner, I want every Placement change and journal step, automatic or manual (`conduct`, `failover`, `resume`, `move`, `carve`, `etcd-export`), to hold the one etcd writer key, and each step to write `started` by compare-and-set before its side effect and `done` after, takeovers one at a time, so that a stale or second writer, even one still running, cannot start a new side effect. [parallel-safe now]
9. As the owner, I want `resume` after a Conductor crash to re-run the first step not marked done, exactly as Release 1 (ticket 10), so that a crash at any step is safe. [parallel-safe now]
10. As the owner, I want Gateways and the Front door to keep reading the local `placement.json`, installed by each Box's lease agent from the etcd key with Release 1's checks (lower generation, same generation with other bytes, bad schema, wrong Agency all refused) and an ack, so that routing never depends on reaching etcd. [parallel-safe now]
11. As a chatter, when my Box loses quorum, I want the inbox, chats and live updates to keep working under my normal grants (an expired or revoked Grant is still refused), so that I can keep reading. [parallel-safe now]
12. As a chatter, when my Box loses quorum, I want my send refused with a visible "sending paused" reason and no Retry button, not a silent failure or a retry, so that I know to wait. [parallel-safe now]
13. As the owner, I want automations on a paused Cell to hold their jobs (not fail, skip or advance them) until the permit is back, so that nothing is lost or doubled by the pause. [parallel-safe now]
14. As the owner, I want a Box that cannot renew its lease to pause fan writes on its own, with no peer-majority override, so that quorum coming back can never meet a send a stale owner made meanwhile (Codex #2). [parallel-safe now]
15. As the owner, I want `oi-lease` to write a Cell's first Send permit under a new lease only after a fresh bucket read shows the Owner epoch equals the Cell's own and names this Box (the `oi-cell-open` rule; unreadable bucket = no permit), so that a Box that came back after a takeover stays silent. [parallel-safe now]
16. As the owner, I want a missing, unreadable or expired Send permit to mean "paused", so that a reboot, a copied folder or a dead lease agent fails closed. [parallel-safe now]
17. As the owner, I want send claims to stay in each Cell's SQLite and Cells never to call etcd when sending, so that etcd is not on the send path and there is still one claim store. [parallel-safe now]
18. As the owner, while quorum is lost, I want no Placement change, no Failover and no Planned move, automatic or manual, plus a page, so that no second writer appears beside etcd. [parallel-safe now]
19. As the owner, I want pages for: quorum lost >1 min, a Box with no lease while its probe is fine >2 min (alive but paused), Conductor not running, Fence unconfirmed, Failover stuck at a step, a dead Box holding a Cell not admitted to automation; a finished automatic Failover sends no page, only a line in a morning summary, so that I am woken only when automation stopped. [parallel-safe now]
20. As the owner, I want an observe-only Conductor first (logs what it would do), installed in N/N+1 order (lease agent + permit reader, then Cells one at a time, Conductor writes last), so that its decisions are checked against human pages before it acts. [parallel-safe now]
21. As the owner, I want a one-command rollback to Release 1 (stop the Conductor, refuse while a journal op is open, export Placement to `fleet.toml` at generation+1 under the writer key, Cells stop checking permits), so that etcd can be removed without data or routing changes. [parallel-safe now]
22. As the owner, I want automatic Failover for Fansly Cells only after the MP mixed-platform restore drill (until then the Conductor pages for that Cell and fails over the rest of the Box), so that a Fansly Cell is never restored unproven. [waits for MP mixed-platform restore drill]
23. As the owner, I want automatic Failover for Fanvue Cells only after MP Phase 2, same per-Cell page rule, so that it follows that Platform's runtime contract. [waits for MP Phase 2 merged]
24. As the owner, I want 20 kill drills with 0 duplicate sends, a lost-quorum drill (reads continue, fan writes pause) and a broken-fence-API drill (no takeover, page sent) to pass, each with a mutant that turns it red, before Release 3 acts. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - fleet.py: Placement store backend (file or etcd) used by every verb that publishes (Phase 3 `failover`/`resume`/`move`, Phase 5 `carve`), journal backend, writer key, `conduct` command (Conductor loop, observe and act), `etcd-seed`, `etcd-export` (rollback).
  - New box tool `oi-lease` (beside `oi-epoch`): lease keepalive, Send permit writer, Placement installer from etcd.
  - Relay `send_ops.dispatch()` (Phase 2's) gains one check: Send permit fresh. `server.py` `_proxy_message_write` (unsend, hide, like, pin, bookmark) gains the same check. Automation executor tick gains it at its top (saves churn; `dispatch()` stays the guard for jobs already queued behind a run slot).
  - App composer and message bubble: map `writes_paused` to "Sending paused", no Retry button.
  - Witness probe and pager (Phase 3's) gain the R3 pages.
- **Interfaces.**
  - `fleet.py conduct [--observe]`: one loop; decision is a pure function `decide(probe, lease, fence, journal, cell_platforms) → action` (none, page, start_failover, resume). `--observe` never takes the writer key.
  - Writer key `/oi/<agency>/writer/leader`: held on an etcd lease by whichever fleet.py process writes (Conductor or a manual verb); a second writer is refused, not queued.
  - `fleet.py etcd-seed`: writes current Placement and `gen_base` = its generation to etcd; refuses if any Witness journal op is open. A rebuilt cluster is seeded again the same way.
  - `fleet.py etcd-export`: needs the writer key and no open journal op; reads the etcd key, writes `fleet.toml` + publishes at generation+1 over SSH (Release 1 path).
  - `oi-lease run`: grants a Box lease (TTL 30 s, g), renews every 5 s (g). On each new lease it reads the bucket epoch per Cell and writes a permit only for Cells passing the `oi-cell-open` rule; then per renew writes `/run/oi/<cell>/send_permit` = `{lease_id, box, until}` with `until = last_renew + 15 s` (g). Installs Placement on key change with Release 1's checks, acks to `/oi/<agency>/acks/<box>`.
  - `dispatch()` and `_proxy_message_write`: when `OI_CELL_SEND_PERMIT` is set, refuse `writes_paused` (HTTP 503) before the claim if the file is missing, unreadable, names another Box, or `until` has passed. Unset env = check not run (Release 1 and single box unchanged).
- **Schema.** None in SQLite. etcd keys (all under `/oi/<agency>/`):
  ```
  placement           = placement.json bytes (same schema; gains "store":"etcd")
  ops/<op>/<step>     = journal line (ticket 10 shape, gains "rev_expected")
  leases/<box>        = {box, lease_id}   (attached to the Box lease)
  acks/<box>          = {generation, sha256}
  gen_base            = last Release 1 generation (set by etcd-seed)
  writer/leader       = writer key (writer's own lease)
  ```
- **Contracts.**
  - Placement write: txn `if mod_revision(placement) == expected && writer key is ours then put placement, put ops/<op>/<step>`. `generation` in the JSON = `gen_base` + the etcd revision returned with the read of `expected` + 1: derived from the revision, no counter or lock of its own (03 item 9), strictly above the previous generation and every Release 1 one.
  - Journal step: CAS `started` (writer key ours) → side effect → CAS `done`. A failed CAS ends the process before any further side effect. Every side effect is safe to repeat (power stop of a stopped VM, epoch write refused for another Box, restore onto a closed target), so a resume that repeats a `started` step is safe (ticket 10).
  - Talk to etcd over its HTTP/JSON gateway with stdlib (house precedent: `oi-epoch` is stdlib SigV4, m). No new Python dependency.
  - Send permit file: on a per-Cell tmpfs bind mount, read-only inside the Cell, never under `data/`, so a Planned move, backup or Carve never copies it.
  - New refusal code `writes_paused` (503), never retried by the app; automation jobs treat it as "not run yet".
- **Failover trigger and order.** Trigger: Witness probe failed ≥2 min (Release 1 page threshold) **and** `leases/<box>` gone. Then Release 1's order unchanged (Phase 3): Fence (power only, pinned `vm_id`, map IP check; proxy fence stays human) → publish `down` → Owner epoch write (refused for a second Box) → re-read `stopped` (a failed or timed-out read blocks restore) → restore (manifest v2 checks, hash mismatch stops) → target egress gate → readiness (every Owned Creator logs in once) → publish `live` → wait first good backup → clean source. A Cell whose Platform is not admitted to automation is skipped and paged. Ticket 05's lossy-restore rules apply unchanged (Data generation bump, 24 h peek, parking).
- **Pause timing.** Permit lapses at 15 s without renew; lease expires at 30 s; takeover needs ≥2 min probe failure plus a confirmed power-off. The pause is defence in depth; the Fence stays the safety (ADR-0063).
- **Quorum loss.** Every Box pauses its own Cells via the permit. Reads stay on: the Front door reads its local file and Cells check actor token and Grant age as in Phases 1–2. A chatter opening a thread may still mark it read upstream (a read, not a fan write). In-flight claims finish under ticket 05's one-attempt rule; no new claims. No writer can get the writer key, so no Fence, epoch write, restore, Placement or journal write runs.
- **Etcd members.** Witness box + 2 voter Boxes, on at least 2 providers. A voter Box still runs Cells.
- **Upgrade.** Placement gains `store`; journal lines gain `rev_expected` (formats only gain fields, 12). Release N (readers): box tools (`oi-lease`, permit reader, etcd installer) → data Cells one at a time (permit check present, not required) → Caddy + app (`writes_paused` mapping) → Control last. Release N+1 (writers): `etcd-seed` → `min_cell_proto` bump → `OI_CELL_SEND_PERMIT` Cell by Cell → Conductor `--observe` 7 days (g) → act. Rollback = `etcd-export` at a higher generation.

## Testing Decisions
- **Seam 1 (main): `deploy/fleet/tests/failover-in-containers.sh --etcd`.** Extends the existing container drill: 3 etcd members, boxes a, b and a spare, MinIO, the Hostinger stub (`api_stubs.py`), a FakeOF that counts sends. Drives the real `fleet.py conduct`, `oi-lease`, `oi-epoch`, relay and app. Cases:
  - Power stub tied to the containers: a Box keeps running until the stub's stop lands (no `docker kill` before the Conductor acts, except the kill cases).
  - 20 Box kills mid-traffic, each with a send FakeOF accepted just before the kill and one claimed but not sent: spare live, the same Op IDs replayed after restore give 0 new accepts, ≤1 accept per Op ID, 0 duplicates, then a fresh send from the spare gives 1 accept; 0 pages on success, one morning-summary line.
  - Lost quorum (2 members stopped): inbox and SSE work under a fresh Grant, an expired Grant is refused; send and unsend give `writes_paused` with no Retry in the bubble; a job queued behind a run slot when the permit lapses stays pending and runs once after quorum is back; 0 Fence, epoch, restore, Placement or journal writes; a manual `fleet.py move` is refused; page sent; quorum back → sends resume.
  - Box cut from etcd but not FakeOF: its sends stop ≤15 s; takeover only after confirmed power-off; a Box cut from etcd with probe fine pages "alive but paused".
  - Fence API broken (errors, timeouts, `stopping` forever, wrong VM id) and post-epoch read timing out: a failed Fence writes 0 Placement generations (no `down`); after a confirmed Fence with the post-epoch read timing out, only the `down` generation exists; 0 restore, 0 `live` publish, 0 epoch writes before a confirmed stop; page with resume command.
  - Conductor killed after each step resumes; two Conductors: one acts; a Conductor paused (SIGSTOP) past its lease then resumed starts 0 new side effects; old Box back after takeover gets no permit.
  - Box with one Fansly Cell dies before the MP drill: OnlyFans Cells fail over, the Fansly Cell stays down and pages.
  - Upgrade: N/N+1 order above, `min_cell_proto` stops an old relay; control-first fails.
  - `etcd-export` rollback works and is refused with an open op; env unset run identical to main.
- **`--etcd --break <mutant>`**, house rule: exits 0 only when that mutant's own check goes red and no other. Mutants: `permit-skip`, `peer-majority`, `cas-no-rev`, `no-fence`, `down-before-fence`, `permit-no-epoch`, `writer-no-cas`.
- **Seam 2: `deploy/fleet/tests/test_failover.py`** (pytest, stubs): pure `decide()` table (incl. per-Cell platform gate), CAS refusal handling, generation from revision (re-seeded cluster never lower), writer-key refusal, permit freshness rules, etcd installer refusals (lower generation, same generation other bytes, bad schema, wrong Agency) and ack, `carve` publishing through the etcd store, `etcd-seed`/`etcd-export` refusal with an open op.
- App: vitest on the `writes_paused` mapping (message, no Retry).
- Relay `dispatch()` permit check rides Phase 2's `service/tests/test_send_ops_kill.py` (plain script) with one added case.
- Prior art: `failover-in-containers.sh` and its `--break` mutant; `test_failover.py` with `api_stubs.Stubs`; `test_send_once.py` `_Killed` pattern.

## Acceptance
```sh
cd repo
set -e
venv/bin/python -m pytest -q deploy/fleet/tests/test_failover.py
venv/bin/python service/tests/test_send_ops_kill.py
(cd app && pnpm test:run)
nice -n 10 deploy/fleet/tests/failover-in-containers.sh --etcd
for m in permit-skip peer-majority cas-no-rev no-fence permit-no-epoch writer-no-cas; do
  nice -n 10 deploy/fleet/tests/failover-in-containers.sh --etcd --break "$m"
done
scripts/run-tests.sh
# manual, 108 only: Phase 4 7-day proof passed
# manual, 108 only: entry conditions recorded (power-off drill 10/10, 90 days of Witness logs on >=5 Boxes, >=2 slow unplanned deaths or owner rejects human response)
# manual: pull the etcd image/binary for the drill and the boxes (new dependency, human runs the pull)
# manual: 7 days of Conductor --observe on the live Agency, decisions match human pages
# manual: owner go-live for act mode
```

## Depends on
- Phase 1: Placement, its Box-side install checks, `OI_ACCOUNTS`, the Front door reading a local file, Grant age rules, `min_cell_proto`.
- Phase 2: `send_ops.dispatch()`, Send tripwire, Retry off, the Fence path (pinned `vm_id`, epoch refusing a second Box, egress gate) and `oi-cell-open` rule every promotion shares.
- Phase 3: Witness probe and pages, Witness journal with resume, restore manifest v2, readiness, 05's lossy-restore reconcile, N/N+1 smoke, the container drill this Phase extends.
- Phase 4: Release 1 live and the Platform admission this Phase's per-Cell gate reuses; its 7-day proof gates 108 only (2026-11-26).
- Phase 5: Release 2 ships first (map order); `carve` moves onto the etcd store here. (superseded 2026-11-26: dropped; Phase 5 is later, scale cannot wait on it. When carve lands it uses the etcd writer key.)
- Phase 0 items 0i (power-off drill, an entry condition) and 0j (`notify.sh` fails loudly; pages must be delivered).

## Out of Scope
- Automating the proxy fence: unproven until ticket 04's open-tunnel drill passes; stays a human step.
- Send claims in etcd: Cells never touch etcd when sending (03, ADR-0059, map); one claim store stays SQLite.
- Pausing upstream writes outside `dispatch()` (feed posts, stories, vault uploads): they have no Op ID in v1 (05 fog); the power Fence still stops a stale Box.
- Automatic Planned moves or Carves on hot cells: Release 3's goal is Box death only.
- A second Witness or Conductor: one per Agency (03).
- Postgres, Kubernetes: owner.
- Second contact when a page goes unanswered: 03 fog.

## Further Notes
ASSUMPTION: Send claims stay in Cell SQLite in Release 3 (ticket 03 item 9, map.md, plan Phase 6 "no local claim fallback": rung 2; ADR-0060 agrees); ticket 05's "if etcd comes later, it replaces this store" is read as superseded. Overturned by the owner wanting claims in etcd; then etcd sits on the send path and ADR-0060 needs a superseding ADR.
ASSUMPTION: the pause signal is a per-Box lease plus a local Send permit file, not Cells calling etcd (rung 5; keeps 03's "Cells never touch etcd"). Overturned by a drill where the permit file lags the lease; falls: stories 11–16.
ASSUMPTION: "fan writes" = sends through `dispatch()`, message writes through `_proxy_message_write`, plus automation ticks; a chatter's thread open marking read upstream is a read (rung 5). Overturned by an owner ask to pause feed posts or mark-read too; falls: Out of Scope item 3.
ASSUMPTION: the published generation = `gen_base` + etcd revision + 1, not the raw revision (rung 4: a rebuilt cluster restarts revisions at 1 and Boxes refuse lower generations, 12; still "revision replaces the counter and the lock", 03 item 9). Overturned by 03 read as "raw revision only"; falls: story 7.
ASSUMPTION: the 7-day observe week, morning summary and owner go-live are not in the plan's proof list; added as default-off, reversible steps (rung 4). Overturned by the owner skipping them; falls: story 20, two manual Acceptance lines.
ASSUMPTION: one writer key for the Conductor and every manual verb, refused not queued (rung 5; 04 "takeovers one at a time"). Overturned by a drill where a manual resume races the Conductor badly; falls: story 8.
ASSUMPTION: during quorum loss manual `fleet.py` cannot publish either (rung 4, fail closed; Codex #2 no-fallback by analogy). Overturned by an owner break-glass ask; it would need its own fenced path.
ASSUMPTION: trigger = probe failed ≥2 min and lease gone; lease TTL 30 s, renew 5 s, permit 15 s, observe week 7 days, quorum page at 1 min (g, rung 5). Overturned by drill timings.
ASSUMPTION: etcd members on the Witness box + 2 voter Boxes across ≥2 providers (03 + rung 4). Overturned by cost.
ASSUMPTION: etcd reached through its HTTP/JSON gateway with stdlib (rung 3: `oi-epoch`). Overturned if the gateway lacks lease keepalive streaming on the pinned version; then use the `etcdctl` binary.
Send permit, `writes_paused` and Box lease are defined in CONTEXT.md "Cell mode" (added by the 2026-11-26 plan review).

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1, R4, R7). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Required for 1,000.** At 15–40 Boxes (i) a human paged at night is the outage. ADR-0059 amended.
- **Paths.** scale: 96–104, 107, 108. later: 105, 106 (Fansly, Fanvue). None is on the demo path.
- **Edges.** No ticket waits on 25 (GATE). The Phase 5 edge is dropped. The 7-day proof and the entry conditions gate 108 only.
  ASSUMPTION: building 96–104 and 107 before the entry conditions hold is safe, since act mode stays off until 108 (rung 4: unused code is reversible). Overturned by: the owner wanting no etcd code on main before the conditions are counted.
- **D3 = B:** no change here. Release 3 automates only the power Fence.
- **Human (R7):** paid boxes and the go-live for 108.
- Beyond Release 3 at ~100 Cells: `phase-07-hold-1000.md`.

## Review
codex (gpt, effort high), partly blind (read .scratch via git objects), 2026-11-26. Blind call B1–B6, draft call D1–D12.
- B1 alternatives (keep human Failover; single-Witness Conductor without etcd): **reject**. Plan Phase 6 and 03 item 9 fix etcd + Witness + 2 voters (rung 2); the entry condition already measures whether human response is the bottleneck.
- B2 release gate omits ≥5 Boxes / "slow" undefined: **reject**. Entry conditions already carry 03's three verbatim, incl. ≥5 Boxes and page → start >10 min.
- B3 claim store conflict, how a Box learns it is stale, define fan writes, thread-head GET marks read: **partial**. Claims/permit already decided; fan writes now include `_proxy_message_write`; chatter mark-read stays a read (ASSUMPTION added).
- B4 contention with move/Carve, unjournaled side effects, monotonic Placement, carry forward Fence checks, page delivery: **partial**. Writer key + `started`/`done` CAS, derived generation, explicit Failover check list, 0j in Depends; provider/SSH credentials stay on the Witness per 03 item 7 (no change).
- B5 seam: Conductor → real fleet → Relay → FakeOF, accept-then-kill, stale leader, post-recovery send; stub reports stopped at once: **partial**. Cases added; power stub now tied to containers; restore-before-claim stays Phase 2's proof.
- B6 falsifiers; today `cmd_failover` restores after SSH fail and `oi-epoch` takes a second Box at same epoch: **reject**. Phase 2 fixes both (ADR-0063, Depends); outage-time falsifier is the entry condition.
- D1 `--etcd` usage error exits 2, `! --break` passes on it, house `--break` exits 0 when caught, no Phase 4 proof line: **accept**. `set -e`, per-mutant `--break <m>` house rule, Phase 4 manual line.
- D2 kills can pass with zero sends: **accept**. Accept-before-kill, same-Op-ID replay, fresh send from spare.
- D3 generation must come from the etcd revision (03:36); notes misquote ADR-0060: **accept**. Generation = `gen_base` + revision + 1, no counter/lock; note fixed to cite ticket 05.
- D4 broken-Fence "0 Placement writes" contradicts publish-`down`-first; post-epoch read failure untested: **accept**. Only `down` may be published; post-epoch read timeout case added. (Superseded 2026-11-26 by the plan review: Fence first, then `down`; a failed Fence publishes nothing.)
- D5 CAS cannot stop a stale leader still running between authorization and side effect; quorum drill checks only Placement: **accept**. `started` CAS before each side effect, repeat-safe steps, SIGSTOP Conductor case, quorum drill checks 0 Fence/epoch/restore and refuses manual move.
- D6 manual `resume`/`move` and `etcd-export` have no writer authority: **accept**. One writer key for all verbs; export needs key + no open op; observe never takes it.
- D7 unsend etc. bypass `dispatch()`; jobs queued behind a run slot: **accept**. `_proxy_message_write` checks the permit; queued-job case added, `dispatch()` stays the guard.
- D8 permit issuer lacks Story 15's epoch check: **accept**. `oi-lease` writes a first permit per new lease only after the `oi-cell-open` bucket read.
- D9 503 test passes while bubble shows Retry; expired Grants untested; run-tests may skip vitest: **accept**. No Retry, expired-Grant case, explicit `pnpm test:run`.
- D10 upgrade order drops Caddy/app, Control last, `min_cell_proto`; installer untested: **accept**. Plan order rewritten, N/N+1 case, installer cases in seam 2.
- D11 observe week, go-live, morning summary not in plan; lease-lost page fires before every good Failover: **partial**. Lease-lost page now only "alive but paused"; success = 0 pages (tested). Observe week/summary/go-live kept as reversible steps, flagged.
- D12 Depends misplaced; Phase 5 not optional; MP gates belong to Phase 4: **partial**. Depends rewritten (Phase 1, 0j, Phase 5 first, carve through etcd tested). Stories 22–23 kept (run rule needs MP labels) but now a per-Cell gate with a mixed-Box case.

### Plan review (six hats), 2026-11-26
- Black: "publish `down` → Fence" here vs Phase 3's Fence first — **accept**: Fence → `down`, as Phase 3 and Phase 2 story 25; a failed Fence writes no Placement; story 6, broken-Fence case, mutant `down-before-fence`; D4 annotated.
- White: Send permit missing from CONTEXT — **accept**: Send permit, `writes_paused`, Box lease added to CONTEXT.md Cell mode; ticket 05's etcd line struck as superseded by ADR-0060.
- Green doing-less: drop the Phase 5 dependency — **reject**: plan order puts Release 2 before Release 3 (rung 2), and `carve` must move onto the etcd writer key here. (superseded 2026-11-26: accepted; re-plan R4 puts carve on the later path)
- Red: every P6 ticket is Blocked-by Phase 0's `GATE build`, on top of this Phase's own entry conditions. (superseded 2026-11-26: no gate edge; entry conditions gate 108 only)
- Rests on D3: none. Release 3 automates only the power Fence; a manual `move` through the writer key carries whichever kind D3 picks.
