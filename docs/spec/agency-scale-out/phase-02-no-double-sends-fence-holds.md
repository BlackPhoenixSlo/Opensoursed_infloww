# Phase 02 — No double sends, the fence holds

**Objective.** In Cell mode every Send op reaches the Platform at most once, and no promotion (Failover, Planned move, restore, clone activation) runs without a confirmed Fence, so a stale Box can never send.

## Problem Statement
Owner view: once Cells move and get restored, a message can go out twice — from an old Box not really off, or after a restore forgot it was sent. Today nothing stops either (m): sends share no boundary (ticket 05), fleet.py stops the VM it finds by IP, two writes of one Owner epoch both pass (ticket 04), a fresh Cell boots with the network open, and Retry can resend what OnlyFans already took. A double PPV or two sessions on one account is worse than downtime (owner: fail closed).

## Solution
Owner view: in Cell mode each send is written in the Cell's own database before it goes out, and goes out once. An unknown result lands on Unconfirmed sends for a person to mark; Retry is gone and automated sends to that Fan wait. A send kind with no stable anchor is refused. Taking over a Cell needs proof the old Box is off (two "stopped" reads of the exact VM, re-read after the epoch write); without it nothing is restored and the owner is told. A Cell boots network-shut until the bucket says it owns. `OI_CELL_MAP` unset: nothing changes.

## User Stories
1. As a chatter, I want a send I clicked once to reach the Fan at most once even if the Cell dies mid-send, and an unknown outcome shown to me, so that Fans never get doubles. [parallel-safe now]
2. As a chatter, I want a resend of the same action (double click, flaky network) to return the first result, not send again, so that retries are safe. [parallel-safe now]
3. As a chatter, I want an unknown outcome shown as Unconfirmed, never auto-retried by the app, so that I decide. [parallel-safe now]
4. As an owner, I want every Cell-mode send (composer, mass, schedule, publish-now, vault, every automation) to pass one boundary — Not owner → capability gate → Send claim → upstream — so that no sender gets around it. [parallel-safe now]
5. As an owner, I want any send without a Send claim refused with `unclaimed_send` before any network call, so that coverage is proven by the code, not a caller list. [parallel-safe now]
6. As an owner, I want a send refused (`claim_failed`) when its claim cannot be written, with no fallback store, so that two stores can never both say yes. [parallel-safe now]
7. As an owner, I want one claim to allow one wire attempt, counted at the transport (a second only after a full 4xx or a proxy refusal before any tunnel), so that the proxy retry loop, co-tag drops, text-only fallback and 429 pacing cannot double-send. [parallel-safe now]
8. As an owner, I want claims still open at boot marked Unconfirmed, so that a crash mid-send is never silently resent. [parallel-safe now]
9. As an owner, I want a replay of a sent op to skip local side effects (mass run open, unsend enqueue), so that a replay changes nothing. [parallel-safe now]
10. As an owner, I want the same Op ID with a different body refused (`op_conflict`), so that two different messages never share one op. [parallel-safe now]
11. As an owner, I want each automated kind to build its Op ID from a Send anchor saved before the send, so that a rerun after a crash maps to the same op. [parallel-safe now]
12. As an owner, I want the 6 kinds without a stable anchor (autoreply, welcome_chatter, generic followup, vault items, online nudge, purchase_followup) refused in Cell mode until each has one, so that unsafe kinds stay off. [parallel-safe now]
13. As an owner, I want Unconfirmed sends to list every uncertain Send op with a link to the chat or queue, and record who marked it and how, so that I can clean up. [parallel-safe now]
14. As an owner, I want Retry off in Cell mode (409 `retry_off_cell_mode`, button hidden; Dismiss stays), so that a resend is always a new manual message. [parallel-safe now]
15. As an owner, I want automated sends to one Fan held while that Fan has an Unconfirmed send, other Fans unaffected. [parallel-safe now]
16. As an owner, I want a Cell restored from a copy taken before a claim to hold automated sends with a Cell hold (Creator scope, why `restore`; saved in the Cell DB, kept across restarts) and park overdue jobs as "may have sent (restore)" until a person releases, audited, so that a forgotten send is not repeated. [parallel-safe now]
17. As an owner, I want a Fansly Cell's automations after a restore to stay held until a person releases them, because Fansly has no proven peek. [waits for MP mixed-platform restore drill merged]
18. As an owner, I want fleet.py to stop the VM id stored in Placement after checking provider account, VM id and IP agree, never look it up by IP. [parallel-safe now]
19. As an owner, I want "stopped" to count only on a `success` stop action plus two fresh `stopped` reads ≥5 s apart with matching IP within 180 s, everything else unconfirmed. [parallel-safe now]
20. As an owner, I want the Owner epoch write to refuse when the bucket holds an epoch ≥ N from another Box, and every promotion (Failover, move, restore, clone activation) run one at a time under one lock on the Witness box. [parallel-safe now]
21. As an owner, I want the VM read again after the epoch write and required `stopped`, so that a Box that restarted in between is caught. [parallel-safe now]
22. As an owner, I want a Fence to be a typed, expiring result matched to Placement, so that a stale or wrong proof is refused. [parallel-safe now]
23. As an operator, I want the manual path to need the typed `stopped <vm_id>`, never a bare Enter. [parallel-safe now]
24. As an owner, I want Failover, Planned move, restore and clone activation to call the same `fleet.fence()`, so that no path promotes around it; a Planned move gets a Cell fence (reboot-proof egress block on that Cell's bridge, read back over SSH) so sibling Cells on the source Box stay live. [parallel-safe now]
25. As an owner, I want an unconfirmed Fence before the epoch write to make no epoch, owner-changing Placement, DNS or restore write (P3's `down` status publish is not an owner change); and a failed read after the epoch write to keep that epoch (it marks the source stale) but make no restore, Placement or egress-open write. Both keep the target closed and print the evidence and resume command for paging, so that unknown means down, not doubled. [parallel-safe now]
26. As an owner, I want a re-run after a crash at any fence step to continue safely from the step that failed. [parallel-safe now]
27. As an owner, I want the proxy fence built but reported "unavailable" until a provider passes the open-tunnel drill and restored copies get new credentials, so that a half-fence never counts. [parallel-safe now; turning it on needs the human item]
28. As an owner, I want a Cell to boot behind an Egress gate that docker Requires, lifted only when the bucket's Owner epoch equals the Cell's and names this Box, so that a zombie Box cannot reach a Platform. [parallel-safe now]
29. As an owner, I want ownership written to the bucket before a Cell's first boot, so that epoch 0 never counts as owner. [parallel-safe now]
30. As an owner, I want a running Cell that reads itself stale to re-block egress before stopping containers, and an unreadable bucket to leave a running Cell open. [parallel-safe now]
31. As an owner, I want every safety check to have a mutant that turns its own drill red, and a drill with fencing disabled to fail. [parallel-safe now]
32. As an owner, I want, once P1 is in, the Acceptance run to show one send = 1 FakeOF call + 1 `sent` row in the owning Cell. [parallel-safe now; run needs P1]
33. As an owner on one Box, I want everything above inert with `OI_CELL_MAP` unset: same wire calls, same Retry, same boot gate, no `send_ops` table, Compose identical to main. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - Service: new `send_ops` module; `of_sends` (the 5 OF send methods), `fansly_shim.FanslyShimClient.send_message`, `of_client` proxy-refusal check, `_send_failure` fallback, the 7 HTTP/vault callers and 16–19 automation callers (ticket 05 list), anchor writers (`scheduled_send`/mass-job payloads, priority_mass run), `automation_executor` restore parking, `unconfirmed_sends_api`, `db.models` (`SendOp`), `cell_scope.json` rows for new routes.
  - App: `useSendMessage`, manual mass and native-schedule send hooks, `useUnconfirmedSends`, `UnconfirmedSends`.
  - Fleet: `fleet.py` (map `vm_id`, fence, takeover lock, promotion paths), `oi-epoch` (put, watch), new `oi-cell-open` + firewall unit template, `wizard.sh` confirm, `api_stubs`, `failover-in-containers.sh`, `test_failover.py`.
- **Interfaces.**
  - `send_ops.dispatch(account, op_id, kind, target, digest, send_fn)`: runs the four steps in order; returns the stored result on a sent replay; raises typed refusals `not_owner | capability | claim_failed | op_conflict | op_pending | op_uncertain | fan_held | cell_held | no_anchor` (`cell_held` carries the hold's `why`).
  - `cell_hold.active(account) -> Hold | None` reads the `cell_holds` rows that cover that Creator (its own or a Cell-scope row); `blocks=automations` refuses automated kinds in `dispatch()` and stops executor claims, jobs wait (not fail, skip or advance); `blocks=writes` (Phase 5) adds every mutating route through Phase 1's route guard. `oi-cell-hold set|clear <cell> --why move|entry_cut|carve --blocks automations|writes --op <op>` is the box tool fleet runs over SSH, also on a stopped Cell (one-shot container on its data dir); never an HTTP call. Restore holds are set at boot and released per Creator by a person (route below).
  - `send_ops.op_id(platform, account, kind, target, anchor, part)` = sha256 of `v1|…`; recipe per kind as ticket 05 item 3. IDs are strings end to end.
  - Send tripwire: a ContextVar set only inside `dispatch`; each client send method raises `unclaimed_send` without it. It carries through `to_thread`, `_proxy` and the vault hop; bare `run_in_executor`/`pool.submit` fail closed (m, ticket 05). It replaces P1's refuse-all tripwire in place. The ContextVar also carries the claim's attempt budget, spent in `OFClient._attempt` before each write leaves; `_proxy_retry` (5 tries on any ProxyError/ConnectionError today, m `of_client.py:69,649-674`) cannot spend a second without the attempt rule allowing it.
  - Publish route (`server.py` ~3141): the "Message now" branch dispatches through `send_ops`; "Post now" (feed) stays untripped like `_post_dropping_auto_cotag`.
  - Replay returns the stored response body (`result`), not only `upstream_id`.
  - `unconfirmed_sends_api`: list gains `send_ops` uncertain rows of every kind plus `retry_allowed`; new resolve route (`was_sent | not_sent`, audited); `/retry` → 409 `retry_off_cell_mode` before `settle_landed`/`retry_clear`; new route to release a restore Cell hold per Creator (`why=restore` rows only).
  - App: one `X-Op-Id` (UUID) per user action on composer, manual mass, native schedule, minted before any upload; kept across that action's own resubmits; each POST of one action (manual mass sends a main body then one per extra GIF, m `useMassSend.ts:64,69`) adds its part index; never auto-retry an unknown outcome; Retry hidden when `retry_allowed` is false. Cell mode is never sniffed in the app.
  - `fleet.fence(cell, why) -> FenceResult{kind: power|proxy|cell, vm_id|cell, evidence, expires}`; promotion code accepts only an unexpired result matching Placement. `why=move` gives `cell` (ticket 10 step 6: reboot-proof egress block on the source Cell's bridge + SSH read-back; siblings untouched); Failover/restore/clone give `power`, else `proxy`. Amended 2026-11-26 (R9): on one Box the Entry cut's clone activation and a slot relocation give `cell` (old relay or Cell container stopped + removed, restart none, two `docker inspect` reads); FenceResult and Owner epoch are keyed by Cell instance (Box + data dir), not Box. `hostinger_stop` takes a `vm_id`, polls the action, never returns silently on error.
  - `oi-epoch put N box`: refuses when the bucket holds epoch ≥ N from another box; same box + same N is idempotent (resume).
  - `oi-cell-open <cell>`: lifts the Egress gate only when bucket epoch == local epoch and box == this box; unreadable → stays closed.
- **Schema.** `send_ops` (Cell's own SQLite, created by `create_all`, additive):
  ```
  send_ops(account TEXT, op_id TEXT, kind, target TEXT, digest, epoch, data_gen,
           state CHECK IN (claimed,sent,refused,uncertain,resolved_sent,resolved_not_sent),
           upstream_id TEXT, result TEXT, attempts INT, created_at, updated_at, resolved_by, resolved_at,
           PRIMARY KEY (account, op_id))
  ```
  Plus cell-local `last_data_gen`, and `cell_holds(id, scope CHECK IN (creator,cell), account TEXT NULL, why CHECK IN (restore,move,entry_cut,carve), blocks CHECK IN (automations,writes), op, set_by, set_at, released_by, released_at)`, the one store for every Cell hold (Phases 2, 3, 5), on the same Cell-mode-only metadata. Placement/`fleet.toml` boxes gain `vm_id` and `provider_account`.
  The table lives on its own metadata, created only when `OI_CELL_MAP` is set (plan: unset env = no new code path; `Base.metadata.create_all` at `db/engine.py:243,255` would otherwise add it everywhere, m).
- **Contracts.** Header `X-Op-Id` (app → relay). Error bodies above. `FenceResult` JSON on the Witness box. Firewall unit is a systemd dependency docker **Requires** (IPv4+IPv6, per-Cell fixed bridge name). Formats only gain fields (N/N+1).
- **Write order.** Commit claim → wire call → mark sent/refused/uncertain. WAL+synchronous=NORMAL survives a kill, not power loss (i).
- **Attempt rule.** Second wire attempt only after a full OF 4xx answer or a proxy refusal before any tunnel; in Cell mode `proxy_refused` stops accepting any `ProxyError` (ticket 05, codex P0-3). Anything else → `uncertain`. Enforced where the request leaves (`_attempt`), so caller-level fallbacks and `_proxy_retry` share one budget.
- **Boot.** Claims older than boot → `uncertain` (rule of `send_marker_decide`, rung 3). If the Cell's Data generation is above `last_data_gen`, start a restore Cell hold, one `cell_holds` row per Creator so a restart keeps it: automated kinds refused `cell_held` whatever their due time, every pending/running one-shot job with run_at ≤ boot and every recurring occurrence due ≤ boot parked "may have sent (restore)" (today only running jobs park, m `automation_executor.py:661-670`); manual chatting continues (stale tabs get P1's `X-Cell-Gen` 409; a new tab's resend is a new manual message, as Retry). A person releases per Creator, audited; release un-holds future sends only, parked jobs stay parked. A Planned move keeps Data generation, so no hold.
  ASSUMPTION: the blanket restore hold is P2's stand-in for P3's per-thread peek and queue listing (ticket 05 item 6); overturned when P3 lands the peek, which narrows the hold to Fans with a mismatch.
- **Fence order** (ticket 04 item 1): optional SSH drain (never a fence) → pre-stop check → stop vm_id → confirm → epoch put → read VM again → restore → `oi-cell-open`. Planned move (ticket 10 steps 6–8): Cell egress block + read-back → epoch put → `oi-cell-open` on target. One promotion lock on the Witness box for every verb; one fence record line per step for resume. Resume past an expired FenceResult re-fences; it never reuses old proof.
- **Fence failure.** Unconfirmed before epoch put: no epoch, owner-changing Placement, DNS or restore write. Post-write read not `stopped`: epoch stays (source now reads itself stale and its gate shuts), no restore, no Placement owner change, no egress open. Both: target closed, evidence + resume command printed for paging.
  ASSUMPTION: P2 writes fence steps as its own append-only record; P3's Witness journal adopts it. Overturned by P3's journal format.
  ASSUMPTION: FenceResult expires 10 min after confirmation (rung 5, matches P3's "spare ready ≤10 min"); overturned by measured Hostinger restart behaviour.
- **Owner epoch at send.** Not owner = account in `OI_ACCOUNTS` and the epoch confirmed at boot by `oi-cell-open`; each claim records it.
- Feed posts/stories keep using `_post_dropping_auto_cotag` untripped (ticket 05: tripwire on methods, not the shared helper).

## Testing Decisions
Seams, highest first:
1. **Acceptance run** (P1's `cells-acceptance.sh`, P2 adds `--send` and `--send-kill`): real relays as subprocesses, FakeOF as a separate process journaling each attempt and accept before it answers (verdict read from FakeOF's journal, never a patched client method), SIGKILL, restart on the same DB and on a pre-claim copy with Data generation +1; then ticks, `/retry`, a composer resend with the same op, a Planned move. Pass: ≤1 accept per op, 0 duplicates, uncertain row visible, kill before wire = 0 accepts; one send = 1 FakeOF call + 1 `sent` row in the owning Cell; pre-claim copy: old tab gets the `X-Cell-Gen` 409, `cell_holds` restore rows present and parked jobs listed, hold survives one more restart; Unconfirmed sends resolved both ways via the real routes, `resolved_by`/`resolved_at` set, held Fan's tick refused and another Fan's tick sends, then the held Fan sends after resolve; prints claim-write p50/p99. `--env-unset` (P1) also diffs rendered Compose and systemd units against the merge-base and checks no `send_ops` table.
2. **`service/tests/test_send_ops_kill.py`** (house plain script, `_Killed` pattern): drives real callers (`run_once`, HTTP handlers) through the real `OFClient`/`FanslyShimClient` with only the HTTP session faked and counting (so `_proxy_retry`, co-tag and text-only fallbacks run); every send kind × 3 kill points (after claim, after accept before row update, after update), each case asserting its kill point was reached and its own outcome. Positive control per enabled kind: a clean run = 1 accept + 1 `sent` row. Kinds without anchor: 0 accepts and `no_anchor`. Replay: same response body as the first, and mass-run, unsend-enqueue and attribution rows unchanged. Each refusal (`not_owner`, `capability`, `claim_failed`, `op_conflict`, `fan_held`, `cell_held`) injected alone → 0 transport calls, and gate order checked. `--break <mutant>` exits 0 only when that mutant's checks go red: tripwire bypassed, claim after wire, second attempt on unknown error, transport retry outside the budget, Retry on in Cell mode. P0's 0e baseline is the same file on today's code.
3. **`deploy/fleet/tests/failover-in-containers.sh`** + `api_stubs` (Hostinger action states, per-credential proxy stub, send-counting OF stub): ticket 04 item 7 drills, plus: running Cell with bucket unreadable stays open; running Cell reading stale shuts egress before containers stop (order checked); `move`, `restore`, `failover` each refused with no FenceResult; Planned move's Cell fence leaves the sibling Cell sending; wizard refuses bare Enter and a wrong `stopped <vm_id>`. The OF stub tags each accept with the sending Box: pass = 0 accepts from the old Box once the target's egress opens, open tunnels included. `--break=<mutant>` for accept-any-VM-state, skip-post-write-read, skip-egress-gate, skip-proxy-check, fencing-disabled, per-verb no-fence; each must turn its own check red (precedent: current `--break`, applied via cp backup, restored on exit).
4. **`test_failover.py`** (pytest): FenceResult matching/expiry, epoch put refusal, map `vm_id` validation.
5. **vitest**: `useSendMessage` mints one `X-Op-Id` per action (before upload) and never auto-retries; `useMassSend` gives each POST of one action the same op and its own part; Unconfirmed sends hides Retry on `retry_allowed:false` and shows the chat/queue link.
Prior art: `test_send_once.py`, `test_unconfirmed_sends.py`, `test_send_marker_decide.py`, `test_platform_capability.py`, `failover-in-containers.sh --break`, `useSendMessage.test.tsx`.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
venv/bin/python scripts/run_tests_parallel.py service/tests send_ops -j 8
venv/bin/python scripts/run_tests_parallel.py service/tests unconfirmed -j 8
venv/bin/python scripts/run_tests_parallel.py service/tests send_once -j 8
for m in tripwire_bypass claim_after_wire retry_unknown transport_retry retry_on; do
  venv/bin/python service/tests/test_send_ops_kill.py --break "$m"
done
(cd app && pnpm exec vitest run hooks/useSendMessage.test.tsx components/compose/useMassSend components/automations)
uvx --python venv/bin/python pytest deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_failover.py
nice -n 10 deploy/fleet/tests/failover-in-containers.sh
for m in any_vm_state skip_post_write_read skip_egress_gate skip_proxy_check no_fence move_no_fence restore_no_fence; do
  nice -n 10 deploy/fleet/tests/failover-in-containers.sh --break="$m"
done
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --send --send-kill
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --env-unset
scripts/run-tests.sh
# manual: real Hostinger power-off 10/10 is P0i/P3 (needs a throwaway box), not this Phase
# manual: proxy fence stays "unavailable" until the owner confirms per-cell credentials + an open-tunnel drill passes
```

## Depends on
- **P0** — gate verdict "Build" (superseded 2026-11-26: the gate blocks nothing); 0e kill-matrix baseline harness; 0j alert fixes used to print/page fence failures.
- **P1** — `OI_ACCOUNTS`/Not owner, `X-Cell-Gen` and Data generation, Cell scope default-closed guard (new routes need rows), the refuse-all tripwire P2 replaces, no-proxy refusal and OnlyFans-with-proxy admission (story 37; the power/proxy fence assumes no Cell egresses from its Box IP), and `cells-acceptance.sh`. P2 code builds alongside P1; the full Acceptance run needs both.
- **MP 1b** (merged, m) — capability gate sits before the claim.
- **P0i** — gates turning the proxy fence on only (provider check); P2 builds it reported "unavailable".

## Out of Scope
- Per-thread post-restore peek, `reconcile_since`, OF native-queue listing, drain on Planned move — P3 (needs ticket 10's manifest).
- Witness journal for moves, Placement lock/generation publishing, paging delivery — P3 (tickets 03, 10).
- Real power-off drill and proxy-provider revoke check — P0i (throwaway box).
- Clone activation callers (Entry cut, Carve) — P3/P5 call P2's fence.
- Op IDs for feed posts and stories (`auto_posts`, `s4s_post`) — ticket 05 fog.
- Send claims in single-Box mode; folding old funnel/followup markers into `send_ops` — ticket 05 fog.
- Queue edit (reschedule, not a new send); Fansly CLI (outside the relay) — ticket 05 adversary.
- Browserbase logins on provider proxies — ticket 04 fog.
- Any etcd role in sends — ADR-0060: etcd never holds claims; P6 only adds a Send permit.

## Further Notes
ASSUMPTION: a full 4xx from OF means not accepted (ticket 05). Overturned by a 4xx that still delivered; falls the attempt rule.
ASSUMPTION: one local SQLite claim write per send is fast enough. Overturned by claim p99 > 100 ms under load; falls Cell budget (ticket 02).
ASSUMPTION: 180 s confirm window, 5 s read gap (ticket 04, rung 5). Overturned by measured Hostinger stop times; falls P3's recovery time.
ASSUMPTION (evidence blocked): proxy providers offer per-Cell credentials or a revoke API (ticket 04). Overturned by provider docs or the owner's panel; falls the proxy fence only.
ASSUMPTION: "6 gap kinds" per the plan and ticket 05's gap list; ticket 05's "8" also counts two kinds P2 builds as ordinary anchors (inferred). Overturned by a seventh kind found unanchored by the kill matrix; it is then refused and added to the Feature table.
ASSUMPTION: mutants for the kill test run in-process via the test's own `--break` flag (no hooks in `service/`); fence mutants patch a cp-backed copy restored on exit (rung 3, current `--break`). Overturned if a mutant cannot be expressed without touching service code.

ASSUMPTION: restore, move and carve pauses are one Cell hold in one DB table, differing only in scope, `blocks` and who releases them (rung 5; Phase 5's own ASSUMPTION reuses a Phase 2/3 store if one ships). Overturned by: a hold that must survive losing the DB (a file outside it), or a relay that cannot read the row per call cheaply; falls stories 16, Phase 3's move pause, Phase 5 story 6.

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1, R2, R4). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Paths:** demo = 38–42, 44–48 (stories 1–16, 18–33). later = 43 (story 17, Fansly). No ticket waits on 25 (GATE).
- **D3 decided B** (ADR-0063 Accepted): a Planned move with a reachable source gets the `cell` fence. 47 is unparked and on the demo path; story 24 and everything under "Rests on D3" are in.
  ASSUMPTION: the owner wanted B (R2). Overturned by: the owner picking power-stop; then 47 parks again and story 24's sibling part flips to siblings greyed.
- **Why it matters for the demo:** the relocation of Cell 2 to a new slot on box A must keep Control and Cell 1 sending (R9: one Box).

## Review
codex (reasoning high), 2026-11-26 — partly blind: reviewer read `.scratch` tickets through git objects. B = blind call, D = draft call.
- B1 plan says "exactly one", kill-before-wire gives 0 — **accept**: story 1 now "at most once + unknown shown"; objective already at-most-once.
- B2 alternative: fence first, hold restored sends, today's markers as baseline — **partial**: P2 already holds after a lossy restore and P0 0e baselines today's markers; claims-off-on-restore rejected, plan Phase 2 builds claims (rung 2).
- B3 alternative: independent remote claim store — **reject**: ADR-0060 chose Cell SQLite, no remote store, no fallback.
- B4 Planned move needs a Cell-scoped fence, not power — **accept**: FenceResult gains `kind: cell` for `move` (ticket 10 step 6); story 24, Interfaces, Fence order rewritten.
- B5 restore rule not executable (absent claim, peek errors, native queue, after 24 h, fresh browser; only running jobs park today) — **partial**: blanket hold refuses every automated send whatever its due time, so absent claims are covered; pending + recurring parking stated (m `automation_executor.py:661-670`); new-tab resend = new manual message; peek and native queue stay P3 (plan).
- B6 identity through uploads, replay side effects, vault carrier, publish route — **accept**: op minted before upload; publish "Message now" dispatched, "Post now" untripped; replay asserts body + side-effect rows.
- B7 attempt budget must live on the wire — **accept**: same as D1.
- B8 ownership as (epoch, box), serialize every promotion — **partial**: epoch refusal already story 20 + ticket 04 drills; lock widened to every promotion verb.
- B9 assert at a separate FakeOF journal, not the slop client patch — **accept**: seam 1 rewritten.
- B10 positive control per kind; p99 evidence — **accept**: positive controls in seam 2; Acceptance run prints claim p50/p99. 4xx-delivered stays an ASSUMPTION.
- B11 fence falsifier must be receiver-side incl. open tunnels — **accept**: Box-tagged OF stub, 0 old-Box accepts after target opens.
- D1 `_proxy_retry` retries any ProxyError up to 5× under one claim (m by reviewer; `of_client.py:69,649-674` read) — **accept**: budget spent in `_attempt`; kill test runs real clients with only the HTTP session faked; `transport_retry` mutant.
- D2 Planned move power-off kills sibling Cells — **accept**: as B4, plus sibling-stays-sending drill.
- D3 "no epoch write" conflicts with post-write VM read and P3's `down` publish — **accept**: Fence failure split pre/post epoch put; `down` status publish is not an owner change; resume never reuses expired proof.
- D4 Creator-wide release can reopen the duplicate window — **partial**: hold saved in DB across restarts, release audited and un-holds future sends only, parked jobs stay parked; release route kept in P2 (else a restored Cell has no way out before P3; mirrors ADR-0060's person-release rule).
- D5 kill matrix passes with dropped sends — **accept**: per-kind positive control, kill point reached, per-case outcome, pre-claim 409 + hold asserted.
- D6 replay/refusal/gate order/mass parts unasserted — **accept**: replay body + rows, each refusal → 0 transport calls, gate order, `useMassSend` part keys (m `useMassSend.ts:64,69`).
- D7 Unconfirmed UI flow untested — **accept**: both resolutions, audit fields, held vs other Fan ticks in the Acceptance run.
- D8 fence drill gaps (runtime outage, re-block before stop, per-verb, wizard) — **accept**: drills + `move_no_fence`/`restore_no_fence` mutants added.
- D9 script is `cells-acceptance.sh` (m P1 spec :99-101); Compose not compared — **accept**: renamed; `--env-unset` diffs Compose + units, no `send_ops` table.
- D10 `create_all` adds the table with env unset; etcd handoff contradicts ADR-0060 — **accept**: table on own metadata, Cell mode only (m `db/engine.py:243,255`); etcd line replaced.
- D11 Depends on gaps — **partial**: P1 no-proxy refusal/admission and P0i (proxy fence turn-on) added; 0j stays P0 and paging delivery P3 (already so); story 17 label kept, run rule ties Fansly cells to the MP restore drill (rung 2).

### Plan review (six hats), 2026-11-26
- Black (d) three holds drift (`restore_hold` DB here, move pause in Phase 3, `cell_hold` file in Phase 5) — **partial**: one term, Cell hold, one store (`cell_holds` in the Cell DB, owned here), one refusal `cell_held`; they keep different kinds (Creator vs Cell scope, `automations` vs `writes`, person vs fleet release), so one record with three reasons, not one behaviour. DB over file: restore already chose it, and the hold must copy with the DB into a moved or carved Cell.
- Black: script name — already `cells-acceptance.sh` here; Phase 1 now matches.
- Green (a) pick B by ticket 10 (rung 2) — **reject** the rung: ticket 10 and ADR-0063 were written by this run; D3 stays needs-human, default `cell` kind kept, ADR-0063 notes the pending call. (superseded 2026-11-26: D3 decided B, see Further Notes)
- Red: every P2 ticket is Blocked-by Phase 0's `GATE build`. (superseded 2026-11-26: no gate edge)
- Rests on D3 (unparked 2026-11-26, D3 = B): story 24's "Planned move gets a Cell fence … sibling Cells stay live" part, Interfaces `why=move` → `cell`, the Fence order's Planned move line, the sibling-stays-sending drill (D2) and the `move_no_fence` mutant's Cell-fence check.
