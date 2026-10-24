# Infloww screen inventory

Captured 2026-10-11. This lists every screen in Infloww's product UI so we can rebuild its navigation 1:1 in our Next.js app (`app/`).
Scope comes from `VISION.md`: we rebuild everything except "My Automations", and we do keep Auto-post and Auto-story. The targets are web, phone and desktop.

## How to read this doc

- **C[ref]** = CONFIRMED. The label appears verbatim in that source.
- **G** = GUESS. This covers inferred placement, order or wording, and any label we could not quote.
- **ours** = our own decision. This includes all Next.js routes and all Auto-post / Auto-story fields.
- Labels in "double quotes" are verbatim. Infloww's own text mixes Title Case and sentence case. We follow the v5.7.14 sidebar casing [BS] wherever we have it.

## Sources

| Ref | Source | What it covers | Confidence |
|---|---|---|---|
| BS | `ui-redesign/infloww-exact/BUILD_SPEC.md` | Sidebar order, top bar, Settings tab list. Written from real app screenshots (`infloww__*.png`), which were session-local and are gone | **High** for labels and order as of **v5.7.14**. May be stale for the current build |
| PAL | `ui-redesign/infloww-exact/PALETTE.md` | Colors sampled from real pixels; version string; which buttons are accent-colored | High (v5.7.14) |
| CL | `ui-redesign/infloww-exact/*.html` (clone pages that BS maps to screenshots) | Page titles, columns, filters | **Medium**. Built pixel-exact from the screenshots, then **wired to our relay and rewritten in places**; no pristine copy survives. Only the 23 BS-mapped pages count (title "Infloww — …"). Pages titled "Inflowwww — …" (ai-*, outreach-*, onboarding-*, tips-*, fans-*, content-*, auto-stories, vault-*, funnels, group, automations) are ours and never cited. Labels the clone extract tagged ours are excluded; ones it could not attribute are marked "[CL ?]" |
| GAP | `ui-redesign/infloww-exact/INFLOWW_GAP_TO_BUILD.md` | Feature descriptions (Dashboard shift cards etc.) | Medium (describes features, not exact copy) |
| H{id} | `https://help.infloww.com/en/articles/{id}` (Intercom help center) | Features, fields, in-app paths | **High** for features and fields. Each article is dated (see the table below). Text only, because screenshots were not readable |
| NEWS | https://news.infloww.com (changelog, 6 pages, Feb 2025 to Sep 2026) | Feature existence and dates | High |
| DL | https://infloww.com/download plus HEAD probes of `download.infloww.com` (2026-10-11) | Desktop installers | High (URLs return HTTP 200) |
| PROBE | HTTP probes of login.infloww.com, signup.infloww.com, app.infloww.com | What each host serves | High |
| MKT | https://infloww.com, https://infloww.com/pricing, https://infloww.com/blog/* | Feature and brand names | **Medium** |
| BDL | The v5.7.20 Dashboard bundle `~/Downloads/infloww-remote-web/index.9f50f370.js`, read statically 2026-10-19; `@N` is a byte offset. Notes in `.scratch/infloww-gap-deepdive/` (not committed) | Routes, settings tabs, feature flags, limits, permission ids | **High** for what ships; it cannot say what a given agency is shown (feature flags) |
| 3P | ofm-tools.com/infloww-review, outseeker.net/blog/is-infloww-worth-it-2026, ofmaitools.com, infloww.software.informer.com | Platform claims | **Low** |

Key help articles (id, then last-updated date):

| Area | Articles |
|---|---|
| Messages Pro | 262067 Getting started (2026-08-24), 406874 FAQ (2026-08-07), 262029 Split Inbox (2026-01-23), 262022 Idle mode (2026-01-23), 262023 SFW mode (2026-01-23), 545992 Multi-Window (2026-03-17), 418759 Fan insights panel (2026-09-01), 523936 Fan Insights (2026-04-14) |
| OF Manager | 262112 Navigating OF Manager (2026-01-23), 262111 Messages (Basic) (2026-01-23), 300186 sending messages (2026-09-01), 300694 tagging co-creators (2026-09-01) |
| Vault Pro | 262062 Getting started (2026-08-06), 766217 Media statistics (2026-08-27) |
| Smart Messages | 262059 Getting started (2026-01-23), 262070 Message and posts FAQ (2026-09-24), 262035 FAQs, 262045 Sequences/collections/auto-unsend (2026-01-23), 262055 Priority mass message (2026-08-28), 262034 OF Mass Message (2026-09-15), 262044 Smart Message Analytics (2026-01-23), triggers 262046-262051 and 262054 |
| Growth | 262064 Smart Lists, 262109 Auto-follow (2026-09-21), 262075 Tracking links (2026-08-18), 262032 Free trial links (2026-08-18), 262033 Profile promotion (2026-04-17), 262068 Sensitive Words, 751579 Share links (2026-08-18), 262042 Scripts (2026-05-04), 262073 / 348377 Script import |
| AI Copilot | 262040, 262039, 262038, 262036, 262037 (titles only) |
| Analytics | 276166 Creator Reports, 276167 Fan reports, 262078 Employee reports (2026-08-27), 262061 Message Dashboard (2026-08-26), 529697 Sales records (2026-08-12), 262021 Leaderboard (2026-09-04), 262077 Time zones (2026-07-17), 262080 Employee calculation rules |
| S4S | 262106 S4S settings, 262107 requests, 262108 Using S4S (2026-03-13) |
| Team and creators | 262104 Managing employees, 262098 Role permissions (2026-07-30), 262099 Shifts, 300963 Time tracking (2026-09-01), 262105 Creator accounts (2026-03-19), 262102 Custom proxies, 324929 Login+ / FaceID, 262072 Collaborating with agencies (2026-07-30) |
| Settings and billing | 262101 Personal/agency info, 451172 Language (2026-09-01), 463402 2FA (2026-09-01), 262030 AI Translator (2026-08-25), 673161 AI Translator prompt (2026-09-01), 262093 Payments (2026-09-07), 262091 Wallet / referrals |
| Platform | 262113 Discover Infloww CRM (2026-07-31), 262081 FAQ, 367655 App updates (2026-09-01), 518057 Safe Storage |

Caveat: about 40% of the articles carry the same date (2026-01-23), which looks like a bulk re-date. The v5.7.14 screenshots date to about early Jul 2026 (the leaderboard screenshot reads "Last updated : 2026-07-02" and "Jun leaderboard" [CL]), so help articles edited Aug-Sep 2026 are **newer** than BS/CL. A help article dated 2026-01-23 is not reliably newer.

Research notes these refs were taken from (not committed): `/tmp/infloww-research/{screens,clone-extract,help-a,help-b,automations-platforms,local-notes}.md`. Where two notes read the same article differently, both readings are given.

---

## 1. Global chrome

### 1.1 Left sidebar (top to bottom)

Primary order: v5.7.14 [BS], matched by the clone shell [CL]. The rows marked "help center" are items that only the help center names. Their placement is G. **No help article states a top-to-bottom order.** The research notes each proposed a different guessed order (e.g. Messages Pro or OF Manager first, Vault Pro as its own item); those guesses carry no weight against BS.

| # | Item | Sub-items (in order) | Status | Notes |
|---|---|---|---|---|
| 0 | "OnlyFans ▾" | Platform selector: OnlyFans / Fansly / mym / Fanvue | Label C[BS]; platforms C[help collections, MKT pricing] | We saw it as static. The other platforms come from separate help collections, and the control type is G |
| 1 | "Dashboard" | none | C[BS] | Not named in any help article |
| 2 | "OF Manager ▾" | "Home" / "New post" / "Notifications" / "Messages Basic" / "Vault" / "Queue" / "Collections" / "Statements" / "Statistics" / "Bank" / "My profile" / "OF settings" | C[BS] | H262112 lists: New Post, Notifications, Messages, Collections, Vault, Queue calendar, **Lists**, Statements, Statistics ("Creator statistics"), My Profile, Settings ("OF Settings"). "Lists" is help-only; "Home" and "Bank" are BS-only |
| 3 | "Analytics ▾" | "Creator reports" / "Employee reports" / "Fan reports" / "Message dashboard" | C[BS] | Help center also lists **"Sales records"** (H529697) and **"Leaderboard"** (breadcrumb, H262021). Placement G: Sales records at the end of Analytics. In v5.7.14 "Sales records" is a **tab inside Employee reports** [CL], and Leaderboard is in the **top bar** [BS]. **Conflict:** H262021 (2026-09-04, newer) breadcrumbs Leaderboard under Analytics, but H262091 still says Referrals sits "right beside" Leaderboard (top bar). We keep the top bar (BS) |
| 4 | "Messages Pro" | none. Pink unread badge plus "↗" | C[BS] | Opens in its own window. An arrow icon next to it opens an additional window, C[H545992] (which spells it "Message Pro") |
| 5 | "Growth ▾" | "Smart Messages" / "Smart lists" / "Auto-follow" / "Vault Pro" / "Scripts" / "Profile promotion" / "Free trial links" / "Tracking links" | C[BS] | Help center adds **"Sensitive Words"** ("Growth > Sensitive Words", C[H262068]) and **"AI Copilot"** ("Growth > AI Copilot", C[H262038]). Placement G: both at the end of Growth. **"Share links"** is reached from Free trial links / Tracking links, C[H751579]; as its own sidebar item it is G (we treat it as a sub-page). **Vault Pro** under Growth comes from BS only; no help article gives its sidebar path, and one research note guessed it is a top-level item. BS wins. Sensitive Words' article (H262068) is undated in our notes, so we cannot tell whether it is newer than v5.7.14 or simply missing from the screenshot |
| 6 | "Share for Share ▾" | "Discover creators" / "Requests" / "S4S schedule" | C[BS] | Help center: "S4S Setting", "Request", "Schedule", "Discover" C[H262108, H262106]. "S4S Setting" may be newer than v5.7.14 (G). **S4S is built** (Phase 3 of `docs/plans/infloww-parity-next-steps.md`), bounded to this deployment's agencies (ADR-0011); see 3.6 |
| 7 | divider | | C[BS] | |
| 8 | "Creators ▾" | "Manage creators" / "Custom proxy" | C[BS] | Help center: "Creators > Manage Creators" / "Custom Proxy" C[H262102, H262105] |
| 9 | "Employees ▾" | "Manage employees" / "Shift schedule" | C[BS, CL] | **Conflict:** help center calls the section **"Manage Employees"**, with an **"Employees"** item/tab and **"Shift Schedule"** C[H262104, H262099]. H262104 is dated 2026-01-23 (possibly bulk re-dated), so it is not provably newer than v5.7.14; the rename is G. One research note reads H262104 as tabs Employees / Organization Chart / Shift Schedule; another reads "Organization Chart" as a left panel on the Employees page. The clone's Manage employees page has a left rail ("Views", "Employee groups") [CL], which favors the panel reading (G) |
| 10 | "Settings" (bottom) | 11 tabs (see 3.10) | C[BS]; "bottom-left" C[H262098, H463402] | |
| 11 | "Help center" | none | C[BS] | In-app "Intercom support messenger" C[H262072] |
| 12 | "Version 5.7.14" (muted) | none | C[BS, PAL] | |

The clone's current sidebar (`dashboard.html`) also includes "AI Selling", "Onboarding", "Tip Rewards", "Fan Intelligence", "Auto Posts", "Auto Stories", "Create Post" and "Vault AI". These are **Inflowwww additions, not Infloww**.

### 1.2 Top bar (left to right)

| Element | Label / behavior | Status |
|---|---|---|
| Collapse | panel-collapse icon button | [CL] |
| Trial chip | "You're on a free trial" / "7 days left" | [CL]; only shown during a trial (G) |
| Status pill | "Operational" | C[BS]. Linking it to https://status.infloww.com is G (the status page itself is C[MKT]) |
| Timezone | "UTC-10:00" (the user's regular time zone) | C[BS]. Its source is Settings > Your Preferences "regular time zone ... on the Manager" C[H262077] |
| Referrals | "Referrals" | C[BS]. "right beside" Leaderboard C[H262091] |
| Leaderboard | "Leaderboard" | C[BS, H262091] |
| SFW toggle | "SFW". Shortcut Cmd+Shift+S / Ctrl+Shift+S | C[BS, H262023] |
| Bell | Notifications page | C[BS]; "🔔 icon in the top navigation bar" C[H262067] |
| Avatar / username menu | "Add account" / "Log out" | C[BS]. The help center adds "Add / Switch Account", "Add New Account", "New Window" and the account status "Login required" C[H262072], plus "Billing notifications", "Clock in and out" and "Timezone" as translatable menu items C[H451172]; that those three sit in this menu is G |

### 1.3 Global overlays and dialogs

| Overlay | Labels | Status |
|---|---|---|
| Idle mode (Messages Pro, after 10 min with no input) | Full-screen overlay; "Return to Messages Pro" | C[H262022] |
| Update prompt | "Update now". Required updates restart the app; optional ones can wait until the next restart | C[H367655] |
| Login | email and password; "Try a different method" (email code) if 2FA is on | C[H262113, H463402] |
| Settings / Referrals / Leaderboard / Notifications | Full overlays over the shell: header title + close "×" (Notifications uses "Back") | [CL] |

### 1.4 Theme (v5.7.14, dark) [PAL]

- Sidebar `#000`. Canvas and cards `#262626`, border `#333`.
- Thread and composer `#151515`. Side panels `#232323`. Selected row `#353535`.
- Accent `#4166f6`: "Online Fans", "UNLOCK PPV", "Send", the Total-earnings figure. Green `#67d1ae`: "Notifications" button, online dots. Expired avatar red `#f0483e`.
- Font: Suisse Int'l, Regular 400 and Medium 500 only (`@font-face` in app.asar 5.7.20, files from fe-static-assets.infloww.com/font/); heavier weights are browser-synthesized. Our stand-in is Instrument Sans (app/app/layout.tsx). Radii: cards 12, buttons 8-10, pills full.

---

## 2. Route map (ours)

All routes below are **ours**. Infloww exposes no URL routes (desktop app). Existing app routes (`/`, `/chat/[accountId]/[fanId]`, `/inbox`, `/messages`, `/stats`, `/vault`, `/setup`, `/settings`, `/automations`, `/growth`, `/group`) should redirect to these or be folded into them.

| Nav item | Route (ours) |
|---|---|
| Dashboard | `/` |
| OF Manager > {item} | `/of-manager/[section]`. Sections: `home`, `new-post`, `notifications`, `messages`, `vault`, `queue`, `collections`, `statements`, `statistics`, `bank`, `profile`, `settings`, `lists` |
| Analytics > Creator reports / Employee reports / Fan reports / Message dashboard / Sales records | `/analytics/creator-reports`, `/analytics/employee-reports`, `/analytics/fan-reports`, `/analytics/message-dashboard`, `/analytics/sales-records` |
| Messages Pro | `/messages-pro` and `/messages-pro/[creatorId]/[fanId]`. Desktop: a separate window. Web: a new tab |
| Growth > Smart Messages | `/growth/smart-messages` (tabs `?tab=automated` / `?tab=priority`), `/growth/smart-messages/new`, `/growth/smart-messages/analytics` |
| Growth > Smart lists / Auto-follow / Vault Pro / Scripts / Profile promotion / Free trial links / Tracking links / Share links / Sensitive Words / AI Copilot | `/growth/smart-lists`, `/growth/auto-follow`, `/growth/vault-pro`, `/growth/scripts`, `/growth/profile-promotion`, `/growth/free-trial-links`, `/growth/tracking-links`, Share links as a tab of the two links pages (public report `/share/<id>.<secret>`), `/growth/sensitive-words`; AI Copilot has no Growth page (the Messages Pro Composer's "AI" button) |
| Auto-post / Auto-story (not in Infloww) | `/growth/auto-post`, `/growth/auto-story`. Placed under Growth because Infloww keeps all its automations there (see section 4) |
| Creators | `/creators`, `/creators/proxy` |
| Employees | `/employees`, `/employees/org-chart`, `/employees/shifts` |
| Settings | `/settings/[tab]`. Tabs: `account`, `preferences`, `security-org`, `security-personal`, `billing`, `balance`, `roles`, `sales`, `time-tracking`, `messaging`, `about` |
| Top bar | `/referrals`, `/leaderboard`, `/notifications` |
| Share for Share | `/share-for-share/discover-creators`, `/share-for-share/requests`, `/share-for-share/schedule`, `/share-for-share/settings` ("S4S settings", its own page and nav entry; any other section is a 404). Bounded to this deployment's agencies (ADR-0011) |

---

## 3. Screens

### 3.1 Dashboard

- Menu: "Dashboard" C[BS]. Route (ours): `/`.
- Purpose: an agency-wide earnings and team snapshot.
- Layout: KPI header, then charts, then the team cards and the creators table, each in its own card.

Key controls and blocks:
- Header: "UTC-10:00"; dropdown "Net earnings" / "Gross earnings"; segmented period "Yesterday" / "Today" / "This week" / "This month" [CL]. The header title was rewritten by us; Infloww's is unknown.
- "Total earnings" (accent figure) [CL, PAL]. Channel split "Subscriptions" / "Posts" / "Messages" / "Tips" / "Referrals" / "Streams" [CL]. The split by channel is also C[GAP].
- "Employee sales" bar chart [CL].
- "Earnings by channel" [CL ?, probably ours]. "Fans & subscriptions", "Daily earnings" and "Creators overview" (its table, search and "Export CSV") were probably **added by us** [CL ?]. None of these four is Infloww evidence.
- "My shifts" and "Current clocked-in employees" cards [GAP; CSS classes `.myshifts`, `.clocked`]. The exact titles are G.
- Banner "Your 7-day free trial has started." [CL, low]. Our audit flagged our copy of it as fake. Do not rebuild it.

### 3.2 OF Manager

- Menu: "OF Manager ▾" C[BS]. Route (ours): `/of-manager/[section]`.
- Purpose: embeds the live OnlyFans web UI for the selected creator, so you act "on behalf of the Creator" C[H262112].
- Layout: the sidebar submenu picks the OF page, and the main area is the embedded OF site [BS]. Our clone added back/forward/reload; Infloww's own chrome there is G.

Sub-items (BS labels; descriptions from H262112):

| Sub-item | What it shows | Notes |
|---|---|---|
| "Home" | the OF feed | C[BS] only |
| "New post" | the OF composer: "compose a new post on behalf of the Creator" | Fields are OF-native: caption, media, schedule, "Expiration Period" C[H262070]; price and tags G |
| "Notifications" | new subscribers, tips, messages | |
| "Messages Basic" | the embedded OF chat, plus a messaging widget. Filters: custom fan tags, "Priority", "Unread", "Unread with Tips", Oldest/Newest first | Widget fields C[H262111]: "Creator notes", "Fan notes", "Country/Region", "Auto-renew Status", "Last paid", "Buy rate", "Spending habits", "Purchasing trends", "PPV timeline", "Source", "Birthdate", "Infloww name", "Fan lists". "+Timer" C |
| "Vault" | the OF vault (videos, GIFs, photos). Tag editor: edit icon > "Create" > notes > "Save" | C[H300186] |
| "Queue" ("Queue calendar") | "scheduled posts, messages, and streams for each Creator, including the publishing date and time" | C[H262112]. Read-only from Infloww's side (G) |
| "Collections" | fan lists, bookmarks, post labels | |
| "Statements" | earnings and payouts by day, week or month. Download icon > select Creators > date range > "Download" | C[H262112] |
| "Statistics" | fan growth, earnings, reach, engagement | |
| "Bank" | the OF banking page | C[BS] only |
| "My profile" | picture, bio | |
| "OF settings" | OF account settings. For example "Fans and following": "Auto follow back my fans", "Unfollow when the subscription has ended" | C[H262109] |
| "Lists" | saved lists, bookmarks, post labels, saved subscribers, tags | C[H262112]; missing from BS |

### 3.3 Messages Pro

- Menu: "Messages Pro" (pink badge, "↗") C[BS]. Route (ours): `/messages-pro/[creatorId]/[fanId]`.
- Purpose: a multi-creator chat workspace. Feature names: "Multi-Creator Inbox", "Real-Time Notifications", "Online Fans Smart Filters" C[H262067].
- Layout: 3 panes under two tab strips.
  - Top strip: "Creator tabs". A "+" picks a creator; each tab shows the name and unread total; tabs reorder by drag. Then the "Fan tabs" strip ("Open in new tab"; each tab shows the name, online status, unread count and a signal; up to 100 tabs) C[H262067, H406874].
  - Left pane: the "Fan List" / inbox C[H545992], background `#232323`.
  - Center pane: the conversation and composer, background `#151515` [PAL].
  - Right pane: the "Insights panel" / "Fan insights" C[H262067, CL].

**Header buttons** [CL]: "Home", "Add a Creator", "SFW", "Online Fans", "Notifications". "Online Fans" and "Notifications" are also confirmed as accent-colored buttons [PAL]. "All Models" and "Group chat" are ours (exclude).

**Left pane header** [CL]: creator name, a "New" button (menu items mass message / message online fans / post; "broadcast" is ours), inbox selector "All inboxes" + gear, "✎ Lists", and a row of the creator's OF chat-folder chips. Empty state "No conversations found". The sort label "Needs reply" and its options are [CL ?, probably ours].

**Inbox tabs, filters and sort:**
- "All" with sort "Newest first"; "Focus mode" works only in All + Newest first. It shows a "new messages banner" with a count, and clicking it refreshes C[H262067].
- Messages Pro chips: "All" / "Unread" / "Pinned" / "Priority" [CL]; "Unread tips" [CL ?]; "↩ Owe reply" is ours.
- **Correction:** "Priority" / "Unread" / "Unread with Tips" / custom tags (e.g. "With Tips") / "Oldest/Newest first" are C[H262112] for **OF Manager > Messages Basic**, not Messages Pro. Do not merge the two lists.
- The Split Inbox group filter is a dropdown in the inbox header (G). The clone's "All inboxes" selector is the likely spot [CL, G].
- Fan-row badges: "New" (subscribed in the last 7 days), 🔥 (bought a PPV in the last 7 days), ❄️ (not messaged in 72h), ❌ (expired), "Off" (stopped renewing). An orange total-spend number replaces the avatar C[H262067]. Spend pill `$0` [PAL].

**Split Inbox** C[H262029]:
- Splits one creator inbox into up to **9** groups.
- Screens: "Choose the number of groups", and "Reassign fans to different groups" (moves a fan).
- Steps: Choose the number of groups, assign employees (verbal only, with no binding in the app), filter the inbox.
- Admin and Owner by default; configurable per role. The location of the group-count control is G.

**Idle mode**: see 1.3. **SFW mode** C[H262023]: blurs media in Messages Pro, Vault Pro and Scripts; "Media View" reveals it.

**Multi-Window** C[H545992]:
- Menu: an arrow icon next to "Message Pro" opens another window.
- Tabs: right-click a creator tab > "Open in a new window". Fans: right-click in the Fan List > "Open in a new window".
- No window limit. On restart, only the last closed window's creator is restored.

**Chat header and fan actions** C[H262067]:
- Click the avatar for "Subscription status", "Earnings", "Special offers" and add-to-lists.
- Actions: "restrict", "block", "report", "hide chats", "mute notifications".
- "Gallery" icon (all media exchanged). 📈 by the creator name opens "Mass message statistics" / "Online fans message statistics".
- Chat link: copy a link that deep-links into the app.
- Message records: sender details, "Read receipts", "PPV message statuses".
- Clone header [CL]: fan name + status ("Last seen …" / "Offline"); icons star, mute, notes, pin; "Gallery", "Find"; pop-out (Infloww label probably "Open new", G); refresh; kebab. Thread empty states "Select any conversation to start", "No messages yet"; bubbles show "Sent by …". The persona button, AI strip and "0 scheduled" chip are ours.

**Composer:**
- Buttons "AI" · "Scripts" · "PPV" · "Aa" · "Send" [CL]; "Send" C[PAL].
- Bottom toolbar icons, in order [CL]: upload, GIF, vault, calendar (schedule), tag, mention (@), "Aa", translate, then "Send". Reply strip "Replying to: …" with ✕ [CL].
- 😀 emoji with ⚙️ favorites (up to 40, "Save"); "GIF" C[H262067].
- ⏱️ "Timed message" (delay of 1-60 min, "Start") and "Timed reminder" (countdown with alarm, "Start"); cancel with ❌ C[H262067].
- "Tag other Creators" > "Add"; "More" > "Add a tag" > "Release form" C[H300694].
- AI Translator icon: "Translate messages from fans into" > "Use translation" C[H262030].

**PPV / price composer:**
- The "PPV" button [CL] and the "UNLOCK PPV" button on a message [PAL] are confirmed.
- The price field label is **unknown**. Clone PPV row: "PPV", "$" input (0.00), "lock text" checkbox, schedule "at", "Clear" [CL, medium]. The "free previews" stepper is ours.
- PPV pricing in automations is called "PPV price" C[H262059].

**Vault picker** ("Vault Pro window") C[H262062, H262067]:
- Card: red status icon (last send/purchase), last price, notes, tags. Grey overlay = the fan already has it.
- ⓘ opens "Media details". The price icon shows history: "Purchased", "Sent (free or paid)", "Unsent (free or paid)", "Posted in feed".
- Unsend icon at the lower left > "unsend".
- Search covers hashtag, note and previous PPV caption; there is a duration filter.
- Clone picker [CL ?, partly rewired]: chips "All" / "Photos" / "Videos" / "GIFs", "All folders", sort Newest/Oldest, "No media here".

**Scripts in chat** C[H262067, H262042]:
- The "Scripts" button opens a list; "Manage" opens the "Manage scripts" window ("# Manage tags", "+ Add script", 👁️ preview, ✏️ edit).
- Placeholder `Press "/" + keyword to quickly search scripts` [CL]. Searching with "/ + keyword" is C[H262042].
- The next sequence step is auto-suggested. "Quick adding a new script" saves the current text as a script.

**AI Copilot (Beta)**:
- In chat: the "AI" button with modes "Casual", "Re-engage", "Tip request", "Sexting", plus "Regenerate" C[H262036 per one research note; another read the AI Copilot articles as titles only, so treat as medium].
- It suggests replies only and never auto-sends; "Real-time auto-suggestions" C[MKT].
- Separately, Infloww ships **AI Chatbot (Beta)**, which does auto-send: per fan it can be turned off, paused or resumed, and it hands the chat to a human ("Human action needed": spending threshold, suspects bot, low confidence, special request, tip, upset after PPV, keyword alert) C[BDL]. It is gated by the `inAutoChatWhiteList` feature flag, so not every agency sees it. See 3.10 and §4.

**Online fans mass message** C[H262067]:
- "Message all" opens the "Message online fans" window ("Send a message to online fans").
- Fields: tags, media, price, exclude list, and filters (total spend, subscription duration, tip amount). "Exclude Creators" toggle; "exclude fans you've already messaged" (hours); "Send".
- Stats statuses: "Complete" / "In progress" / "Failed".

**Notifications button** C[H262067]: quick reply ("Reply"), open a fan tab, purchases and tips. The "Message withdrawn" notification has "View details".

**Fan insights panel** (right; drag to reorder, order saved per employee, collapsible blocks) C[H418759, H523936]:

| Block | Fields |
|---|---|
| "Spending behavior" ("Spending history" in H418759) | Total spend, Last spend, PPV (total/avg), Tip (total/avg), Highest spend; older: Purchase rate. [CL] adds "Purchases over time" |
| "Organization metrics" | "Spending power": Top 1% / Top 5% / Top 10% / Top 25% / Top 50% / Bottom / No Spending History / Insufficient Data. "Chargeback risk": High (>66%) / Medium (33-66%) / Low (0-33%). Visibility is set per role |
| "Subscription" | Status, Cost, Duration, Auto-renewal |
| "Profile" | Nickname (feeds {name}), Birthday, Source, Location, Local time, Salary frequency, Last pay date, Salary |
| "Lists" | the fan's lists; ⚙️ quick editor (add, remove, create) |
| "Notes" | template fields Age, Job, Preferences, Hobbies, Nationality, Gender, GF, Others; ⚙️ edits the template; fan notes max 13,000 chars |
| "PPVs" (bottom nav) / "PPV timeline" | Buy rate, Highest price, Lowest price; per PPV "Copy as draft", "See chart" |
| "Creator notes" | shared notes about the creator's style; max 10,000 chars; autosaves |

The Apr 2026 article says "six blocks": Spending behavior, Organization metrics, Subscription, Profile, Lists, Notes C[H523936]. H418759 (Sep 2026) is newer and says "Spending history".

Clone right pane [CL]: header "Fan insights"; bottom tabs "Insights" / "Sales" / "Notes". Its Profile card shows Nickname, Tags, Language, Birthday ("Select date"), Location, which differs from the help list above; prefer the help list (newer). Sales tab: purchase history Date / Gross / Net, "Vault history" [CL ?]. The "Generated profile note" in Notes is ours.

### 3.4 Analytics

Menu: "Analytics ▾" C[BS]. Reports share these controls: date range, NET/Gross toggle, creator filters and export. The report time zone comes from Settings > Your Preferences C[H262077].

| Screen | Route (ours) | Layout and tabs | Key controls / columns |
|---|---|---|---|
| "Creator reports" C[BS] | `/analytics/creator-reports` | Tabs "Overview" / "Creator performance" [CL]. Sections: "Earnings summary", "Growth rate", "Earnings trends" (Hour/Day/Week/Month), "Earnings by channel", "Earnings breakdown" (pie), "Creator statistics"; on the performance tab: "Earnings growth", "Earnings breakdowns", "Earnings heatmap", "Chargebacks" C[H276166] | Filters: date range, "Creator tag", "Creator", "Show net earnings", "Reset" [CL]. Customizable metrics table. Breakdown rows: Gross earnings, Platform fee, VAT collected, Chargeback ratio, Refunds, Net earnings [CL]. "Hide $0 creators", "Export CSV" [CL ?, partly ours]. Metric catalog in H276166 (earnings, fans, messaging) |
| "Employee reports" C[BS] | `/analytics/employee-reports` | Tabs "Overview" / "Sales records" / "Employee performance" [CL]; "Chatting statistics" C[H300963]. Notices: "Clocked hours are not differentiated by platform…", "The sales data is based on your organization's sales settings." + "Learn more" / "View sales settings" [CL]. Right of tabs: date-time range, "Shown by day", "Filters" [CL]. Overview: "Employee sales" chart, "Employee comparison" (three "Select" pickers; "No comparison data"), "Sales ranking" (sort "Descending") [CL]. Sales records tab: "Only the selected window", "Load 50 more" [CL ?]. Employee performance tab: "Hide $0 rows", "Show totals only" [CL]. The "Automation performance" tab is ours | Views: "Total by employee", "Total creators by day (daily) by employee", "Total by creator by employee", "By creator by day by employee" C[H262078]. Filters: date/time, creator, employees. 27 metrics (Sales … Fans chatted per hour (clock hours)). Sale status Pending/Complete/Reverse. "Clocked hours" > "Export" (xlsx) |
| "Fan reports" C[BS] | `/analytics/fan-reports` | Left creator column: "Search", refresh, "All creators", creator cards [CL]. Charts: "New fans (growth & trends)" (All / Renews / New subscribers), "Total fans (growth & trends)" [CL]; "Fan value & LTV" [CL ?, probably ours]; fan retention table and chart C[H276167]. "Fan cohorts", "Spend distribution", "Fan data" and its "Download CSV" are **ours** | Date range, "Shown by day", "Net earnings" [CL]. Metrics: Total Spend, Tips, PPV Sales, Subscription Length; downloadable C[H276167] |
| "Message dashboard" C[BS] ("Messages Dashboard" in places) | `/analytics/message-dashboard` | Tab "Direct messages" (employee DMs only) C[H262061] | Filters: Creator, Date, Sender, Price range, Purchased status, Message status (Sent / Unsent / withdrawn), Fan ("Sent to"), Type (script / without script). Columns: Purchase status, Message earnings, Reply time, Sent to, Gross/Net. Actions: open chat, unsend. Export: max 100 senders, max 1 month, queued, link valid 30 days. Refreshes every 10 min. Clone (v5.7.14) [CL]: title + "Learn"; search "Search message text"; "Sender:" "All senders"; "Creator:" "All creators"; "Sent to:" "Fan username / display name"; "Price:" $ min - $ max; "Purchased:" All / Purchased / Not purchased; "Status:" All messages / Priced (PPV) / Free; "Reset" / "Search"; "No new messages" + "Last updated: …"; columns Sender, Creator, Sent to, Message, Sent time, Price, Purchased; empty "No data". "Direction:" is [CL ?]; ingest/ledger panels are ours |
| "Sales records" C[H529697]; sidebar placement G | `/analytics/sales-records` | Table | Filters: Creator tag, Creator, Employees/groups, Sales types, "Show unassigned sales", Date (day/week/month/custom), Export CSV. Columns: Date & time, Employee, Creator, Fan, Earnings, Gross revenue, Net revenue, Type, Rule, Assigned by, Status, Action ("Reassign") |
| "Leaderboard" | `/leaderboard` | see 3.9 | Top-bar item in v5.7.14 [BS]; listed under Analytics in the help center |

### 3.5 Growth

Menu: "Growth ▾" C[BS]. The help center confirms the path for each item ("Growth > X").

#### 3.5.1 Smart Messages

- Route (ours): `/growth/smart-messages`.
- Page: "Smart Messages List" with "New Message" [CL]. Tabs "Automated Messages" / "Priority Mass Messages" C[H262055, 2026-08-28] ([CL] says "Mass Messages"; the help label is newer, use it).
- Header: creator chip, "Learn", "New Message" [CL]. Filters: search "Search message", Status, Trigger, Sent to, Start date, Date created, Created by; "Reset" / "Search" [CL]. Status option values are [CL ?] (ours added run-health values).
- Columns: Messages, Status, Trigger, Sent, Purchased, Actions; empty "No Data" [CL]. The screenshot showed an empty list, so the clone has **no** first-hand trigger catalogue or "New Message" modal (the clone's modal is ours).
- "+New Message" opens the "Create Message" pop-up, which lists the type. Only the menu label "Subscriber Welcome" is confirmed C[H262070]; the other labels are G (we assume they match the trigger names).

Automation types, in **priority order** (only the highest match sends) C[H262059]:

| # | Trigger | Help title | Specific rules |
|---|---|---|---|
| 1 | "Birthday" | "Wish fans a happy birthday" | immediate or delay |
| 2 | "Expired" | "Message fans after their subscription expires" | hours after expiry; optional discount; runs every 12h |
| 3 | "Nearing expiry" | "Message fans when their subscription is about to expire" | hours before expiry; discount; only fans with auto-renew off |
| 4 | "Resubscribe" | "Greet fans when they resubscribe" | immediate or delay |
| 5 | "Purchased" | "Follow up fans who purchase a PPV" | right after a PPV purchase, or after a delay |
| 6 | "Delayed welcome" (menu: "Subscriber Welcome") | "Greet fans when they subscribe" | delay; active welcomes send in random order |
| 7 | "Nudge" | "Message fans when they come online" | targets 'Online Fans'; "Immediate send" / "Delayed send" |
| - | "Priority Mass Message" (PMM) | H262055 | not a trigger; "Schedule the message" (now or a future date); about 300-700 fans/h; max 5,000 fans |
| - | "OF Mass Message" (OFMM) | H262034 | not a trigger; OF-native |

Wizard (identical for every trigger) C[H262051 and siblings]:

1. **"Segment your audience"**: a list (e.g. "Fans") or "smart filtering rules". Exclusions:
   - "Fans who were sent direct messages, automated messages or priority messages recently" (last N days/hours)
   - "Fans who previously viewed attached media"
   - "Fans with unread messages"
   - "Creator(s)"
   - "Lists" (max 50)
2. **"Set the rules"**: immediate or after a (random) delay; trigger-specific hours and discount.
3. **"Choose the frequency & scheduling"**: "Send only once" / "every time".
4. **"Build the message or sequence"**: text with `{name}`, emoji, import a Script, Vault Pro media, "PPV price", "Tag" a co-creator. Up to 5 follow-up messages with pauses ("Add follow-up message"; old UI "+New line").
5. **"Collections"**: up to 10 variants, one picked at random per send. Table headers "Collection", "Message 1", "Message 2".
6. **"Auto-unsend settings"**: "Unsend messages" (after h/min, within OF's 24h limit) and "Stop message sequence" (when the fan replies; on by default).
7. "Save".

Lifecycle C[H262059, H262035]:
- New items are "Active". Set the status to "cancel" to stop one. Editing is not allowed once active.
- To reuse: "Duplicate" > "Publish".
- Review the targeting with "You send message to" > "Show more".

**PMM** wizard: Segment (same exclusions) > "Schedule the message" > Build > Auto-unsend C[H262055]. The schedule field labels are not documented (G: a date-time picker).

**OF Mass Message**: "1. Segment your audience" (include lists / smart rules, exclude lists) > "2. Schedule the message" > "3. Build the message" (text, emoji, Vault Pro media, PPV price). None of PMM's exclusions C[H262034]. The changelog adds "Add purchasers to a list" and "Export OFMM history" C[NEWS].

**Smart Message Analytics** C[H262044]. Route (ours): `/growth/smart-messages/analytics`. Its placement inside Smart Messages is G.
- Filters: Search; Status "Scheduled" / "Active" / "Completed" / "Cancelled"; Trigger; "Send to"; "Start date"; "Create date"; "Create by".
- Columns: Sent, Purchased, Earnings, Attachments, Price, Sent to, "Creator by", Start date, End date, Create date.
- Admins can export.

#### 3.5.2 Smart lists C[H262064]

- Route (ours): `/growth/smart-lists`. Page "Smart lists" with "Create list" [CL].
- Layout [CL]: left creator panel ("Search", "All creators"); right: search "Search list name", "Create list"; columns "List name", "Criteria", "Incl. expired", "Fans", "Actions" (edit/delete). Sample criteria text: "Total spend: $1-$40", "Total spend: $200-no upper limit", "Subscription less than 4 day(s)"; pill "Includes" / "Excludes". The clone's rule-builder modal ("Create smart list", presets, "+ Add rule") is ours.
- Editor (modal) types:
  - "Segment by total spend": "Set your segments", include-expired checkbox, "Create". Each segment becomes a list; only one segmented list is allowed.
  - "New fans": days subscribed, "Create". Several allowed.
- No free-form rule builder. First scan takes about 30 min; refresh every 6h; name suffixes are randomized.

#### 3.5.3 Auto-follow C[H262109]

- Route (ours): `/growth/auto-follow`.
- A table of creators with an on/off toggle in the "Action" column. Columns: "Creator name", "Total", "Today", "Yesterday", "7 days", "30 days", "Action" [CL]; "Last run" [CL ?].
- Notice: 'If "auto follow back my fans" is enabled in OnlyFans, the number of follow displayed will include fans who have active subscriptions that have been followed.' + "Learn more about settings" [CL].
- The clone's filters ("Creator:", "Auto-follow:"), presets and editor are ours; Infloww's filters are unknown.
- Click a creator to open "Auto-Follow details": "Total spend", "Follow date", "Expiry date", "Actions" (a message icon that opens Messages Pro).
- Follows **expired** fans only. Syncs every 24h.

#### 3.5.4 Vault Pro C[H262062, H766217]

- Route (ours): `/growth/vault-pro`. Title "Vault Pro", creator chip, "Learn", "Add media" [CL] ("+ add media" in H262062).
- Clone [CL]: left rail headed "Custom" with category names and per-type counts; "Caption" search "Search media by PPV caption"; sort "Recent"; "Media:" pills "All" / "Photo" / "Video" / "GIF" / "Audio". **Conflict:** "Video" [CL, Jul 2026] vs "Videos" [H262062, 2026-08-06, newer]. AI describe, price, review queues and harvest tools are ours.
- Layout:
  - Left: category ("folder") menu with search.
  - Top: type tabs "All" / "Photo" / "GIF" / "Videos" / "Audio".
  - Search dropdown "Note" / "Hashtags" / "PPV caption". Sort: "All time", "Go to date", "Recent", "Most liked", "Highest tips", "Ascending", "Descending".
  - Filter toggle "Hide content viewed or unlocked by fan, or posted on creator's feed". "Grid" / "Table" switch. Bottom batch bar.
- Upload: link the OF fan account, drag into "Add media", per-file fields, "Bulk upload".
  - Per-file fields: Categories / Tag co-Creators / Hashtags / Notes / Descriptions / Suggested prices.
  - Limits: images max 100 MB, videos max 4 GB.
- "Batch edit window": the same fields plus "All", then "Save". "Delete" (max 40). File info: "Uploader", "Uploaded time".
- Stats: "Sent count", "Unlock count", "Unlock rate", "Revenue". Folder totals.
  - Duration filter: "Less than 1 minute" / "1 to 5 minutes" / "5 to 10 minutes" / "More than 10 minutes".
  - Permission "View media statistics".

#### 3.5.5 Scripts C[H262042, H262073, H348377]

- Route (ours): `/growth/scripts`. Sections: "Tags", "Sequences", "Manage Scripts".
- "+" menu: "Add Sequence" > "Create new" / "Import from tag"; "Import" > "From Excel" / "From other creators".
- Sequence editor: name and description; "Normal script" / "Conditional script" (up to 3 options); up to 200 scripts; drag to reorder; "Publish".
- Share to creators: select > pick creators > "Confirm".
- Stats per tag: count, conversion, revenue. Per script: 📧 sent, 🛒 purchased, 💰 sales.
- Excel import: columns A=name, B=text, C=notes; each sheet is a tag. Limits: name 64, tag 32, text 1000, note 246.
- The clone's tabs (Singles / Script ladders / Simulate / Live offers / Canned lines) are Inflowwww (exclude).

#### 3.5.6 Profile promotion C[H262033]

- Route (ours): `/growth/profile-promotion`.
- Page "Profile promotion" > "Promotion campaigns" with "Create promotion", "Learn more", "Campaign insights", "Show expired". Columns: Promo / Claims / Revenue / Actions; empty "No data" [CL]. Left creator panel ("Search creators", "Creators" count) [CL].
- Info bullets [CL]: "Campaign insights are available for up to 10,000 of the most recent promotion campaigns created within the past 365 days"; the last-click attribution line (see 3.5.7).
- Setting rows [CL, medium]: "Auto-activate campaign", "Default offer duration" (No duration / 3 / 7 / 14 / 30 / 90 / 365 days; values [CL ?]), "Add fans to list". The "Keep promos running" automation box is ours.
- Create pop-up:
  - target (new / expired / both)
  - type ("free trial" / "first-month discount")
  - offer limit (none, or up to 100)
  - offer expiration (none, or up to 30 days)
  - optional message
  - "Create"
- One active campaign per type. Toggles "auto-activate campaign" and "Add fans to list" ("Select the list"). Actions: "Deactivate".

#### 3.5.7 Free trial links C[H262032]

- Route (ours): `/growth/free-trial-links`. Tabs "Links list" / "Dashboard" [CL].
- "Create free trial link" pop-up: name (locked after creation), offer limit (up to 100), offer expiration (up to 30 days), trial duration (up to 12 months), tags, channel source, optional "List", "Create".
- Filters: creator, search "Search free trial link name", Source, Tag, Date created, "Show deactivated links", "Show net earnings" [CL]. Buttons "Create free trial link", "Export" [CL].
- Notice [CL]: "Each fan's spending is always attributed to the last free trial link, tracking link or promotion campaign that has been clicked by the fan." + "Learn more".
- Clone columns (v5.7.14) [CL]: "Free trial links", "Date created", "Claim", "Spend/Claim", "Promo cost", "Earnings", "Actions". Help (2026-08-18, newer) uses "Claims" / "Promo costs" and more columns (below).
- Columns: Claims, Spend/Claim, Promo costs, Earnings, Profit, AEPS, ROI, Source, Tag, List, Last updated. Dashboard: "Profile funnel", Total claims, Spend/claims, Total earnings, Average ROI.

#### 3.5.8 Tracking links C[H262075]

- Route (ours): `/growth/tracking-links`. Tabs "Links list" / "Dashboard"; same attribution notice; search "Search tracking link name", "Source", "Tag", "Date created", "Show deactivated links", "Show net earnings" [CL]. Clone columns: "Tracking link", "Date created", "Clicks", "Subs", "Subscription CVR", "Actions" [CL]. Dashboard tab: "Profile funnel", "Profile visitors", "Link performance" [CL]. The "Internal redirect links" section is ours.
- "Create link" opens the "Create tracking link" pop-up: name (locked after creation), "channel source" (TikTok / Reddit / Twitch / custom), "List" ("Add new list"), "Create".
- Columns: Clicks, Subs, Subscription CVR, Promo costs, Earnings, Spending CVR, Profit, CPC, EPC, CPS, AEPS, ROI, Source, Tag, List, Last updated, Actions (✏️ promo cost, "Deactivate", "Details").
- KPIs: Total clicks, Average CPC, Total subs, Average CPS, Subscription CVR, Total earnings, Average ROI.
- Controls: creator filter, net/gross, source, tag, time, export CSV (sent by email), "Show expired". Autosync every 2h.

#### 3.5.9 Share links C[H751579]

- Route (ours): the "Share links" tab of `/growth/free-trial-links` and `/growth/tracking-links`; the public report is `/share/<id>.<secret>`. Reached from Free trial links / Tracking links > "Share links".
- "Create share link": name, creator(s), links (up to 100), metrics to expose ("Include earnings"). Result: access code and link. Max 50 per agency. The link "may take up to 30 minutes"; "Once ready, the link can be viewed for the next 7 days", shown in an "Expires on" column C[BDL @14128428].
- Public page sections: "Overview", "Links by creator", "Performance chart" (30 days), "Time zone" (UTC+0). Refreshes hourly.

#### 3.5.10 Sensitive Words C[H262068]

- Route (ours): `/growth/sensitive-words`.
- "+Add Sensitive Word" (modal; "+Add the next column"; "Save"), "Import from Excel" (template; "Upload"; "Import"), "Export Excel".
- Max 32 chars, no special characters. Blocks posts, scripts, DMs, group messages and mass messages.

#### 3.5.11 AI Copilot C[H262038 path "Growth > AI Copilot"]

- Route (ours): none; ours is the Messages Pro Composer's "AI" button only (Casual, Re-engage, Tip request, Sexting).
- Personas ("Creating AI Personas"); permissions; credits.
- Dashboard: "Free credits unused", "Total credits used", "Credits to be allocated", "AI message ratio", "Assigned credits", "Buy AI credits". **G**: from research notes with no article id recorded (the AI Copilot articles were read as titles only).
- Billing subtab "AI Copilot" [CL]. Sidebar placement G.

### 3.6 Share for Share (built: Phase 3 of `docs/plans/infloww-parity-next-steps.md`)

- Menu: "Share for Share ▾" with "Discover creators" / "Requests" / "S4S schedule" C[BS]. The help center also has "S4S Setting".
- Behavior: Infloww schedules and **auto-publishes** cross-promo posts and removes them after 24h C[H262108].
  - "Create Post": caption up to 5000 chars, media from a dedicated S4S vault ("Add from Vault"), "Save". The help article says up to 10 media; the v5.7.20 bundle caps a post at **5** C[BDL @13802032]. Up to 20 posts per creator; "Set as Primary Post".
  - "Limit": 1/2/3 per day; "Discovery Page Visibility".
  - "Schedule": monthly calendar; statuses "In progress" / "Will be posted shortly" / "Completed" / "Canceled".
  - Requests: "Accept" / "Skip" / "Decline"; "Received" / "Sent" tabs.
- app.infloww.com hosts the "Infloww Share for Share" web community C[PROBE].
- **Ours (built in Phase 3** of `docs/plans/infloww-parity-next-steps.md`, spec `docs/spec/phase-03-share-for-share.md`), bounded to this deployment's agencies (ADR-0011), never Infloww's community directory:
  - Routes: `/share-for-share/discover-creators`, `/share-for-share/requests`, `/share-for-share/schedule`, and "S4S settings" as a fourth page and nav entry, `/share-for-share/settings`. Owner-only: a chatter is refused.
  - S4S Setting: opt-in per Creator (off by default), Discovery Page Visibility, Limit 1/2/3 per day, display name, @username and avatar URL, up to 20 posts of 5000 characters with one Primary post, each with up to 5 media from the Creator's own vault, copied to the Relay by the Creator's own session and uploaded to the partner's account at slot time (ADR-0015). A partner Creator can be blocked; a Creator sends at most 50 S4S requests a day (UTC).
  - Discover creators: the S4S projection of opted-in, visible Creators of every agency on this deployment, the owner's own included, and nothing else.
  - Requests: Received / Sent with Accept / Skip / Decline and the sender's Cancel; Accept books one S4S slot per side at the agreed time.
  - Schedule: the monthly calendar with Infloww's four statuses plus "Failed" (an Inflowwww extra). Each slot posts the partner's Primary caption and its media plus an @mention on its own Creator's account only, through the Auto Post path, and comes down after 24h through the unsend automation. Posting runs only while the deployment's `S4S_LIVE_POSTING` flag is on; it is on by default (`S4S_LIVE_POSTING=0` turns it off), and a slot that comes due while it is off ends "Canceled" with the reason "live posting off".
- Used below as the analog for Auto-post.

### 3.7 Creators

| Screen | Route (ours) | Contents |
|---|---|---|
| "Manage creators" C[BS] | `/creators` | Columns: Creator, Nickname, Proxy, Creator ID, Action [CL]; "Platform & session" and "Employees who worked it" [CL ?]. Footer "Total: N creators", "Per page" 10/25/50 [CL]. Filters: platform, tag, connectivity status, assigned employee, account status C[H262105]; clone filter bar: "Creator name or id", "Any platform", "Any proxy", "Any connectivity", "Any employee", "Any account status", "Reset" [CL] (its connectivity values are ours). Primary button: help says "Add creator"; the clone's "Connect a creator" cURL modal, "Re-check health" and row actions are ours. Modals below |
| "Custom proxy" C[BS] | `/creators/proxy` | "Manage your custom proxies", "+ Add new proxy"; columns Proxy label, Host, Port, Type, Creator, Proxy status, Actions [CL]. Add modal: hostname/IPv4, port, "Add proxy" C[H262102]; the clone's add form (Label, Scheme, Auth & notes) is mostly ours. Empty "No data" [CL]. Without a custom proxy each creator gets a unique automatic proxy |

Manage creators modals and statuses C[H262105]:
- "Add creator": image, Creator name, Gender, "Next", platform, link.
- "+ Link Creator Account" / "Link Another Creator Account". Actions ⋮: "Deactivate" ("Deactivate creator") / "Delete".
- Connectivity statuses: "Connected", "Disconnected", "Pending connection", "Not connected", "2FA required", "ID verification".
- Recovery actions: "Link account - need to reenter password", "Log in to account via OnlyFans/Login+".

2FA / FaceID (Login+) C[H324929]: when OF asks for face recognition, paste the authentication link into the Login+ phone app, which opens the OF face-recognition page; tap "Confirm". There is also "Auto-Login".

### 3.8 Employees

| Screen | Route (ours) | Contents |
|---|---|---|
| "Manage employees" C[BS] ("Employees" tab C[H262104]) | `/employees` | Left rail [CL]: "Views" ("All employees" / "Activated" / "Deactivated"; other views ours) and "Employee groups". Header "All employees"; "Batch actions" ("Batch edit group" / "Batch edit roles" / "Assign" C[H262104]; the clone's menu items are ours); "+ Add employee" [CL] / "+ Add Employee" [H262104] (Name, Email address, Phone number (optional), Role, Group, "Submit"); filters "By employee :" / "By Creator :" / "By status :" (Activated/Deactivated) / "By role :", "Reset", "Search" [CL]; columns ☐, Employee, Assigned Creators, Role, Status, Actions ("More" > "Deactivate" / "Delete") [CL, H262104]; "Performance (all-time)" [CL ?] |
| "Organization Chart" C[H262104]; tab-vs-panel G | `/employees/org-chart` | Group tree; ⋮ on the agency or a group > "Add sub-group" ("Add Group Settings", group name) > "Submit" |
| "Shift schedule" C[BS] | `/employees/shifts` | Week calendar; "Create shift(s)" [CL, v5.7.14] / "Create Shifts" [H262099; date not recorded, so which is newer is unknown] opens the "Shifts" window with "+ Add Shift": start/end, Creators, employees, repeat weekly (days), "Repeat Ends" ("Never" or a date), "OK"; 🗑️ to delete. Filters Employee / Creator / "Reset" / "This week" [CL]. ⚙️ "Shift Settings": "Allow multiple employees to work on the same shift for the assigned Creator." Shift history: Total Earnings, Scheduled Shifts, Shifts Worked C[H262099, H262104] |
| Roles and permissions | `/settings/roles` | Lives in Settings > Role Settings (3.10) |
| Time tracking | `/settings/time-tracking` | Configured in Settings; reported in Employee reports > "Clocked hours". "Clock in and out" is a menu item C[H451172] (G: avatar menu). Dashboard card "Current clocked-in employees" [GAP] |

### 3.9 Notifications, Referrals, Leaderboard (top bar)

| Screen | Route (ours) | Contents |
|---|---|---|
| Notifications (bell) C[BS] | `/notifications` | "Back", "Notifications", "Mark all read", gear [CL]; section "OnlyFans notifications" [CL]; tabs All / Subscriptions / Purchases / Tips / Comments / Mentions / Likes / Messages [CL ?, JS-rendered]. The "Delivery channels" modal, "Live activity" and "Clear errors" are ours. Types: new subscribers, tips, messages, "Message withdrawn" > "View details" C[H262067] |
| "Referrals" C[BS] | `/referrals` | "Referral Program", "Partner with Infloww / Get paid for inviting your network", card "Invite an Agency": "earn 10 % of first year subscription", "Start Earning Now" [CL]. The OF referral-earnings cards are ours. "Infloww's Wallet": Total earnings, Available to withdraw, Pending earnings, Withdrawn. Referral table: Email, Type, Join date, Total spent, Total commissions, Status C[H262091] |
| "Leaderboard" C[BS] | `/leaderboard` | "Infloww Leaderboard". Hero "You're not on the Infloww Leaderboard yet." + body text ("…didn't make the Top 1,000 in the Jun leaderboard or the 2025 annual ranking… The Leaderboard updates monthly…") + "Add creator", "Last updated : … UTC" [CL]. The "Your agency ranking" block (Creators/Employees tabs, period chips, "Rank by") is **ours**, not Infloww. Toggle "Global ranking" / "Country ranking"; "Share my agency's rank" ("Download the image" / "Generate a link"); ranked by net earnings; Owners and Admins by default C[H262021] |

### 3.10 Settings

- Menu: "Settings" (bottom-left) C[BS, H262098]. Route (ours): `/settings/[tab]`.
- Layout: one page with a **left list of 11 tabs** C[BS]. The clone kept the tab names and a few labels, but almost every panel body was replaced by ours, so Infloww's original per-tab fields come from the help center only.

| # | Tab (BS label) | Sections and fields | Source |
|---|---|---|---|
| 1 | "Your Account" | Personal: Picture, Username ("Edit"). "Agency info": Picture, Agency Name ("Save"). Agency name feeds the Leaderboard | C[H262101, H262021] |
| 2 | "Your Preferences" | Report time zone ("Your preferred time zone for Creator and fan reports"), regular time zone (top bar), week start day; "Language Settings": English / Spanish. Clone hint: weekly-report start day, display mode, platform sync [CL ?] | C[H262077, H451172] |
| 3 | "Security (organization)" | "Two-factor authentication" toggle (Owner/Admin); per-employee 2FA status Active/Inactive, last login, "Reset" | C[H463402, CL] |
| 4 | "Security (personal)" | Your own 2FA status ("Enabled on <date>") and backup codes. No session list | Tab C[BS]; fields C[BDL] |
| 5 | "Billing" | Subtabs "Infloww subscription" / "AI Copilot"; "Pricing plans", "Update card", "Cancel subscription", "Billing information" [CL]. Invoice table > "Make a Payment" > "Pay with Wallet", "Credit Card" (external page) / "Bank Transfer (Wire Transfer)" > "Pay" > "Yes"; statuses Unpaid / Partially Paid / Paid | C[H262093]; [CL] medium |
| 6 | "Your Balance" | The Infloww Wallet (`/wallet/balance`, `/wallet/records`): Transaction History, Withdraw balance, Commission; payout method and withdrawal permissions. H262091 adds Total earnings / Available to withdraw / Pending earnings / Withdrawn | Tab C[BS]; fields C[BDL, H262091] |
| 7 | "Role Settings" | "Roles" tab: list with "Operations" column ("Edit", "Set Permissions"); "+ Add Role" [H262098] / "Add role" [CL] ("Role Name", "Description", "Submit"). Permission editor: radio buttons per page, tabs "Operations" / "Growth" / "OF Manager" (maybe more); data scope "All data" / "Self and subordinates" / "Data about self". Known permissions: "View media statistics", Spending power / Chargeback visibility, Split Inbox, AI Copilot. Roles: Owner, Admin; examples Manager, Chatter, Assistant. The bundle's full matrix: about 93 menu permissions (each with its own data range where the menu allows one) and about 230 function permissions (add, edit, delete, export, send, terminate...), in the columns Menus / Function permissions / Data permissions, with platform tabs General / OnlyFans / Fansly / mym / Fanvue; roles can be disabled, and a role in use cannot be deleted. Default roles in a new agency: Owner, Admin, Team Leader, Chatter, Creator (live capture) | C[H262098, H262039, H766217, BDL] |
| 8 | "Sales Settings" | Clone hints: "Exclude welcome messages", exclude the 20% OnlyFans fee [CL ?]. Shift settings (multiple employees per shift). Earnings types and attribution rules: Messages = Shift schedule / Message sender / Converters; Posts and Tips = Shift schedule / Converters; Subscriptions, Streams & Referrals = shift schedule (opt-in to chatters) | C[H262080] |
| 9 | "Time tracking" | "Edit", enable toggle, "Auto clock out time" (min 1 min), clock-in reminder, "Save" / "Cancel" | C[H300963] |
| 10 | "Messaging settings" | "AI translation": "Enable AI translation in Messages Pro for employees in your organization" [CL] / "Enable AI Translation" (36 languages); AI Translator prompt "Edit" > "Save" | C[H262030, H673161] |
| 11 | "About Infloww" | Panel title "About" [CL]; contents G (version and build info) | Tab C[BS]; fields G |

The v5.7.20 bundle has one more tab the v5.7.14 sidebar capture lacks, **"AI Chatbot (Beta)"** (settings tab id 79), shown only to agencies with the `inAutoChatWhiteList` feature flag C[BDL @10699139]:
- An autonomous chatter per creator that replies and sells. Persona (hobby, zodiac, nationality, personality, favourite expressions, sexual favourites, others); Purpose: All / Sales / VIP conversion; Conditions: all fans, new fans and/or lists, or high spenders over $X, plus exclude lists.
- A spending threshold switches the bot off so a human takes over; keyword alerts (up to 10,000 keywords, Excel/CSV import and export) pause it and notify.
- Media library: priced bundles ($3 or more; at least one active bundle and at least 20 media in the vault's "Sales folder" before it can be turned on), story sets (at least 2 steps, at least one free and one paid, $3-200), and script sequences with "Enable chatbot use".
- A per-agency cap on active chatbots; an organization-wide off switch.
- Reports: "AI chatbot reports" at `/admin/analytics/ai-reports` (fans assigned and engaged, PPVs sent and unlocked, unlock rate, VIP conversion, sales).

Ours has no AI Chatbot: the selling AI Chatter engine was deleted on purpose (`c32cd7bc`; the owner's 2026-10-19 decision keeps AI to Copilot reply suggestions, no selling chatbot). Our Auto-reply (`/growth/auto-reply`, §4.1) sends one casual reply to a fan nobody answered in time, and never sells.

---

## 4. Automations

**Infloww has NO "My Automations" menu and NO Auto Post or Auto Story feature.**

Evidence:
- The v5.7.14 sidebar [BS] has neither.
- The help center has none: 9 collections and about 120 articles were crawled, see help-a §19.
- The changelog has none: all of news.infloww.com, 59 entries, Feb 2025 to Sep 2026 [NEWS].
- Neither do https://infloww.com/pricing or https://infloww.com [MKT].
- Infloww's own blog tells creators to post stories by hand in the OF app (https://infloww.com/blog/onlyfans-stories, MKT).
- Posting goes through OF Manager > "New post" (OF-native composer) and "Queue" (OF-native calendar) C[H262112].

The only auto-publishing of posts in Infloww is S4S (3.6). Ours is built (Phase 3 of `docs/plans/infloww-parity-next-steps.md`), bounded to this deployment's agencies (ADR-0011), and posts through the Auto Post path only while the deployment's live-posting flag is on.

Infloww's automations all live under **Growth**:

| # | Automation | Where | Source |
|---|---|---|---|
| 1-7 | Smart Message triggers: Birthday, Expired, Nearing expiry, Resubscribe, Purchased, Delayed welcome, Nudge | Growth > Smart Messages > Automated Messages | H262059 |
| 8 | Priority Mass Message (scheduled) | Growth > Smart Messages > Priority Mass Messages | H262055 |
| 9 | OF Mass Message (scheduled) | Growth > Smart Messages | H262034 |
| 10 | Auto-unsend ("Unsend messages", "Stop message sequence") | setting inside every Smart Message | H262045 |
| 11 | Auto-follow (follows back expired fans) | Growth > Auto-follow | H262109 |
| 12 | Profile promotion "auto-activate campaign" (marketing calls it "Auto-renew campaigns") | Growth > Profile promotion | H262033, MKT |
| 13 | Smart Lists (auto-updating segments) | Growth > Smart lists | H262064 |
| 14 | Sensitive Words (auto-block) | Growth > Sensitive Words | H262068 |
| 15 | AI Copilot "Real-time auto-suggestions" (suggests only, never sends) | Messages Pro / Growth > AI Copilot | MKT, H262036 |
| 16 | Timed message / Timed reminder (one-off delays in chat) | Messages Pro composer | H262067 |
| 17 | AI Chatbot (Beta): auto-replies and sells per fan, hands off to a human (feature-flagged, `inAutoChatWhiteList`) | Settings > AI Chatbot (Beta); reports at `/admin/analytics/ai-reports` | BDL (see 3.10) |
| - | Legacy, replaced by Smart Messages: "Welcome Message", "Expired Fans", "Expiring Fans" | none | H262059 |

Searched for and absent: auto post, auto story, auto like. AI auto-reply (auto-send) was listed as absent here until the v5.7.20 bundle showed AI Chatbot (Beta), row 17.

### 4.1 THE TWO WE KEEP: Auto Post and Auto Story

Both are **ours**; Infloww has no equivalent. Every field is labeled with the Infloww analog it is derived from.

Behavior to preserve from our current Inflowwww implementation (BUILD_GUIDE.md:34):
- Auto Posts: every 3-7h.
- Auto Stories: every 4-7h, 2 per run, live about 14h.

Placement (ours): Growth > "Auto-post" and Growth > "Auto-story", directly below "Smart Messages", because Infloww groups all automations under Growth. Routes: `/growth/auto-post`, `/growth/auto-story`.

#### Auto Post: editor fields

| Field | Values | Ours, derived from |
|---|---|---|
| Creator | one creator (the selector) | ours, derived from the creator scoping in S4S Setting > [creator] > Manage posts (H262108) |
| Enabled | toggle in the list row | ours, derived from Auto-follow's "Action" on/off toggle (H262109) and Profile promotion's "auto-activate campaign" (H262033) |
| Schedule: mode | "Once" (date and time) / "Repeat" | ours, derived from PMM "Schedule the message: now or a future date" (H262055) |
| Schedule: recurrence | random interval between min and max hours (default 3-7h), or weekly days plus time; "Repeat Ends": "Never" or a date | ours, derived from Shift Schedule "repeat weekly", "Repeat Ends" (H262099) and Smart Messages "Delayed send" (random delay, H262054) |
| Schedule: daily cap | posts per 24h | ours, derived from S4S "Limit" 1/2/3 per 24h (H262106) |
| Schedule: timezone | defaults to Settings > Your Preferences regular time zone | ours, derived from H262077 and the top-bar timezone [BS] |
| Media | up to 10 items from the Vault Pro picker, or "random from category" | ours, derived from S4S "up to 10 media", "Add from Vault" (H262108), Vault Pro categories (H262062) and Collections random pick (H262045) |
| Skip media already posted | toggle | ours, derived from the Vault Pro filter "Hide content viewed or unlocked by fan, or posted on creator's feed" and the "Posted in feed" history (H262062) |
| Caption | max 5000 chars; `{name}` n/a; optional variants (max 10, random) | ours, derived from the S4S caption limit 5000 (H262108) and Collections, up to 10 random (H262045) |
| Price (PPV post) | optional price, only where OF allows paid posts | ours, derived from "PPV price" in Smart Messages (H262059); OF paid-post support G |
| Audience | n/a. Posts go to the creator's feed | ours (OF feed semantics) |
| Expiration / auto-delete | none / after N hours (24h default) | ours, derived from OF "Expiration Period" in New post (H262070) and S4S auto-remove after 24h (H262108) |
| Sensitive words check | blocks the post if it matches | ours, derived from Sensitive Words, which applies to Posts (H262068) |

#### Auto Story: editor fields

| Field | Values | Ours, derived from |
|---|---|---|
| Creator, Enabled, Timezone | as in Auto Post | as above |
| Schedule | random interval between min and max hours (default 4-7h); items per run (default 2); daily cap | ours, derived from Smart Messages "Delayed send" (H262054) and S4S "Limit" (H262106); defaults come from Inflowwww |
| Media | one item per story, from the Vault Pro picker or random from a category; skip media already used | ours, derived from Vault Pro (H262062) and Collections random pick (H262045) |
| Caption / text | none (G: OF story text overlays are not modeled) | ours |
| Price | n/a. OF stories cannot be priced (G) | ours |
| Audience | n/a. Stories are visible to subscribers | ours (OF semantics) |
| Expiration / auto-delete | delete after N hours (default 14h; OF expires stories at 24h, G) | ours, derived from S4S auto-remove (H262108) |

#### List view (both)

- Layout: tabs "List" / "Calendar". The calendar is ours, derived from OF Manager "Queue calendar" (H262112) and the S4S "Schedule" monthly calendar (H262108).
- Filters: Creator, Status, date range, "Reset" / "Search". Ours, derived from the Smart Messages filters [CL] and Smart Message Analytics (H262044).

| Column | Ours, derived from |
|---|---|
| Creator | Smart Message Analytics "Sent to" / Manage creators |
| Media (thumbnails) | Smart Message Analytics "Attachments" |
| Caption (truncated; Auto Post only) | none |
| Schedule (interval or next date) | PMM schedule |
| Next run | Queue calendar "publishing date and time" |
| Last run | Smart Message Analytics "Start date" / "End date" |
| Posted count | Smart Message Analytics "Sent" |
| Enabled | Auto-follow "Action" toggle |
| Status | see below |
| Actions: Edit, Duplicate, Delete, Run now | Smart Messages "Duplicate" (H262059); Run now is ours |

Statuses for each item (ours): "Scheduled", "In progress", "Posted", "Removed" (after expiry), "Failed", "Cancelled". Derived from Smart Message Analytics "Scheduled / Active / Completed / Cancelled" (H262044), the S4S statuses "In progress / Will be posted shortly / Completed / Canceled" (H262108), and Online fans stats "Failed" (H262067).

Editing (ours): allow editing in place. This deliberately departs from Infloww's "cancel and duplicate" rule (H262059), which would add friction for no benefit here.

---

## 5. Platforms: desktop, web and phone

| Surface | Finding | Status |
|---|---|---|
| Desktop, Mac | "Download for Apple Silicon": https://download.infloww.com/latest/darwin-m/InflowwApp-latest.dmg. "Download for Intel chip": https://download.infloww.com/latest/darwin/InflowwApp-latest.dmg. Both return HTTP 200, about 120 MB, last-modified 2026-09-22. Requires macOS 12.0 (Monterey) or later, i5, 8 GB RAM, 10 GB disk | C[DL, H262113] |
| Desktop, Windows | The download page says "Looking for the Windows download?" and gives no visible link. The installer exists: https://download.infloww.com/latest/win32/InflowwApp-latest.exe (HTTP 200, application/x-msdownload, about 107 MB, 2026-09-22). Requires Windows 10 or later | C[PROBE, H262113] |
| App name | "Infloww" (file "InflowwApp"); "Infloww desktop app"; app id `com.infloww.app` | C[PROBE login bundle]; app id 3P (low) |
| Framework | **Electron is unconfirmed.** Hints: macOS Keychain item "Infloww Safe Storage" (Electron safeStorage naming, H518057); "Hardware acceleration" setting (changelog v5.0.1); required/optional auto-update pop-ups (H367655); same-day .dmg and .exe builds; one `-latest` artifact per arch; activity signals "Window Resize" / "Viewport Scroll" (H262078). To verify, look for `Contents/Resources/app.asar` | G (strong) |
| Web CRM | **None.** login.infloww.com ("Login \| Infloww", Next.js) serves `/login`, `/signup/*`, `/signup/download`, `/trackinglink`, `/leaderboard/[code]` only; signup.infloww.com is the same. app.infloww.com is "Infloww Share for Share" (S4S community site). Card payments open an external page | C[PROBE] |
| Mobile CRM | **None.** FAQ: "Unfortunately, Infloww is currently unavailable for mobile devices." (https://help.infloww.com/en/articles/262081-frequently-asked-questions). No App Store or Play listing. 3P: "There is no standalone Infloww mobile app as of September 2026"; agencies use remote desktop | C[H262081]; 3P low |
| Phone helper "Login+" | Creator-side FaceID 2FA helper only, not a CRM. iOS via TestFlight (https://testflight.apple.com/join/cTXFsX7r). Android APK https://download.infloww.com/loginAssistant/android/latest-release/app-universal-release.apk. Not in the stores | C[H324929, PROBE] |
| Chrome extension | None found. 3P: "a downloadable application for Mac and Windows, not a browser extension" | Unverified (likely none) |
| Multi-window | Messages Pro windows, creator or fan per window, no limit | C[H545992] |

**What this means for us:** Infloww is desktop-only.
- **Desktop:** copy Infloww 1:1. Our Electron shell (`desktop/`) wraps the same Next.js routes, and Multi-Window maps to opening `/messages-pro/...` in new BrowserWindows.
- **Web:** the same routes in a browser. Infloww has no web CRM, so the web layout is the desktop layout. Messages Pro opens in a new tab.
- **Phone:** **there is no Infloww reference for any phone screen.** Every phone layout is our own design (G/ours). The nearest Infloww artifact is Login+, which only does FaceID; we may fold that flow in. Suggested approach (ours): a bottom-tab shell (Messages Pro, Dashboard, Notifications, More) over the same routes, with Messages Pro as single-pane navigation (list, then chat, then a Fan insights sheet).

---

## 6. Unknowns

1. The current (post-v5.7.14) sidebar order and labels. In particular: whether "Employees" became "Manage Employees", whether Sales records, Leaderboard, Sensitive Words, AI Copilot and Share links are their own sidebar items, and whether Organization Chart is a tab or a panel.
2. The exact "+New Message" type labels other than "Subscriber Welcome".
3. Schedule field labels for PMM / OFMM (date, time, timezone).
4. The PPV price input label in the Messages Pro composer.
5. **Resolved, except About Infloww:** the fields on Settings tabs "Security (personal)" and "Your Balance" come from the v5.7.20 bundle (3.10 rows 4 and 6, C[BDL]). About Infloww's contents stay G.
6. **Resolved:** the full role-permission matrix (the bundle's menu, function and data permissions) and the default role set (the live capture), in 3.10 row 7, C[BDL].
7. Dashboard card titles for shifts / clocked-in, and whether the free-trial banner is real.
8. Whether the "Operational" pill links to status.infloww.com.
9. Whether the desktop app is Electron (check app.asar).
10. Icons for every sidebar item (the screenshots are gone; we have no source).
11. Smart Messages "+New Message" type picker layout: the clone never captured it (the screenshot showed an empty list).
12. Which is current where BS/CL and help disagree on small labels with undated or bulk-dated articles: "Create shift(s)" vs "Create Shifts", "Show deactivated links" vs "Show expired", "Employees" vs "Manage Employees".
13. The Fansly / mym / Fanvue sidebars (only OnlyFans is inventoried here; the mym inbox tabs "Online" / "Unread" / "Requests" are C[H737197]).
