# Phase 03 — Chat header and message list

**Objective.** The Thread's Chat header and message list have the Clone's elements, order, labels and Geometry. Every Chat header action either calls an existing relay route or renders as Not wired. The Inflowwww extras that used to sit in the header are moved behind the Legacy flag or into the Chat header's Extras overflow.

## Gap table

Sources: `ui-redesign/infloww-exact/messages.html` (the current Clone, cited as `m.html:N`), `messages.js` (`m.js:N`), and the original screenshot build of the same file at commit `4e83397` (`orig:N`, read with `git show 4e83397:ui-redesign/infloww-exact/messages.html`). `orig` is the Clone before it was rewired, so its labels are the closest copy of the Infloww screenshot. Ours: `app/components/chat/ChatSurface.tsx` (`CS:N`), `MessageList.tsx` (`ML:N`), `ChatActionsMenu.tsx` (`CAM:N`), `Composer.tsx` (`CMP:N`), and `app/app/messages-pro/page.tsx` (`PG:N`). `_shared/components.html` is the fx- kit for our own pages and has no Chat header or bubble snippet. Colours never come from the Clone (ADR-0001). Every colour named below is a token from `app/app/globals.css`.

### Chat header

| # | Clone selector → values | Ours | Gap | Change |
|---|---|---|---|---|
| H1 | `.thread-head` `m.html:201,350`: flex row, align center, gap 14px, padding 12px 18px, border-bottom 1px, min-height 58px, nowrap | `CS:878`: `px-3 md:px-4 py-3`, `gap-2 md:gap-3`, `flex-wrap md:flex-nowrap`, no min-height | padding-x is 16 instead of 18, gap is 12 instead of 14, no min-height | From md up, `ChatHeader` uses padding 12/18, gap 14 and min-height 58. Below md it keeps today's wrap (house precedent, `docs/routes.md:42`) |
| H2 | `.back` `m.html:202`, `orig:499`: 22×22 chevron SVG, shown at every width | `CS:880-889`: 36×36 "‹" glyph, `lg:hidden` | size and glyph differ; the Clone shows it on desktop too | Use the 22px chevron SVG. It stays below lg only (ASSUMPTION F15) |
| H3 | none; the Clone header has no avatar. §3.3 C[H262067]: "Click the avatar for…" | `CS:898`: 36px avatar inside a button that opens Fan insights | the click opens Fan insights instead of the Avatar menu | The 36px avatar opens `FanAvatarMenu` (F16) |
| H4 | `.th-id` `m.html:203`: column, gap 2px, margin-right 6px. `.th-name` `m.html:205,351`: 700 16px, nowrap | `CS:912`: `font-medium text-sm` (500 / 14px), truncate | weight 500 instead of 700, 14px instead of 16px | Name at 700 / 16px, nowrap with ellipsis |
| H5 | `.th-status` `m.html:206-209,353`: 12px, gap 6px, 8px dot; online is the green dot, `.off` is muted. Texts are "Available now" (`orig:505`), "Last seen …" or "Offline" (`m.js:839-848`, online = seen within 5 min) | `CS:913-915`: 11px "@username · Creator" | no presence line | Status line at 12px with an 8px dot. Online uses `ok`, off uses `fg-dim`. "@username · Creator" moves into the name's tooltip (F17) |
| H6 | `.th-tools` `m.html:210-212`: gap 4px. `.icon-btn` 30×30, SVG 19px. Order: star, mute, notes, pin (`m.html:697-700`, `orig:508-511`) | absent | four icons missing | Add star, mute, notes, pin in that order. Mute is wired. Star, pin and notes behave as F3 and F23 describe |
| H7 | `.th-tools .lbl` `m.html:213-215`: 13px, gap 6px, padding 6px 8px, radius 7px, SVG 17px. Labels "Gallery", "Find" (`m.html:701-702`) | Find is "🔍 search", 11px underlined (`CS:949-960`). Gallery is absent | label, size and icon differ; Gallery missing | "Gallery" opens `ChatGallery`. "Find" toggles the existing `ChatSearch` |
| H8 | `#tbModel` after Find, `m.html:703` (ours per §3.3) | `CS:1004-1006`: `ModelInfoButton` always shown from md up | an automation extra shown with the flag off | Persona button renders only when `useLegacyAutomations()` is true, placed after Find |
| H9 | `.th-right` `m.html:216`: margin-left auto, gap 4px. `.open-new` `m.html:217-218,352`: accent text, 13px / 600, gap 6px, padding 6px 8px, radius 7px, SVG 16px. Label "Open in new tab" with an external-link icon (`orig:516`). The current Clone relabels it "Pop out" and pins a tab (`m.html:707`, `m.js:2588-2596`, commit `5949d64`) | `CS:978-992`: "↗ pop out", 11px underlined, `hidden md:inline`, opens `/messages-pro/<acc>/<fan>` in a new browser tab | wrong label and size; opens a page, not a Fan tab | "Open in new tab" is Phase 1's `OpenInNewTabButton`: it adds or focuses this Fan's Fan tab, and at the cap it is disabled with "Fan tab limit reached (100)". It takes these values and is hidden below md (F1, F14) |
| H10 | `#tbRefresh` `m.html:708`: `.icon-btn` 30×30, refresh SVG 19px | `CS:995-1003`: "↻ refresh" text, 11px, `hidden md:inline-flex` | text instead of an icon | Icon-only at 30×30, keeps the spin while refreshing, stays hidden below md |
| H11 | `#tbKebab` `m.html:709`: vertical three-dot SVG, `.icon-btn` 30×30, last in the row | `CS:1019-1027`: horizontal "⋯" glyph, `text-lg` | glyph and size differ | Vertical dots at 30×30, last in `.th-right` (Phase 0's Fan insights toggle stays before it) |
| H12 | `#schedChip` in `.th-right`, `m.html:706` (ours per §3.3) | `CS:930`: `ScheduledForChat` in the header row | an extra in the header row | Moves into the Chat header's Extras overflow (ADR-0003) |
| H13 | none (ours) | `CS:994`: `GroupChatButton` "👥 group"; `CS:933-948`: "👁 focus" on phone; `CS:961-977`: "🌐 translate" | extras displace Infloww elements | Group chat and focus move into the Extras overflow (F10). The 🌐 translate toggle is removed, because Phase 4's Translator in the Composer toolbar drives the same translate mode (F12) |
| H14 | `.ai-strip` `m.html:475-476,713`: a band under the header, padding 7px 18px, 11.5px, border-bottom 1px (ours per §3.3) | `CS:919-923`: inside the name button, flag-gated | wrong position | With the flag on, `ChatHeader` renders it as a band under its row, inside the Region. With the flag off, it does not render (as today) |
| H15 | none. `docs/routes.md:42` gives the "Fan insights" slide-over below lg, and Phase 0 makes the "Fan insights" button a toggle at every width with `aria-expanded` | `CS:1008-1018`: Info button, `lg:hidden`, 40×40 | none once Phase 0 lands | Keep Phase 0's toggle, visible at every width, before the kebab (F16) |
| H16 | none; §3.3 C[H262067]: "📈 by the creator name opens 'Mass message statistics' / 'Online fans message statistics'" | absent | missing | `MessageStatsLink` is a 30×30 📈 button that opens a two-item menu. "Mass message statistics" opens `/growth/smart-messages`, and "Online fans message statistics" is Not wired (F7) |
| H17 | none; §3.3 C[H262067]: "Chat link: copy a link that deep-links into the app" | absent | missing | Add "Copy chat link" to the Kebab menu (F6) |

### Menus and sheets

| # | Clone selector → values | Ours | Gap | Change |
|---|---|---|---|---|
| M1 | `.pop` `m.html:361`: min-width 238px, max-width 360px, max-height 72vh, radius 10px, padding 6px, 13px. `.prow` `m.html:364`: gap 9px, padding 8px 10px, radius 7px. `.phead` `m.html:370`: 10.5px / 700, uppercase, padding 8px 10px 4px. `.pdiv` `m.html:371`: 1px, margin 5px 2px | `CAM:228`: `min-w-[220px]`, `rounded-lg` (8px), `py-1`. `CAM:339`: `px-3 py-3 md:py-1.5 text-sm md:text-xs` (12px on desktop) | min-width 220 instead of 238, radius 8 instead of 10, rows are 12px with 12px padding instead of 13px with 8/10 padding | The Kebab menu, Avatar menu, Extras overflow and 📈 menu all use the `.pop`, `.prow`, `.phead` and `.pdiv` values. Phone rows keep `py-3` for touch (F14) |
| M2 | Kebab contents. Infloww C[H262067]: "restrict", "block", "report", "hide chats", "mute notifications". The rewired Clone menu (`m.js:2733-2753`) also has Mark as unread, Group view, Re-scrape, mass-message opt-out, Restrict automations and Lists, all ours | `CAM:231-305`: Mark as unread, Mute, Hide, Restrict from automations, MASSppvEXCLUDE, MASSdmEXCLUDE, Restrict on OnlyFans, Add to list ▸ | wrong order, Infloww's Block and Report are missing, ours are mixed in | Rows in help order: Restrict, Block, Report (Not wired), Hide chats, Mute notifications. Restrict and Block confirm first (F24, F27). Then a divider and "Copy chat link". The non-automation extras (Mark as unread, the two MASS toggles) move to the Extras overflow. With the flag on only, a second divider and the automation-restrict row ("Restrict from automations" / "Allow automations", or the disabled "Auto-restricted", as today at `CAM:250-263`) come last (F10). Lists move to the Avatar menu |
| M3 | none; §3.3 C[H262067]: "Subscription status", "Earnings", "Special offers", add-to-lists | absent. The lists submenu is `ToggleListsSubmenu`, `CAM:347` | missing | New `FanAvatarMenu` with those four rows. "Add to lists ▸" reuses `ToggleListsSubmenu`. "Special offers" is Not wired (F4) |
| M4 | `.sheet` `m.html:383`: width min(900px, 92vw), max-height 84vh, radius 14px. `.sheet-h` `m.html:385`: padding 13px 16px, 700 / 14px. `.mgrid` `m.html:390`: grid `repeat(auto-fill,minmax(118px,1fr))`, gap 10px. `.mt` `m.html:391`: radius 9px, aspect 1, border 1px. `.tag` `m.html:393`: price at left/bottom 6px, radius 6px, padding 2px 6px, 10.5px / 700. Title "Chat gallery", "↻ Refresh", empty "No media in this chat" (`m.js:2610-2618`) | none. FanDrawer's purchased-only list is not a gallery | missing | New `ChatGallery` sheet with those values. Below md it is full-screen (F14) |
| M5 | Find popover `m.js:2643-2648`: anchored `.pop`, head "Search this conversation", placeholder "word or phrase…" | `CS:1039-1050`: `ChatSearch` panel under the header | a panel instead of an anchored popover | Keep the panel (plan: "Find reuses ChatSearch"). Recorded as `VISUAL GAP` (F9) |

### Message list

| # | Clone selector → values | Ours | Gap | Change |
|---|---|---|---|---|
| L1 | `.thread-body` `m.html:220`: padding 22px 26px, column, gap 14px | `ML:405`: `px-2 md:px-4 py-3 space-y-2` (8/16 × 12, gap 8) | padding and gap are smaller | From md up: padding 22/26, gap 14. Phone keeps today's values (F25) |
| L2 | `.bubble` `m.html:243-246`: max-width 60%, padding 11px 15px, radius 16px, 14.5px / 1.45, tail corner 5px (`.in` bottom-left, `.out` bottom-right) | `ML:672`: `max-w-[88%] md:max-w-[75%]`. `ML:763-766`: `px-3 py-2` (12/8), `rounded-2xl` (16), `text-sm` (14/20), `rounded-br-md` / `rounded-bl-md` (6) | max-width 75 instead of 60, padding 8/12 instead of 11/15, font 14 instead of 14.5, tail 6 instead of 5 | From md up: 60%, 11/15, 14.5 / 1.45, 5px tail. Phone keeps 88% (F25). Fills stay `accent` / `bg-elev-1` |
| L3 | `.bubble .btime` `m.html:244`: inside the bubble, block, 11px, margin-top 5px, 50% white on `.in`, 70% on `.out` | `ML:904-913`: a meta row under the bubble, 10px | outside instead of inside, 10px instead of 11px | Time, receipt and "Sent by" move into an in-bubble time row at 11px. Our status controls (sending…, failed — retry, scheduled, cancel) stay in the row under the bubble, because the Clone has none of them |
| L4 | `.seen-tick` `m.html:261,263`: "✓" sent, "✓✓" seen (`m.js:896,900-910`), 10px, margin-left 5px, opacity .6, seen brighter | `ML:919-925`: "✓ delivered" / "✓✓ seen" text | words instead of glyphs | Glyph only, at 10px. Tooltip and accessible name are "Delivered" or "Seen". Seen uses the `info` token. The read pointer is the newer of the `chat` prop and the live chat cache (F28) |
| L5 | `.sent-by` `m.html:262`: inside `.btime`, 10px / 700, margin-left 7px, nowrap. Title "Sent by <name>" (`m.js:918-925`) | `ML:958-975`: "Sent by X" on its own reserved line under the bubble | separate line instead of inline | "Sent by <name>" goes inline in the time row. The anti-reflow placeholder line is removed, because the time row always exists |
| L6 | `.ppv-mini .paid-tag` `m.html:250`: 12px / 600, "$X.XX · paid" or "· not paid" (`m.js:884-890`). Original `.msg-meta` `orig:196`, markup `orig:640`: 12.5px muted "$35.00 · not paid · 4:46 am" | `ML:743-757`: 10px chip "🔒 $X locked" / "✓ $X unlocked" | wording and size differ | A status line at 12px / 600: "$X.XX · paid" in `ok` or "$X.XX · not paid" in `fg-dim`. Paid means `isOpened || isPaid` (unchanged rule, `ML:658`) |
| L7 | `.unlock-btn` `orig:187-188`, markup `orig:630`: absolute, left/right/bottom 20px, height 52px, radius 9px, 700 / 15px, letter-spacing .4px, accent, "UNLOCK FOR $35". [PAL] calls it the "UNLOCK PPV btn" | absent | missing | An outgoing PPV that is not paid shows a display-only accent bar "UNLOCK FOR $<price>" under its media at those values (F20) |
| L8 | Message-list empty: `.msg-meta` "No messages yet" (`m.js:966`), 12.5px muted (`m.html:241`) | `ML:364-369`: "No messages yet.", 14px, centred | trailing period, 14px instead of 12.5px | "No messages yet" at 12.5px in `fg-dim` |
| L9 | Thread empty: `.empty` `m.html:287-289`: gap 22px, 130px send icon, 26px text "Select any conversation to start" (`m.html:719-722`) | `PG:216-218`: "Pick a conversation on the left.", 14px | wrong text and size | Phase 1 owns it: its spec builds and tests this state and greps for the label. This Phase changes nothing here (F22) |
| L10 | `.reply-strip` `m.html:525-530`: gap 9px, padding 8px 12px, margin-bottom 8px, border-left 3px, radius 8px, 13px; ↩ SVG 15px; text one line with ellipsis; ✕ 22×22, radius 6px, 14px. Text "Replying to: " + quote (`m.js:1919`) | `CMP:509-523`: two lines, 11px, "Replying to {author}" + preview, `px-2.5 py-1.5` | wording, layout and size differ | New `ReplyStrip`: one line, "Replying to: <preview>", ↩ icon, ✕ "Cancel reply". `Composer` renders it in the same slot (F26) |

### Not wired (to be listed in the Phase result)

Evidence: the relay route list in `service/server.py` (`grep -nE '@app\.(post|put|patch|delete)\("/api/of/v2/' service/server.py`).

- **Star (Priority).** There is no route that sets or clears Priority on a chat. Only the read filter `GET /api/of/v2/chats?filter=priority` exists (`app/hooks/useChatList.ts:44`).
- **Pin (Pinned chat).** There is no route that pins a chat. `PATCH /api/of/v2/lists/{id}/pin-chat` (`server.py:4537`) pins a list as a Chat folder, and `POST /api/of/v2/messages/{id}/pin/user/{uid}` (`:6223`) pins a message. Neither one pins a chat.
- **Report.** There is no `/report` route anywhere in `service/`.
- **Special offers (Avatar menu).** There is no per-Fan offers route. `GET /api/of/v2/promotions` (`:5956`) is the Creator's campaign list.
- **Online fans message statistics (📈 menu).** No view shows statistics for online-fans blasts on their own. `/growth/smart-messages` opens on its Mass tab from component state, with no URL parameter (`app/components/growth/SmartMessagesPage.tsx:32-34`), and `MassMessagesTab.tsx:546` only labels `online_blast` rows.

Wired, contrary to the plan's parenthetical (F2): Restrict (`POST/DELETE /api/of/v2/users/{id}/restrict`, `:6568`, `:6626`), Block (`POST/DELETE /api/of/v2/users/{id}/block`, `:6559`, `:6564`), and Hide chats (`POST /api/of/v2/chats/{id}/hide`, `:6301`). Mute (`:6292`, `:6297`) is wired too.

## Problem Statement

An Employee who knows Infloww opens a Thread in Inflowwww and cannot find the Chat header they expect. The Fan's presence is missing, and in its place is an "@username · Creator" line. There is no star, mute, notes or pin icon, and no Gallery. Find is an underlined "🔍 search" link, pop-out and refresh are small text links, and the kebab is a horizontal "⋯" whose menu mixes our own tools (MASS excludes, automation restrict, Mark as unread) with Infloww's actions. Block and Report are missing from it. Our extras (Persona button, Scheduled chip, Group chat, focus, translate) take the places where Infloww's controls should be, and the Persona button shows even when the Legacy flag is off. The avatar opens Fan insights instead of Infloww's Avatar menu. The message list is close but not the same: bubbles are wider and tighter, time and "Sent by" sit under the bubble, receipts are spelled out in words, PPV status is a small "locked/unlocked" chip, there is no "UNLOCK FOR $X", and the reply strip and empty states use other words.

## Solution

The Thread opens with Infloww's Chat header: a back chevron (phone), the Fan's avatar (which opens the Avatar menu), name and presence ("Available now", "Last seen …" or "Offline"), then star, mute, notes, pin, "Gallery", "Find". On the right are 📈, "Open in new tab", refresh, the Fan insights toggle and the vertical kebab. The kebab holds restrict, block, report, hide chats and mute notifications, plus "Copy chat link". Each action either calls the relay route that already exists or shows as disabled with the tooltip "not wired". It never pretends to succeed. Our extras sit in a "+" Extras overflow after Find, each with an "Inflowwww extra" tooltip. The Persona button and the AI strip appear only with the Legacy flag on. The message list takes the Clone's bubble Geometry, puts the time, ✓/✓✓ and "Sent by …" inside the bubble, shows "$X · paid / not paid", and shows "UNLOCK FOR $X" on unpaid PPVs. The reply strip reads "Replying to: …" with ✕. An empty conversation reads "No messages yet".

## User Stories

1. As an Employee, I want the Chat header to show the Fan's name in bold, so that I can see at a glance who I am talking to.
2. As an Employee, I want a presence line that reads "Available now" with a green dot when the Fan is online, so that I know a reply may land right away.
3. As an Employee, I want the presence line to read "Last seen <time ago>" when the Fan is offline, so that I can judge how fresh the conversation is.
4. As an Employee, I want the presence line to read "Offline" when no last-seen time is known, so that I am never shown a made-up time.
5. As an Employee, I want the Fan's username and Creator in the name's tooltip, so that I can still check them without the header showing a second line.
6. As an Employee, I want the icon row in Infloww's order (star, mute, notes, pin, Gallery, Find), so that muscle memory from Infloww works here.
7. As an Employee, I want the star icon to show as disabled with the tooltip "not wired", so that I know Priority cannot be set from here yet and nothing pretends it was.
8. As an Employee, I want the mute icon to mute or unmute this chat's OnlyFans notifications and to show its current state, so that I can silence a noisy Fan in one click.
9. As an Employee, I want the notes icon to open Fan insights with the Fan notes field focused, so that I can read or write Fan notes without hunting for them.
10. As an Employee, I want the pin icon to show as disabled with the tooltip "not wired", so that I know pinning a chat is not available yet.
11. As an Employee, I want "Gallery" to open a "Chat gallery" sheet of all media exchanged with this Fan, with prices on paid items and "Load more" for older media, so that I can see everything that was sent and bought.
12. As an Employee, I want the gallery to show "No media in this chat" when there is none, the relay's error when it fails, and a "↻ Refresh" that re-pulls it, so that an empty or stale gallery is never mistaken for a broken one.
13. As an Employee, I want "Find" to open the existing conversation search, so that I can jump to an old message.
14. As an Employee, I want a 📈 button whose menu opens "Mass message statistics", so that I can check how my blasts performed without leaving Messages Pro.
15. As an Employee, I want "Online fans message statistics" in that menu to show as disabled with the tooltip "not wired", so that I am not sent to a view that does not exist.
16. As an Employee, I want "Open in new tab" to add this Fan to my Fan tabs (or focus the tab if it is already there), and to show as disabled with "Fan tab limit reached (100)" when I already have 100, so that I can juggle conversations as in Infloww and no click is silently ignored.
17. As an Employee, I want the refresh icon to re-pull this chat and the Fan and to spin while it works, so that I can force fresh data.
18. As an Employee, I want the vertical kebab to list Restrict, Block, Report, Hide chats and Mute notifications in that order, so that Infloww's Fan actions are where I expect them.
19. As an Employee, I want Restrict and Lift restrict to ask for confirmation and then toggle the Fan's OnlyFans restrict through the existing route, without sending the Fan any message, so that the action really happens and nothing I did not ask for reaches the Fan.
20. As an Employee, I want Block to ask for confirmation and then block the Fan through the existing route, so that I cannot block someone by accident.
21. As an Employee, I want Report to show as disabled with the tooltip "not wired", so that I am not misled into thinking a report was filed.
22. As an Employee, I want Hide chats to hide this chat until the Fan writes again, so that dead threads leave my Fan List.
23. As an Employee, I want "Mute notifications" in the kebab to act on the same state as the mute icon, so that the two never disagree.
24. As an Employee, I want "Copy chat link" to copy a Deep link to this Fan, so that I can send a teammate straight to the conversation.
25. As an Employee, I want each kebab action to report success or the relay's error in the menu, so that I know what happened.
26. As an Employee, I want clicking the Fan's avatar to open the Avatar menu, so that I can reach the Fan's account facts as in Infloww.
27. As an Employee, I want "Subscription status" in the Avatar menu to show the Fan's subscription state, or "—" when we do not have it, so that I see facts and never guesses.
28. As an Employee, I want "Earnings" in the Avatar menu to show what the Fan has paid this Creator, or "—" when unknown, so that I can pitch at the right level.
29. As an Employee, I want "Special offers" to show as disabled with the tooltip "not wired", so that I know it is not available yet.
30. As an Employee, I want "Add to lists ▸" in the Avatar menu to add or remove the Fan on the Creator's lists, so that list management sits where Infloww puts it.
31. As an Employee, I want our extras (Scheduled, Group chat, Mark as unread, MASS excludes, focus) in a "+" Extras overflow, each with an "Inflowwww extra" tooltip, so that I can still use them without them crowding Infloww's controls.
32. As an Employee with the Legacy flag off, I want no Persona button, no AI strip and no "Restrict from automations" anywhere in the Thread, so that automation surfaces stay hidden.
33. As an Employee with the Legacy flag on, I want the Persona button after Find, the AI strip as a band under the header, and "Restrict from automations" as the last Kebab row after a divider, so that the automation tools come back.
34. As an Employee on a phone, I want the header to wrap into a second icon row and to hide "Open in new tab" and refresh, so that the header fits 390px without sideways scrolling.
35. As an Employee on a phone, I want the back chevron to return to the Fan List and the Fan insights toggle to open the slide-over, so that the one-pane-at-a-time rules in `docs/routes.md` still hold.
36. As an Employee at any width, I want the Fan insights toggle to stay in the Chat header and to open or close Fan insights, so that the avatar opening the Avatar menu never costs me my way into Fan insights.
37. As an Employee, I want message bubbles with the Clone's width, padding, radius and tail, so that the thread reads like Infloww's.
38. As an Employee, I want each bubble's time inside the bubble, so that I can scan times without extra lines.
39. As an Employee, I want my outgoing bubbles to show ✓ when delivered and ✓✓ when the Fan has read them, including when the Fan reads them while I have the Thread open, so that I know whether the Fan saw my message.
40. As an Employee, I want outgoing bubbles to show "Sent by <name>" in the time row when we know the sender, so that I can tell teammates' and automations' messages apart.
41. As an Employee, I want each PPV to show "$X.XX · paid" or "$X.XX · not paid", so that I can see at a glance whether it sold.
42. As an Employee, I want an unpaid PPV I sent to show the "UNLOCK FOR $X" bar the Fan sees, so that I can read the thread the way the Fan does.
43. As an Employee, I want clicking ↩ on a bubble to show a strip above the Composer reading "Replying to: <quote>" with ✕, so that I know my next send is a reply.
44. As an Employee, I want ✕ on the reply strip to cancel the reply, so that I can back out of quoting.
45. As an Employee, I want an empty conversation to say "No messages yet", so that an empty thread is clearly empty and not still loading.
46. As a maintainer, I want every Chat header and message-list size to come from the Messages Pro token module, so that the Geometry pass (Phase 6) changes numbers in one place.
47. As a maintainer, I want the Phase result to list every Not wired control with its reason, so that missing relay routes are visible work.

## Implementation Decisions

- **Owns.**
  - `ChatHeader` (new): the Chat header Region, including the flag-gated AI strip band under its row.
  - `ChatActionsMenu` (modified): becomes the Kebab menu.
  - `FanAvatarMenu` (new): the Avatar menu. It takes over `ToggleListsSubmenu` from `ChatActionsMenu`.
  - `ChatHeaderExtras` (new): the Chat header's Extras overflow.
  - `ChatGallery` (new): the Gallery sheet.
  - `MessageStatsLink` (new): the 📈 button and its menu.
  - `ReplyStrip` (new): the reply strip, plus `quoteFromMessage`, moved out of `ChatSurface`'s quote builder unchanged.
  - `MessageList` (modified): bubbles, time row, receipts, PPV status, unlock bar, empty text, and the exported `newestReadPointer` (F28).
  - `ChatSurface` (modified): mounts `ChatHeader` and `ChatSearch`, wires the callbacks, owns the `focusNotesRequest` counter (F23), drops the header's 🌐 translate toggle (F12), and passes `newestReadPointer(chat.lastReadMessageId, liveChat?.lastReadMessageId)` to `MessageList` (F28). Its quote state and send path (`ChatSurface.tsx:713-719`, `:1105-1157`) are unchanged.
  - `Composer` (modified): one slot only. It renders `ReplyStrip` where the inline quoted block was (`Composer.tsx:509-523`). Its `quoted` and `onClearQuoted` props and its send logic are unchanged.
  - `useFanChatMedia` (modified, additive): an option to include both directions, which joins the query key (F29).
  - `app/app/messages-pro/windowed.test.tsx` (modified): Phase 0's case 7 is rewritten for the Chat header this Phase builds (Testing Decisions, seam 4).
  - `FanDrawer` (modified): one prop, `focusNotesRequest`, that focuses its own Fan notes field (F23).
  - The Messages Pro token module in `app/lib/` (the plan's `messagesPro.ts`): this Phase writes its `chatHeader` and `messageList` sections (F13).

- **Interfaces.**
  - `ChatHeader` takes props. It renders the Region and owns the open state of the Avatar menu, Kebab menu, Extras overflow, 📈 menu and Gallery, and the shared mute state. It is given:
    ```ts
    { accountId: string; fanId: FanId; chat: OFChatItem;
      onBack?: () => void;                       // phone back (existing)
      findOpen: boolean; onToggleFind: () => void;
      refreshing: boolean; onRefresh: () => void; // existing handleRefresh
      onOpenNotes: () => void;                   // open Fan insights, focus Fan notes (F23)
      insightsOpen: boolean; onToggleInsights: () => void; // Phase 0's toggle, every width
      extras: { focusMode: boolean; onToggleFocus: () => void } }
    ```
    It reads presence and avatar-menu facts from `useOFUser` and `chat`, and reads the flag with `useLegacyAutomations()`. For "Open in new tab" it renders Phase 1's `OpenInNewTabButton({accountId, fanId, name})`.
  - `ChatActionsMenu({accountId, fanId, chat, onClosed, muted, onToggleMute})`. Its rows become Restrict, Block, Report, Hide chats, Mute notifications, a divider, and Copy chat link. With the flag on, a second divider and the automation-restrict row follow, and that row keeps its mutation and its "Auto-restricted" state unchanged (`CAM:250-263`). The mute row reads `muted` and calls `onToggleMute`. The mutations for Mark as unread and the MASS excludes move to `ChatHeaderExtras` unchanged.
  - `FanAvatarMenu({accountId, fanId, onClosed})`.
  - `ChatHeaderExtras({accountId, fanId, chat, focusMode, onToggleFocus})` renders `ScheduledForChat`, the Group chat action, Mark as unread, the two MASS toggles and focus (below lg only), in both flag states.
  - `ChatGallery({accountId, fanId, onClose})`.
  - `MessageStatsLink()` has no props.
  - `ReplyStrip({quoted: QuotedReply, onCancel})`. `quoteFromMessage(msg): QuotedReply`. `QuotedReply` moves with it, and `ChatSurface` re-exports it.
  - `MessageList` props are unchanged. `newestReadPointer(a?: number | null, b?: number | null): number | null` returns the larger of the two, or the one that is set.
  - `FanDrawer` gains `focusNotesRequest?: number`.
  - `useFanChatMedia(accountId, fanId, opts)` gains `opts.creatorOnly?: boolean`, default `true`, which is today's behaviour. `false` omits `from_user` (F8). The value joins the query key.

- **Schema.** None.

- **Contracts.** Every route is existing. This Phase adds no relay route and changes nothing in `service/`.
  - `GET /api/of/v2/users/{fanId}` (presence `lastSeen`, `subscribedOnData`, `isRestricted`)
  - `POST /api/of/v2/users/{fanId}/restrict?ack=false` and `DELETE /api/of/v2/users/{fanId}/restrict` (F27)
  - `POST|DELETE /api/of/v2/users/{fanId}/block`
  - `POST /api/of/v2/chats/{fanId}/hide`
  - `POST|DELETE /api/of/v2/chats/{fanId}/mute`
  - `GET /api/of/v2/chats/{fanId}/media` (Gallery: no `purchased`, no `from_user`, paged by `last_id`)
  - `GET /api/of/v2/chats/folders` and `POST|DELETE /api/of/v2/lists/{id}/users/{fanId}` (Add to lists)
  - `GET /api/of/v2/chats/{fanId}/messages/search` (Find, unchanged)
  - "Copy chat link" writes `${location.origin}/messages-pro/${encodeURIComponent(accountId)}/${encodeURIComponent(String(fanId))}` with `navigator.clipboard.writeText`. That is the same path the old pop-out used (`CS:979`), and it becomes the Deep link under Phase 0.
  - "Open in new tab" is Phase 1's `OpenInNewTabButton`, which calls `useFanTabs().open`.
  - Notes uses no DOM id. `onOpenNotes` opens Fan insights and increments `focusNotesRequest` (F23).

- **Not wired rendering.** A Not wired control is a button with `aria-disabled="true"`, the title "not wired" and a no-op click. It is not a native `disabled` button, so the tooltip still shows on hover (F19). The set is Star, Pin, Report, Special offers and Online fans message statistics. Each is named in the Phase result.

- **Order in the header, left to right.**
  - Phone only: back.
  - avatar, name and status.
  - Star, mute, notes, pin, Gallery, Find.
  - Persona button (flag on only).
  - "+" Extras overflow.
  - Then right-aligned: 📈, Open in new tab (from md), refresh (from md), Fan insights toggle, kebab.
  - With the flag on, the AI strip band sits under the row, inside the Region.

- **Kebab actions.** Each row keeps today's mutation, cache invalidation and status line from `ChatActionsMenu`: Restrict and Lift restrict (`CAM:194-222`, with `?ack=false` added to the POST), Hide chats (`CAM:113-124`) and Mute (`CAM:94-103`). Block is new and has the same shape: POST or DELETE, then invalidate `["of-user", accountId, fanId]`. A resolved call shows the row's success text and a rejected call shows the relay's error message, both in the menu's status line (`CAM:63-66`). Restrict and Block ask `window.confirm` first (F24). The Thread stays open after Hide chats, as today.

- **Menus.** The Kebab menu, Avatar menu, Extras overflow and 📈 menu each close on an outside pointerdown or Escape, as `CAM:50-61` does today.

- **Mute** has one mutation and one state, owned by `ChatHeader` and given to the mute icon and to the Kebab row. The state starts from `chat.isMutedNotifications` and flips when the call succeeds, as `CAM:94-103` does today.

- **Presence.** Online when `chat.isOnline === true`, or when `lastSeen` is within 5 minutes (the Clone's rule, `m.js:841`). Otherwise "Last seen" uses the existing `fmtAgo` from `app/lib/format.ts`. With no `lastSeen` at all it reads "Offline".

- **Avatar menu values.**
  - "Subscription status" is `subscribedOnData.status`. When that is absent but `expiredAt` is in the past, it reads "Expired".
  - "Earnings" is `subscribedOnData.totalSumm` formatted as dollars.
  - Missing values render as "—" (F5).

- **📈 menu.** "Mass message statistics" opens `/growth/smart-messages` in a new browser tab. "Online fans message statistics" is Not wired (F7).

- **Gallery** reuses `MediaTile` for every tile and the `fan-chat-media` query through `useFanChatMedia(accountId, fanId, {purchased: false, creatorOnly: false, limit: 30})`. "Load more" under the grid fetches the next page while there is one. "↻ Refresh" refetches the query. A failed request shows the relay's error and "↻ Refresh" in place of the grid. Tiles have no click action, the same as the Clone gallery (F29).

- **PPV unlock bar.** It is display-only on outgoing PPVs that are not paid. It sits under the media strip so the T-GRID tile boxes (`MediaGrid.test.tsx`) do not change. It carries the tooltip "What the Fan sees until they pay".

- **Extras.** Each row in the Extras overflow has the tooltip "Inflowwww extra". The "+" itself has the title "Inflowwww extras".

- **Geometry and colour.** Region numbers come from the token module (F13), and colours come only from `globals.css` tokens (ADR-0001). Below md, the header and bubbles keep today's phone values, because the Clone has no phone layout (F14, F25).

## Testing Decisions

There are four seams. All are public component interfaces. The first two are named by the plan's Acceptance, the third is the existing `FanDrawer` test, which is where the notes icon's effect can be seen, and the fourth is Phase 0's windowed test, whose case 7 this Phase takes over. A test renders the component under `renderWithProviders` (`app/test-utils.tsx`) and asserts what the Employee sees: roles, accessible names, text, focus, `aria-disabled`, `aria-expanded`, `title`, and the relay calls made. It never asserts internal state.

1. **`ChatHeader`**, in `app/components/chat/ChatHeader.test.tsx` (new). The relay is mocked with `vi.mock("@/lib/relay", …)` (precedent: `app/components/MoneyRail.render.test.tsx:38`), the flag is set through `FlagsProvider` (`app/contexts/FlagsContext.tsx`), and `navigator.clipboard` and `window.confirm` are stubbed. It covers:
   - **Icon order:** the accessible names in DOM order match the header order above, with the flag off and with it on (the Persona button appears after Find only when on).
   - **AI strip:** the band renders under the row with the flag on and is absent with it off.
   - **Status line:** "Available now", "Last seen …" and "Offline".
   - **Kebab:** the five rows in order. Report has `aria-disabled` and the title "not wired" and makes no relay call. Restrict confirms and then POSTs `/users/{id}/restrict?ack=false`. A declined confirm makes no call. Block confirms, then POSTs. Hide POSTs. A resolved call shows the row's success text, and a rejected call shows the relay's error message in the menu. Copy chat link writes the Deep link. With the flag off, nothing follows Copy chat link. With the flag on, a divider and "Restrict from automations" follow it, and a mocked automation-set restrict shows the disabled "Auto-restricted" row there instead.
   - **Avatar menu:** the four rows. Special offers is Not wired. "Add to lists ▸" lists folders from the mocked `/chats/folders`, and clicking a folder POSTs `/lists/{id}/users/{fanId}`, or DELETEs it when the Fan is already on that list.
   - **Star and pin:** Not wired, and clicking them makes no relay call.
   - **Mute:** the icon and the kebab row show one state and POST/DELETE `/chats/{id}/mute`.
   - **Gallery:** opens "Chat gallery" with one tile per mocked media item and the price tag. The request carries no `from_user` and no `purchased`. "Load more" requests the next page with `last_id`. An empty list shows "No media in this chat", and a failed request shows the error and "↻ Refresh".
   - **📈:** "Mass message statistics" targets `/growth/smart-messages`. "Online fans message statistics" is Not wired.
   - **Open in new tab:** with Phase 1's Fan tabs store at its cap (seeded the way Phase 1's `FanTabs.test.tsx` seeds it), the button is disabled with the tooltip "Fan tab limit reached (100)".
   - **Callbacks:** Find, refresh, notes and the Fan insights toggle call their callbacks. The toggle's `aria-expanded` follows `insightsOpen`.
   - **Extras overflow:** the rows carry "Inflowwww extra" and are the same in both flag states. It has no translate row and no "Restrict from automations" row. If this Phase lands before Phase 4, the parked translate row is the one exception until Phase 4 removes it (F12).

   This test covers the new modules `FanAvatarMenu`, `ChatHeaderExtras`, `ChatGallery` and `MessageStatsLink`, and the changed `ChatActionsMenu`, through the header. None of them gets its own test file.

2. **`MessageList`**, in `app/components/chat/MessageList.test.tsx` (extended, existing `msg()` helper and `baseProps`). It covers:
   - **Sent by:** "Sent by <name>" sits inside the bubble's time row when `attribution` has the id.
   - **Receipts:** ✓ "Delivered" and ✓✓ "Seen" follow `lastReadByPeerId`. `newestReadPointer` returns the larger of two pointers, and the one that is set when the other is null.
   - **PPV status:** "$X.XX · paid" for `isOpened` or `isPaid`, "$X.XX · not paid" otherwise. The three existing PPV-unlock cases (`MessageList.test.tsx:122-141`) keep their inputs, and their expected text changes from "locked" / "unlocked" to "not paid" / "paid".
   - **Unlock bar:** "UNLOCK FOR $X" only on an outgoing PPV that is not paid.
   - **Empty:** "No messages yet".
   - **Reply strip:** a small harness renders `MessageList` and the real `Composer`, with the relay mocked. It feeds `onQuoteReply` through `quoteFromMessage` into `Composer`'s existing `quoted` prop and clears it from `onClearQuoted`. Clicking ↩ on a bubble shows "Replying to: <text>" inside the Composer, and ✕ "Cancel reply" removes it.

   The existing alignment, load-error, refused-attachment and release-form cases stay green unchanged. So does `MediaGrid.test.tsx`.

3. **`FanDrawer`**, in `app/components/chat/fanDrawerEditFreshness.test.tsx` (extended, its existing fixtures). Rerendering an open `FanDrawer` with a higher `focusNotesRequest` moves focus to the Fan notes field. In the recommended order Phase 5 has landed, so the case starts on another tab with the Notes block collapsed and expects the Insights tab, the Notes block expanded and focus on Fan notes.

4. **Phase 0's windowed test**, in `app/app/messages-pro/windowed.test.tsx` (case 7 rewritten, its existing fixtures). In any case with a Thread, the Chat header has no "↗ pop out" link and renders "Open in new tab". Right-clicking the selected Fan's row and choosing "Open in a new window" calls `window.open` with `/messages-pro/<acc>/<fan>?window=1`. This keeps a Pop-out window for one Fan covered after the header link is gone (ADR-0002, amended).

Prior art: `MessageList.test.tsx` (the house style for bubbles), `MoneyRail.render.test.tsx` (relay mock), `AiStatusStrip.test.tsx` (a chat-header child under the flag), and `fanDrawerEditFreshness.test.tsx` (`useOFUser`-driven UI).

ASSUMPTION: `Composer` renders under `renderWithProviders` with the relay mocked, because its `VaultPicker` is a `next/dynamic` import that only loads on click (`Composer.tsx:52`). This is overturned if it does not, in which case the harness renders `ReplyStrip` in `Composer`'s place and the Phase result says so.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# the new seam exists (vitest passes with no tests, so check the file itself)
test -f app/components/chat/ChatHeader.test.tsx
# the Phase's seams, then the full suite (binding commands)
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/ChatHeader.test.tsx components/chat/MessageList.test.tsx components/chat/MediaGrid.test.tsx components/chat/fanDrawerEditFreshness.test.tsx app/messages-pro/windowed.test.tsx
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
# no relay/service change in this Phase
git diff --quiet "$(git merge-base HEAD main)" -- service/
# visual loop harness (Phase 0) — exits non-zero on overflow, console errors or a missing shot
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-desktop.png
test -s docs/screenshots/messages-pro-phone-thread.png
test -s docs/screenshots/clone-messages-pro.png
test -s docs/screenshots/messages-pro-report.json
# manual: open messages-pro-desktop.png beside clone-messages-pro.png and write the visual-diff list for the Chat header and message list (position, size, label, order, missing element); fix, re-run, up to three rounds; record what remains as VISUAL GAP: with its reason
# manual: open messages-pro-phone-thread.png (390x844) and confirm the header wraps with no horizontal scroll, back + Fan insights visible, "Open in new tab" and refresh hidden
# manual: record the messages-pro-report.json summary and the Not wired list (Star, Pin, Report, Special offers, Online fans message statistics) in the Phase result, and commit the final PNGs with the code
```

## Depends on

- **Phase 0**:
  - `scripts/ui-shots.sh` and the shots it writes (the Acceptance runs it).
  - The Deep link meaning of `/messages-pro/<accountId>/<fanId>`, which "Copy chat link" produces.
  - `ChatSurface`'s "Fan insights" toggle at every width, with `aria-expanded`, and its `insightsOpenAtStart` prop. `ChatHeader` keeps the toggle (H15, F16).
- **Phase 1**:
  - `useFanTabs` and `OpenInNewTabButton({accountId, fanId, name})`, which `ChatHeader` renders for "Open in new tab".
  - The right-click "Open in a new window", which remains the way to open a Pop-out window now that the header button opens a Fan tab.
  - The Thread empty state, "Select any conversation to start", which Phase 1 owns (F22).
- **Not dependencies, hand-offs.** Both Phases land before this one in the recommended order (`docs/spec/plan-review.md`), and this Phase still lands if they have not.
  - **Phase 5:** this Phase's `focusNotesRequest` switches Phase 5's tabbed Fan insights to the Insights tab and expands the Notes block before it focuses. If this Phase lands first, Phase 5 keeps the prop working (F23).
  - **Phase 4:** its Translator drives the same translate mode, so this Phase removes the header 🌐 toggle. If this Phase lands first, the toggle parks in the Extras overflow and Phase 4 removes that row (F12). If Phase 4 has landed, `ReplyStrip` goes into the slot below the button row where Phase 4 row 23 puts it.

## Out of Scope

- **A new relay route for star (Priority), pin (Pinned chat), Report or Special offers, and a new online-fans statistics view.** The plan allows an endpoint only "when a ticket proves it missing". This Phase renders them as Not wired and lists them instead.
- **The Clone's verified tick (`.vf`, `m.html:177`).** It is not in the plan's Phase 3 target, and our OF types carry no verified field (`grep -rn isVerified app/` finds nothing).
- **The bubble hover toolbar's restyle (`.msg-acts`, `m.html:252-260`).** It is not in the Phase 3 target. Its Geometry belongs to Phase 6.
- **"Load older", date separators, the typing line and the pinned-messages bar.** They are not in the Phase 3 target, and they already exist.
- **The Clone's large PPV card (`.ppv-card` 540×250, `orig:178`).** It would replace the T-GRID media strip and its tested tile boxes. This Phase takes only the unlock bar and the status line.
- **A lightbox from Gallery tiles.** The Clone gallery has no tile action.
- **Turning Find into an anchored popover.** The plan says Find reuses `ChatSearch`.
- **`ChatSearch`'s 12-page cap and its numeric message ids** (`ChatSearch.tsx:32`, `:97`, `:118`). Find reuses `ChatSearch` unchanged, so a fix is its own ticket.
- **The Composer toolbar, PPV row and the AI Translator.** Phase 4 owns them. This Phase only removes the header 🌐 toggle (F12).
- **Fan insights restyle.** Phase 5 owns it. This Phase adds only the `focusNotesRequest` prop (F23).
- **`docs/messages-pro-parity.md` entries for the moved extras.** Phase 7 owns that file.

## Further Notes

**F1 — the pop-out opens a Fan tab, which resolves ADR-0002's open question.**
The screenshot-built Clone labels the button "Open in new tab" with an external-link icon (`orig:516`). The help center names the Fan tabs strip's entry "Open in new tab" C[H262067, H406874]. The current Clone pins a tab: commit `5949d64` quotes the human asking for "extra subtab on the page" instead of a window. The decision rests on observation (rung 1), but the button's behaviour is inferred from its label.
ASSUMPTION: Infloww's Chat header button is "Open in new tab" and adds or focuses this Fan's Fan tab. It does not open a Pop-out window, so ADR-0002's pop-out ASSUMPTION is overturned, and ADR-0002 now carries the amendment (`## Amended 2026-10-12`). This is overturned if a current Infloww build shows the header button opening a separate window.

**F2 — the plan's "not wired" list.** The plan names restrict, block, report and hide as having no relay endpoint. Observation (rung 1) finds routes for three of them: `service/server.py:6568`, `:6559` and `:6301`.
ASSUMPTION: the parenthetical "(restrict, block, report, hide)" states a fact, and the rule it illustrates is "no endpoint → Not wired". So Restrict, Block and Hide chats are wired, and only Report is Not wired. This is overturned if the human meant those four to render disabled whatever the relay offers.

**F3 — star and pin.** The glossary ties the pin icon to the Pinned chat (`CONTEXT.md:78-80`, "Pinned chat"). Neither Priority nor Pinned chat has a write route. The rewired Clone differs on both icons: its star is a read-only indicator painted from the pinned and priority filters (`m.js:715-727`), and its pin opens a "Pin a message" popover (`m.js:2684-2706`). This spec follows the glossary, which the run must respect.
ASSUMPTION: star stands for Priority and pin for Pinned chat. Both are Not wired and show no state, because reading their state would need two extra filtered chat-list fetches on every Thread open (YAGNI). This is overturned if Infloww's pin icon pins a message, in which case it opens the Clone's "Pin a message" popover (`m.js:2684-2706`) over the existing `POST /api/of/v2/messages/{id}/pin/user/{uid}`.

**F4 — Special offers.**
ASSUMPTION: "Special offers" is per Fan and has no route, so it is Not wired. This is overturned if Infloww's row lists the Creator's promotions, in which case it reads `GET /api/of/v2/promotions` (`server.py:5956`).

**F5 — Avatar menu values.**
ASSUMPTION: "Subscription status" shows `subscribedOnData.status` (or "Expired" once `expiredAt` has passed), "Earnings" shows `subscribedOnData.totalSumm`, and anything absent shows "—". This is overturned if Infloww's rows open sub-panels instead of showing inline values.

**F6 — where Copy chat link goes.**
ASSUMPTION: "Copy chat link" is placed after a divider at the bottom of the Kebab menu, because §3.3 gives no position. This is overturned by evidence of its real place, for example the Avatar menu.

**F7 — 📈 placement and targets.** `/growth/smart-messages` opens on its Mass tab from component state, with no URL parameter (`app/components/growth/SmartMessagesPage.tsx:32-34`). Its Mass tab lists every active Creator's blasts with no Creator preselected (`app/components/settings/MassMessagesTab.tsx:78-88`), and `:546` only labels `online_blast` rows. No view shows online-fans statistics on its own.
ASSUMPTION: 📈 sits first in the header's right group, because "by the creator name" points at a name the Chat header does not show. "Mass message statistics" opens `/growth/smart-messages` in a new browser tab, unscoped, because that page takes no Creator parameter and the plan changes nothing outside Messages Pro. "Online fans message statistics" is Not wired. This is overturned if Phase 2's Fan List header takes 📈 beside the Creator name (then the Chat header mount is removed), or if a view of online-blast statistics exists.

**F8 — "MediaGrid".** The repo has no component named `MediaGrid`. The name is the T-GRID tile code that `MediaGrid.test.tsx` tests (`MediaTile`, `mediaTileBox`).
ASSUMPTION: Gallery reuses `MediaTile` and the `fan-chat-media` query, with a new default-on `creatorOnly` option set to false so that it shows "all media exchanged" (§3.3). This is overturned if the plan meant a different, existing grid.

**F9 — Find stays a panel.**
ASSUMPTION: Find keeps `ChatSearch`'s panel under the header instead of the Clone's anchored popover (`m.js:2643`). The difference is recorded as `VISUAL GAP`. This is overturned if the human wants the popover enough to rework `ChatSearch`.

**F10 — what counts as an extra.** Mark as unread, MASSppvEXCLUDE, MASSdmEXCLUDE, focus and Group chat are not in Infloww's kebab (C[H262067]).
ASSUMPTION: they are non-automation Inflowwww extras and go to the Extras overflow, while Restrict from automations is an automation extra and shows only with the flag on. This is overturned if Infloww's kebab is found to carry Mark as unread.
ASSUMPTION: with the flag on, the automation-restrict row stays in the Kebab, after Infloww's rows and a divider, instead of moving to the Extras overflow. Phase 7 puts it there (`phase-07-ours-kept-marked.md:27`, story 13), and the other automation extras also come back to their pre-parity place with the flag on (Persona button after Find, AI strip). Leaving it in `ChatActionsMenu` is also the smaller change, because its mutation and its "Auto-restricted" state do not move (rungs 3 and 5). This is overturned if the human wants every Chat header extra in one overflow, in which case Phase 7's Gap table changes with it.

**F11 — where the "+" sits.**
ASSUMPTION: the "+" Extras overflow sits right after Find (and after the Persona button when the flag is on), in the free space before the right group, so that no Infloww element moves. This follows the Clone, which puts its own extra (`#tbModel`) there (`m.html:703`). It is overturned if Phase 7 chooses one fixed position for every Region's overflow.

**F12 — translate.**
Phase 4's Translator switch is bound to the same `useTranslateMode` as the header toggle (`phase-04-composer-ppv-vault.md:233`), so translate is Infloww's control, not an extra. Phase 4 lands before this Phase in the recommended order (`docs/spec/plan-review.md`), so this Phase removes the header toggle. If this Phase lands first, the toggle parks in the Extras overflow until Phase 4 lands, and Phase 4 then removes that row.
ASSUMPTION: the header toggle's batch hints ("…" while busy and "⚠" after a failed batch, `ChatSurface.tsx:976-978`) leave with it. Phase 4's Translator shows no status (`phase-04-composer-ppv-vault.md:230-233`), and after a failed batch the bubbles still show their originals. This is overturned if the human wants the hints kept, in which case Phase 4's translate icon carries them.

**F13 — token module.**
ASSUMPTION: ADR-0001 forbids magic numbers in JSX, so this Phase writes its measured numbers into the `chatHeader` and `messageList` sections of the Messages Pro token module (`app/lib/messagesPro.ts`), creating the module if Phase 6 has not landed. Phase 6 owns the module's final shape and its snapshot test. This is overturned if Phase 6 lands first with a different shape, in which case this Phase follows that shape.

**F14 — phone header.**
ASSUMPTION: the Clone has no phone layout, so below md the header keeps today's wrap and hides "Open in new tab" and refresh, as `CS:989` and `CS:999` already do (house precedent). Menus keep the `py-3` touch rows, and Gallery opens full-screen. This is overturned if the phone shot shows overflow that can only be fixed another way.

**F15 — back chevron.**
ASSUMPTION: the chevron stays below lg only, although the Clone shows it on desktop (`m.html:688`). With three panes it has no destination, and `docs/routes.md:42` defines it as the phone "Back". This is overturned if the human wants it on desktop to clear the Thread.

**F16 — avatar and Fan insights.** Phase 0 makes the "Fan insights" button a toggle at every width, so that Fan insights can be closed and reopened on a desktop after a Deep link.
ASSUMPTION: the Chat header's avatar keeps our 36px size, because the Clone has none to measure. Clicking it opens the Avatar menu (`CONTEXT.md`, "Avatar menu") and no longer opens Fan insights. Fan insights stays reachable at every width through Phase 0's toggle, which this Phase keeps last before the kebab. This is overturned by a measured Infloww avatar size, or by a Phase 0 change to the toggle.

**F17 — username and Creator.**
ASSUMPTION: "@username · Creator" moves into the name's tooltip, because the Clone's second line is presence and the Creator shows in Phase 1's Creator tabs. This is overturned if All Models (an extra) needs the Creator visible in the header.

**F18 — accessible names.**
ASSUMPTION: the icon buttons' accessible names are "Priority", "Mute notifications"/"Unmute notifications", "Notes", "Pinned chat", "Gallery", "Find", "Inflowwww extras", "Message statistics", "Open in new tab", "Refresh" and "More actions". The Clone gives the icons no labels. These names are overturned by Infloww's own tooltips.

**F19 — how Not wired renders.**
ASSUMPTION: Not wired controls use `aria-disabled` with a no-op click instead of the native `disabled` attribute, so that the "not wired" tooltip reliably shows on hover. This is overturned if the house later standardises Not wired on a shared component.

**F20 — unlock bar.**
ASSUMPTION: the bar uses the Clone's label "UNLOCK FOR $<price>" (`orig:630`). [PAL]'s "UNLOCK PPV" is read as the palette's name for the button. The bar is display-only and shows only on outgoing PPVs that are not paid. This is overturned if the human meant the literal label "UNLOCK PPV".

**F21 — PPV statuses.**
ASSUMPTION: the PPV message statuses are the Clone's two, "paid" and "not paid" (`m.js:888`, `orig:640`). This is overturned if Infloww shows more, for example "unsent".

**F22 — thread empty state.** Phase 1's spec builds the Thread empty state, tests it, and greps for "Select any conversation to start" in its Acceptance (`docs/spec/phase-01-window-chrome-tabs.md`: the "Thread empty state" decision, its page test and its Acceptance grep). This spec's earlier overturn condition, "if Phase 1's spec builds it", is met, so `ThreadEmptyState` is dropped from this Phase.
ASSUMPTION: the plan's Phase 3 "empty states" are the message list's own ("No messages yet"), and the Thread empty state is Phase 1's. This is overturned if Phase 1 drops it.

**F23 — notes icon.** A DOM id cannot do this job. `ChatSurface` can mount two `FanDrawer`s at once, the overlay and the pinned column (`ChatSurface.tsx:1175`, `:1192`), so one id would be duplicated. After Phase 5, only the active Fan insights tab renders and Insights blocks can be collapsed (`docs/spec/phase-05-fan-insights-panel.md`: the "Tabs" decision and gap row G5), so an id cannot switch the tab or expand the block.
ASSUMPTION: the notes icon calls `onOpenNotes`, which opens Fan insights and increments a `focusNotesRequest` counter that `ChatSurface` passes to every `FanDrawer` it mounts. When the value changes, each `FanDrawer` scrolls to and focuses its own Fan notes field through a ref. An element that is not rendered cannot take focus, so only the visible instance does. Whichever of this Phase and Phase 5 lands second makes the prop first switch to the Insights tab and expand the Notes block. In the recommended order that is this Phase. This follows the Clone's `#tbNotes`, which switches the right pane to Notes (`m.js:2541`). It is overturned if Phase 5 exposes a different focus hook.

**F24 — block and confirmations.**
ASSUMPTION: Block and Restrict both ask `window.confirm` first, as the Clone does for restrict (`m.js:2804`). Hide chats does not, as today (`CAM:113-124`), because the Fan's next message undoes it. After Block succeeds the row flips to "Unblock" for the session, or reads `isBlocked` if the OF user payload carries it; no such field is observed in our types. This is overturned by the field's real name.

**F25 — phone bubbles.**
ASSUMPTION: the Clone's bubble and thread-body numbers apply from md up. Below md, bubbles keep `max-w-[88%]` and the thread keeps `px-2`, so that a 390px screen still fits two-sided bubbles. This is overturned if `messages-pro-phone-thread.png` shows them reading badly against the Clone.

**F26 — who owns the reply strip.** The glossary places the reply strip inside the Composer (`CONTEXT.md`, "Composer"), but the plan gives it to Phase 3 and tests it with the message list.
ASSUMPTION: this Phase owns `ReplyStrip` as its own module, and `Composer` only swaps its inline block for it, which keeps Phase 4's Composer chrome work separate. This is overturned if Phase 4's spec absorbs the strip into its toolbar rebuild.

**F27 — what Restrict sends.** `POST /api/of/v2/users/{id}/restrict` defaults to `ack=true` and `hide=true`. It sends the Fan ".", marks the chat read, restricts on OnlyFans, writes the `of_restricted` registry and hides the chat (`service/server.py:6568-6624`). Today's "Restrict on OnlyFans" row calls it with those defaults (`CAM:194-222`). The registry write alone already keeps the Fan out of our unread and owe-reply counts (`app/lib/relay.ts:375-379`).
ASSUMPTION: the Kebab's Restrict posts with `?ack=false`, so it sends the Fan nothing and does not mark the chat read. It keeps `hide` at its default. A message to a Fan cannot be unsent, so reversibility (rung 4) wins over the existing row's precedent. Lift restrict is today's DELETE, unchanged, and the success text drops "Sent “.”". This is overturned if the human wants the Kebab's Restrict to keep the "." flow.

**F28 — read pointer freshness.** `ChatSurface` takes `lastReadMessageId` from the `chat` prop before the live chat cache (`ChatSurface.tsx:702-711`), although its own comment says that prop "is a snapshot captured at click time and never refreshed" (`:657`). So ✓ can stay ✓ after the Fan reads while the Thread is open.
ASSUMPTION: OF's read pointer only grows, so `ChatSurface` passes the newer of the two through `newestReadPointer`. This is overturned if OF can lower `lastReadMessageId`.

**F29 — Gallery paging and errors.** `useFanChatMedia` returns cursor pages and loads the next one only on `fetchNextPage()` (`app/hooks/useFanChatMedia.ts:103-106`). Fan insights' Sales list calls it from a "Load more" button (`FanDrawer.tsx:575`). The hook's query key does not carry `from_user` (`useFanChatMedia.ts:77`).
ASSUMPTION: the Gallery shows "Load more" under the grid while there is a next page, as Fan insights does (house precedent), and shows the relay's error with "↻ Refresh" when a page fails. `creatorOnly` joins the query key, so the Gallery and Fan insights never share a cache entry. This is overturned if the Clone gallery is found to page another way.

## Review

codex, 2026-10-12. Two calls (`codex exec --sandbox read-only`, reasoning high) in a sparse worktree without `docs/spec/`: a blind call on the plan and source (B), then a call on this draft (D). Both exited 0 with fresh, non-empty output. The blind call's log shows no read of `docs/spec/`. The draft call read the neighbouring phase specs through `git show HEAD:`.

- B1 — extract `ChatHeader` but keep orchestration in `ChatSurface`: **reject**, the spec already does this (Owns, Interfaces).
- B2 — a Fan tab overturns only ADR-0002's header-action assumption, not its full-window decision: **reject**, F1 already overturns only that ASSUMPTION and leaves the full-window decision alone.
- B3 — reusing `useFanChatMedia` as-is drops inbound and unpurchased media, and `MediaGrid.tsx` does not exist: **reject**, F8 already sets `purchased: false, creatorOnly: false` and names `MediaTile`. Paging is taken up under D4.
- B4 — Restrict's route defaults send ".", mark read, write the registry and hide (`server.py:6568-6624`), so the spec must say which call it makes: **accept**. F27 and Contracts now post with `?ack=false`, Kebab actions names the moved mutation, and the header test asserts the query.
- B5 — "UNLOCK PPV" could be read as a purchase action: **reject**, F20 already makes the bar display-only, with no fake success.
- B6 — the Clone was rewired, so it should not be copied wholesale: **reject**, the gap table takes labels from `orig` at `4e83397` and colours from tokens (ADR-0001).
- B7 — Phase 0's shared tree is not in the checkout (`[fanId]/page.tsx:205-220`): **partial**. A Phase that has not landed is what a dependency is. Depends on now also names Phase 0's Fan insights toggle and `insightsOpenAtStart` (see D1).
- B8 — star, chat pin and message pin conflict: the Clone's star is read-only (`m.js:715-727`) and its pin opens "Pin a message" (`m.js:2684-2706`). Replacing the avatar click also needs an insights entry point: **partial**. Pin stays the Pinned chat because the glossary binds it (`CONTEXT.md:78-80`), and F3 now records the Clone's divergence. The insights entry is Phase 0's toggle (D1, F16).
- B9 — reverse operations, Hide's effect on the open Thread, error display, cache updates, and mute state local to the menu (`CAM:94-103`): **accept**. A new "Kebab actions" decision moves each handler and its invalidations unchanged, adds Lift restrict and Unblock, keeps the Thread open after Hide, and shows errors in the status line. Mute is lifted into `ChatHeader`, and `ChatActionsMenu` gains `muted` and `onToggleMute`. The old "keeps its props" interface made the shared mute impossible.
- B10 — presence precedence and the unknown state are not defined: **reject**, the Presence decision already defines the online rule, "Last seen" and "Offline" when nothing is known.
- B11 — message-state invariants, and the stale read pointer (`ChatSurface.tsx:657`, `:707-711`): **partial**. The read pointer is accepted as F28 (`newestReadPointer`, tested). The rest is rejected: L3, L5 and L6 already keep attribution, `isOpened || isPaid` and the status controls unchanged.
- B12 — the reply strip belongs to `Composer`, and a `MessageList`-only test cannot prove the wiring: **partial**. `ChatSurface`'s quote state and send path are now stated as unchanged, and the reply test renders the real `Composer` (see D6).
- B13 — Gallery paging, failure, SFW reveal, and `ChatSearch`'s 12-page cap and numeric ids (`ChatSearch.tsx:32`, `:97`, `:118`): **partial**. Gallery paging and the error state are accepted (F29). SFW comes with `MediaTile`. `ChatSearch` is rejected because Find reuses it unchanged, and it is now listed in Out of Scope as its own ticket.
- B14 — extras placement, flag behaviour, menu Escape and focus: **partial**. Placement is already set (H8, H12, H13, M2). A new "Menus" decision gives all four menus the `CAM:50-61` outside-pointerdown and Escape close.
- B15 — Geometry cannot all wait for Phase 6: **reject**, the gap table measures every Region value and F13 writes them now.
- B16 — the primary seam should be `ChatSurface` integration: **partial**. The plan's Acceptance names `ChatHeader.test.tsx` and `MessageList.test.tsx`, so those stay. The gaps are closed where the behaviour lives instead: the AI strip moves into `ChatHeader`, the reply test uses the real `Composer`, notes focus gets a `FanDrawer` test, and the read pointer gets a helper test.
- B17 — no runtime pass: `scripts/ui-shots.sh` is missing and `vitest: command not found`: **reject**. The harness is Phase 0's deliverable and is already in Depends on. vitest is missing only because the sparse review worktree has no `node_modules` (`ls -d app/node_modules` succeeds in the repo).
- B18 — "Sent by", receipts and PPV status already exist (`MessageList.tsx:488-511`, `:649-661`, `:915-975`): **reject**, the spec already treats them as a restyle (L3 to L6), not new work.
- D1 — H15 and F16 keep `lg:hidden` and undo Phase 0's Fan insights toggle at every width: **accept**. H15, F16, the interface (`onToggleInsights`), the order, stories 35 and 36, the test (`aria-expanded`) and Depends on are rewritten.
- D2 — `onOpenInNewTab: () => void` loses Phase 1's 100-tab cap: **accept**. `ChatHeader` renders Phase 1's `OpenInNewTabButton`, and the header test seeds the cap.
- D3 — a DOM id for Notes duplicates across the two `FanDrawer` mounts (`ChatSurface.tsx:1175`, `:1192`) and cannot switch Phase 5's tab: **accept**. F23 is rewritten to a `focusNotesRequest` prop with a ref, and a `FanDrawer` test is added.
- D4 — "all media exchanged" with `limit: 30` and no paging: **accept**. F29 adds "Load more", an error state and `creatorOnly` in the query key, all tested.
- D5 — both 📈 rows open the same unscoped page, and `MassMessagesTab.tsx:546` is only a label map: **accept**. "Online fans message statistics" is Not wired, and Mass stays unscoped as an ASSUMPTION (F7).
- D6 — the seams miss the real reply wiring, the list add and remove calls, success and error outcomes, and the AI strip mounted outside the header: **accept**. All four are now asserted, and the AI strip band moves into `ChatHeader`.
- D7 — "PPV-unlock cases stay green unchanged" contradicts L6 (`MessageList.test.tsx:122-141`): **accept**. Those cases keep their inputs, and their expected text changes.
- D8 — `ThreadEmptyState` is a two-way dependency, and Phase 1 already owns and tests it: **accept**. It is dropped from this Phase (L9, F22, Owns, stories, tests), and Depends on is fixed.
- D9 — Acceptance never requires committing the final PNGs (plan Visual loop step 3): **accept**. The manual line now says so, following Phase 0 to Phase 2 precedent.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: Phase 0's windowed.test case 7 (`phase-00-pop-out-window.md:298`) asserts the "↗ pop out" link that H9 removes. **accept**: checked against both lines. This Phase takes the case over: it is in Owns, in a new seam 4 and in the Acceptance vitest list, and Phase 0's case carries a note.
- Black: "Restrict from automations" is placed in the Extras overflow here (old `:158`) and in the Kebab by Phase 7 (`phase-07-ours-kept-marked.md:27`, story 13). **accept**: the Kebab wins. M2, story 33, Interfaces, both tests and a new F10 ASSUMPTION now put the automation-restrict row last in the Kebab, after a divider, with the flag on only. Rungs 3 and 5, flagged.
- Black: Phase 7's list misses Mark as unread, translate and focus, which this spec calls extras (`phase-07-ours-kept-marked.md:175`, H13, F10). **accept**: Phase 7 now lists Mark as unread and Phone focus. Translate is Infloww's AI Translator, which Phase 4 owns, so this spec stops calling it an extra: H13, story 31, Interfaces, Out of Scope and F12 now remove the header toggle. Its lost batch hints are a new ASSUMPTION.
- Black: Phase 5's byte-identical check on `fanDrawerEditFreshness.test.tsx` (`phase-05-fan-insights-panel.md:199`) clashes with seam 3 here (`:245`). **accept**: Phase 5's check becomes "unchanged by Phase 5" (merge-base idiom, rung 3). Seam 3 now expects the tab switch and the Notes block expanding, because Phase 5 lands first.
- Green: Phase 5 before this Phase avoids the test-file clash, and Phase 4 before it lets it drop translate. **accept**: Depends on now names both as hand-offs, with a fallback if this Phase lands first (F12, F23).
- Red: the moves Phase 7 makes look like churn. **partial**: where this spec can place an extra at its final spot now, it does (the automation-restrict row, translate). The rest of the reconcile is in `plan-review.md`.
- White: ADR-0002:12 is overturned by F1. **accept**: ADR-0002 has an `## Amended 2026-10-12` paragraph, and F1 now points to it.
