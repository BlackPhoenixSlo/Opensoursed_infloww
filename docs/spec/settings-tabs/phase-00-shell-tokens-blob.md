# Phase 00 — shared shell, tokens, settings blob

**Objective.** Every Settings tab sits in Infloww's frame (the Settings header with ✕, a Tab area whose Tab list and Panel scroll on their own, 64px rows on Infloww's colours through Infloww tokens), later Phases have the Panel parts and `useSettingsBlob` to build on, the Relay stores one Settings blob per Agency and Blob tab behind `GET/PUT /admin/settings/{tab}`, and the Settings walk proves the geometry of all 11 Settings tabs with an empty Write list.

## Measured gap table

Ground truth is the plan's table (Dashboard bundle `index.9fc9db54.css`, module `rxwf7`; re-grepped for this spec). "Ours" is this worktree at `4d8c6039`.

| # | Ground truth (selector → value) | Ours (`file:line`) | Gap | Change |
|---|---|---|---|---|
| 1 | `._about-header_rxwf7_9`, `._account-wrap_rxwf7_118 ._header_rxwf7_121` → height 48px, margin 0 24px, border-bottom 1px `--tc-L1`, title 16px/500 `--tc-T1` | `app/app/settings/layout.tsx:10-11` → `<header class="flex items-center gap-3">`, `h1 text-2xl font-semibold`, no border, content height | 24px title, no fixed height, no rule, page padding `p-3 sm:p-6` (`:9`) | Settings header in the new `SettingsShell`: `--if-header-h` 48px, margin 0 24px, `--if-line` rule, "Settings" 16px/500 `--if-fg`; "Desktop app" link (`:14-21`) kept on the right |
| 2 | `SettingPage$2` (`index.9f50f370.js`) → `PageHeader$1` `rightRender` = a close icon whose click handler leaves Settings | `layout.tsx:10-22` → no close control | missing | ✕ button (aria-label "Close settings") right of "Desktop app": `router.back()` when `window.history.length > 1`, else `router.push("/")` |
| 3 | `._tab-wrap_rxwf7_77` → `display:flex; height: calc(100vh - var(--root-header-height) - 48px)`; `._tab-left_rxwf7_81` `height:100%; overflow-y:auto`; `._tab-main_rxwf7_114` `flex:1` | `layout.tsx:23-26` → `flex flex-col md:flex-row gap-5`, no height, page scrolls | whole page scrolls; 20px gap | Tab area (md and up): `height: calc(100dvh - var(--shell-top, 3.5rem) - var(--if-header-h))`, no gap, Tab list and Panel each `overflow-y:auto` |
| 4 | `SettingPage$2` resize handler (`ResizeObserver` on the tab-wrap's `offsetWidth`) → list = width × 3/16 at ≥1200px, × 4/16 at 576–1199px; `min-width` = width | `app/components/settings/SettingsNav.tsx:37` → `md:w-56 md:shrink-0` (224px fixed) | fixed width, not a fraction | Tab area is a size container (`@container`); Tab list `width:25%`, `18.75%` at container ≥1200px, `shrink-0` |
| 5 | `._tab-left_rxwf7_81` → `background-color: var(--tc-B1)` (#f5f5f5) | `SettingsNav.tsx:37` → no background | none | `--if-list-bg` |
| 6 | `._tab-item_rxwf7_88` → height 64px, padding 0 16px, 16px, `--tc-T3`; `._tab-item-icon_rxwf7_108` margin-right 16px | `SettingsNav.tsx:28` → `px-3 h-10 rounded-lg text-sm`, no icon; `app/lib/nav.ts:61,159-169` `nb()` sets no `icon` | 40px rows, 14px, 12px padding, radius, no icon | md and up: `--if-tab-h` 64px, padding 0 16px, 16px `--if-fg-3`, lucide icon + 16px gap, square corners; below md the current strip classes stay |
| 7 | `._tab-item-active_rxwf7_99` → `color: var(--tc-M1)` on `var(--tc-M-B)` | `SettingsNav.tsx:29` → `bg-bg-elev-1 text-fg`, no `aria-current` | app colours | `--if-accent` on `--if-accent-bg`, `aria-current="page"` |
| 8 | `._account-wrap_rxwf7_118 ._header_rxwf7_121` (Panel header, as row 1); `._personal-info-wrap_rxwf7_132` → padding 24px, `overflow:auto`, height = tab area − 48px | `app/app/settings/[tab]/page.tsx:16` → bare `NotBuiltYet` card | no Panel frame | `SettingsPanel`: Panel header + 24px body that scrolls |
| 9 | `._title_rxwf7_137` 14px/500 `--tc-T1`, padding-bottom 16px; `._table-wrap_rxwf7_143` margin-bottom 40px | none | missing | `Section` |
| 10 | `._personal-item_rxwf7_146` margin-bottom 30px; `._personal-item-title_rxwf7_155` 14px/400 `--tc-T3`, margin-bottom 8px | none | missing | `Field` |
| 11 | `._personal-input_rxwf7_237` width 448px, border `--tc-L1`, bg `--tc-B-nav`; `._personal-item-content_rxwf7_230` radius 8px; `._disabled-input_rxwf7_242` bg `--tc-B-th` | `app/components/ui/primitives.tsx:62` → generic `Input`, app tokens | width, radius, colours | `FieldInput`: `--if-input-w`, `--if-input-radius`, `--if-line`, `--if-bg`; disabled `--if-input-disabled` |
| 12 | `._switch-theme_rxwf7_303` → height 72px, padding 0 16px, radius 4px, border `--tc-L1`; title 14px, desc 12px `--tc-T3` | none (`AutomationSwitch.tsx` is the automation tabs' card) | missing | `ToggleRow` |
| 13 | `:root` light `--tc-B-nav` #ffffff · `--tc-B1` #f5f5f5 · `--tc-T1` #151515 · `--tc-T2` #666666 · `--tc-T3` #999999 · `--tc-M1` #3467ff · `--tc-M-B` #eff4ff · `--tc-L1` #e6e6e6 · `--tc-D1` #ff7c71 · `--tc-B-th` #fafafa | `app/app/globals.css:75-96` → app palette only | no Infloww tokens | `--if-*` colour slots in `html[data-theme="light"]` |
| 14 | dark: `docs/infloww-screens.md` §1.4 [PAL] canvas #262626, side panel #232323, border #333, selected #353535, accent #4166f6, red #f0483e; `.theme-dark` `--element-emphasis-00/01/02` #fff / 62% / 38% | `globals.css:12-58` (`@theme`), `:63` | no Infloww tokens | `--if-*` dark values in a `:root` block beside `@theme` |
| 15 | `body{font-family:"RobotoRegular",…}`; `hb-design` `"Suisse Int'l"` | `globals.css:41` `--font-sans` (Sora) | font differs | none: VISUAL GAP: font stays `--font-sans` (plan Constraints) |
| 16 | Ground truth 6: `UserLlmKey` (`service/db/models.py:2669-2697`), migration `0064_user_llm_keys`, `tenant_keys_api.py:32-42`, upsert `webhook_config_api.py:98-115`, registration `server.py:89,230` | `grep -n "user_settings\|settings_api" service/` → nothing | no store, no route | `UserSetting`, migration `0065_user_settings`, `service/settings_api.py`, registration |

Tokens this Phase adds (names are ours, values from rows 1–14): geometry `--if-header-h` 48px, `--if-tab-h` 64px, `--if-row-px` 16px, `--if-panel-pad` 24px, `--if-section-gap` 40px, `--if-field-gap` 30px, `--if-label-gap` 8px, `--if-input-w` 448px, `--if-input-radius` 8px, `--if-toggle-h` 72px, `--if-toggle-radius` 4px; type `--if-fs-lg` 16px (Settings header, Panel header, tab rows), `--if-fs` 14px (Section title, Field label, ToggleRow title), `--if-fs-sm` 12px (ToggleRow description), `--if-fw-title` 500, `--if-section-title-pb` 16px; colours (light / dark) `--if-bg` #ffffff / #262626, `--if-list-bg` #f5f5f5 / #232323, `--if-fg` #151515 / #ffffff, `--if-fg-2` #666666 / rgb(255 255 255 / 62%), `--if-fg-3` #999999 / rgb(255 255 255 / 38%), `--if-accent` #3467ff / #4166f6, `--if-accent-bg` #eff4ff / #353535, `--if-line` #e6e6e6 / #333333, `--if-danger` #ff7c71 / #f0483e, `--if-input-disabled` #fafafa / #232323.
ASSUMPTION: the dark slot mapping (canvas → `--if-bg`, side panel → `--if-list-bg` and `--if-input-disabled`, selected → `--if-accent-bg`, emphasis 00/01/02 → `--if-fg`/`-2`/`-3`) is ours; §1.4 samples colours, not slots. Overturned by a dark Settings capture.

## Problem Statement

An Agency owner who opens Settings sees eleven tabs that each say "not built yet", in a frame that looks like none of Infloww: a large page title, a narrow 40px pill list, and no way back but the browser. Later Phases cannot build tabs that look and save like Infloww's, because nothing gives them Infloww's colours and geometry, Panel parts, or a place on the Relay to store a tab's values.

## Solution

Settings opens on Infloww's frame: a 48px Settings header with "Settings", the "Desktop app" link and a ✕ that goes back; under it a full-height Tab area where the Tab list (64px rows with icons, Infloww's grey list and blue active row, a quarter of the width or 3/16 when wide) and the Panel scroll on their own. Each tab still shows its "not built yet" card, now inside a Panel with its 48px Panel header. Behind it the Relay keeps one Settings blob per Agency and Blob tab, and every later Phase gets the parts (Panel header, Panel section, Field, ToggleRow, Not wired, Not applied yet) and one hook that loads and saves a blob whole behind the Load gate.

## User Stories

1. As an Agency owner, I want a 48px Settings header reading "Settings" at 16px/500, so that Settings is framed as in Infloww.
2. As an Agency owner, I want the "Desktop app" link kept on the right of the Settings header, so that I can still get the desktop app from Settings.
3. As an Agency owner, I want a ✕ in the Settings header that takes me back to the page I came from, or to `/` when Settings was opened with no history (a deep link in a new tab), so that I leave Settings as in Infloww and never get a dead button.
4. As an Agency owner, I want the Tab area to fill the viewport under the app's top bar and the Settings header, with the Tab list and the Panel each scrolling on their own, so that a long Panel never scrolls the tab rows away.
5. As an Agency owner on a desktop, I want each Settings tab row 64px tall, padded 0 16px, at 16px with a 16px gap after its icon, so that the Tab list reads like Infloww's.
6. As an Agency owner, I want each of the 11 Settings tabs to carry its own icon, so that the rows match Infloww's icon + title rows.
7. As an Agency owner, I want the active row in Infloww's accent on its accent background, and the others in Infloww's tertiary grey on the grey list background, so that I can see where I am.
8. As an Agency owner, I want the Tab list to take 25% of the Tab area, and 18.75% once the Tab area is 1200px or wider, so that it scales as Infloww's does.
9. As an Agency owner on a phone, I want the current horizontal strip below `md`, with no horizontal overflow of the page, so that Settings stays usable at 390px.
10. As an operator with the legacy flag on, I want the "Legacy" group and its four Legacy tabs unchanged, and with the flag off I want them hidden, so that this effort never touches them.
11. As an Agency owner, I want every Settings tab, built or not, to show a Panel with a 48px Panel header naming the tab and a 24px body, so that the frame is the same on all 11 tabs.
12. As an Agency owner, I want Settings in Infloww's light colours under the light theme and in the sampled dark palette under the dark theme, so that Settings looks like Infloww in either theme.
13. As a developer of a later Phase, I want `--if-*` Infloww tokens for every measured colour and geometry value in one block of `globals.css`, so that no Panel carries a magic number (ADR-0009).
14. As a developer of a later Phase, I want `SettingsPanel`, `Section`, `Field`, `FieldInput`, `ToggleRow`, `NotWired` and `NotAppliedYet`, so that every tab is built from the same measured parts.
15. As an Agency owner, I want a Not wired control to be disabled with the tooltip "not wired" and never to report success, so that I am never told something happened that did not (ADR-0008).
16. As an Agency owner, I want a Panel whose values nothing reads to say "Saved for your organization; not applied yet.", so that I do not believe a saved setting is enforced (ADR-0008).
17. As a developer of a later Phase, I want `useSettingsBlob(tab, defaults)` that loads a Blob tab's Settings blob, merges my edits, and saves the full object through `SaveRow`, so that every Blob tab saves the same way.
18. As an Agency owner, I want Save disabled, and nothing sent, until the Settings blob has loaded, so that a failed load can never overwrite my stored settings with a sparse blob (Load gate).
19. As an Agency owner, I want Cancel-style resets to restore the loaded values without sending anything, so that discarding an edit is safe.
20. As a developer of a later Phase, I want one `SETTINGS_PANELS` record in `[tab]/page.tsx` that maps a tab to its Panel, with unmapped tabs still on `NotBuiltYet`, so that landing a Phase is one added entry.
21. As the Relay, I want a `user_settings` table (`user_id` FK CASCADE + `tab` as the key, `config_json` Text, `updated_at`) next to `UserLlmKey`, with its migration, so that a Settings blob persists and goes when its Agency goes.
22. As a signed-in Agency owner, I want `GET /admin/settings/{tab}` to return `{tab, config}` (`{}` when nothing is stored) and `PUT /admin/settings/{tab}` to replace the blob with my JSON object and return `{tab, config}`, so that the Panels have one read and one write (ADR-0007).
23. As the Relay, I want only the six Blob tabs (`account`, `preferences`, `roles`, `sales`, `time-tracking`, `messaging`) accepted, any other tab answered 404, a non-object body 400, a body over 64 KB 413, and no signed-in User 401, so that the store holds only what the Panels own.
24. As an Agency owner, I want my Settings blobs readable and writable only by my own session, so that another Agency can never see or change them.
25. As a developer, I want `scripts/settings-check/walk.py` to mock the Relay with synthetic data, walk all 11 Settings tabs at 1440×900 and 390×844, assert the geometry against the tokens, record the Write list, write PNGs and a report, and abort any off-host request, so that every later Phase accepts on it.
26. As a developer of Phase 0, I want the walk to pass on all 11 tabs with unbuilt Panels allowed and an empty Write list, so that the shell is proven before any Panel lands.
27. As a developer, I want the shell's eleven 1440 PNGs read against the Ground-truth table, fixed for up to three rounds and copied to `docs/screenshots/`, so that the Check loop holds for this Phase too.
28. As an Agency owner signed in as a Chatter, I want the six Blob tabs left out of the Tab list, so that I am not shown Panels whose Settings blob the Relay refuses me (401).

## Implementation Decisions

- **Owns.** `globals.css` (the `--if-*` block); the Settings `layout`; new `SettingsShell` (client: Settings header, ✕, Tab area); `SettingsNav`; new `SettingsPanel` module; new `settingsBlob` module in `app/lib`; the `[tab]` page; `nav.ts` (`nb()` and the 11 `SETTINGS_TABS` entries gain icons); `db/models.py` (`UserSetting`); migration `20261013_0100_user_settings.py`; new `service/settings_api.py`; `server.py` (import + `include_router`); new `scripts/settings-check/walk.py`; tests `app/components/settings/SettingsShell.test.tsx`, `app/lib/settingsBlob.test.ts`, `service/tests/test_settings_api.py`.
- **Interfaces.**
  - `layout` keeps `metadata` and renders `<SettingsShell>{children}</SettingsShell>`. The header lives in `SettingsShell` because ADR-0009 lets only `app/components/settings/` read `--if-*`, and `router.back()` needs a client component.
  - `SettingsShell({children})`: Settings header (`data-settings="header"`), Tab area (`data-settings="tab-area"`, `@container`), `SettingsNav`, Panel slot. The ✕ calls `router.back()` when `window.history.length > 1`, else `router.push("/")`.
  ASSUMPTION: the no-history fallback is `/`; the plan says only `router.back()`, which does nothing on a fresh tab. Overturned by a capture of Infloww's close handler's target.
  - `SettingsNav`: same data source and filters (`visibleLinks`), rows `data-settings="tab"` with `aria-current="page"` on the active one; list `data-settings="tab-list"`. Below md: current strip unchanged.
  - `nav.ts`: `nb(label, href, icon?, extra?)`; each of the 11 Settings tabs gets a lucide icon, and the six Blob tabs get `chatterHidden: true` (story 28). Legacy entries unchanged.
  ASSUMPTION: the six Blob tabs are hidden from a Chatter-only session, because `/admin/settings/{tab}` answers a Chatter session 401 and `nav.ts:10-11` already hides owner-only routes that way (rung 3); the five other Settings tabs stay visible (Security reads the roster, Billing and About are static, Your Balance per Phase 5). Overturned if the human wants Chatters to see the Blob tabs, read-only.
  - `SettingsPanel({title, actions?, children})` with `data-settings="panel-header"` on its header and `data-settings="panel-body"` on its scrolling body; `Section({title, children})`; `Field({label, htmlFor?, children})`; `FieldInput` (an `input` with `max-width:100%`); `ToggleRow({title, description?, checked, onChange, notWired?})` with a `role="switch"` button; `NotWired({label})`: `<button disabled title="not wired">` (house precedent `ComposerToolbar.tsx:170-176`); `NotAppliedYet()`: the ADR-0008 sentence. No hooks, so the server page can wrap `NotBuiltYet` in it.
  - `settingsBlob`: `BLOB_TABS` (the six) and `BlobTab`; `useSettingsBlob<T>(tab: BlobTab, defaults: T)` → `{ value: T, set(patch: Partial<T>), reset(), loaded: boolean, save: SaveControl }`. Query key `["settings-blob", tab]` over `relay.get`; `value = {...defaults, ...stored, ...edits}`; `save.onSave` returns early unless `loaded`, else `relay.put` of the whole `value`, then seeds the query with the reply and clears edits; `save.canSave = loaded` with `loaded = !!q.data` (no `isSuccess` conjunct: a failed background refetch over a good load keeps Save on, house precedent `WebhookDispatchTab.tsx:81-87`), `save.gateNote = loadGateNote(q)`, `save.error` the mutation's message, `save.saved` true until the next `set`. Panels render `<SaveRow {...blob.save} />`.
  - `[tab]` page: `SETTINGS_PANELS: Partial<Record<string, ComponentType>>` keyed by the full href (`"/settings/<tab>"`, plan:154), looked up as `` `/settings/${tab}` ``, empty in this Phase. Order: unknown → 404; legacy → `LegacySettingsTab` (unchanged); mapped → its Panel (which renders its own `SettingsPanel`); else `<SettingsPanel title={link.label}><NotBuiltYet title={link.label} /></SettingsPanel>`.
- **Schema.**
  ```
  user_settings(user_id String FK users.id ON DELETE CASCADE, tab String, config_json Text NOT NULL,
                updated_at DateTime NOT NULL, PRIMARY KEY (user_id, tab))
  ```
  Migration revision `0065_user_settings`, `down_revision = "0064_user_llm_keys"`, built like `20260820_0100_user_llm_keys.py`; `init_db`'s `create_all` creates it for tests.
- **Contracts.**
  - `GET /admin/settings/{tab}` → 200 `{"tab": tab, "config": {...}}` (`{}` when no row or unreadable JSON).
  - `PUT /admin/settings/{tab}` body = the whole blob as a JSON object → 200 `{"tab": tab, "config": body}`; upsert on `(user_id, tab)` as `webhook_config_api.py:98-115`.
  - Check order: 401 (no User, `_require_user()` as `tenant_keys_api.py:35-42`) → 404 (tab not in the allow-list, GET and PUT) → 413 (raw body > 65536 bytes) → 400 (not JSON, or not an object). No key validation inside a blob (ADR-0007).
  - Write list entry format (walk): `[method, path, json body]`.
- **Shell CSS.** Light `--if-*` inside `html[data-theme="light"]` (`globals.css:75`); dark in a plain `:root` block right after `@theme` (`:12-58`), because `--if-*` is not a Tailwind theme namespace and `html[data-theme="light"]` (0,1,1) beats `:root`. Components read tokens through arbitrary values (`h-[var(--if-tab-h)]`, `text-[var(--if-accent)]`). The Settings surface (header, Tab area) paints `--if-bg`; the page is full-bleed (no `max-w-shell`, no page padding) so the Tab area is the whole main column.
  ASSUMPTION: below md the Tab area has no fixed height and the page scrolls as today, and the strip keeps its current classes; overturned if a phone capture of Infloww Settings shows a fixed-height layout.
  ASSUMPTION: the ✕ is 16px lucide `X` in `--if-fg-3`; the bundle's icon is an inline-coloured `#6F767E`, a value not in the plan's table. Overturned by adding that value to the table.
  ASSUMPTION: row icons are 20px (the app Sidebar's `w-5 h-5`, `Sidebar.tsx:84`) with this mapping: account `CircleUser`, preferences `SlidersHorizontal`, security-org `ShieldCheck`, security-personal `LockKeyhole`, billing `CreditCard`, balance `Wallet`, roles `UsersRound`, sales `BadgeDollarSign`, time-tracking `Clock`, messaging `MessageSquareText`, about `Info`. Icons live on `SETTINGS_TABS` because `SIDEBAR` entries carry theirs in `nav.ts` (rung 3). Overturned by measured icon sizes or names.
  ASSUMPTION: `FieldInput` is 32px high and `ToggleRow`'s switch is 44×22px (antd defaults; `._persinal-text_rxwf7_253` line-height 32px), neither in the plan's table. Overturned by a measured value.
  ASSUMPTION: the Panel header names the tab with its `SETTINGS_TABS` label; overturned by a capture showing a different title.
- **Width rule.** Measured: the bundle keys the fraction on the tab-wrap's own width, not the viewport (row 4). Our app Sidebar is 252px (`Sidebar.tsx:107`), so at 1440 with the Sidebar open the Tab area is 1188px and the rule gives 25%; Infloww at 1440 (256px nav, 1184px) gives 25% too.
  ASSUMPTION: the plan's "left list 18.75% of the tab area at 1440" is read as the measured rule; the walk asserts 25% with the app Sidebar open and 18.75% after "Toggle sidebar" collapses it (Tab area 1440px). Overturned if the human wants 18.75% at a 1440 viewport regardless, which means a viewport media query instead of the container query.
- **Not applied yet.**
  ASSUMPTION: `NotAppliedYet` is added to the Panel parts though the plan's Phase 0 list omits it, because every Blob tab's Panel shows the sentence (ADR-0008) and one part keeps the wording single. Overturned if the Phases inline it.
- **Settings walk** (`python3 -I scripts/settings-check/walk.py [--allow-unbuilt all|<tab>,<tab>…]`, of-mirror-check style: Playwright sync, `BASE=http://localhost:${PORT:-3091}`, module docstring as its documentation, one `{"check","want","got"}` line per check).
  - Mocks: `/auth/me` (synthetic owner "tester"), `/chatter/me*`, `/admin/employees` ("Alpha One", "Beta Two", "Gamma Three"), `GET/PUT /admin/settings/{tab}` over an in-memory dict (a PUT stores the body and returns `{tab, config}`), `POST /auth/logout` (200), `/api/of/v2/payments/referrals/balance` and `/api/of/v2/payouts/requests/referral` (synthetic), any other `/api/**` `[]`. A request to a host other than localhost/127.0.0.1 is aborted and fails the run.
  - Walk: every non-legacy `SETTINGS_TABS` href (read from `app/lib/nav.ts` by regex on `nb("…", "/settings/…"`) at 1440×900, then at 390×844. The app's default theme is dark (`app/app/layout.tsx:67` sets `data-theme` only for light), so the token checks above prove only self-consistency; one light pass on `/settings/account` at 1440 (`chatterly:theme`=`light` in localStorage, as `scripts/of-mirror-check/dark.py:3`) asserts the measured literals: active row `color` rgb(52, 103, 255) on rgb(239, 244, 255), Tab list background rgb(245, 245, 245), header rule rgb(230, 230, 230).
  - Fails on: the "is not built yet." marker on a tab not allowed by `--allow-unbuilt`; any console error or page error; `scrollWidth > clientWidth` on the document; at 1440: Settings header ≠ 48px or ≠ `--if-header-h`, any tab row ≠ 64px or ≠ `--if-tab-h`, active row's computed `color`/`background-color` ≠ resolved `--if-accent`/`--if-accent-bg` (resolved through a probe element), Panel header ≠ 48px, Settings header title font-size ≠ `--if-fs-lg`, independent scroll broken (Tab list and panel body computed `overflow-y` ≠ `auto`, Tab area `bottom` ≠ viewport height ±1px, `document.scrollingElement.scrollHeight` > `innerHeight`), Tab list width off the rule by more than 1px (once with the Sidebar open, once on `/settings/account` after "Toggle sidebar"); at 390: the rows of the strip share one `top`.
  - Records every non-GET request as `[method, path, json body]`. `SCENARIOS` is a list of `(tab, name, run(page), want_writes)` that later Phases append to; each scenario checks the slice of the Write list it caused. The plain walk must add nothing to the Write list. Phase 0 ships `SCENARIOS = []`.
  - Writes `/tmp/settings-shots/settings-<tab>.png` (1440), `settings-<tab>-390.png` (390), and `settings-report.json` `{tabs: {tab: {viewport: {geometry…}}}, writes, failures}`; exits 1 on any failure.
  ASSUMPTION: `--allow-unbuilt` takes a tab list rather than a boolean so a Phase can never allow its own tabs (Cross-spec decision (c): Phases 1–4 name every non-legacy tab but their own, Phases 5 and 6 name none); overturned if the human prefers one switch.
  ASSUMPTION: the 390 PNG name carries a `-390` suffix, since the plan names only `settings-<tab>.png`; overturned by another naming.

### Cross-spec decisions

Stated word for word in every Phase spec of this effort; `docs/spec/settings-tabs/plan-review.md` `## Landing order` names each one's owner.
- (a) Every Acceptance block starts with `set -e` (flags a block already sets stay), and every negated check is written `! cmd || exit 1`, because `set -e` ignores a command inverted with `!` (`bash -c 'set -eu; ! true; echo reached'` prints `reached`).
- (b) `SETTINGS_PANELS` is keyed by the full href, `"/settings/<tab>"` (plan:154 "maps each href"); the `[tab]` page looks a tab up as `` `/settings/${tab}` ``.
- (c) Phases 1–4 land in any order after Phase 0, Phase 5 after all four, Phase 6 last. Each of Phases 1–4 runs the walk with `--allow-unbuilt` set to exactly the non-legacy Settings tabs other than its own, a fixed list never edited at landing; Phase 0 passes `--allow-unbuilt all`; Phases 5 and 6 pass none. A Phase never allows its own tabs, which is how plan:175 "unbuilt panels allowed in Phase 0 only" is read.
  ASSUMPTION: rung 4 (no Phase can block on another's order); overturned if the coordinator fixes plan order and wants every walk to catch a regression in an earlier Phase's tab, in which case each list shrinks to the tabs still unbuilt in plan order.
- (d) A Phase's report check selects the writes to its own paths (`[x for x in writes if x[1] == path]`) and asserts on those; a walk scenario checks only the slice of the Write list it caused; only Phase 6 asserts the whole Write list (the union).
- (e) Only the eleven 1440x900 `docs/screenshots/settings-<tab>.png` are ever committed, never a `-390` PNG (plan:129, plan:309). Phase 0 commits all eleven (the shell), each of Phases 1–5 overwrites its own tabs' PNGs, and Phase 6 refreshes all eleven from its final walk.
- (f) No Acceptance compares a PNG byte for byte (`cmp`) with another walk's. An Acceptance that commits PNGs runs `rm -rf /tmp/settings-shots` before its walk and copies its PNGs from that walk to `docs/screenshots/` in the same block, so the copied files are this run's by construction.
  ASSUMPTION: byte-stability of two walks on one commit is unobserved (rung 4/5); overturned if two walks on one commit are shown byte-identical, which would allow a `cmp` gate in Phase 6.

## Testing Decisions

Three seams, each at the highest public surface:
- **`SettingsShell.test.tsx`** renders the Settings `layout` (as a function component) with a child, through `renderWithProviders`, `FlagsProvider`, and `vi.mock("next/navigation")` / `UserContext` / `ChatterContext` as `AppShell.test.tsx:9-12` does. Cases: 11 rows in `SETTINGS_TABS` order, each with an icon; the row for the mocked pathname has `aria-current="page"` and no other does; the ✕ calls `back` once with history, and `push("/")` (not `back`) when `window.history.length` is 1; with the flag off no "Legacy" heading and no legacy href, with it on the four Legacy tabs follow; with a Chatter-only session the six Blob tab rows are absent and the other five remain. The Panel parts are covered here too (Constraints: a test per new component): `SettingsPanel` puts its title in `data-settings="panel-header"` and its children in `data-settings="panel-body"`; `Section` renders its title as a heading above its children; `FieldInput` forwards `value`, `onChange` and `disabled` to an `input`; `NotWired` is disabled with title "not wired" and clicking it calls nothing; `ToggleRow` with `notWired` is a disabled switch; `Field` labels its input; `NotAppliedYet` says the ADR-0008 sentence.
- **`settingsBlob.test.ts`** drives `useSettingsBlob` with `renderHook` and renders `SaveRow` from its `save` (via `createElement`), relay mocked at `fetch`. Cases: after a load of `{a:1,b:2}` and `set({b:3})`, the PUT to `/admin/settings/account` carries the full `{…defaults, a:1, b:3}`; a 500 on GET leaves Save disabled, `gateNote.failed` true, and `save.onSave()` sends no PUT (asserted on `fetch` calls); `reset()` restores the loaded value and sends nothing; after a good load, a failed refetch leaves Save enabled and `gateNote` the "Couldn't refresh" note (`StickySaveBar.tsx:173-183`).
- **`service/tests/test_settings_api.py`**: plain-assert, `import _harness` first and `_harness.bootstrap()` (`test_llm_tenant_keys.py:29-31`), `_harness.make_client()` and `/auth/login` as `:443-475`, `_harness.run()` (`:1001`). Cases from the plan: empty GET → `{tab, config: {}}`; PUT/GET round-trip; unknown tab → 404 (GET and PUT); list body → 400; 65 KB body → 413 with nothing stored; no session → 401 (GET and PUT); a Chatter session → 401 (a different principal, `tenant_keys_api.py:9-11`); two Agencies isolated; deleting the User removes its rows (CASCADE).
- The Settings walk is the browser seam for geometry and the Write list.

Prior art: `app/components/shell/AppShell.test.tsx`, `app/components/settings/stickySave.test.tsx` (gate asserted on the wire), `service/tests/test_llm_tenant_keys.py`, `scripts/of-mirror-check/settings_writes.py`.

## Acceptance

```sh
set -e
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/settings/SettingsShell.test.tsx lib/settingsBlob.test.ts
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
./venv/bin/python service/tests/test_settings_api.py
./venv/bin/python service/tests/test_llm_tenant_keys.py
# the migration chain has one head, ours (offline: reads the version files, no database)
test "$(PYTHONPATH=. ./venv/bin/alembic -c service/db/migrations/alembic.ini heads)" = "0065_user_settings (head)"
# --if-* is read only by app/components/settings/ (ADR-0009)
test -z "$(grep -rln -e '--if-' app/app app/components app/lib | grep -v -e '^app/components/settings/' -e '^app/app/globals.css$')"
# the four Legacy tabs are untouched
git diff --quiet main... -- app/components/settings/LegacySettingsTab.tsx app/components/settings/RestrictionsTab.tsx app/components/settings/TransferTab.tsx app/components/settings/AuditTab.tsx app/components/settings/LanesTab.tsx
(cd app && npx next dev --webpack -p 3091 >/tmp/settings-next.log 2>&1 &)
until curl -sf -o /dev/null http://localhost:3091/settings/account; do sleep 2; done
rm -rf /tmp/settings-shots
python3 -I scripts/settings-check/walk.py --allow-unbuilt all
python3 -I -c 'import json; r=json.load(open("/tmp/settings-shots/settings-report.json")); assert r["writes"]==[] and r["failures"]==[], r'
test "$(ls /tmp/settings-shots/settings-*.png | wc -l)" -eq 22
pkill -f "next dev --webpack -p 3091"
# manual: Read each /tmp/settings-shots/settings-<tab>.png, list visual diffs against the Ground-truth table, fix and re-run (up to three rounds); the rest goes into the ticket as VISUAL GAP:, with the font among them
# only the eleven 1440 PNGs are committed, never a -390 one (Cross-spec decision (e))
for t in account preferences security-org security-personal billing balance roles sales time-tracking messaging about; do cp "/tmp/settings-shots/settings-$t.png" docs/screenshots/; done
test -z "$(ls docs/screenshots | grep -e '-390\.png$')"
scripts/settings-check/export-check.sh   # the plan's throwaway-tree recipe, scoped to lines this effort added (hits inherited from before the effort base are reported, not failed)
```

## Depends on

None — Phase 0 is the base every other Phase builds on.

## Out of Scope

- Panel content of the 11 Settings tabs, their Write lists and `SCENARIOS` entries: Phases 1–5.
- Removing `NotBuiltYet` from the `[tab]` page and `nb()`/`notBuilt` from `nav.ts`, and the `nav.test.ts` "no notBuilt" case: Phase 5.
- `docs/settings-parity.md`, the `docs/NEXT_SESSION_SETTINGS_UI.md` §3 rewrite, the `docs/routes.md` Settings row: Phase 6.
- Avatar, bordered translation card, Messaging card, About logo and beta box, Learn-more link: each belongs to the Phase whose Panel uses it (YAGNI until then).
- The measured two-column field grid `repeat(2,350px)` (plan:34): no Phase uses it (Phase 1 sets one field per row), so it is a `VISUAL GAP:` that Phase 6's parity doc lists among the plan-decided gaps.
- A full dark-theme literal pass: the dark values are sampled, not measured (row 14 ASSUMPTION); the walk's one light pass covers the measured palette.
- Loading "Suisse Int'l" or RobotoRegular: licensed, served from Infloww's host (Constraints); recorded as VISUAL GAP.
- Per-field routes, a roles table, key validation inside a blob, any consumer of stored values: ADR-0007, ADR-0008.
- Measuring the Tab list at Infloww's 5/16 (<576px) step: below md we keep the strip.

## Further Notes

- The task brief's `service/models.py` and `service/migrations/…` are `service/db/models.py` and `service/db/migrations/versions/…` (observed); the plan's paths are right.
- CONTEXT.md's open ASSUMPTION on two 48px rows is settled by observation: the bundle has both `._about-header_rxwf7_9` and `._account-wrap_rxwf7_118 ._header_rxwf7_121` at 48px, and `._personal-info-wrap_rxwf7_132` subtracts both (`- 48px - 48px`).
- ASSUMPTION: the migration file is dated `20261013_0100` and numbered `0065` (house naming, rung 3; head observed at `0064_user_llm_keys` by `PYTHONPATH=. ./venv/bin/alembic -c service/db/migrations/alembic.ini heads`, which prints `0064_user_llm_keys (head)` on 2026-10-13). The Acceptance's `alembic heads` line goes red if another effort lands `0065` first, which means renumbering. The service never runs `alembic upgrade` (`service/tests/test_automation_queue_indexes.py:31-33`: new tables reach a box through `init_db`'s `create_all`), so the chain check guards the house convention, not a deploy step.
- ASSUMPTION: the Settings blob store has no read cache and no polling (one GET per Panel mount, as `useSellerConfig`); overturned if a Panel needs live updates.

## Review

codex, 2026-10-13 (blind call B, draft call D).

- B1 Two 48px rows are only an ASSUMPTION in CONTEXT.md. **reject**: settled by observation in this spec (Further Notes: `._about-header_rxwf7_9` and `._account-wrap_rxwf7_118 ._header_rxwf7_121` both 48px, `._personal-info-wrap_rxwf7_132` subtracts both).
- B2 The ✕ has no defined behaviour on a deep link with no history. **accept**: `router.back()` when `history.length > 1`, else `router.push("/")` (gap row 2, story 3, Interfaces, a SettingsShell test case), flagged ASSUMPTION.
- B3 Whole-blob PUT loses concurrent edits from two tabs. **reject**: whole replacement and no conflict rule is ADR-0007's decision; one owner per Agency, and YAGNI.
- B4 The Load gate contract is thinner than StickySaveBar's three states. **accept**: `loaded = !!q.data` without the `isSuccess` conjunct (house precedent `WebhookDispatchTab.tsx:81-87`), so a failed background refetch keeps Save on; `gateNote = loadGateNote(q)` already words the three states; new settingsBlob test case.
- B5 Auth tests skip the Chatter principal and impersonation. **partial**: added a Chatter session → 401 case (`tenant_keys_api.py:9-11`); impersonation writes are refused by the global session middleware (`auth.py:144-151`), not by this router, so no per-route case.
- B6 Preferences and agency name have documented consumers (`infloww-screens.md:81,264,477`). **reject** for Phase 0: Panel content and the note's reach are Phase 1's and ADR-0008's; nothing in this Phase reads or labels those values.
- B7 Test at two seams, the service route and the hook at `fetch`. **reject** as a change: the spec already has both, plus the walk.
- B8 The dark palette and Settings geometry are unproven by a Settings capture. **reject** as a change: already flagged ASSUMPTION under the gap table (dark slot mapping); geometry comes from the bundle's CSS.
- B9 Alternative: defer the table and API until a Panel first saves. **reject**: the plan's Phase 0 Decisions put the backend here (rung 2), and Phases 1, 3, 4 depend on it.
- D1 The walk accepts 25% at 1440, weakening the plan's "18.75% at 1440". **reject**: the plan's Phase 0 Decision binds a container query at ≥1200px; with the 252px Sidebar the Tab area is 1188px, and the walk also asserts 18.75% with the Sidebar collapsed (Tab area 1440px), so a list stuck at 25% fails. Already an ASSUMPTION under Width rule.
- D2 Independent scrolling (story 4) is never checked. **accept**: `data-settings="panel-body"` added; the walk fails on Tab list or panel body `overflow-y` ≠ `auto`, Tab area bottom ≠ viewport height, or a document that scrolls.
- D3 ADR-0009 wants every measured value as a token, but no type tokens exist. **accept**: `--if-fs-lg` 16px, `--if-fs` 14px, `--if-fs-sm` 12px, `--if-fw-title` 500, `--if-section-title-pb` 16px added; the walk checks the header title size.
- D4 Story 12 promises light colours but the walk checks only the default theme. **accept**: the default is dark (`app/app/layout.tsx:67`), so the token checks were only self-consistent; one light pass on `/settings/account` now asserts the measured literals (accent, accent-bg, list bg, rule). Out of Scope rewritten to exclude only a dark literal pass.
- D5 `SettingsPanel`, `Section`, `FieldInput` lack tests (Constraints: a test per new component). **accept**: cases added to `SettingsShell.test.tsx`.
- D6 `docs/screenshots/` does not exist, so the `cp` fails. **reject**: false outside the sparse workspace; `ls -d docs/screenshots` in the worktree lists it with existing PNGs.
- D7 `NotAppliedYet` is scope the plan's Phase 0 list omits. **reject**: Phases 1, 3 and 4 already depend on it (`phase-01-account-preferences.md:102`, `phase-03-roles-sales.md:138`, `phase-04-time-tracking-messaging.md:69`), and ADR-0008 wants one wording on every Blob tab; already flagged ASSUMPTION.


### Six hats

Six hats report (`.scratch/settings-tabs/SIX-HATS.md`), 2026-10-13, reconciled by the plan reviewer. Cross-spec items (a)–(f) are decided once under Implementation Decisions, "Cross-spec decisions", word for word in every Phase spec.
- White, "dark palette is sampled, not measured; dark is the default theme" (phase-00:29,155,104) — **reject** as a change: already the gap table's ASSUMPTION, the walk's light pass asserts the measured literals, and no dark Settings capture exists to measure (plan:48-50). Listed in plan-review Open questions.
- White, "the migration's parent `0064` is only observed head" (phase-00:164) — **accept**: Acceptance now requires `PYTHONPATH=. ./venv/bin/alembic -c service/db/migrations/alembic.ini heads` to print exactly `0065_user_settings (head)`; observed offline today printing `0064_user_llm_keys (head)` (rung 1). Further Notes rewritten.
- White, "no Phase builds the two-column grid `repeat(2,350px)`" (phase-00:154) — **accept**: Out of Scope now says no Phase uses it and Phase 6 lists it as a `VISUAL GAP:`.
- Red, "Phase 0 is a big bang" (phase-00:71) — **partial**: the contents are the plan's (plan:131-176, rung 2) and stay; the risk is recorded in plan-review (Phase 0 is Wave 1 alone, the critical path), and the ticket cut belongs to the Tickets step.
- Black (a), "no `set -e`" (phase-00:123) — **accept**: the block starts with `set -e`; it has no negated check.
- Black (b), "`SETTINGS_PANELS` keyed by last segment against plan:154 'each href'" (phase-00:80) — **accept**: keyed by the full href, looked up as `` `/settings/${tab}` `` (rung 2).
- Black (e), "Phase 0 commits 22 PNGs, Phase 6 only 11" (phase-00:138,141) — **accept**: Acceptance copies only the eleven 1440 `settings-<tab>.png` and fails on a `-390` PNG in `docs/screenshots/`; the `/tmp` count of 22 stays (walk output, never committed).
- Black, "no Acceptance runs the alembic migration" (phase-00:86) — **accept**, with a correction: the `alembic heads` line above checks the chain; the claim that a wrong `down_revision` surfaces at deploy is false, since the service never runs `alembic upgrade` (`service/tests/test_automation_queue_indexes.py:31-33`).
- Black, "no spec says what a Chatter sees on the six Blob tabs" (phase-00:116) — **accept**: the six Blob tabs carry `chatterHidden: true` (Interfaces `nav.ts`, story 28, a SettingsShell test case), rung 3 from `app/lib/nav.ts:10-11`; flagged ASSUMPTION.
- Green, "ship Phase 0 as three tickets: backend, shell, walk" — **partial**: the plan binds contents, not ticketing (agreed), but a backend / shell / walk split is three horizontal layers, which the Tickets step's rule ("Vertical, never one layer") forbids; the cut is left to that step.
- Blue items 1, 2, 5 and the migration-chain and Chatter lines — **accept**: decided above and in Cross-spec decisions (a), (b), (e).
