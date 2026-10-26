# Phase 01 — window chrome, creator tabs, fan tabs

**Objective.** Messages Pro has Infloww's two top rows from 1024px up: a Window header (Home, the Creator tabs strip, "+ Add a Creator", SFW) and the Fan tabs strip. The Online Fans and Notifications buttons sit at the top of the Fan List. Everything is in the Clone's order and Geometry. `AccountRoster` is gone from Messages Pro, and All Models and Group chat sit behind the Legacy flag or in the Extras overflow.

## Gap table

Values are measured from `ui-redesign/infloww-exact/messages.html` (CSS line numbers are given first, then markup) and `messages.js`. `_shared/components.html` is the Inflowwww fx- kit and has no tab, header or menu rule (`grep -n 'tab\|header' _shared/components.html` → none), so no row cites it. Colours are left out on purpose (ADR 0001).

| Clone selector and values | Ours (`file:line`) | Gap | Change |
|---|---|---|---|
| `.topstrip` `:51-55`, override `:101`: height 46px, padding 0 14px, `align-items:flex-end`, border-bottom 1px. Markup `:582` | None inside Messages Pro: `app/app/messages-pro/page.tsx:187-220` renders panes only. The shell's `components/shell/TopBar.tsx:54` (56px) belongs to the app, not to Messages Pro | Region missing | New Window header row: 46px tall, 14px side padding, children bottom-aligned |
| `.htab` (Home) `:87-89`, `:103`: gap 7px, 12.5px/600, padding 6px 16px, radius 8px 8px 0 0, icon 15px, `align-self:flex-end`. Markup `:585-588`, label "Home", grid icon | None | Missing | First item in the row, a link to `/` |
| `.am-hero` (All Models, ours) `:92-97`, `:104`: height 30px, padding 0 14px, margin-left 2px, radius 8px, 13px/700, icon 16px, margin-bottom 5px | `components/inbox/AccountRosterIcon.tsx:209` `AllModelsRosterIcon`, a 32px circle inside the roster (`AccountRoster.tsx:221-238`) | An extra placed in the Infloww row | Flag on: right after Home, with these values. Flag off: inside the Window header's Extras overflow. Tooltip "Inflowwww extra" |
| `.ctabs` `:332-333`: horizontal flex, gap 4px, max-width 58vw, `overflow-x:auto`, scrollbar hidden, `align-items:flex-end` | `components/inbox/AccountRoster.tsx:192-258`: a vertical rail 44px / 260px wide (`page.tsx:29-30`, `:189`, `:194-199`) | Wrong orientation and place | Creator tabs strip inside the Window header. The roster column leaves the grid |
| `.ctab` `:56-59`, `:105`, `:334-339`: height 36px, padding 0 10px 0 6px, gap 8px, radius 9px 9px 0 0, max-width 220px, 1px border with no bottom edge. Active: tinted border plus a 2px inset top line. `.dragging` opacity .4. `.dropmark` 2px inset left line | `AccountRosterIcon.tsx:132`: a 32px round icon with no name and no close | Shape; name and close missing | Creator tab with these values |
| `.ctab .cav` `:60`, `:340`: 26×26, radius 6px; initials fallback 800 11px | `AccountRosterIcon.tsx:132`, `:149`: 32×32 round; initials 11px/500 | Size, radius | 26px avatar, radius 6px |
| `.ctab .cname` `:62`: 13px/700 | None (the rail shows no name) | Missing | Name 13px/700, ellipsis inside the 220px cap |
| `.mini-badge` `:63-64` (`.pink` on the tab, `:347`): min-width 16px, height 16px, padding 0 4px, radius 8px, 10px/700 | `AccountRosterIcon.tsx:42-43`: min-width 16px, height 14px, 9px bold | Height, font | 16px badge, 10px/700 |
| `.ctab .cclose` `:67`, `:345`: 16×16, margin-left 2px | None | Missing | ✕ close |
| `.ctab.nosess`, `.lock` `:342-346` | Not applicable: only session-bearing Creators are listed (`hooks/useAccounts.ts:137-143`) | None | None |
| `.ctabs-empty` `:358`: 12px, padding 0 10px. Texts `messages.js:284` "All creator tabs closed — use “+ Add a Creator”" and `:3410` "No creators on this relay" | `AccountRoster.tsx:173-177` renders an empty div | Missing | Same texts and geometry |
| `.add-creator` `:68-69`, `:102`: gap 7px, 13px/500, padding 0 14px, icon 15px, `align-self:center`. Markup `:594-597` "Add a Creator" | None. The Creator choice today is the top bar's `ScopeSwitcher` (`TopBar.tsx:72`) | Missing | "+ Add a Creator" after the tabs, opening the Creator picker |
| `.pop` `:361-376`: min-width 238px, max-width 360px, radius 10px, padding 6px. `.prow` padding 8px 10px, radius 7px, gap 9px. `.phead` 10.5px/700 uppercase, letter-spacing .5px, padding 8px 10px 4px. `.pav` 22×22, radius 5px. `.pmeta` 11px | None | The picker is missing | Used by the Creator picker and the "Open in a new window" menu |
| `.top-right` `:70`: margin-left auto, gap 14px | Not applicable | None | SFW and the Extras overflow sit at the right, 14px apart |
| `.sfw` / `.switch` `:71-74`: a column with 3px gap; the label sits above the switch at 10px/600, letter-spacing .5px; switch 26×14, radius 8px; knob 10×10 at 2px/2px. Markup `:599` | `TopBar.tsx:82-94`: a row with a 14px label left of the switch, inside a 36px bordered button; switch `w-[26px] h-[14px]` (`:91`), knob 10px (`:92`) | Label position and size, container | Window header SFW in the Clone's column layout, using the same SFW store as the top bar |
| `.tr-box`, `.icon-btn` in `.top-right` `:75-79`. Markup `:600-606` | None | Not in §3.3's header list | None (Out of Scope) |
| `.hometabs` `:82`: height 34px, padding 0 14px, `align-items:flex-end`, border-bottom 1px. Markup `:611` | None | Missing | Fan tabs row, always rendered from lg up |
| `.hometabs .htab` (Group chat, ours). Markup `:612-615`, same `.htab` values | `components/chat/ChatSurface.tsx:994`, `:1214` `GroupChatButton` in the chat header | An extra placed in the Infloww row | Flag on: first item in the Fan tabs row, a link to `/group`. Flag off: inside the Window header's Extras overflow. Tooltip "Inflowwww extra" |
| `.hometabs .thread-tabs` `:108-109`, `.thread-tabs` `:194`: gap 3px, margin-left 4px, flex 1, `overflow-x:auto` | None | Missing | Fan tabs strip |
| `.ttab` `:195-197`: gap 8px, 1px border with no bottom edge, radius 8px 8px 0 0, padding 7px 11px, 12.5px/600, max-width 190px, nowrap. Active: 2px inset top line | None. Nearest is `ChatSurface.tsx:981-993` "↗ pop out", which opens a browser tab | Missing | Fan tab with these values |
| `.ttab-dot` `:110`: 7×7 round (Creator colour in the Clone, `messages.js:2555-2557`). `.ttab-name` `:198` ellipsis. `.ttab-x` `:199`: opacity .5, 11px, radius 4px, padding 2px 4px | None | Missing | The 7px dot carries online status; name and ✕ as measured |
| Fan tab unread and signal: not in the Clone (`messages.js:2559-2562` renders dot, name and ✕ only). C[H262067, H406874] | None | Missing | See ASSUMPTION below |
| `#tbOpen` "Pop out" `:707` in `.th-right` before refresh. It pins the chat as a tab (`messages.js:2588-2596`) | `ChatSurface.tsx:981-993` "↗ pop out" opens `/messages-pro/<acc>/<fan>` in a browser tab | No control creates a Fan tab | Add "Open in new tab" right before "↗ pop out" |
| `.big-btns` `:122-126`: a row under `.list-head`, gap 12px, padding 4px 16px 14px. Buttons: flex 1, height 42px, radius 9px, gap 8px, 14px/600, icon 18px; Online Fans accent fill, Notifications green fill. Markup `:634-643` | No Online Fans control (`components/chat/ChatList.tsx` has no online filter). Notifications is the top bar's 32px bell (`components/NotificationBell.tsx:240-254`) | Missing in the Fan List | Fan List buttons between the Fan List header and its filters |
| `.notif-badge` `:127-128`: top -7px, right -6px, min-width 22px, height 22px, radius 11px, 12px/700, 2px border in the panel colour | `NotificationBell.tsx:249-253`: min-width 16px, height 16px, 9px, top/right -4px | Size, position | The Fan List variant uses the Clone's values |
| Online Fans pressed state, `messages.js:3103-3107`: 2px outline while on | None | Missing | `aria-pressed` plus a 2px ring |
| `.empty` `:287-289`: a column with 22px gap, 130×130 icon, 26px text. Markup `:719-721` "Select any conversation to start" | `page.tsx:216-218`: "Pick a conversation on the left.", 14px, no icon | Label, size | The Clone's label and Geometry |
| `.list` `:116`: width 390px | `page.tsx:189`: 320px column | Width | None here (Fan List pane: Phase 2; Geometry: Phase 6) |
| Right-click "Open in a new window": not in the Clone (`grep -n contextmenu messages.js` → none). C[H545992] | None | Missing | A one-item menu with `.pop` Geometry |

ASSUMPTION: the right-click menu uses `.pop`/`.prow` Geometry, because the Clone has no context menu. Overturned by a measured Infloww context menu.
ASSUMPTION: the Fan tab's unread badge uses `.mini-badge` Geometry, and its signal is the Row badge glyph at the tab's 12.5px font. Neither value is in the Clone or §3.3. Overturned by a measured Infloww Fan tab.
ASSUMPTION: the Fan tab rows above (`.thread-tabs`, `.ttab`, `.ttab-dot`, `.ttab-x`) measure Inflowwww's own strip, which was built at an operator's request (`messages.js:2543-2546`), not a capture of Infloww's Fan tab. The values stand because the plan names the Clone as the Geometry reference. Overturned by a measured Infloww Fan tab.

## Problem Statement

An Employee who works several Creators in Messages Pro switches between them with a 44px rail of round icons that shows no names. They can keep only one Fan's conversation in view. To keep a second one they must open a separate browser tab, which loses the Fan List. Infloww users expect a row of named Creator tabs with unread totals, a row of Fan tabs for the conversations they are juggling, Home and SFW at the top, and big "Online Fans" and "Notifications" buttons at the top of the Fan List. None of these exist. Notifications open only from the app's top-bar bell and lead to new browser tabs. Two Inflowwww extras, All Models and Group chat, sit where Infloww's own controls go.

## Solution

Messages Pro gets Infloww's two top rows. The Window header holds Home, one Creator tab per Creator (avatar, name, unread total; click to switch, ✕ to close, drag to reorder, "+ Add a Creator" to reopen one), and SFW. Under it, the Fan tabs strip holds up to 100 Fan tabs. The Employee adds one with "Open in new tab" in the Chat header. Each tab shows the Fan's name, online status, unread count and signal, and clicking it opens that Fan's Thread. Right-clicking a Creator tab, a Fan tab or a Fan List row offers "Open in a new window", which opens a Pop-out window. "Online Fans" narrows the Fan List to Fans who are online now. "Notifications" opens the Creator's notifications, where the Employee can open a Fan tab or send a quick reply. Tabs are remembered per Employee across reloads. With the Legacy flag off, All Models and Group chat move into the Window header's Extras overflow. Closing the last Fan tab leaves the Thread on "Select any conversation to start".

## User Stories

Window header
1. As an Employee, I want Messages Pro to have its own Window header row above the panes, so that Messages Pro looks like Infloww's both in the app and in a Pop-out window.
2. As an Employee, I want "Home" first in the Window header, so that one click takes me to the dashboard at `/`.
3. As an Employee, I want an "SFW" switch in the Window header with its label above it, so that I can blur media without leaving Messages Pro, including in a Pop-out window that has no app top bar.
4. As an Employee, I want the Window header's SFW and the app top bar's SFW to always agree, so that one switch never says "on" while the other says "off".
5. As an Employee on a screen narrower than 1024px, I want Messages Pro to keep its one-pane layout with no Window header or tab strips, and Creator switching in the top bar, so that the phone layout in `docs/routes.md` stays as it is.

Creator tabs
6. As an Employee, I want one Creator tab per session-bearing Creator, in the relay's account order by default, so that the strip opens on Creators I can actually chat as.
7. As an Employee, I want each Creator tab to show the Creator's avatar, name and unread total, so that I can see which Creator needs attention.
8. As an Employee, I want clicking a Creator tab to switch the Fan List to that Creator and mark the tab active, so that the tab works like Infloww's.
9. As an Employee, I want a Creator to start loading the moment I hover or pick its tab, so that switching feels as fast as the old roster.
10. As an Employee, I want ✕ on a Creator tab to close it, and when I close the active tab I want the first remaining tab to become active, so that I can hide Creators I am not working.
11. As an Employee, I want the strip to say "All creator tabs closed — use “+ Add a Creator”" when every tab is closed, and "No creators on this relay" when there are no Creators, so that an empty strip is never a mystery.
12. As an Employee, I want "+ Add a Creator" to list every Creator, marked "open" or "add", so that I can reopen a closed tab and switch to it in one click.
13. As an Employee, I want to drag a Creator tab to a new position, with a drop marker while I drag, so that I can order Creators the way I work them.
14. As a keyboard user, I want ArrowLeft and ArrowRight to move the focused Creator tab, and Enter or Space to activate it, so that I can reorder without a mouse.
15. As an Employee, I want right-click on a Creator tab to offer "Open in a new window", which opens a Pop-out window on that Creator, so that I can put one Creator on a second screen.
16. As an Employee, I want a Messages Pro URL carrying `account=<id>` to open on that Creator and reopen its tab if I had closed it, so that "Open in a new window" lands where I asked.
17. As an Employee, I want a newly added Creator to appear at the end of the strip, and a removed one to disappear, so that the order I saved survives roster changes.
18. As an Employee, I want my Creator tab order and closed tabs remembered per Employee across reloads, so that my setup is still there tomorrow.
19. As an Employee with many Creators, I want the strip to scroll sideways without a visible scrollbar and without pushing SFW off screen, so that the row keeps its shape.

Fan tabs
20. As an Employee, I want "Open in new tab" in the Chat header to add a Fan tab for the conversation I have open, so that I can come back to it in one click. Clicking a Fan List row opens that Fan's Thread without adding a tab, and marks the Fan's tab active if it has one.
21. As an Employee, I want "Open in new tab" on a Fan who already has a tab to make no duplicate, so that the strip stays clean.
22. As an Employee, I want each Fan tab to show the Fan's name, online status, unread count and signal, so that I can see who is waiting and who matters without opening them.
23. As an Employee, I want clicking a Fan tab to open that Fan's Thread, and to switch to the Fan's Creator if another Creator is showing (but not when All Models is showing), so that the Thread always matches the Fan List.
24. As an Employee, I want the Fan tab of the open conversation marked active, so that I know where I am.
25. As an Employee, I want ✕ on a Fan tab to close it. When I close the active tab I want the last remaining tab to open, and when I close the last tab, whether or not it was the open one, I want the Thread to show "Select any conversation to start".
26. As an Employee, I want at most 100 Fan tabs. At 100, "Open in new tab" is disabled with the tooltip "Fan tab limit reached (100)", so that no tab I kept is ever dropped silently.
27. As an Employee, I want my Fan tabs remembered per Employee across reloads, so that a refresh does not lose my working set.
28. As an Employee, I want Fan tabs to span Creators and to stay put when I switch Creator tabs, so that I can juggle Fans across Creators.
29. As an Employee, I want right-click on a Fan tab to offer "Open in a new window", which opens a Pop-out window at that Fan's Deep link.
30. As an Employee with two Messages Pro windows open, I want a Fan tab opened or closed in one window to show up in the other, so that the two windows never disagree.
31. As an Employee who switches to another Employee in the top bar, I want the tab strips to show that Employee's tabs, so that tabs are personal.
32. As an Employee, I want the Fan tabs row to keep its 34px height even when it is empty, so that the panes do not jump when the first tab opens.
33. As an Employee, I want a Fan tab's tooltip to name the Fan and the Creator, so that I can tell same-named Fans of different Creators apart.
48. As an Employee, I want closing a Creator tab to leave that Creator's Fan tabs in place, and a Fan tab whose Creator has left the relay to be hidden until the Creator returns, so that no Fan tab is lost silently.
49. As an Employee at 100 Fan tabs, I want a notification's "open" to still open the Fan's Thread, without adding a tab, and to tell me "Fan tab limit reached (100)", so that the cap never blocks a reply.

Fan List buttons
34. As an Employee, I want "Online Fans" and "Notifications" as two equal-width buttons under the Fan List header and above its filters, as in the Clone, so that they are where Infloww users look for them.
35. As an Employee, I want "Online Fans" to narrow the Fan List to Fans who are online now and to show that it is pressed, and pressing it again to clear it, so that I can work Fans who are present.
36. As an Employee, I want a Fan to count as online when OnlyFans says so on the row, when the Fan was last seen within 5 minutes, or when the Fan is on the Creator's OnlyFans online-subscribers list, so that the filter matches the Clone's rule without missing Fans the row data does not cover.
37. As an Employee, I want "Notifications" to open the notification panel for the active Creator (every Creator under All Models), with the Creator's OnlyFans notification count on the button, so that I can see new subscriptions, purchases and tips.
38. As an Employee, I want a notification about a Fan to open that Fan in a Fan tab in this window, so that I can answer without losing Messages Pro (Infloww's "open a fan tab").
39. As an Employee, I want a "Reply" field on a message notification that sends my text to that Fan as the Creator, so that I can quick-reply the way Infloww allows.
40. As an Employee on a phone, I want the Fan List buttons to stay in the Fan List pane, so that Online Fans and Notifications work at every width.

Fan List row
41. (Moved to Phase 2.) Right-click on a Fan List row is Phase 2's story 38. Phase 1 reuses that menu for both tab kinds.

Inflowwww extras
42. As an Employee with the Legacy flag off, I want All Models and Group chat out of the Window header and the Fan tabs row, inside the Window header's Extras overflow with the tooltip "Inflowwww extra", so that no extra takes an Infloww element's place.
43. As an Employee with the Legacy flag on, I want All Models right after Home and Group chat first in the Fan tabs row, so that the pre-parity layout comes back.

Thread empty state
44. As an Employee with no conversation open, I want the Thread to read "Select any conversation to start" at the Clone's size, so that the empty Thread matches Infloww.

Maintainers
45. As a maintainer, I want the `AccountRoster` modules left in the repo untouched, so that the roster can return to another screen without archaeology.
46. As a maintainer, I want vitest coverage for the Creator tabs, the Fan tabs and the Messages Pro page chrome, so that later Phases cannot silently break them.
47. As a maintainer, I want `scripts/ui-shots.sh` to show the Window header, both tab strips and the Fan List buttons in Clone order in `messages-pro-desktop.png`, so that the visual loop can check the Phase.

## Implementation Decisions

- **Owns.**
  - New: the Window header (`WindowHeader`). Creator tabs (`CreatorTabs`, which includes "+ Add a Creator" and its picker) with their store (`useCreatorTabs`). Fan tabs (`FanTabs`, `OpenInNewTabButton`) with their store (`useFanTabs`). The Fan List buttons (`FanListButtons`). The Creator window URL helper. The online rule (`isFanOnline`).
  - Modified: Phase 0's `MessagesPro` component, which the index route and the Deep link route both render (Phase 0 spec, Interfaces, `MessagesPro`): its composition, the `account` parameter and the Thread empty state. The pages themselves are not edited, so the chrome reaches both routes (ADR 0002's one tree). The Fan List (`FanList` from Phase 2: the `actions` slot and `onlineOnly`). Phase 2's `OpenInNewWindowMenu`, which both tab kinds reuse unchanged. `NotificationBell` (a Messages Pro variant). The Chat header inside `ChatSurface` (one added button). The Messages Pro token module (Phase 1's measured numbers). `scripts/ui-shots.sh`: only the `messages-pro-desktop` state's setup and state check.
  - Untouched: `AccountRoster*`, `TopBar`, `Sidebar`, `ScopeContext`, `lib/relay.ts`, `service/`.

  ASSUMPTION: Phase 1 may edit the desktop state of `scripts/ui-shots.sh`, the one file outside `app/` and `docs/` that Phase 0 adds under the plan's own naming of it (Phase 0 spec, the Owns ASSUMPTION on `scripts/ui-shots.sh`). Overturned if Phase 0 freezes the harness's states.

  The Phase 1 modules (`CreatorTabs`, `FanTabs`, `useFanTabs`, `FanListButtons`, `OpenInNewWindowMenu`) live in `app/components/chat/`, beside Phase 2's Fan List modules, because Phase 2 landed there first (ticket 64).

  ASSUMPTION: `AccountRoster*` stays in the repo with no importer. `grep -rn AccountRoster app` shows that `app/app/messages-pro/page.tsx:21` is its only importer, so the plan's "the roster stays elsewhere" has no "elsewhere" today. Deleting it would be the less reversible move. Overturned if the human wants the dead modules removed.
- **Interfaces.**
  - `WindowHeader()`: no props. In order, it renders Home, All Models (flag on), `CreatorTabs`, then at the right SFW and, with the flag off, the Extras overflow holding All Models and Group chat.
  - `CreatorTabs()`: no props. It reads the session-bearing Creators, their unread counts (the roster-counts hook) and the scope, and writes the scope. It keeps the roster's pick-time and 250ms hover-intent warm-up (prefetch the Creator's Fan List, refresh its unread count; `AccountRoster.tsx:77-114`).
  - `useCreatorTabs()` returns `{ openIds, closedIds, reorder(ids), close(id), reopen(id) }`.
  - `useFanTabs()` returns `{ tabs, full, open(tab): "opened" | "exists" | "full", close(key) }`. The constant `FAN_TABS_MAX = 100`. `tabs` leaves out tabs whose Creator is not among the loaded session-bearing Creators; those stay in storage and count toward the cap.
  - `FanTabs({ activeKey, onActivate(tab), onClosed(next | null) })`. `onClosed` fires when the closed tab was the active one (`next` is the last remaining tab, or null) and when no tab remains (null), whether or not the closed tab was active.
  - `OpenInNewTabButton({ accountId, fanId, name })`.
  - `FanListButtons({ onlineOnly, onToggleOnline, onOpenFan(tab) })`.
  - `OpenInNewWindowMenu({ href, children })` wraps its child and opens the one-item menu on `contextmenu`.
  - `isFanOnline(row, profile, onlineIds?)` returns true when the row's `isOnline` is true, `lastSeen` is less than 5 minutes old (`messages.js:98-101`), or the Fan id is in `onlineIds`.
  - The Fan List gains `onlineOnly?: boolean` (filters rows with `isFanOnline`, combined with the chips) and an `actions?: ReactNode` slot rendered between the Fan List header and its filters.
  - `NotificationBell` gains `variant?: "topbar" | "messages-pro"` and `onOpenFan?`. `"topbar"` is the default, so the top bar is unchanged. The Messages Pro variant renders the Clone's green button, shows the active Creator's OnlyFans notification count as its badge, opens its panel inside the viewport, makes a row with a known Fan id call `onOpenFan` instead of opening a browser tab, and gives message rows the quick reply.
- **Schema.** None. Nothing reaches the relay's database.
- **Contracts.**
  - Fan tabs storage: `localStorage["chatterly:fan-tabs:v1:<employeeKey>"]` holds an array of at most 100 `{ accountId: string, fanId: string, name: string }`, in open order. `fanId` keeps the wire spelling, because Fansly snowflakes exceed 2^53 (`app/app/messages-pro/[accountId]/[fanId]/page.tsx:32-46`). It is parsed with `fanIdFromParam`.
  - Creator tabs storage: `localStorage["chatterly:creator-tabs:v1:<employeeKey>"]` holds `{ order: string[], closed: string[] }` (the Clone's `fastt_msg_tab_order` / `fastt_msg_tab_closed`, `messages.js:30`). Saved ids are filtered to live Creators, and unknown Creators are appended (`messages.js:242-255`).
  - Change events `chatterly-fan-tabs-change` and `chatterly-creator-tabs-change`, plus `storage`, sync the stores within a window and across windows (the `hooks/useBlurMode.ts:42-48` pattern).
  - `employeeKey` is the picked Employee's id (`useEmployee().current`). Without one it falls back to the signed-in principal (user id, then chatter id, the `useRosterCounts.ts:41-45` rule), and then to `"anon"`. The stores neither read nor write until the Employee and the principal have resolved, so tabs loaded during sign-in are never saved under `"anon"`. A stored value that is not valid JSON or not the shape above reads as empty and is overwritten on the next change.
  - Creator window URL: `/messages-pro?window=1&account=<accountId>`. Fan window URL: `/messages-pro/<accountId>/<fanId>?window=1`. Both open with `window.open(url, "_blank", "popup")`.
  - The `account` search parameter, on any Messages Pro route, sets the scope to that Creator and reopens its tab. An unknown id is ignored (`messages.js:3416-3428`).
  - Relay reads, all existing: the accounts list, `/admin/accounts/roster-counts`, the Fan List's chat rows, `/api/of/v2/users/notifications` (`service/server.py:5353`), `/api/of/v2/users/notifications/count` (`service/server.py:5393`), and `/api/of/v2/subscribers?type=active&online=1&limit=50` (`service/server.py:5598`). The last two are per Creator through `X-Account-Id` (`app/lib/relay.ts:58`). Quick reply sends with `POST /api/of/v2/chats/<fanId>/messages` through the Composer's send hook. No relay endpoint is added.
- **Layout.** From lg up, the `MessagesPro` root keeps `.h-chat` and becomes a column: the Window header (46px), the Fan tabs row (34px), then the pane grid with the roster column removed, as `flex-1 min-h-0` so the panes take the height left under the two rows. Below lg, both rows are hidden and the panes behave as today.

  ASSUMPTION: the Window header and both strips are hidden below 1024px, by analogy with `docs/routes.md:42` ("The account roster is hidden; scope switching lives in the top bar"), while the Fan List buttons show at every width because they belong to the Fan List pane. Overturned if the phone shots need tabs.
- **Two rows, not three.** The Clone has two rows: `.topstrip` holds Home, the Creator tabs, "Add a Creator" and SFW, and `.hometabs` holds the Fan tabs (`messages.html:582-620`). This spec follows the Clone (observation). `CONTEXT.md`'s Messages Pro entry reads as three rows.
- **Where Online Fans and Notifications go.** The plan's Phase 1 line and §3.3 "Header buttons" put them in the header. The Clone puts them as `.big-btns` in the Fan List under `.list-head` (`messages.html:634-643`). The plan binds what ships (the five buttons exist), and the Clone decides where. They ship as the Fan List buttons.

  ASSUMPTION: position by observation, so Online Fans and Notifications sit in the Fan List pane, not in the Window header. This is flagged for the human's veto, and is overturned if the human wants them in the Window header as the plan's wording reads. The glossary records this placement (`CONTEXT.md`: the Window header entry's 2026-10-12 note, and the "Fan List buttons" term), and it changes with a veto.
- **Creator tabs.**
  - The default order is the relay's account order, with no reshuffling by activity (`messages.js:244-247`). Closing the active tab activates the first open tab. When none remain, the strip shows its empty text and the scope is left alone (`messages.js:282-285`, `:352-365`).
  - Picking from "+ Add a Creator" reopens the tab and activates it (`messages.js:368-388`).
  - A Creator tab's unread total is the number of unread conversations (`useRosterCounts.ts:6`). It refreshes for every Creator, not only the scoped one, because the roster counts poll every 60s (`useRosterCounts.ts:73`) and realtime events patch them.
  - After ✕, focus moves to the tab that became active, or to "+ Add a Creator" when none remain. Fan tabs follow the same rule, with focus going to the Fan tabs strip when none remain.

  ASSUMPTION: the focus targets after ✕ are a coin flip among accessible options (rung 6); the Clone sets no focus. Overturned by an Infloww capture.
  - Drag reorder uses `hooks/useReorder.ts`, the house's native HTML5 drag helper, including its ArrowLeft and ArrowRight move, so no dependency is added.

  ASSUMPTION: the picker lists only session-bearing Creators (`useActiveAccounts`, house precedent), not the Clone's every-Creator list with "no session". Overturned if the human wants session-less Creators shown.

  ASSUMPTION: Creator tabs ignore the All Models include list (`useAllModelsInclude`), which belongs to the All Models extra. Overturned if excluded Creators should also leave the strip.

  ASSUMPTION: Creator tab order and closed tabs are stored per Employee, like Fan tabs. The plan keys only Fan tabs. Overturned if they should be shared per browser.
- **Fan tabs.**
  - Opening adds the tab at the end (`messages.js:2565-2572`). Closing the active tab opens the last remaining one (`messages.js:2573-2580`). Closing the last tab clears the Thread to the empty state whether or not it was the open one, because the plan says "closing the last tab shows the thread empty state" without a condition (`docs/plans/messages-pro-parity.md:91-92`).
  - Only "Open in new tab" and a notification's "open" create a Fan tab. A notification's "open" from any window adds the tab in the Messages Pro window: a Messages Pro page that is up takes it in place, with no reload; with none up, its link carries `?fanTab=<name>`, which Messages Pro reads once and drops. Clicking a Fan List row or arriving by Deep link selects the Fan without adding a tab, and marks the Fan's tab active if one exists. In the Clone only `#tbOpen` adds a tab (`messages.js:2594`).
  - One Thread is mounted at a time, keyed by Creator and Fan, as today (`app/app/messages-pro/page.tsx:33`). Inactive tabs are never mounted, so they send no read marks (`ChatSurface.tsx:413`). Composer drafts behave as they do today when the selection changes. A send already in flight keeps its own Creator and Fan (`app/hooks/useSendMessage.ts:118`).
  - Activating a Fan tab changes the selection only. The URL does not change, as row selection does not change it today.
  - Closing a Creator tab leaves its Fan tabs alone. A Fan tab whose Creator is not among the loaded session-bearing Creators is hidden, kept in storage and counted toward the cap, and shows again when the Creator returns. Hiding waits until the Creators have loaded.
  - At 100 tabs, a notification's "open" selects the Fan's Thread without adding a tab and shows "Fan tab limit reached (100)": in the panel for its rows, under the Fan tabs strip for a few seconds for any other notification.
  - A Fan whose presence is unknown shows the offline dot, because `isFanOnline` returns false.

  ASSUMPTION: a tab whose Creator left the relay is hidden and kept rather than dropped, because keeping is reversible (rung 4). Overturned if the human wants such tabs removed.

  ASSUMPTION: at the cap, a notification's "open" falls back to selecting the Thread, so the cap never blocks a reply (rung 4). Overturned if Infloww refuses the open.
  - Activating a tab of another Creator first sets the scope to that Creator, unless the scope is All Models. Otherwise the page's scope guard (`page.tsx:43-48`) would clear the selection.
  - The Thread for a tab is opened the way Phase 0's Deep link opens one from an account id and a Fan id.
  - Inside a tab the order is: online dot (7px), name, unread badge, signal, ✕. The tooltip is "<Fan> · <Creator>" (`messages.js:2560`).

  ASSUMPTION: at 100 tabs, opening is refused and nothing is evicted, which is the more reversible choice. Overturned if Infloww evicts the oldest tab.

  ASSUMPTION: the 7px dot shows online status (ok token when online, dim when offline) instead of the Clone's Creator-colour dot, which looks like a Inflowwww addition (`messages.js:2554`). The Creator is named in the tooltip. Overturned if the Creator colour cue is wanted back.

  - A tab's facts are the same facts Phase 2 feeds `FanRow`, read from the query cache by the same keys: the Fan List's chat rows for that Creator, the `["of-user", accountId, fanId]` profile, and Phase 2's Fan activity facts (`lastPpvPurchase` and the rest; Phase 2 spec, Interfaces, `FanRow`). The signal is computed with Phase 2's `rowBadges(facts, now)`, not from a separate source. Tabs of the scoped Creator are live, because the Fan List keeps those queries fresh.

  ASSUMPTION: no fetch is added for tabs of other Creators. Their unread count, online status and signal come from whatever the cache holds, and a tab with nothing cached (the persisted cache sheds old queries on quota pressure and skips idle ones, `app/components/providers.tsx:194-198`, `:210-214`) shows its stored name and the offline dot only. Fetching per tab would fan out up to 100 requests, which the page already avoids for warm-ups (`app/app/messages-pro/page.tsx:76-81`). Overturned if stale or bare tabs prove confusing in use.

  ASSUMPTION: the signal is the Fan's single highest-priority Row badge, taken in the plan's listed order: New, 🔥, ❄️, ❌, Off. It is computed with Phase 2's Row badge rules. The evidence is "a priority Fan Signal" (uncommitted research note `/tmp/infloww-research/screens.md:68`; the Fan Signals list at `:79` is the mym product). Overturned by a measured Infloww Fan tab.

  ASSUMPTION: Fan tabs do not reorder. The plan's target line gives drag only to Creator tabs, and the Clone's Fan tabs are not draggable (`messages.js:2559`). The acceptance's "add, close, reorder, 100 cap, unread badge" is read as the union of the two test files. Overturned if Fan tabs must also drag.

  ASSUMPTION: both windows share one tab set through the `storage` event (the `useBlurMode` precedent). Overturned if each Pop-out window should keep its own tabs.
- **"Open in new tab" in the Chat header.** It is placed right before "↗ pop out" (`ChatSurface.tsx:981`), where the Clone's `#tbOpen` sits relative to refresh. It is disabled at the cap.

  ASSUMPTION: Phase 1 adds the button to the current Chat header. Infloww's help says "From their conversation, click Open in new tab" (C[H262067]), which bears on ADR 0002's assumption that the Chat header's pop-out opens a window. The Phase 3 draft relabels "↗ pop out" itself as "Open in new tab" that adds or focuses the Fan tab (Phase 3 spec, Gap row H9). Phase 3 then places Phase 1's `OpenInNewTabButton` in that slot rather than keeping two controls. Overturned if Phase 3 lands first, in which case Phase 1 only wires Phase 3's button to `useFanTabs`.
- **Open in a new window.** One menu module is used by Creator tabs, Fan tabs and Fan List rows. Phase 2 owns the row's menu, the `OpenInNewWindowMenu` module and their tests (Phase 2 spec, story 38 and Interfaces). Phase 1 reuses that module for both tab kinds and does not change the row. It closes on an outside pointerdown or Escape (the `TopBar.tsx:115-127` pattern). The keyboard context-menu key and Shift+F10 reach it through the native `contextmenu` event.

  ASSUMPTION: the Fan URL relies on Phase 0's windowed variant applying under the shared Messages Pro layout to the Deep-link route too. The Creator URL adds an `account` parameter, because the plan names no Creator-only route. Overturned by Phase 0's spec.

  ASSUMPTION: `window.open(url, "_blank", "popup")` asks for a separate window rather than a tab, with the size left to the browser. Overturned if windows must open at a fixed size.
- **Online Fans.** The button toggles page state passed to the Fan List as `onlineOnly`. It uses only existing relay data, as the plan binds. Row data alone under-reports who is online: local enrichment carries no `lastSeen` (`app/hooks/useChatList.ts:118-160`), only Fans fetched from OnlyFans get it (`:189`), and `isOnline` is set only when OnlyFans sends it (`:232-233`). The relay already serves the Creator's online subscribers: `GET /api/of/v2/subscribers?online=1` (`service/server.py:5598-5611`, OnlyFans' `filter[online]=1`, `service/of_client.py:893-907`). While the button is on, the page reads that route once for the scoped Creator with `type=active&limit=50` and passes the Fan ids to `isFanOnline` as `onlineIds`. If the read fails, the filter uses the row rule alone and the button's tooltip says "Online list unavailable". Under All Models the route is not read, and only the row rule applies.

  ASSUMPTION: one page of 50, which the client sorts by latest activity (`service/of_client.py:894`), rather than paging through every online subscriber. Fans online beyond the first 50 are still caught by the row rule. Overturned if busy Creators show online Fans missing from the filter.

  ASSUMPTION: no read under All Models, because one read per Creator is the fan-out the page already avoids (`app/app/messages-pro/page.tsx:76-81`). Overturned if All Models must filter by the online list too.

  ASSUMPTION: the tooltip text "Online list unavailable" is coined here; nothing in the Clone or §3.3 covers the failure. Overturned by an Infloww capture.
- **Notifications.**

  - The button reuses `NotificationBell`'s panel and filters (house precedent). Its badge is not the bell's tab-local arrival counter, which starts at zero, counts arrivals from every Creator and resets when the panel opens (`app/components/NotificationBell.tsx:112`, `:123-145`). It shows `all` from `GET /api/of/v2/users/notifications/count` for the scoped Creator, hidden at zero or on error, as the Clone does (`messages.js:2931-2944`). That route exists (`service/server.py:5393-5410`), with a 30s relay cache. It is re-read when the scope changes and when the panel closes.

  ASSUMPTION: under All Models the badge is hidden, because the count is per Creator and summing it is the all-Creator fan-out the page avoids (`app/app/messages-pro/page.tsx:76-81`). Overturned if All Models must show a total.

  ASSUMPTION: the re-read moments (scope change, panel close) follow the Clone, which reloads the count on Creator switch (`messages.js:1667`). Panel close stands in for the Clone's other reloads. Overturned if the badge proves stale in use.

  ASSUMPTION: "open a fan tab" and the quick reply come from C[H262067] (Notifications: "Quick reply … Reply", "message icon opens a fan tab"), not from the plan or the Clone. They are specced because the goal is element-for-element parity. The quick-reply field mounts that Fan's message hook only while it is open, sends text only, clears and reads "Sent" on success, and shows the error on failure without faking success. Overturned if the human narrows Phase 1 to the Clone's notification sheet.

  **Quick reply ticket.** The quick reply is this Phase's last ticket, and it is separable. The Notifications button, its badge, its panel and "open a fan tab" ship first. The Reply field (story 39, the Reply clause of the `NotificationBell` interface and the send in Contracts) and its two test cases come last. A short budget can drop that ticket without touching the others, and the human can veto it (`docs/spec/plan-review.md`, "Needs the human").
  ASSUMPTION: the quick reply stays specced, as Phase 1's last ticket. The help centre documents it (`docs/infloww-screens.md:243` gives the Notifications button a quick reply, "Reply", from C[H262067]), and the plan's goal is element-for-element parity, though the plan's Phase 1 line lists only the five buttons (`docs/plans/messages-pro-parity.md:84-95`). Putting it last is rung 5. This is overturned if the human vetoes it, in which case story 39, the Reply clause and its two test cases leave this spec.
- **Inflowwww extras (ADR 0003).** With the flag off, All Models and Group chat sit only in the Window header's Extras overflow (a "+" icon button labelled "Inflowwww extras"). With the flag on they return to their Clone places and the overflow is not rendered. All Models sets the scope to all and warms every Creator (the `AccountRoster.tsx:158-167` precedent). Group chat keeps the Chat header button's action, which never navigates the source tab: with a Fan open it calls `openGroupTab(accountId, fanId)` (`ChatSurface.tsx:1214-1217`, `app/lib/groupChannel.ts:335`), and with none open it opens `/group` in a new browser tab. The Chat header's own `GroupChatButton` is not touched here: Phase 3 moves it into the Chat header's Extras overflow (Phase 3 spec, Gap row H13; Phase 7 story 11).

  ASSUMPTION: with no Fan open, Group chat opens `/group` with `window.open("/group", "_blank")`, which may start a second group tab. The coordination layer has no call that focuses a group tab without adding a slot (`openGroupTabWithSlots([])` returns early, `app/lib/groupChannel.ts:295`). Overturned if a focus-only call is added.

  ASSUMPTION: the Extras overflow sits at the far right of the Window header, after SFW, where it displaces nothing. Overturned by Phase 7's placement.
- **Colours (ADR 0001).**

  ASSUMPTION: the Clone's colours map to our tokens as follows: Online Fans fill to `accent`, Notifications fill to `ok`, the active-tab top line and border to `accent`, the unread badges to `info` (the roster's "blue badge" rule, `useRosterCounts.ts:6`), and the online dot to `ok`. Overturned by Phase 6's token table.
- **Geometry tokens (ADR 0001).**

  ASSUMPTION: Phase 1's measured numbers from the Gap table go into the Messages Pro token module `app/lib/messagesPro.ts`, which Phase 1 creates if it is missing and Phase 6 owns. Components read them, with no magic numbers in JSX. Overturned if Phase 6 must land first.
- **Thread empty state.** The page's no-selection branch shows the Clone's icon and "Select any conversation to start" at 130px and 26px.

  Phase 1 owns this empty state, because the plan ties it to closing the last Fan tab (`docs/plans/messages-pro-parity.md:91-92`). The Phase 3 draft also lists the text (Phase 3 spec, Solution); for Phase 3 it is already done.

## Testing Decisions

There are two vitest seams, both external and both in the repo's style, plus the Visual loop, which drives the real app in a browser.

1. **The tab strips (module seam: `CreatorTabs`, `FanTabs` with `OpenInNewTabButton`).** The tests render through `renderWithProviders` (`app/test-utils.tsx`), with the real `ScopeProvider` and `FlagsProvider`. `EmployeeContext` is mocked to a fixed Employee, as `components/shell/AppShell.test.tsx` does. `relay.get` is mocked by path, as `app/analytics/message-dashboard/page.render.test.tsx` does. `localStorage` is cleared before each test, `window.open` is spied, and drag events carry a stub `dataTransfer`. Assertions are made on visible text, roles, `aria-*`, document order and `window.open` calls, never on hook state.
   - `app/components/chat/CreatorTabs.test.tsx` covers:
     - the default tabs with names and unread badges
     - clicking a tab, which sets the active Creator
     - closing with ✕, the switch to the next tab, and the all-closed text
     - "+ Add a Creator", which reopens a closed tab
     - drag-and-drop reorder and ArrowLeft/ArrowRight reorder, both surviving a remount
     - a saved order surviving a roster change: a new Creator appended at the end, a removed one gone, the rest in saved order
     - hovering a tab for 250ms (fake timers) issuing that Creator's Fan List prefetch
     - a different Employee seeing different tabs, nothing written while the Employee is unresolved, and a malformed stored value reading as the default tabs
     - focus landing on the newly active tab after ✕
     - right-click → "Open in a new window", which calls `window.open("/messages-pro?window=1&account=<id>", "_blank", "popup")`
   - `app/components/chat/FanTabs.test.tsx` covers:
     - "Open in new tab", which adds a tab, and a second click, which adds no duplicate
     - name, online dot, unread badge and signal from a cache seeded under the keys and shapes Phase 2's `FanRow` facts use (chat row, `of-user` profile, Fan activity with `lastPpvPurchase`), and a tab with nothing cached showing its stored name and the offline dot
     - click → `onActivate`
     - closing the active tab → `onClosed(last remaining)`; closing the only tab while another Fan is open → `onClosed(null)`
     - 100 seeded tabs leaving the button disabled with "Fan tab limit reached (100)"
     - persistence across a remount, and per Employee
     - a tab whose Creator is not loaded hidden but still counted toward the cap
     - `storage` events from another window adding a tab and removing one, the active one included
     - right-click → the Fan window URL
2. **The Messages Pro page (page seam).** The test is `app/app/messages-pro/page.render.test.tsx`. It mounts the index page, and for the first case also the Deep link page, with the real `MessagesPro`, the real Fan List and the real tab strips. `relay.get` and `relay.post` are mocked by path, `EventSource` and `matchMedia` are stubbed, and the Thread (`ChatSurface`) is stubbed to a marker naming its account and Fan id. The Thread is another Region, and only the selection is under test here. It covers:
   - Home, Add a Creator, SFW, Online Fans and Notifications in that document order, on both the index route and the Deep link route
   - no roster ("Expand roster" absent)
   - a Fan tab of Creator A clicked while Creator B is scoped: the Fan List shows A's rows and the Thread marker names A and the Fan (the scope guard at `page.tsx:43-48` does not clear it)
   - a Fan List row click selecting a Fan without adding a Fan tab
   - ✕ on the active tab opening the last remaining one; ✕ on the last tab, active or not, leaving the Thread on "Select any conversation to start"
   - the Window header SFW switch flipping the shared blur store, and a `chatterly-blur-mode-change` event (`hooks/useBlurMode.ts:26`) flipping the switch
   - flag off: All Models and Group chat only inside the Extras overflow, each with the "Inflowwww extra" tooltip
   - flag on: All Models after Home and Group chat first in the Fan tabs row
   - Online Fans: `aria-pressed`; a row last seen 4m59s ago kept and one seen 5m01s ago dropped (fake clock); a Fan on the mocked `/api/of/v2/subscribers?online=1` reply kept; a failed read falling back to the row rule; pressing again restoring every row
   - Notifications: the badge showing `all` from the mocked count route; the panel opening; a row opening a Fan tab, and at 100 tabs selecting the Thread with "Fan tab limit reached (100)"; Reply posting to `/api/of/v2/chats/<fan>/messages` with the notification's Creator in `X-Account-Id`; a rejected Reply keeping the text and showing the error
   - the empty Thread reading "Select any conversation to start"
   - `?account=<id>` opening on that Creator, including one whose tab was stored as closed, which reopens
3. **The Visual loop (browser seam).** Phase 1 changes the `messages-pro-desktop` state in `scripts/ui-shots.sh` to: click the first fixture Fan, click "Open in new tab", click the second fixture Fan, click "Open in new tab". Its state check asserts two Fan tabs with the second active. The click goes through the real Chat header, so a button that is not mounted fails the harness.

Prior art: `components/shell/AppShell.test.tsx` (context mocks), `app/analytics/message-dashboard/page.render.test.tsx` (page render with relay mocked by path), `hooks/useAllModelsInclude.test.tsx` (localStorage-backed hook), `components/NotificationToaster.test.tsx` (notification rows and window naming), `hooks/useInboxRealtime.roster.test.tsx` (roster counts).

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/CreatorTabs.test.tsx components/chat/FanTabs.test.tsx app/messages-pro/page.render.test.tsx
# Creator tabs replace the roster inside Messages Pro only; the roster modules stay.
test -z "$(grep -rlE 'components/inbox/AccountRoster' app/app/messages-pro)"
test -f app/components/inbox/AccountRoster.tsx
# "Open in new tab" is mounted in the real Chat header.
grep -q 'OpenInNewTabButton' app/components/chat/ChatHeader.tsx
# No new dependency for drag or context menus.
test -z "$(grep -E '"(@dnd-kit/[^"]+|react-dnd[^"]*|react-beautiful-dnd|@radix-ui/react-context-menu)"' app/package.json)"
# The Clone's empty-state label replaced ours.
grep -rq "Select any conversation to start" app/app/messages-pro
test -z "$(grep -rl 'Pick a conversation on the left' app/app/messages-pro)"
# Visual loop (harness from Phase 0).
# Prerequisite: venv/bin/python; in a git worktree, link the main checkout's venv first (see Worktrees in docs/ui-shots.md).
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-desktop.png
test -s docs/screenshots/clone-messages-pro.png
test -s docs/screenshots/messages-pro-report.json
# manual: Read docs/screenshots/messages-pro-desktop.png and docs/screenshots/clone-messages-pro.png side by side; list the visual diff for the Window header, Creator tabs, Fan tabs and Fan List buttons (position, size, label, order, missing element); fix, re-run scripts/ui-shots.sh, up to three rounds; write what remains as VISUAL GAP: lines in the ticket.
# manual: record the messages-pro-report.json summary in the Phase result and commit the final PNGs with the code.
```

## Depends on

- **Phase 0.** It provides `scripts/ui-shots.sh` and its `docs/screenshots/` artefacts (the visual loop and the last step of Acceptance). It also provides the windowed layout variant behind `?window=1`, which every "Open in a new window" targets, and the Deep link, which opens a Thread from an account id and a Fan id. Fan tab activation and the Fan window URL reuse that.
- **Phase 2.** It provides the split Fan List (`FanList`, `FanListHeader`, `FanListFilters`, `FanRow`), which this Phase extends with the `actions` slot and `onlineOnly`. It provides the row's "Open in a new window" menu, which this Phase reuses for both tab kinds. It also provides `rowBadges` and the Fan activity facts that the Fan tab's signal is computed from.

ASSUMPTION: Phase 1 lands after Phase 2, so that it edits the split Fan List instead of `ChatList.tsx` and reuses the Row badge rules and the row menu instead of duplicating them. There is no land-first fallback: the plan's target line requires the signal (`docs/plans/messages-pro-parity.md:85-86`), and without Phase 2 it has no source. Overturned if the human orders Phase 1 first, which means re-cutting this spec, not shipping it without the signal.

## Out of Scope

- **Deleting `AccountRoster*`.** The plan says the roster stays, and keeping it is reversible.
- **Fan tab drag reorder.** It is not in the plan's target line or the Clone.
- **The Clone's top-right translate selector (`.tr-box`) and window icon (`.icon-btn`), `messages.html:600-606`.** Neither is in §3.3's header list, and the translator belongs to Phase 4.

  ASSUMPTION: the unlabelled window icon is not Infloww's Multi-Window entry, which help article H545992 places in the sidebar menu (Phase 0). Overturned if a screenshot shows it in Infloww's Messages Pro header.
- **The SFW shortcut Cmd/Ctrl+Shift+S.** It belongs to the app's global top bar (§1.2), which this Phase does not change.
- **A new relay route for online subscribers.** The existing `/api/of/v2/subscribers?online=1` serves Online Fans (see Implementation Decisions).
- **The Fan List row's "Open in a new window".** Phase 2 owns it.
- **The Chat header's `GroupChatButton`.** Phase 3 moves it into the Chat header's Extras overflow.
- **Keeping Composer drafts per Fan tab.** Drafts behave as they do today when the selection changes.
- **The "Message withdrawn" notification's "View details" (C[H262067]).** It is parked: building it needs the notification's shape, which can only be observed in live data (floor 2).
- **"Message all" / "Message online fans".** That is Phase 2's "New" menu.
- **The Fan List width (390px vs our 320px) and the Fan List header.** These belong to Phases 2 and 6.
- **Restoring the last closed window's Creator on restart (H545992).** That is a desktop-app behaviour. A browser has no app restart.
- **Cross-device sync of tabs.** The plan puts Fan tabs in `localStorage`.
- **Changing the behaviour of All Models or Group chat.** Only their placement and tooltip change; the Window header's Group chat keeps the Chat header button's add-this-Fan action. Their parity-doc entries belong to Phase 7.
- **Idle mode (§1.3).** No Phase names it.

## Further Notes

- **The Window header term.** `CONTEXT.md` defines the Window header as holding all five buttons. Observation moves Online Fans and Notifications into the Fan List, and this spec calls that pair the "Fan List buttons". The plan review updated the glossary: the Window header entry carries an amended note, and "Fan List buttons" is a term in the Fan List section.

  ASSUMPTION: "Fan List buttons" is coined here for the Clone's `.big-btns` pair. Overturned if the glossary picks another name.
- **The online-subscribers route.** It already exists, `GET /api/of/v2/subscribers?online=1` (`service/server.py:5598`), so Online Fans needs no relay change.
- **Two SFW switches in-app.** In the app, the shell's top bar SFW and the Window header SFW are both on screen. They drive one store, so they cannot disagree. In a Pop-out window only the Window header's shows.

## Review

codex, 2026-10-12. Blind call (B) and draft call (D) against the sparse workspace at HEAD `231646e7`. Both runs exited 0 in 223s and 224s with fresh, non-empty output. Caveat: this spec is committed at HEAD (`c7f2b131`), so the blind call could have read it with `git show`. Its log has no `docs/spec` access, so it stayed blind in practice but not by construction.

- B1 Phase 1 changes workspace state (scope drives the Fan List and SSE, a Creator change clears the selection, mounting a Thread marks it read), and component tests miss that: **accept**. There are new page-level transition tests, and the Fan tabs section states that only one Thread is ever mounted.
- B2 alternatives are the plan's five-button header or the Clone's placement: **reject**. The spec already records the departure and flags it for veto ("Where Online Fans and Notifications go").
- B3 ScopeContext or a separate workspace selection, since SSE follows the scope: **partial**. ScopeContext stays (rung 5; Phase 0 already extends it). Creator tab counts are not tied to SSE: they poll every Creator every 60s (`useRosterCounts.ts:73`), and that is now stated. Fan tabs of Creators outside the scope read the cache only, which is already flagged. The falsifier (B's events while A is scoped) therefore hits only those tabs, by design.
- B4 a Fan tab could be a kept conversation or every selection, and row-click behaviour was unstated: **accept**. Only "Open in new tab" and a notification's open create a tab. A row click or a Deep link selects without adding one (`messages.js:2594`; story 20).
- B5 Thread lifecycle (mounting marks read, Composer state is local): **accept**. One Thread is mounted, keyed by Creator and Fan. Inactive tabs never mount, and drafts behave as today.
- B6 Online Fans could use the existing `/api/of/v2/subscribers?online=1`: **accept**. The spec's claim that the relay had no such route was false (`service/server.py:5598`). Online Fans now unions that list (one page of 50, scoped Creator) with the row rule.
- B7 the reused bell opens browser tabs and counts arrivals per browser tab: **accept**. The badge now reads `/api/of/v2/users/notifications/count` (merged with D5). Rows already called `onOpenFan`. The gap left outside Messages Pro is closed too (2026-10-26): a toast, a top bar or /notifications row, a Buys & tips row and an OS notification all open the Fan as a Fan tab in the Messages Pro window (the one named `messages-pro`), in place whenever its page is up (`app/lib/notificationLink.ts`). In the desktop app a Messages Pro link opened as a tab, and the native notification's click, go into that window (`desktop/lib/window-open.js`). Evidence: slop `inbox-unread`'s nine notification click checks.
- B8 one tab set per Employee or one per window: **reject**. Already decided (one set, synced by `storage`) and flagged.
- B9 Phase 0 (and its falsifier, a missing shared tree) is not in this checkout: **reject**. Phase 0 is a declared Depends on, and the reviewed tree predates it by construction.
- B10 the tab transition contract has gaps (closing a Creator that has Fan tabs, removed Creators, opening a 101st tab from a notification or Deep link): **accept**. Stories 48 and 49 are added, with matching decisions and tests.
- B11 identity boundaries (unresolved sign-in, malformed storage): **accept**. Nothing is read or written until identity resolves, and a malformed value reads as empty. Chatter-only sessions were already covered by the principal fallback.
- B12 lossless `(accountId, fanId)` identity: **reject**. It is already in Contracts (wire-spelled `fanId`, `fanIdFromParam`).
- B13 Creator membership against the All Models include list, session-less Creators and the active Creator floating first: **reject**. Each is already decided and flagged (no reshuffle, include list ignored, session-only picker).
- B14 unread, online and signal semantics: **partial**. The spec now says Creator unread counts unread conversations and that unknown presence shows the offline dot. The signal was already defined.
- B15 drafts and sends in flight: **partial**. Sends keep their own destination (`useSendMessage.ts:118`). Keeping drafts per tab is Out of Scope, because the plan does not ask for it.
- B16 the header's behaviour has no acceptance (picker, SFW sync, notification actions, Online Fans errors): **accept**. Tests are added (see D7). "View details" on withdrawn messages stays parked (floor 2).
- B17 navigation (back/forward, query preservation): **partial**. Activating a tab changes the selection only and not the URL, as row selection does today (`page.tsx:33`). The Creator window URL was already specified.
- B18 keyboard, touch and height: **partial**. Focus after ✕ and a `flex-1 min-h-0` pane grid are added. Keyboard reorder and context-menu keys were already specified.
- B19 do not delete the extras, and tell the overflow "+" apart from "+ Add a Creator": **reject**. The spec already follows ADR 0003, and the overflow has its own label and position.
- B20 test the workspace through rendered interactions, not isolated strips: **accept** (merged with D6).
- B21 a query/event test layer for inactive tabs: **partial**. Roster counts are already covered by `useInboxRealtime.roster.test.tsx`. Fan tabs outside the scope are cache-only by a flagged design, so no event test is added.
- B22 a browser layer (two windows, drag, focus): **partial**. Storage sync, drag, keys and focus are tested in vitest, and the Visual loop now shows real tabs (D9). No multi-window e2e is added: there is no harness for it (rung 5).
- B23 do not mount 100 Threads: **reject**. The spec never did, and it now says so.
- B24 the Clone's Fan tab strip was built at an operator's request (`messages.js:2543-2546`): **accept**. An ASSUMPTION now marks those Gap rows as Inflowwww's Geometry.
- B25 the harness is missing: **reject**. It is a Phase 0 output, listed in Depends on.
- D1 Phase 0 moves composition into the shared `MessagesPro`, so editing "the page" could miss the Deep link route: **accept**. Owns now names `MessagesPro`, and the page test covers both routes.
- D2 Group chat as a `/group` link loses the add-this-Fan action, and the Chat header button stays outside an overflow: **partial**. The Window header item now keeps `openGroupTab(accountId, fanId)` when a Fan is open. The Chat header button is Phase 3's to move (Phase 3 H13, Phase 7 story 11), so Phase 1 leaves it alone.
- D3 closing the last tab only when active contradicts the plan: **accept**. The plan line (`messages-pro-parity.md:91-92`) has no condition. Closing the last tab now always clears the Thread, and the old ASSUMPTION is removed.
- D4 the cache-only contract cannot supply the signal (🔥 needs `lastPpvPurchase`), and bare tabs are allowed: **partial**. Tabs now read Phase 2's `FanRow` facts, including the activity facts, through `rowBadges`, and tests seed those shapes. Fetching per tab is rejected because it fans out up to 100 reads (`page.tsx:76-81`); bare tabs of Creators outside the scope stay flagged.
- D5 the arrival counter is the wrong quantity when a count route exists: **accept**. The badge shows `all` from `/api/of/v2/users/notifications/count` for the scoped Creator (`service/server.py:5393`, `messages.js:2931-2944`) and is hidden under All Models.
- D6 the tests stop before integration (tab activation, close clamp, button mounted, Group chat in the Chat header): **partial**. Page tests now cover a cross-Creator tab click past the scope guard, both close clamps and the no-tab row click. The real-header mount is checked by the harness click (D9) and an Acceptance grep. Group chat in the Chat header is Phase 3's.
- D7 several stories have no test (SFW sync, warm-up, roster changes, URL reopen, remote close, the 5-minute boundary, a failed Reply): **accept**. Each is added to the CreatorTabs, FanTabs or page list.
- D8 the Acceptance block passes after a failed command: **accept**. It now starts with `set -e` and `cd` to the repo top (the Phase 2 spec's style).
- D9 the desktop shot never opens a Fan tab: **accept**. Phase 1 changes the harness's desktop state to open two tabs and check for them.
- D10 Phase 2 already owns the row menu, and the land-first fallback drops the signal: **accept**. Phase 1 reuses Phase 2's menu, story 41 moves to Phase 2, and the fallback is replaced by "re-cut the spec".
- Reconciler note (not a reviewer finding): the Phase 3 draft turns "↗ pop out" into "Open in new tab" (H9). The Chat header ASSUMPTION is restated so that Phase 3 places Phase 1's button in that slot.
- Reconciler note (not a reviewer finding): the Phase 3 draft also lists "Select any conversation to start". Phase 1 keeps it on the plan line (`messages-pro-parity.md:91-92`, rung 2), so for Phase 3 it is already done.

Counts: 17 accept, 10 partial, 8 reject, 0 needs-human.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: the quick reply (`:102`, `:152`) is work beyond the plan. **partial**: verified. The plan's Phase 1 line lists five buttons and no quick reply (plan:84-95), but the help centre documents it (`docs/infloww-screens.md:243`), and the plan's goal is element-for-element parity (rung 1). It stays specced, as the last separable ticket of this Phase (new "Quick reply ticket" note and ASSUMPTION).
- Green: hold the quick reply. **partial**: it is not held out of the spec. It lands last, so a short budget drops it first within this Phase.
- Red: the quick reply looks like churn. **partial**: same reconcile. It sends through the Composer's existing send hook and adds no relay route (Contracts), so the churn is one field and two test cases.
- Blue: park the quick reply for the human. **accept**: it is listed under "Needs the human" in `plan-review.md` as a veto.
- White: `CONTEXT.md:31-32` still lists five Window header buttons. **accept**: verified. The glossary entry has a 2026-10-12 note, "Fan List buttons" is a new term, and Further Notes and the placement ASSUMPTION now point to them.
- Green: Phase 1 lands after Phase 2. **accept**: this agrees with Depends on (`:318`). Phase 1 is Wave 2, after Phase 2's core.
