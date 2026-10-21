# Infloww parity: next steps

Goal plan for `/spec-auto docs/plans/infloww-parity-next-steps.md`. It covers the work that remains after the three original runs (OF Manager connectors, Messages Pro parity, Settings tabs) and the Messages Pro look-and-feel run, reconciled against the repository on 2026-10-16. Each `Phase <n>` heading becomes one spec.

ASSUMPTION: this plan was derived from the root file `nestStepsInflowCopy.txt` (the parked roadmap "NEXT STEPS: INFLOWW PARITY + PRODUCT IMPROVEMENTS") because the invoked path did not exist. A byte-identical copy of that roadmap also sits untracked at `docs/plans/infloww-parity-next-steps.md` in the `t3code/recreate-infloww-ui-prompt` worktree (`diff` exits 0). Overturned if the owner supplies a different plan.

**The most important reconcile finding.** `main` (8581aead) does not hold the original runs' results. They live on the unmerged branch `t3code/recreate-infloww-ui-prompt` (worktree `<worktree>`, tip 4c9c7160). That branch is 454 commits ahead of `main` and 14 behind, with 525 files changed and +55302/−5274 lines. `git merge-tree --write-tree main t3code/recreate-infloww-ui-prompt` reports exactly one conflict, in `app/components/auth/Landing.tsx`: the branch moved the repo URL into `app/lib/repoUrl.ts`, and `main` reworked the landing page for the parody auth pages. On that branch:

| Effort | Plan / map on the branch | Status (`map.md` status column, counted) |
|---|---|---|
| messages-pro-parity | `docs/plans/messages-pro-parity.md`, `.scratch/messages-pro-parity/map.md` + `RUN.md` | 129 done, 1 closed (ticket 121: the human ruled that Tailwind scale classes are not magic numbers). RUN.md says "DONE. Stop condition: empty frontier" |
| of-manager-connectors | `docs/plans/of-manager-connectors.md`, `.scratch/of-manager-connectors/` | 40 done, 6 parked (06, 12 and 19 are live checks; 31 is the Tips `type` value; 38 is the trial-link write; 46 rests on 38) |
| settings-tabs | `docs/plans/settings-tabs.md`, `.scratch/settings-tabs/` | 28 of 28 done, none parked |
| messages-pro-look-and-feel | `docs/plans/messages-pro-look-and-feel.md`, `.scratch/messages-pro-look-and-feel/` | 23 of 23 done (tickets 131–153), sign-off at fe3011c8 |

On `main` itself, `docs/plans/of-manager-connectors.md`, `docs/plans/settings-tabs.md` and their `.scratch` dirs do not exist. `.scratch/messages-pro-parity/map.md` on `main` is the stale 2026-10-12 snapshot: 127 tickets, of which 23 are done, 100 ready-for-agent, 2 parked (B11 page-bounded figures; scale classes) and 2 claimed with stale claims (20261012T175302Z, 20261012T180132Z). Counted with `grep -E '^\| [0-9]+ \|' .scratch/messages-pro-parity/map.md`, the brief's "~27 done" is 23. The branch already finished all 100 of those ready tickets.

**Messages Pro parity is not re-ticketed here.** Its plan and map own it. If the branch is merged (Phase 0), nothing is left to continue. If the owner declines the merge, continuing it on `main` is a separate `/spec-auto docs/plans/messages-pro-parity.md --execute` run, which would redo work that already exists on the branch. That choice is under `## Needs the human`.

ASSUMPTION: every Phase below builds on the merged tree (`main` plus `t3code/recreate-infloww-ui-prompt`), and Phase 0 performs that merge locally, without pushing. Rung 3 (house precedent): `main` already merges finished t3code branches with `merge:` commits (8581aead, 9fc6bdba). Overturned if the owner wants the branch kept apart, in which case Phases 1–6 run on that branch and Phase 0's merge step is dropped.

## Product requirements (binding, from the roadmap)

Copied from `nestStepsInflowCopy.txt`. They bind every Phase.

- "S4S discovery is limited to creator and agency records in the same shared database/deployment (typically 2–5 agencies in one Docker environment), never a global/public directory."
- "Implement backend tenancy and permission checks with the UI."
- "Do not guess unknown external request bodies." ADR-0005 (branch) says the same: "of-mirror sends only known bodies".
- "Preserve stronger Inflowwww features and label deliberate improvements." ADR-0003 already sets the labelling: kept behind the Legacy flag or in an Extras overflow, with the tooltip "Inflowwww extra".
- "Authentication and employee identity come from server-side session context, never a trusted client-supplied employee or agency id."
- "Migrations are reversible or have a documented recovery path; include indexes, constraints, data retention, and audit events for consequential actions."
- "Use mocked network/relay tests for default acceptance. Any live write test must be separately authorized … and be impossible to trigger from the normal automated suite."
- Repo floors (HEADER.md): no push, no live OnlyFans actions, no reads of `*.db`, `.env*` or session files, and no real creator, fan or account names in fixtures, screenshots, logs or docs.

## Existing modules every Phase reuses

YAGNI: the plan adds no new service, no new runtime dependency and no new scheduler.

- Relay (FastAPI, `service/server.py`) with per-feature routers like `service/settings_api.py`. Tables are in `service/db/models.py`, and migrations are Alembic under `service/db/migrations/versions/`; the latest is `20261014_0100_split_inbox.py`.
- Tenancy: `service/auth.py` `require_user` (`:142`), `assert_account_owned` (`:289`) and `require_master` (`:854`), plus `_account_isolation_middleware` in `service/server.py`. Chatter sessions use `service/chatters.py` `get_request_chatter` (`owner_user_ids`). The Employee mirror is `service/employees.py` `resolve_outbound_employee_id` / `resolve_chatter_employee_id` (`:549-620`).
- Settings blobs: the `user_settings` table, `GET`/`PUT /admin/settings/{tab}` for `account`, `preferences`, `roles`, `sales`, `time-tracking` and `messaging` (`service/settings_api.py:34`), and `useSettingsBlob` in the app. ADR-0007 and ADR-0008 are on the branch.
- App: Next.js under `app/` with `app/lib/nav.ts` (the single route tree, `nb()` stubs), `app/lib/relay.ts`, `components/NotBuiltYet` and the shared Settings Panel parts (`SettingsTable`, `ToggleRow`, `Switch`, `Card`, `SubTabs`).
- Tests: `pnpm -C app typecheck`, `pnpm -C app lint` and `pnpm -C app test:run` (vitest; `app/package.json` scripts). Relay tests are plain-assert scripts run as `./venv/bin/python service/tests/test_<x>.py` (228 files; for example `test_account_isolation_gate.py`, `test_chatter_access.py` and `test_settings_api.py`). Effort suites follow `.scratch/<effort>/suite.sh` (house precedent: `.scratch/settings-tabs/suite.sh`). The visual check loops are `scripts/ui-shots.sh` (Messages Pro), `scripts/settings-check/walk.py` and `scripts/of-mirror-check/*.py`.

## Baseline table

Status values: done / partly / missing / intentionally different / blocked. "Branch" means it is present on `t3code/recreate-infloww-ui-prompt` and arrives on `main` with the Phase 0 merge. Paths are relative to the merged tree.

| Area (inventory §) | Status | Evidence |
|---|---|---|
| Global shell: sidebar, top bar, timezone, SFW (§1.1–1.2) | partly | `app/lib/nav.ts`, `app/components/shell/TopBar.tsx`; Referrals/Leaderboard links absent (no `/referrals` or `/leaderboard` in `app/`) |
| Platform selector Fansly / mym / Fanvue (§1.1, §6.13) | blocked | only OnlyFans inventoried (`docs/infloww-screens.md` §6 item 13) |
| Idle mode, update prompt (§1.3) | missing / intentionally different | Out of Scope in messages-pro-parity (`.scratch/messages-pro-parity/map.md` "Idle mode (P1)"); the update prompt is desktop-app only |
| Dashboard earnings blocks (§3.1) | partly | `app/app/page.tsx` (comment: "Phase B replaces this with the Dashboard component"), `app/components/home/CompetitorReports.tsx`, `TotalRevenueChart.tsx`; clone-only cards not yet reclassified |
| Dashboard "My shifts", "Current clocked-in employees" (§3.1) | missing | no shift/clock table in `service/db/models.py`; no card in `app/components/home/` |
| OF Manager mirror + connectors (§3.2) | partly (branch) | 40/46 done, 6 parked (`.scratch/of-manager-connectors/RUN.md`) |
| Messages Pro (§3.3) | done (branch) | `.scratch/messages-pro-parity/RUN.md` "DONE"; look-and-feel 23/23 |
| Analytics: Creator / Employee / Fan reports (§3.4) | partly | `app/components/stats/StatsReport.tsx` views `creator\|employee\|fan`; Fan reports is `UserDataTab` with "ours" panels; no "Clocked hours" (no time data) |
| Analytics: Message dashboard (§3.4) | partly | `/analytics/message-dashboard` (old `/messages`) |
| Analytics: Sales records (§3.4) | missing | no `/analytics/sales-records` route; data exists in `service/attribution.py` |
| Leaderboard (§3.9) | blocked / intentionally different | Infloww's ranks against Infloww's global customer base; nothing like that exists inside one deployment |
| Growth: Smart Messages, Scripts, Vault Pro (§3.5) | done (pre-existing) | `docs/routes.md` Sidebar rows |
| Growth: Smart lists, Auto-follow (§3.5) | partly | `app/components/growth/SmartListsTab.tsx`, `AutoFollowTab.tsx`, `service/smart_lists_api.py`; smart lists used by `compose/MassMessageComposer.tsx` |
| Growth: Tracking links (§3.5) | done (branch) | `service/tracking_links_api.py`; connectors Phase 5 tracking-link write wired |
| Growth: Free trial links, Profile promotion (§3.5) | blocked | connectors ticket 38 parked (`expired_at` body), promotion "Start campaign" read-only (connectors RUN.md Assumption 1) |
| Growth: Sensitive Words, AI Copilot (§3.5) | partly | `service/sensitive_words_api.py`, `automations/_wordfilter.py`; Composer AI button (messages-pro-parity Phase 4) |
| Share for Share (§3.6) | missing | `app/app/share-for-share/[section]/page.tsx` renders `NotBuiltYetRoute`; `nav.ts:129-131` `nb(...)`; inventory says "Dropped on purpose", which the roadmap overturns |
| Creators, Custom proxy (§3.7) | partly | `/creators`, `/creators/proxy` (`setup/ProxiesTable`); clone extras unlabelled |
| Employees: CRUD, chatters (§3.8) | partly | `app/components/employees/ManageEmployees.tsx` (53 lines: `EmployeesTab` + `ChattersTab`); no groups, batch actions or deactivate view |
| Employees: Organization chart (§3.8) | missing | no `/employees/org-chart`; no group table |
| Employees: Shift schedule (§3.8) | missing | `app/app/employees/shifts/page.tsx` renders `NotBuiltYetRoute`; `nav.ts:163` |
| Notifications page (§3.9) | partly | `components/NotificationBell.tsx`, OF Manager `notifications/*` mirror; no `/notifications` overlay; Tips tab parked (ticket 31) |
| Referrals (§3.9) | intentionally different | Infloww's own partner program; Your Balance shows per-Creator OF referral cards (settings-tabs ticket 23) |
| Settings: 11 tabs UI (§3.10) | done (branch) | settings-tabs 28/28; `docs/settings-parity.md` |
| Settings: stored values applied (§3.10) | missing | ADR-0008: "Settings store what Infloww stores and apply none of it" |
| Settings: 2FA, password, sessions, billing, wallet (§3.10) | blocked | Not wired by design (settings-tabs RUN.md "Cut"); no auth or billing backend |
| Role permissions enforced server-side | missing | roles blob `{roles, assignments}` (`RoleSettingsTab.tsx:27`) is read by nothing |
| Employee identity source | partly | owner sessions send client-picked `X-Employee-Id`, validated against ownership (`service/employees.py:569-583`); chatter sessions resolve server-side |
| Automations: Auto Post, Auto Story (§4.1) | done | `service/automations/auto_posts.py`, `auto_stories.py` |
| Help center | intentionally different | `app/app/help-center/page.tsx` stub |
| Phone layouts (§5) | intentionally different | Inflowwww improvement, `docs/routes.md` "Responsive behaviour" |

Other branches, read-only (`git log --oneline main..<b>`):

- `t3code/recreate-infloww-ui-prompt` is 454 ahead and holds every effort above. Its worktree also has uncommitted edits (`app/components/chat/VaultPicker.test.tsx`, `app/lib/messagesProOurs.ts`, `app/lib/relay.ts`, an untracked `app/components/chat/MessageList.media.test.tsx`) that belong to a live session. They are not part of the merge.
- `t3code/direct-browser-login` is 3 ahead: docs only (direct-login spec and build prompt, 771 lines).
- `scenes-lane` is 7 ahead (2026-08-15): in-flight scene-lane automation work, unrelated.
- `lane/chat-ui`, `lane/funnels`, `lane/mass-audience` and `fix/tip-detection-ws` are 1 ahead each: July WIP snapshots and a live tip driver, unrelated.
- `t3code/merge-worktree-changes`, `t3code/parody-auth-pages`, `customs-handoff`, `deferred-cheap`, `fansly-vault-and-send`, `fix/quota-purchase-reopens-day`, `hook-upsell`, `sales-wire-fixes`, `sleep-badge` and `sticky-save` are 0 ahead (fully merged).

---

## Phase 0 — Merge the finished runs, fix stale docs, publish the route matrix

**Goal.** Bring the four finished efforts onto `main`, prove the combined tree green on one commit, and replace stale counts and routes with an honest route-by-route matrix. That matrix is the baseline every later Phase cites.

**Decisions already made.**
- Roadmap: "Finish eligible tickets that are part of the original plans before starting new work. Keep 'needs human' decisions parked; do not guess a request body, enum, or product policy." No eligible ticket remains. The six parked connector tickets need live checks or unknown bodies (floor 2), so they stay parked.
- Roadmap: "Run each plan's stated acceptance suite on the same final commit. Fix stale docs, route maps, ticket counts, screenshots, and test paths."
- Roadmap: "Make an updated route-by-route matrix: Infloww surface, current Inflowwww route, visual evidence, real data source, read/write behavior, permission scope, and remaining gap." Every numbered section of `docs/infloww-screens.md` is a row.
- Roadmap: "Treat old screenshots and the July 2026 gap analysis as evidence to re-check, not current truth." Record the inventory version (v5.7.14 capture or v5.7.20 bundle/help) on every row.

**Current state.** See the reconcile finding at the top. `docs/routes.md` on `main` still lists the Settings tabs as "stubs" and has no `docs/settings-parity.md` row. The branch fixes the Settings row, and its `docs/routes.md` auto-merges (merge-tree). The Dashboard row's "existing home page" is not graded against §3.1.

**Work.**
1. Merge `t3code/recreate-infloww-ui-prompt` into `main` with a `merge:` commit. Resolve `app/components/auth/Landing.tsx` by keeping `main`'s parody-site behaviour and the branch's `REPO_URL` import from `app/lib/repoUrl.ts`.
2. Run every effort suite on the merge commit: `sh .scratch/messages-pro-parity/suite.sh`, `.scratch/of-manager-connectors/suite.sh`, `.scratch/settings-tabs/suite.sh`, `.scratch/messages-pro-look-and-feel/suite.sh`, plus `node scripts/of-mirror.mjs --check`. Record each suite's last line.
3. Write `docs/infloww-parity-matrix.md`: one row per inventory section and sub-screen, with the columns the roadmap names plus `status` (matched / intentionally improved / not wired / unverified / missing / blocked) and `inventory version`. Seed it from this plan's Baseline table.
4. Fix stale docs only where the merge leaves them wrong: `docs/routes.md` (Shift schedule and S4S stay "stub" until their Phases land), and `docs/infloww-screens.md` §3.6's "we dropped it", which now points to Phase 3 of this plan.
5. Walk `/`, `/employees`, `/settings/time-tracking` and `/messages-pro` at 1440×900 and 390×844 in light and dark. Use the existing harnesses (`scripts/ui-shots.sh`, `scripts/settings-check/walk.py`); PNGs go under `/tmp`, never committed.

ASSUMPTION: the matrix goes in a new doc `docs/infloww-parity-matrix.md` rather than more columns in `docs/infloww-screens.md`. Rung 3: `docs/settings-parity.md` and `docs/messages-pro-parity.md` are per-effort parity docs. Overturned if the owner wants one inventory file.

**Depends on:** nothing.

**Out of scope.** The six parked connector tickets (live checks and unknown bodies). Re-grading Messages Pro or Settings visuals (both are signed off). Pushing. Scrubbing the absolute home paths that `scripts/check-public-export.sh` flags (settings-tabs RUN.md › Needs the human), which stays the human's call. The live session's uncommitted edits in the branch worktree.

## Phase 1 — Agency context and server-side employee identity

**Goal.** Give later Phases one relay helper that answers "which agency, which Employee, which role" from the session alone, and one cross-agency negative-test fixture, so that shifts, S4S and permission enforcement don't each reinvent tenancy.

**Decisions already made.**
- Roadmap gate: "Authentication and employee identity come from server-side session context, never a trusted client-supplied employee or agency id."
- Roadmap gate: "Agency tenancy enforced at every read/write; tests include cross-agency negative cases."
- `docs/routes.md` (main): "Each owner account is an agency … the master role (`users.is_admin`) … sees every account."

**Current state (observation).** Tenancy exists for account-scoped resources (`assert_account_owned`, the isolation middleware, `test_account_isolation_gate.py`), and agency-wide rows are keyed on the session user id (`settings_api.py`: "the user id comes from the session and never from the request"). Employee identity has three paths (`service/employees.py:549-590`):
- A chatter session resolves server-side to a mirror Employee.
- An owner session trusts a client-picked `X-Employee-Id` after an ownership check.
- An unauthenticated caller's header is taken as-is (`:587-589`).

Shifts and S4S rows are agency-scoped but not account-scoped, and no helper returns the agency id for a chatter session, whose `owner_user_ids` can hold more than one owner.

**Work.**
- `agency_context(request)` in `service/auth.py` (or `service/employees.py`, beside the resolver) returns `{agency_user_id, employee_id | None, is_owner, is_master}`. It is built only from `get_request_user()` / `get_request_chatter()`, with no header input. When a chatter is linked to more than one owner, the request names the agency through an account it may access (`assert_account_owned`), never a raw agency id.
- A reusable plain-assert fixture under `service/tests/` that seeds two agencies, each with an owner, a chatter and a creator. Every later Phase's tests assert cross-agency 403/404 with it.
- Unauthenticated (`user is None and chatter is None`) gets 401 on every endpoint this plan adds. The existing header fallback for internal cron callers is left untouched.

ASSUMPTION: an owner session acts as the agency, not as an Employee. Writes that need an actor Employee (clock in/out) come only from chatter sessions, and an owner's edit of someone's shift or timesheet is recorded as an owner edit in the audit history. Rung 2 (the roadmap gate forbids trusting a client-supplied employee id) plus rung 4. Overturned if the owner wants owners to clock in as themselves, which needs an owner-to-Employee link that does not exist (`Employee.user_id` is the owning agency, not the person).

**Depends on:** Phase 0.

**Out of scope.** Enforcing role permissions (Phase 4). Changing the owner `X-Employee-Id` path for chat-send attribution (it stays as it is, and the matrix records it). New auth, 2FA or sessions.

## Phase 2 — Shifts, time tracking and the Dashboard shift cards

**Goal.** One backend-backed shift and time-tracking feature: the agency-scoped Shift schedule at `/employees/shifts`, clock in/out for the signed-in Employee, timesheet rollups, and the Dashboard's "My shifts" and "Current clocked-in employees" cards, all on the same endpoints and agency scope.

**Decisions already made (roadmap, verbatim where they constrain).**
- "Agency-scoped shift records assigned to one or more employees and creators, with timezone-aware start/end, repeat rules, status, and safe edit/cancel history."
- "Clock-in/out events tied to the authenticated employee and assigned creator; prevent duplicate active shifts and invalid clock-outs. Support the configured auto-clock-out and reminder policy."
- "Shift calendar with week navigation, employee/creator filters, create/edit/cancel flows, and the 'allow multiple employees on the same shift for the assigned Creator' setting."
- "Timesheet rollups: scheduled vs worked shifts, hours, employee/creator totals … Clearly separate recorded earnings from calculated payroll; do not silently claim to pay employees."
- "Dashboard cards for 'My shifts' and currently clocked-in employees, using the same backend source and agency permissions as the shift page."
- "API/schema migrations, validation, audit trail, indexes, agency isolation, and tests for overlaps, daylight-saving transitions, abandoned sessions, simultaneous clock actions, and unauthorized cross-agency reads/writes."
- Inventory §3.8: week calendar; "Create shift(s)" opens "Shifts" with "+ Add Shift" (start/end, Creators, employees, repeat weekly by day, "Repeat Ends" "Never" or a date, "OK", 🗑️). Filters are Employee / Creator / "Reset" / "This week". ⚙️ "Shift Settings". Shift history shows Total Earnings, Scheduled Shifts and Shifts Worked.

**Current state.** Missing: there is no shift, clock or timesheet table (`grep -n __tablename__ service/db/models.py`), the page is `NotBuiltYetRoute`, and the Dashboard has no cards. The stored inputs already exist: the `time-tracking` blob `{enabled, auto_clock_out_minutes, clock_in_reminder}` (`TimeTrackingTab.tsx:16-17`), the `sales` blob's `multi_employee_shift` toggle (`SalesSettingsTab.tsx:38`) and the roster `useRoster` with `EmployeeAccountAccess` (Employee to Creator access). ADR-0008 says nothing reads them yet.

**Work.**
- An Alembic migration with a working `downgrade()` adds three tables:
  - `shifts`: agency_user_id, start_utc, end_utc, tz, repeat rule, repeat_until, status, created_by, cancelled_at.
  - `shift_assignments`: shift × employee × account.
  - `clock_events`: employee, account, shift nullable, in_utc, out_utc, close_reason (`manual` / `auto` / `owner_edit`).

  It also adds indexes on (agency_user_id, start_utc) and (employee_id, out_utc IS NULL), plus a partial unique index allowing one open clock row per employee. History lands in the existing `actions` audit table.
- A router `service/shifts_api.py` on Phase 1's `agency_context` covers: list and create/edit/cancel shifts (owner), clock in/out (chatter session), "me" (current shift and open clock), "clocked-in now" (agency) and the timesheet rollup. An overlap with `multi_employee_shift` off is a 409.
- The first Settings consumers, under ADR-0008's Consequences ("a later plan that wires a consumer … must treat existing blobs as unreviewed and say how it handles them"). This Phase reads `time-tracking` and `sales.multi_employee_shift` only. When `enabled` is false, clock endpoints answer 409 "time tracking is off", and the Time tracking Panel's "not applied yet" note is lifted for the fields now applied.
- UI: replace the stub at `/employees/shifts` (drop the `nb()` in `nav.ts:163`) with the week calendar, the "Shifts" window and Shift Settings. Shift Settings edits the same `sales` key and stores nothing of its own. Add two Dashboard cards in `app/components/home/` and a "Clock in and out" entry in the top bar avatar menu.
- Rollups show hours and counts, plus earnings already recorded by `service/attribution.py` inside worked intervals, labelled "Recorded earnings". No payroll figure.

ASSUMPTION: auto clock-out is applied lazily: when any shifts endpoint is read or written, an open clock row older than `auto_clock_out_minutes` past its shift's end (or past the last activity when it has no shift) is closed with `close_reason=auto`. Rung 5: no new scheduler. Overturned if the owner needs the close to happen with nobody using the app.

ASSUMPTION: the clock-in reminder is an in-app toast through the existing `NotificationToaster`, with no email, push or OF send. Rung 5 and floor 2. Overturned by a request for out-of-app reminders.

ASSUMPTION: "Clock in and out" sits in the top bar avatar menu. Inventory §1.2 marks that placement G (guessed). Overturned by evidence of its real location, which the matrix records as unverified.

ASSUMPTION: the card titles are "My shifts" and "Current clocked-in employees", taken from the CSS classes `.myshifts` and `.clocked`. Inventory §6 item 7 says the exact titles are unknown. Overturned by evidence.

ASSUMPTION: repeat rules are weekly by weekday with "Never" or an end date, expanded into occurrences at read time over the requested week, in the shift's own `tz`. DST is handled by computing wall-clock times in `tz` and converting to UTC. Rung 1: §3.8 lists only weekly repeat. Overturned by evidence of other repeat kinds.

**Depends on:** Phase 1.

**Out of scope.** Payroll and payouts to employees. Applying Sales attribution rules to move credit between employees (Phase 4). Employee reports "Clocked hours" and its xlsx export (Phase 5 candidate, fed by this rollup). Platform split of hours ("Clocked hours are not differentiated by platform"). Native desktop notifications.

## Phase 3 — Share for Share inside this deployment's agencies

**Goal.** Restore S4S as a consent-based network bounded by the shared database. A Creator of any agency in this deployment can be discovered (when opted in), requested, accepted and scheduled for cross-promo posts. No agency can read beyond the S4S fields or act on another agency's OnlyFans account.

**Decisions already made (roadmap, verbatim).**
- "Discover S4S creators belonging to any agency in this same database/deployment, including the user's own agency. Never search across separate deployments or expose records from outside the database."
- "Use existing creator and agency records; do not scrape, import, or fabricate external creators."
- "Scope every list, request, schedule, and write to the authenticated agency and creator IDs. An agency can request a collaboration but cannot operate another agency's OnlyFans account."
- "Keep discovery limited to S4S-relevant profile fields … do not expose login credentials, proxy details, private notes, fan data, or unrelated account data."
- "Support the S4S workflow from the reference inventory: discovery, requests, creator-specific settings/limits, schedule, and status/history. Preserve the reference's posting caps and expiry behavior only where confirmed by the local source."
- "Add cross-agency isolation tests: same deployment can discover eligible records, unrelated tenant data remains hidden, and neither party can mutate the other's creator/account."
- "Make the UI explain that discovery is limited to agencies connected to this deployment; show an honest empty state when no other agency/creator is present."
- "Spec S4S as a consent-based, database-bounded network; implement tenancy before discovery UI."
- Inventory §3.6 (help article H262108, local source): Create Post has a caption of up to 5000 characters and up to 10 media from the Vault, up to 20 posts per creator, and "Set as Primary Post". "Limit" is 1/2/3 per day, with "Discovery Page Visibility". The schedule is a monthly calendar with statuses "In progress" / "Will be posted shortly" / "Completed" / "Canceled". Requests are "Accept" / "Skip" / "Decline" with "Received" / "Sent" tabs. Posts are removed after 24h.

**Current state.** Missing. `/share-for-share/[section]` is `NotBuiltYetRoute`, and the relay 403s any account outside the caller's agency (`_account_isolation_middleware`), which S4S discovery must cross on purpose. Reusable pieces: `Account` / `user_accounts` (creator to agency), `of_client.create_post` / `delete_post` with relay routes `POST /api/of/v2/posts` and `DELETE /api/of/v2/posts/{post_id}` (`server.py:7524,7541`), the Auto Post scheduler (`service/automations/auto_posts.py`) and the Vault picker.

**Work.**
- An ADR records the one deliberate exception to account isolation: a single discovery read returns only an allow-listed S4S projection of other agencies' opted-in Creators. Every other S4S write is checked with `assert_account_owned` on the caller's own Creator.
- A reversible migration adds four tables:
  - `s4s_profiles`: account_id, opted_in default false, discovery_visible, daily_limit 1–3, display fields.
  - `s4s_posts`: account_id, caption ≤5000, is_primary, at most 20 per account.
  - `s4s_requests`: from_account, to_account, status, timestamps.
  - `s4s_schedule`: request, slot, the posting account (always the caller's own), status, of_post_id, remove_at = posted + 24h.
- A router `service/s4s_api.py` on `agency_context`. The UI replaces the three `nb()` routes (`nav.ts:129-131`) with Discover creators, Requests (Received / Sent) and S4S schedule, plus an S4S Setting panel. The empty state reads, for example, "Only agencies on this Inflowwww deployment appear here".
- Publishing reuses the Auto Post path. Each agency's own Creator posts the partner's promo text on its own account and deletes it at `remove_at`. Both actions are behind a flag that is off by default. Acceptance uses mocked relay tests only.

ASSUMPTION: the cross-agency projection is display name, @username, avatar URL, the primary S4S post's caption, daily limit and opt-in state, and nothing else (no fan counts, earnings, proxy, notes or credentials). Rung 2 (the roadmap's "S4S-relevant profile fields") plus rung 4. Overturned by the owner's field list.

ASSUMPTION: the request lifecycle is pending → accepted / declined / skipped (skipped hides the request from the receiver only), and pending → cancelled by the sender. When an agency or Creator is disabled or opts out, it drops out of discovery, its pending requests become cancelled, and its future schedule slots become "Canceled". Already-published posts are left for the 24h removal. Rung 4: cancelling is additive and reversible by re-requesting. Overturned by the owner's lifecycle (the roadmap asks to confirm it before implementation, so it is listed under Needs the human).

ASSUMPTION: S4S posts carry text only (caption plus @mention of the partner). Vault media ids belong to one OF account and cannot be posted from another, and the transfer path is unknown, so the "up to 10 media" field is Not wired. Rung 2 (no guessed bodies). Overturned when a known body for cross-account media exists.

ASSUMPTION: live posting stays off (flag default off) until the owner runs the parked live check of `POST /posts` (connectors ticket 06) for one test account. Floor 2. Overturned by the owner enabling it after that check.

**Depends on:** Phase 1. It is independent of Phase 2.

**Out of scope.** Any cross-deployment or public directory. The app.infloww.com community. Importing creators. Fan data of any kind. Operating another agency's account. Media transfer between accounts. Analytics on S4S performance.

## Phase 4 — Apply the stored Settings

**Goal.** Make the Settings blobs that exist (`account`, `preferences`, `roles`, `sales`, `time-tracking`, `messaging`) take effect in their consumers, with server-side validation and a stated rule for blobs saved while they were inert. Keep Security, Billing and Balance actions Not wired.

**Decisions already made.**
- Roadmap: "Enforcing role permissions and data scope across API routes and UI actions; connect employee assignments to roles. Test denial at the server, not only hidden buttons."
- Roadmap: "Applying Sales attribution settings to employee/creator reporting and shift calculations."
- Roadmap: "Applying agency preferences, timezone, week start, agency name, time-tracking policy, and messaging translation settings consistently in the relevant screens and services."
- Roadmap: "Implementing real security features … only after a secure auth design and endpoints exist. Keep these unavailable rather than presenting a fake success state." It says the same of "Billing, invoices, payment methods, wallet top-up, and withdrawal flows".
- Roadmap: "validate blob schemas server-side, version settings where needed, and define rollback/default behavior before applying stored values to production actions."
- ADR-0007 (one blob per agency and tab, whole-blob replace, no key validation) and ADR-0008 (stored, not applied). This Phase supersedes ADR-0008 with a new ADR for the consumers it wires.

**Current state.** Settings storage was built (settings-tabs 28/28 on the branch), so this Phase is not blocked. Nothing reads the blobs. The roles blob is `{roles: PermissionRole[], assignments?: Record<employeeId, roleId>}` (`RoleSettingsTab.tsx:26-27`), with coined scope values and deny-all defaults (settings-tabs RUN.md › Assumptions 3). `/admin/translate` exists (`service/translate_api.py:222`), and the Composer's "Use translation" switch is per-Employee (`ComposerToolbar.tsx:393-401`). Phase 2 already wires `time-tracking` and `sales.multi_employee_shift`.

**Work.**
- Server-side blob validation: per-tab schemas in `settings_api.py`, a `version` key, and 400 on invalid input. The existing whole-blob replace is kept.
- Permissions: a `require_permission(page, op)` check on Phase 1's `agency_context` that resolves a chatter's mirror Employee to its role via `assignments`, applied to the relay routes behind each nav page the Permission editor lists. The nav's `chatterHidden` reads the same result. Tests cover a denied chatter at the relay, not only at the menu.
- Sales: Employee reports and Phase 2's rollups apply `exclude_welcome`, `exclude_of_fee` and the attribution radios in the read path only. Stored attributions in `service/attribution.py` are not rewritten.
- Preferences and account: the top bar timezone and report timezone come from `preferences`, the shift calendar and reports start on its week start day, and the agency name shows where Infloww shows it.
- Messaging: when the agency switch is off, the Composer's per-Employee translate switch is disabled with "Turned off by your organization", and the relay `/admin/translate` refuses chatter calls. The AI Translator prompt is passed to `/admin/translate` as its instruction.
- Each Panel's "Saved for your organization; not applied yet." note is removed for exactly the fields this Phase applies.

ASSUMPTION: blobs saved before this Phase are applied as stored, with no migration. Permission enforcement, though, ships behind a per-agency "Enforce role permissions" switch that is off by default, so a deny-all role saved while inert cannot lock a team out on upgrade day. Rung 4, answering ADR-0008's Consequences. Overturned if the owner wants enforcement on for everyone at once.

ASSUMPTION: Owner and the master role bypass role checks. Rung 1/3: `require_master` and the existing owner scope (`docs/routes.md` multi-agency paragraph). Overturned by the owner's role matrix (inventory §6 item 6 says it is unknown).

**Depends on:** Phases 1 and 2 (rollups and the time-tracking consumer).

**Out of scope.** 2FA enrollment and reset, password change, session listing and revocation, picture upload, Billing and invoices, wallet top-up and withdrawal, and Your Balance payouts. All stay Not wired (blocked: no backend). Language Settings (English/Spanish UI translation). Rewriting historical attribution rows.

## Phase 5 — Remaining confirmed parity gaps, ranked

**Goal.** Close the evidence-backed, backend-supported gaps the Baseline table marks partly or missing, in the order below, and park the rest with a concrete question.

**Decisions already made.**
- Roadmap: "Prioritize by evidence, user value, and available backend data. Prefer reusing existing analytics, audience, automations, creator/account, and employee services over creating parallel systems."
- Roadmap: "Implement only evidence-backed, backend-supported features; park unresolved APIs/policies."
- Roadmap: "Add auto-follow/auto-like only if supported by a documented and tested API with limits and a safe stop control."
- Roadmap: "The OF Manager plan has a parked trial-link uncertainty, so settle its request shape and availability first. Do not invent expiration fields or campaign bodies."
- Roadmap: "Verify the disagreement in the source notes about where Leaderboard belongs instead of silently choosing a placement."

**Ranked work.** Rank = evidence strength × data already in the relay.
1. **Employees surface** (§3.8; C[BS, H262104]). Views All / Activated / Deactivated, the deactivate action on the existing `Employee.is_active`, "By Creator" / "By role" filters (role from Phase 4), and the shift history columns from Phase 2. This needs no new table.
2. **Employee reports "Clocked hours"** and its export (§3.4, C[H262078]), fed by Phase 2's rollup. Export is CSV only, because xlsx would need a new dependency.
3. **Sales records** at `/analytics/sales-records` (§3.4, C[H529697]). Reads `service/attribution.py` rows with "Reassign" through the existing attribute-override path (migration `20260522_1300_phase_f_attribute_override.py`). Its sidebar placement is G, so it goes under Analytics and the matrix records "unverified".
4. **Employee groups and Organization Chart** (§3.8, C[H262104]). A reversible `employee_groups` table (agency-scoped tree) plus a group column. "Self and subordinates" data scope in Phase 4's permissions reads it.
5. **Notifications page** (§3.9). A `/notifications` overlay reusing `NotificationBell`'s source with the eight tabs. Tips waits on the parked `type` value (connectors ticket 31).
6. **Dashboard reclassification** (§3.1). Label the clone-only cards ("Earnings by channel", "Fans & subscriptions", "Daily earnings", "Creators overview") as Inflowwww extras and drop the fake trial banner if present. Nothing is removed.
7. **Fan reports** (§3.4). Label the "ours" panels (cohorts, spend distribution, Fan data CSV) and add the Infloww-evidenced retention table only if `fans` / `transactions` hold the fields.
8. **Growth checks** (§3.5). Smart lists: confirm spend/recency/status/tag rules against `smart_lists_api.py` and list missing rules. Auto-follow: confirm that limits and a stop control exist in `AutoFollowTab` / its relay route, or mark it read-only.

**Parked here, not built:**
- Free trial links "Create link" (connectors 38/46: `expired_at`) and Profile promotion "Start campaign" (no known body).
- Leaderboard. Global and country rankings need Infloww's customer base. ASSUMPTION below.
- Referrals (Infloww's own partner program).
- The platform selector for Fansly / mym / Fanvue (no inventory).
- Idle mode and the update prompt.
- Help center content.

ASSUMPTION: Leaderboard and Referrals are graded "intentionally different" and not built. Infloww's versions rank and reward across Infloww's global customer base, which a single deployment does not have, and a global ranking would contradict the deployment-bounded data rule the owner set for S4S. Rung 2 by analogy plus rung 5. Overturned if the owner wants an agency-internal leaderboard, which is an Inflowwww improvement and would be labelled as one.

ASSUMPTION: items 1–8 are built in rank order, and the spec may split this Phase into sub-phases if it exceeds one spec's ticket budget. Overturned by the owner reordering.

**Depends on:** Phase 2 (items 1–2), Phase 4 (items 1 and 4 scope), Phase 0 matrix (all).

**Out of scope.** Guessed OF bodies. Live OF checks. A new analytics service. Rebuilding Smart Messages, Scripts or Vault Pro (done). Removing any Inflowwww-only workflow.

## Phase 6 — Visual and functional sign-off matrix

**Goal.** Re-walk every supported route against the best available Infloww evidence and publish the final "matched / intentionally improved / not wired / unverified" matrix, so a reviewer can tell deliberate upgrades from mismatches.

**Decisions already made.**
- Roadmap: "Record exact differences in layout, typography, responsive behavior, labels, empty/loading/error states, dialogs, keyboard use, and navigation. Do not copy protected assets or user/account names."
- Roadmap: "Where the Infloww account ban means no fresh authenticated capture is possible, use saved code/screenshots, mark uncertainty, and avoid claiming verified 1:1 parity."
- Roadmap: "Phone layouts are Inflowwww improvements, not evidence-based 1:1 screenshots; mark them as such."
- Roadmap: "Keep improvements visibly documented … Do not remove stronger Inflowwww-only workflows just to imitate Infloww."
- Roadmap: "Re-run typecheck, lint, focused tests, backend tests, route checks, and screenshot walks for each phase."

**Current state.** Messages Pro (`docs/messages-pro-parity.md`) and Settings (`docs/settings-parity.md`) have signed-off parity docs on the branch. No route-wide matrix exists until Phase 0 writes `docs/infloww-parity-matrix.md`.

**Work.** Walk every route in `nav.ts` at 1440×900 and 390×844, light and dark, with the existing harnesses. Grade each matrix row and record the inventory version. Run every effort suite plus this plan's suite on one final commit. List the labelled improvements: the bounded S4S, shift tracking with audit history, explicit Not wired and stored-only labels, phone layouts and the Auto Post / Auto Story automations.

**Depends on:** Phases 0–5.

**Out of scope.** Fresh authenticated Infloww captures (the account is banned). Committing PNGs beyond the docs' existing screenshot sets. Any fix bigger than a label or a test path, which becomes a new ticket in the Phase that owns the area.

---

## Needs the human

- **Merge the branch, or keep it apart?** Merging `t3code/recreate-infloww-ui-prompt` (454 commits, one conflict in `Landing.tsx`) into `main` is Phase 0's first step under ASSUMPTION. Declining it means every Phase runs on the branch, and `main` keeps the stale messages-pro-parity map (23 done / 100 ready / 2 parked / 2 claimed).
- **Messages Pro ordering.** If the merge is declined, finishing messages-pro-parity on `main` is a separate `/spec-auto docs/plans/messages-pro-parity.md --execute` run, ordered before this plan, and it would redo work that is already done on the branch. With the merge, no such run is needed.
- **S4S policy, which the roadmap asks to confirm before implementation.** The cross-agency visible fields, the request/accept lifecycle, and what happens to requests and slots when an agency or Creator is disabled. Phase 3 proceeds on its ASSUMPTION lines until vetoed.
- **S4S live posting.** It stays off until the owner runs connectors ticket 06's live `POST /posts` check on a chosen test account.
- **Role enforcement rollout.** Phase 4 ships it per agency and off by default. Should it be on by default?
- **LLM spend for the AI Translator prompt.** Phase 4 meets "the AI Translator prompt is passed to `/admin/translate` as its instruction" with an LLM tier. gtx takes no instruction, so this is the only way to meet it. The tier adds per-message spend whenever an owner has written a prompt. It is paid by that Agency's own key under the existing daily soft cap, and gtx is the fallback. Approve the spend, or veto it, in which case the prompt stays "Not applied yet" (Phase 4 spec, translator ASSUMPTION).
- **A second merge for `ff715056`.** Phase 0 merges the pinned tip `4c9c7160`. The branch has since gained `ff715056`, the live session's 21 files (Composer, VaultPicker, MessageList, relay and others), so `main` stays behind the branch after Phase 0. Merging it is a separate decision and a separate merge.
- **Carried over from the original runs.** Connectors 06, 12, 19, 31, 38 and 46. Settings: Tab list icons, dark palette mapping, initials colours, the public-export path scrub. Messages Pro: the B11 page-bounded figures, if still open after the merge.

## Sources

- `nestStepsInflowCopy.txt` (root, untracked, read whole; not edited)
- `.scratch/infloww-parity-next-steps/HEADER.md`
- `docs/infloww-screens.md` (§1.2, §1.3, §3.1, §3.4, §3.6–§3.10, §6)
- `docs/routes.md`, `README.md`, `VISION.md`, `CONTEXT.md`
- `docs/adr/0001`–`0004` (main); `docs/adr/0005`–`0010` (branch; 0007 and 0008 read)
- `docs/plans/messages-pro-parity.md`, `.scratch/messages-pro-parity/map.md` (main, statuses counted)
- `docs/spec/plan-review.md`
- Branch `t3code/recreate-infloww-ui-prompt` (read-only via `git show` and its worktree): `.scratch/{messages-pro-parity,of-manager-connectors,settings-tabs,messages-pro-look-and-feel}/map.md`, the `RUN.md` files of messages-pro-parity, of-manager-connectors and settings-tabs, `service/settings_api.py`, `service/employees.py`, `service/auth.py`, `service/db/models.py`, `service/db/migrations/versions/`, `app/lib/nav.ts`, `app/app/**/page.tsx`, `app/components/{home,employees,settings,growth,stats}/`, `app/package.json`
- `git branch -a`, `git worktree list`, `git log --oneline main..<branch>`, `git merge-tree --write-tree main t3code/recreate-infloww-ui-prompt`
