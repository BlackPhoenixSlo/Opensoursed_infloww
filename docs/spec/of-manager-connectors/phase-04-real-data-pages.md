# Phase 04 — real data on profile, queue, collections, notifications, statements

**Objective.** In Single-Creator scope, the Mirror pages profile, profile/media, queue (month, list, messages, saved for later), collections/bookmarks/all, notifications (all, tips, subscriptions, comments, mentions) and statements (earnings, payouts, referrals) show that Creator's rows from the Relay in OnlyFans's own row markup instead of the Example rows, and put the Example rows back in All-Creators scope.

## Problem Statement

An Employee who opens the OF Manager for one Creator sees that Creator's chats, vault and user lists, but every other list page shows the captured Example rows: two "Lorem ipsum" posts by "Your Model", nine fake media tiles, an empty queue whatever is scheduled, an empty bookmarks page, notifications from "Fan 30", and earnings and payouts that are not the Creator's. The Employee cannot use these pages to check what the Creator posted, what is scheduled, who tipped or what was paid out, and cannot tell real data from the examples.

## Solution

With one Creator selected, each of these pages loads the Creator's rows through the Relay and draws them with OnlyFans's own markup: the profile shows the Creator's real posts and media grid, the queue shows what is scheduled this month and what is saved for later, the bookmarks page lists bookmarked posts, the notifications tabs list real notifications, and the statements tabs list real earnings, payout requests and referral payouts. Pictures load through the Relay's image proxy. Anything the Relay does not return is left empty, never made up. Row actions with no Known body (a post's "More" menu, "Create new list") answer with the Read-only note. With all Creators selected, or before data arrives, or on a Relay error, the pages stay exactly as captured.

## User Stories

1. As an Employee in Single-Creator scope, I want `profile` to list the Creator's own wall posts newest first, so that I see what the Creator actually published.
2. As an Employee, I want each post's text, date, pinned mark, first picture, like count and comment count taken from the Relay, so that the post card is the real post.
3. As an Employee, I want a post with no picture to show no picture area, and a post with no text to show no text block, so that empty fields are never filled with examples.
4. As an Employee, I want the post author's name, handle and avatar to be the Creator's, so that the header matches the profile (left to the identity hook, which already replaces the generator's placeholder everywhere on the page).
5. As an Employee, I want `profile/state-more-menu` to show the same real posts behind its menu, so that the state page matches its parent page.
6. As an Employee, I want `profile/media` to show one tile per photo or video post, merged newest first, three to a row, so that I see the Creator's media grid.
7. As an Employee, I want each media tile's picture and media count to come from the post, so that the tile is real.
8. As an Employee, I want `queue` (month view) to list the Creator's scheduled posts and messages for the month the calendar shows, so that I see what goes out this month.
9. As an Employee, I want `queue/state-list-view` to list the same month's scheduled items in place of "There are no scheduled events for this month", so that the list view is real.
10. As an Employee, I want `queue/state-tab-messages` to list the Creator's queued messages for that month, so that the Messages tab is real.
11. As an Employee, I want `queue/saved-for-later-posts` and `queue/saved-for-later-messages` to list the Creator's saved-for-later posts and messages in place of their empty state, so that those lists are real.
12. As an Employee, I want each queue item to show its time, its text (or "Media" when it has only media) and OnlyFans's post, message or saved-for-later colour mark, so that I can tell the items apart.
13. As an Employee, I want `queue/state-tab-streams` to stay as captured, so that no stream data is invented (the plan names no stream source).
14. As an Employee, I want `collections/bookmarks/all` to list the Creator's bookmarked posts in place of "No bookmarks yet", so that bookmarks are real.
15. As an Employee, I want a bookmarked post to show its own author's name, handle and avatar (empty when the Relay omits them), so that another creator's post is not shown as the Creator's.
16. As an Employee, I want `notifications` (All) to list the Creator's notifications of every type, so that I see what happened.
17. As an Employee, I want `notifications/tip`, `subscribed`, `commented` and `mentioned` to list only that type, so that each tab is real.
18. As an Employee, I want each notification's fan name, handle, avatar, text, date and unread mark from the Relay, so that the row is real.
19. As an Employee, I want the notification tabs with no plan-named source (Likes, Purchases, Promotions, Tags, OnlyFans) to keep their Example rows, so that the plan's scope holds.
20. As an Employee, I want `statements/earnings` to list the Creator's earning transactions with date, time, amount, fee, net, description and status, so that I can check the money.
21. As an Employee, I want `statements/payouts` to list the Creator's payout requests with date, time, invoice, amount and status, so that I can check payouts.
22. As an Employee, I want `statements/referrals` to list the Creator's referral payouts in the payouts table's row markup in place of "This list is empty", so that referrals are real.
23. As an Employee, I want every request these pages make to carry the selected Creator's `X-Account-Id`, so that one Creator's data never shows under another.
24. As an Employee, I want every picture on these pages to load through the Relay's `/img` proxy, so that OnlyFans's IP-bound CDN links load and no request leaves for OnlyFans directly.
25. As an Employee, I want a post's "More" button and the collections page's "Create new list" button to show the Read-only note, so that a click is never silent and never fakes success.
26. As an Employee in All-Creators scope, I want every one of these pages to keep its Example rows and make no Relay call for these Data parts, so that no Creator's data is mixed in.
27. As an Employee, I want a Relay error (no data) to leave the Example rows in place, and an empty Relay list to hide the Example rows and show the page's captured empty state, so that a broken feed never blanks the page and an empty feed is never shown as examples (precedent: `fill` hides examples with zero clones, ofMirrorData.ts:111-123; a missing Part keeps them, ofMirrorData.test.ts:155-160).
28. As an Employee switching from one Creator to another or to All Creators, I want the page to drop the previous rows and show the new ones (or the examples), so that nothing stale lingers.
29. As a maintainer, I want each Data part's field mapping written as a measured table (capture selector to Relay field), so that a recapture or a Relay shape change can be checked line by line.
30. As a maintainer, I want a Mirror check (`feeds.py`) and vitest cases per Data part, so that a recapture that changes a selector fails loudly.

## Implementation Decisions

- **Owns.** `ofMirrorData` (the Data parts, `DATA_PAGES`, `MirrorData`, `applyData`, `useOfData`); one optional field on `OfMe` and one exported query helper in `ofMirrorIdentity`; the new Mirror check `scripts/of-mirror-check/feeds.py`; the check `README.md` and `docs/routes.md` rows for these pages (Check loop item 3).
- **Interfaces.**
  - `Part` gains `posts`, `profileMedia`, `queue`, `bookmarks`, `notifications`, `transactions`, `payouts`, `referrals`.
  - `DATA_PAGES` gains: `profile/index` and `profile` (its state page) -> `posts`; `profile/media` -> `profileMedia`; `queue/index`, `queue/state-list-view`, `queue/state-tab-messages`, `queue/saved-for-later-posts`, `queue/saved-for-later-messages` -> `queue` (no bare `queue` key, so `queue/state-tab-streams` maps to nothing); `collections/bookmarks/all` -> `bookmarks`; `notifications/index`, `notifications/tip`, `notifications/subscribed`, `notifications/commented`, `notifications/mentioned` -> `notifications`; `statements/earnings` -> `transactions`; `statements/payouts` -> `payouts`; `statements/referrals` -> `referrals`. `collections/index` keeps `userLists`.
  - `MirrorData` gains one optional row array per new Part (`posts`, `profileMedia`, `queue`, `bookmarks`, `notifications`, `transactions`, `payouts`, `referrals`) and `templates?: Partial<Record<"post" | "agenda" | "payoutRow", Element>>` (see Templates). `applyData(doc, page, data, img)` keeps its signature and stays synchronous and idempotent; each new Part runs only when its rows are present, exactly like the existing Parts.
  - New pure export `queueMonth(doc): {start: string; end: string} | null`: parses the captured `.b-queue-header__date` text ("October 2026") into the first and last day of that month as `yyyy-mm-dd`.
  - `ofMirrorIdentity`: `OfMe` gains `id?: number | string`; the `["of-me", accountId]` query options are exported (`ofMeQuery(accountId)`) and used by both `useOfIdentity` and `useOfData`, so the two share one cache entry and one request.
- **Schema.** None — reads only.
- **Contracts.** Only existing Relay GET routes, all passthrough to `of_client` (`_proxy`), each sent with `X-Account-Id` via `relay.get(path, {accountId})`. Rows are read with the existing `rowsOf` (`{list}`, `{chats}` or a bare array).

  | Part | Page | Request |
  |---|---|---|
  | posts | profile/index, profile/state-more-menu | `GET /api/of/v2/users/{id}/posts?limit=20` (server.py:5555 -> of_client.py:875); `{id}` from `GET /api/of/v2/users/me` (server.py:2044) `id` |
  | profileMedia | profile/media | `GET /api/of/v2/users/{id}/posts/photos?limit=24` (server.py:5584) and `/posts/videos?limit=24` (server.py:5589) |
  | queue | queue/index, queue/state-list-view | `GET /api/of/v2/schedules?publish_date=<start>&publish_date_end=<end>&time_zone=<browser IANA zone>&limit=50` (server.py:5883) |
  | queue | queue/state-tab-messages | `GET /api/of/v2/messages/queue?limit=50` (server.py:5992), kept to items whose `scheduledDate` falls in `<start>..<end>` |
  | queue | queue/saved-for-later-posts | `GET /api/of/v2/schedules/later/post?limit=50` (server.py:5878) |
  | queue | queue/saved-for-later-messages | `GET /api/of/v2/schedules/later/chat?limit=50` (server.py:5873) |
  | bookmarks | collections/bookmarks/all | `GET /api/of/v2/posts/bookmarks/all?limit=20` (server.py:6914) |
  | notifications | notifications/index | `GET /api/of/v2/users/notifications?limit=20` (no `type`) (server.py:5359) |
  | notifications | notifications/tip, subscribed, commented, mentioned | same, plus `&type=`: tip -> `tipped`, subscribed -> `subscribed`, commented -> `commented`, mentioned -> `mentioned` (of_client.py:748-752, "verified live 2026-06") |
  | transactions | statements/earnings | `GET /api/of/v2/payouts/transactions?limit=20` (server.py:5907) |
  | payouts | statements/payouts | `GET /api/of/v2/payouts/requests?limit=20` (server.py:5478) |
  | referrals | statements/referrals | `GET /api/of/v2/payouts/requests/referral?limit=20` (server.py:6931) |

  `<start>`/`<end>` come from `queueMonth` on the loaded frame; the queue request waits until the frame has loaded once. The browser time zone is `Intl.DateTimeFormat().resolvedOptions().timeZone`, as `useScheduledMessages` does.

- **Method (all Parts).** Same as the existing Parts: hide the Example rows with `display:none` (`fill`), clone a template per real row with `make` (drops `data-oi-*` markers, marks `data-oi-data`), append, and register every change to a captured node with `track` so `restore` undoes it. Absent Relay field -> its element is removed or its text emptied (precedent: `applyChats` removes the unread dot, `applyVaultMedia` removes the date label). Text from OnlyFans HTML goes through `plain` (ofMirrorData.ts:130); dates through `valid`, `dayOf`, `clock`, `stamp`; pictures through `img` (= `proxyImage(url, accountId)`), still picked with `stillUrl` (ofMedia.ts:55). An empty Relay list counts as data: the examples hide and the captured empty state, where the page has one, stays visible.
- **Templates.** Three pages capture no row of their own (measured: `queue/*` have no `.b-agenda__area-events__item` anywhere in `app/public/of-mirror/pages/`; `collections/bookmarks/all` has no `.b-post`; `statements/referrals` has only the `.empty-message` row). Their template is taken from another captured page: `useOfData` fetches the static page same-origin (`/of-mirror/pages/<page>.html`, a plain GET of a committed file, never the Relay), parses it inertly with `DOMParser` (scripts do not run), and passes the element in `MirrorData.templates`; `applyData` adopts it with `doc.importNode`. Fetched once per session (query key `["of-mirror-template", page]`, `staleTime: Infinity`), only in Single-Creator scope and only on a page that needs it.
  - `post` = the first `.vue-recycle-scroller__item-view` containing `div.b-post` in `profile/index.html` (used by bookmarks; profile itself clones its own).
  - `agenda` = `.b-queue-scroll-wrapper` in `queue/state-list-view.html`, with its `.empty-message` removed (used by the month pages, which have no list block).
  - `payoutRow` = the first `.b-table tbody tr` with `.b-table__date` and `span.approved` in `statements/payouts.html` (used by referrals; its table has the same four columns, measured: Date & Time | Invoice | Amount | Status).
  - Queue items have no captured markup at all, so each item is built from the classes OnlyFans's own stylesheet defines for them (`queue-page-4c120c8f.css`: `.b-agenda__section`, `.b-agenda__section-date`, `.b-agenda__area-events`, `.b-agenda__area-events__item` with `post-indicator` / `chat-indicator` / `sfl-post-indicator` / `sfl-chat-indicator`, `.b-agenda__area-events__item-content`, `.b-agenda__area-events__item-details`, `.b-agenda__area-events__item-inward`), each element carrying the `data-v-*` scope attributes of the page's `.b-agenda` (the way `setAvatar` copies scope attributes, ofMirrorData.ts:154-156).
- **Row actions.** A post's `.b-post__tools__more button[aria-label='More']` (profile and bookmarks rows) and `collections/index`'s `button[aria-label='Create new list']` get a click handler that calls `note(doc, button, READ_ONLY)` (both exported from `ofMirrorWrites` by Phase 0) and carries no `data-oi-wired`: it sends nothing, so it is not a Wired control, and Phase 6's `dead.py` fails a marked control that shows the Read-only note. When Phase 6's click fallback lands, Phase 6 removes this handler if the fallback gives the same note. The handler is bound by `useOfData` on every frame load in both scopes (no Known body exists in either). "Request withdrawal" is captured `disabled` on both statements pages and stays so; queue items are built without a kebab (none captured), so "queue delete" has no control to bind.
- **Ordering.** `useOfData` stays mounted after `useOfIdentity` and `useOfRow` (OfMirrorFrame.tsx:17-22), so a cloned profile post already carries the identity hook's name, handle and avatar, and the real rows win over `useOfRow`'s.

### Field mapping — `posts` (profile/index; template: its own first `.vue-recycle-scroller__item-view` holding `div.b-post`; rows appended to that scroller's `.vue-recycle-scroller__item-wrapper`)

| Capture selector (inside the cloned row) | Relay field (`/users/{id}/posts` item) | Rule |
|---|---|---|
| `div.b-post` class `m-pinned` | `isPinned` | toggled |
| `.b-post__pinned` | `isPinned` | removed when not pinned |
| `.b-post__date > span` text | `postedAt` | `Mon D, YYYY` (en-US short month, day, year); removed when absent |
| `.b-post__date > span[title]` | `postedAt` | `stamp` ("May 20, 12:01 am") |
| `.b-post__text .g-truncated-text > div` (one `<p>`) | `text` (HTML) | `plain(text)`; `.b-post__text` removed and `m-post-has-text` dropped from `.b-post__content` when empty |
| `.post_media img.b-post__media__img`, `.b-post__media-bg img` src | `media[0]` | `img(stillUrl(media[0]))`; `.post_media__loading` removed; `.post_media` removed and `m-post-has-media` dropped when no still |
| `.b-summary-list a[aria-label='Show who liked this post'] > span` | `likesCount ?? favoritesCount` | link removed when both absent |
| `.b-summary-list a[aria-label='Show post comments'] > span` | `commentsCount` | link removed when absent |
| `.b-post__labels-controls .b-list-titles a` (example list "List 14") | none | removed (the Relay returns no post lists) |
| `.b-username .g-user-name`, `.g-user-username`, `.b-post__avatar .g-avatar` | none here | left to `useOfIdentity` (placeholder swap, ofMirrorIdentity.ts:43-114) |
| `[data-index]` | row index | renumbered |

### Field mapping — `profileMedia` (profile/media; grid `.b-photos.vue-recycle-scroller .vue-recycle-scroller__item-wrapper`, rows of 3 as `applyVaultMedia`)

| Capture selector | Relay field (`/posts/photos` and `/posts/videos` items, merged, de-duplicated by `id`, newest `postedAt` first) | Rule |
|---|---|---|
| `a.b-photos__item[at-attr='photo_item']` | one per post | cloned from the first captured tile |
| `img.b-photos__item__img` src | `media[0]` | `img(stillUrl(media[0]))`; the `img` removed when no still (never the example picture) |
| `.b-purchase__list-item__count` | `mediaCount ?? media.length` | `.b-subscribe-block` removed when 0 or absent |

The sidebar strip `.b-photos.m-recent-list` and the tab counts ("12 posts", "Photo 12") keep the captured values (Out of Scope).

### Field mapping — `queue` (items built from OnlyFans's agenda classes; see Templates)

Container: `queue/state-list-view` -> its own `.b-agenda.m-main-block` (its `.empty-message` hidden); `queue/index` and `queue/state-tab-messages` -> a copy of the `agenda` template inserted after the calendar (`.v-calendar`'s parent block), only when there is at least one item; `queue/saved-for-later-*` -> a copy of the `agenda` template inserted after `.saved-for-later > .g-page__header`, its `.empty-message` hidden.

| Built element | Relay field | Rule |
|---|---|---|
| `.b-agenda__section` | one per local calendar day of the item's time | sorted soonest first; saved-for-later items (no time) go in one section with no date |
| `.b-agenda__section-date` text | day | `dayOf` ("Oct 12") |
| `a.b-agenda__area-events__item` class | source | `/schedules` item `type: "post"` -> `post-indicator`, `type: "chat"` -> `chat-indicator`; `/messages/queue` -> `chat-indicator`; `/schedules/later/post` -> `sfl-post-indicator`; `/schedules/later/chat` -> `sfl-chat-indicator` |
| `.b-agenda__area-events__item-details` text | time: `/schedules` `publishDateTime` (useScheduledMessages.ts:11); `/messages/queue` `scheduledDate` (relay.ts:831-835) | `clock`; empty when absent |
| `.b-agenda__area-events__item-inward` text | `/schedules` `entity.text`; other sources `text` | `plain(text)`, else "Media" when `mediaCount > 0` (precedent `applyChats`), else empty |

The month calendar's day cells (`.b-month-day-cell`) are not changed: no captured markup marks a day with items.

### Field mapping — `bookmarks` (collections/bookmarks/all; template `post`; rows appended to `.l-main-content.m-r-side .g-page-content__body`, whose `.empty-message` is hidden)

Same as `posts`, plus:

| Capture selector | Relay field | Rule |
|---|---|---|
| `.b-username .g-user-name` (text node before the verified icon) | `author.name` | empty when absent |
| `.g-user-username` | `author.username` | `@<username>`; empty when absent |
| `.b-post__avatar .g-avatar` | `author` | `setAvatar(el, author, img)`; when `author.avatar` is absent the cloned `img` (with its `.g-avatar__img-wrapper`) is removed, since `setAvatar` returns early and would keep the template's picture (ofMirrorData.ts:148); the placeholder letter is set where the template has one |
| `.b-post__avatar a`, `a.b-username` href | none | `#` (another creator's profile is not mirrored) |

The sidebar "Recent" list (`.b-bookmarks__list`) keeps its captured empty state.

### Field mapping — `notifications` (notifications/index, tip, subscribed, commented, mentioned; template: the first `.vue-recycle-scroller__item-view` whose `.b-notifications__list__item` has no `.b-list-titles a`, i.e. the "Add to favorites and other lists" variant)

| Capture selector | Relay field (`/users/notifications` item) | Rule |
|---|---|---|
| `.b-notifications__list__item` class `m-unread` | `isRead` | present when `isRead === false`; dropped otherwise |
| `.b-username .g-user-name` | `user ?? fromUser` `.name` | `nameOf` (name, else username, else id) |
| `.g-user-username` | `user ?? fromUser` `.username` | `@<handle>` (`handleOf`) |
| `.b-available-users__round-img .g-avatar` | `user ?? fromUser` `.avatar` | `setAvatar` (also drops the example's online dot); absent avatar -> the cloned `img` removed, as bookmarks |
| `.b-notifications__avatar__icon svg` | item `type` | `subscribed` -> `icon-follow`, `tip` or `tipped` -> `icon-price` (the two measured on those tabs; items carry `tip`, notifSettings.ts:120); other types: the icon block removed |
| `.b-notifications__list__item__text .g-truncated-text` | `text` with `replacePairs` applied | `plain(...)` (replace as `NotificationBell.renderText`); the example's trailing `<a>` removed |
| `.g-date > span` text / `title` | `createdAt` | `dayOf` / `stamp`; removed when absent |
| `[data-index]` | row index | renumbered |

### Field mapping — `transactions` (statements/earnings; templates: a captured `tbody tr` whose `.b-table__status svg` is `icon-done`, and one whose is `icon-loading`; rows inserted before the `.infinite-loading-container` row)

| Capture selector | Relay field (`/payouts/transactions` item; field names as `transaction_ingest._parse_row`, transaction_ingest.py:241-258) | Rule |
|---|---|---|
| `.b-table__date__date > span` | `createdAt` | `Mon D, YYYY` |
| `.b-table__date__time > span` | `createdAt` | `clock` |
| `.b-table__amount > span` | `amount` | `$` + 2 decimals; empty when absent |
| `.b-table__fee > span` | `fee` | same |
| `.b-table__net strong > span` | `net` | same |
| `.b-table__desc .b-field-subscription` | `description` (HTML) | `plain(description)` (its fan link becomes text) |
| `.b-table__status .b-table__status-tip`, and its copy inside `.b-table__desc` | `status` | `done` -> the `icon-done` row ("Complete"); `loading` -> the `icon-loading` row with `aria-label` "Earning will become available in N days", N = `payoutPendingDays` (sentence dropped when absent); any other status -> both status tips removed |

### Field mapping — `payouts` (statements/payouts; templates: a captured row with `span.approved`, and the one with `span.rejected`)

| Capture selector | Relay field (`/payouts/requests` item) | Rule |
|---|---|---|
| `.b-table__date__date > span`, `.b-table__date__time > span` | `createdAt` | as earnings |
| `.b-table__invoice` | `invoice` | text; empty when absent |
| `.b-table__amount strong > span` | `amount` | `$` + 2 decimals |
| `.b-table__desc > span.approved` | `state` | `done` or `approved` -> the approved row as captured ("Payout has been processed") |
| `.b-table__desc > span.rejected` | `state`, `reason` | `rejected` -> the rejected row, its "Reason: …" line replaced by `reason` (removed when absent) |
| `.b-table__desc` | other `state` | emptied |

### Field mapping — `referrals` (statements/referrals; template `payoutRow`; rows appended to `.b-table tbody`, its `.empty-message` row hidden)

Same columns and rules as `payouts`, from `/payouts/requests/referral` items.

## Testing Decisions

- **Seam 1 — `applyData` (vitest, `app/lib/ofMirrorData.test.ts`, extended).** The public interface is `applyData(doc, page, data, img)` plus `restore`, `partsOf` and `queueMonth`, run against the committed captures loaded as the existing `load(p)` does; templates are read from their captured pages with `readFileSync` and `DOMParser`. Per Part: the rows are cloned in order with exactly the mapped values; no Example text is left visible (`PLACEHOLDER` regex extended with `Lorem`, `Your Model` only where the identity hook is not in play, `Fan \d`); an absent field renders empty; `img` is used for every picture; an empty list hides the examples and keeps the captured empty state; `restore` (via a second `applyData(doc, page, {})`) gives back the captured HTML byte for byte (the existing `it.each(Object.keys(DATA_PAGES)...)` case covers every new page automatically). Plus: `partsOf` for every new page and for `queue/state-tab-streams` (nothing); `queueMonth` on `queue/index` gives `2026-10-01..2026-10-31`; a post's More button and `collections/index`'s "Create new list" button note `READ_ONLY`; an avatar-less author or a still-less media post keeps no captured picture; `applyData` with Creator A's rows then Creator B's rows shows only B's rows (no A row left).
- **Seam 2 — Mirror check `scripts/of-mirror-check/feeds.py` (Playwright, style of `data.py`).** Mocks the login as `data.py`, `/users/me` with `{"id": 1, "username": "livemodel", "name": "Live Model"}`, every route in the Contracts table with 2-3 synthetic rows ("Alpha One", `https://cdn.example.invalid/...` pictures), `/img*` with a generated 1x1 PNG, unmocked `/api/**` with `[]`, and fails on any request to a non-localhost host. For each page: exactly the synthetic rows are visible in order, no `Fan \d`, `@fan\d` or `Lorem` text in the list, every relay call carries `X-Account-Id: 1`, every visible row picture has an `/img?` src with `account_id` and `naturalWidth > 0`, the queue request carries `publish_date=2026-10-01&publish_date_end=2026-10-31` and a `time_zone`, every request carries its Contracts-table `limit`, the notifications requests carry the tab's mapped `type` (`tipped`, `subscribed`, `commented`, `mentioned`; none on All), a post's More click and the "Create new list" click each show `READ_ONLY`, no console errors. Creator-switch pass: on `profile` and `notifications`, switch from account 1 to account 2 (distinct synthetic rows): only account 2's rows are visible, every later relay call carries `X-Account-Id: 2`, then All Creators brings the Example rows back. All-Creators pass: each page shows its Example rows and none of these Relay routes is requested. Prints one JSON line per check; screenshots to `/tmp/of-mirror-shots/inapp-feeds-*.png`.
- The existing `data.py`, `render.py` and `navigate.py` must still pass (they share `applyData`).
- Prior art: `app/lib/ofMirrorData.test.ts` (clone/restore cases for chats, vault, lists), `scripts/of-mirror-check/data.py` (mocked relay, `SHOWN`, `IMAGES`, `settle`), `scripts/of-mirror-check/writes.py` (request recording).

## Acceptance

```sh
pnpm -C app exec vitest run lib/ofMirrorData.test.ts lib/ofMirrorIdentity.test.ts
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
node scripts/of-mirror.mjs --check
export PORT=3091
(cd app && npx next dev --webpack -p "$PORT" >/tmp/of-mirror-dev.log 2>&1 &)
for i in $(seq 1 120); do curl -sf "http://localhost:$PORT/" >/dev/null && break; sleep 1; done
python3 -I scripts/of-mirror-check/feeds.py
python3 -I scripts/of-mirror-check/data.py
python3 -I scripts/of-mirror-check/render.py
python3 -I scripts/of-mirror-check/navigate.py
grep -q "feeds.py" scripts/of-mirror-check/README.md
grep -q "feeds.py" docs/routes.md
# manual: Read /tmp/of-mirror-shots/inapp-feeds-*.png (OnlyFans's look kept, real rows visible, Read-only note visible on the More click); never commit them.
```

## Depends on

- Phase 0 — exports `note`, `READ_ONLY` (and `SELECT_MODEL`) from `ofMirrorWrites`, used for the row-action Read-only note. Nothing else; the Data parts do not depend on Phases 1-3 or 5.

## Out of Scope

- Stream items on `queue/state-tab-streams`: the plan names no stream source for the queue (YAGNI).
- Notification tabs Likes, Purchases, Promotions, Tags, OnlyFans: the plan keeps their examples.
- Statements index, Earning Statistics, Chargebacks tabs, the balance boxes and the referral balance: not named by the plan.
- Profile tab counts ("12 posts", "Photo 12", "Video 1"), the Photo/Video sub-tab filters, the sidebar recent-media strip, the label tabs: not named by the plan; their controls are Phase 6's click fallback.
- Paging beyond the first page (infinite scroll, `tailMarker`), queue month navigation (`.b-queue-header__btn`): the plan asks for the shown rows only (YAGNI).
- Marking calendar day cells that have items: no captured markup for it.
- Video play buttons and durations on post and media tiles, post prices and locks, poll or quiz bodies inside posts: not in the captured post template (YAGNI).
- Writes of any kind: edit, delete, pin, unbookmark, mark-read, withdraw, list create (plan Constraints, ADR-0005).
- Like, comment, statistics, bookmark and add-to-list buttons on rows: Phase 6's fallback gives them the Read-only note.

## Further Notes

- The notification `type` values follow the capture and the observed code, not the plan's literal list. The plan says index=`all`, tip=`tips`, subscribed=`subscribes`, commented=`comments`, mentioned=`mentions` (from the server.py:5363 docstring). But of_client.py:748-752 says plural forms return 400 and the working filters are past-tense singular ("verified live 2026-06"). The captured tab hrefs are `tip`, `subscribed`, `commented`, `mentioned`, and `NotificationBell` already sends exactly these with no `type` for All (NotificationBell.tsx:52-62). The Relay passes `type` through unchecked (server.py:5359-5394).
  ASSUMPTION: rung 1 over the plan's literal values (the observation shows those values would 400, which would leave every tab on examples). The Tips tab sends `tipped`, the only value of_client.py:750 records as verified live, although NotificationBell.tsx:57 sends `tip` (unverified). Overturned if a live check shows `tipped` fails or `tips`/`all` work.
- The plan's "same clone-template-row method" cannot hold on four pages that capture no row (queue/*, bookmarks, referrals, the month view's list). Those pages take a template from another captured page fetched same-origin, and queue items are built from OnlyFans's own stylesheet classes.
  ASSUMPTION: rung 5 (it reuses captured markup and adds no dependency; the alternative of leaving these pages on their empty state would shrink the plan's goal). Overturned if review prefers building bare elements from OnlyFans classes for every page (the `chatMediaTemplate` fallback, ofMirrorData.ts:214-237), or dropping these pages.
- The month view has no captured list block, so the month's items show in a copy of the list view's agenda block placed under the calendar.
  ASSUMPTION: rung 4 (additive, removed by `restore`); overturned by a capture of OnlyFans's month view with events.
- `queue/state-list-view` is not named in the plan; it is the only queue page with a captured agenda container, so it is wired to the same `/schedules` month as `queue/index`.
  ASSUMPTION: "evidence never shrinks the goal" (the list view is part of the queue); overturned if the human wants only the plan-named pages.
- `queue/state-tab-messages` uses `/messages/queue` as the plan says, although `useScheduledMessages.ts:6-9` notes that endpoint returns stale or empty data for sends scheduled with OnlyFans's newer flow (`/schedules` `type: "chat"` is the newer source).
  ASSUMPTION: plan constraint kept; flagged as a risk. Overturned if the human switches this tab to `/schedules` chat items.
- The shown month is read from the captured header (`.b-queue-header__date`, "October 2026"), not today's date, because the captured calendar grid is fixed to that month.
  ASSUMPTION: rung 5; overturned when the mirror gets month navigation.
- Field names with no observation in the repo (live OnlyFans is out of bounds): payout requests `invoice`, `state` (`done`/`approved`/`rejected`), `reason`; notifications `isRead`; bookmarked post `author {name, username, avatar}`; saved-for-later items `text`, `mediaCount`.
  ASSUMPTION (evidence blocked): names follow OnlyFans's other payloads in this repo; a wrong name renders that field empty, never invented. These table rows are therefore guessed, not measured as the plan asks: `feeds.py` proves the mapping, not the Relay's shape. Overturned by a recorded Relay response for each route.
- Notification type icons other than `subscribed` (`icon-follow`) and `tip` (`icon-price`) are removed rather than guessed (the comments and mentions tabs mix `icon-account` and `icon-follow`).
  ASSUMPTION: rung 5; overturned by a measured type-to-icon map.
- The post `id` for `/users/{id}/posts` comes from `/users/me` as the plan says, though `useMyFeed` (usePosts.ts:104-125) uses the account id directly as the OnlyFans user id.
  ASSUMPTION: plan constraint kept; the shared `["of-me"]` query adds no extra request on pages where `useOfIdentity` already ran.

## Review

codex, 2026-10-12 (blind call + draft call, `model_reasoning_effort=high`, both exit 0).

Blind call:
- **reject** — Plural notification filters (`tips`, `subscribes`...) would 400: already decided in Further Notes against the plan's literals; the `tip` sub-point is handled under draft finding 1.
- **reject** — Queue streams have no Part: the plan's queue list names no stream source (plan:204-206) and `/schedules` returns chats and posts only (of_client.py:1214-1219); `queue/state-tab-streams` stays captured (Story 13, Out of Scope).
- **partial** — `state-tab-messages` source: of_client.py:1234-1236 calls `/schedules/later/chat` what OF's Queue tab shows and `/messages/queue` the older API. The plan names `/messages/queue` (plan:205), a binding constraint; the risk was already flagged in Further Notes and the claim is now cited there by this line.
- **partial** — Pagination and date window not asserted: paging stays Out of Scope (plan asks for the shown rows); `feeds.py` now also asserts `time_zone` on the queue request and each route's `limit`.
- **reject** — Statements scope ambiguous: Out of Scope already names the statements index, stats and chargebacks tabs; of_client.py:1278's note is about a statements-history path this spec does not call.
- **accept** — Single-Creator error vs empty result unclear: merged with draft finding 4; Story 27 rewritten (error keeps examples, empty list shows the captured empty state).
- **reject** — Alternative: page-specific hooks: house precedent is one Part pipeline in `ofMirrorData` (ofMirrorData.ts:489-506) and the plan says "new `Part`s in `ofMirrorData.ts`" (plan:202).
- **reject** — Alternative: `/users/me/posts` (server.py:5562 accepts `me`): the plan fixes `id` from the `["of-me"]` query (plan:203); kept as a constraint, already flagged in Further Notes.
- **reject** — Alternative: `posts?type=` instead of photos + videos merged: the plan fixes "photos + videos merged newest first" (plan:204).
- **partial** — Keep examples until each field contract is measured: the plan wants real rows now; unmeasured fields render empty, never examples, and are now labelled guessed (draft finding 3).
- **reject** — Test at the iframe runtime boundary: that is Seam 2 (`feeds.py`, the `data.py` seam) already; no change.

Draft call:
- **needs-human** — Tips tab `type`. Codex: of_client.py:748-752 records `tipped` as the live-verified filter, so `tip` may 400 and a mocked `feeds.py` would still pass. Spec before review: `tip`, as NotificationBell.tsx:57 ships it. Decision for now: `tipped` (the only value with a recorded live check), ASSUMPTION in Further Notes. Settles it: one live `GET /api/of/v2/users/notifications?type=tipped` and `?type=tip` for a Creator with tips; whichever returns tip rows wins, and NotificationBell should follow.
- **accept** — Fallbacks leave example pictures: `profileMedia` now removes the `img` when no still; bookmarks and notifications remove the cloned `img` when the author has no avatar (`setAvatar` returns early, ofMirrorData.ts:148); vitest asserts both.
- **partial** — Mapping called measured while names are guessed: true for the fields listed in Further Notes, but live OnlyFans is out of bounds (floor 2); those rows are now labelled guessed, not measured, and render empty when wrong.
- **accept** — Story 27 contradicted the Method on an empty list: Story 27 rewritten to the house behaviour (`fill` with zero clones hides examples, ofMirrorData.ts:111-123; missing Part keeps them, ofMirrorData.test.ts:155-160).
- **accept** — "Create new list" Read-only note untested: added to the vitest and `feeds.py` cases.
- **accept** — Creator-to-Creator switch untested: vitest A-then-B case and a `feeds.py` switch pass (account 1 -> 2 -> All Creators) added.

### Six hats

Source: `.scratch/of-manager-connectors/SIX-HATS.md`, 2026-10-12. Set-level bullets are reconciled in `plan-review.md`.
- White, departure 2 (notification types `tipped`/`subscribed`/... instead of the plan's plurals): **accept** as fact. The decision stays on rung 1 (Further Notes), the `tipped` value stays needs-human, and the plan is not edited (Open questions in `plan-review.md`).
- White, several field names are guessed, not measured as plan:213 asks: **accept**. They are already labelled guessed (Further Notes) and are parked under Needs the human in `plan-review.md`.
- Red, borrowing templates from other captured pages and building queue items from CSS classes is fragile: **partial**. The method stays, because the only alternative that meets the plan is dropping pages it names (see the Green line below). A recapture that moves a selector fails vitest against the real captures (Testing Decisions), so the method fails loudly, not silently.
- Black, duplicated read-only handling: **accept**. The row-action handler (post kebab, "Create new list") now carries no `data-oi-wired`. Before this change it would have failed Phase 6's rule that a marked control must not show the Read-only note (phase-06 Testing → Failures; glossary "Wired control"). Phase 6 removes the handler once its fallback gives the same note (Row actions).
- Green, drop the borrowed-template pages (bookmarks, referrals, queue month view): **reject**. The plan's table says wire (data) for `collections/bookmarks/all`, `statements/referrals` and `queue/*` (plan:60-61, 64). Dropping them would shrink the plan's goal (HEADER: evidence never shrinks the goal).
- Green, drop the `queue/state-list-view` wiring the plan never asked for: **reject**. The plan's row is `queue/*` (plan:60), which covers it, and it is the page that supplies the `agenda` template.
