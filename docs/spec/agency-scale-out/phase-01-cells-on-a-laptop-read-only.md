# Phase 01 — Cells on a laptop, read-only

**Objective.** On one laptop, 3 data cells plus a Control cell behind Caddy give a chatter one login and one All inbox with live updates, every send is refused, and with `OI_CELL_MAP` unset everything behaves exactly as main. Plan: `.scratch/agency-scale-out/phased-plan.md` Phase 1; tickets 01, 03, 04, 06, 07, 08, 09, 12; ADRs 0058–0064.

## Problem Statement
If Phase 0 says one Box cannot carry the Agency, its Creators must sit in several Cells. Today a chatter would need one login per Relay and see one Relay's Creators: fleet's login refuses a username on two shards, Caddy sends everything to one Relay, and a request with no account falls back to the "active account" (m, tickets 01, 06). Nothing stops a Cell acting for a Creator it does not own, writing agency data it only copies, or sending unclaimed.

## Solution
Only with `OI_CELL_MAP` set: the Control cell signs people in and mints an Actor token; data cells verify it against a read-only Agency copy. Caddy routes each request by explicit account to its Cell. The app fans the All inbox out per Cell, merges it, and opens one live stream per Cell plus control; a dead Cell greys only its Creators. Cells answer Not owner outside `OI_ACCOUNTS`, refuse routes Cell scope lacks, and refuse every send until Phase 02. A local acceptance script proves it with FakeOF.

## User Stories
1. As an installer, I want the mode called "Cells" with `OI_CELL_` env names, so that it never collides with Ultra, fleet, shard or split inbox. [parallel-safe now]
2. As an installer, I want `OI_CELL_MAP` unset (or empty) to render the same Compose file and env, start the same way, run no new code and answer byte-identically to main, so that single-Box users see no change. [parallel-safe now]
3. As an installer, I want a Relay to refuse to start when `OI_CELL_MAP` is set but unreadable, lacks this `OI_CELL_ID`, disagrees on `OI_CELL_ROLE`, or demands a `min_cell_proto` above the Relay's, so that bad config serves nothing. This boot check is the only time a Cell reads Placement; ownership never comes from it. [parallel-safe now]
4. As the owner, I want to list Creators per Cell as `accounts = ["onlyfans:<id>"]` in `fleet.toml` and get `placement.json` with a Placement generation, so that one file says where each lives. [parallel-safe now]
5. As the owner, I want fleet.py to refuse an unknown platform, a Creator in two Cells, an unknown Box, and one bare id under two platforms, so that Placement is never ambiguous. [parallel-safe now]
6. As the owner, I want each Box's install step to refuse a lower generation, the same generation with other bytes, a bad schema or another Agency, and answer `PLACEMENT-OK gen sha256`, so that a stale map never wins. [parallel-safe now]
7. As the owner, I want a Cell to start pumps, and run DB-listed per-Creator jobs (automation_executor, notifications), only for Owned Creators that have session files, so that a Cell never acts for a Creator it does not own. [parallel-safe now]
8. As a chatter, I want a request for a Creator the Cell does not own (each bundle account too), or one whose Caddy-stamped expected Cell and epoch differ from the Cell's, answered `409 not_owner` and greyed without retry, and two account selectors that disagree answered `400 account_conflict`, so that a misroute never shows an empty inbox. [parallel-safe now]
9. As a chatter, I want one sign-in on the Control cell to work on every Cell, so that I never juggle logins. [parallel-safe now]
10. As the owner, I want only the Control cell to hold the Actor token's private key, so that a broken data cell cannot mint owner sessions. [parallel-safe now]
11. As a chatter, I want my token renewed every 5 min and on a 401, so that I stay signed in while grants stay fresh. [parallel-safe now]
12. As the owner, I want logout, impersonation (read-only flag) and share-token checks to honour `oi_actor`, so that cell mode opens no new hole. [parallel-safe now]
13. As the owner, I want each data cell to long-poll the Agency copy and apply whole changed sections in one transaction, so that grant changes land in ~1 s (i). [parallel-safe now]
14. As the owner, I want grant rows copied unfiltered and never password, TOTP or recovery fields, so that access never widens and secrets stay on control. [parallel-safe now]
15. As the owner, I want write-block triggers on copied tables (except `last_seen_at` and `last_used_at`), so that a Cell can never fork agency data. [parallel-safe now]
16. As the owner, I want a revoke to end that chatter's streams and requests on every connected Cell within ~1 s (i), including a stream registering during the apply, so that a fired chatter loses access fast. [parallel-safe now]
17. As the owner, I want a Cell past 15 min Grant age, or freshly booted with no confirmed copy, to refuse every human request (`503 grant_age_exceeded`, owner API keys too) and close streams while in-cell automations run, so that a long control outage keeps no revoked chatter in. [parallel-safe now]
18. As a chatter, I want chatting to carry on through a 5-min Control cell outage, so that a control restart does not stop work. [parallel-safe now]
19. As the owner, I want a Control cell restored from an older backup to publish a newer copy epoch Cells accept, and to create no Employee until every Cell in Placement has reported its highest Employee id and the counter is floored above all of them, so that no Employee id is reused. [parallel-safe now]
20. As the owner, I want Mirror Employees and their default role created on control with the grant, plus a one-time backfill, so that no Cell writes them on the send path. [parallel-safe now]
21. As the owner, I want adding a Creator to follow one order (listed in `fleet.toml` → Placement and `OI_ACCOUNTS` rendered and installed → Cell restarted → admission on that Cell takes a Creator reservation on control before any session or proxy write), refused if the Creator is not in this Cell's `OI_ACCOUNTS`, 409 if another Cell or platform holds it, refused while control is down, so that one id never lives twice and an admitted Creator is routable. [parallel-safe now]
22. As the owner, I want unlisted or `closed` routes in Cell scope refused, so that new routes stay closed until classified. [parallel-safe now]
23. As a developer, I want CI to fail when Cell scope is missing, stale, duplicated or invalid, so that it never drifts. [parallel-safe now]
24. As the owner, I want agency routes and agency jobs (clock-in missed, agency notifications) to run only on the Control cell, so that they never run 4 times. [parallel-safe now]
25. As a chatter, I want `X-Account-Id` on the ~75 body-only or bare-id app calls, and `relay.ts` refusing an unclassified call without one, so that Caddy routes every call. [parallel-safe now]
26. As a chatter, I want sales amendments sent as (account_id, tx_id) pairs split per Cell, so that a tx id shared by two Cells hits only the right row. [parallel-safe now]
27. As a chatter, I want a cancel or update of mass run id 1 to reach only the Cell I meant, so that equal local ids never cross. [parallel-safe now]
28. As a chatter with an old tab, I want a write carrying an older Data generation refused with 409 and my view refetched, so that a stale handle never hits a different row. [parallel-safe now]
29. As a chatter, I want fan and message ids above 2^53 to round-trip byte-exact, including scheduled-send rows, so that no fan is mixed up. [parallel-safe now]
30. As a chatter, I want the All inbox, roster and recent seed fetched per Cell (only Cells holding my granted Creators, 2026-11-26) and merged in a fixed order (missing time first, then account, fan; dedup `account:fan`), so that the list is stable with no duplicates. [parallel-safe now]
31. As a chatter, I want each Cell's first paint bounded at 3 s, so that a slow Cell only greys its own Creators, keeping their paging place. [parallel-safe now]
32. As a chatter, I want one live stream per Cell plus control, each with its own cursor, a resync refetching only that Cell's Creators, so that one restart does not reload everything. [parallel-safe now]
33. As a chatter, I want mass queues cleared only for the resynced Creators, so that other queues survive a Cell resync. [parallel-safe now]
34. As a chatter on HTTP/1.1, I want a clear "Live updates need HTTP/2" banner, so that I never get silent greying. [parallel-safe now]
35. As the owner, I want inbox caches, screen-bundle flights and placeholders keyed by actor, grant generation and Placement generation, and cell-mode server-rendered first load to inline only `/auth/me` and `/chatter/me` from control, so that a revoked chat never flashes back. [parallel-safe now]
36. As a chatter, I want the view lease taken on the Creator's own Cell, so that it keeps working across Cells. [parallel-safe now]
37. As the owner, I want Creators with no proxy refused in cell mode on REST and WebSocket paths, a client cached before its proxy was removed included, and non-OnlyFans Creators refused at admission, so that no Cell reaches a Platform from its Box's IP. [parallel-safe now]
38. As the owner, I want every send and publish (DMs, scheduled and mass sends, feed posts, stories) refused with `unclaimed_send` before its upstream write, so that Phase 01 cannot double-send. [parallel-safe now]
39. As the owner, I want every Cross-cell read other than the All inbox, roster and recent seed refused `403 cell_scope_closed` in Phase 01, and those three to carry `(platform, account_id, as_of, ok)` per row and `partial` naming the missing accounts, so that no total is silently short. [parallel-safe now]
40. As a developer, I want one acceptance script (`deploy/fleet/tests/cells-acceptance.sh`, the name Phase 02 extends) booting 3 Cells, control, Caddy over TLS, the app, FakeOF, MinIO and the power stub at nice 10, so that every proof reruns on a laptop. [parallel-safe now]

## Implementation Decisions
- **Owns.**
  - Relay: new cell-mode module (startup check, role, `OI_ACCOUNTS`, `min_cell_proto`, Data generation, route guard, Not owner); Cell scope (finishing Phase 0's draft); new Agency copy module (publisher, puller, apply, gate, cache clearing, Grant age); new Actor token module; Creator reservations; Send tripwire. Modified: `server` pump start, `automation_executor` and `notifications_api` job listing, `accounts.ensure_platform`, `proxies`, `auth`/`chatters` logout, share-token gate, `employees` mirrors, `events` SSE registration, `sales_amend`, scheduled-send rows, `fleet_api`, `of_sends`, `fansly_shim`, `of_ws` proxy check. Production write-block trigger installer and gate row (Phase 00 only ships a test-DB probe).
  - Fleet: `fleet.py` (shard `accounts`, top-level `agency`/`generation`, Placement render and checks, env render, Caddy cell block), `override.yml.tmpl`, `Caddyfile.tmpl`, a new Box-side Placement install script, a new local acceptance script.
  - App: `relay.ts`, the ~75 call sites, `useChatList`, `useAccounts`, `useRecentChatsLocal`, `chatsCache` comparator, `screenKey`, `layout.tsx`/`inlineBoot.server.ts` (cell-mode SSR), `events`/`eventBusReducer` (per-Cell buses), `useAccountStateEvents`, `useMassMessages`, site-auth, view lease, an HTTP/1.1 banner.
  - CI: a standard-library Cell scope check job beside comment-budget.
- **Interfaces.**
  - Env (all only read when `OI_CELL_MAP` is set): `OI_CELL_MAP` (path of the Box's `placement.json`), `OI_CELL_ID`, `OI_CELL_ROLE` (`control|data`), `OI_ACCOUNTS` (comma list of `platform:id`), `OI_CELL_MAX_GRANT_AGE_S` (default 900), `OI_CELL_CONTROL_URL`, `OI_CELL_ACTOR_PUBKEY`; control alone gets the Ed25519 private key; each data cell its own Agency copy credential. fleet.py emits the `OI_CELL_*` block, each with `:?` and only the vars that role needs, only into a cell-mode shard's override; with no `agency` in `fleet.toml` the rendered override is byte-identical to main (a bare `${OI_CELL_MAP:?}` fails `docker compose config` when unset, m per review). The Control cell's template renders `OI_ACCOUNTS` as `${OI_ACCOUNTS?}` (empty allowed, unset refused; `:?` rejects empty, m codex `docker compose config` probe); `--read-only` runs `docker compose config` on the rendered Control file and boots it with `OI_ACCOUNTS` empty. Phase 3's Entry cut uses this template. Key rotation = render a new key pair and restart every Cell; open tabs re-sign in on 401.
  - Relay errors: `400 account_required`, `400 account_conflict`, `403 cell_scope_closed`, `403 agency_write_on_data_cell`, `409 not_owner`, `409 stale_cell_gen`, `409` reservation (`lives_in_cell`, `PlatformCollision`), `503 grant_age_exceeded`, `unclaimed_send`, `no_proxy_refused`.
  - The route guard is one app-level FastAPI dependency on the matched route (ticket 09), installed only in cell mode.
  - The Send tripwire is a ContextVar check in OF `post_message`, `schedule_message`, `schedule_mass_message`, `send_mass_message`, `publish_schedule` and Fansly `send_message` (ticket 05). Phase 01 also puts the refuse-all check in OF `create_post` and `create_story` (feed posts and stories, `of_sends.py:540,798`, m), which ticket 05 leaves untripped. In Phase 01 nothing sets the claim, so all refuse.
    ASSUMPTION: the publish refusal is Phase 01-only; Phase 02's in-place replacement drops it, as its spec leaves posts untripped (rung 5, "read-only" in the plan). Overturned if Phase 02 puts publishing behind `dispatch()`.
  - `CELL_PROTO = 1` in the Relay.
- **Schema.** Created by the cell-mode installer only, never by main's migrations:
  - Control: `creator_reservations(account_id TEXT PRIMARY KEY, platform TEXT NOT NULL, cell TEXT NOT NULL, state TEXT CHECK (state IN ('pending','active')), expires_at)`; `agency_copy_version(epoch, version, grant_gen)` bumped by AFTER triggers per copied table in the same transaction; `grant_gen` only by triggers on grant tables, so it is one control-issued number every Cell and token agrees on.
  - Data cells: `agency_copy_gate(open INTEGER)` row and the production BEFORE triggers, installed by this phase (ticket 07 item 6; Phase 00's 0d probe only names the tables and agency writers); `cell_meta(data_gen INTEGER NOT NULL DEFAULT 1, copy_epoch, copy_version, section_sha TEXT, applied_at, confirmed_at, grant_gen)`.
- **Contracts.**
  - Placement v1: `{schema:1, agency, generation, written_at, by, min_cell_proto, cells:{sNN:{box, epoch, relay, role, state}}, accounts:{"onlyfans:<id>":"sNN"}}`. Formats only gain fields.
  - Caddy order: control allowlist → account from `X-Account-Id`, `?account_id=`, `?account=` or path → `X-Cell-Id` / `?cell=` → 400 `account_required`. Caddy stamps `X-Cell-Expect: <cell>.<epoch>` from Placement; the Relay answers `409 not_owner` on a mismatch. Selectors that disagree (header vs query vs path vs body account) → `400 account_conflict` in the route guard.
  - `oi_actor`: HttpOnly same-origin cookie, payload `{v, agency, kind, id, eff_id, ro, iat, exp≤15 min, ggen}` plus Ed25519 signature.
  - Agency copy: `GET /fleet/agency-copy?since=<epoch>.<version>`, held ≤25 s, answer `{format, epoch, version, grant_gen, sections:{name:{sha256, rows}}}`, field allowlist; a Cell stores control's `grant_gen`, never counts its own; the cell reports dead push ids on its next poll. Unknown fields ignored.
  - Per-model responses carry `X-Cell-Gen`; the app echoes it on writes. SSE frames carry `cell` and `data_gen` in the payload; resync carries `{"accounts":[…]}`.
  - Control's granted-accounts answer lists each account's `cell` and the `placement_gen`.
- **Agency copy apply** follows ticket 07 items 4–5: one BEGIN IMMEDIATE, delete-missing then UPSERT, tombstones, stubs, old version kept on failure, newer epoch beats version.
- **Cache clearing** after a changed grant section follows ticket 07 item 7, plus a grant generation re-checked at SSE registration.
- **Grant age** renews only when control confirms the applied version; a restart counts from the saved `confirmed_at`; a Cell with no confirmed copy counts as past the max. Past the max the Cell refuses Actor tokens and owner API keys (`503 grant_age_exceeded`) and ends open streams.
- **Employee floor after restore**: each Cell reports its highest copied Employee id on every poll; restored control creates no Employee until every Cell in Placement has reported once, then floors the counter.
  ASSUMPTION: wait-for-all over flooring from responders (rung 4: a missing Cell may hold the highest id). Overturned if the owner prefers staff creation available with a Cell down.
- **Data generation is checked by the Cell, not by Caddy.**
  ASSUMPTION: the Relay enforces `X-Cell-Gen` against its own `cell_meta.data_gen` (rung 5: Caddy only matches static values, and the Cell knows its own number). Overturned if a write path reaches a Cell without passing the Front door. Falls: tickets 06, 10.
- **Live streams**: the app reads `nextHopProtocol`; anything but h2/h3 shows the banner and opens no per-Cell streams; fetches still load. Each Cell's bus keeps today's heartbeat staleness rule (`events.ts`, 45 s, rung 3); a stalled stream greys only that Cell's Creators.
- **Upstream side effects that are not sends** (mark-read on thread open, like, pin, block) behave as today; Phase 01 counts only send and publish calls.

## Testing Decisions
- **Main seam: the local acceptance script** (ticket 12), nice 10: real Relays on temp dirs, Caddy with local TLS and HTTP/2, the real app, FakeOF via `OF_API_ORIGIN` (not slop), MinIO, power stub; signs in through a browser; saves settled screenshots and API answers. Seed: one restricted chatter whose only restriction points to another Cell, the same Fan on Creators in different Cells, adjacent ids above 2^53, a non-owned Creator's rows and a DB-listed job on the wrong Cell, automations with posts and stories enabled. TLS ends at Caddy on the laptop; the Traefik-in-front path is proven at Phase 04 preflight. Prior art: `deploy/fleet/tests/failover-in-containers.sh`, `scripts/verify-app/drive.py`.
- `--read-only`: real login; cold reload with only `oi_actor` set; All inbox spans 3 Cells with the restricted chatter seeing only granted rows; a FakeOF DM reaches the chatter's stream ≤1 s; 19 streams over HTTP/2 (4 Cell streams plus 15 stub SSE endpoints from 0h behind the same Caddy) while inbox loads stay in budget; two Cells' events interleave through one Cell's reconnect, only its Creators refetched; forced HTTP/1.1 shows the banner; one Cell blackholed greys only its Creators within 3 s; a Creator added in the story-21 order is reachable through Caddy; a composer send returns `unclaimed_send` and, over the whole run, FakeOF records 0 send or publish calls and the scheduled/mass rows are unchanged; the agency-copy response holds no password, TOTP or recovery field.
- `--drills`: control down 5 min (chatting goes on) and 16 min, checked with an owner API key that does not expire (exact `503 grant_age_exceeded`, streams closed, one in-cell automation tick still runs); revoke on a connected Cell (refused ≤1 s, a stream registering mid-apply rejected) and while a Cell is partitioned from control (refused there ≤15 min); one renewed token accepted on a Cell that caught up after missing two versions and on one that never missed; aged and old-grant-generation tokens refused, then renewed; expiry with a current copy; both logout paths, read-only impersonation and the share-token gate with `oi_actor`; a failed apply during a fan-write burst keeps the old version; first request against a fresh Mirror Employee needs no Cell write; old control restored with the Cell holding the highest Employee id down (no Employee created until it reports, then counter floored, newer epoch applied).
- `--env-unset`: with `OI_CELL_MAP` unset and with it empty, the rendered override/Compose file and env, the startup log, and the same request set, bytes diffed (timestamps masked) against a worktree of the merge-base.
- **Two-Relay service tests** (plain scripts, ticket 06 item 7 a–f, Nova ids `900539700124344320`/`…321`), plus Cell scope live-vs-JSON, default deny, conflicting selectors, an owned object outside the actor's grants, wrong expected Cell/epoch, a non-owned DB-listed job skipped, production triggers (and missing gate row) blocking writes, Not owner on bundles, no-proxy refusal on REST, WebSocket and a cached client, tripwire in all 8 methods. Prior art: `test_audience_coverage.py`, `test_fleet_api.py`.
- **Fleet pytest**: Placement render and refusals, Box install refusals, env render. Prior art: `deploy/fleet/tests/test_fleet.py`.
- **App vitest**: merge comparator (missing time, ties, dedup), `relay.ts` refusal and header echo, scope-keyed cache and screen-bundle keys, scoped resync, per-Cell bus cursors. Prior art: `app/lib/relay.test.ts`.

## Acceptance
```sh
set -e
cd "$(git rev-parse --show-toplevel)"
venv/bin/python -m pytest -q deploy/fleet/tests/test_fleet.py deploy/fleet/tests/test_placement.py
venv/bin/python scripts/run_tests_parallel.py service/tests cell_ -j 8
python3 scripts/cell_scope_check.py
(cd app && pnpm exec vitest run cell relay)
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --read-only
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --drills
nice -n 10 deploy/fleet/tests/cells-acceptance.sh --env-unset
scripts/run-tests.sh
# manual: owner looks at the settled screenshots in the run's evidence folder
```

## Depends on
- Phase 00: the gate says build (superseded 2026-11-26: the gate blocks nothing); 0a stall fix and split-inbox filter before the SQL limit; 0d agency-write list (probe only; the production installer is built here); 0f draft `service/cell_scope.json`; 0h stream spike passed (125 streams since 2026-11-26) and its stub endpoints (a fail brings in gateway fan-in, Phase 7).
- MP 1a–1d and W32 fixes, merged (m).
- Phase 02 runs alongside; the full acceptance run with sends needs both.

## Out of Scope
- `send_ops.dispatch()`, Send claims, anchors, `X-Op-Id`, kill matrix: Phase 02.
- Fence, `vm_id`, Owner epoch write check, Egress gate: Phase 02.
- WireGuard, front routes on 2 Boxes, probes off loopback, Placement push over SSH, lock file, Witness journal, pages: Phase 03; a laptop has one host.
- `cell_owned()` filter and Session-folder quarantine: Phase 03 Entry cut; laptop Cells are seeded fresh.
- Carve: Phase 05. etcd: Phase 06.
- Fansly and Fanvue Cells: wait for MP mixed-platform restore drill / MP Phase 2.
- Wizard copy change: waits for ticket 12's release boundary.
- Moving `last_seen` writes off Cells: ticket 07 keeps them as local columns.
- Cross-cell S4S: closed in Release 1 (ticket 09).
- Every Cross-cell read beyond the All inbox, roster and recent seed (analytics, CSV, sales totals, ~29 reads, ticket 08 fog), payroll finalization freshness gate, auto clock-out across Cells, public slugs and share links across Cells: whichever Phase the signed Feature table assigns; refused here by default closed.
- Per-row generation columns, signed Placement, SharedWorker, gateway service: rejected (tickets 03, 06, 08) unless their trigger fires.

## Further Notes
ASSUMPTION: past the max Grant age a Cell refuses every human request, owner API keys included, and only in-cell automations run (rung 2, ticket 08 refines 07). Overturned if the owner wants owners served through a long control outage.
ASSUMPTION: `OI_CELL_ROLE` env names control vs data, matched against Placement at start (rung 5, same reason as ADR 0059).
ASSUMPTION: the boot-time Placement check (ticket 01 items 3 and the plan's `min_cell_proto`) does not break ADR 0059's "Cells never read it", whose rejected option is reading Placement for ownership (rung 5). Overturned if the ADR means no read at all; then fleet.py renders `OI_CELL_MIN_PROTO` and the role into env and the Relay checks env only. Overturned if fleet.py derives role another way.
ASSUMPTION: cell-mode tables are created at cell-mode boot, not in main's migrations (rung 4). Overturned if the house migration runner cannot skip them cleanly.
ASSUMPTION: "read-only" means no upstream sends or publishes; local writes (notes, sale amendments, agency writes on control) and non-send upstream effects (mark-read, like, pin) work (rung 5). Overturned if the owner wants all model writes refused in Phase 01.
ASSUMPTION: all Cells of an Agency share control's VAPID key pair as a fleet secret, so pushes from any Cell reach existing subscriptions (rung 5, i). Overturned if push is marked off in the Feature table.
ASSUMPTION: the acceptance script imports FakeOF from `slop/lib/of_wire.py` standalone (rung 3). Overturned if that module cannot run outside the slop harness; then a copy moves to the fleet tests.
ASSUMPTION: the acceptance script is `deploy/fleet/tests/cells-acceptance.sh` (rung 3: the earlier draft at 05c64325d and Phase 02 use it; the plan names none). Overturned by: an owner or house name; rename in Phases 1–3 together.
ASSUMPTION: the Control cell renders `${OI_ACCOUNTS?}` (rung 5; `:?` rejects empty). Overturned by: a role-aware template that omits `OI_ACCOUNTS` on control; falls Phase 3's Entry cut step 4.
Ed25519 uses `cryptography`, already pinned (m, `requirements.txt:65`, used by `push_send`): no new dependency (rung 1).

### Re-plan 2026-11-26
Binding: `.scratch/agency-scale-out/replan-2026-11-26.md` (R1, R4, R6). Plan top: `phased-plan.md` "Re-plan 2026-11-26".
- **Path:** all of this Phase is demo: tickets 27–37, stories 1–40. No ticket waits on 25 (GATE).
- **Fan-out (R6, folded into 35):** the app asks only the Cells that hold the actor's granted Creators, read from Control's granted-accounts answer (each account's `cell`). An unrestricted actor (owner, no restriction row) asks every Cell (i). Keeps a chatter at ~5 Cells, not 100, at scale.
- **Agency copy (29):** whole sections stay for the demo. Grant changes as deltas or finer sections at ~100 Cells are a scale change (ADR-0064 amended, `phase-07-hold-1000.md`).
- **Acceptance:** unchanged; the laptop stays 3 data Cells + Control. The live demo runs 2 data Cells (Phase 3/4).

## Review
codex (gpt, effort high), 2026-11-26, partly blind (read P0/P2 specs and `.scratch` through git objects at `05c64325d`). Blind call then draft call, both exit 0.

Blind call:
- B1 keep one Relay after 0a fixes — **reject**: that is Phase 00's gate, already in Depends on.
- B2 inbox bundle per Cell or server gateway — **reject**: already the shape (one `/admin/screens/inbox?accounts=` per Cell, ticket 08 item 3); gateway rejected unless 0h fails.
- B3 online introspection or shared secret — **reject**: ADRs 0058/0064 decide signed tokens plus copy.
- B4 read-only boundary (mark-read GET, zero send-state changes) — **partial**: non-send upstream effects stay as today (new decision + ASSUMPTION); acceptance now asserts 0 send/publish calls and unchanged scheduled/mass rows.
- B5 routing gaps (conflicting selectors, SSR boot fetch, bundle members) — **accept**: `400 account_conflict`, cell-mode SSR inlines only control's `/auth/me` and `/chatter/me`, bundle Not owner kept.
- B6 lifecycle gaps (key rotation, cold boot, principals at max age) — **accept**: rotation = new key pair + restart; cold boot counts as past max; owner API keys refused with exact code.
- B7 partial results (silent stall, tie-breaker, per-Cell replay) — **partial**: comparator and 3 s already specced; added per-Cell heartbeat staleness and interleaved-reconnect proof.
- B8 provisioning (reservation order, no-proxy on WS and cached client) — **accept**: story 21 order, story 37 REST+WS+cached.
- B9 seam needs a TLS Caddy and a richer seed — **accept**: seed list added to the main seam.
- B10 capacity falsifier — **reject**: Phase 00's job.
- B11 front-door falsifier incl. Traefik terminating TLS (`fleet.py:290-303`) — **partial**: laptop ends TLS at Caddy; Traefik path deferred to Phase 04 preflight, stated in Testing.
- B12 isolation falsifiers (unauthorized row, restored grant, sync control write, FakeOF mutation) — **accept**: all now in `--read-only`/`--drills`.

Draft call:
- D1 boot check reads Placement vs ADR 0059 "Cells never read it" — **partial**: ADR's rejected option is reading for ownership; check kept, ownership-from-Placement forbidden in story 3, ASSUMPTION names the env-only fallback.
- D2 `:?` on `OI_CELL_MAP` breaks unset Compose (measured `docker compose config` exit 1) — **accept**: block emitted only into cell-mode shards; env-unset diffs rendered Compose, env, startup, unset and empty.
- D3 Phase 00 ships a probe, not the production trigger installer — **accept**: installer and gate row owned here; Depends on fixed.
- D4 grant generation can drift between Cells — **accept**: control-issued `grant_gen` in the copy answer; drill with one token on a caught-up and a never-missed Cell.
- D5 tripwire misses feed posts and stories — **partial**: refuse-all added to `create_post`/`create_story` (ASSUMPTION: Phase 02 drops it); co-tag lookup in `prepare_message` rejected as a read, not a send.
- D6 outage drills pass on token expiry alone — **accept**: owner API key, exact 503, automation tick, connected-Cell revoke, logout/impersonation/share-token drills.
- D7 copy tests miss cross-Cell restriction, secret fields, failed apply, cold mirror, Cell-down floor — **accept**: all added; floor waits for every Cell (ASSUMPTION).
- D8 guard misses selectors, actor/object, expected Cell/epoch, DB-listed jobs — **accept**: `X-Cell-Expect`, `account_conflict`, executor and notifications job listing gated, service tests added.
- D9 SSR, bundle cache, single event bus; 19 streams impossible with 4 Cells — **accept**: Owns lists `layout.tsx`, `inlineBoot`, `screenKey`, buses; 19 = 4 Cell streams + 15 0h stubs.
- D10 Feature table cannot authorize new analytics — **accept**: Phase 01 fan-in is inbox, roster, recent seed only; rest `cell_scope_closed`; old ASSUMPTION removed; dropped 0g from Depends on.
- D11 reservation does not make a Creator routable — **accept**: Placement-first order in story 21, reachable-through-Caddy check.
- D12 script name differs from Phase 02 — **accept**: one name, `cells-acceptance.sh` (the earlier draft's name and Phase 02's; corrected 2026-11-26, see Plan review).
- D13 `cell_` runner matches nothing at `05c64325d` — **reject**: nothing is built yet; the pattern is the Phase's own new tests.

### Plan review (six hats), 2026-11-26
- Black: script named `cell-` here, `cells-` in Phase 2 — **accept**: one name, `cells-acceptance.sh` (the earlier draft at 05c64325d used it; the plan names none).
- Black: empty `OI_ACCOUNTS` template fixed in Phase 3 while this Phase owns the template — **accept**: Control template `${OI_ACCOUNTS?}` and its `docker compose config` check now live here.
- Red / Black (d) Phase 1 reads like several phases — **partial**: stays one spec; ticketed as several tickets (Placement + env render, relay cell mode + route guard, Agency copy + Actor token, app fan-out), each Blocked-by Phase 0's `GATE build` (superseded 2026-11-26: no gate edge); no new spec files.
- Rests on D3: none.
