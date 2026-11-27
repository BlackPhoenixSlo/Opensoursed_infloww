# Multi-platform Phase 2 — plan review

Plan: `.scratch/multi-platform-p2/plan.md` (decisions in `.scratch/multi-platform-p2/issues/00-14`). Specs: `phase-02a-mp2-primitives.md`, `phase-02b-mp2-lists.md`, `phase-02c-mp2-automation-refusals.md`, `phase-02d-mp2-honest-reads.md`, `phase-02e-mp2-mass-reads.md`, `phase-02f-mp2-mass-writes.md`, `phase-02g-mp2-mass-ui.md`, `phase-02h-mp2-docs-handoff.md`. Coordinator decisions D1–D8 are applied in every spec and recorded in each `## Review` under "Plan review".

ASSUMPTION: this file is `multi-platform-p2-plan-review.md`, not `plan-review.md`, because `plan-review.md` already holds another effort's review and Phase 1 set the per-effort name (rung 3, `multi-platform-p1-plan-review.md`). Overturned if the coordinator wants the brief's literal path; then this file is renamed and the old one moved first.

## Workstreams

Linear (D8). Issue 11's file rule allows one open PR at a time on the registry, `server.py` or the Shim, and every Phase except 02h edits one of them. So each wave waits for the one before it, even where the Depends-on graph would allow parallel work.

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 02a-1 — behaviour: 00 a,b,d; 09 A+B + ADR 0068; `send_refusal` + Shim validate-before-group (01 S6, 12 b, 13 F); five Lacks; one grant API (D1); drift strip and route-only reasons (D7) | `phase-02a-mp2-primitives.md` | none |
| 2 | 02a-2 — tests and docs: 12 a KIND_VERDICTS harness + 03 item 6 recorder, Lift-table drift test, WATCH checks, parity grade column | `phase-02a-mp2-primitives.md` | 02a-1 |
| 3 | 02b — Lists: 01 S1–S5, S7, S8; 04 L1–L5 with 05 C; `priority_mass` lane (D3, `fan=` on every Fansly branch) | `phase-02b-mp2-lists.md` | 02a |
| 4 | 02c — Automation refusals: 03 items 1, 3, 4; 05 A, D; 06 B, D; 07 A, C; 08 S2, S3; 12 c, d; 13 A; `nudge_online` lane; `LIFECYCLE_LACKS` | `phase-02c-mp2-automation-refusals.md` | 02a (02b for list-backed lanes) |
| 5 | 02d — Honest reads + UI: 03 item 5; 05 B; 06 A; 07 B; 08 S1, S4; 13 B–E; 09 C | `phase-02d-mp2-honest-reads.md` | 02a, 02c |
| 6 | 02e — Mass reads: 02 a–f (02 a unsend gate first) | `phase-02e-mp2-mass-reads.md` | 02a (file rule: after 02d) |
| 7 | 02f — Mass writes: 14 A–E, G + 00 c + 03 slice 2; commits 14A re-key → 14C caller auth (+ `confirm_live_broadcast` removal, D4) → 14B Shim lift | `phase-02f-mp2-mass-writes.md` | 02a, 02b, 02e |
| 8 | 02h — Docs + handoff: 10 a, 06 E, finished Lift table, 10 b handoff; Phase 2 deploy follows it | `phase-02h-mp2-docs-handoff.md` | 02a–02f (D5; not 02g) |
| 9 | 02g — Mass UI: 14 F | `phase-02g-mp2-mass-ui.md` | 02f + the mirror's posts-only `FanslyScheduled` filter; ships in the first deploy after it merges |

## Adversary

All reviews are codex (blind + draft), 2026-11-27. Counts are the codex findings in each `## Review`; the plan-review lines are counted separately there.

- 02a (`phase-02a-mp2-primitives.md`): 11 accept, 5 partial, 1 reject; needs-human 0. Strongest objection still open: there is no mechanical inventory of Branches (the P1 falsifier is only partly met).
- 02b (`phase-02b-mp2-lists.md`): 13 accept, 3 partial, 1 reject; needs-human 1 from the plan review: does delete_list's `list=` grant have to pin the Proof fan?
- 02c (`phase-02c-mp2-automation-refusals.md`): 9 accept, 6 partial, 0 reject; needs-human 0. Strongest objection still open: the Cell-mode `no_anchor` bypass is scoped, not fixed.
- 02d (`phase-02d-mp2-honest-reads.md`): 12 accept, 3 partial, 0 reject; needs-human 0. Strongest objection still open: ticket 13 item 9's premise is wrong, so the Verdict rows split by mode.
- 02e (`phase-02e-mp2-mass-reads.md`): 10 accept, 4 partial, 0 reject; needs-human 0. Strongest objection still open: date-stop ordering is inferred from a single captured page.
- 02f (`phase-02f-mp2-mass-writes.md`): 13 accept, 2 partial, 2 reject; needs-human 0. Strongest objection still open: membership can still change between the last read and delivery, so the Fan list at schedule time may differ from the one at delivery. One of the two rejects sits inside a partial line.
- 02g (`phase-02g-mp2-mass-ui.md`): 7 accept, 6 partial, 1 reject; needs-human 0. Strongest objection still open: there is no seam from browser to Relay to fake (P1-3).
- 02h (`phase-02h-mp2-docs-handoff.md`): 9 accept, 4 partial, 2 reject; needs-human 0. Strongest objection still open: legacy `fully_backfilled` rows are 02c's code.

## Six hats

Bullets about specs are reconciled in those specs' `## Review` under "Plan review":

- White 1: 02a, 02b, 02c, 02f, 02g
- White 2: 02c, 02d
- Red 1: 02a, 02b, 02c, 02f
- Red 2: 02f
- Black 1: 02b
- Black 2: 02f
- Black 3: 02g, 02h
- Yellow 1: 02a
- Yellow 2: 02a, 02h
- Yellow 3: 02e, 02g
- Green 1: 02a, 02b, 02c, 02f, 02g
- Green 2: 02b
- Green 3: 02f, 02g, 02h
- Blue 1: 02a
- Blue 2: 02b, 02c, 02d, 02f, 02g

The bullets about the set as a whole:

- White 3, the phases really run in a straight line — **accept** (D8). Workstreams is linear, and each spec's Depends on states the order 02a-1 → 02a-2 → 02b → 02c → 02d → 02e → 02f → 02h → 02g.
- Green 3 (plan part), decouple the deploy from the mirror — **accept** (D5). 02h depends on 02a–02f only, and the Phase 2 deploy follows 02h. 02g lands after the mirror filter and ships in the next deploy. `plan.md` still says 02h "Depends on all". That line is the coordinator's to edit.
- Blue 3, one codex draft review of the grant seam across all specs, then M0 — **reject**. D1 now pins the grant shape once, in 02a's Interfaces, and every consumer cites those names. A set-wide re-review would add a round with no open seam. M0 to the mirror thread is the first step of the 02a-1 PR.
- Recommendation, one grant module before 02a's first Shim edit, consumers rewritten, 02g out of 02h's dependencies — **accept**, with D1's names:
  - six-hats' `granted_targets` is `live_check_targets`;
  - `grants()` is not added, because `live_check_targets` + `live_check_methods` cover every reader;
  - `list=` stays for delete_list only (01 Answer item 4), and every send is `fan=`.

## Cut (YAGNI)

Hand-offs between specs in this set are not cuts and are left out.

- `pnpm typecheck` in `scripts/run-tests.sh`: the `tsc` state on main is unmeasured, and the vitest scans and drift tests cover key drift (D6; 02a, 02d).
- Generic Live-check drift machinery (`LIVE_CHECK_LIGHTS` against `CAP_METHODS`): three literal entries pinned in `platform.test` (D6; 02g).
- More than one mutation self-check per harness: one red-on-mutation proves the harness bites, and the rest are plain tests (D6; 02a, 02c, 02d, 02h).
- Codex grant-seam review across specs: D1 closed the seam (Six hats, Blue 3).
- `unblock_user` build: it could only refuse itself until a populated `/ignore` capture exists (D3; 02b).
- Ungranted priority_mass "fans" on Fansly: a follow-up lift PR after the owner's pass (D3; 02b).
- Prod read audit of stored Platform keys: owner rule "never prod DB" (02a).
- Running any Live check, or any Lift (PR 2 per method): owner-only against a real Fansly account, ADR-0070 (02a, 02b, 02c, 02f, 02g).
- WATCH.md lines before a prod deploy: repo rule (02a, 02h).
- Slop runs: owner rule; no Phase changes volume or concurrency (all).
- Migrations: no schema change (02b).
- P2c empty-roster fix, purchase_followup trigger build, earnings stats read: each needs a Proof purchase or capture (02b, 02c).
- Lifting TIP_LEDGER, PURCHASE_LINKAGE and the lifecycle Lacks: needs P1–P4 Proof purchases (02c).
- Collections route limit change: the Shim refuses limit≠50, so the route returns 501 on Fansly (02b).
- `search_users`, `recent_expired_subscribers`, locked text, buyers and single-row queue reads: Blocked as decided (02b, 02e).
- DB `Message` row for an unsent Fansly message: the Shim drop plus live eviction is all 03 item 5 needs (02d).
- Typing before a first message, and measuring Fansly's outbound typing cadence: Fog in 08, and agents never capture (02d).
- `notifications_read` lift: needs owner capture §6.10 (02d).
- Native welcome-rule read and writes: the read needs a scrubbed fixture, and the writes are mirror-owned (02d).
- A Fansly-specific typing word list: no capture exists (02d).
- Generic `/admin/session/{key}` and a scaffold script: parked by 09 (02d).
- `nav.ts`, FuButton, FanslyManagerPage and every Fansly Manager page change: mirror-owned, or deliberate feature gates (02d, 02e, 02g).
- `/stats/deleted` → `isCanceled`: it only matters once a delete exists (02e).
- Mapping `stats.total`: its meaning is unobserved (02e).
- Media, priced, preview, exclude-list, tier, recipient, online-only and funnel broadcasts, and `groupFlags` variants: no capture proves them (02e, 02f, 02g).
- Persisting the `incomplete` flag in a cache column: a Fansly read with no memo walks again (02e).
- OnlyFans-worded Mass-tab error copy on Fansly rows: cosmetic, and the mirror may own the wording (02e).
- Delivered-broadcast unsend on Fansly: never captured (02e, 02g).
- `edit_queued_message` lift: cancel plus re-create loses the message on failure (02f, 02g).
- Two-write Cell-mode claim budget, and Cell mode itself: agency-scale-out owns them; refusing as `:cell_mode` costs nothing now (02f, 02g).
- `mass_message_buyers`: needs a Proof purchase (02f).
- Temp-list emulation and audience snapshots: 14 forbids a new wire call (02f, 02g).
- Chatter-side grant, and a UI toggle for grants: the Live check is owner-only, and the grant is an env var (02g).
- A broadcast's list in the Audience cell: 02e's read carries none, and it is not worth a per-row read for a label (02g).
- Network triage of any site, a second site's registry row, Backend, Shim or stub, and edits to agency-scale-out's files: owner-invoked run, ticket 10 (02h).
- Landing copy about Fanvue and MYM: owed only when a site lands (02h).
- Earnings-total reconciliation against banked rows: deferred until comparable buckets exist (06 item 3; 02h).
- A test for the triage doc's shape: it has no reader, and Acceptance greps cover it (02h).

## Not yet specified

Every plan line maps to a spec (Workstreams). Not yet planned anywhere:

- The mirror thread's posts-only `FanslyScheduled` filter. 02g waits on it; the mirror thread owns it, and it has no plan yet.
- `unblock_user` build and Live check, after a populated `/ignore` capture (02b follow-up).
- Ungranted priority_mass "fans" lift on Fansly (02b follow-up).
- PR 2 Lifts: one per Live-check method after each owner pass (ADR-0070).
- The owner's network-allowed triage run and the pick of site #2 (02h hands off; no spec runs it).
- P1–P4 Proof purchases and captures that unlock the parked Lacks.
- Cell-mode broadcast budget (agency-scale-out).
- `plan.md`'s 02h "Depends on all" line, which is stale after D5.

## Open questions

Every ASSUMPTION across the specs, plus this file's naming ASSUMPTION above.

Sharpest first (each can let a real Fan receive a write, or ship a wrong reason that the Lift table freezes):
- `02b:90` delete_list's one-valid-member precondition stays a caller check on top of 02a's `list=` rule, which binds list id and Completeness, not member identity. Overturned if the owner wants the Proof fan pinned for delete too, then 02a's `ListTarget` gains a `fan=` field.
- `02a:174` a `fan=` grant needs the Complete audience to be exactly that fan, and `list=` binds a list id plus a Complete read, not its members. Overturned by a lane that needs a two-fan check, or by the owner requiring `list=` to also pin the Proof fan (then `ListTarget` gains a `fan=` field).
- `02f:251` the Cell-mode reason is `:cell_mode`, not ticket 14 item 9's `:cell_budget`; the refusal itself is the ticket's, the name follows the coordinator's D4 because /group no longer spends the Budget outside Cells, so "budget" would be a false reason. Overturned if the owner wants the ticket's string; then one suffix and its Lift row rename.
- `02f:252` POST /group type 3 runs outside the claim Budget via a private `delivery=False`; rung 1 for idempotence (`RECIPES.md:1008`) + rung 5. Overturned if a capture shows /group alone notifies a fan; then the Budget gains a broadcast-shaped two-write allowance outside Cells, and Cell mode still refuses.
- `02f:253` `send_ops._capable` admits on `live_check_targets` presence and every Fansly caller of the three methods runs the exact `live_check` before `begin`. Overturned by a caller that reaches `begin` without the exact check; then `begin` takes the checked `ListAudience` and re-runs `live_check` itself.
- `02f:259` membership resolves at delivery, so a scheduled broadcast is re-read only at schedule time (ticket 14). Overturned if scheduled delivery uses a snapshot; then scheduling refuses until a snapshot exists.
- `02f:260` scheduled `groups[]` carries the recipient list (ticket 14). Overturned and failing closed as `:audience_unknown` otherwise.
- `02f:257` Fansly broadcasts run with `retry=False`, including on 429, because it is unknown whether a retried POST resends (Fog); rung 4. Overturned by a capture showing that a retry doesn't resend.
- `02e:284` stats pages come newest-first by id, and snowflake ids encode creation time, so the binding date stop (ticket 02 item 1) loses no in-window row (inferred from `before` = last id, `RECIPES.md:1023`; only one page was captured). Overturned by a fixture or capture where a later page holds a row newer than an earlier page's row; then the date stop becomes a page-level filter and the walk runs to empty/cap.
- `02d:315` ticket 13 item 9 reads `no_anchor` as a no-group outcome. Measured: it fires for every autoreply and `send_followup` in Cell mode, grouped or not, and never outside it (`automation_executor.py:119,538-540`). So the Verdict rows split by mode: Cell mode → declared `no_anchor` lane on both Platforms (the ticket's verdict text, kept); non-Cell → measured on the Stateful fake (expected: the send path mints one group and sends once, as `_group_for_send` does). Neither is `{}`. Which mode prod runs is not observable here (floor 2). Overturned by the test result; only the Verdict row text changes.
- `02d:316` the Cell-mode `no_anchor` return opens no `AutomationRun`, on both Platforms, before this Phase. 02d pins it and does not change it; persisting it is a cross-Platform executor change outside 03/05-09/13. Overturned by the owner wanting it persisted.
- `02c:199` the existing pre-claim `no_anchor` hold stays the Cell-mode verdict for nudge_online_fire and purchase_followup. Overturned if the owner wants Cell-mode jobs made terminal with the Platform reason.
- `02a:188` the interim Unknown-as-OnlyFans label until 02d is acceptable because every reachable Relay path refuses. Overturned if a prod account carries an unknown key before 02d, which `platform_refusals` alerts on.
- `02a:186` a Live-check grant binds account, method and target only; Branch eligibility is the caller's Branch gate before `live_check`. Overturned if a lane needs one method granted per Branch, then the grammar gains a Branch field.
- `02f:258` the route's ledger anchor is X-Op-Id, else the composer key hash, and any `uncertain` mass row holds the Creator's next Fansly mass send, because the composer clears its op id on edit (`massMessageReducer.ts:158-161`) and reload loses it. Overturned if the owner wants a per-anchor hold only.
- `02g:117` the standing exclusion on Fansly is the Relay's job (02f's Contact-guard intersection and the grant's one-fan list), not the composer's. Falls if 02f's `excl_set` omits `MASSdmEXCLUDE` members; then 02f adds them to the intersection, not 02g.
- `02h:138` 02c owns the legacy-row case (06 item 4 says "stops stamping", silent on old rows; 02c:173 treats the flag as display only). Overturned if 02c's spec claims it or no Fansly scan row exists on any target (unknown: 11 Needs the human).
- `02f:250` enforce-mode AUTOFENCE refuses rather than checking the member difference, and paused/unhealthy keeps AudienceHalt; rung 4. Overturned if the owner wants AUTOFENCE on Fansly; then it gets a Complete-read member check.
- `02c:208` after the 07 A Blocked entries, the app KPI may show a stale value until 02d's 07 B gate; safe in prod because the read now refuses rather than invents. Overturned if 02d lands first.
- `02e:283` the cursor advances on the raw page's last id, including skipped and out-of-window rows. Falls if Fansly's `before` doesn't accept a skipped row's id: the walk stops on a repeated cursor and reads `incomplete` (walk rules).

The rest, by spec (line = `docs/spec/phase-<spec>-mp2-*.md` line):
- `02a:169` Unknown platform is a Platform value, not an exception, so roster and sweeps keep listing the account. Overturned if the owner wants such accounts hidden.
- `02a:170` `platforms.get` maps the empty string to OnlyFans like None. Overturned by a stored empty key that must refuse.
- `02a:171` the Unknown platform refusal is enforced in `client_pool.get`, `_make_client` and `_load_client`, covering every OnlyFans client load except the direct `from_account` call left to 02c. Overturned if 02c's spec moves that call here.
- `02a:172` `ensure_platform` on an Unknown account raises `PlatformCollision` (409) explicitly, before any Cell reservation, rather than overwriting the key. Overturned by an owner repair flow.
- `02a:173` a target-less `PLATFORM_LIVE_CHECK` entry is inert with a warning. Overturned if a list-free method needs an account-wide grant.
- `02a:175` send refusal reasons are `platform_lacks:tagged_users` / `platform_lacks:locked_text` as the tickets wrote, not `<method>:<branch>`. Overturned by the plan renaming them.
- `02a:176` the auto co-tag branch refuses only when the send would really co-tag — derived `auto_tag`, `media_cotag.enabled()`, media present and `needs_cotag`. Overturned if Fansly ever co-tags text or the owner accepts untagged sends.
- `02a:177` mark unread, pin and unpin drop their `returns=` and raise, because only routes via `_platform_call` reach them. Overturned by a service caller that needs a quiet None.
- `02a:178` the live_check path is proven with a test-only Shim subclass and kind inside the test file, since no method is marked in 02a. Overturned if the plan names a first Live-check method for 02a.
- `02a:179` the OnlyFans control uses a recording client stand-in, not a stateful OnlyFans fake. Overturned if a control row needs read-back.
- `02a:180` the Stateful fake lives beside the Fansly tests and is covered by its own test file. Overturned by a shared fixtures package.
- `02a:181` the Lift-table test reads KIND_VERDICTS by `ast.literal_eval`, so the harness file stays a literal. Overturned if verdicts need computed keys.
- `02a:182` a Lift-table Reason cell may hold several backticked reasons. Overturned by a one-reason-per-row rule.
- `02a:183` `platform_refusals` alerts on any `platform_unknown:` run and only reports `platform_lacks:` counts. Overturned by an owner threshold on lacks volume.
- `02a:184` the send and scheduled-send refusal tests live in a new `service/tests/test_send_refusal.py`, and the Live-check tests in `service/tests/test_live_check.py`. Overturned if the implementer folds them into existing files, in which case the Acceptance list follows.
- `02a:185` Acceptance includes `pnpm test:run` because ticket 11 requires it on every merge candidate, even with no app change. Overturned by an app-free exemption.
- `02a:187` the collector marks `env.source` instead of failing every env read on fallback, so existing env checks keep today's reading. Overturned if all env checks should go `unknown` on fallback.
- `02b:93` AudienceRefusal subclasses AudienceUnknown. Overturned if a catcher must tell the two apart and cannot via isinstance order.
- `02b:95` unlisted subscription fields refuse, status/expires_at under the Lack their value depends on and sub_start under its own branch reason. Overturned if 02c or 06 P2a shows Fansly supplies them.
- `02b:97` capacity derives from page size rather than its own attribute. Overturned if a Platform's list cap and page differ.
- `02b:98` one add command per POST on Fansly. Overturned by a captured multi-command echo.
- `02b:100` no recreate on Fansly. Overturned by an owner request to auto-recreate.
- `02b:102` delete_list kept out of SYNC_METHODS so a missing delete grant doesn't block ordinary sync. Overturned if ticket 01 S2 is read to include it.
- `02b:105` run row status untouched on runner refusal. Overturned if the UI needs a terminal run status.
- `02b:108` raise over empty. Overturned if 02c rebuilds online presence another way.
- `02b:110` autofence is unreachable on Fansly until 02f lifts broadcast sends. Overturned if the inventory finds a Fansly path, then it gets the same capacity rule.
- `02b:114` "partial" encoded as gated:<lack> plus the stats assertion since the verdict grammar has no partial form. Overturned if 12 adds one.
- `02b:172` a list page under 50 rows is complete (map Assumption, rung 2). Overturned by a capture showing a short page with more rows.
- `02b:173` `/lists/account` returns every list in one response, so absence = unknown list (map Assumption, rung 2). Overturned by a paged capture.
- `02b:174` `stats.totalActive` counts the same rows `subscribers()` returns (map Assumption, rung 2). Overturned if counts disagree on a known-complete roster. A paid multi-tier roster where it counts subscriptions, not distinct fans, makes distinct ids < total and fails closed (incomplete).
- `02b:175` block's known-state precondition accepts only the observed empty `/ignore` body. Overturned by a populated fixture.
- `02c:198` a refused nudge fire clears its latch only for its own job id, as declared bookkeeping. Overturned if the owner wants a refused latch left set until a lift.
- `02c:200` a payload refusal found after welcome_chatter's shaping keeps the attempt bump, per its comment at `welcome_chatter_for_info.py:1440`. Overturned if the owner wants refused payloads not counted.
- `02c:201` a refused legacy S4S slot is shown failed from read-side facts (job `done` + poster Platform branch) without writing the slot. Overturned if the Verdict table requires the slot row cancelled.
- `02c:202` typing-sender refusals reuse send_refusal's and check_sendable's own tags; no new reason vocabulary. Overturned by a Verdict row naming a specific string.
- `02c:204` all of 06 D lands in this Phase because the plan lists it nowhere else. Overturned if 02d or 02h claims a part.
- `02c:205` apply_profiles keeps `OFClient.from_account` for OnlyFans per ADR-0053. Overturned by an ADR moving OnlyFans to backend.get_client.
- `02c:207` the welcome trigger keys on the registry's free_follow attribute. Overturned if a second free-follow Platform needs different types.
- `02c:209` 02b is only needed by list-backed lanes' tests; other lanes merge without it. Overturned if the 02b spec names more lanes.
- `02d:308` the new neutral event name is `chat_message_deleted`, and the app evicts it across the Creator's cached Threads. This is rung 3 (the `chat_typing` / `chat_read_changed` naming). The ticket assumed an existing OnlyFans handler, and none exists (measured: no per-message delete in `useChatMessages.ts` or `events_decide.SSE_TYPES`), so 02d adds one as the ticket's fallback prescribes. Overturned if Phase 02a or the mirror names a delete event first; only the string falls.
- `02d:309` the type-10 message object carries `id`, `groupId` and `senderId` like the type-1 message (`RECIPES.md:398` says "the whole deleted message object"; field names from the type-1 fixture in `test_ws_translate.py`). This run did not open fansly/capture/out/. Overturned by a scrubbed type-10 fixture; then only the field mapping changes.
- `02d:310` "the hold's life" (ticket 08 item 3b) is approximated in the socket as a sliding 5 s idle gap per fan, because the socket cannot see the hold. A hold's quiet or think phase longer than 5 s costs one extra scan. Overturned if the hold passes a hold id to `emit_typing`; then the miss keys on it.
- `02d:311` the 5 s throttle constant is ticket 08's, from ~5 s inbound announce frames. Overturned by a capture of the Creator's own typing POSTs; the constant falls.
- `02d:312` app capabilities `subscriber_chart`, `fan_activity` and `native_welcome` map to Shim methods `subscribers_chart`, `transactions` and `my_settings` in the drift test. Overturned if the drift test cannot express a method that refuses with `returns=None`; then `native_welcome` goes to APP_ONLY.
- `02d:313` the unknown-key sentinel `"unknown"` lives only in the app (not in `PLATFORMS`), so the drift test's table-keys-equal-registry check still holds. Overturned if Phase 02a's ADR-0068 wording requires the app row; then the drift parser skips it.
- `02d:317` the app tombstone set holds at most 500 ids per account for the tab's life; after a reload the Shim drop and the Relay cache drop cover story 3. Overturned by a reload within the 5-minute cache on a tab that never saw the event, on another Relay worker; then the cache drop must be shared.
- `02d:318` the Shim walks at most 3 extra raw pages past an all-deleted page. Overturned by a Thread with a longer unsent run; only the constant falls.
- `02d:319` the paid card's `m.new_subs_count` on Fansly comes from Relay DB rows, not from `subscribers_chart` or `transactions`, so 07 B leaves it. Overturned if its source is a refused read; then the paid KPI and LTV gate too.
- `02d:320` the verify-app route steps marked `# manual:` (Creator pick, editor open, Thread pick) are clicks a worker performs with `drive.py click`. Their exact targets are not fixed here because the seed's ids are runtime data. Overturned by a deep-link route; the manual lines become commands.
- `02d:321` the lifecycle editor's disabled reason reuses the GET refusal string, and the free-page refusal applies only when that string is null. This is rung 3 (`useFreePageRefusal` precedent). Overturned if both should show; then the reducer takes a list.
- `02e:279` page size 24, the only `limit` seen in the capture (ticket 02 item 1). Falls: the page cap only.
- `02e:280` the one stats row seen was text-only, so `isFree: true` holds for every kept row (ticket 02 item 2). Falls: media rows stay hidden until a broadcast Live check adds a free-media row.
- `02e:281` `stats.delivered` = OnlyFans `sentCount` (ticket 02 item 2; map assumption). Falls: one mapping line.
- `02e:282` the Stats search box is a case-insensitive substring match on `content` in the Relay (ticket 02 item 2). Falls: search on Fansly Group Stats.
- `02e:285` both broadcast GETs are reads (the capture uses the queue GET as the read-back after cancel, `RECIPES.md:1024`; no before/after on the stats GET, 00 item 3). Overturned if the 02f broadcast Live check sees provider state change across two stats reads; then the stats read is treated as a write.
- `02e:286` a malformed stats page raises the Shim's API error class, not a ValueError. Falls: one exception type.
- `02e:287` the "direct" engagement type is refused by the Shim's Blocked raise inside the method, with no separate Lift-table row. The Lift table counts markers, Lacks flags and Verdict `gated:` reasons, and this is none of those. Overturned if 02a's or 02c's table counts in-method Branch raises; then a `platform_lacks:engagement_messages:direct` row and a declared blocked Branch are added.
- `02e:288` OnlyFans `/messages/queue` answers `{list, hasMore}`, so the Fansly scheduled read copies the Shim's `schedules()` envelope. Falls: the envelope keys of one method.
- `02e:289` scheduled rows don't emit `userLists`/`groups`/price/media. Falls: 02f adds the list mapping with its read-back proof.
- `02e:290` string ids only above 2^53 − 1 at the mass-cache boundary, not for every Platform. Overturned if the owner wants one id type everywhere; then all cache ids become strings and the OnlyFans unsend and keys get re-tested.
- `02e:291` on a Fansly Creator, a DELETE id that is neither a cached broadcast nor a listed pending scheduled post answers 501 `platform_lacks:unsend_mass_message`, not 404. This covers a scheduled-broadcast id, an uncached delivered one, and a stale post id that today would reach Fansly and fail. Falls: the reason or status of one branch; 02f's typed cancel replaces the scheduled-broadcast case.
- `02e:292` `hasMore`/`incomplete` come from a process-memory walk memo keyed by account, `days_back` and `limit`. On Fansly a missing memo counts as stale and walks once (≤20 GETs, reads only). On OnlyFans the flags are absent after a restart and no extra request is made. Overturned if the owner wants the line to survive restarts without a walk; then the flag moves to a cache column, which needs a migration.
- `02e:293` the "more not loaded" line also shows for OnlyFans Creators whose history says `hasMore`. Ticket 02 item 7 words it Platform-neutrally, but it is a visible OnlyFans change. Overturned if the owner wants it Fansly-only; then it keys on `incomplete` alone.
- `02e:294` `mass_message` keeps `mass_message_history` in its Drift mapping. Falls: one mapping entry.
- `02e:295` the unsend gate checks `unsend_mass_message` before `mass_message_history`, so slice a's first commit already shows the final reason. Falls: the order of two names.
- `02f:249` branch suffix names `:audience_lists`, `:recipients`, `:exclude_lists`, `:autofence`, `:filters`, `:media`, `:funnel`, `:extras`, `:contact_guard:<n>`, `:list_incomplete`, `:cell_mode`, `:save_for_later`, `:scheduled_date`; rung 5. Overturned by an owner rename (the Lift table moves with it).
- `02f:254` a scheduled Fansly run stays open like OnlyFans' and settles on cancel via `mark_queue_unsent`; fire-time settlement waits for 02e history; rung 3. Overturned if 02e history can't join a run without a queue id (ticket 14 Fog).
- `02f:255` `broadcast_branch_refusal` takes the runner's argument names, not the plan object, so the Shim can share it; rung 5. Overturned if the Shim can't import the Side-effect gate.
- `02f:256` the forced ledger outside Cells skips epoch, permit and hold, and `send_ops.install` runs at every boot; rungs 3 and 4. Overturned if install needs Cell-only state; then it installs lazily on the first forced claim.
- `02f:262` thresholds refuse as `:filters` (they filter fans, a list send can't apply them) and `require_recipients` applies to the Complete read's size; rung 5. Overturned if Fansly gains a per-fan broadcast target.
- `02f:263` Verdict table rows are judged with no grant (`gated:`), and the granted path is proven in test_fansly_mass_writes; rung 3 (the deployed default is off). Overturned if 12 wants a granted Verdict column.
- `02g:104` a broadcast read error keeps posts and sets `incomplete`. Falls if the mirror wants the Manager page to show the incomplete state; then it reads the same key.
- `02g:159` the Relay started by `drive.py up` inherits the caller's env (`drive.py:126` copies `os.environ`). Falls if it doesn't; then `up` gains a pass-through flag.
- `02g:210` 02f lands the `type` param with numeric ids and 02g only turns them into strings. Falls if 02f left the `type` param out; then 02g adds it here.
- `02g:237` Fansly's scheduled-post read stays a single full page (`hasMore: false` today, `fansly_shim.py:1466-1481`). Falls if posts page; then the merged `hasMore` ORs both reads.
- `02h:154` the handoff message is sent after 02h merges, not at PR open, because the tickets wait on "MP Phase 2 merged". Overturned if the owner wants it earlier; only timing falls.
- `02h:155` the orchestrator finds the agency-scale-out thread by `t3_thread_search` on "agency-scale-out"; no thread found → 02h stays open and is reported as a block with the message text. Falls: The thread lookup only; 02h stays open as a reported block.
- `02h:156` O evidence and the triage run's findings are written into the scorecard cells, not a separate evidence folder. Overturned if the run needs raw notes, then a `.scratch/` folder, never `capture/out/`.
- `02h:157` the recipe gains pointer lines to ADR-0069, ADR-0070, the Verdict table and a per-Platform Lift table, because the plan's goal promises a ready path via the recipe. Overturned if the owner wants the recipe Fansly-free; only that paragraph falls.
- `02h:158` the Phase 1b Blocked tables stay as a dated record with one pointer to the Lift table instead of being deleted. Overturned if the owner wants one list; then they are removed in a later docs PR.
- `02h:159` Follow-up PR reads `pending <trigger>` for rows not yet lifted, and that is not an `owner:` placeholder. Overturned if the owner wants every row lifted before Phase 2 closes, which Live checks and P1–P4 make impossible offline.
- `02h:160` the final checks live in `fansly/test_lift_table.py` rather than a new file, since it already reads the table and `KIND_VERDICTS`. Overturned if 02a builds it without reading `KIND_VERDICTS`, then 02h adds that read.
- `02h:161` no venv in this tree to run the current suites; Acceptance assumes `venv/bin/python` as `scripts/run-tests.sh` does. Overturned by `PY=`.

## Needs the human

- 02a: owner runs each Live check locally and flips its row in a follow-up PR (ADR-0070). Not a merge blocker.
- 02b:
  - Owner Live checks for delete_list, block (plus the populated `/ignore` capture) and priority_mass.
- 02c: owner Live check for `nudge_online` on a non-prod Relay, then the post-deploy automation-log check.
- 02d: owner's post-deploy DM Live check on the Proof fan. Not a merge blocker.
- 02f:
  - After 02g, owner Live checks for schedule/cancel/fire and send.
- 02g: owner Live check of the lit composer after merge. The mirror thread must plan and merge the posts-only filter.
- 02h: owner runs the triage run, gives roster counts and terms rulings, and picks site #2. The orchestrator sends the handoff and deploys AE + public after 02h merges.

## Coordinator rulings after review
- D9: `delete_list` `list=` passes only when the Complete read's members ⊆ `fan=` targets granted on that Creator (closes ADR-0070 "only him" without a second grammar). Veto → combined grant.
- Cell-mode suffix is `:cell_mode` (D4); ticket 14's `:cell_budget` was agent-written.
