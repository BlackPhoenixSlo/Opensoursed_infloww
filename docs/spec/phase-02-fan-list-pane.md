# Phase 02 — Fan List pane

**Objective.** The Fan List renders Infloww's left pane element for element: the header, the "New" menu, the "All inboxes" selector backed by Split Inbox groups, the gear, the "Newest first" sort, the filter and Chat folder chips, Focus mode, Row badges, the spend display and the empty state. Four components replace `ChatList`, and our extras sit where they never displace an Infloww element.

## Gap table

Clone values are measured from `ui-redesign/infloww-exact/messages.html` (CSS lines `mh:N`, markup lines `mh:N`), `messages.js` (`mj:N`) and `_shared/components.html` (`kit:N`). "Ours" refers to `app/components/chat/ChatList.tsx` (`CL:N`) unless a different file is named. Colours are not measured, because ADR-0001 assigns them from our tokens (see Implementation Decisions).

| # | Clone selector and CSS (measured) | Ours | Gap | Change |
|---|---|---|---|---|
| 1 | `.list` width 390px, border-right 1px (mh:116) | `app/app/messages-pro/page.tsx:189` grid column `320px` | 70px narrower | None in Phase 2. Pane widths belong to Phase 6, so this stays a VISUAL GAP until then. |
| 2 | `.list-head` padding 16px 16px 12px, gap 6px (mh:117) | CL:707 `p-3` (12px all sides) | padding | 16/16/12, gap 6 |
| 3 | `.list-head h1` 22px / 700, flex 1 (mh:118); markup shows the Creator name (mh:630) | CL:709-710 `text-sm font-semibold` (14px / 600); shows "Unified Inbox" in all scope | size, weight, label | 22px / 700. All scope reads "All Models" (glossary). |
| 4 | `.list-head .icon-btn` 26×26, radius 7, svg 20px (mh:77, mh:119). Order: gallery, search, "+" New (mh:631-633) | header holds a row count (CL:714), ↻ (CL:734) and "⚙ Settings" (CL:744) | no search icon, no New | Add a search icon and a "+" New icon. ↻ and ⚙ move to row 7. The gallery icon is not added (Out of Scope). |
| 5 | `#newBtn` popover rows: "Mass message", "Message online fans", "Broadcast" (ours), "New post" (mj:1626-1631); `.pop` radius 10, padding 6, min-width 238, 13px; `.prow` padding 8px 10px, radius 7, gap 9 (mh:361-364) | none | missing | New menu: "Mass message", "Message online fans", "Post", in that order, with `.pop` / `.prow` geometry |
| 6 | `.big-btns` "Online Fans" / "Notifications", height 42 (mh:122-126, mh:636-645) | none | sits in the clone's list pane | None here. Phase 1 builds both as the Fan List buttons under the Fan List header, through the `actions` slot it adds to `FanList` (`phase-01-window-chrome-tabs.md:157-159`). |
| 7 | `.filter-row` gap 10px, padding 2px 16px 12px, wraps with row-gap 6px (mh:130, mh:357) | none | missing row | Add the row: selector, gear, spacer, sort line |
| 8 | `.inbox-box` "All inboxes": border 1px, radius 9px, padding 9px 11px, 13.5px, gap 8px, icon 16px, chevron 14px, flex 1, min-width 150px (mh:131-133, mh:354, mh:647-651) | none | missing | Split Inbox group selector at this geometry |
| 9 | `.filter-row .gear` 34×34, radius 8, svg 19px (mh:134-136) | CL:744 "⚙ Settings" button, 24px tall, with a text label | size, label | Icon-only 34px gear. The menu keeps its items (CL:759 onward) minus sort, plus Focus mode. |
| 10 | `.sortline` gap 9px, 13px, svg 17px; label "Needs reply" `[CL ?]`, then sort icon, then refresh icon (mh:137-139, mh:655-659) | sort radios inside Settings (CL:802); ↻ in the header (CL:734) | location, label | Sort control in the sort line, labelled with the current sort, default "Newest first". ↻ moves here. |
| 11 | `.chips` gap 8px, padding 0 16px 12px, horizontal scroll, no scrollbar (mh:141-142) | CL:853 `gap-1` (4px), `flex-wrap` | gap, wrapping | 8px gap, scroll |
| 12 | `.chip` padding 7px 15px, radius 16px, 13px / 500, no border (mh:143-144) | CL:1244 `md:px-2 md:py-0.5`, border, 11px | size, border | Clone values |
| 13 | Chip labels and order: All, Unread, ↩ Owe reply (ours), Pinned, Priority, Unread tips `[CL ?]` (mh:662-667) | CL:853-879: All, Unread, "📌 Pinned", "⚡ Priority", "↩ Owe reply" | emoji in labels; Owe reply inline | "All", "Unread", "Pinned", "Priority", then the Extras overflow "+" that holds "↩ Owe reply". "Unread tips" is not added. |
| 14 | `.chip .cbadge` absolute top −5px, right −4px, min-width 17, height 17, radius 9, 10px / 700, padding 0 3px; amber variant for owe (mh:145-146) | CL:1251 count pill inline inside the chip; All carries the attention count (CL:857) | position; All badge | Corner badge. All has none; the attention count stays in the tab title. |
| 15 | `.fchip` gap 6, padding 6px 13px, 12.5px / 500, radius 16, border 1px transparent, folder svg 13px; row padding-bottom 10px (mh:147-152) | CL:901 "📂 name" in a generic chip | emoji instead of icon; size | Folder icon at 13px, clone values. Re-clicking the active chip clears it (mj:3076). |
| 16 | `.fchip.edit` "✎ Lists", last in the folder row, shown when the Creator has any list (mj:3067) | CL:910 / CL:924 bare "✎" | label, condition | "✎ Lists". The existing folder picker (CL:1268) stays a modal. |
| 17 | `.conv` gap 12px, padding 13px 16px, border-bottom 1px (mh:159) | CL:1040 `px-3 py-2.5`, gap 10px | padding, gap | Clone values |
| 18 | `.av-wrap` / `.av` 48×48, round, 13px / 700 initials; `.av.purple` text 12px; `.av.coral` + `.xmark` (mh:162-168) | CL:1053 36px | 12px smaller; no variants | 48px slot that shows the photo, the spend figure or the expired mark (decisions below) |
| 19 | `.dot` online 12px at bottom 1 / right 1, 2px ring (mh:169) | none; `isOnline` is fetched (`app/lib/relay.ts:509`) | missing | Online dot |
| 20 | `.spend` absolute bottom −7px, left −3px, 11px / 700, padding 1px 5px, radius 8 (mh:171); `[PAL]` "grey pill `$0`"; C[H262067] "orange total-spend number replaces the avatar" | CL:1113 "$N" on a third line, and only when above 0 | position; `$0` missing; no avatar replacement | Spenders get the orange total in the avatar slot. Everyone else gets a pill at `.spend` geometry. |
| 21 | `.conv-top` gap 5; `.cname` 14px / 700, max-width 170px; `.chandle` "@handle" 13px; `.cx` "×" (mh:174-178) | CL:1081 name at 14px / 500; no handle | weight, handle | 700, add "@handle". "×" is not added (Out of Scope). |
| 22 | `.off-label` 11px / 800, letter-spacing .5px (mh:179); `.fx-new` 9px / 700, padding 2px 6px, radius 5 (kit:188). New, 🔥 and ❄️ have no clone CSS | CL:1098-1125: third line with "last buy …" and "renews/ends …" | Row badges missing | Badge strip (decisions below) |
| 23 | `.conv-bot` gap 6, margin-top 4; `.cprev` 13px, bold 600 when unread; `.ctime` 12px (mh:181-185) | CL:1095 time 10px on line one; CL:1099 preview 12px | position, size, bold | Time on line two at 12px, preview 13px, bold when unread |
| 24 | `.ud` unread dot 9px; `.owe-dot` 9px (mh:187-188) | CL:1153 18px count badge; CL:1161 8px owe dot | size, count | 9px unread dot, with the count in its tooltip. The owe dot follows the extras rule. |
| 25 | `.mute-i` 14px in the status slot (mh:190) | CL:1079 🔕 before the name, row at 60% opacity | position | Mute icon in the status slot, no dimming |
| 26 | Empty state "No conversations found", padding 24px 16px, 13px (mj:481-482, mj:575) | CL:953 "No chats." plus a Refresh button | label | Clone line. Refresh stays in the sort line. |
| 27 | Skeleton: 6 rows, padding 13px 16px, gap 12, 48px avatar, two 11px bars at 52% and 78%, gap 10 (mh:566-571) | CL:970: 10 rows, 36px | count, size | Clone values |
| 28 | `.load-more` "Load more conversations", 13px / 600, padding 14px 16px, border-top (mh:155-156, mj:581) | CL:1201 / CL:1216 "loaded N chats · load more" | label | Clone label, with the count in its tooltip |
| 29 | Focus mode banner: no clone element; C[H262067]; `.fx-note` gap 10, padding 11px 14px, radius 10, 13px (kit:191) | none | missing | Banner at the top of the rows |
| 30 | Split Inbox screens: no clone element; C[H262029]; `.fx-select` height 38, radius 9, 13.5px (kit:106-108) | none | missing | Split Inbox dialog |
| 31 | Search: a header icon whose clone handler is a `prompt` (mj:3187-3204) | CL:847 search input always visible | a whole row vs an icon | Icon toggles an input row |

ASSUMPTION: the New, 🔥, ❄️ and Off placement and size (row 22), the banner (row 29) and the dialog (row 30) have no Messages Pro clone source, so their geometry is borrowed from the `_shared/components.html` kit or from neighbouring clone classes. A real Infloww capture or the Phase 6 measurement would overturn this.

## Problem Statement

An Employee coming from Infloww opens our Messages Pro and finds a left pane that works differently. It is narrow and dense, with a 36px avatar, 11px chips and the time squeezed onto the name line. Its header carries our controls: a row count, a text "Settings" button and a search box that takes a whole row. There is no "New" menu, no "All inboxes" selector and no way to split a Creator's Fans among Employees. The filter chips carry emoji, and our "↩ Owe reply" sits among Infloww's chips. Rows put spend, "last buy" and renewal text on a third line instead of Infloww's signals: New, 🔥, ❄️, ❌, Off, the orange spend figure and the `$0` pill. The default order is our spend-and-unread ranking rather than "Newest first". There is no Focus mode, so the list jumps whenever a message arrives. Everything lives in one 1,387-line `ChatList.tsx`, which no Phase can change safely.

## Solution

The left pane matches Infloww's. At the top are the Creator's name, a search icon and a "+" New menu (Mass message, Message online fans, Post). Below them sits a row with the "All inboxes" selector, a gear, the sort ("Newest first") and refresh. Then come the chips All, Unread, Pinned and Priority, with our Owe reply tucked into a "+" Extras overflow, and then the Creator's Chat folder chips ending in "✎ Lists". Rows show a 48px avatar, or in its place the Fan's orange Total spend. Fans with no spend get a `$0` pill, expired Fans get a red ✕ avatar, and the badges New, 🔥, ❄️ and Off sit beside the name and handle, with the preview and time underneath. Owners can split a Creator's Fans into 1 to 9 Split Inbox groups and move Fans between them. Every Employee then filters to one group from the "All inboxes" selector, on any device. Focus mode freezes the list and counts new messages in a banner, and clicking the banner refreshes. The pane is built from `FanListHeader`, `FanListFilters`, `FanRow`, `FanList` and `SplitInbox`.

## User Stories

1. As an Employee, I want the Fan List header to show the Creator's name in large type, so that I always know whose chats I am working.
2. As an Employee viewing All Models, I want the header to read "All Models", so that the combined view is named by its glossary term.
3. As an Employee, I want a search icon in the header that opens the name search, so that searching does not cost a permanent row.
4. As an Employee, I want a "+" New menu listing "Mass message", "Message online fans" and "Post" in that order, so that I can start outbound work from the inbox the way Infloww does.
5. As an Employee, I want "Mass message" to open the existing mass-message composer for the Creator in scope, so that I do not have to leave Messages Pro to send one.
6. As an Employee, I want "Message online fans" to open the same composer in its online mode, so that I can reach Fans who are online now.
7. As an Employee, I want "Post" to take me to OF Manager's New post page, so that the menu's third item goes where posts are made.
8. As an Employee, I want broadcasting from all models to stay reachable through Mass message, so that losing an Infloww-shaped menu costs me no feature.
9. As an Employee, I want an "All inboxes" selector beside a gear, so that I can narrow the Fan List to one Split Inbox group.
10. As an Employee on a Creator with no split, I want the selector to offer only "All inboxes", so that it never shows empty groups.
11. As an Employee, I want the gear to hold the list settings (Mark all as read, Keep fan info panel open, the two blur options, Compact media previews, Focus mode), so that the header carries only Infloww's controls.
12. As an Employee, I want the sort control to read "Newest first" by default, so that the list orders the way Infloww's does.
13. As an Employee, I want our other orders (Amount spent, Spend + unread on top, Spend + recency) kept in the Fan List's "+" Extras overflow, each with an "Inflowwww extra" tooltip, and the sort control to show the chosen order's name, so that I keep them without mistaking them for Infloww's.
14. As an Employee, I want any sort I choose, including "Spend + unread on top", to be kept across reloads, so that the new default does not override my choice.
15. As an Employee, I want a refresh icon in the sort line that forces a fresh list, so that I can recover from missed realtime events as I can today.
16. As an Employee, I want the chips All, Unread, Pinned and Priority in that order and at the Clone's size, so that the filters sit where my hands expect them.
17. As an Employee, I want the Unread chip to show its count in a corner badge, so that I can see my backlog without switching filters.
18. As an Employee, I want Pinned and Priority to show their counts while active, so that I know how many Pinned chats or priority chats I am looking at.
19. As an Employee, I want "↩ Owe reply" in a "+" Extras overflow at the end of the chips, with its count and an "Inflowwww extra" tooltip, so that our filter never displaces an Infloww chip.
20. As an Employee, I want the "+" chip to look active and carry the owe-reply count while Owe reply is on, together with the existing scan status line, so that I can see a hidden filter is applied.
21. As an Employee, I want the Creator's Chat folders (the OF lists pinned to chats) as chips with a folder icon, where clicking filters and clicking again clears, so that I can work one list at a time.
22. As an Employee, I want a "✎ Lists" chip at the end of the folder row that opens the folder picker, so that I can pin and unpin Chat folders.
23. As an Employee, I want an active folder that gets unpinned to drop me back to All, so that I never sit on a phantom filter.
24. As an Employee in All Models, I want the folder chips and the "All inboxes" selector hidden, so that I am not offered per-Creator filters over many Creators.
25. As an Employee, I want each row to show a 48px avatar, the bold name with "@handle", and the preview with its time underneath, so that rows read like Infloww's.
26. As an Employee, I want a green dot on the avatar when the Fan is online, so that I can spot live Fans.
27. As an Employee, I want a spending Fan's Total spend shown in orange in place of the avatar, so that I can see value at a glance.
28. As an Employee, I want a `$0` pill on Fans who have never paid, so that non-buyers are explicit rather than blank.
29. As an Employee, I want an expired Fan's avatar to become a red ✕ circle, with any Total spend still shown in the pill, so that lapsed subscribers stand out without hiding what they paid.
30. As an Employee, I want a "New" badge on Fans who subscribed within 7 days, so that I can welcome them.
31. As an Employee, I want a 🔥 badge on Fans who bought a PPV within 7 days, so that I can follow up while they are warm.
32. As an Employee, I want a ❄️ badge on chats with no message for 72 hours, so that I can re-engage cold Fans.
33. As an Employee, I want an "Off" badge on Fans whose auto-renew is off, so that I can try to keep them before they lapse.
34. As an Employee, I want unread chats to show a 9px dot and a bold preview, so that unread rows stand out the way Infloww's do.
35. As an Employee, I want muted chats to show a mute icon in the status slot, so that muting is visible without dimming the row.
36. As an Employee, I want the owe-reply dot on rows only when the Legacy flag is on or Owe reply is the active filter, so that the extra stays inside its overflow.
37. As an Employee, I want a row's "last buy" and "renews/ends" facts in its tooltip, so that the row stays two lines without losing that information.
38. As an Employee, I want right-clicking a row to offer "Open in a new window", which opens a Pop-out window at that Fan's Deep link, so that I can work Fans side by side as Infloww's Multi-Window allows.
39. As an Employee, I want hovering or tapping a row to keep warming its messages and vault exactly as today, so that the redesign costs no speed.
40. As an Employee, I want the selected row highlighted, so that I can see which Thread is open.
41. As an Employee, I want "No conversations found" when a filter matches nothing, so that an empty list reads as empty rather than broken.
42. As an Employee, I want six skeleton rows at the real row size during a cold load, so that loading reads as loading.
43. As an Employee, I want "Load more conversations" when more chats exist, so that the tail of a long inbox stays reachable.
44. As an Employee, I want load errors explained as they are today, so that failures stay diagnosable.
45. As an Employee, I want to turn on Focus mode from the gear while on All with Newest first, so that the list stops reordering under my cursor.
46. As an Employee in Focus mode, I want new messages to leave the order alone and show a "N new messages" banner instead, so that I finish what I am on before re-sorting.
47. As an Employee in Focus mode, I want clicking the banner to refresh the list and clear the banner, so that I can catch up in one click.
48. As an Employee, I want Focus mode to be unavailable on any chip other than All or any sort other than Newest first, with a hint saying why, so that I am never misled about what it does.
49. As an owner, I want to open Split Inbox settings from the selector and choose from 1 to 9 groups, so that I can divide a Creator's Fans among Employees.
50. As an owner, I want to move a Fan to a different group, so that I can rebalance the split by hand.
51. As an Employee, I want every Fan to belong to exactly one group, and a new split to spread the Fans at once, so that no Fan falls through the cracks.
52. As an Employee, I want the split saved per Creator on the relay, so that every Employee on every device sees the same groups.
53. As a chatter-only Employee, I want to filter by group without being offered the group-count or reassign controls, so that only owners change the split.
54. As an owner, I want groups to grant no permissions and bind to no Employee, so that the split matches Infloww and needs no role changes.
55. As an owner, I want a Fan in a group that disappears when I lower the count to fall back to a remaining group, so that lowering the count never hides anyone.
56. As an Employee below 1024px, I want the Fan List as the single pane, with the same header, chips, badges and spend display, so that I can work from my phone.
57. As an Employee on a phone (below 768px), I want chips and header buttons to keep tap targets of at least 36px, so that the Clone's small sizes stay tappable.
58. As an Employee using Group chat, I want its picker list to be the same Fan List, so that both views behave alike.
59. As an Employee, I want the tab title to keep showing "(N) Inbox · Inflowwww", so that background tabs still tell me there is work waiting.
60. As the implementer, I want the left pane in `messages-pro-desktop.png` and in `messages-pro-phone-list.png` compared with `clone-messages-pro.png` through the Visual loop, so that parity is checked by eye as well as by tests.
61. As an Employee filtering to one Split Inbox group, I want the list to keep loading until that group has rows or the scan cap is reached, and "Load more conversations" to stay while more chats exist, so that an empty first page is not mistaken for an empty group.
62. As an owner, I want a failed Split Inbox save to keep the dialog open with the error, so that I know the split did not change.
63. As an Employee arriving by Deep link, I want the selected row to keep `aria-current="true"` and to be scrolled into view, so that Phase 0's arrival behaviour survives the rebuild.

## Implementation Decisions

- **Owns.**
  - App: `FanList`, `FanListHeader`, `FanListFilters`, `FanRow`, `SplitInbox` and `OpenInNewWindowMenu` (all new, under `components/chat`), and a `useSplitInbox` hook (new). `ChatList` is removed once its behaviour has moved.
  - App, modified: `useFanActivity`, `useChatSortMode`, Phase 0's `MessagesPro` component (which holds the Fan List once Phase 0 lands; the index page only renders it, `docs/spec/phase-00-pop-out-window.md:102-103`) and the Group chat page (`app/app/group/page.tsx:27`). Each swaps its import from `ChatList` to `FanList`.
  - Relay: `split_inbox_api` (new route module), the `AccountAiConfig` model, one Alembic migration, router registration in the server, and `settings_transfer_api`'s column list.
  - Rung 2: the plan names the four-way split, and ADR-0004 names the relay store.

- **Interfaces.**
  - `FanList` takes the same props `ChatList` took: `selected`, `onSelect` and `setTabTitle`. It exports `FanListSelection` (`{accountId, fanId, chat}`), which is the former `ChatListSelection` renamed. It still owns data, selection, pagination, prefetch, Focus mode and the Split Inbox filter.
  - `FanList` and `FanRow` keep Phase 0's selected-row contract, which Phase 0 adds to `ChatList` and asks Phase 2 to keep (`docs/spec/phase-00-pop-out-window.md:121`, `:139`, the "Selected Fan row" and `ChatList` bullets): the selected row carries `aria-current="true"`, and when a selection's row first renders it is scrolled into view (nearest edge) once for that selection.
  - `FanListHeader` renders the title, the search toggle (with its input row) and the New menu.
  - `FanListFilters` renders the filter row (selector, gear menu, sort control, refresh), the chip row with the Extras overflow, and the folder row. It is stateless, so its parent passes in the active filter, counts, folders, sort, Split Inbox state and gear settings, together with their callbacks.
  - `FanRow` renders one row from raw facts: the chat item, profile, Total spend in cents, subscription status and expiry, last PPV purchase time, optional subscribe time, last purchase time, the selected flag, owe-dot visibility, the All Models account colour, `now`, and callbacks for select and prefetch. It wraps itself in `OpenInNewWindowMenu`.
  - `OpenInNewWindowMenu({ href, children })` wraps its child and opens a one-item "Open in a new window" menu on `contextmenu`, which calls `window.open(href)`. The props are the ones Phase 1 names for the same module (`docs/spec/phase-01-window-chrome-tabs.md:140`), so Phase 1 reuses it for Creator tabs and Fan tabs instead of building a second. Its module exports the pure `rowBadges(facts, now)`, which returns the subset of New, 🔥, ❄️, ❌ and Off in that order.
  - `SplitInbox` is a dialog that takes `accountId`, `open`, `onClose` and the loaded Fans (`{id, name}`). Its module exports the pure `groupOf(fanId, config)`.
  - `useSplitInbox(accountId)` returns the stored config and a save mutation, following the `useNudgeConfig` pattern (rung 3).
  - `useFanActivity` gains a third map, `lastPpvPurchase` (`"acct:fan"` → ISO time), next to `lastPurchase` and `recentSpend`. The change is additive, so `FanDrawer` and its test mock are unaffected.
  - `useChatSortMode`'s default changes from `spend-unread` to `recent`, and its setter stores every choice. Today the setter removes the key when `spend-unread` is chosen (`app/hooks/useChatSortMode.ts:55`), so under the new default that choice would read back as `recent` on the next change event or reload.
  ASSUMPTION: `ChatListSelection` is renamed to `FanListSelection` with no alias, and Phase 2 updates every importer, which after Phase 0 are `MessagesPro` and the Group chat page. This is overturned if an importer outside this tree needs the old name.

- **Schema.**
  - `account_ai_config.split_inbox_json`: TEXT, nullable. It holds `{"group_count": 1..9, "assignments": {"<fanId>": 1..group_count}}`, and NULL means not split.
  - `assignments` stores only explicit moves. Every other Fan's group is computed (see Split Inbox below).
  - The migration (`0065_split_inbox`, on top of today's head `0064_user_llm_keys`) is additive, nullable and inspector-guarded (rung 3: the `0030_autoreply` migration and others). It is written into this tree only and never run against a real database.
  - The relay never runs `alembic upgrade`. An existing database gains the column through `init_db()`'s additive catch-up, which adds missing nullable columns and silently skips a non-nullable one without a default (`service/db/engine.py:163-194`). The column is therefore nullable with no server default, and the relay test proves the catch-up adds it (Testing Decisions).
  - Rung 2: ADR-0004 and its house precedent `nudge_config_json` (`service/db/models.py:1514`).

- **Contracts.**
  - `GET /admin/split-inbox?account_id=` returns `{account_id, config}`. When unset, `config` is `{group_count: 1, assignments: {}}`.
  - `PUT /admin/split-inbox` takes `{account_id, config}` and returns `{account_id, config}` as stored.
  - Validation: `group_count` must be an integer from 1 to 9, and `assignments` must be an object, otherwise the route returns 422. Keys are coerced to strings, and entries whose group is not an integer within `1..group_count` are dropped. Dropping follows the coerce-and-drop style of `_validate_config` in `service/nudge_config_api.py` (rung 3).
  - Both routes call `assert_account_owned`. The PUT first calls `assert_owner()` (`service/chatters.py:869`), so a chatter session gets 403 and an anonymous one 401, as the owner-only routes from `service/chatters.py:925` onward do. The GET stays open to chatters, who filter by group. Rung 2: the plan's "admin/owner by default" (`docs/plans/messages-pro-parity.md:110`); rung 3 for the helper. `assert_account_owned` alone would not do, because it admits chatter principals (`service/auth.py:298-300`) and the chatter middleware lets unlisted `/admin/` paths through (`service/chatters.py:701-706`).
  - The PUT upserts the row the same way `put_nudge_config` does (`service/nudge_config_api.py:110`, `:129`; rung 3).
  - The brain upsert (`PUT /admin/account-config`) leaves the column alone, because it never names it. This is the same as `nudge_config_json` (`service/account_config_api.py:661`).
  - `settings_transfer_api` adds `split_inbox_json` to its config column list, because the drift guard at `service/tests/test_settings_transfer.py:231` requires every data column (rung 1). On clone it sets the column to null, as it already does for `day_log_json`, because Fan ids belong to one Creator (rung 3: `_sanitize_config_clone`). On restore to the same Creator it is written back unchanged.
  ASSUMPTION: a split is dropped when settings are cloned to another Creator and kept on restore. This is overturned if the human wants splits copied between Creators.
  - Consumed unchanged:
    - `/api/of/v2/chats` through `useChatList`.
    - Chat folders: `GET /api/of/v2/chats/folders` (`service/server.py:4489`) through `useChatFolders` / `useAllChatFolders` (`app/hooks/useChatFolders.ts`), and `PATCH /api/of/v2/lists/{id}/pin-chat`. The route exists, so the plan's "if none exists, add a read-only relay route" branch does not fire (rung 1).
    - `/admin/fans/{aid}/spend-batch` (`service/fans.py:344`).
    - `/api/of/v2/payouts/transactions` (`service/server.py:5889`, an OF passthrough).
    - `POST /api/of/v2/chats/{id}/mark-as-read`.

- **Geometry and colour.**
  - Every measured value in the Gap table is applied. Phase 2 keeps those values in one exported geometry constant in the `FanList` module, built from Tailwind class fragments, rather than as literals scattered through the JSX.
  ASSUMPTION: Phase 6 later moves that constant into the Messages Pro token module that ADR-0001 requires. This is overturned if Phase 6 lands first, in which case Phase 2 reads the token module directly.
  - Colours come from `app/app/globals.css` tokens: chip active → `accent`; chip count badge → `err`; owe count → `warn`; unread dot and New → `info`; orange spend figure → `warn`; `$0` pill → `fg-dim`; Off → `accent` (the Clone's purple); expired avatar → `err`; online dot → `ok`; selected row → `bg-elev-1`.
  ASSUMPTION: this token mapping is a choice by nearest hue and the `info` comment at `globals.css:38`. It is overturned by Phase 6's token pass.
  - Pane width is not set here; Phase 6 owns it (Gap table row 1, rung 2).
  - Below `md` (768px), chips and header buttons keep the current ≥36px tap targets (`CL:1244`, `CL:733`, `CL:743`). From 768px to 1023px the Fan List is still the single pane (`docs/routes.md:42`) but uses the Clone's sizes, as `ChatList`'s header buttons do today.
  ASSUMPTION: the house phone tap-size rule beats the Clone's sizes below `md`, and its `md` breakpoint (rung 3) is kept rather than widened to the 1024px single-pane breakpoint. This is overturned if the phone Visual loop shows the Clone sizes are usable, or a tablet check shows 26px header buttons are not.
  - Menus (New, selector, gear, sort, Extras overflow, row context menu) use the Clone's `.pop` / `.prow` / `.phead` / `.pdiv` geometry (mh:361-371). They follow the outside-pointerdown and Escape dismissal that the current settings menu already uses (rung 3), factored once and shared by the Fan List modules.

- **Header.**
  - The title is the Creator's nickname; in All Models it reads "All Models".
  - The search icon toggles an input row under the header with focus in the input. Escape or clearing it closes the row, and the existing search query semantics are unchanged.
  ASSUMPTION: search stays as an icon plus an input row, because §3.3's left-pane list omits search and the Clone's icon only opens a `prompt` (mj:3187). This is overturned if Infloww has a permanent search field.
  - The New menu opens the existing `MassMessageComposer` in `standard` mode for "Mass message" and in `online` mode for "Message online fans" (`app/components/compose/MassMessageComposer.tsx:51`; rung 3: `SmartMessagesPage` does the same). "Post" navigates to `/of-manager/new-post` (`app/lib/nav.ts:69`).
  - In a single-Creator scope the composer opens with that Creator passed as `forcedAccountId`, which only seeds its account state (`MassMessageComposer.tsx:95`). The account picker, the all-models switch and the schedule field stay, because they hide only in return-payload mode (`composeMode`, `:78`, `:635`). In All Models it opens unseeded, as `SmartMessagesPage` opens it (`app/components/growth/SmartMessagesPage.tsx:70`).
  - The menu is built from an ordered item list, with a divider after the three Infloww items for extras.
  ASSUMPTION: "Post" goes to the OF Manager New post route, which is a stub today. This is overturned when a post composer exists.
  - Broadcast: ADR-0003 puts broadcast in the Fan List's "New" menu, and §3.3 tags the New menu's broadcast item as ours (`docs/infloww-screens.md:179`; the Clone's item is `messages.js:1630`). The composer's "Broadcast from ALL models" switch (`MassMessageComposer.tsx:642`) is a different control and does not meet that placement. Phase 2 adds no Broadcast item. Phase 7 appends it after the divider, because Phase 7 decides its gate and target.
  ASSUMPTION: the Broadcast item belongs to Phase 7, whose spec names this menu as its host and puts the item behind the Legacy flag, linking to `/automations` (`docs/spec/phase-07-ours-kept-marked.md:15`, `:206`). This is overturned if Phase 7 does not add it, in which case this menu needs the item to satisfy ADR-0003.

- **Filters, sort and gear.**
  - The built-in chips map to server filters exactly as today. "↩ Owe reply" keeps its client-side bounded scan and its status lines, but it is chosen from the "+" Extras overflow at the end of the chip row (rung 2: plan, ADR-0003).
  - The Extras overflow and the extra sort orders carry the tooltip "Inflowwww extra" (rung 2: ADR-0003).
  - Badge counts: Unread shows the unread count over the cached All set. Pinned and Priority show the count only while active, as today. All shows no badge.
  ASSUMPTION: the All chip loses its attention-count badge to match the Clone (mh:662). The count stays in the tab title. This is overturned if Employees miss it on the chip.
  - The sort control lists only "Newest first" (`recent`). The three extra orders are entries in the Fan List Extras overflow, after "↩ Owe reply". Choosing one sets the sort, and the sort control then shows that order's name (rung 2: plan:30 puts non-automation extras behind a "+" overflow, and ADR-0003 agrees). Phase 7 audits them there (`phase-07-ours-kept-marked.md`, "Extra sort orders").
  ASSUMPTION: the hook's default becomes "Newest first" for anyone with nothing stored, and stored choices are untouched. An Employee who explicitly chose "Spend + unread on top" before this Phase has nothing stored, because the old setter removed the key (`useChatSortMode.ts:55`), so that Employee moves to Newest first; that history cannot be recovered. This changes the default for Group chat too. It is overturned if the human wants our spend ranking to stay the default.
  - The gear keeps Mark all as read, Keep fan info panel open, both blur options and Compact media previews, and gains Focus mode.

- **Rows.**
  - Name priority, the preview text (with "you:" and the 💰 / 🔒 / 📎 markers), the hover, focus and pointer-down prefetch, `data-chat-row` and the All Models colour marker are all kept as they are (rung 5).
  - `rowBadges` rules:
    - New: subscribe time within 7×24h.
    - 🔥: last PPV purchase within 7×24h.
    - ❄️: the chat's last message is older than 72h.
    - ❌: `interpretSubStatus(...).expired` (`app/lib/utils.ts:91`).
    - Off: `interpretSubStatus` reports "Won't renew" and the subscription has not expired. ❌ and Off never appear together.
    - The 7-day windows are inclusive: a fact exactly 7×24h old still lights New or 🔥 (the plan's "≤7d"). ❄️ lights only when the last message is more than 72h old. A missing, unparseable or future timestamp lights nothing.
  ASSUMPTION (❄️): "not messaged in 72h" means the last message from either side is older than 72h, and a chat with no message shows no ❄️. This is overturned if Infloww means the Creator has not sent anything for 72h.
  ASSUMPTION (🔥): a PPV purchase is a transactions-feed row whose `description` starts with "Payment for message from " or "Message from ". These are the prefixes `service/transaction_ingest.py:180-181` classifies as `ppv_message` from the same OF ledger, which `useFanActivity` already fetches as one page of 50 per account (`app/hooks/useLastPurchases.ts:50`). A PPV older than an account's 50 most recent transactions is therefore missed. Tips never count, because their prefixes differ (`:176-179`). Rows whose OF `status` is "undo" or "pending_return" (a chargeback or a pending refund, `service/transaction_ingest.py:190-195`) do not count. This is overturned if the feed is paged deeper or the relay exposes a per-Fan PPV time.
  ASSUMPTION (New): no field the Fan List fetches carries a subscribe date. `OFChatItem` (`app/lib/relay.ts:483`) lacks one, spend-batch returns only spend, status and expiry (`service/fans.py:344`), and enrichment stores only name and avatar. So New is built and tested but never lights in production. This is overturned by a ticket that adds `Fan.subscribed_at` (`service/db/models.py:410`) to spend-batch under the proven-endpoint exception.
  - Avatar slot precedence:
    1. Expired: a red circle with ✕ (`[PAL]` "red circle avatar (❌)", Clone `.av.coral` / `.xmark`).
    2. Total spend > 0: the orange figure in the slot at 12px / 700 (Clone `.av.purple` text size), as whole dollars, shortened to "k" above $9,999.
    3. Otherwise: the photo or initials.
  - The `.spend` pill shows whenever the slot is not already showing the figure: `$0` for non-spenders, and the total for expired spenders. Total spend keeps today's rule, `max(spend-batch lifetime, recent ledger sum)`.
  - `$0` needs a known zero: spend-batch has loaded and returned an entry for the Fan, and the ledger sum is zero. While spend-batch is loading, or when it has no entry for the Fan (it returns only Fans in our database, `service/fans.py:380`), the slot shows the photo and no pill.
  ASSUMPTION: an unknown spend shows no pill rather than `$0`, because a false `$0` misstates a Fan we have not ingested. This is overturned if the Visual loop or Employees find the missing pill confusing.
  ASSUMPTION: "orange total-spend replacing the avatar" (C[H262067]) applies to every spender, with no setting, and the `$0` pill (`[PAL]`) covers the rest. This is overturned if Infloww makes the replacement an option.
  - The badge strip sits after the name and handle in plan order: "New" as a `.fx-new` pill, 🔥 and ❄️ as 13px glyphs, and "Off" in `.off-label` type. ❌ is the avatar treatment.
  ASSUMPTION: the badges sit in one strip on the name line, because the Clone has `.off-label` and `.xred` styles but no markup for them. This is overturned by a real Infloww capture.
  - The old third line (spend, "last buy …", "renews/ends …") moves into the row's `title` tooltip.
  ASSUMPTION: the third line is dropped from the row because no source tags it as an Infloww element or as an extra, and Fan insights still shows those facts. This is overturned if Phase 7 lists it as an extra.
  - The owe-reply dot shows only when `useLegacyAutomations()` is true or Owe reply is the active filter.
  ASSUMPTION: the row's owe dot is part of the Owe reply extra, so ADR-0003's "no extra outside an overflow" hides it otherwise. This is overturned if the human counts it as plain row status.
  - Right-click (`contextmenu`) on a row opens `OpenInNewWindowMenu` with the href `/messages-pro/<accountId>/<fanId>?window=1`, Phase 0's Deep link in the windowed layout.
  ASSUMPTION: the row's right-click (§3.3, C[H545992]) and the shared menu module are built here, because Phase 2 lands before Phase 1 and Phase 1's spec hands the row's right-click to this Phase and reuses the menu for its tabs (`docs/spec/phase-01-window-chrome-tabs.md:106`, story 41). This is overturned if Phase 1 keeps the row menu, in which case `FanRow` drops its own and Phase 1 wraps it.

- **States.** The empty, skeleton and load-more states take the Clone's text and geometry (Gap rows 26-28). The cap, autofill and owe-reply scan logic are unchanged.
  ASSUMPTION: the empty state's own Refresh button is dropped because the Clone shows a plain line (mj:481) and refresh lives in the sort line. This is overturned if the Visual loop shows Employees stuck on an empty list.

- **Focus mode.**
  - It is a gear checkbox, enabled only while the All chip is active, with no folder and no Owe reply, and the sort is Newest first. The Split Inbox group does not matter.
  - Turning it on freezes the order and membership of the displayed rows, while row contents keep updating in place.
  - It freezes only the Fan List's projection. Writes to the shared `["chats"]` cache are never suppressed or delayed, whether they come from realtime (`setQueryData`, `app/hooks/useInboxRealtime.ts:441`) or from the head poll (`app/hooks/useChatList.ts:480`), so other readers of that cache are unaffected.
  - The banner reads "{N} new messages", where N is the number of chats in the live set whose newest message came from the Fan after the freeze. Clicking it refreshes the list (`refresh()`, which bypasses the relay cache as the refresh icon does), unfreezes to the live order and clears N.
  - Leaving All or Newest first suspends Focus mode, and the checkbox shows "Only in All · Newest first".
  - Changing the Creator scope or the Split Inbox group takes a new snapshot and resets N. Because N counts chats, a duplicate or replayed event for a chat already counted does not raise it, and a chat that first appears through the head poll counts the same as one pushed by realtime. If the banner's refresh fails, the frozen order and the banner stay, and the load error shows as it does today.
  ASSUMPTION: the gear placement, the banner wording, counting chats rather than messages, and in-place content updates are all choices, because C[H262067] gives only the feature. This is overturned by a real Infloww capture.
  ASSUMPTION: Focus mode and the selected Split Inbox group are session state, not persisted (rung 5). This is overturned if Employees ask to keep them across reloads.

- **Split Inbox.**
  - The selector lists "All inboxes", then "Inbox 1" to "Inbox N" when the count is above 1, and then, for owners only, "Split Inbox settings".
  - The dialog (Radix Dialog, already a dependency, as in `AppShell`) has two sections under Infloww's screen names. "Choose the number of groups" is a 1-9 select. "Reassign fans to different groups" lists the Fans loaded in the Fan List, each with a group select. A single Save sends one PUT.
  - Filtering is client-side over the loaded rows. The group filter applies on top of (AND) the active chip or folder and the search. Chip counts stay as defined under Filters and are not narrowed by the group.
  - With a group selected, the list runs the same bounded fill that Owe reply runs, with its constants (`OWE_REPLY_TARGET` and `OWE_REPLY_SCAN_CAP`, `ChatList.tsx:57-58`, loop at `:597-612`): it pages until enough rows match, the scan cap is reached, or no pages remain. "No conversations found" shows when nothing matches, and "Load more conversations" stays under it while `hasMore` is true.
  - When a saved split lowers the count below the selected group, the selection returns to "All inboxes".
  ASSUMPTION: the group fill reuses Owe reply's target and cap (rung 3), because a hash split leaves about 1/N of loaded rows in each group. This is overturned if groups routinely come up empty at the cap.
  - `groupOf` returns the Fan's explicit assignment if it has one and it is within range. Otherwise it returns a stable string hash of the Fan id modulo N, plus 1, so a new split divides Fans immediately and identically on every device.
  - Concurrent saves are last-write-wins.
  - A failed save keeps the dialog open with the relay's error and applies nothing. Other Employees and devices see a saved split on their next fetch of the config, which follows `useNudgeConfig`'s 60-second `staleTime` and invalidation on save (`app/hooks/useNudgeConfig.ts:77`, `:91`; rung 3). There is no push.
  ASSUMPTION: the selector is Infloww's Split Inbox filter, and its settings entry is where the group count is chosen (§3.3 marks both locations G). This is overturned by a capture showing otherwise.
  ASSUMPTION: groups are labelled "Inbox 1" to "Inbox N", because no source gives a label. This is overturned by an Infloww label.
  ASSUMPTION: Fans without an assignment are spread by hash, and changing N re-spreads them and drops assignments above the new N. This is overturned if Infloww starts every Fan in group 1.
  ASSUMPTION: the reassign screen lists only the Fans already loaded and has no search, because that is the smallest version (rung 5). This is overturned if owners need to move Fans who are not loaded yet.
  ASSUMPTION: "admin/owner by default" means a User principal, which is what `assert_owner()` checks. Chatter-only sessions (`useIsChatterOnly`, `app/components/shell/useIsChatterOnly.ts:8`) get the filter but not the settings entry, and the relay rejects their PUT (Contracts). This is overturned if the human wants some chatters to edit the split, which needs the per-role permission model we do not have.
  ASSUMPTION: the selector and the folder chips are hidden in All Models, because both are per Creator. This is overturned if All Models should show a merged group filter.

- **Responsive.** Below 1024px the Fan List stays the single pane described in `docs/routes.md` (rung 2). The page's list/thread swap is unchanged.

## Testing Decisions

Tests check behaviour that is visible from outside each module and never assert internal state.

- **Seam choice.** The highest seam is `FanList`, rendered through `renderWithProviders` (`app/test-utils.tsx`) with the relay boundary mocked: `@/lib/relay`'s `relay.get` and `relay.put` answer by URL path. Also mocked are `@/contexts/ScopeContext`, `@/hooks/useAccounts`, `@/lib/perfLog`, `@/hooks/useDeferredMount` (ready at once), `useLegacyAutomations` and `useIsChatterOnly`. This mirrors `app/hooks/useChatList.test.tsx:23-50`.
- **Plan-named files.** The plan names `FanRow`, `FanListFilters` and `SplitInbox` as their own test files, so those three are tested at their props, which is their public interface. No other seam is added.
- **`components/chat/FanList.test.tsx`** (seam: `FanList`):
  - The header shows the Creator name, or "All Models" in all scope.
  - The New menu lists "Mass message", "Message online fans" and "Post" in order. "Mass message" renders the composer in standard mode with the Creator in scope selected, "Message online fans" renders it in online mode, and "Post" navigates to `/of-manager/new-post`.
  - Choosing a group in "All inboxes" leaves only that group's rows. A group with no match on the first page keeps loading pages, and keeps "Load more conversations" while `hasMore` is true.
  - With a folder chip active, unpinning that folder through the folder picker returns the chips to All.
  - Choosing "Spend + unread on top" and remounting keeps it; with nothing stored the sort reads "Newest first".
  - 🔥 end to end: the mocked `/api/of/v2/payouts/transactions` returns a recent "Payment for message from" row for Fan A, a "Tip from" row for Fan B and a PPV row with `status: "undo"` for Fan C. Only Fan A's row shows 🔥.
  - The selected row carries `aria-current="true"`.
  - "↩ Owe reply" is not among the chips and is reachable from "+".
  - An empty response shows "No conversations found".
  - Focus mode banner: with Focus mode on, a new fan-sent message delivered the way production delivers it leaves the row order unchanged and shows "1 new messages". The test mounts `useInboxRealtime` beside `FanList` and injects the realtime event through the `@/lib/events` mock, as `app/hooks/useChatList.test.tsx:53-56` does, so the row moves through `setQueryData` (`useInboxRealtime.ts:441`), not a refetch. A second case lands a chat that was not in the frozen rows through the head poll. Clicking the banner reorders the rows and removes the banner. Focus mode is disabled under Unread.
- **`components/chat/FanRow.test.tsx`** (seam: `FanRow` props), a badge matrix with a fixed `now`:
  - Each of New, 🔥, ❄️, Off alone, and the 7-day and 72-hour boundaries on either side (exactly 7×24h lights; exactly 72h does not). A missing or future timestamp lights nothing.
  - ❌ with Off never both.
  - A spender shows the orange figure and no avatar image; a non-spender shows the avatar and `$0`; an expired spender shows the ✕ avatar and a `$N` pill; a Fan with unknown spend shows the avatar and no pill.
  - The online dot.
  - The owe dot hidden unless the flag is on or Owe reply is active.
  - Right-click shows "Open in a new window" and calls `window.open` with the Deep link plus `?window=1`.
- **`components/chat/FanListFilters.test.tsx`** (seam: props):
  - Chips render All, Unread, Pinned, Priority, "+" in order, with no emoji.
  - Clicking a chip reports the filter; the Unread corner badge shows its count; All has no badge.
  - The "+" overflow holds "↩ Owe reply" with its count and the "Inflowwww extra" tooltip.
  - Folder chips render pinned folders, followed by "✎ Lists", and re-clicking the active folder clears it.
  - The sort control reads "Newest first" by default and lists no extra order. The "+" overflow lists the three extra orders, and choosing one reports the choice and shows its name on the sort control.
  - The Focus mode checkbox is disabled outside All with Newest first.
  - The settings entry is absent for chatter-only sessions.
- **`components/chat/SplitInbox.test.tsx`** (seam: `SplitInbox` props, relay mocked; `groupOf` as a pure export):
  - The count select offers exactly 1 to 9.
  - Saving PUTs `{group_count, assignments}`.
  - Reassigning a Fan changes only that Fan's entry.
  - Lowering N drops out-of-range assignments.
  - `groupOf` is stable for the same id, always in `1..N`, honours explicit assignments, and hashes a 19-digit string id without losing precision.
  - A failed PUT keeps the dialog open with the error.
- **Existing tests that must stay green:** `components/chat/fanDrawerEditFreshness.test.tsx` (it mocks `useFanActivity` with two maps, which still type-checks because the third map is additive), `hooks/useChatList.test.tsx`, and Phase 0's `app/messages-pro/windowed.test.tsx`, whose Deep link case asserts the selected row's `aria-current` and scroll.
- **Relay seam: `service/tests/test_split_inbox_api.py`.** It is plain-assert and drives the routes over HTTP through `_harness.make_client()` (`service/tests/_harness.py:88`) against the temp DB, so router registration and the session middleware are exercised. The precedent for cookie-authenticated cases is `service/tests/test_chatter_auth.py:185-261`. Cases:
  - GET on an unset account returns the defaults.
  - A PUT/GET round trip as an owner.
  - A chatter cookie for the account gets 200 on GET and 403 on PUT; no cookie gets 401.
  - 422 for `group_count` values 0, 10 and "x", and for `assignments` that is not an object.
  - Out-of-range entries are dropped.
  - The additive catch-up: after bootstrap, drop `split_inbox_json` from `account_ai_config`, re-run `init_db()`, and assert the column is back (precedent: `service/tests/test_automation_queue_indexes.py:31-36`).
  - The brain PUT preserves `split_inbox_json`. This case is added to `test_account_config_api.py` beside `case_upsert_preserves_nudge_config`.
  - `test_settings_transfer.py` stays green with the new column exported, and gains two assertions: a clone writes `split_inbox_json` as null, and a restore to the same Creator writes it back unchanged.
- **Prior art:** `app/hooks/useChatList.test.tsx`, `app/components/chat/MessageList.test.tsx`, `app/components/chat/fanDrawerEditFreshness.test.tsx`, `service/tests/test_account_config_api.py`, `service/tests/test_chatter_auth.py`.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"

# The split replaced ChatList
test ! -e app/components/chat/ChatList.tsx
if grep -rq 'components/chat/ChatList"' app/app app/components app/hooks; then echo "ChatList still imported" >&2; exit 1; fi
for f in FanList FanListHeader FanListFilters FanRow OpenInNewWindowMenu; do test -s "app/components/chat/$f.tsx"; done

# Phase tests (core)
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run \
  components/chat/FanRow.test.tsx components/chat/FanListFilters.test.tsx \
  components/chat/FanList.test.tsx \
  components/chat/fanDrawerEditFreshness.test.tsx hooks/useChatList.test.tsx \
  app/messages-pro/windowed.test.tsx

# Split Inbox tickets. They land after Phase 3 and before Phase 6 (docs/spec/plan-review.md), so this block
# joins the run only once they have landed. The Phase is done when both blocks pass.
test -s app/components/chat/SplitInbox.tsx
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/SplitInbox.test.tsx
# Relay route (temp DB only; the migration is compiled, never run)
./venv/bin/python service/tests/test_split_inbox_api.py
./venv/bin/python service/tests/test_account_config_api.py
./venv/bin/python service/tests/test_settings_transfer.py
./venv/bin/python -m py_compile service/split_inbox_api.py service/db/migrations/versions/*_split_inbox.py

# Full suites (binding)
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run

# Visual loop (harness from Phase 0)
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-desktop.png
test -s docs/screenshots/messages-pro-phone-list.png
test -s docs/screenshots/clone-messages-pro.png
python3 -m json.tool docs/screenshots/messages-pro-report.json > /dev/null
# manual: Read messages-pro-desktop.png (left pane) and messages-pro-phone-list.png beside clone-messages-pro.png; write the visual diff for header, chips, badges and spend pill; fix and re-run up to three rounds; record what remains as VISUAL GAP: lines (row 1 pane width is expected until Phase 6).
# manual: record the messages-pro-report.json summary in the Phase result and commit the final PNGs with the code.
```

## Depends on

- **Phase 0.**
  - `scripts/ui-shots.sh` and its mock data: five Fans and the shot names, which the Acceptance block runs.
  - `MessagesPro`, the component that holds the Fan List after Phase 0, and its selected-row contract (`aria-current="true"`, scroll into view), which `windowed.test.tsx` asserts.
  - The windowed layout (`?window=1`) and the Deep link route, which the row's "Open in a new window" opens.
  ASSUMPTION: for the left-pane shot to show badges and the spend display, the five mock Fans need to vary in spend, subscription status and recent PPV. If Phase 0's seed does not vary them, the Phase 2 ticket extends that seed and records the change. This is overturned by Phase 0's spec.
  - Phase 0 lands first, because its harness is in this Phase's Acceptance. Phase 2 therefore carries Phase 0's selected-row contract from `ChatList` into `FanList` and `FanRow`, and swaps `ChatList` for `FanList` inside `MessagesPro`.
- **Phase 1:** none for this Phase. The dependency runs the other way: Phase 1 extends `FanList` with an `actions` slot and `onlineOnly`, reuses `OpenInNewWindowMenu` for its tabs, and reuses `rowBadges` for the Fan tab signal (`docs/spec/phase-01-window-chrome-tabs.md:142`, `:198`, `:295`). Phase 2 lands before Phase 1.
- **Phase 6:** none for landing. Phase 6 later absorbs this Phase's geometry constant and sets the pane width.
- **Phase 7:** none for landing. Phase 7 appends the Broadcast item to this Phase's New menu (Header).
- **Landing split.** The Phase lands as a core and a set of Split Inbox tickets. The core lands in Wave 1. The Split Inbox tickets are the relay route, the migration, `split_inbox_json`, the `AccountAiConfig` and `settings_transfer_api` changes, the `SplitInbox` dialog, `useSplitInbox` and the selector's group entries. They land after Phase 3 and before Phase 6, because Phase 6 lifts `SplitInbox`'s Geometry (FL50) and Phase 7 grades the Split Inbox Region. Until they land, the selector offers only "All inboxes" (story 10), with no settings entry.
  ASSUMPTION: Split Inbox lands as late as Phases 6 and 7 allow, because it is the only ticket in the set that changes the relay's database: once a deploy runs it, `init_db()` adds `account_ai_config.split_inbox_json` to the production database at relay start (`service/db/engine.py:163-194`), and no code path drops it (rung 4). This is overturned if the human wants Split Inbox with the rest of the Fan List, in which case it lands in Wave 1 with the core.

## Out of Scope

- **Fan List pane width (390px vs 320px):** the plan gives pane widths to Phase 6.
- **The Clone's "Online Fans" / "Notifications" buttons in the list pane:** Phase 1 builds them as the Fan List buttons, through the `actions` slot it adds to `FanList` (`phase-01-window-chrome-tabs.md:157-159`).
- **The Clone's gallery icon in the list header (mh:631):** §3.3's left-pane list omits it, and its only handler forwards to the Chat header's Gallery (mj:3207-3210), which Phase 3 owns.
- **"Unread tips" chip and the gear's "Show only" items:** tagged `[CL ?]`, or owned by Phase 1's Online Fans, and not in the plan.
- **Row "×" (`.cx`):** the Clone gives it no handler and no source names its action, so building it would fake a control.
- **The "Needs reply" sort label:** §3.3 tags it as probably ours. The order survives as "Spend + unread on top".
- **Messages Basic's "Oldest first" / "Unread with Tips":** §3.3 marks them as a different screen.
- **Binding Split Inbox groups to Employees, and per-role edit permissions:** ADR-0004 rules out binding, and we have no per-role permission model.
- **Server-side group filtering:** OF has no such filter, and client-side filtering over loaded rows is enough.
- **A `subscribed_at` field for New:** the plan limits badges to fields already fetched.
- **Persisting Focus mode or the chosen group:** YAGNI until asked.
- **Restyling the folder picker as a popover:** its behaviour already matches the Clone, and a modal is enough.
- **The Broadcast item in the New menu:** Phase 7 adds it (Header).
- **Paging Chat folders past the first 50 lists:** `useChatFolders` fetches `limit=50` once (`app/hooks/useChatFolders.ts:79`), and folders are consumed unchanged.
- **Hiding the mass-exclude system lists from folder chips (mj:3050):** this is not a parity element.
- **The Messages Pro token module and the `docs/messages-pro-parity.md` "Ours" entries:** Phases 6 and 7.

## Further Notes

The open questions below are already decided, and each is flagged inline above:

- Whether New can ever light. It cannot: the data is missing, and the rule ships dark (Rows).
- 🔥's 50-transaction horizon (Rows).
- ❄️'s meaning (Rows).
- Avatar-slot precedence and the spend format (Rows).
- Badge placement (Rows, Gap table).
- The owe dot as part of the extra (Rows).
- The broadcast and Post targets (Header).
- Selector placement and labels, the hash spread, and the group fill (Split Inbox). The role gate is now enforced on the relay (Contracts).
- Focus mode's placement, wording and count (Focus mode).
- The sort default (Filters).
- The token mapping and the geometry constant's handover to Phase 6 (Geometry).
- Splits on settings clone (Contracts).
- The Phase 0 handoffs, the row right-click and its menu module shared with Phase 1, and Broadcast handed to Phase 7 (Depends on, Rows, Header).
- Unknown spend shows no pill (Rows).

The rungs used: rung 1 for the Gap table values and the existing endpoints; rung 2 for the split, the store, the chips, the overflow and the badge rules; rung 3 for the hook and route patterns, the migration style and the dismissal pattern; rung 5 for session state, the loaded-Fans reassign list and keeping the folder picker. Everything at rung 3 or below carries an `ASSUMPTION:` line.

## Review

Reviewer: codex (`codex exec --sandbox read-only`, reasoning effort high), 2026-10-12. Two calls against the sparse review worktree: a blind call (B, no spec) and a draft call (D, this spec). Both exited 0, and their outputs were fresh and non-empty. The blind call's log shows no read of `docs/spec/`. The draft call read the Phase 0, 1 and 7 specs through `git show HEAD:`, because the worktree's object store holds committed specs. That was harmless for a call that is shown the draft anyway, but it means the worktree is blind by checkout, not by construction.

Blind call:

- B1 (JSON column vs a normalized `(creator, fan) → group` table; whole-payload replacement loses concurrent edits): **reject**. ADR-0004 fixes the store, and its overturn clause asks for a better *existing* store, which a new table is not. Edits are owner-only (now enforced, D1) and rare, so last-write-wins stays, as for `nudge_config_json`.
- B2 (hash default vs explicit assignment of every Fan is a product decision): **reject**. The hash spread is already flagged ASSUMPTION with an overturn clause, and the reviewer brought no Infloww evidence for another rule.
- B3 (local filtering cannot promise a complete group; scan cap at `ChatList.tsx:65`): **partial**. Client-side filtering stays, because OF has no group filter (Out of Scope). Accepted: a selected group runs Owe reply's bounded fill, and "Load more conversations" stays under the empty line while `hasMore` is true (Split Inbox; story 61; FanList test).
- B4 (extend spend-batch or fetch per-Fan details for badge data): **reject**. The plan limits badges to fields already fetched, and missing fields become `ASSUMPTION:` (`docs/plans/messages-pro-parity.md:120-121`). New stays dark and flagged.
- B5 (Focus mode should freeze the pane's presentation, not suppress shared cache writes): **accept**. Focus mode now states that it never suppresses or delays realtime or head-poll writes to `["chats"]` (Focus mode).
- B6 (assignment lifecycle: failed saves, cross-device propagation, resize, concurrency): **partial**. Accepted: a failed save keeps the dialog open and applies nothing, and other devices see a save on their next fetch with `useNudgeConfig`'s 60-second `staleTime` (Split Inbox; story 62; SplitInbox test). Resize and unseen Fans were already decided. Concurrency is rejected as in B1.
- B7 (the owner/admin edit right must be enforced on the server): **accept**. The PUT calls `assert_owner()`; chatters keep GET (Contracts; HTTP test).
- B8 (clone and same-Creator restore need explicit expectations): **accept**. Clone writes null, restore writes it back unchanged, with two new assertions in `test_settings_transfer.py`.
- B9 (badge meaning, boundaries and missing timestamps; ❄️ direction): **partial**. Accepted: the 7-day windows are inclusive, ❄️ lights above 72h, and missing, unparseable or future timestamps light nothing (Rows; FanRow test). ❄️'s direction stays an ASSUMPTION, because no source settles it.
- B10 (Off via `interpretSubStatus`; unknown spend shown as `$0`; 24h spend staleness): **partial**. Accepted: `$0` needs a known zero, and unknown spend shows no pill (Rows; FanRow test). Off keeps `interpretSubStatus`, because it is the only renewal field fetched (plan constraint). Staleness keeps today's rule, which this Phase does not change.
- B11 (filter composition, a selected group disappearing, counts, folders capped at 50): **partial**. Accepted: the group filter ANDs with the chip or folder and the search, chip counts are not narrowed by group, and lowering the count below the selected group resets to "All inboxes" (Split Inbox). Folder paging is rejected: the endpoint is consumed unchanged (Out of Scope).
- B12 (Focus mode transitions: scope or group change, duplicates, poll discoveries, refresh failure): **accept**. A scope or group change takes a new snapshot, N counts chats so duplicates do not raise it, poll arrivals count like realtime ones, and a failed refresh keeps the frozen order (Focus mode).
- B13 (behaviour behind the chrome: New-menu Creator context, keyboard, sort persistence): **partial**. The Creator context and sort persistence are accepted, as in D4 and D2. Keyboard dismissal was already specified (Escape, outside pointerdown).
- B14 (test seam: rendered list with real hooks and injected realtime events, plus HTTP and auth to the route): **accept**. See D5 and D6.
- B15 (list integration cases: a match beyond page one, two Creators sharing a fan id, large string ids): **partial**. Accepted: a group match beyond page one (FanList test) and a 19-digit string id in `groupOf` (SplitInbox test). The two-Creator case is rejected, because the selector is hidden in All Models and the config is per Creator.
- B16 (permission cases need real HTTP auth; direct coroutine tests missed a middleware-order bug, `service/server.py:310`): **accept**. Same as D6.
- B17 (test the data contract: a tip without a PPV, a refunded PPV): **accept**. 🔥 now excludes "undo" and "pending_return" rows, and a FanList-seam test drives 🔥 from the mocked transactions feed with PPV, tip and "undo" rows.
- B18 (measure the 390px pane in visual regression): **reject**. The plan gives pane widths to Phase 6 (`docs/plans/messages-pro-parity.md:190`), and Gap row 1 records the VISUAL GAP.
- F1 (the folder endpoint already exists): **accept**. This was already the decision (Contracts), so nothing is rewritten.
- F2 (groups need service work): **accept**. This was already the decision, under ADR-0004.
- F3 (badge fields not all fetched; a tip-only fixture lighting 🔥 is decisive): **accept**. The tip-only case is now a test (B17), and New stays dark (B4).
- F4 (the Clone is not product truth for Unread tips or Needs reply): **accept**. Both were already Out of Scope.
- F5 (a group match deeper than the loaded pages falsifies loaded-page filtering): **partial**. Same as B3.
- F6 (a realtime event or head poll moving rows falsifies a banner-only test): **accept**. Same as D5.
- F7 (two clients saving different reassignments falsifies whole-document persistence): **reject**. Same as B1.

Draft call:

- D1 (owner-only Split Inbox editing is unenforced; `assert_account_owned` admits chatters, `service/auth.py:298`, `service/chatters.py:701`): **accept**. Verified. The PUT now requires `assert_owner()` (`service/chatters.py:869`), and the HTTP test covers chatter GET 200, chatter PUT 403 and anonymous 401.
- D2 (the setter deletes the key on `spend-unread`, so a new `recent` default snaps that choice back, `useChatSortMode.ts:55`): **accept**. Verified. The setter now stores every choice, the historical ambiguity is flagged, story 14 is reworded, and a FanList remount test covers it.
- D3 (Broadcast left as a composer switch contradicts ADR-0003's New-menu placement): **partial**. Accepted that the composer switch does not meet ADR-0003. Phase 2 does not add the item itself, because Phase 7's spec places it in this menu, flag-gated, linking to `/automations` (`docs/spec/phase-07-ours-kept-marked.md:15`, `:206`). The New menu now has an extras divider for it (Header).
- D4 (New-menu actions, PPV ledger → 🔥, and folder unpin → All can pass with presentation only): **accept**. Three FanList-seam cases were added: composer mode and Creator, 🔥 from the feed, and unpin resets to All. The composer is seeded through `forcedAccountId`, which only sets its initial account (`MassMessageComposer.tsx:95`).
- D5 (the Focus test used invalidation, but production patches with `setQueryData`, `useInboxRealtime.ts:441`): **accept**. Verified. The test now injects the realtime event through the `@/lib/events` mock (`useChatList.test.tsx:53-56`) and adds a head-poll arrival.
- D6 (Acceptance passes with the routes unregistered): **accept**. The relay test now goes over HTTP through `_harness.make_client()` (`service/tests/_harness.py:88`).
- D7 (`py_compile` does not prove the migration upgrades a database): **partial**. Rejected the request to test `alembic upgrade`: the relay never runs Alembic, and an existing database is upgraded by `init_db()`'s additive catch-up (`service/db/engine.py:88-117`, `:163-194`). Accepted a test of that real path: drop the column, re-run `init_db()`, and assert the column is back (precedent `test_automation_queue_indexes.py:31-36`).
- D8 (the spec targets the page, but Phase 0 moves the Fan List into `MessagesPro` and requires `aria-current` to be kept): **accept**. Owns now names `MessagesPro`, the Interfaces carry the selected-row contract, story 63 is added, and `windowed.test.tsx` was added to Acceptance.
- D9 ("neither Phase needs the other" and "no Phase lists right-click" are false; Phase 1 claimed the row menu, `phase-01:137`, `:187`, `:276` at HEAD): **partial**. The dependency direction is accepted: Depends on now says Phase 1 depends on Phase 2, never the reverse. The ownership half is resolved the other way. The Phase 1 spec, as reconciled in parallel, now hands the row's right-click to this Phase's story 38 and reuses its menu for tabs (`docs/spec/phase-01-window-chrome-tabs.md:106`). Phase 2 therefore keeps the right-click and builds `OpenInNewWindowMenu` with the props Phase 1 names (`:140`), so there is one menu and no cycle. The coordinator should check that the final Phase 1 text agrees, because its `:212` and `:295` still describe Phase 1 adding the row menu.
- D10 (≥36px tap targets apply below `md`, while the stories say below 1024px): **partial**. The stories now separate the single pane (below 1024px) from tap targets (below 768px). The `md` breakpoint is kept by house precedent (`CL:733`, `CL:1244`), and the tablet range is flagged ASSUMPTION.

Counts: 18 accept, 12 partial, 5 reject, 0 needs-human.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Green: move Split Inbox last (`:124`, `:141-145`). **accept** on order, rung 4: it is the only ticket that touches a database. The Split Inbox tickets land after Phase 3 and before Phase 6, not at the very end, because Phase 6 lifts `SplitInbox`'s Geometry (`phase-06-geometry-pass.md:387`, FL50) and Phase 7 grades the Split Inbox Region. Depends on has a new "Landing split" entry with its ASSUMPTION, and the Acceptance block is split into a core block and a Split Inbox block. Story 10 already gives the core a selector with only "All inboxes". The plan names Split Inbox, so it is deferred, not cut.
- Black: `init_db()` changes the production database (`:144`). **partial**: the spec runs nothing against a real database. The migration is compiled only, and the catch-up is tested on a temp database (`:143`, `:300`). Deploying is the only step that adds the column to production, and that is the human's call, so it is listed under "Needs the human" in `plan-review.md`. The column stays nullable and additive.
- Blue: Split Inbox is first in the cut order. **partial**: it is the first thing a short budget defers, but it stays specced, because the plan names it and ADR-0004 decides its store.
- Red: the moves Phase 7 makes look like churn. **partial**: this Phase now puts the three extra sort orders in the Fan List Extras overflow from the start (story 13, the sort decision and its test), as plan:30 asks (rung 2). Phase 7 no longer moves them.
- Red: the set breaks at the joins. **accept** for this spec's join: gap row 6 and the Out of Scope entry said Phase 1 puts Online Fans and Notifications in the Window header. Phase 1 now builds them as the Fan List buttons (`phase-01-window-chrome-tabs.md:157-159`), and both lines say so.
