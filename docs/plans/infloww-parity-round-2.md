# Infloww parity: round 2 — match the Infloww bundle on eight pages, move auto mass messages to My Automations, demote the Drive import

Goal plan for `/spec-auto docs/plans/infloww-parity-round-2.md --execute --tickets 999`. It follows `docs/plans/infloww-parity-next-steps.md` (run 20261015T230107Z; `.scratch/infloww-parity-next-steps/RUN.md`), whose sign-off graded 37 of 79 Parity matrix rows `unverified` and named eight pages whose layout does not match Infloww. The layout truth is now the real Infloww dashboard bundle, read with REA; the Clone is secondary. The owner's decisions of 2026-10-16 and 2026-10-17 (below) are binding and are not re-opened by any Phase.

## Owner decisions (binding, 2026-10-16, 2026-10-17)

- **The worktree branch is already merged.** Branch `t3code/recreate-infloww-ui-prompt` (worktree `<worktree>`) was merged into `main` locally by the owner: a fast-forward to `5fb64b78` on 2026-10-17 00:35. The `ui-shots` fix the merge needed is `7f0b1c04`. Nothing is pushed.
- **Match the Infloww layout on all eight pages:** Dashboard, Smart Messages, Scripts, Vault Pro, Tracking links, Creator reports, Manage creators, Custom proxy. (2026-10-17; replaces the 2026-10-16 line that made the Clone the layout truth.) The layout truth is the bundle, captured with REA into `docs/infloww-layouts/<page>.md`. Where a Clone page under `ui-redesign/infloww-exact/` disagrees, the bundle wins and the Clone page is fixed. The Inventory `docs/infloww-screens.md` stays the control truth; the Parity matrix's grading rules (`docs/infloww-parity-matrix.md` header) decide `matched`.
- **Smart Messages are nudge and on-purchase messages** (2026-10-17). They are triggered, one-to-one messages: the nudge message, the message on purchase, and any other per-fan behaviour trigger the bundle shows. They are not mass messages.
- **Auto mass messages go in a My Automations tab** (2026-10-17). Automated mass messages leave Smart Messages. They get their own tab under My Automations, with the auto delete (unsend after a time) next to them. If REA shows Infloww puts them somewhere else, follow the bundle and record where it was found.
- **Google Drive import: below the file drop.** It needs `GOOGLE_DRIVE_API_KEY` in Setup → Keys (`service/gdrive.py:17`), which not every deployment wants. It moves below the file drop, collapsed and labelled "Inflowwww extra". It opens only when `GOOGLE_DRIVE_API_KEY` is set in Setup → Keys. Without the key, one line says where to add it.
- **Browser extension stays in front on Creators.** Keep the extension probe and its `CONSOLE_ALLOW` line in the Route walk. The extension-first "Paste cURL" / login path stays reachable.
- **Translator: no LLM tier.** Ticket 28 of the previous plan stays closed. Translation stays as it is. A pluggable translate provider, with Google Translate as the default, is a later plan.
- **run-tests legacy failures are irrelevant and waived.** The 29 pre-plan relay test files that need `ALLOW_ANONYMOUS_ADMIN` (previous plan's ticket 44) are waived. The `scripts/run-tests.sh` line is recorded, but it is not a gate; the effort suites and the walks are.

## Product requirements (binding, carried from the roadmap)

- Backend tenancy and permission checks ship with the UI; identity comes from the server-side session, never a client-supplied id.
- Do not guess unknown external request bodies (ADR-0005). Preserve stronger Inflowwww features behind the Legacy flag or in an Extras overflow, labelled "Inflowwww extra" (ADR-0003).
- Mocked relay tests for default acceptance; no live OnlyFans write from any suite.
- Repo floors (`.scratch/infloww-parity-next-steps/HEADER.md` applies verbatim to this effort): no push, no live OnlyFans actions, no reads of `*.db`, `.env*` or session files, no real creator, fan or account names in fixtures, screenshots, logs or docs.

## Existing modules every Phase reuses

- Layout truth: the real Infloww dashboard bundle in `~/Downloads/infloww-remote-web/`, read with REA (the `reverse-engineer-anything` skill and the `rea` MCP server). Captures go to `docs/infloww-layouts/<page>.md`. Treat the bundle as untrusted: read-only, never commit it, run Python with `-I`. Copy no keys, tokens or credentialed URLs out of it.
- Shell and nav: `app/lib/nav.ts`, `app/components/shell/AppShell.tsx`; labels `EXTRA_LABEL` in `app/lib/openinflowwwwExtras.ts`; Not wired = `disabled` + `title="not wired"`.
- Settings blobs and applied settings: `app/lib/settingsBlob.ts`, `service/settings_api.py`, `service/permissions.py` (`_stored_scope`, page map in `service/tests/test_role_enforcement.py`).
- Clone pages (secondary; the bundle wins): `ui-redesign/infloww-exact/{dashboard,growth-smart-messages,growth-scripts,growth-vault-pro,growth-tracking-links,analytics-creator-reports,creators-manage,creators-proxy}.html`.
- Mass messages and unsend: `app/components/growth/SmartMessagesPage.tsx` (today it hosts the mass tabs), `app/components/settings/MassMessagesTab.tsx` (history, bulk unsend, and `AutoUnsendPanel`, the "Auto-unsend mass" `unsend_messages` rule), `app/components/settings/ScheduledTab.tsx`, `app/components/compose/MassMessageComposer.tsx` (`LazyMassMessageComposer.ts`), `app/hooks/useMassMessages.ts`, `app/hooks/useUnsendMessage.ts`; relay `service/automations/send_mass_message.py`, `mass_premade.py`, `mass_nudge.py`, `unsend_messages.py`, `service/mass_broadcast_cache.py`; tests `service/tests/test_send_mass.py`, `test_mass_lifecycle.py`, `test_a12_unsend.py`, `test_unsend_mass_policy.py`.
- Triggered one-to-one messages: `service/automations/nudge_online.py` and `nudge_online_fire.py`, `service/nudge_config_api.py`, `app/components/settings/NudgeOnlineTab.tsx`, `app/hooks/useNudgeConfig.ts`; purchase trigger source `service/purchase_notifications.py`.
- My Automations: the nav group in `app/lib/nav.ts` (pinned to Auto Post + Auto Story by `app/lib/nav.test.ts`), routes `/growth/auto-post`, `/growth/auto-story`, `app/components/automations/ReadyMadePanel.tsx` (`only=`), `docs/routes.md`.
- Walks and suites: `scripts/ui-shots.sh`, `scripts/settings-check/walk.py`, `scripts/of-mirror-check/`, the Route walk (`/tmp/route-walk-src/walk.py`, never committed; recreate from ticket 41 of the previous plan if `/tmp` was cleared), `.scratch/*/suite.sh`.
- Parity matrix: `docs/infloww-parity-matrix.md` (79 rows, 11 cells each, sections Baseline run / Matrix / Sign-off / Labelled improvements; `suite.sh` checks the contract).

---
## Phase 0 — Baseline on the merged tree, layouts captured with REA

**Goal.** The Parity matrix's Baseline run names the current `main` tip, the file the merge left at the root is where the other records live, and each of the eight pages has a REA layout capture in `docs/infloww-layouts/<page>.md`.

**Decisions already made.** Owner: merge. **Already done by the owner** at 00:35 on 2026-10-17: `main` was fast-forwarded to `t3code/recreate-infloww-ui-prompt` (`5fb64b78`, 62 commits over `3986b7da`: OF Manager nine-tab wiring, the Messages Pro composer rework from `TODO.md` A1–A5 and B1–B2, the upload fixes; A4 "Upload + send fails" fixed in `a86ad044` and ticked). The one merge-caused red, the `ui-shots` phone composer flow still clicking the "+" overflow that TODO A1/A2 removed, was fixed in `7f0b1c04`. The OF Manager click-through and the Route walk have not run since the merge. The worktree still exists at the same commit (floor 2: this plan does not remove it). The bundle wins over the Clone (owner).

**Work.**
1. Rerun the sign-off set on the current tip and point the matrix's Baseline run at that sha: the five effort suites, the mirror check, `ui-shots`, the Settings walk, and, rerun because neither ran after the merge, the OF Manager click-through and the Route walk. The dev server for this tree is `127.0.0.1:3001`. Record the `run-tests` line too; it is not a gate.
2. Move `TODO.md` to `docs/messages-pro-feedback-2026-10-16.md` (git mv) so the root stays clean; keep its content as the record of A1–B2. Update the three rows in `docs/messages-pro-parity.md` (62, 64, 66) that still describe the removed "+" overflow as measured by the flow.
3. Layout capture with REA. Serve the bundle on 127.0.0.1 with `python3 -I -m http.server --bind 127.0.0.1 <port> --directory ~/Downloads/infloww-remote-web`, started from a directory outside the bundle. Point REA's `inspect_web_page`, `capture_web_screenshot` and `analyze_web_bundle` at it. If the SPA blocks on API calls, mock them with a local route. Known limits: `analyze_web_bundle` needs a live page, and `recover_javascript_sources` needs Linux. If the page won't render, use REA's chunk/module map plus `grep -F` on the JS chunks and CSS. For each of the eight pages, write `docs/infloww-layouts/<page>.md` (`dashboard`, `growth-smart-messages`, `growth-scripts`, `growth-vault-pro`, `growth-tracking-links`, `analytics-creator-reports`, `creators-manage`, `creators-proxy`). Each file holds the component tree, every visible label verbatim, tab order, table columns, filters, buttons, empty states, and spacing and colours from the CSS, each with its source chunk or CSS file and offset. `growth-smart-messages.md` also records which per-fan triggers the bundle shows and where the bundle puts automated mass messages and their auto delete. Where a Clone page in `ui-redesign/infloww-exact/` disagrees, the bundle wins: fix the Clone page.

**Depends on:** nothing.

**Out of scope.** Pushing; deleting the worktree; committing the bundle; live sandbox tests (`LIVE_TEST_HERE.md` is the owner's, untracked, left alone).

---
## Phase 1 — Dashboard matches the bundle

**Goal.** `/` reads like `docs/infloww-layouts/dashboard.md`: a KPI header with period tabs over the cards that already exist (My shifts, Current clocked-in employees, the Phase 2 cards). The matrix row §3.1 Dashboard moves from `unverified` to `matched` or lists only tagged, labelled improvements.

**Decisions already made.** Match the Infloww layout (owner). The layout source is `docs/infloww-layouts/dashboard.md`, captured with REA; `dashboard.html` is secondary. KPI numbers come from the relay's existing report endpoints (`service/stats.py`, the Employee reports and Sales records reads) at the Agency's report time zone (Phase 4 of the previous plan); any KPI the relay cannot compute is Not wired, not invented. A reviewer rejects any difference from the capture without an "Inflowwww extra" label.

**Work.**
1. Transcribe the header from `docs/infloww-layouts/dashboard.md`: tabs, KPI tiles, labels, order, spacing (`C[…]` tags from the Inventory §3.1 on every control).
2. Wire each tile to an existing read; period tabs change the window in the URL (`?window=`) as the reports pages do.
3. Keep the shift cards; place them where the bundle places its equivalent, else below the KPI header with the "Inflowwww extra" label.
4. Tests: vitest on the header (tabs, tiles, Not wired tiles), relay test that the Dashboard read holds Agency isolation.
5. Before closing, recheck the page against the bundle with REA. Regrade the matrix row with the walk shot beside the REA capture (and `clone-dashboard.png`).

**Depends on:** Phase 0.

---
## Phase 2 — Growth pages match the bundle: Smart Messages, Scripts, Vault Pro, Tracking links

**Goal.** Four routes read like their `docs/infloww-layouts/` captures. `/growth/smart-messages` holds triggered, one-to-one messages only: the nudge message, the message on purchase, and any other per-fan trigger the bundle shows, in the bundle's tabs and list. Mass messages are no longer on it (Phase 2b). `/growth/scripts` shows ladders with tabs instead of the Templates card; `/growth/vault-pro` has the folder rail and media chips; `/growth/tracking-links` has the Links list and Dashboard tabs. Existing Inflowwww behaviour behind them (the nudge rules, the Scripts store, the Vault import, the tracking-link reads) stays and is reached from the bundle's controls.

**Decisions already made.** Match the Infloww layout (owner). The layout source for each page is `docs/infloww-layouts/<page>.md`, captured with REA; the Clone page is secondary. Smart Messages = nudge and on-purchase messages, not mass messages (owner, 2026-10-17). Each page's data stays what it is today; a bundle control with no relay behind it is Not wired with the house marker, never a fake. A reviewer rejects any difference from the capture without an "Inflowwww extra" label.

**Work.** One ticket per page, each: transcribe the layout from `docs/infloww-layouts/<page>.md`; move the existing panel into the bundle's structure; Not wired markers for bundle controls without a read/write; vitest for structure and markers; before closing, recheck the page against the bundle with REA; matrix row regraded with the walk shot beside the REA capture. Smart Messages specifically:
1. Nudge message: `NudgeOnlineTab` and `useNudgeConfig` (relay `nudge_online.py`, `nudge_online_fire.py`, `nudge_config_api.py`) in the bundle's list and editor.
2. Message on purchase: the trigger reads `service/purchase_notifications.py`; the send reuses the existing per-fan send path. If no existing path can send it, the control is Not wired. No new sending path.
3. Other per-fan triggers only where `growth-smart-messages.md` shows them; each is wired to an existing automation or Not wired.
4. Remove the Mass messages and Scheduled tabs, the "New Message" mass composer and "Message online fans" from Smart Messages only after Phase 2b ships them in My Automations, so they are never unreachable.

**Depends on:** Phase 0; the Smart Messages ticket also on Phase 2b.

**Out of scope.** New Growth features the bundle shows but the relay cannot do (they become Not wired rows, not tickets). Live sends in tests.

---
## Phase 2b — My Automations: Auto mass messages with auto delete

**Goal.** A new My Automations tab, "Auto mass messages", holds the automated mass messages and, next to them, the auto delete (unsend after a time). If `docs/infloww-layouts/growth-smart-messages.md` shows Infloww puts them somewhere else, the tab goes where the bundle puts them, and the capture records where that was found.

**Decisions already made.** Owner, 2026-10-17. The layout source is the bundle's mass-message screen as captured with REA in `docs/infloww-layouts/`; where Infloww has no such screen, the tab is ours, labelled "Inflowwww extra". Reuse the existing mass-message and unsend code; no new sending path, and no live sends in tests. Mass Nudge (`mass_nudge.py`, `MassNudgeTab.tsx`) is a broadcast, so it goes here, not in Smart Messages, unless the bundle says otherwise. A reviewer rejects any difference from the capture without an "Inflowwww extra" label.

**Work.**
1. Route and nav: a new route under My Automations in `app/lib/nav.ts` (with `/growth/auto-post` and `/growth/auto-story`); update `app/lib/nav.test.ts`, which pins the group to Auto Post + Auto Story, the page map in `service/permissions.py` and `service/tests/test_role_enforcement.py`, and `docs/routes.md`.
2. Move, not rewrite: `MassMessagesTab` (history, bulk unsend), `ScheduledTab`, `LazyMassMessageComposer` and `MassNudgeTab` from `SmartMessagesPage.tsx` into the new tab. Put `AutoUnsendPanel` (the "Auto-unsend mass" `unsend_messages` rule) next to the mass-message list. Relay unchanged: `send_mass_message.py`, `mass_premade.py`, `mass_nudge.py`, `unsend_messages.py`, `mass_broadcast_cache.py`.
3. Tests: vitest for the tab's structure and the auto-delete control; the existing relay tests (`test_send_mass.py`, `test_mass_lifecycle.py`, `test_a12_unsend.py`, `test_unsend_mass_policy.py`) stay green with mocked OF calls only. Before closing, recheck against the bundle with REA.
4. Matrix: a row for the tab (or its place in the bundle), and a Labelled improvements line if the tab is ours.

**Depends on:** Phase 0.

**Out of scope.** Changing how mass messages send or unsend; new automation kinds.

---
## Phase 3 — Creator reports matches the bundle

**Goal.** `/analytics/creator-reports` shows the Overview / Creator performance tabs as `docs/infloww-layouts/analytics-creator-reports.md` records them; the current Ingest health content stays reachable from an "Inflowwww extra" tab or overflow.

**Decisions already made.** Match the Infloww layout (owner). The layout source is `docs/infloww-layouts/analytics-creator-reports.md`, captured with REA; `analytics-creator-reports.html` is secondary. A reviewer rejects any difference from the capture without an "Inflowwww extra" label.

**Work.** Transcribe the layout from `docs/infloww-layouts/analytics-creator-reports.md`; move Ingest health; wire Overview to the existing per-Creator stats reads; Not wired where no read exists; tests; before closing, recheck against the bundle with REA; regrade with the walk shot beside the REA capture.

**Depends on:** Phase 0.

---
## Phase 4 — Creators pages match the bundle, extension kept in front

**Goal.** `/creators` leads with the creator table from `docs/infloww-layouts/creators-manage.md`; adding a creator through the browser extension (Paste cURL / login) is the first action in the table's Add flow, as the owner wants the extension in front. `/creators/proxy` shows the columns and egress table from `docs/infloww-layouts/creators-proxy.md`; the paste box becomes the Add action.

**Decisions already made.** Match the Infloww layout (owner). The layout source is `docs/infloww-layouts/creators-manage.md` and `creators-proxy.md`, captured with REA; the Clone pages are secondary. Keep the extension probe and its `CONSOLE_ALLOW` line (owner). Tenancy holds as `service/tests/test_creators_tenancy.py` proves today; every new read/write gets a case there. A reviewer rejects any difference from the capture without an "Inflowwww extra" label.

**Work.**
1. Manage creators: creator table first (columns from `creators-manage.md`), Add creator opens the existing Paste cURL card and login forms; probe unchanged.
2. Custom proxy: columns from `creators-proxy.md`, egress table from the registry (`proxy_registry`), paste box inside Add; the real registry file stays off limits to tests (mkdtemp copies only).
3. Tests; before closing, recheck both pages against the bundle with REA; regrade both rows (§3.7) with the walk shots beside the REA captures.

**Depends on:** Phase 0.

---
## Phase 5 — The Google Drive import goes below the file drop, behind a configured key

**Goal.** On the Vault import card (`app/components/vault/VaultImportCard.tsx`) the file drop leads; the Drive-link paste sits in a collapsed "Inflowwww extra" section below it that only opens when `GOOGLE_DRIVE_API_KEY` is set in Setup → Keys; without the key the section is one line saying where to add it. `service/gdrive.py` is unchanged.

**Decisions already made.** Below the file drop, collapsed, not removed (owner). The layout source for the rest of the card is `docs/infloww-layouts/growth-vault-pro.md`, captured with REA; the Drive section is the labelled extra. A reviewer rejects any other difference from the capture without an "Inflowwww extra" label.

**Work.** A relay read that says whether the key is configured without revealing it (or reuse the existing keys-status read if one exists); the collapsed section; vitest for both states; before closing, recheck the card against the bundle with REA; matrix row updated.

**Depends on:** Phase 0.

---
## Phase 6 — Sign-off

**Goal.** One commit on which the five effort suites, the mirror check, `ui-shots`, the Settings walk, the OF Manager click-through and the Route walk are green; the Parity matrix's regraded rows carry their evidence; `## Sign-off` records every line verbatim; the `run-tests` line is recorded, not a gate (owner's waiver).

**Work.** As the previous plan's Phase 6: regrade, walk, record, sign. The regrade compares each walk shot with a REA capture of the same page, not only with the Clone shot. The matrix's `Labelled improvements` list gains anything Phases 1–5 and 2b kept as an "Inflowwww extra".

**Depends on:** Phases 1–5 and 2b.

---
## Needs the human

- Delete the worktree when it is no longer needed (floor 2 keeps this plan from doing it).
- The pluggable translate provider (Google Translate default) as a later plan.

## Sources

- `.scratch/infloww-parity-next-steps/map.md` ("Ticket 42 (grading)" line), `RUN.md`, `docs/infloww-parity-matrix.md`
- `git reflog show main` (fast-forward at 2026-10-17 00:35 to 5fb64b78), `TODO.md` at the repo root, `docs/infloww-parity-matrix.md` › `## Sign-off` (run 8 on 7f0b1c04)
- `~/Downloads/infloww-remote-web/` (the Infloww dashboard bundle; untracked, read-only)
- `service/gdrive.py`, `app/components/vault/VaultImportCard.tsx`
- `app/components/growth/SmartMessagesPage.tsx`, `app/components/settings/MassMessagesTab.tsx`, `service/automations/unsend_messages.py`, `app/lib/nav.ts`
- Owner messages of 2026-10-16 and 2026-10-17 in this session
