# Phase 04 — App integration

**Objective.** With `fansly_manager` on, every Fansly Manager nav entry opens its section: either a Fansly mirror page in a same-origin frame, showing the picked Fansly Creator's name, handle, avatar and banner in the app theme, or one of the four Built pages, unchanged; with the flag off, or for a role that is denied the page, nothing of it opens.

## Problem Statement
An agency running a Fansly Creator gets four hand-built Fansly Manager pages: Scheduled Posts, Lists, Notifications and Earning Statistics. Fansly's own creator UI is not in the app at all, while an OnlyFans Creator gets a ~150-page OF Manager that looks like OnlyFans. Phase 3 produces the scrubbed Fansly mirror pages and their pages table. Nothing serves them yet. No nav entry reaches them. Nothing puts the Creator's identity on them, applies the app theme, or keeps a role or the flag from reaching them.

## Solution
The Fansly Manager group lists the 14 entries of Infloww's Fansly menu. Ten open Fansly mirror pages under `/fansly-manager/<section>/...`; four stay the Built pages at their exact URLs. A mirror page sits under a thin Fansly Manager title bar with a Fansly Creator picker. Fansly's left rail is hidden, because our sidebar is the nav, and its top bar stays. The Creator picked in the URL (`?creator=`) fills in name, handle, avatar and banner. With no valid pick, the first live Fansly Creator is shown, with a hint saying so. The frame follows the app's light or dark theme. Links inside the frame move through the app and keep the picked Creator, including links to a Built page. A role sees an entry only if it holds that entry's OnlyFans counterpart page, and opening the URL directly gives the same denied panel.

## User Stories
1. As an agency owner with `fansly_manager` on, I want the Fansly Manager group to list Homepage, Profile, Subscriptions, Media Vault, Scheduled Posts, Lists, Bookmarks, Messages, Notifications, Creator Dashboard, Earning Statistics, Profile Statistics, Tracking Links and Settings in that order, so that it matches Infloww's Fansly menu.
2. As an agency owner, I want Scheduled Posts, Lists, Notifications and Earning Statistics to open the same Built pages at the same URLs as today, so that their real rows and writes (create list, cancel scheduled, notification ack) keep working.
3. As an agency owner, I want each of the other ten entries to open the Fansly mirror page for its section, so that I see Fansly's own UI for it.
4. As an agency owner, I want a mirror subpage such as `/fansly-manager/lists/list` or `/fansly-manager/scheduled/<sub>` to open the mirror page, while only the bare `/fansly-manager/lists` opens the Built page, so that mirror subpages under a Built section still serve.
5. As an agency owner, I want an unknown `/fansly-manager/<section>/<path>` to answer 404, so that a mistyped URL cannot render an empty frame.
6. As an agency owner, I want bare `/fansly-manager` to land on the first Fansly Manager entry my flags and role allow, so that the group's own URL never dead-ends.
7. As an agency owner, I want a mirror link to Fansly's earnings page to land on the Built Earning Statistics page, and every other redirect-table entry to land on its target, so that one section is never served by two pages.
8. As an agency owner, I want `?creator=` kept through every redirect (including bare `/fansly-manager?creator=`), every in-frame link click (plain or modified, so a new tab keeps it too) and every hand-off into a Built page, so that moving between mirror and Built pages never loses the picked Creator. Sidebar clicks use bare hrefs, as they do for the Built pages today, and are not covered.
9. As an agency owner, I want a Fansly Creator picker in the mirror's title bar that writes `?creator=`, so that I can switch Creators as the Built pages already let me.
10. As an agency owner, I want switching Creator A to Creator B to reload the frame and show B's handle, name, avatar and banner, so that I never read one Creator's identity on another's page.
11. As an agency owner with no Creator picked (or a pick that is not a live Fansly Creator), I want the mirror to show the first live Fansly Creator and a hint "Showing <name>, pick a model to switch", so that All Models scope shows a real Creator and says which one.
12. As an agency owner with no live Fansly Creator, I want a "no creator linked" state with a link to Creators Management (or the no-permission line), so that I know what to do.
13. As an agency owner, I want Fansly's left rail hidden and its top bar kept, so that our sidebar is the nav and the avatar and balance menu states keep their openers.
14. As an agency owner, I want the mirror frame to follow the app theme at first paint and when I toggle it, with no light flash in dark mode, so that the frame matches the app.
15. As an agency owner, I want avatar and banner images loaded through the app's `/img` proxy, so that no request from the frame leaves our origin.
16. As an agency owner, I want each mirror page's tab title to read "<nav label>: <page title>", so that tabs and history are readable.
17. As an agency owner with `fansly_manager` off, I want every Fansly Manager entry hidden, and a direct visit to any mirror path to show "<label> is not available." and read nothing, so that the area stays dark until switched on. (This covers the app routes. The raw `/fansly-mirror/*.html` files are public static files, as `/of-mirror/*` is, per ticket 04 §Gates.)
18. As a chatter whose role lacks an entry's OnlyFans counterpart page, I want that entry hidden, and its URL and every URL under it to show the denied panel, so that the mirror never grants more than the role does. A redirect-table path is the one exception: it is served by its target, so the target's grant decides (story 7, one section is one page).
19. As a chatter whose role grants `/of-manager/statistics` but not `/analytics/creator-reports`, I want Creator Dashboard, Profile Statistics and Tracking Links open, and Earning Statistics, including the redirect from the mirror's earnings link, denied. As a chatter with the reverse grants, I want the earnings redirect to open Earning Statistics and the rest of Profile Statistics denied. So that the earnings redirect never crosses grants either way. With Role enforcement off, or for an Owner or the Master, every entry is open (ADR-0012).
20. As a chatter, I want Bookmarks to answer to the OnlyFans Bookmarks grant (`/of-manager/collections/bookmarks/all`), not Collections, so that the same grant covers both Platforms.
21. As an agency owner switching the sidebar to Fansly, I want `firstPage("fansly")` to still skip flagged pages, so that switching Platforms never lands on "not available".
22. As a developer, I want the route and nav tests to run against fixture page tables and never read the generated `app/public/fansly-mirror` tree, so that the public export, which drops that tree, stays green.
23. As a developer, I want a raw-file test of the generated landings of the four Built sections that skips when the tree is absent, so that the copies exist on private main without being linked.
24. As a developer, I want the Fansly Shim's `/users/me` to carry `header` from the account's banner, only when the Tracer facts in `fansly/capture/RECIPES.md` record a `banner_field` (Phase 2 story 39); with none recorded the Shim is unchanged and `data-oi-banner` keeps the blank image, so that the frame fills in the banner without a guessed field.
25. As a developer, I want headless Fansly mirror checks to prove these things: every routable page in the pages table renders in the frame, and the four shadowed landings route to their Built pages; the frame makes no request off localhost (aborted before dispatch, with a planted remote image as negative control) and no non-GET request; every `oi-state-link` and `oi-state-backdrop` lands on its target page; the first paint is dark in dark mode and light in light mode, and toggling the app theme with the frame mounted flips it both ways; the top bar's avatar and balance openers open and close their states; and the bare, flag-off and denied deep links behave through the real layout. So that layout, theme and gate regressions show up without Fansly.
26. As a developer, I want a verify-app run with the seeded Fansly Creator Nova, Built-page rows, `/users/me` built by the real Shim code from a fixture, and avatar and banner answered by a fixture `/img` route, so that identity and images are proven in the real app without any request to Fansly; the A → B switch is proven by `navigate.py` with mocked accounts.
27. As the owner, I want a `fansly_mirror_errors` watch check, and one WATCH.md line once AE is deployed, so that browser errors on `/fansly-manager/` show up in the 4h sweep.
28. As a developer, I want the parity matrix rows for Fansly Manager to describe the mirror, so that the docs match the code.
29. As the owner, I want `fansly_manager` turned on for AE once this PR is deployed there, by the coordinator, for every AE Agency that holds a Fansly Creator: inside the client relay container, after ae-deploy's DB backup, through the relay's own flags code (`read_blob(s, <agency user id>, "flags")`, set `fansly_manager: true`, `parse_blob("flags", …)`, `write_blob`, the same path `PUT /admin/settings/flags` takes), read back with `applied_blob` as `fansly_manager is True`, and proven by a screenshot of the Fansly Manager nav on the client site, so that the shipped mirror is reachable on AE and goes dark again by writing `false` the same way.

## Implementation Decisions
- **Owns.**
  - Fansly Manager route: replaces the `[page]` route with `[section]/[[...path]]`, plus a bare-group page.
  - Fansly Manager layout: new.
  - Fansly mirror route module: new, sibling of the OF mirror route module.
  - Fansly mirror pick module: new.
  - Fansly mirror document module: new; it holds the chrome CSS, the Identity swap and the theme marker.
  - `FanslyMirrorChrome` and `FanslyMirrorFrame` components: new.
  - Fansly nav: one `FANSLY_NAV` block change in `app/lib/nav.ts`.
  - `of_user` in the Fansly Shim: gains `header`.
  - verify-app Fansly seed (`fansly_nova`): adds Built-page rows, and a banner only when the Tracer facts record a `banner_field`. `/users/me` stays a browser fixture built by `FanslyShimClient.me()` (`scripts/demo-shots/fansly_nova.py:140-156`), because the relay route would call Fansly and `drive.py api` refuses `/api/of` by design (`scripts/verify-app/drive.py:345-346`). `/img` is answered by the harness router's existing fixture route, never upstream.
  - `scripts/fansly-mirror-check/`: new.
  - One `AppErrors` row in `scripts/proxy-health/watch.py`.
  - Docs: the parity matrix rows.
- **Interfaces.**
  - Fansly mirror route module. Every function takes the pages table as a parameter, defaulting to Phase 3's `FANSLY_MIRROR_SECTIONS`:
    ```ts
    type FanslyRoute =
      | { kind: "built"; href: string }                       // exact /fansly-manager/{scheduled|lists|notifications|earning-statistics}, no path
      | { kind: "redirect"; to: string }                      // REDIRECTS hit, already carrying ?creator=
      | { kind: "mirror"; key: string; title: string; src: string } // src = /fansly-mirror/pages/<key>.html
      | null;                                                 // 404
    fanslyRouteOf(section: string, path: readonly string[], creator: string | null, table?): FanslyRoute
    withCreator(href: string, creator: string | null): string // adds or keeps ?creator=, keeps other params and #hash
    fanslyMirrorPageOfHref(href: string, table?): string | null
    firstFanslyPage(f: NavFilter): string | null              // first visible Fansly Manager child, via nav's visibleLinks
    ```
    Dispatch order: Built exact path, then redirect table, then mirror page (OF's `mirrorPageOf` semantics: `index` sub for an empty path, `Object.hasOwn` lookups), then `null`. The redirect table starts as `statistics/earnings` → `/fansly-manager/earning-statistics`, plus any Fansly legacy alias whose landing Phase 3 mirrored under another key. The redirect runs on the server before the client's `DeniedPageGate` (`app/components/shell/DeniedPage.tsx:34-41`) sees the source path, so the target's grant decides. That is intended: the redirect serves the target section, and no page opens without its own grant.
    `routableFanslyPages(table?)` lists the table keys that `fanslyRouteOf` resolves to `mirror`. The four shadowed landings (`scheduled/index`, `lists/index`, `notifications/index`, `statistics/earnings`) are excluded, and the headless sweep reads this list.
  - Fansly mirror pick module (pure):
    ```ts
    type FanslyPick =
      | { kind: "picked"; accountId: string }
      | { kind: "standIn"; accountId: string } // no valid pick; first live Fansly Creator
      | { kind: "none" };                      // no live Fansly Creator
    fanslyPick(known: AccountMeta[] | undefined, creatorParam: string | null): FanslyPick
    ```
    `known` is the relay's Fansly Creator list (never watchers, never OnlyFans Creators). "Live" uses `liveSession`. `picked` needs a live Creator in `known`; any other id counts as no pick. A dead Creator is never chosen as the stand-in (unlike OF's `standInPick`).
  - Fansly mirror document module:
    - `prepareFanslyDoc(doc, { me, accountId, dark })` is idempotent. It injects the chrome style, which hides `[data-oi-nav]`, resets the content offset it leaves behind, and keeps the top bar.
    - It sets the theme marker both ways: on for dark, off for light.
    - It replaces the placeholders `yourmodel` and `Your Model` in text nodes and in `title`/`alt`/`aria-label`/`placeholder` attributes.
    - It sets `src` (or `style` `background-image`) on `[data-oi-avatar]` and `[data-oi-banner]` through `proxyImage(url, accountId)`. With no `me`, which includes a failed `/users/me` (for example a relay 403 for a Creator outside the chatter's Agency), it leaves the placeholders as they are and never fills in another Creator.
    - It rewrites every in-frame `a[href^="/fansly-manager/"]` to `withCreator(href, accountId)`, so a modified click or a new tab keeps the pick.
    - `useFanslyDoc(ref, src, accountId)` runs `prepareFanslyDoc` on load, and again when the theme or `me` changes. A `me` that arrives after load fills the still-present placeholders in the same document. A changed `me` for the same account is not re-swapped, because the switch remounts. Its React Query key is `ofMeQuery(accountId)`.
  - `FanslyMirrorChrome` (client). The layout uses it for `mirror` routes only and passes `built` routes through.
    - It renders: the title from `findNavLink('/fansly-manager/<section>')`, an `IfCreatorSelect` over live Fansly Creators that writes `?creator=` with `router.replace`, and the stand-in hint.
    - It shows the flag-off empty state while `useFlags().fansly_manager` is not true, a skeleton while flags load, and NoCreators for `none`.
    - It reads accounts with `usePlatformAccounts('fansly')` and `useAccounts`, never `useOfManagerAccounts`, `useWatcherAccounts` or `WatcherScope`.
    - It owns no state beyond the URL: the pick is derived during render, so the reducer rule does not apply.
  - `FanslyMirrorFrame({ src, title, accountId })`:
    - The iframe is keyed `src|accountId`, so a switch remounts it and Back stays one step per page.
    - Click interception: `#` is swallowed. A plain left click on an `/fansly-manager/...` href does `router.push(withCreator(href, pickedOrNull))`. A modified click is left to the browser.
    - The background colour follows the theme. It has no write hooks.
  - Fansly Manager route page: a server component. `built` renders `FanslyManagerPage` as today. `redirect` calls `redirect(to)`. `mirror` renders `FanslyMirrorFrame` inside the chrome, with `generateMetadata` giving the title. `null` calls `notFound()`. It reads `searchParams.creator`.
  - Bare-group page (client): `router.replace(withCreator(firstFanslyPage(filter), searchParams.creator))`. With none visible it shows the flag-off empty state, or the denied panel when the flag is on.
- **Schema.** None.
- **Contracts.**
  - *Phase 3 → this Phase.* What this Phase consumes:
    - `FANSLY_MIRROR_SECTIONS`, the same shape as `OF_MIRROR_SECTIONS` (`{ index, pages: Record<sub, title> }`), keyed by the section slugs below.
    - Page files at `/fansly-mirror/pages/<section>/<sub|index>.html`.
    - In-page links already rewritten to `/fansly-manager/...` or `#`.
    - The rail tagged `data-oi-nav`.
    - The identity placeholders `yourmodel`, `Your Model`, `data-oi-avatar` and `data-oi-banner`.
    - A dark-boot script that adds Fansly's dark marker when the parent's `data-theme` is not `light` and never removes it (OF's `THEME_BOOT`).
  - *Section slugs* (ticket 05 §1): `home`, `profile`, `subscriptions`, `vault`, `scheduled`, `lists`, `bookmarks`, `messages`, `notifications`, `creator`, `statistics`, `tracking-links`, `settings`, plus `earning-statistics` (Built only).
  - *Nav.* `FANSLY_NAV`'s Fansly Manager group, Infloww order. Every child has `flag: "fansly_manager"` and the `permission:` alias shown:

    | Label | href | permission |
    |---|---|---|
    | Homepage | `/fansly-manager/home` | `/of-manager/home` |
    | Profile | `/fansly-manager/profile` | `/of-manager/profile` |
    | Subscriptions | `/fansly-manager/subscriptions` | `/of-manager/collections` |
    | Media Vault | `/fansly-manager/vault` | `/of-manager/vault` |
    | Scheduled Posts | `/fansly-manager/scheduled` | `/of-manager/queue` |
    | Lists | `/fansly-manager/lists` | `/of-manager/collections` |
    | Bookmarks | `/fansly-manager/bookmarks` | `/of-manager/collections/bookmarks/all` |
    | Messages | `/fansly-manager/messages` | `/of-manager/messages` |
    | Notifications | `/fansly-manager/notifications` | `/of-manager/notifications` |
    | Creator Dashboard | `/fansly-manager/creator` | `/of-manager/statistics` |
    | Earning Statistics | `/fansly-manager/earning-statistics` | `/analytics/creator-reports` |
    | Profile Statistics | `/fansly-manager/statistics` | `/of-manager/statistics` |
    | Tracking Links | `/fansly-manager/tracking-links` | `/of-manager/statistics` |
    | Settings | `/fansly-manager/settings` | `/of-manager/settings` |

    The change is confined to the `FANSLY_NAV` literal and its doc comment. `deniedPage`, `keep`, `firstPage`, `platformOfPath` and `app/lib/platform.ts` are not edited. Every section has its own entry, so `deniedPage`'s first-prefix alias rule needs no change. The parallel thread that co-owns `nav.ts` is told before the edit, and the edit is rebased onto its merges.
  - *Shim.* `of_user(account)` gains `"header": <banner URL or None>`, resolved like `_avatar_url` (locations, then variant locations) from the account's banner field, whose name and shape come from the Tracer facts `banner_field`, read from Phase 2's scrubbed `account-me.shape.json` (Phase 2 story 21). The Shim test fixture is copied from that shape, never guessed. No `banner_field` recorded means no `header` and no Shim change. `/api/of/v2/users/me` passes it through unchanged, and the app's `OfMe.header` already types it.
  - *Watch.* `AppErrors("fansly_mirror", "fansly_mirror_errors", "Fansly Manager browser errors", urls=("/fansly-manager/",), source="browser", by_path=False)`, the Focus-page row's precedent. After the AE deploy, the coordinator appends `- fansly-mirror | added <date> | expires +3d | fansly_mirror_errors | <PR url>` to WATCH.md.
- **Theme.** Following the Fable note (it supersedes ticket 05 §8), pages are captured in light and only the generator's boot script adds dark. At runtime the document module sets the marker both ways from `useTheme`, the way OF's `applyTheme` does. There is no own-dark or sync toggle, and Fansly's Display-settings theme control is not wired.
- **Built pages.** `FanslyManagerPage` and its four bodies stay as they are. They already read `?creator=` through `useCreatorParam`. "Has a body for every /fansly-manager/* nav href" becomes "every Built href".
- **Public.** On the public export the route, nav and tables ship and the HTML does not. A mirror route there renders the frame onto a 404 (OF precedent, ADR-0067), and the default-off flag hides the nav.

## Testing Decisions
Seams, by public interface; no test reads `app/public/fansly-mirror` at module load.
- **Fansly mirror route module** (vitest table, fixture pages table):
  - Each of the four Built exact paths resolves to `built`.
  - `lists/list` and `scheduled/<sub>` resolve to `mirror`.
  - `statistics/earnings` resolves to `redirect`, keeping `?creator=`.
  - Unknown section, unknown sub, a prototype key (`__proto__`, `constructor`) and the slug `earning-statistics/x` all resolve to `null`.
  - The `index` sub is used for an empty path.
  - The title is "label: page".
  - `withCreator`: adds the param, keeps an existing one, keeps other params and the hash, and leaves the URL alone for `null`.
  - `firstFanslyPage`: flag off gives `null`; owner gives Homepage; a role without `/of-manager/home` gives the next allowed entry.
  - `routableFanslyPages` excludes the four shadowed landings and includes `lists/list`.
- **Fansly mirror pick module** (vitest table): `picked`; `standIn` when there is no param, for an unknown id and for a dead Fansly pick; the stand-in skips a dead first Creator; `none`.
- **Fansly mirror document module** (vitest + jsdom on inline fixture HTML):
  - Placeholders are replaced in text and attributes.
  - The avatar and banner come out as `/img?u=…&account_id=…`.
  - The rail style is present exactly once after two runs.
  - The theme marker toggles on, then off.
  - With no `me` the placeholders stay. A run with no `me` and then one with `me` on the same document fills them in.
  - Running A and then B on a fresh document gives B's values.
  - An in-frame `/fansly-manager/` href comes out carrying `?creator=<id>`; `#` and other hrefs are left alone.
- **Route page** (the `[section]/[[...path]]` test, which replaces `[page]/page.test.tsx`, with `next/navigation` mocked):
  - Built paths render `FanslyManagerPage` with flag `fansly_manager`.
  - A redirect throws to the target with `?creator=`.
  - A mirror path renders the frame with the right `src`.
  - Unknown paths throw `NEXT_NOT_FOUND`.
  - The route module is mocked with a fixture table.
- **Chrome and frame** (`@testing-library/react`, prior art `OfManagerChrome.test.tsx`, `ofMirrorStandIn.test.tsx`; accounts and flags mocked):
  - Flag off shows "not available", and no `/users/me` read is sent.
  - The hint shows only on `standIn`.
  - NoCreators renders.
  - The picker writes `?creator=`.
  - An in-frame click on `/fansly-manager/home` pushes `/fansly-manager/home?creator=<id>`.
  - A `#` click is swallowed.
  - A failed `/users/me` (mocked 403) shows no other Creator's identity, and the frame keeps its placeholders.
  - The bare-group page with `?creator=B` replaces to `/fansly-manager/home?creator=B`.
- **Nav** (`nav.test.ts`, replacing the Fansly cases):
  - The group outline and order are the 14 entries above.
  - Every child is flagged.
  - Each child's `permission` is the table above and is a `PERMISSION_PAGES` page.
  - A child is hidden, and `deniedPage` answers its alias, for the href and a descendant (`/fansly-manager/lists/list`, `/fansly-manager/statistics/x`) when the alias is not granted.
  - Statistics granted without creator-reports leaves Earning Statistics denied and the others open. Creator-reports without statistics leaves `/fansly-manager/earning-statistics` open and `/fansly-manager/statistics` and `/fansly-manager/statistics/x` denied.
  - `grantedPages` `null` (Role enforcement off, Owner, Master) leaves all 14 visible with the flag on.
  - Bookmarks is denied without the Bookmarks grant, even with Collections granted.
  - `firstPage("fansly")` is still `/growth/scripts`.
  - `platformOfPath("/fansly-manager/home")` is `"fansly"`, which flips the old `null` case.
  - `test_role_enforcement` still passes against the new `nav.ts`.
- **Raw landings** (vitest, `it.skipIf(!existsSync(dir))` with the read inside the body): the generated landings of the four Built sections exist under their mirror keys, and no nav entry, link or redirect points at them.
- **Shim** (`fansly/test_shim_shapes.py`, the plain-script house style): `of_user` with a banner in each of the two location shapes gives `header`, and with none gives `None`.
- **Headless mirror checks** (`scripts/fansly-mirror-check/`, ports of `of-mirror-check` `render.py`, `navigate.py` and `dark.py`; login faked by Playwright routes, Next dev on `PORT` 3091; prior art `scripts/of-mirror-check/README.md`). They need the generated tree, so they run on private main only:
  - `render.py`: every page in `routableFanslyPages()` renders inside the frame. Each of the four shadowed landings' public URLs reaches its Built page. Every non-localhost request is aborted in a Playwright `context.route("**/*")` handler before dispatch and fails the run, as does any non-GET request, localhost 404 or page error; a planted page holding a remote `<img>` must make it fail (negative control). Every `oi-state-link` and `oi-state-backdrop` click lands on its target page. It saves one screenshot per page and the request log. The run fails on an empty pages table. (It absorbs Phase 3's former raw-page check.)
  - `navigate.py`: rail hidden, top bar shown; the avatar and balance openers each open their state and close it again. An in-frame link click keeps `?creator=`, and so does a modified click's href. Mirror → Built hand-off works. A mocked `/users/me` per account switching A → B changes the handle; with B's response delayed 2 s, A's handle never shows after the switch. `/fansly-manager?creator=B` lands on Homepage with `?creator=B`. A flag-off deep link and a denied-role deep link through the real layout show their panel, with no `iframe` in the DOM and no `/users/me` request.
  - `dark.py`: the first paint inside the frame's box is never light in dark mode and is light in light mode. With the frame mounted, toggling the app theme light → dark → light flips the frame's marker each time.
- **Real path** (verify-app `--fansly`): Nova (banner only if the Tracer facts record one), and Built pages have rows for scheduled, lists and notifications. The run takes desktop and phone screenshots, light and dark, of home, profile, creator and settings. The phone context forces light on navigation (`scripts/verify-app/drive.py:537-556`), so the dark phone shots set the theme on the phone page before the capture. The side effects are: `reads --match users/me` shows the frame's `/users/me` read with Nova's account id, and in-frame avatar (and banner, when present) have `src` starting `/img?` and `naturalWidth > 0`.
- **Watch** (`scripts/proxy-health` pytest): `fansly_mirror_errors` is in `WATCH_CHECKS`, and its SQL filters `source = 'browser'` and `/fansly-manager/`.

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# manual: this worktree needs venv/ and app/node_modules set up the way the main checkout has them
test -x venv/bin/python && test -d app/node_modules
BASE=$(git merge-base HEAD origin/main)
# private main must carry the coordinator's real, guarded output (an empty table and null build also pass --check)
test -d app/public/fansly-mirror/pages
node scripts/fansly-mirror.mjs --check
(cd app && pnpm exec vitest related --run lib/fansly-mirror-route.ts lib/fanslyMirrorPick.ts lib/fanslyMirrorDoc.ts \
  components/fansly-manager/FanslyMirrorChrome.tsx components/fansly-manager/FanslyMirrorFrame.tsx \
  components/fansly-manager/FanslyManagerPage.tsx 'app/fansly-manager/layout.tsx' 'app/fansly-manager/page.tsx' \
  'app/fansly-manager/[section]/[[...path]]/page.tsx' lib/nav.ts)
(cd app && pnpm exec tsc --noEmit)
test ! -e 'app/app/fansly-manager/[page]'
# the whole app suite stays green with the generated tree absent (public export); vitest passes with no tests (vitest.config.ts:31), so related is not enough here
mv app/public/fansly-mirror .scratch/fansly-manager-mirror/aside-tree
trap 'mv .scratch/fansly-manager-mirror/aside-tree app/public/fansly-mirror' EXIT
(cd app && nice -n 10 pnpm test:run)
mv .scratch/fansly-manager-mirror/aside-tree app/public/fansly-mirror; trap - EXIT
# shared files: platform.ts untouched; every changed nav.ts line sits inside FANSLY_NAV's doc comment + literal
git diff --quiet "$BASE" -- app/lib/platform.ts
git diff -U0 "$BASE" -- app/lib/nav.ts | venv/bin/python -I -c '
import re, sys
src = open("app/lib/nav.ts").read().split("\n")
s = next(i for i, l in enumerate(src) if l.startswith("export const FANSLY_NAV"))
while s > 0 and src[s - 1].lstrip().startswith(("/**", "*")): s -= 1
e = next(i for i in range(s, len(src)) if src[i] == "];")
hunks = [tuple(int(x or 1) for x in m.groups()) for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", sys.stdin.read(), re.M)]
assert hunks, "nav.ts unchanged"
for c, d in hunks:
    assert s + 1 <= c and c + max(d, 1) - 1 <= e + 1, (c, d, s + 1, e + 1)'
# no watcher and no write in the mirror's own code (if-form: `! grep` does not trip set -e)
if grep -nE 'useWatcherAccounts|useOfManagerAccounts|WatcherScope' app/components/fansly-manager/FanslyMirror*.tsx app/lib/fanslyMirror*.ts; then exit 1; fi
if grep -nE 'relay\.(post|put|patch|delete)\(' app/components/fansly-manager/FanslyMirror*.tsx app/lib/fanslyMirror*.ts app/lib/fansly-mirror-route.ts; then exit 1; fi
venv/bin/python scripts/run_tests_parallel.py fansly shim_shapes -j 8
scripts/run-tests.sh role_enforcement
venv/bin/python scripts/run_tests_parallel.py --pytest scripts/proxy-health -j 8
grep -q 'fansly_mirror_errors' scripts/proxy-health/watch.py
# headless mirror checks (need the generated tree; private main only)
(cd app && PORT=3091 nice -n 10 npx next dev --webpack -p 3091 > ../.scratch/fansly-manager-mirror/next-3091.log 2>&1) &
NEXT_PID=$!
for _ in $(seq 1 90); do curl -sf -o /dev/null http://localhost:3091/login && break; sleep 2; done
nice -n 10 python3 -I scripts/fansly-mirror-check/render.py
nice -n 10 python3 -I scripts/fansly-mirror-check/navigate.py
nice -n 10 python3 -I scripts/fansly-mirror-check/dark.py
pkill -P "$NEXT_PID" || true; kill "$NEXT_PID" || true
# real path
D=scripts/verify-app/drive.py
nice -n 10 $D up --fansly && $D doctor
$D login --as owner
# manual: turn the fansly_manager flag on for the seeded agency (Settings > feature flags, or $D db on the Settings blob)
$D goto '/fansly-manager/home'
$D screenshot --path fansly-home-light.png && $D screenshot --phone --path fansly-home-light-phone.png
# manual: repeat for /fansly-manager/profile, /fansly-manager/creator, /fansly-manager/settings, then toggle dark and repeat all four (desktop + phone; set dark on the phone page, which forces light on navigation)
$D reads --match 'users/me' | venv/bin/python -I -c 'import json,sys; a=[r["account"] for r in json.load(sys.stdin)["reads"]]; assert len(set(a)) == 1, a'
# manual: in the frame, the avatar (and banner, when the Tracer facts record one) src start with /img? and have naturalWidth > 0 (snapshot or DevTools)
# manual: $D goto '/fansly-manager/nope-section' shows the 404 page (drive.py api refuses /api/of and the 404 is a page route)
# manual: open /fansly-manager/scheduled, /lists, /notifications from the frame's links; each Built page shows its seeded rows with ?creator= kept
$D down
scripts/run-tests.sh
# manual (coordinator, after AE deploy): append the fansly-mirror line to the proxy-health WATCH.md
# manual (coordinator, after AE deploy, DB backed up by ae-deploy): story 29 flag-on in the client relay container for each AE Agency holding a Fansly Creator; read back applied flags fansly_manager true; screenshot the Fansly Manager nav on the client site
```

## Depends on
- Phase 1 (Never-public gates): `app/public/fansly-mirror` is a Never-public path before any mirror file reaches main. This Phase's route, tables and tests are written to pass without that tree.
- Phase 3 (Generator and guard): `FANSLY_MIRROR_SECTIONS` and `FANSLY_MIRROR_BUILD`, the generated pages and static assets, the `data-oi-nav` rail tag, the identity placeholders, the dark-boot script, the generated landings of the four Built sections, and `node scripts/fansly-mirror.mjs --check`. Code and unit tests build on Phase 3's empty table and `null` build (its story 38). Private acceptance needs the coordinator's populated, guarded output, because `--check` also passes an absent tree (its story 40). Same PR as Phase 3 (plan review 2026-11-27 reorder).
- Phase 2 Tracer facts, before any code of this Phase: the "Tracer facts" section of `fansly/capture/RECIPES.md` (Phase 2 story 39) gives the dark marker, the banner field (from the scrubbed `account-me.shape.json`, Phase 2 story 21) and the rail and avatar hooks.

## Out of Scope
- Real Fansly data rows and writes on mirror pages (map "Not yet specified", phase 2 of the effort): Phase 1 is static + identity + theme.
- The mirror replacing the four Built pages (ticket 04 (C)): they keep their slots until the mirror has their rows and writes.
- Media Collection and Referrals entries (ticket 05 §5, ticket 04): not in the page list.
- OF Manager chrome extras (pop out, fullscreen, reload, fan insights, CreatorColumn, popout `?account=`): YAGNI for a static copy with no chats.
- OF's own-dark/display-sync toggle and wiring Fansly's Display theme switch: Fable reduced theme to light capture + dark boot.
- Hiding Fansly's top bar (ticket 05 §4 ASSUMPTION): kept so menu states keep their openers.
- Phone-specific frame hooks (OF's `useOfPhone`): Fansly's own layout is responsive; phone screenshots prove it or open a ticket.
- Any edit to `deniedPage`, `keep`, `firstPage`, `platformOfPath` or `app/lib/platform.ts`: co-owned with P2, and a section per entry removes the need.
- Fixing the OF mirror's public exposure: parked for the owner (map "Needs the human").
- Fan-side (:9232) UI.
- A second seeded Fansly Creator and `/img` cache seeding in verify-app — deferred (YAGNI, six-hats): the A → B switch is proven in `navigate.py` with mocked accounts and a delayed `/users/me`.
- Expired-pick SessionGone, the OnlyFans-id pick story and the Watcher-pick story — deferred (YAGNI, six-hats): `known` holds live-checkable Fansly Creators only, so a dead, foreign or Watcher id is just "no pick" and the stand-in shows with its hint.
- The Shim `header` field when the tracer records no banner field — deferred (YAGNI, six-hats).

## Further Notes
- The pick lives in `?creator=`, the Built pages' precedent (`useCreatorParam`), not in the app-wide `ScopeContext` the OF chrome uses. The global Scope select does not drive the Fansly mirror.
  ASSUMPTION: rung 3 (Built pages already pick by `?creator=`, ticket 05 §1 carries it everywhere). Overturned if the owner wants the global Scope select to drive Fansly too; then the chrome reads `useScope` and `?creator=` is only a hand-off.
- A pick that is a dead Fansly Creator falls back to the first live one, with the stand-in hint naming who is shown.
  ASSUMPTION: rung 5 (coordinator trim 2026-11-27; ticket 05 §7's "never an expired stand-in" still holds, since the stand-in is always live). Overturned if the owner wants OF's SessionGone panel for a dead pick.
- The account switch remounts the iframe (key `src|accountId`) instead of re-swapping in place.
  ASSUMPTION: rung 5 (no original-value bookkeeping like OF's WeakMaps). Overturned if the reload flash on a switch is judged too slow.
- The banner field on Fansly's `/account/me` is the Tracer facts `banner_field`, read from Phase 2's `account-me.shape.json` before this Phase's code; no recorded field means no banner swap.
- Fansly's dark marker is the Tracer facts `dark_marker`, the same constant Phase 3's boot script sets; the document module holds it. If the tracer records "stylesheet swap", the dark copy is parked for the owner before this Phase's code (Phase 3 Further Notes).
- The left rail's CSS reset (content margin after hiding `[data-oi-nav]`) is written against the captured layout.
  ASSUMPTION: rung 5 (OF's `OF_CHROME_CSS` precedent). The exact selectors fall to the first rendered capture, and `render.py` screenshots prove them.
- Bare `/fansly-manager` is a client page using `firstFanslyPage`, not a `next.config` redirect.
  ASSUMPTION: rung 2 (ticket 05 §1 says "first allowed nav entry", which needs flags and grants that only the client has). Overturned if a static redirect to Homepage is preferred.
- The A → B switch is proven in `navigate.py` with mocked accounts and a 2 s delayed `/users/me` for B, not with a second seeded Creator in verify-app.
  ASSUMPTION: rung 2 (coordinator 2026-11-27 trim, over ticket 05 §9's real-app switch). Overturned if the owner wants the switch shown in the real app, which brings the second seed back.
- The flag is turned on for AE by the coordinator after deploy, per Agency, through the relay's own flags code inside the client relay container (story 29).
  ASSUMPTION: rung 1 (flags are a per-Agency Settings blob, `FLAGS = ("fansly_manager",)` in `service/settings_schema.py:235`, applied only when `is True`, written only by `PUT /admin/settings/{tab}` → `write_blob`; no UI toggle and no per-deploy default exist), rung 3 (an existing skill already writes the live client DB in the relay container) and rung 4 (one blob key, set back to `false` the same way). Which Agencies: every AE Agency holding a Fansly Creator. Overturned if the owner wants only the client Agency, or wants the flag left off until they flip it.
- The watch check is a browser `app_errors` row on `/fansly-manager/`, because a static mirror has no relay route of its own to watch.
  ASSUMPTION: rung 3 (Focus-page row). Overturned if the owner wants a relay-side check on `/users/me` for Fansly accounts.
- `docs/spec/phase-01c-app-capability-table-and-fansly-ui.md`'s Acceptance expects `/fansly-manager/home` to answer 404, and that turns false when this Phase lands. This Phase supersedes that line, which is recorded here and not edited (another effort's spec). The parity matrix rows `1.1 Fansly Manager` and `1.1 Fansly Manager v1`, and the note at line 73, are rewritten in this Phase's PR.
- Opening the mirror's Notifications section never sends a notification ack: the mirror has no write hooks, and Built Notifications keeps its own ack.

## Review
codex (gpt, `model_reasoning_effort=high`, read-only sparse workspace), 2026-11-27. Blind call, then draft call. Both exited 0 with non-empty output.

Blind call:
- B1. Keep the four Built pages at their exact URLs, and prove one page through the real shell first. **reject**: the spec already does this (ticket 04). Tracer order belongs to the tickets step.
- B2. Alternatives: preview URLs, immediate replacement, embedded Built panels, app-native screens. **reject**: ticket 04 decided this, and static-first is the map's recorded assumption.
- B3. One route table for links, redirects, titles and grants. Ticket 03 says `post/post` and ticket 05 says `profile/post`. Which grant applies to an alias and which to its destination. **partial**: the slug conflict is already settled by Phase 3 (`profile/post`, phase-03 spec line 187). The grant question is accepted under D2, rewritten in stories 21 and 22 and in the route-module interface.
- B4. Creator-selection contract: precedence, foreign, unknown or expired picks, persistence, and multi-agency relay scoping. **partial**: precedence and the foreign, unknown and expired cases are already specced (`?creator=` only, pick module). Accepted: a failed `/users/me` (a relay 403 for another Agency's Creator) leaves the placeholders and never fills in another Creator, in the document-module interface and a chrome test. Sidebar persistence is rejected under D3.
- B5. Static HTML and app authorization have different boundaries; zero mirror-originated mutations. **partial**: raw `/fansly-mirror/*.html` being public is ticket 04 §Gates (rung 3), now stated in story 20. Accepted: `render.py` asserts no non-GET request from the frame.
- B6. Theme marker and banner shape unproven; on a slow A → B switch, A's identity must clear. **accept**: the banner comes from Phase 2's `account-me.shape.json` (Depends on, Shim contract, Further Notes), and `navigate.py` delays B's `/users/me` and asserts A's handle never shows. The theme marker stays Phase 3's guarded constant (its refusal "dark marker selector absent").
- B7. Test the browser → relay seam; the stock verify-app intercepts `/users/me` and `/img`. **accept**: merged with D6.
- B8. Falsifiers: a state that loads by URL but cannot open or close; real rows required. **partial**: opener open and close are accepted under D9. Real rows are rejected, because the map makes Phase 1 static-first.
- B9. The AE watch entry needs a named check and the PR URL. **reject**: the spec already has both (`fansly_mirror_errors`, `<PR url>`).

Draft call:
- D1. Four generated landings cannot pass a sweep of "every page in the table in-frame". **accept**: added `routableFanslyPages`. `render.py` sweeps it and asserts that the four shadowed public URLs reach Built; the raw-file test keeps the copies.
- D2. The earnings redirect skips the source grant. Only one grant combination is tested, and ADR-0012's enforcement-off and bypass states are untested. **partial**: rejected as a leak, because the target's own grant still gates the served page (`DeniedPage.tsx:34-41` runs on the target). Accepted: this is now explicit in stories 21 and 22 and the interface, with the reverse-combination nav test, a `grantedPages` `null` test, and denied deep links through the real layout in `navigate.py`.
- D3. `?creator=` is lost on the bare-group redirect, on modified clicks and on Built → mirror via the sidebar. **partial**: accepted for the bare group (`withCreator` in the bare-group page, a test, and `navigate.py`) and for modified clicks (`prepareFanslyDoc` rewrites in-frame hrefs, plus a test). The sidebar is rejected, because Built pages use bare sidebar hrefs today (`Sidebar.tsx:98-103`) and story 8 now says so.
- D4. Phase 2 is a direct dependency (`account-me.shape.json`), and Phase 3 can finish with an empty table that still passes `--check`. **accept**: Depends on is rewritten, and Acceptance requires `app/public/fansly-mirror/pages`. `render.py` fails on an empty table.
- D5. Scope creep: the stylesheet-swap fallback, and SessionGone for an expired pick. **reject**: the fallback is a contingency that only fires if Phase 2 falsifies the guess. It is not dark capture, so Fable's reduction stands. SessionGone for a scoped dead Creator is OF precedent (`OfManagerChrome.tsx:124,222`); the note is re-ranked rung 3.
- D6. The real-path commands cannot run: `drive.py api` refuses `/api/of` (measured, `drive.py:345-346`), `reads` skips `/img` (`drive.py:576-579`), the router serves `/img` from fixtures (`capture.py:93-94`), and the phone forces light. **accept**: the side effect is now `reads --match users/me` across two accounts. `/img` passes through to the real relay from a pre-seeded `IMG_CACHE_DIR` (`img_api.py:79,389`), checked with `drive.py api /img`. The dark phone shots set the theme on the phone page. ASSUMPTION added in Owns.
- D7. `! grep` does not trip `set -e`, and the hunk count passes zero hunks. **accept**: both are `if grep …; then exit 1; fi`, and a script checks that every hunk sits inside the `FANSLY_NAV` doc comment and literal and that there is at least one.
- D8. The tree-absent check runs only three `vitest related` inputs (`passWithNoTests: true`, `vitest.config.ts:31`) and never exercises the export. **partial**: accepted, the tree-absent run is now the full `pnpm test:run`. The replay, whole-tree gate and exported-route proofs are rejected here: they are Phase 1's (ticket 06, ADR-0067) and listed in Depends on.
- D9. Unit seams pass while the assembled route is broken: a bare page that never navigates, a layout that mounts the frame with the flag off, dead openers. **accept**: `navigate.py` covers the bare link with `?creator=`, flag-off and denied deep links through the real layout (no iframe, no `/users/me`), and opener open and close.
- D10. In-place identity refresh and live theme wiring are untested. **accept**: a late `me` on the same document fills the placeholders (test). A changed `me` for the same account is stated as not re-swapped, since a switch remounts. `dark.py` toggles the app theme light → dark → light with the frame mounted.

needs-human: none.

### Six hats (plan review, 2026-11-27)
Story numbers in the codex lines above refer to the pre-trim draft (31 stories; now 29).
- White, unresolved guesses (dark marker, banner field) — **accept**: both are Tracer facts measured before this Phase's code; the Shim `header` is conditional on a recorded `banner_field` (story 24, Shim contract, Further Notes).
- White, nothing turns the flag on for AE — **accept**: story 29; flags are a per-Agency Settings blob with no UI toggle and no per-deploy default, so the coordinator writes it after the AE deploy through the relay's own flags code (Further Notes ASSUMPTION on which Agencies).
- Black, Phases 3/4 built on guesses — **accept**: Depends on now names the Tracer facts.
- Black, Phase 4 scope creep — **accept**: second seeded Creator, `/img` cache seeding, SessionGone, OnlyFans-id and Watcher pick stories cut; pick module is `picked`/`standIn`/`none`.
- Green, Phase 4 cuts (switch mocked in `navigate.py`; pick states beyond first live Creator + NoCreators; Shim banner only if known; add the AE flag story) — **accept**: done as listed (stories 11, 24, 26, 29; pick module; Testing; Acceptance; Out of Scope). `picked` stays because the title-bar picker (story 9) needs it.
- Reorder (Phase 3+4 one PR after the tracer) — **accept**: Depends on rewritten; `render.py` absorbs Phase 3's raw-page check.
- Blue, a line on who turns the flag on — **accept**: story 29.
