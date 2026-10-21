# Infloww OF Manager, automations and tokens: REA / static extraction (2026-10-18)

How the real Infloww desktop app (`/Applications/Infloww.app`, app.asar 5.7.20) builds the OF Manager shell,
which automation pages it ships, and the colour and type tokens it uses. Research only; no repo code changed.

Complements, does not repeat:

- `docs/of-manager-current-state.md`: screenshot pixel colours and our gaps.
- `docs/infloww-sidebar-palette.md`: sidebar geometry and the light palettes (shell and Messages Pro).
- `docs/adr/0001-infloww-geometry-our-colours.md`, `0010-messages-pro-infloww-palette-app-accent-elsewhere.md`,
  `0013-dashboard-bundle-via-rea-is-layout-truth.md`, `0014-smart-messages-are-per-fan-triggers-mass-messages-move-to-my-automations.md`.
- `docs/infloww-parity-matrix.md`, `docs/infloww-screens.md`, `docs/infloww-layouts/*.md` (dashboard, growth-smart-messages,
  growth-scripts, growth-vault-pro, growth-tracking-links, creators-*).

## Method and sources

- The REA `analyze_javascript_application` tool ran on the extracted ASAR. Its full output went to a file, and I read it with jq. Static grep work
  used read-only Python helpers (`python3 -I`), with the scripts kept outside the extracted tree. Nothing extracted was executed.
- **Shell (Electron):** `app.asar` was extracted into a fresh `/tmp` directory.
  - `dist/main/index.js` only does `require('bytenode'); require('./main.jsc')`, so the main process is V8 bytecode and was not decompiled.
  - `dist/renderer/index.html` and `index.6f9b6ded.js` are a loader that points at the remote SPA.
  - `dist/preload/browserview/of-base.js`, `dist/preload/pages/of/common.css`, `dist/preload/pages/main-Z6US7XYN.mjs` are the preloads injected into onlyfans.com.
- **The SPA (remote, React, antd, Tailwind and the "HB" design system):** `index.9f50f370.js` (17 MB) and
  `index.9fc9db54.css` (6.4 MB). These were downloaded earlier from the embed-remote-web host into `~/Downloads/infloww-remote-web/`.
  - Offsets below are byte offsets into these files.
- **Messages Pro** is a separate "lite" SPA on its own host, opened in a separate window. It is out of scope here.
- **Not available:** the i18n locale chunks. Keys such as `creators0172` and `settings0159` are resolved from the screenshots
  only, and the info-banner copy was not found as a literal.

Evidence labels: **O** = observed in source, **I** = inferred, **U** = unknown.

## 1. OF Manager shell

### 1.1 Overall frame (O)

`body` vars, from `index.9fc9db54.css` @655562 (duplicate @740157):

| var | value |
|---|---|
| `--root-header-height` | `calc(var(--controls-generous-min-height) + var(--sizing-named-micro)*2 + var(--main-banner-height))` = 36 + 16 + banner = **52px** without the banner |
| `--main-title-height` | 49px (page header 48px + 1px border) |
| `--main-content-height` | `calc(100vh - root-header - main-title)` |
| `--main-tab-height` | 54px |
| `--nav-width` | **256px**; `body._navCollapsed_*` sets it to **60px** |
| `--main-banner-height` | 0px. `body._hasBanner_*` overrides it, and `GlobalBanner` sets it at runtime |

### 1.2 Title bar (O)

- **Component:** `index$c` header @~11162438 in the JS. Classes are `_headerWrap_53zf2`, `_header_53zf2`, `_headerMacos`, `_headerLeftPart` and `_headerRightPart`.
- **CSS:**
  - `._headerWrap`: `flex column; min-height: var(--root-header-height); transition: height .2s`
  - `._header`: `flex row; space-between; min-height: 36px; padding: 8px 0; background: var(--element-reverse-emphasis-00)` (black in dark mode) and `app-region: drag`
- **Left side:**
  - `HeaderAside` (the sidebar toggle)
  - `FreeTrialRender`: "You're on a free trial" (caption1-strong, `element-emphasis-00`) and "N days left" (body2-strong, `element-emphasis-01`)
- **Right side, in order:**
  1. `StatusPageComponent`: polls a statuspage.io summary every 15s and shows Operational, Partial Outage or Major Outage with a level dot. Operational is the signal-go green `#58a744`.
  2. `UTCRender`: Globe04 icon, the offset, and an InfoCircle tooltip "The regular time zone you selected in Settings". Clicking it opens Settings.
  3. `ReferralsRender`, then `Leaderboard` (`/admin/leaderboard`).
  4. `SFW` switch: tooltip "Turn off and on Safe For Work mode", shortcut Shift S / Ctrl Shift S.
  5. `HeaderNotification`: Bell01 with a count chip; goes to `/admin/settings/notification`.
  6. `HeaderSignButton`, then `HeaderSetting` (the avatar menu).

### 1.3 Info banner (O, copy U)

- **Components:** `GlobalBanner`, `FreeTrialEndingSoon` (keys `header_freeTrial_endingSoon_001..008`) and `FreeTrialModal`.
  Class map `styles$4y` is at JS @11157565.
- **`._global-banner`:** background `--element-reverse-emphasis-00`.
- **`._global-banner-page`:**
  - background `--surface-signal-caution-emphasis-01` (`rgba(175,148,35,.145)`)
  - margin `0 16px 12px 16px`
  - radius `--control-generous-border-radius`, padding from the generous control
  - flex, space-between
- **Icon:** 16px wide, colour `--element-signal-caution-emphasis-00` `#af9423`.
- **Info variant (I):** the screenshot's info variant (dark blue background, blue icon) uses the signal-guide family (`#05a2dc`). The CTA is
  `--action-primary` `#f88056` (see `docs/of-manager-current-state.md` §0 for the measured pixels).

### 1.4 Left icon rail (O)

- **The rail is not a separate component.** It is the normal sidebar collapsed and locked.
  - `OfManagerWrap` (JS @13763021) calls `toggleMenu(true, true)` on mount. That sets antd `inlineCollapsed` and
    body class `navCollapsed`, so `--nav-width` becomes 60px.
  - On unmount it hides the BrowserView.
  - `._aside_dwdgg`: `flex column; overflow-y: auto; background: var(--element-reverse-emphasis-00); transition: width .2s`.
    The scrollbar is 0px.
- **Menus come from the server.** `createMenuByPower` (@10730038) maps server menu ids and `platformType` onto static configs
  `onlyfansMenu` and `inflowwMenu` (@10699289–10716000). `groupMenuByType` (@10731747) emits the platform group, a divider,
  then the common group. `RenderIcon` and `AsideFooter` are @11111189.
- **Platform selector** (`_selectPlatform_117te`):
  - CSS: `flex; gap: 12px; font-size: 20px; colour --tc-T0`; label font `--typography-text-body1-strong`
  - Icon: the OnlyfansColor logo, with a red dot for unreads
  - Popover options: OnlyFans, Fansly, mym, Fanvue

Rail order (icons confirmed by rendering the bundle SVGs against a screenshot crop):

| # | Item | Icon | Route / children |
|---|---|---|---|
| 0 | Platform selector | OnlyfansColor | popover |
| 1 | Dashboard (id 1) | Grid01 | `/admin/home` |
| 2 | OF Manager (id 2) | OnlyfansLine | `/of-manager/*` (see 1.6) |
| 3 | Analytics (id 14) | BarChart10 | creators, sexting (Employee reports), fans, message (Message dashboard), ai-reports under `/admin/analytics/` |
| 4 | Messages Pro | MessagesProLine (bubble + sparkle) | Separate lite window (`requestOpenLiteWindow("/_token")`); unread chip + Share04 pop-out. Static config nests it as id 37 under OF Manager; it renders top level (I: via server menu) |
| 5 | Growth (id 20) | LineChartUp04 | see section 2 |
| 6 | Share for Share (id 50) | SwitchHorizontal01 | discover, request, schedule, setting |
| - | divider | | |
| 7 | Creators (id 24) | UserSquare | `/admin/creators`, `/admin/creators/proxy` |
| 8 | Employees (id 26) | EmployeeLine | `/admin/employee/add-edit`, `/admin/employee/shifts` |
| footer | Settings | Settings04 | `/admin/settings` |
| footer | API keys | | `/admin/api-keys`, OF-only and permission-gated |
| footer | Help center | HelpCircle | `/admin/help` |
| footer | Book a call | | gated by server config; the version label shows when expanded |

Other routes that exist: `/admin/leaderboard`, `/admin/affiliates`, `/admin/home-dashboard` (id 754) and TP Manager (id 60).

### 1.5 Page header (O)

- **Component:** `PageHeader$1` (JS @7145588), styles `_15lbq` (JS @7142584). CSS:
  - `._page-header`:
    - `height: 48px; flex: 0 0 48px; display: flex; align-items: center; justify-content: space-between`
    - `background: var(--tc-B-nav); padding: 0 24px; border-bottom: 1px solid var(--tc-L1)`
  - `._page-header-text`: `colour --tc-T1; 16px / 600; user-select: none; flex`
  - `._page-header-utc`: `margin: 0 16px`, then `._utc`: `margin-right: 8px; colour --tc-T2; 14px`, followed by an (i) tooltip
- **Timezone:** `/of-manager` is in `LocalTimezoneUrls`, so the header shows the LOCAL machine offset. Other pages show the
  Settings timezone.
- **Right side:** `OfMessageToolbar` (JS @13110104). It renders only when the creator is verified and has a session cookie.
  - **Fullscreen** (SMessagefullscreen): `createOFWindow` opens an independent OF window, 1280x670, with tabs.
  - **Reload** (SMessagerefresh): `refreshBrowserView`, throttled to 2s.
- **Legacy CSS:** `_of-manager-box_1vxss` (an old Roboto 18px header and a 160px models block) is still in the CSS. It is dead.
  The current layout uses `_15lbq` and `_1b629`.

### 1.6 OF Manager routes (O, `ofManagerRouter` @13771143, pages @13768527)

| SPA route | OF path loaded |
|---|---|
| `/of-manager/home` | `/` |
| `post` | `/posts/create` |
| `notification` | `/my/notifications` |
| `message` | `/my/chats/` |
| `bookmarks` | `/my/collections/bookmarks/all` |
| `vault` | `/my/vault` |
| `queue` | `/my/queue` |
| `lists` | `/my/collections` |
| `statements` | `/my/statements` |
| `statistics` | `/my/statistics/statements/earnings` |
| `banking` | `/my/banking` |
| `my-profile` | `/{ofUsername}` |
| `setting` | `/my/settings` |
| `release-forms` | `/my/release-forms` |

These are OF Manager's sub-menu entries. OF's own nav is never used for navigation; navigation inside OF goes through `PAGE_GO` (1.8).

### 1.7 Creator column (O, `Index$D` / `ModelItem$3` @7164700–7170711, styles `_1b629`)

- **Width** is set inline:
  - expanded **192px**, collapsed **70px** (`defaultExpandWidth$3=192`, `defaultUnExpandWidth$3=70`)
  - CSS base is 300px with `transition: width .2s linear`
  - The screenshots are at about 1.25x, which explains the "about 250px" measurement.
- **Top row:**
  - Search input: placeholder `settings0159` "Search", 136x40, radius 4, 800ms debounce.
  - Refresh button: 38x38, 1px border `--tc-L1`. It refreshes unread counts at most once per 60s.
- **`GroupSelect`:** "All creators", antd Select, borderless, text `--tc-M1` (`#3467ff`), padding `0 16px`.
  Groups come from `/creator/group/list/v3`.
- **Row:**
  - padding `0 16px`
  - avatar 36x36, radius 4
  - status dot: 12px circle at the bottom right (verified = online icon, otherwise offline or warning)
  - name: 14px / 500 `--tc-T1`, 90px wide with ellipsis
  - hover `--tc-B-model-hover`; selected `--tc-B-model-active`
- **Badges:** all `padding: 1px 4px; radius 4px`, numbers 10px / 500 `#151515`.
  - Notification: bg `#FFC49A`, bell icon, caps at "99+".
  - S4S: bg `#A8C5FF`.
  - Message unread: bg `#FF7C71`, radius 22px, white text.
- **Switching creators:** clicking a row runs `selectCrmModel(creatorId)` and then `switchModel()`. The BrowserView is then destroyed and
  recreated with the new creator's session, cookie partition and proxy (I: one view per creator).
- **Empty state** (`OfNotHaveModel$2` @~7176388):
  - antd `Empty` illustration
  - Trans key `components-view0200`: "You have not yet tied a creator, if you need to bind one, you can bind on the
    "Creators Management" page." Styled 16px / 600 `--tc-T1`, centred.
  - A primary antd button, key `creators0172`, rendered as "Link account", that routes to `/admin/creators`. Users without
    permission see red text instead.
  - The column itself shows "No data".
- **BrowserView placeholder states** (`styles$4c` @12416719): `page-error`, `timeout-text`, `logout-text`,
  `no-OF-account-text` ("The creator has not yet bound an OF account..."), `no-OF-account-error-text`, plus
  `HideOFPage` (OnlyfansSolid icon and key `components-view0107`) and a Spin while loading.

### 1.8 How the OF page is embedded (O)

- **OF is NOT an iframe.** It is a native Electron **BrowserView** stacked over a placeholder div (BrowserView @12421653 and the IPC
  helpers @10857777).
- **Create:** the SPA measures the placeholder with `getBoundingClientRect()` and sends IPC `CREATE_BROWSER_VIEW` with
  `{url: "https://onlyfans.com" + ofPath, modelId, accountId, proxy, networkChannel, session, verified, username,
  modelName, avatar, ofUsername, ofUserId, x, y, width, height, tabId}`.
- **Lifecycle IPC:**
  - `UPDATE_BROWSER_VIEW` resizes the view. It is throttled to 200ms and fires on window resize and on `transitionend` of the creator column.
  - `HIDE_BROWSER_VIEW` fires when any global modal opens, because the native view paints above all DOM.
  - `REFRESH_BROWSER_VIEW`, `CLOSE_ALL_BROWSER_VIEW` and `DESTROY_VIEW_BY_UUID` cover reload and teardown.
- **Preload** `dist/preload/browserview/of-base.js` (siblings: `fansly-base.js`, `multi-base.js`):
  - Exposes `ipcRenderer` and `appEnv` through contextBridge, and pulls `GET_ACCOUNT_INFO` and `GET_BROWSER_INFO`.
  - Handles `PAGE_GO`, which runs `history.pushState` and then dispatches `popstate` so OF's own router navigates without a reload. On failure it sends `PAGE_GO_FAIL`.
  - Injects `dist/preload/pages/of/common.mjs` and `common.css`. The messages page also gets `of/messages.css`.

### 1.9 How OF's left nav is hidden (O, `dist/preload/pages/of/common.css` @841441)

```css
.l-header{position:absolute!important;pointer-events:none!important}
.l-header>nav{opacity:0!important;visibility:hidden}
#content{border-right:none!important;max-width:100%!important}
.l-wrapper__content{margin-left:0!important;max-width:100%}
.container{max-width:100%!important;padding:0!important}
.l-wrapper__sidebar{flex:1 0 300px!important;min-width:300px!important}
.b-chats__conversations-list{max-width:345px!important;flex:0 0 345px!important}
.banner_place,.b-login-posts-wrapper,.l-footer-static,.b-login-posts-outer,.contact_button.visible-lg{display:none!important}
.b-chats__item:hover{background-color:var(--tc-OF-fansitem-bg)!important}
body{-webkit-app-region:no-drag!important}
```

- OF's right sidebar (subscription, scheduled events) stays visible, and OF keeps its own dark theme.
- The same CSS file also declares the Suisse Int'l `@font-face` rules, loaded from Infloww's static asset CDN.
- **Exception:** the class `.l-header-show` brings the nav back in exactly one case, an independent window (`tabId > 1000`) on the
  profile page. In that case the logout button is removed (`main-Z6US7XYN.mjs` @62634).

## 2. Automations

All of these live under Growth (id 20). Routes come from the static menu (JS @10699289–10716035) and the routes list (@16913480).

| Page | Route | Notes |
|---|---|---|
| Smart Tags | `/admin/growth/smart-tag` | |
| Smart lists (Beta) | `/admin/growth/new-smart-lists` | id 751 |
| Smart lists | `/admin/growth/smart-lists` | |
| Auto-follow | `/admin/growth/auto-follow` | id 23, details below |
| Scripts | `/admin/growth/pro-written` | id 65, see `infloww-layouts/growth-scripts.md` |
| Vault Pro | `/admin/growth/vault` | id 114, see `infloww-layouts/growth-vault-pro.md` |
| Profile promotion | `/admin/promotion/profile-promotion` | id 80 |
| Free trial links | `/admin/promotion/free-trial-links` | id 81 |
| Tracking links | `/admin/promotion/tracking-links` | id 82 |
| Sensitive words | `/admin/growth/sensitive-words` | id 87, API `/growth/sensitive/list` |
| AI Copilot | `/admin/growth/ai-assistant` | id 90. Fields U |
| Smart Messages | `/admin/growth/smart-message` | id 116, details below |

**Auto-follow** (O, JS @12843170–12856000):

- **What it is:** a list, not a form. Subtitle: "Automatically follow fans whose subscriptions have expired", with a link "Learn more about settings".
- **Filters:** "Creator:" and "Auto-follow:" (on/off), plus a Reset button.
- **Table columns:** Creator name (avatar), Total follows, Today, Yesterday, 7 days, 30 days, Last followed
  ("MMMM DD, YYYY hh:mm A"), and Action, a per-creator Switch.
  - The switch is gated by permission `AutoFollow_Turn_on_off` (330).
  - It posts `/fans/autofollow-switch` with `{accountId, ...}`.
- **List API:** `/autofollow/task/statistic/page` with `{creatorAccountId, requireTotal, autoFollowOn}`.
- **Row click opens "Auto-Follow / Details"** (permission `AutoFollow_View_Details`, 331):
  - creator header
  - columns: Fans name, Total spend, Expiry date, Follow date, Actions (a chat icon that opens Messages Pro for that fan)
  - sortable by spend, follow date and expiry date, with a time range
  - API `/autofollow/task/records/page`
- **There are no tunable settings fields.** It is a simple per-creator on/off.

**Smart Messages** (O, module around JS @14540000–14700000). Product semantics are in ADR-0014 and
`infloww-layouts/growth-smart-messages.md`. New facts:

- **Trigger enum** (@16272389): `1 Nudge, 2 Delayed welcome, 3 Purchased, 4 Not Purchased, 5 Nearing expiry,
  6 Expired, 7 Resubscribe, 8 Birthday`.
- **Automated-message status values:** Scheduled 0, Active 1, Completed 2, Canceled 4.
- **API surface (`/message/smart-message/...`):**
  - `triggers?clientType=`, `auto-messages`
  - `create`, `edit`, `detail`, `terminate`, `withdraw`
  - `buyers`, `selector/senders`, `selector/sent-to-list`, `user/lists`
  - `priority-mass-messages`, `of-mass-messages/v4` (+ `/export`, `/detail`)
- **Related APIs:** `/message/scripts/v2`, `/message/script-placeholder`, `/message/script-tags/search`, `/model/config/message/price`,
  `/model/emoji/list`.
- **Legacy menu ids** (enum @3381261) show older standalone pages that were folded into Smart Messages:
  - WelcomeMessages 100, ExpiringFansMessages 101, ExpiredFansMessages 102
  - AllMessage 111, OfMassMessage 112, PriorityMassMessages 113
  - GreetingMessage 115, AutoMessage 119

**Auto-unsend** is per message, not a page (ADR-0014). **Share for Share** (id 50) has its own schedule and settings
pages, which are out of scope here.

## 3. Colour and typography tokens

There are two token systems. Both are in use at the same time.

**A. Legacy `--tc-*`.** These are set at runtime from `themeColorConfig` (JS @4453438). The light defaults are also in CSS `:root` @457593 and
a duplicate @460428. OF Manager pieces (page header, creator column, badges) use these.

| token | dark | light |
|---|---|---|
| `--tc-T0` | `#ffffff` | |
| `--tc-T1` | `#d9d9d9` | `#151515` |
| `--tc-T2` | `#b8b8b8` | `#666666` |
| `--tc-T3` | `#999999` | `#999999` |
| `--tc-T4` | `#666666` | |
| `--tc-B1` | `#262626` (creator column bg) | `#f5f5f5` |
| `--tc-B-nav` | `#151515` (page header bg) | `#FFFFFF` |
| `--tc-Home-B1` | `#151515` | |
| `--tc-B-th` | `#1a1a1a` | |
| `--tc-B-model-hover` | `#353535` | `#e4e4e4` |
| `--tc-B-model-active` | `#384360` | `#d7e4ff` |
| `--tc-B-S1` | `#384360` | |
| `--tc-L1` | `#444444` | `#e6e6e6` |
| `--tc-M1` | `#3467ff` (Link account, All creators) | `#3467ff` |
| `--tc-M-tag` | `#1890ff` | |
| `--tc-M-disable` | `#a8c5ff` | |
| `--tc-M-B` / `M-B1` / `M-B2` / `M-B3` | `#353535` / `#2f2f2f` / `#262626` / `#4D5159` | |
| `--tc-A1` | `#2ad4ac` | |
| `--tc-D1` | `#ff7c71` | `#ff7c71` |
| `--tc-W1` | `#ffa15f` | `#ffa15f` |
| `--tc-nav-header` | `#2B2C30` | |
| `--tc-btn-bc` | `#0D0D0D` | |
| `--tc-OF-fansitem-bg` | `#0091ea1f` | |
| `--tc-select-creator-b` | `#1E1E1E` | |
| `--tc-notification-B` | `#4D5159` | |
| `--tc-scrollbar-B` | `#454545` | |

Badge colours are hard-coded rather than tokens: notification `#FFC49A`, S4S `#A8C5FF`, message unread `#FF7C71`, numbers `#151515`.

**B. HB design system.** CSS `.theme-default` @6038300, `.theme-dark` @6063030, `.theme-light` @6084086. The title bar,
rail, banner and new components use these.

| token | dark |
|---|---|
| `--element-reverse-emphasis-00` | `#000000` (title bar, rail, banner bg; light theme `#ffffff`) |
| `--element-emphasis-00` / `-01` / `-02` / `-03` | `#ffffff` / `rgba(255,255,255,.62)` / `.38` / `.235` |
| `--action-primary` | `#f88056` (orange CTA; light `--light-brand-primary-00` `#fe7d50`) |
| `--action-secondary` / tertiary | `#b3d0f2` / `#bcddb8` |
| signal go / guide / stop / caution | `#58a744` / `#05a2dc` / `#fb609f` / `#af9423` |
| `--surface-signal-caution-emphasis-01` | `rgba(175,148,35,.145)` |
| navigation-rail-surface, navigation-drawer-surface | `rgba(255,255,255,.09)` |
| surface-level-01-emphasis-opaque-00 / -01 / -02 | `#171717` / `#0d0d0d` / `#0a0a0a` |
| surface-level-00-emphasis-opaque-00 | `#0d0d0d` |
| grayscale white-opaque-03 / -04 / -05 / -06 | `#3d3d3d` / `#262626` / `#171717` / `#0d0d0d` |
| `--surface-01-radius` / `--surface-pill` | 12px / 50px |
| `--controls-generous-min-height` | 36px |

- **Sizing scale (`--sizing-named-*`):** pico 2, nano 4, micro 8, mini 12, small 16, intermediate 20, medium 24, moderate 28,
  large 32, generous 36, abundant 40, huge 48 (all px).
- **Typography:**
  - Families: `"Suisse Int'l"` and `"Suisse Int'l Mono"`, with font files served from Infloww's static asset CDN (declared in `preload/pages/of/common.css`).
  - Scale (`--typography-text-*`): body2-base 400 14px / 1.1428; body2-strong 500 14px; caption1 12px; body1 16px (strong for the
    platform label); heading1 32px.
  - The OF Manager legacy parts use plain px: page header 16px / 600, UTC 14px, creator name 14px / 500, badge numbers 10px / 500.

## 4. Unknowns

- **U:** the main-process BrowserView implementation, which is bytenode, so the session partition naming and proxy wiring are not read.
- **U:** i18n copy for the info banner, `creators0172` (inferred to be "Link account" from the screenshot), and the AI Copilot field labels.
- **U:** whether Messages Pro's top-level rail position comes from the server menu. This is inferred from the screenshot against the static config.
- **U:** the exact info-banner variant class. Only the caution variant CSS was read.
