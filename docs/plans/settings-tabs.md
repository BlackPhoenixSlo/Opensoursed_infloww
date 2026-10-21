# Goal plan: Settings tabs with Infloww's layout, wired to our backend

Make the 11 Settings tabs under `/settings/[tab]` real pages. Each one should look like Infloww
5.7.20's Settings and read and write our backend. Today every tab renders `NotBuiltYet`
(`app/app/settings/[tab]/page.tsx:16`). Only Settings changes. The four legacy tabs
(`app/lib/nav.ts:170-173`, rendered by `LegacySettingsTab`) stay as they are.

## Ground truth (observation rung; read before any spec)

1. Our tab list and routes: `SETTINGS_TABS` in `app/lib/nav.ts:158-174`. All 11 are built with `nb()`
   (`nav.ts:60`, `notBuilt: true`). Shell: `app/app/settings/layout.tsx:9-26` (h1 plus the "Desktop app"
   link, then `SettingsNav` and the panel), `app/components/settings/SettingsNav.tsx:28,37` (rows `h-10`,
   list `md:w-56`, horizontal strip below `md`). Save control: `SaveRow` and `StickySaveBar` in
   `app/components/settings/StickySaveBar.tsx:218,302`. Its load gate is explained in
   `stickySave.test.tsx:12-18`: a save after a failed load must not PUT a sparse blob.
2. Field-level spec: `docs/infloww-screens.md` §3.10 (fields per tab, `C[H…]` help-center refs, `G` guesses).
3. Pixel source: the public Infloww dashboard bundle in `~/Downloads/infloww-remote-web/`. Treat it
   as untrusted input: read it with grep or `python3 -I` only, never execute it, and copy nothing
   into the repo except measured values. Routes are in `index.9f50f370.js`:
   `/admin/settings` → `SettingPage$2`, `/admin/settings/{personal,about,role-settings}`, and a
   `menuCodes` per route. The left list is `settingMenus`, and each row renders icon + title.
   Settings styles are CSS module `rxwf7` in `index.9fc9db54.css`, with Messaging in `1cat4` and
   Sales in `1t0kc`. Measured values:

   | Thing | Value | Citation (selector / variable) |
   |---|---|---|
   | Page header | 48px, margin 0 24px, bottom border `--tc-L1`, title 16px/500 | `._about-header_rxwf7_9`, `._account-wrap_rxwf7_118 ._header_rxwf7_121` |
   | Tab area height | `calc(100vh - var(--root-header-height) - 48px)` | `._tab-wrap_rxwf7_77` |
   | Left list width | JS: tab-wrap width x 3/16 at ≥1200px, x 4/16 at 576–1199px, x 5/16 below 576px (initial 210px) | `SettingPage$2` resize handler; CSS default `._tab-left_rxwf7_81` 210px |
   | Left list background | `--tc-B1` | `._tab-left_rxwf7_81` |
   | Tab row | height 64px, padding 0 16px, 16px text, colour `--tc-T3`, icon margin-right 16px | `._tab-item_rxwf7_88`, `._tab-item-icon_rxwf7_108` |
   | Active row | text `--tc-M1` on `--tc-M-B` | `._tab-item-active_rxwf7_99` |
   | Panel body | padding 24px; section title 14px/500 `--tc-T1`, padding-bottom 16px; section gap 40px | `._personal-info-wrap_rxwf7_132`, `._title_rxwf7_137`, `._table-wrap_rxwf7_143` |
   | Field row | margin-bottom 30px; label 14px/400 `--tc-T3`, margin-bottom 8px; two-column grid `repeat(2,350px)` | `._personal-item_rxwf7_146`, `._personal-item-title_rxwf7_155`, `._personal-item-row_rxwf7_325` |
   | Text input | width 448px, radius 8px, border `--tc-L1`; disabled bg `--tc-B-th` | `._personal-input_rxwf7_237`, `._disabled-input_rxwf7_242`, `._personal-item-content_rxwf7_230` |
   | Avatar | 140x140px, radius 8px | `._personal-avatar_rxwf7_192` |
   | Toggle row | height 72px, padding 0 16px, radius 4px, border `--tc-L1`; title 14px, desc 12px `--tc-T3` | `._switch-theme_rxwf7_303` |
   | Bordered card (translation) | border `--tc-L1`, radius 8px, margin 24px, padding 24px; title 14px/600; tip 12px/20px `--tc-T2` | `._translation-item_rxwf7_369` |
   | Messaging card (newer) | padding 12px 16px, radius 12px, bg `--surface-level-00-emphasis-00`, margin-top 16px | `._translation-item-content_1cat4_4` |
   | About | logo 88x88px, 24px below; beta box 760px wide, padding 16px, radius 4px | `._about-logo_rxwf7_31 img`, `._join-beta-wrap_rxwf7_40` |
   | Learn-more link (Sales) | `#de6d46`, 14px strong | `._learn-more_1t0kc_5` |
   | Shell vars | `--nav-width` 256px (60px collapsed); `--root-header-height` 36+8x2+0 = 52px; `--main-title-height` 49px; `--main-content-height` `calc(100vh - root-header - main-title)` | `body`, `body._navCollapsed_rxwf7_*`, `--controls-generous-min-height` 36px, `--sizing-named-micro` 8px, `--main-banner-height` 0px |
   | Radii | `--ui-radius-small` 12px, `--ui-radius-medium` 16px, `--surface-01-radius` 12px | `.theme-light` / `.theme-dark` |
   | Font | Settings inherits `body{font-family:"RobotoRegular",…}`. Newer `hb-design` parts use `"Suisse Int'l"` via `--typography-text-body2-base` (400 14px/1.14), `-body1-base` (400 16px/1.25), `-heading3-strong` (500 24px) | `body`, `--typography-*` |
   | Colours (light, `:root`) | `--tc-B-nav` #ffffff · `--tc-B1` #f5f5f5 · `--tc-T1` #151515 · `--tc-T2` #666666 · `--tc-T3` #999999 · `--tc-M1` #3467ff · `--tc-M-B` #eff4ff · `--tc-L1` #e6e6e6 · `--tc-D1` #ff7c71 · `--tc-B-th` #fafafa | `:root` |
   | Colours (dark) | `--tc-*` has no dark value in the CSS. Use the sampled dark palette in `docs/infloww-screens.md` §1.4 [PAL] (canvas #262626, side panel #232323, border #333, selected #353535, accent #4166f6, red #f0483e) and `.theme-dark` `--element-emphasis-00/01/02` (#fff, 62%, 38%) | §1.4, `.theme-dark` |

4. Real screenshots: `~/Downloads/infloww-shots-2026-10-12/` (six PNGs). They show the dark desktop
   shell (Messages Pro, OF Manager) and no Settings page. They confirm the dark theme and nothing
   more. They contain the user's real handle and fan names: read them, never copy a name.
5. Backend today (verified; corrects the draft in `docs/NEXT_SESSION_SETTINGS_UI.md` §3):
   - `GET /auth/me` (`service/auth.py:564`; `AuthResp` at `:489` = user_id, username, impersonating)
     and `POST /auth/logout` (`:555`). There is no rename, password, sessions-list or 2FA route.
     One cookie session slides on `users.last_seen_at` (`:543-545`).
   - `GET /admin/employees` (`service/employees.py:95`): id, display_name, color, is_active,
     chatter_id, created_at. **No role field** (the draft's "roles" is wrong).
   - `GET/PATCH /api/of/v2/users/me` (`server.py:2044,6859`) is the OF model's profile, **not** the
     agency account (the draft's Your Account wiring is wrong).
   - Referral `GET …/payments/referrals/balance` (`server.py:6926`) and
     `GET …/payouts/requests/referral` (`:6931`). Both are per selected model.
   - Translate: only `POST /admin/translate` (`service/translate_api.py:222`), Google gtx, with no
     prompt and no config. Attribution: no config route (`/admin/lanes`, `server.py:3593`, is
     concurrency). Version: `app/package.json:3`, shown by `Sidebar.tsx:32,158`.
6. House pattern for stored config, which `user_settings` follows:
   - Table `UserLlmKey` (`service/db/models.py:2669-2707`): `user_id` FK CASCADE + a second key as
     PK, `updated_at`. Migration `service/db/migrations/versions/20260820_0100_user_llm_keys.py`.
     `init_db` creates new tables with `create_all` (`service/db/engine.py:82-95`).
   - Route `service/tenant_keys_api.py`: prefix router (`:32`), `_require_user()` returns 401
     (`:35-42`), GET/PUT (`:45,61`).
   - JSON-as-Text upsert in `webhook_config_api.py:98-115`, returning `{config}` (`:80-91`).
     Registration: `server.py:89` (import) and `:230` (`include_router`).
   - Not the pattern: `/admin/secrets` (`server.py:550,558`) is a master-only file store;
     `/admin/webhooks` (`:9174-9192`) is an unrelated list.

## Constraints (binding)

- Infloww's geometry; Infloww's colours via `--if-*` tokens. Decision: one `--if-*` block in
  `app/app/globals.css` (light under `html[data-theme="light"]`, `:75`; dark beside the `@theme` defaults,
  `:12`). Values come from the Ground-truth table. Geometry also lives there (e.g. `--if-tab-h: 64px`).
  Only components under `app/components/settings/` that this plan creates read them.
- Font stays `--font-sans` (`globals.css:41`). Suisse Int'l is licensed and served from Infloww's host,
  so it is not loaded. This is a recorded visual gap.
- YAGNI backend: exactly one table `user_settings` (`user_id`, `tab`, `config_json`, `updated_at`) and
  `GET/PUT /admin/settings/{tab}`. No per-field routes, no roles table, no 2FA, no sessions list.
  A control with no backend renders disabled with the tooltip "not wired" and never fakes success.
- Stored settings are not enforced or consumed elsewhere in this plan (roles, attribution, translation
  toggle). Each such panel shows "Saved for your organization; not applied yet."
- No backend deletions. Nothing outside `app/`, `docs/`, `service/` changes, except new `scripts/settings-check/`.
- Every Phase ships vitest for each new component (`app/components/settings/*.test.tsx`; house style
  `@testing-library/react`, `renderWithProviders` from `app/test-utils.tsx:30`, relay mocked at `fetch`)
  and keeps green: `pnpm -C app typecheck`, `pnpm -C app lint` (0 errors),
  `ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run`, `./venv/bin/python service/tests/test_settings_api.py`.
- `scripts/check-public-export.sh` green on the files this run touches. The script targets the public
  tree. Against this private tree it exits 1 by design, and in a worktree it exits 2 (`:19`, where
  `.git` is a file). So each Phase runs it on a throwaway tree:
  `T=$(mktemp -d); git -C "$T" init -q; git diff --name-only --diff-filter=AM main... | rsync -R --files-from=- . "$T"; git -C "$T" add -A; scripts/check-public-export.sh "$T"`
  must exit 0. Fixtures use synthetic names only.
- The unattended run has no network: no `pnpm install`, no new dependency, and the check loop
  aborts every non-localhost request.
- Each spec starts with a measured gap table: Ground-truth selector and value → our `file:line` → gap
  → change. A value not in the table is an `ASSUMPTION:`.

## Check loop (binding for every UI ticket)

Use the `scripts/of-mirror-check/*.py` style, not `scripts/ui-shots.sh`. `ui-shots.sh` is
Messages-Pro-shaped: its shot list is fixed at `:28-29`, and it needs the venv relay, Chromium and a
temp-DB stack. of-mirror-check fakes login with Playwright routes and no relay (`README.md`), and
`writes.py:44,58` already records relay writes and asserts their bodies, which is exactly what each
Phase accepts on.

`scripts/settings-check/walk.py` (`python3 -I`, against `cd app && npx next dev --webpack -p 3091`):
- It mocks `/auth/me`, `/chatter/me*`, `/admin/employees` (synthetic "Alpha One", "Beta Two",
  "Gamma Three"), `GET /admin/settings/{tab}` from an in-memory dict, and the referral balance and
  payouts. It aborts off-host requests.
- It walks all 11 `SETTINGS_TABS` hrefs at 1440x900, and at 390x844 for the strip.
- It fails on a `NotBuiltYet` marker, a console error, horizontal overflow, or a computed style
  (`getComputedStyle`) off its token: tab row 64px, left list 18.75% of the tab area at 1440,
  panel header 48px, active row colour = `--if-accent`.
- It records every non-GET request as `(method, path, json body)`. Each Phase names the exact list
  the mock must receive.
- It writes `/tmp/settings-shots/settings-<tab>.png` and `settings-report.json`, and exits
  non-zero on a failure.

A UI ticket is done when:
1. `walk.py` exits 0.
2. The implementer has Read the ticket's PNG, listed visual diffs against the Ground-truth table
   (position, size, label, order, missing element), fixed them and re-run. Up to three rounds;
   the rest goes into the ticket as `VISUAL GAP:`.
3. The final PNGs are copied to `docs/screenshots/settings-<tab>.png` (synthetic data) and committed.

## Phase 0 — shared shell, tokens, settings blob

Target: the Infloww Settings frame around all 11 tabs, plus the one store later Phases write to.

Decisions:
- `--if-*` block in `globals.css` (Constraints): geometry plus colour slots `bg`, `list-bg`, `fg`,
  `fg-2`, `fg-3`, `accent`, `accent-bg`, `line`, `danger`, `input-disabled`.
- `layout.tsx` gets a 48px header: "Settings" at 16px/500, and on the right the kept "Desktop app" link
  (ours) plus a close ✕ (`router.back()`). The tab area below is
  `calc(100dvh - <our top bar> - 48px)`, and each column scrolls on its own.
- `SettingsNav.tsx`, at `md` and up: 64px rows, padding 0 16px, 16px text, a lucide icon with a 16px
  gap, `--if-list-bg`, active row `--if-accent` on `--if-accent-bg`. Width comes from a container
  query on the tab area: 25% by default, 18.75% at ≥1200px. Below `md` the current strip stays
  (`docs/routes.md`). "Legacy" is unchanged.
- New `SettingsPanel.tsx` provides the parts every tab is built from:
  - the 48px panel header and 24px body padding
  - `Section`: title 14px/500, 40px gap
  - `Field`: label 14px `--if-fg-3`, 8px/30px gaps, 448px inputs
  - `ToggleRow`: 72px
  - `NotWired`: a disabled control with the "not wired" tooltip
- New `app/lib/settingsBlob.ts`: `useSettingsBlob(tab)`, a TanStack Query wrapper over
  `relay.get/put` (`relay.ts:160,194`). Save goes through `SaveRow` with the `configLoaded` gate, and
  a PUT always sends the full object.
- `[tab]/page.tsx` maps each href to its panel in one `SETTINGS_PANELS` record. Unmapped tabs keep
  `NotBuiltYet` until their Phase lands.
- Backend:
  - Model `UserSetting` (`user_settings`) next to `UserLlmKey`: `user_id` FK CASCADE + `tab` as
    composite PK, `config_json` Text, `updated_at`. Migration `…_user_settings.py` modelled on
    `20260820_0100_user_llm_keys.py`.
  - `service/settings_api.py`: `APIRouter(prefix="/admin/settings")` with `_require_user()` as in
    `tenant_keys_api.py:35-42`. `GET /{tab}` → `{tab, config}` (`{}` when absent).
    `PUT /{tab}` takes a JSON object, upserts as in `webhook_config_api.py:98-115`, and returns `{tab, config}`.
  - Tab allow-list: `account`, `preferences`, `roles`, `sales`, `time-tracking`, `messaging`. Other
    tab → 404, non-object body → 400, over 64 KB → 413.
  - Registered in `server.py` beside `_webhook_config_router`.

Acceptance:
- `service/tests/test_settings_api.py` (plain-assert, `_harness` first, as
  `test_llm_tenant_keys.py:29-31`). Cases: empty GET returns `{}`; PUT/GET round-trips; unknown tab
  → 404, list body → 400, 65 KB body → 413, no session → 401; two users are isolated; deleting a
  user removes its rows.
- `SettingsShell.test.tsx`: 11 rows in nav order, active row marked, ✕ calls `back`, legacy hidden
  with the flag off. `settingsBlob.test.ts`: the PUT carries the full object; after a failed load
  Save is disabled and no PUT goes on the wire.
- `walk.py` exits 0 on geometry for all 11 tabs (unbuilt panels allowed in Phase 0 only). The mock
  receives no write.

## Phase 1 — Your Account, Your Preferences

Target: §3.10 rows 1–2 (`C[H262101, H262077, H451172]`).

Decisions:
- Your Account, Personal section:
  - Picture is a 140px initials avatar (radius 8), with upload `NotWired`.
  - Username is read-only from `GET /auth/me`, with "Edit" `NotWired` (there is no rename route).
- Your Account, "Agency info": Picture as above. "Agency Name" goes to blob `account`
  `{agency_name}`. Nothing touches `/api/of/v2/users/me` (Ground truth 5).
- Your Preferences: "Report time zone" ("Your preferred time zone for Creator and fan reports"),
  "Time zone", "Week start day" (Monday/Sunday) and "Language Settings" (English / Spanish) go to
  blob `preferences` `{report_tz, tz, week_start, language}`. Zones come from
  `Intl.supportedValuesOf("timeZone")`. No consumer yet.

Acceptance:
- `YourAccountTab.test.tsx`: username shown, Edit disabled, save PUTs `{agency_name}`.
  `PreferencesTab.test.tsx`: four fields, and save sends all four keys.
- `walk.py`: saving "Synthetic Agency" makes the mock receive exactly
  `PUT /admin/settings/account {"agency_name":"Synthetic Agency"}`. Week start Sunday makes it receive
  `PUT /admin/settings/preferences` with `"week_start":"sunday"` plus the other three keys.

## Phase 2 — Security (organization), Security (personal)

Target: §3.10 rows 3–4 (`C[H463402]`; personal fields are `G`).

Decisions:
- Org: the "Two-factor authentication" `ToggleRow` is `NotWired`. We have no 2FA, and the toggle
  is not stored, so a saved "on" can never mislead anyone.
- Org: the employee table comes from `GET /admin/employees` with columns Name / 2FA status /
  Last login / Operations. 2FA status and Last login show "—", "Reset" is `NotWired`, and
  disabled employees are greyed.
- Personal: a "Current session" card (username from `/auth/me`) with "Sign out" →
  `POST /auth/logout`. "Change password" and "Enable 2FA" are `NotWired`.
- No blob tab for either.

Acceptance:
- `SecurityOrgTab.test.tsx`: 3 rows, toggle disabled with its tooltip, no PUT.
  `SecurityPersonalTab.test.tsx`: Sign out POSTs `/auth/logout`.
- `walk.py`: org lists "Alpha One", "Beta Two", "Gamma Three". Clicking the 2FA toggle records no
  write. Sign out makes the mock receive exactly `POST /auth/logout`.

## Phase 3 — Role Settings, Sales Settings

Target: §3.10 rows 7–8 (`C[H262098, H262080]`).

Decisions:
- Roles table: Name / Description / Operations ("Edit", "Set Permissions"), plus "+ Add Role" (modal:
  "Role Name", "Description", "Submit"). Owner and Admin are built in and cannot be deleted.
- Permission editor: tabs "Operations" / "Growth" / "OF Manager". Pages are derived from the
  `SIDEBAR` groups in `app/lib/nav.ts`, so they cannot drift. One radio per page, plus a data scope
  of "All data" / "Self and subordinates" / "Data about self". Each employee's role is a select.
- Roles go to blob `roles`
  `{roles:[{id,name,description,permissions:{href:bool},scope}], assignments:{employee_id:role_id}}`.
  No roles column on `employees`.
- Sales: "Exclude welcome messages", "Exclude the 20% OnlyFans fee", "Multiple employees per
  shift", and attribution radios:
  - Messages = Shift schedule / Message sender / Converters
  - Posts and Tips = Shift schedule / Converters
  - Subscriptions, Streams & Referrals = shift schedule with a chatter opt-in
  
  Stored in blob `sales`. "Learn more" (styled as `._learn-more_1t0kc_5`) is hidden until a docs page exists.

Acceptance:
- `RoleSettingsTab.test.tsx`: add, edit permissions, built-ins cannot be deleted, assignment saved.
  `PermissionEditor.test.tsx`: tabs and pages equal the nav groups.
  `SalesSettingsTab.test.tsx`: radio matrix, full-object save.
- `walk.py`: adding "Synthetic Role" makes the mock receive exactly one
  `PUT /admin/settings/roles`, with Owner, Admin and Synthetic Role in `roles`. "Message sender"
  makes it receive `PUT /admin/settings/sales` with `attribution.messages == "sender"`.

## Phase 4 — Time tracking, Messaging settings

Target: §3.10 rows 9–10 (`C[H300963, H262030, H673161]`).

Decisions:
- Time tracking: a read view with "Edit". Edit mode shows the enable toggle,
  "Auto clock out time" (minutes, min 1) and the clock-in reminder, with "Save" / "Cancel". Saved
  to blob `time-tracking` `{enabled, auto_clock_out_minutes, clock_in_reminder}`. Cancel restores
  the loaded values and sends nothing.
- Messaging (`1cat4` card geometry): an "AI translation" card with the toggle "Enable AI
  translation in Messages Pro for employees in your organization", and an "AI Translator prompt"
  card with "Edit" › textarea › "Save". Saved to blob `messaging` `{ai_translation, prompt}`.
  `/admin/translate` does not read it.

Acceptance:
- `TimeTrackingTab.test.tsx`: 0 minutes rejected, Cancel sends nothing.
  `MessagingSettingsTab.test.tsx`: toggle and prompt save.
- `walk.py`: Edit → 30 → Save makes the mock receive exactly
  `PUT /admin/settings/time-tracking {"enabled":…,"auto_clock_out_minutes":30,"clock_in_reminder":…}`.
  Edit → Cancel records nothing. The prompt "synthetic prompt" makes it receive
  `PUT /admin/settings/messaging` containing it.

## Phase 5 — Billing, Your Balance, About Inflowwww

Target: §3.10 rows 5, 6, 11 (`C[H262093]`, `[CL]`; Balance and About fields are `G`).

Decisions:
- Billing is static, with no blob. Subtabs "Infloww subscription" / "AI Copilot", a plan card
  "Inflowwww — self-hosted, free", and an invoice table with the empty state "No invoices".
  "Pricing plans", "Update card", "Cancel subscription", "Billing information" and "Make a Payment"
  are `NotWired`.
- Your Balance: four cards (Total earnings / Available to withdraw / Pending earnings / Withdrawn)
  from `…/payments/referrals/balance`, plus payouts from `…/payouts/requests/referral`, for the
  selected model. In all-models scope it shows "Select a model to see its balance" and fetches
  nothing. A missing field renders "—".
- About: an 88px logo, "Version {version}" from `app/package.json`, and links to "Desktop app"
  (`/download`) and the licence. No beta box, no build hash.
- When this Phase ends, remove `NotBuiltYet` from `[tab]/page.tsx` and `nb()` from `nav.ts:159-169`.

Acceptance:
- `BillingTab.test.tsx`: all actions disabled, empty table. `BalanceTab.test.tsx`: cards from a
  synthetic balance, "—" for a missing field, no fetch in all-models scope. `AboutTab.test.tsx`:
  version equals `package.json`.
- `nav.test.ts` gets a case like the OF Manager one (`:78-83`): no non-legacy `SETTINGS_TABS` entry
  is `notBuilt`.
- `walk.py`: Balance in scope `model:acc1` shows the four synthetic cards. All three tabs record no write.

## Phase 6 — sign-off

Target: all 11 tabs are done, verified and recorded.

Decisions:
- `docs/settings-parity.md` holds one row per tab: Ground-truth evidence → component → wired / not
  wired / visual gap. It lists every `NotWired` control and every `VISUAL GAP:`, the font included.
- `docs/NEXT_SESSION_SETTINGS_UI.md` §3's table is replaced by a pointer to this plan and the parity
  doc, with the Ground truth 5 corrections.

Acceptance:
- `grep -rn NotBuiltYet app/app/settings` is empty. Every Constraints gate is green.
- `walk.py` exits 0 on all 11 tabs at 1440x900 and 390x844. Its write list equals the union of the
  Phase 1–4 lists. The 11 `docs/screenshots/settings-<tab>.png` files are committed.
