# Settings parity

Inflowwww's eleven Settings tabs graded against Infloww 5.7.20's Settings. The one live Infloww Settings capture is Time tracking (the w5-a live captures of 2026-10-19, `.scratch/infloww-live/03-06`, DPR 2 at 1512x944); page-parity ticket 20 measured the frame and the dark palette there. Every other tab is graded against the Dashboard bundle selectors (CSS modules `rxwf7`, `1cat4`, `1t0kc`, `1r0jx`, `6tj53`, `1dq9x` and the bundle's components) and the help-center reconstruction in `docs/infloww-screens.md` §3.10 (`C[H…]` refs; `G` marks a guess). The plan is `docs/plans/settings-tabs.md`; the specs are `docs/spec/settings-tabs/phase-00` to `phase-06`. The committed look is `docs/screenshots/settings-<tab>.png` (1440x900, from the final Settings walk, ticket 26). Every Blob tab's values are stored and read back. Since ADR-0012 each field is Applied by the screen or Relay route it describes (Permission roles only under Role enforcement), except the Agency name, Language and the AI Translator prompt, which stay Not applied yet (ADR-0008).

## Backend corrections

These replace §3 of the deleted draft runbook `docs/NEXT_SESSION_SETTINGS_UI.md` (removed in `b07a433d`, not recreated). They are Ground truth 5 of `docs/plans/settings-tabs.md`, checked against the Relay on this tree; the draft's wiring must not come back.

- No role field on `/admin/employees`: `GET /admin/employees` (`service/employees.py:95`) returns id, display_name, color, is_active, chatter_id and created_at. Roles and their Employee assignments live in the `roles` Settings blob, not in an Employee column.
- `/api/of/v2/users/me` (`GET` `service/server.py:2047`, `PATCH` `:6862`) is the OF model's (Creator's) profile, not the Agency account. Your Account never calls it; the Agency Name is the `account` Settings blob.
- No rename, `password`, sessions-list or `2FA` route: `service/auth.py` has only `/auth/register`, `/auth/login`, `/auth/logout` (`:565`) and `/auth/me` (`:574`, `AuthResp` = user_id, username, is_admin, impersonating). Username Edit, Change password, Enable 2FA, the organization 2FA switch and Reset are therefore Not wired.
- `referrals/balance` and payouts are per Creator: `GET /api/of/v2/payments/referrals/balance` (`service/server.py:6929`) and `GET /api/of/v2/payouts/requests/referral` (`:6934`) answer for the selected model (`X-Account-Id`), so Your Balance fetches nothing in all-Creators scope.
- `/admin/translate` (`service/translate_api.py:253`) has no prompt: it is the Google gtx batch translator. Of the `messaging` blob it reads only `ai_translation`, and refuses a chatter 403 while that is off (ADR-0012).
- No attribution config route: `/admin/lanes` (`service/server.py:3596`) is send concurrency, not sales attribution. Sales attribution rules live in the `sales` Settings blob.
- The version shown on About comes from `app/package.json` (`version`), the same value the Sidebar footer shows; there is no build hash.

The one store this effort added is `user_settings` behind `GET/PUT /admin/settings/{tab}` (`service/settings_api.py`, allow-list `account`, `preferences`, `roles`, `sales`, `time-tracking`, `messaging`; ADR-0007).

## Not wired

Every Not wired control in the Settings Panels: each `<NotWired` and the `notWired` `ToggleRow` in the non-test files under `app/components/settings` (eleven uses, all eleven named by the plan; no other use exists). Each renders disabled with the tooltip "not wired" and never fakes success.

- `account` — Upload picture (the camera veil over each picture, shown on hover): no picture upload or picture store for the User or the Agency in the Relay (`YourAccountTab.tsx`).
- `account` — Edit: no rename route; the Username comes read-only from `GET /auth/me` (`YourAccountTab.tsx:64`).
- `security-org` — Two-factor authentication: no 2FA route and no 2FA state in the Relay (`ToggleRow notWired`, `SecurityOrgTab.tsx:28`).
- `security-org` — Reset: no per-Employee 2FA reset route, and `/admin/employees` carries no 2FA field (`SecurityOrgTab.tsx:52`).
- `security-personal` — Change password: no password route under `/auth` (`SecurityPersonalTab.tsx:37`).
- `security-personal` — Enable 2FA: no 2FA enrolment route (`SecurityPersonalTab.tsx:40`).
- `billing` — Pricing plans: no billing backend; self-hosted Inflowwww has no plan or pricing route (`BillingTab.tsx:31`).
- `billing` — Update card: no payment-method route (`BillingTab.tsx:32`).
- `billing` — Cancel subscription: no subscription route (`BillingTab.tsx:33`).
- `billing` — Billing information: no billing-profile route (`BillingTab.tsx:34`).
- `billing` — Make a Payment: no invoice or payment route (`BillingTab.tsx:39`).

## Visual gaps

Each line is carried verbatim from its ticket in `.scratch/settings-tabs/issues/`. "Owner: the human (see Needs the human)" points at the Needs the human entries in `.scratch/settings-tabs/map.md` (Tab list icons, the dark palette mapping, the Assistant launcher, the initials colours).

### Open (ticket 26's final walk, which merged the per-ticket lines; re-graded by page-parity tickets 20 and 21)

VISUAL GAP: the font stays `--font-sans` (Sora), not RobotoRegular or the licensed Suisse Int'l (plan Constraints, gap row 15) (ticket 05; tickets 02, 03, 08, 11, 17-22, 25 merged). Owner: ticket 27 (plan-decided).

VISUAL GAP: the two-column field grid `repeat(2,350px)` (`._personal-item-row_rxwf7_325`) is not built. The bundle defines the class but no component reads it (its only occurrence is the CSS-module map), and Infloww's Account and Preferences render one `personal-item` per row, so the one-field rows match what Infloww draws (page-parity ticket 21 checked the bundle). Owner: none.

VISUAL GAP: the Tab list's icons are lucide stand-ins for Infloww's set (ticket 20 picked the closest lucide glyph per tab at a 1.5 stroke; the 20px size is ours); Infloww's own SVGs are not copied (ticket 05). Owner: the human (see Needs the human).

VISUAL GAP: the app-wide help launcher now docks where Intercom's bubble does (`app/components/assistant/AssistantWidget.tsx:244`, `fixed bottom-5 right-5`, page-parity ticket 22), so it no longer covers the Tab list; it sits over the Panel's bottom-right corner on every Settings tab (ticket 05). Owner: none.

VISUAL GAP: the Personal and Agency pictures' initials colours (`--if-accent` on `--if-accent-bg`) are ours, not measured (ticket 08). Owner: the human (see Needs the human).

VISUAL GAP: the Edit button (32px `IF_BTN`) makes Messaging card 2's title row taller than card 1's (22px switch); the bundle's `HBButton size="moderate"` height is unmeasured (ticket 21). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the committed PNG shows only the read view; the open editor is checked only for 390x844 overflow (ticket 21). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the `1dq9x` amount type may belong to the wallet top-up screen rather than Settings (the spec's own ASSUMPTION), so the 14px/500 label and 32px/600 amount are unconfirmed for this screen (ticket 23) (ticket 25). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the committed `settings-balance.png` is the walk's All-Creators view ("Select a creator to see its balance"); the amount block and the payout row are seen only in `/tmp/settings-shots/settings-balance-model.png`, which is never committed (Cross-spec decision (e)) (ticket 25). Owner: ticket 27 (carried verbatim).

VISUAL GAP: only Time tracking has a live Infloww capture (`.scratch/infloww-live/03-06`); every other tab is graded against the bundle selectors (page-parity ticket 20). Owner: the human (more live captures).

### Closed by page-parity tickets 20 and 21 (2026-10-19)

Ticket 20 (the Settings frame, measured on the live Time tracking capture 03):

- The dark palette is measured, not sampled: header, Panel and fields #151515, Tab list #262626, rules #444, table head #353535, T1/T2/T3 #d9d9d9/#b8b8b8/#999, switch off rgba(255,255,255,.25), on #2d74ff.
- The "Desktop app" link left the Settings header for About (owner decision 7); the header is the title and the close button over a full-width rule.
- Settings docks the locked 60px rail, so the Tab list sits where Infloww's does.
- Edit / Cancel / Save on Time tracking and Messaging are Infloww's 32px buttons (`IF_BTN`, `IF_BTN_PRIMARY`), no Save icon.
- Disabled switches are at opacity .65 and the 44x22 track and 18px knob match the capture.

Ticket 21 (the tabs' controls and layouts, from the bundle selectors):

- Save is `IF_BTN_PRIMARY` in the Panel header on Your Account, Your Preferences, Sales Settings and Role Settings (Account's no longer sits at the fold); the Not applied yet note and the Load gate note stay in the body.
- Every select is ticket 00's `IfSelect` (antd's select: custom chevron, listbox), 448px, the time zones searchable; the Employee role selects are 200px.
- Not wired buttons are `IF_BTN`, disabled, titled "not wired" (Billing's included).
- Radios are antd's: a 1px #444 ring on #151515, checked an M1 ring round an 8px dot.
- Account: no Upload button; a not-wired camera veil over the 140px picture on hover; the read-only Username is B-th #1a1a1a (`--if-input-readonly`).
- Security (organization): the Employees table has the #353535 head and 13px cells.
- Security (personal): three bordered cards; "Current session" is the card's own 14/600 title with a 12px/20px tip and Sign out (`IF_BTN`) at the right.
- Billing: `IfTabs` line tabs, the 75px row with "Make a Payment" at the right above the invoice table, "No invoices" as `EmptyState`.
- Balance: the 360px centred amount block (14/500 label, 32/600 amount), the other three figures in a row under it, "Transaction history" (16/600) with Infloww's status colours, the no-Creator state as `EmptyState`.
- Role Settings: "Roles" and "Employee roles" are 16/500 table titles 16px over their tables, 32px apart; Delete is #ff7c71; Employee roles is an Employee / Role table; "+ Add Role" and Submit are `IF_BTN_PRIMARY`.
- Permission editor: its own Panel, a 20px back chevron before the role name and Save at the right of the 48px header, `IfTabs` for its pages.
- Messaging: the prompt is always a read-only textarea (100-200px, sized to its text) with an `n/2000` counter until Edit.
- About: the centred 88px tile on #262626 with T1 text, "Version", a 760px desktop-app box with "Download", the licence link under it.

### Plan-decided departures and the font

VISUAL GAP: Settings stays on `--font-sans` (Sora), while Infloww uses "RobotoRegular" for Settings and the licensed "Suisse Int'l" for its `hb-design` parts, which is served from Infloww's host and not loaded here (plan Constraints). Owner: none, plan-decided.

VISUAL GAP: below `md` the Tab list is a horizontal strip above the Panel, where Infloww keeps a 5/16 column below 576px (`SettingPage$2` resize handler) (plan Phase 0). Owner: none, plan-decided.

VISUAL GAP: Sales Settings hides the "Learn more" link (`._learn-more_1t0kc_5`) until a docs page exists (plan Phase 3). Owner: none, plan-decided.

VISUAL GAP: About has no beta box (`._join-beta-wrap_rxwf7_40`) and no build hash, only the version from `app/package.json`; the box's place holds our desktop-app download box (plan Phase 5, page-parity ticket 21). Owner: none, plan-decided.

VISUAL GAP: the Tab area height is computed from our top bar (`calc(100dvh - <our top bar> - 48px)`), not from Infloww's 52px `--root-header-height` (plan Phase 0). Owner: none, plan-decided.

### Per-ticket source lines (history: merged into the lists above by ticket 26; their status is the Open and Closed lists above)

From ticket 02:

VISUAL GAP: the font stays `--font-sans` (Sora), not RobotoRegular / Suisse Int'l (plan Constraints). Owner: ticket 05 records it, ticket 27 lists it in `docs/settings-parity.md`.

VISUAL GAP: the "Desktop app" link keeps the app's colours and border inside the Infloww header (plan-decided, ours). Owner: ticket 27 (plan-decided departures).

From ticket 03:

VISUAL GAP: the font stays `--font-sans` (Sora), not RobotoRegular / Suisse Int'l. Owner: ticket 05 records it, ticket 27 lists it.

VISUAL GAP: row icon size (20px) and names are ours, not measured. Owner: the human (see Needs the human).

VISUAL GAP: the dark palette is sampled, not measured (the default theme in the PNGs). Owner: the human (see Needs the human).

From ticket 05:

VISUAL GAP: the font stays `--font-sans` (Sora), not RobotoRegular or the licensed Suisse Int'l (plan Constraints, gap row 15). Owner: ticket 27 lists it in `docs/settings-parity.md`.

VISUAL GAP: the measured two-column field grid `repeat(2,350px)` (plan:34) is not built, because no Phase uses it (spec Out of Scope). Owner: ticket 27 lists it among the plan-decided gaps.

VISUAL GAP: the "Desktop app" link keeps the app's colours and border inside the Infloww header (plan-decided). Owner: ticket 27 (plan-decided departures).

VISUAL GAP: the dark palette in every PNG (the default theme) is sampled, not measured; only the walk's light pass asserts measured literals. Owner: the human (see Needs the human).

VISUAL GAP: row icon size (20px) and the lucide icon names are ours, not measured. Owner: the human (see Needs the human).

VISUAL GAP: the app-wide Assistant "?" launcher (`app/components/assistant/AssistantWidget.tsx:188`, `fixed bottom-3 left-[264px]`) floats over the Tab list's bottom-left corner on every Settings tab. It is outside the Settings components and Infloww has no equivalent. Owner: the human (see Needs the human).

From ticket 06:

VISUAL GAP: Save is the house `SaveRow` primary Button (purple), not an `--if-accent` button, and sits below the 900px fold in the Panel body's own scroll; owner ticket 08.

VISUAL GAP: the two-column field grid repeat(2,350px) is not used; every field is its own row; owner ticket 08 (and Phase 6's parity doc, ticket 27).

VISUAL GAP: the font is `--font-sans`, not Suisse Int'l (plan Constraint). Owner: ticket 27 lists it in `docs/settings-parity.md`.

From ticket 07:

VISUAL GAP: Save is the house `SaveRow` primary Button (purple), not an `--if-accent` button; owner ticket 08.

VISUAL GAP: the selects are native `<select>`s with the browser's arrow, not Infloww's custom dropdown; owner ticket 08.

From ticket 08:

VISUAL GAP: the two-column field grid repeat(2,350px) is not used; every field is its own row. Owner: ticket 27 lists it among the plan-decided gaps.

VISUAL GAP: Save is the house `SaveRow` primary Button (purple), not an `--if-accent` button; the plan names `SaveRow` as the Save control (plan:13) and it is shared with the Legacy tabs. Owner: ticket 27 (carried verbatim).

VISUAL GAP: on Your Account at 1440x900 the Not applied yet note and Save sit at the 900px fold, reached by the Panel body's own scroll, because `SaveRow` renders in flow after two measured 140px pictures. Owner: ticket 27 (carried verbatim).

VISUAL GAP: the selects are native `<select>`s with the browser's own arrow, not Infloww's custom dropdown arrow (spec ASSUMPTION, house `RestrictionsTab.tsx:118`). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Personal and Agency pictures' initials colours (`--if-accent` on `--if-accent-bg`) are ours, not measured. Owner: the human (see Needs the human).

VISUAL GAP: the "Upload" control is a visible `NotWired` button beside the picture (spec: "Picture upload ... visible but Not wired"); Infloww's is an invisible input laid over the 140px picture (`._upload-input_rxwf7_218`: position absolute, z-index 2, opacity 0) with a photo icon shown on hover (`._photo-icon_rxwf7_211`). Owner: ticket 27 (carried verbatim).

From ticket 09:

VISUAL GAP: font (`--font-sans`, not RobotoRegular / Suisse Int'l); owner: ticket 27 (plan Constraints, licensed font).

From ticket 10:

VISUAL GAP: "Sign out" is the house secondary `Button`, whose colours are the app's `bg-elev-1`/`border` tokens, not `--if-*` (spec A4 picks the house Button); owner: ticket 27.

From ticket 11:

VISUAL GAP: the font is `--font-sans`, not RobotoRegular / Suisse Int'l (plan Constraint). Owner: ticket 27 lists it in `docs/settings-parity.md`.

VISUAL GAP: the Current session card carries no title or tip of its own. "Current session" is the Phase 0 `Section` title above the card (14px/500), not `._translation-item_rxwf7_369`'s in-card title (14px/600) and 12px/20px tip (spec Implementation Decisions, A3). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Employees table's row height (48px), cell padding and header style (14px `--if-fg-3`) are ours. The bundle has no security-table selector (spec A1). Owner: ticket 27 (carried verbatim).

VISUAL GAP: "Sign out" is the house `Button` (secondary), whose colours come from the house theme, not from `--if-*` tokens (spec A4, `TopBar.tsx:102` precedent). Owner: ticket 27 (carried verbatim).

From ticket 12:

VISUAL GAP: the font is `--font-sans`, not RobotoRegular / Suisse Int'l (plan Constraints); owner: ticket 27.

VISUAL GAP: the house primary `Button` is `bg-accent` (`--color-accent` #8b5cf6 dark / #7c3aed light) with `rounded-lg`, not the measured `--if-accent` (#4166f6 dark / #3467ff light) at the field radius; owner: ticket 27.

From ticket 13:

VISUAL GAP: "Save" and "+ Add Role" are the house primary `Button` (`bg-accent` violet, `rounded-lg`), and "Back" the house secondary, not `--if-accent` at the field radius; owner: ticket 27.

VISUAL GAP: the editor's tab bar height and the Back/Save row are unmeasured (the bundle has no `_1r0jx` rule for them); owner: ticket 27.

From ticket 14:

VISUAL GAP: "+ Add Role" and Submit are the house primary `Button` (`bg-accent` violet, `rounded-lg`), not `--if-accent` at the field radius; owner: ticket 27.

VISUAL GAP: the 16px gap between "Edit" and "Set Permissions" is unmeasured; owner: ticket 27.

From ticket 15:

VISUAL GAP: Save and "+ Add Role" are the house primary `Button` (`bg-accent` violet, `rounded-lg`), not `--if-accent` at the field radius; owner: ticket 27.

VISUAL GAP: the Employee roles layout (one Field per Employee) is unmeasured: Infloww assigns roles on Manage employees, not here; owner: ticket 27.

From ticket 16:

VISUAL GAP: the house primary `Button` (Save) is `bg-accent` violet with `rounded-lg`, not the measured `--if-accent` at the field radius; owner: ticket 27.

From ticket 17:

VISUAL GAP: "+ Add Role", Submit, the editor's Save and both Panel Saves are the house primary `Button` (`bg-accent` violet, `rounded-lg`), not the measured `--if-accent` at the field radius. The editor's "Back" is the house secondary (tickets 12-16). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Permission editor's tab bar height and its Back/Save row are unmeasured: the bundle has no `_1r0jx` rule for them (ticket 13). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the 16px gap between "Edit" and "Set Permissions" is unmeasured (ticket 14). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Employee roles layout (one Field per Employee) is unmeasured, because Infloww assigns roles on Manage employees, not here (ticket 15). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Employee role selects are native `<select>`s with the browser's own arrow, not Infloww's custom dropdown arrow (same as ticket 08's select gap). Owner: ticket 27 (carried verbatim).

VISUAL GAP: an unchecked radio is a 1px `--if-line` ring (`RADIO`, `SettingsPanel.tsx:204`). That is (49,49,49) against (38,38,38) on the dark PNG, barely visible (the opt-in checkbox is native with `accent-color` and clearly visible), and the unchecked style is unmeasured (the gap table pins only checked = `--if-accent`). Owner: ticket 27 (carried verbatim).

From ticket 18:

VISUAL GAP: the font is `--font-sans`, not Infloww's RobotoRegular / Suisse Int'l (plan Constraint); owner ticket 27.

VISUAL GAP: Edit / Cancel / Save are the house `Button` (accent colour, ~36px high, Save icon), not Infloww's 32px default/primary buttons; owner ticket 27.

VISUAL GAP: disabled switches render at 50% opacity, the shared `Switch`'s disabled drawing; the bundle's disabled `HBSwitch` look is unmeasured; owner ticket 27.

From ticket 19:

VISUAL GAP: the switch is the shared 44x22 `Switch`; the bundle's `HBSwitch size="medium"` geometry is unmeasured; owner ticket 27.

From ticket 20:

VISUAL GAP: the bundle shows the prompt in an always-present read-only textarea (auto-size 5–10 rows, character count, placeholder), ours shows a text line until Edit and a fixed 6-row textarea after (ticket and spec); owner ticket 27.

VISUAL GAP: the Edit button (32px house `Button`) makes card 2's title row taller than card 1's; the bundle's `HBButton size="moderate"` height is unmeasured; owner ticket 27.

VISUAL GAP: the committed PNG shows only the read view; the open editor is checked only for 390x844 overflow; owner ticket 27.

From ticket 21:

VISUAL GAP: Edit / Cancel / Save are the house `Button` (accent colour, ~36px high, Save icon), not Infloww's 32px default/primary buttons. Owner: ticket 27 (carried verbatim).

VISUAL GAP: disabled switches render at 50% opacity, the shared `Switch`'s disabled drawing; the bundle's disabled `HBSwitch` look is unmeasured. Owner: ticket 27 (carried verbatim).

VISUAL GAP: the switch is the shared 44x22 `Switch`; the bundle's `HBSwitch size="medium"` geometry is unmeasured. Owner: ticket 27 (carried verbatim).

VISUAL GAP: the bundle shows the prompt in an always-present read-only textarea (auto-size 5–10 rows, character count, placeholder), ours shows a text line until Edit and a fixed 6-row textarea after (ticket and spec). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the Edit button (32px house `Button`) makes card 2's title row taller than card 1's; the bundle's `HBButton size="moderate"` height is unmeasured. Owner: ticket 27 (carried verbatim).

VISUAL GAP: the committed PNG shows only the read view; the open editor is checked only for 390x844 overflow. Owner: ticket 27 (carried verbatim).

From ticket 22:

VISUAL GAP: the font is `--font-sans`, not Suisse Int'l, and Not wired buttons use the house drawing; owner ticket 27.

VISUAL GAP: card to "Make a Payment" distance unmeasured against Infloww (bundle filter row 75px not adopted); owner ticket 27

From ticket 23:

VISUAL GAP: the balance cards' arrangement (four across vs two by two), the gap between them (16px) and the space between label and amount (8px) are not measured in the bundle or the plan's table. Owner: ticket 27.

VISUAL GAP: the `1dq9x` amount type may belong to the wallet top-up screen rather than Settings (the spec's own ASSUMPTION), so the 14px/500 label and 32px/600 amount are unconfirmed for this screen. Owner: ticket 27.

From ticket 24:

VISUAL GAP: the tile's colours and radius, the links' arrangement (row, 24px gap) and colour, and the 40px vertical padding of the centred block are not measured in the bundle or the plan's table. Owner: ticket 27.

VISUAL GAP: in the dark theme `--if-accent-bg` makes the tile a dark grey with blue text; Infloww's light logo image is not reproduced. Owner: ticket 27.

From ticket 25:

VISUAL GAP: Billing's Not wired buttons use the house drawing (ticket 22). Owner: ticket 27 (carried verbatim).

VISUAL GAP: card to "Make a Payment" distance unmeasured against Infloww (bundle filter row 75px not adopted) (ticket 22). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the balance cards' arrangement (four across vs two by two), the gap between them (16px) and the space between label and amount (8px) are not measured in the bundle or the plan's table (ticket 23). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the `1dq9x` amount type may belong to the wallet top-up screen rather than Settings (the spec's own ASSUMPTION), so the 14px/500 label and 32px/600 amount are unconfirmed for this screen (ticket 23). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the About tile's colours and radius, the links' arrangement (row, 24px gap) and colour, and the 40px vertical padding of the centred block are not measured in the bundle or the plan's table (ticket 24). Owner: ticket 27 (carried verbatim).

VISUAL GAP: in the dark theme `--if-accent-bg` makes the About tile a dark grey with blue text; Infloww's light logo image is not reproduced (ticket 24). Owner: ticket 27 (carried verbatim).

VISUAL GAP: the committed `settings-balance.png` is the walk's All-Creators view ("Select a model to see its balance"); the four cards and the payout row are seen only in `/tmp/settings-shots/settings-balance-model.png`, which is never committed (Cross-spec decision (e)). Owner: ticket 27 (carried verbatim).

### Closed (recorded as closed in a later ticket's notes; not open)

Closed by ticket 03 (the Tab area fills the viewport and the Tab list has 64px icon rows; confirmed by ticket 05's walk, recorded in ticket 26):

VISUAL GAP: the Settings surface (`--if-bg`) ends at the content's height and the page column below it shows the app background; the Tab area does not fill the viewport yet. Owner: ticket 03.

VISUAL GAP: the Tab list is still today's 40px pills, no icons, app colours, 224px wide. Owner: ticket 03.

Closed by ticket 04 (every Panel has its 48px Panel header; recorded in ticket 26):

VISUAL GAP: the Panel is the bare "not built yet" card, no 48px Panel header or 24px body. Owner: ticket 04.

VISUAL GAP: the Panel is the bare "not built yet" card, no 48px Panel header. Owner: ticket 04.

Closed by the eleven Panel tickets and ticket 25 (no tab renders the placeholder; recorded in ticket 26):

VISUAL GAP: the "not built yet" card keeps the app's `bg-panel`/`border-border` colours, not `--if-*`. Owner: ticket 05 (Phase 0 visual loop). Each tab's Panel phase (06-24) replaces the card.

VISUAL GAP: the "not built yet" card inside each Panel keeps the app's `bg-panel` colours and dashed `border-border`, not `--if-*`. `NotBuiltYet` lives outside `app/components/settings/`, so ADR-0009 keeps `--if-*` out of it. Owner: each tab's Panel ticket (06, 07, 09, 10, 12, 16, 18, 19, 22, 23, 24) replaces it, and ticket 25 removes the placeholder.

Closed by ticket 14 (the roles PNG shows "Edit" and "Set Permissions" on both rows; recorded in ticket 17):

VISUAL GAP: the Operations column is empty; owner: tickets 13 ("Set Permissions") and 14 ("Edit").

VISUAL GAP: the Operations column lacks "Edit"; owner: ticket 14.

## Parity table

| Tab | Ground-truth evidence | Component | Wired | Not wired | Visual gap |
|---|---|---|---|---|---|
| `account` | §3.10 row 1, C[H262101, H262021]; `._personal-info-wrap_rxwf7_132`, `._personal-item_rxwf7_146`, `._personal-input_rxwf7_237`, `._disabled-input_rxwf7_242`, `._personal-avatar_rxwf7_192`, `._upload-input_rxwf7_218` | `YourAccountTab` (`app/components/settings/YourAccountTab.tsx`) | Username read-only from `GET /auth/me`; Agency Name saved whole to `/admin/settings/account`, blob keys `agency_name`; Not applied yet (no consumer, so the whole-Panel note stays) | Upload, Edit | initials colours (the human); font (`--font-sans`) |
| `preferences` | §3.10 row 2, C[H262077, H451172]; `._personal-item_rxwf7_146`, `._personal-item-title_rxwf7_155`, `._personal-item-timezone_rxwf7_176`, `._persinal-text_rxwf7_253` | `PreferencesTab` (`app/components/settings/PreferencesTab.tsx`) | Report time zone, Time zone, Week start day and Language saved whole to `/admin/settings/preferences`, blob keys `report_tz`, `tz`, `week_start`, `language`; zones from `Intl.supportedValuesOf("timeZone")`; Applied: `tz` labels the top bar, `report_tz` cuts report days, `week_start` starts the Shift schedule and "My shifts" week; `language` Not applied yet | none | font (`--font-sans`) |
| `security-org` | §3.10 row 3, C[H463402, CL]; `._switch-theme_rxwf7_303` (toggle row), `._title_rxwf7_137`, `._table-wrap_rxwf7_143`; no security-table selector in the bundle | `SecurityOrgTab` (`app/components/settings/SecurityOrgTab.tsx`) | Employees from `GET /admin/employees` (`useRoster`), disabled ones greyed; 2FA status and Last login read "—"; stores nothing | Two-factor authentication, Reset | no security-table selector in the bundle (the table takes the shared antd head, 13px cells); font (`--font-sans`) |
| `security-personal` | §3.10 row 4 (tab C[BS], fields G); `._translation-item_rxwf7_369` (session card), `._title_rxwf7_137` | `SecurityPersonalTab` (`app/components/settings/SecurityPersonalTab.tsx`) | Current session username from `GET /auth/me`; Sign out sends `POST /auth/logout` with `{}`; stores nothing | Change password, Enable 2FA | font (`--font-sans`) |
| `billing` | §3.10 row 5, C[H262093], [CL]; `._billing-header_6tj53_47`, `._billing-tabs-wrap_6tj53_60`, `._period_6tj53_29`, `._translation-item_rxwf7_369` | `BillingTab` (`app/components/settings/BillingTab.tsx`) | static: subtabs "Infloww subscription" / "AI Copilot" (local state), plan card "Inflowwww — self-hosted, free", invoice table with "No invoices"; reads and writes nothing | Pricing plans, Update card, Cancel subscription, Billing information, Make a Payment | font (`--font-sans`) |
| `balance` | §3.10 row 6 (tab C[BS], fields G from H262091); `._balance-amount_1dq9x_13`, `._balance-amount-text_1dq9x_21`, `._personal-info-wrap_rxwf7_132` | `BalanceTab` (`app/components/settings/BalanceTab.tsx`) | four cards from `GET /api/of/v2/payments/referrals/balance` and payouts from `GET /api/of/v2/payouts/requests/referral` for the selected Creator (`X-Account-Id`); all-Creators scope fetches nothing; a missing field reads "—"; stores nothing | none | the three extra figures' row is ours (Infloww shows one amount); `1dq9x` amount type unconfirmed; committed PNG is the all-Creators view; font (`--font-sans`) |
| `roles` | §3.10 row 7, C[H262098]; `._role-header_1r0jx_36`, `._tabble-content_1r0jx_77`, `._table-title_1r0jx_83`, `._table-wrap_1r0jx_89`, `._open-delete-role_1r0jx_52`, `._personal-input_rxwf7_237` | `RoleSettingsTab` with `PermissionEditor` (`app/components/settings/RoleSettingsTab.tsx`, `PermissionEditor.tsx`) | Roles, permissions per sidebar page, data scope and Employee role assignments saved whole to `/admin/settings/roles`, blob keys `roles` (id, name, description, permissions, scope), `assignments` and `enforce`; Employees from `GET /admin/employees`; Applied under Role enforcement ("Enforce role permissions", off by default): the Relay refuses denied pages, the sidebar shows only granted pages, Data scope narrows a chatter's Employee reports; Not applied yet while it is off | none | Employee roles table is ours (Infloww assigns roles on Manage employees); font (`--font-sans`) |
| `sales` | §3.10 row 8, C[H262080]; `._switch-theme_rxwf7_303` (three toggle rows), `._learn-more_1t0kc_5` (not rendered) | `SalesSettingsTab` (`app/components/settings/SalesSettingsTab.tsx`) | three toggles and the attribution radios saved whole to `/admin/settings/sales`, blob keys `exclude_welcome`, `exclude_of_fee`, `multi_employee_shift`, `attribution` (messages, posts_tips, subscriptions_chatter_opt_in, converters_window_seconds: Converters' "within X hours and Y minutes" window, hours 0-999 and minutes 0-59, 1 h default); Applied in the read path: the attribution rules credit Employee reports and the Timesheet, the two exclusions drop welcome-message sales and the OnlyFans fee, `multi_employee_shift` allows double-staffing and splits Shift schedule credit | none | "Learn more" hidden (plan-decided); font (`--font-sans`) |
| `time-tracking` | §3.10 row 9, C[H300963]; bundle `ClockSetting`, `._translation-item_rxwf7_369`, `._translation-item-input_rxwf7_408`, `._about-header_rxwf7_9` | `TimeTrackingTab` (`app/components/settings/TimeTrackingTab.tsx`) | read view, then Edit with Save / Cancel saved whole to `/admin/settings/time-tracking`, blob keys `enabled`, `auto_clock_out_minutes`, `clock_in_reminder`; Cancel sends nothing; Applied (Phase 2): `enabled` gates clock in (clock-out still closes an open event, and the heartbeat stops renewing it), `auto_clock_out_minutes` closes forgotten clock-ins, `clock_in_reminder` shows the reminder | none | matches the live capture 03 (ticket 20); card tip ink about 2px higher; font (`--font-sans`) |
| `messaging` | §3.10 row 10, C[H262030, H673161]; `._messaging-setting-wrap_1cat4_1`, `._translation-item-content_1cat4_4`, `._translation-item-title_1cat4_10`, `._btn-wrap_1cat4_21`, bundle `HBSwitch` | `MessagingSettingsTab` (`app/components/settings/MessagingSettingsTab.tsx`) | AI translation switch and AI Translator prompt saved to `/admin/settings/messaging`, blob keys `ai_translation`, `prompt`; `ai_translation` Applied: while off, a chatter's "Use translation" is disabled, the per-message Translate is hidden and `/admin/translate` refuses them; `prompt` stored but not used, its card saying "Saved for your organization, but not used: Google's free translate service takes no instructions." (`/admin/translate` stays Google gtx, keyless; ticket 28 closed); the switch card's note links `/messages-pro` and `/employees` | none | Edit button row taller; committed PNG shows the read view only; font (`--font-sans`); prompt caption toned to "Instructions such as tone, style and specific vocabulary for translations" (Infloww: "Customize the translation output with instructions such as tone, style and specific vocabulary to use"); a note under each card saying what it does |
| `about` | §3.10 row 11 (tab C[BS], panel title [CL], fields G); `._about-wrap_rxwf7_25`, `._about-logo_rxwf7_31`, `._about-version_rxwf7_37`, `._join-beta-wrap_rxwf7_40` (not rendered) | `AboutTab` (`app/components/settings/AboutTab.tsx`) | "Version" from `app/package.json`; the desktop-app box's "Download" (`/download`) and the licence on the repo named in `app/lib/repoUrl.ts`; makes no request and stores nothing | none | the wordmark tile stands in for Infloww's logo image; no beta box or build hash (plan-decided); font (`--font-sans`) |
