# OF Manager, automations and theme: current state (2026-10-18)

Research snapshot for "fix the OF manager and the rest of automations, and match Infloww's colours".
Main at `2e6d8035` plus uncommitted work. File:line refs are against the main checkout.

**§1 re-checked against main `159f77ac` on 2026-10-20.** Its layout gaps, per-section status and branch notes below
are updated; §0 and §2-§4 are still the 2026-10-18 snapshot.

## 0. What the screenshots show

**Infloww** (attachments `5d094222`, `67471cf1`, `eba5ca1a`, `4b2adce3`), from left to right:

1. **Top bar**, `#000000`: collapse button, trial chip, Operational pill, UTC chip, Referrals, Leaderboard, SFW,
   bell, avatar. Chips are `#171717`. A banner strip sits under it: bg `#061720`, info icon `#01a2dc`, and an orange
   "Add creator" CTA `#f88056`.
2. **Icon rail**, about 80px, `#000000`. This is Infloww's normal sidebar collapsed to icons. The active item
   is a `#0e0e0e` tile and the logo tile is `#171717` with the OF-blue logo. The rail's items are the same groups as
   our sidebar (Dashboard, OF Manager, Analytics, Growth, ...), then Creators and Employees, then
   Settings and Help.
3. **Section header row**, `#151515` with a `#3e3e3e` bottom rule: "<Section> UTC+02:00 (i)", plus fullscreen and
   reload icons on the right.
4. **Creator column**, about 255px, `#262626`: a Search box (`#373737`/`#444` border), a reload button, an
   **"All creators ▾"** dropdown in blue `#3364f3`, then creator rows. Each row has an avatar, a green online dot,
   the name, and an orange "🔔 99+" badge. The selected row is `#38435f`. With no creators it shows "No data", and the
   main pane says "You have not yet tied a creator…" with a **Link account** button in `#3467ff`.
5. **The OF page itself**, with **no OF left nav**. It shows only OF's main column and right column in OF's own dark
   theme: `#161618`, OF blue `#00aff0` (links, DISMISS, GO LIVE, VIEW QUEUE), and the All chip `#1c3c4f`.

**Ours** (attachment `74ebc3a0`). The shot predates the rebrand, so the top bar still says "OpenInfloww"; it now
says "Inflowwww" (`app/components/shell/TopBar.tsx:60`). Our sidebar is collapsed, which **hides it completely**.
What fills the left of the screen is **OnlyFans' own left nav**: Home, Notifications, Messages, Collections, Vault,
Queue, Statements, Statistics, My profile, More, NEW POST. It is baked into every mirrored HTML page and sits inside
the iframe. There is no creator column and no section header.

## 1. How OF Manager is built

**Route.** `app/app/of-manager/[section]/[[...path]]/page.tsx:12-33`. It maps `/of-manager/<section>/<sub>` to
`/of-mirror/pages/<section>/<sub|index>.html` through the generated table `app/lib/of-mirror-pages.ts` (236 lines)
and renders `<OfMirrorFrame>`.

**Pages.** These are re-captured OnlyFans HTML pages, not React and not the live site. About 385 files (17 MB) are
in `app/public/of-mirror/`, built from a SiteSucker dump plus logged-in captures by `scripts/of-mirror.mjs` (3621
lines). The generator scrubs identities and drops all of OF's JS. It also injects **OF's left nav
(`header.l-header`) into every page**, with the current item marked (`scripts/of-mirror.mjs`). At runtime the
frame hides it, as Infloww does (`app/lib/ofMirrorChrome.ts`). The overrides CSS is at `:747-764`, and the theme boot script that adds `m-mode-dark` from the parent is
at `:743`.

**Frame.** `app/components/of-manager/OfMirrorFrame.tsx` (147 lines) loads one page in a same-origin iframe (`:144`,
bg `#161618`). About 27 `useOf*` hooks (`:76-102`) reach into `iframe.contentDocument` and hydrate it with real data
from the relay's `/api/of/v2/*` proxy:

- **Data and lists:** `ofMirrorData`, `ofMirrorRow`, `ofMirrorChats`, `ofMirrorCollections`, `ofMirrorVault`,
  `ofMirrorQueue`.
- **Writes:** `ofMirrorWrites`, `ofMirrorSettingsWrites`, `ofMirrorPost` (post and story), `ofMirrorChat`,
  `ofMirrorChatTools`, `ofMirrorMessageMenu`, `ofMirrorOffers`, `ofMirrorSubscription`.
- **Money and stats:** `ofMirrorMoney`, `ofMirrorStats`.
- **Theme:** `ofMirrorTheme`.

In total `app/lib/ofMirror*.ts` is about 37.6k lines. In-frame links to `/of-manager/*` become `router.push`
(`:104-138`).

**Shell and nav.** `app/components/shell/AppShell.tsx` puts the TopBar on top and our `Sidebar` on the left. The
sidebar has the "OF Manager" group (`app/lib/nav.ts`), now with Release forms too. Collapse shrinks the sidebar to
Infloww's 60px icon rail, with flyout submenus (`Sidebar.tsx`, `collapsed`), and OF Manager pages show the rail.

**Creator switching.** OF Manager has Infloww's chrome (`app/components/of-manager/OfManagerChrome.tsx`): a 48px
page header (section, time zone, fullscreen, reload, pop out) over a 192px creator column (Search, refresh, "All
creators" or a Tag, one row per creator with its avatar, online dot, OF notification count and unread chats). A row
sets `ScopeContext`; below lg the column hides and the top bar's `ScopeSwitcher` takes over. With no creators the view
shows Infloww's `OfNotHaveModel` with Link account; a creator with a dead session gets the `page-error` placeholder.
In All-creators scope, several pages still show the first model through `standInModel` (`app/lib/ofMirrorProfile.ts`).

**Sections.** home, streaming (Go live), new-post, notifications, messages, vault, queue, collections, statements,
statistics, bank, profile, settings, release-forms.

### Gaps against Infloww's layout (the main ask)

All five are closed on main (2026-10-20): OF's left nav is hidden at runtime (`ofMirrorChrome.ts`), collapse is the
60px icon rail, `OfManagerChrome` draws the creator column, the "no creator" state and the section header, and the
TopBar has the Operational pill, the trial chip and the free-trial banner. The original notes follow.

1. **OF's own left nav shows inside the frame.** Infloww hides it. The cheapest fix is a runtime `<style>` the
   frame injects, for example `header.l-header{display:none}` plus a width reset on OF's `.l-wrapper`/main columns,
   in `OfMirrorFrame` or `useOfTheme`. A rule in `OVERRIDES` (`scripts/of-mirror.mjs:747`) would also work, but it
   needs a regenerate, and the generator's inputs live in `~/Downloads`.
   - The DOM stays, so the identity badges (`ofMirrorIdentity.ts:74`) and the tests are unaffected.
   - OF's NEW POST button and avatar/More drawer then need another entry point. The sidebar already has New post
     and My profile.
2. **No icon-rail collapse.** Collapse should shrink the `Sidebar` to icons, about 80px on `#000`, instead of
   `lg:hidden`. Infloww picks the OF page from the sidebar's OF Manager submenu (`docs/infloww-screens.md:147`), so
   the rail needs a flyout for the OF Manager group. Infloww appears to show the rail by default on OF Manager.
3. **No creator column.** Infloww has Search, reload, "All creators ▾", and rows with an avatar, online dot and
   notification badge. It could be built from `AccountRoster`/`useActiveAccounts`/`useRosterCounts` and set the scope
   on click. The "no creator" empty state with **Link account** is also missing.
4. **No section header row** ("Home UTC+02:00 ⓘ", fullscreen and reload).
5. **Top-bar extras** Infloww has: the Operational pill, the banner strip with the orange Add creator CTA, and the
   trial chip. These are in TopBar per parity row 1.2. Check them against the colours above.

### Per-section status

Sources: `docs/infloww-parity-matrix.md` §3.2 rows "Remaining gap", `docs/of-manager/*.md` and the code on main
`159f77ac` (2026-10-20). The matrix grades every section "not wired" except Lists ("unverified"): each page still has
a control shown disabled. Parked connector tickets: 06, 12, 19, 31, 38, 46.

| Section | State |
|---|---|
| Home | Feed is wired, with likes and comments. On the Creator's own post, "N Likes" lists its likers and Post statistics opens OF's popup for a role with Statistics (W8 8.9). The story tiles read `GET /stories` (checked on a fixture only). Another creator's post keeps only Copy link to post. |
| New post | Post, schedule, vault picks and uploads are wired. Labels, poll, quiz, expiration and target are read-only. Parked: Co-tag live (06), upload dedupe (19). |
| Notifications | Every tab reads its own type (`NOTIFICATIONS`, `ofMirrorFeeds.ts`); Tags reads `/release-forms/mentions`. Tips' `tip` value comes from OF's bundle, not a live capture (ticket 31). |
| Messages Basic | The chat list and thread are real. Infloww's 280px Fan insights column sits beside an open chat (`OfManagerChrome`, page-parity 06). Countdown, Copy as draft and Unsend PPV are not on OF's bubbles. |
| Vault | Wired, including the tag editor (`PATCH /admin/vault-ai/items/{media_id}`), folder Search and Go to date, and a folder page's sorts and Create new category (W8 8.9). A folder page's More stays disabled. Ticket 12 (thumbnails through `/img`) is not live-checked. |
| Queue | Edit post, edit message, reschedule and Save for later are on main (`PUT /api/of/v2/queue/posts/{id}`, `GET`/`PUT /api/of/v2/messages/queue/{id}`, `POST /api/of/v2/messages/queue/later` in `service/server.py`), with month and day navigation. The auto-publish switch stays disabled. |
| Collections | Lists are real, and create, rename, add users and delete are wired. A list's Posts tab reads `GET /api/of/v2/lists/{list_id}/posts`. |
| Statements | Read, including balances, Earning Statistics and the chargeback ratio (`ofMirrorMoney.ts`). The guessed fields `invoice`, `state` and `reason` are unverified live. |
| Statistics | Every figure is read from the relay (`app/lib/ofMirrorStats*.ts`); the old "fixed fake" note was stale. `/of-manager/statistics` lands on Statements › Earnings, as Infloww's menu does (`app/next.config.ts`, W8 8.9). |
| Bank | Mirror only, with placeholders, and a line saying bank details stay on onlyfans.com (`BANK_NOTE`, `ofMirrorWrites.ts`). |
| My profile | Wall posts, media and highlights are real; a highlight opens its cover only. |
| OF settings | Live values and writes on many pages. "Start campaign" sends `POST /api/of/v2/promotions`. Bundle Save is read-only (37). Parked: free-trial "Create link" body (38, 46). |
| Release forms | New page (W8 8.6, `ofMirrorReleaseForms`): Tag user and Release form tabs, search, sort, Hide/Show in list and Create new invitation link. Create new release form stays disabled (OF's body is not captured). |

**Branch situation (2026-10-20).** `omf-final` has no commits that main lacks (only merge commits), and the
`of-manager-fixes` and `omf-settings-rea` branches are gone: their Queue edit routes, Vault search and OF-settings
fixes are on main. Nothing needs merging before touching `OfMirrorFrame`.

## 2. Automations

**Backend.** `service/automations/`, about 85 modules. The rule kinds are listed in `service/assistant_manual.md`
(ai_chatter, auto_follow, auto_posts, auto_stories, autoreply, mass_nudge, send_welcome, purchase_followup,
unsend_messages, ppv_send, tip_request, and others). `tip_reward.py` was deleted in `2e6d8035`, and the uncommitted
`assistant_manual.md` edit removes it from the docs. `tip_reward_config.py` and `tip_reward_config_api.py` still
exist.

**UI routes:**

- "My Automations" (ours): `/growth/auto-post`, `/growth/auto-story`, `/growth/auto-reply` (`nav.ts:135-143`).
- Growth: `/growth/smart-messages`, which holds the Automated Messages tab (Nudge, Delayed welcome, Purchased
  triggers) and Mass messages with the auto-unsend card; `/growth/smart-lists`; `/growth/auto-follow`; plus vault-pro,
  scripts, profile-promotion, free-trial-links and tracking-links.
- Legacy `/automations` (`AutomationsPanel`, `ReadyMadePanel`, `RuleEditor`) appears only when
  `OPENINFLOWW_LEGACY_AUTOMATIONS=1` (`nav.ts:146`).

**Tests run today, all passing:**

- vitest on `lib/ofMirror*`, `components/shell`, `components/growth`, `components/automations`: 49 files, 1495
  tests.
- Python: test_collections_lists, test_auto_posts, test_auto_follow, test_autoreply, test_smart_lists,
  test_purchase_followup, test_send_welcome, test_mass_nudge, test_auto_stories.

**Known broken or missing.** Sources: `docs/infloww-parity-matrix.md` §3.5.x and §4.1, `zzz_goaltodos.txt`.

- Smart Messages, §3.5.1 "not wired":
  - Filters #30-33 and the Scheduled/Completed statuses.
  - The Actions and End-date cells on the trigger rows.
  - "Start from scratch".
  - The triggers **Nearing expiry, Expired, Resubscribe, Birthday and Not Purchased have no sender**. Only Nudge,
    Delayed welcome and Purchased are wired.
- Vault Pro §3.5.4, Scripts §3.5.5 and Tracking links §3.5.8 have many unwired controls.
- Profile promotion §3.5.6 and Free trial links §3.5.7 are **blocked** on an unknown OF request body; they need a
  live capture.
- Share links §3.5.9: missing route. Sensitive words §3.5.10 and AI copilot §3.5.11: no route.
- Auto-reply has not had a Route walk yet. It only replies if an LLM key resolves.
- `zzz_goaltodos.txt` asks for:
  - Layout tickets for Smart Messages, Scripts, Vault Pro, Tracking links, Creator reports, Manage creators,
    Custom proxy and Dashboard, matched to the Clone (`docs/infloww-layouts/*.md`).
  - Removing or demoting "upload from Drive", because it needs API keys.
  - Keeping the Creators-page extension probe.
- Local relay `openinflowwww-relay-local` errors in the last 2 hours (read-only `docker logs`):
  - 8× `LLMConfigError: no 'deepinfra' API key` from vision or describe automations.
  - 2× 500 `no such table: per_employee_revenue_with_attribution`, from the sales attribution view in SQLite.
- Legacy test harness (ticket 44): 26 files need `ALLOW_ANONYMOUS_ADMIN=1`. `test_mass_exclude` fails 12 cases
  with a 401 on base.

## 3. Theme tokens

| Where | What | Current |
|---|---|---|
| `app/app/globals.css:12-38` (`@theme`, dark default) | The 14 `--color-*` tokens behind every Tailwind utility (`bg-bg`, `bg-panel`, `bg-accent`, `text-fg-dim`, `border-border`, ...) | bg `#0e1116`, elev-1 `#161b22`, elev-2 `#1f2530`, panel `#14151a`, fg `#e6edf3`, fg-dim `#8b949e`, muted `#6e7681`, border `#2a313a`/`#3a414c`, **accent purple `#8b5cf6`**/hover `#a78bfa`, ok/warn/err/pink, info `#3b82f6` |
| `globals.css:119-139` | Light theme overrides | accent `#7c3aed` |
| `globals.css:68-104`, light at `:140-153` | `--if-*` Infloww Settings tokens, already the sampled Infloww palette, used only by `components/settings/` (about 190 uses) | bg `#262626`, list `#232323`, accent `#4166f6` (light `#3467ff`), line `#333` |
| `components/chat/InflowwPalette.tsx:26-75` | Messages Pro wrapper that re-declares `--color-*` with Infloww values on its subtree, plus `--inf-*` split roles | bg `#151515`, elev `#2b2b2b`/`#353535`, panel `#1c1c1c`, fg `#d9d9d9`, border `#333`, accent `#4166f6` |
| `globals.css:159-176` `[data-look="site"]` | Signed-out `/login` page in the app | site look |
| `app/app/layout.tsx:57` | `themeColor` | `#14151a` |
| `OfMirrorFrame.tsx:144` | Frame background | `#161618` |
| `web/src/main.css:7-16` (marketing site `@theme`) | ink, cream, mint, **forest `#00805e`**, sun | light site |
| `web/src/main.css` (uncommitted additions) | dark `/login/` and `/signup/` | `#0c0c0c`, orange `#f97b4f`, pink `#ff5c9a` |
| `ui-redesign/infloww-exact/PALETTE.md` (deleted in cleanup Phase 2; tag `legacy-ui-final`) | Pixel-sampled reference | |

**What it takes to swap the palette.**

- **Two edits cover about 90% of the app.**
  - Retune the 14 dark tokens in `globals.css:14-38`, and the light block at `:120-139`, to Infloww values.
  - Alternatively, hoist `InflowwPalette`'s values into `@theme`, which makes the Messages Pro wrapper redundant.
- The accent classes are all token-based: 492 uses across 130 files follow the tokens automatically.
- **Leftovers** do not follow tokens:
  - About 311 raw Tailwind palette classes (`bg-purple-500`, `text-emerald-400`, ...). They are concentrated in
    `components/vault/*` (about 150), `app/admin/manage/page.tsx`, `components/messages/CustomsTab.tsx` and
    `components/settings/*` legacy tabs.
  - 72 hex literals in 10 files, 44 of them intentionally in `InflowwPalette`.
  - The `--if-*` and `InflowwPalette` blocks, which you would merge into the tokens.

**Target values sampled from the screenshots.**

| Role | Hex |
|---|---|
| Top bar and rail | `#000000` |
| Rail active tile | `#0e0e0e` |
| Chips | `#171717` |
| Header and content | `#151515` |
| Creator column and cards | `#262626` |
| Search field | `#373737`, with a `#444` border |
| Rules | `#3e3e3e` / `#333` |
| Selected creator row | `#38435f` |
| Primary button | `#3467ff` |
| Link blue ("All creators") | `#3364f3` |
| Orange CTA | `#f88056` |
| Info banner | `#061720`, with a `#01a2dc` icon |
| Online and Operational | `#59a744` |

The caller's guess of `#2f6bff` is close; the measured value is `#3467ff`. `PALETTE.md` and the `--if-*` tokens use
`#4166f6`. The OF page keeps OF's own colours (`#161618`, `#00aff0`) through `m-mode-dark`.

## 4. Uncommitted work on main

Three separate streams.

1. **OF Manager, Collections list "Posts" tab, plus names in New message's Users tab.** This looks complete, and its
   tests pass.
   - `app/lib/ofMirrorData.ts`: the `LIST_POSTS` page `collections/user-lists/list/posts`, `listPostsPath`,
     `postTypeOf`, type chips, `applyListTabs`, and author resolution through `/users/list`.
   - `ofMirrorFeeds.ts`: `LIST_FEED`, and `applyHomeStatus` generalised to take a feed.
   - `ofMirrorCollections.ts`: the list More menu on the Posts tab too.
   - `ofMirrorChat.ts`: mass-send "Users" tab partners named through batched `/users/list` (20 ids a read) instead
     of bare ids.
   - Relay: `service/of_client.py` `list_posts_in()` and `service/server.py`
     `GET /api/of/v2/lists/{list_id}/posts`.
   - Tests: `service/tests/test_collections_lists.py` (+2 cases) and the vitest specs. The mirror page
     `collections/user-lists/list/posts.html` was already committed.
   - It is ready to commit.
2. **`service/assistant_manual.md`**: removes `tip_reward` (whose module was deleted in `2e6d8035`) from the
   assistant's manual. This is docs only and ready to commit.
3. **Marketing site `/login/` and `/signup/` dark restyle** in Infloww's auth-page shape.
   - `web/src/_includes/base.njk` adds `bare: true`, which drops the header and footer and sets `html.auth-dark`
     and the theme colour `#0c0c0c`.
   - `auth.njk`, `login.njk`, `signup.njk` and `main.css` (+117 lines) add `.auth-*` classes: orange `#f97b4f`
     focus and buttons, pink errors.
   - It looks coherent, but I did not build or check it visually.

Untracked files: `LIVE_TEST_HERE.md`, the sandbox live-test runbook (A1-D8, with an empty results table, so the live
pass has not been run), and `zzz_goaltodos.txt`, the owner's notes.
