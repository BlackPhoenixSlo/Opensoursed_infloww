# Phase 04 — Thread and bubbles

**Objective.** The message list reads like the Infloww capture: each incoming bubble has the Bubble action row (pin, reply, heart, translate) beside it, shown on hover at desktop width and always on a phone, days are split by Infloww's Date dividers ("Sep 29", "Today"), each bubble group has its avatar (the Fan's on the left, the Creator's on the right), and the Jump chip wears Infloww's chip. Every Inflowwww control the old hover toolbar held is kept.

## Gap table

Sources, in the plan's ground-truth order. **Cap** is the Infloww capture of the thread with Fan insights open (`~/Downloads/infloww-shots-2026-10-12/…-cbcd0225-….png`, 3024×1964 at 2×, so device px ÷ 2 = CSS px). It was measured by pixel sampling with `python3 -I` and PIL. Only px and colour values were taken from it, never a name, handle or text. **m.html** is the Clone (`ui-redesign/infloww-exact/messages.html`), and **ML** is `app/components/chat/MessageList.tsx` with its tokens `MP.messageList` (`app/lib/messagesPro.ts:391-450`) and `MP.ours.MessageList` (`app/lib/messagesProOurs.ts:245-300`). The Infloww stylesheet (`~/Downloads/infloww-asar/dist/preload/pages/of/messages.css`) holds no thread or bubble selector: `grep -o '\._[a-z-]*\(msg\|bubble\|chat\)[a-z-]*_' messages.css` finds only script, timeout and PPV-tooltip modules. So the Cap is the only source for elements the Clone lacks, and it outranks the Clone where they disagree.

### A — the plan's four items

| # | Infloww (Cap px, or m.html) | Ours | Gap | Change |
|---|---|---|---|---|
| T1 | Incoming action row: four plain glyphs (pin, reply as a speech bubble, heart, translate) in one row **beside** the bubble, vertically centred on it. The first glyph starts 9px right of the bubble, each glyph is about 12px, the pitch is 20px, and the colour is `#666666` on the `#151515` thread | `ML:697-768`: a box on the bubble's top edge (`MP.messageList.actions`, ML14-17, from the Clone's `.msg-acts`, m.html:253-260) holding Reply, Like, Pin and, where they apply, Unsend and Reward. Glyphs are ↩ ♡ 📌 🗑 🎁 in 24px round buttons from md up | wrong place, order, glyphs and size. No translate | A new `BubbleActions` row beside the bubble, in the order Pin, Reply, Like, Translate, using 12px line glyphs in 16px boxes, a 4px gap (20px pitch) and 9px from the bubble |
| T2 | Outgoing bubble: translate and ⋮ to its **left** (translate glyph 12px, then ⋮ 10px from the bubble) | Reply, Pin and Unsend on the top-edge box | Infloww has no visible reply, pin or unsend on our bubbles | Translate, then a ⋮ "More message actions" menu holding Reply, Pin or Unpin, and Unsend (see F3) |
| T3 | The plan: "visible on hover at desktop and always on phone" | Hidden below md until the bubble is tapped (`touchOpen`, ML:613-617). Hover-only from md | the phone tap step | Below md the row always shows, with no tap. From md up it shows while the pointer is over the bubble's line or the row, or while focus is inside the row |
| T4 | Date divider: a 1px line `#333639` across the list, with the label centred in a 12px gap on each side. The label is about 11px, `#999999`, sentence case ("Sep 29", "Today") | `DateSeparator` (ML:1555-1569): 8px gap, uppercase, label "today" / "yesterday" / "23rd May 2026" | case, wording, gap | Label "Today" for today, otherwise the short month and day ("Sep 29"), with the year added for another year (F5). The gap is 12px and the label is not uppercase |
| T5 | Incoming avatar: a 36px circle (`#232323` with no picture) at the left, 8px before the bubble, its bottom level with the group's last bubble. m.html:238-240 has `.msg-avatar-row` (align-items flex-end) and `.mini-avatar` 38px | none | missing | A 36px avatar on the group's last bubble, 8px gap, bottom-aligned. Earlier bubbles of the group keep a 36px spacer so the group lines up (F6) |
| T6 | Outgoing avatar: a 36px circle at the right of the group, a grey person glyph when there is no picture | none | missing | The same at the right, showing the Creator's avatar or a person glyph |
| T7 | The Clone's chip, `.chip` (m.html:143): radius 16px, padding 7px 15px, 13px / 500, `#2f2f2f` on `#e5e5e5` | `MP.ours.MessageList.autoPin`: a 10px pill, padding 2px 8px, 1px border, `bg-bg-elev-1/90` | size and look | The Jump chip takes `.chip`'s Geometry and colours. It keeps its text, its place (8px under the list's top, centred), its timing and `pointer-events-none` |

### B — what the plan's items carry with them

| # | Infloww | Ours | Gap | Change |
|---|---|---|---|---|
| T8 | Translate on a bubble: Cap shows the glyph on every text bubble | Only the thread-wide translate mode (`useTranslateMode`, ML:130-135). The parent effort moved its toggle out of the Chat header | no per-bubble translate | The glyph toggles that one bubble between its original and its English translation through the existing `useTranslations` hook and `POST /admin/translate` (F4) |
| T9 | Tip reward: not in Infloww | 🎁 Reward on an incoming tip, which fires the tip_reward automation (ML:654-658, "Fires the tip_reward automation on demand"). It shows with the Legacy flag off and is not in the extras catalogue (`app/lib/openinflowwwwExtras.ts`) | an automation extra shown with the flag off, against ADR-0003 | It becomes the catalogued extra "Tip reward" (automation). With the flag on it is a fifth glyph after Translate, titled `extraTitle("Tip reward", …)`. With the flag off it does not render (F7) |

### C — bubble shape from the Cap (a separate ticket, so it can be vetoed on its own; F8)

| # | Cap | Ours (from the Clone, parent Phase 3 L2-L5) | Change (from md up; phone keeps today's values) |
|---|---|---|---|
| T10 | Bubble radius 6px, the tail corner (incoming bottom-left, outgoing bottom-right) square, padding 10px, text about 16px on a 20px line | radius 16px, tail 5px, padding 11/15px, 14.5px / 1.45 (`MP.messageList.bubble`, ML3-5) | radius 6px, tail 0, padding 10px, 16px / 20px |
| T11 | Bubbles of one group are 2–3px apart. Groups are 14px apart | 14px between all messages (ML1) | a 2px gap inside a group. The list keeps 14px between groups |
| T12 | The time row ("1:42 am", about 11px, `#999999`) sits **under** the group's last bubble, about 6px below it, left-aligned under incoming and right-aligned under ours (followed by ✓✓) | The time, receipt and "Sent by" sit inside every bubble (ML6-8, `BubbleTimeRow`) | `BubbleTimeRow` moves under the group's last bubble, 6px below it, 11px. Earlier bubbles in the group show no time row |

## Problem Statement

An Employee who knows Infloww opens a Fan's Thread in Inflowwww and the conversation looks off. The quick actions on a message are round emoji buttons floating on the bubble's top edge. They come in a different order, and there is no translate. On a phone they are hidden until the Employee taps a bubble. Days are split by an uppercase "TODAY" or "23RD MAY 2026" instead of Infloww's quiet "Sep 29" and "Today". No avatars mark whose message is whose. The "Jumping to latest…" note is a tiny bordered pill unlike any Infloww chip. Our own tip-reward button, which fires an automation, shows even when the Legacy flag is off. Next to the Infloww capture, our bubbles are also rounder, and every message repeats its time inside the bubble.

## Solution

Hovering an incoming message at desktop width shows Infloww's row beside it: pin, reply, heart and translate, as small grey line icons. On a phone the row is always there. Our own messages show translate and a ⋮ menu holding Reply, Pin and Unsend, so nothing the old toolbar did is lost. Translate shows that one message in English, and a second click shows the original again. Days are split by a thin line with "Sep 29" or "Today" in the middle. Each run of messages from one side ends with that side's avatar: the Fan's on the left, the Creator's on the right. "Jumping to latest…" appears as an Infloww chip. Tip reward stays, as a marked Inflowwww extra, but only with the Legacy flag on. If the separate bubble-shape ticket lands, bubbles take Infloww's flatter shape, and the time sits once under each run of messages.

## User Stories

1. As an Employee at desktop width, I want the pin, reply, heart and translate icons to appear beside an incoming message when I hover it, so that I act on a message the way I do in Infloww.
2. As an Employee, I want those icons in the order pin, reply, heart, translate, so that my muscle memory from Infloww works.
3. As an Employee, I want the icons at Infloww's size (about 12px glyphs, 20px apart, 9px from the bubble) in Infloww's grey, so that the row is as quiet as Infloww's.
4. As an Employee at desktop width, I want the row hidden while I am not over the message, so that the thread stays clean.
5. As a keyboard user, I want the row to show while focus is inside it, and each icon to be a button I can tab to, so that the actions are not mouse-only.
6. As an Employee on a phone, I want the row always visible beside incoming messages with no tap first, so that I can reach actions without discovering a hidden gesture.
7. As an Employee on a phone, I want each icon's tap target to be at least 24px, so that I hit the one I mean.
8. As an Employee, I want pin to pin or unpin the message as today, and the icon to look pressed and read "Unpin" when the message is pinned, so that I see its state.
9. As an Employee, I want reply to start a quote reply as today ("Replying to: …" in the Composer), so that the reply flow is unchanged.
10. As an Employee, I want heart to like or unlike the Fan's message as today, filled and red when liked, and double-click on the bubble to keep working, so that liking is unchanged.
11. As an Employee, I want translate to show that one message in English, and a second click to show the original, so that I can read a foreign message without translating the whole thread.
12. As an Employee, I want translate to keep the original text when no translation comes back, with its title saying so, so that a failed translation never hides the message.
13. As an Employee, I want translate absent on a message with no text, so that the icon never does nothing.
14. As an Employee, I want my own messages to show translate and a ⋮ menu beside them, as Infloww shows, so that our side looks like Infloww's.
15. As an Employee, I want that ⋮ menu to hold Reply, Pin (or Unpin) and Unsend, so that nothing the old toolbar did on my messages is lost.
16. As an Employee, I want the ⋮ menu to close on an outside click or Escape, like every other Messages Pro menu, so that it behaves as I expect.
17. As an Employee, I want no action row on a message that is still sending, has failed or is scheduled, so that I cannot act on a message OnlyFans does not have yet.
18. As an Employee with the Legacy flag on, I want the 🎁 Tip reward icon after translate on a Fan's tip, marked "Inflowwww extra", so that the manual reward stays available where it was.
19. As an Employee with the Legacy flag off, I want no Tip reward icon, so that no automation control shows outside the flag (ADR-0003).
20. As an Employee, I want a Date divider above the first message of each day, so that I can tell days apart.
21. As an Employee, I want today's divider to read "Today" and earlier days to read like "Sep 29", with the year only when it is another year, so that it reads like Infloww.
22. As an Employee, I want the divider to be a thin line with the label centred and 12px of space each side of it, in sentence case, so that it is as quiet as Infloww's.
23. As an Employee, I want the Fan's 36px avatar at the left of each run of the Fan's messages, level with its last bubble, so that I see at a glance who is talking.
24. As an Employee, I want the Creator's 36px avatar at the right of each run of our messages, so that both sides are marked as in Infloww.
25. As an Employee, I want a plain circle (the Fan's) or a person glyph (ours) when there is no picture, so that a missing image never breaks the layout.
26. As an Employee, I want the bubbles of one run to line up, with no avatar except beside the last, so that runs read as one block.
27. As an Employee, I want avatars to cost no extra relay calls, so that the Thread stays as fast as it is.
28. As an Employee, I want the "Jumping to latest…" note to look like an Infloww chip, so that our extra fits the screen.
29. As an Employee, I want the Jump chip to keep its text, its place at the top centre and its timing, and never to block a click, so that only its look changes.
30. As an Employee at 390px, I want the bubble, its avatar and its row to fit the width with no horizontal scroll, so that the phone layout works.
31. As a reviewer, I want Tip reward catalogued in `app/lib/openinflowwwwExtras.ts` and listed under "Ours" in `docs/messages-pro-parity.md`, so that the extras audit and the parity doc stay complete.
32. As a reviewer, I want the Compare page's Thread rows TH1–TH6 (action row, its visibility, Date dividers, both avatars, Jump chip) all present and reading "matched" when the Phase lands, or `differs` naming the remaining px with a reason (`remaining: <n>px — <reason>`, Phase 0's Named remainder), with "ours" allowed only on TH2 (its phone half has no Infloww counterpart), so that "done" is checkable.
33. As an Employee, if the bubble-shape ticket lands, I want bubbles with a 6px radius, a square tail corner, 10px padding and 16px text from desktop width up, so that they match the capture.
34. As an Employee, if the bubble-shape ticket lands, I want a run of messages sent in the same minute to stack 2px apart, with the time (and ✓/✓✓ and "Sent by") shown once under the run's last bubble, so that the thread reads like Infloww's.
35. As an Employee, I want the "sending…", "failed — retry" and "scheduled · cancel" status under each such bubble unchanged, so that I never lose a send's state.

## Implementation Decisions

- **Owns.**
  - `MessageList` (modified): grouping into runs, the avatar slot, the time row's place (Part C), Date divider labels and Geometry, the Jump chip, and the new avatar props.
  - `BubbleActions` (new, in the chat components): the Bubble action row for one bubble, both sides, including the ⋮ menu on ours and per-bubble translate. It replaces the inline hover toolbar in `Bubble`.
  - `BubbleMeta` (modified, Part C only): `BubbleTimeRow` renders outside the bubble box.
  - `ChatSurface` (modified): passes the Fan's and the Creator's avatar URLs, and passes `onSendReward` only when `useLegacyAutomations()` is true.
  - The Geometry token module `messagesPro` (modified): new `MP.messageList` entries for the action row, the avatar, the divider and (Part C) the group gap and the time row. The ML14-17 hover-box entries are replaced. `MP.ours.MessageList.autoPin` takes the chip's Geometry.
  - `openinflowwwwExtras` (modified): one new extra.
  - `scripts/ui-shots.sh` and `docs/ui-shots.md` (modified checks, no new state).
  - `docs/messages-pro-parity.md` (one "Ours" line for Tip reward).
- **Interfaces.**
  - `MessageList` gains two optional props, `fanAvatar: string | null` and `creatorAvatar: string | null`. All existing props and callbacks keep their signatures. `onSendReward` stays optional, and its absence hides Tip reward.
  - `BubbleActions({msg, side, canPin, canReply, canLike, canUnsend, canSendReward, onTogglePin, onQuoteReply, onToggleLike, onUnsend, onSendReward, translated, onToggleTranslate, translateState})` renders nothing when no action applies. The `can*` rules are today's (`ML:636-658`), moved, not changed.
  - Incoming buttons, by accessible name in DOM order: "Pin" or "Unpin" (`aria-pressed` when pinned), "Reply", "Like" or "Unlike" (`aria-pressed` when liked), "Translate" or "Show original" (`aria-pressed` while translated), then "Tip reward" with the flag on, on a tip only.
  - Outgoing: "Translate" or "Show original", then "More message actions" (`aria-haspopup="menu"`), whose menu items are "Reply", "Pin" or "Unpin", and "Unsend", each only where its `can*` rule holds. The ⋮ itself renders only when one of them applies.
  - Each title states the action. Tip reward's title is `extraTitle("Tip reward", "Send a free vault reward for this tip (fires the tip_reward automation)")`.
  - Per-bubble translate: a bubble shows its translation when the thread-wide translate mode is on, or when its own toggle is on. The toggle's first click asks `useTranslations([stripped text], true)` for that one text. That is the same module cache and the same relay call as the thread mode, so a text already translated costs nothing. A cached `null` (failed) leaves the original and sets the title to "No translation available". While the thread-wide mode is on, the per-bubble toggle shows "Show original" and turning it off shows that bubble's original.
  - The Date divider label is a pure function exported from `MessageList` beside `newestReadPointer`: `dateDividerLabel(iso: string, now: Date): string` returns "Today" for `now`'s local day, `"<short month> <day>"` for another day of `now`'s year, and `"<short month> <day>, <year>"` for another year. It uses the browser locale, as `fmtDateSeparator` does today. It replaces `fmtDateSeparator`.
  - Runs (Part C, and for avatar placement in Part A): `messageRuns(messages, ownerUserId, labels)`, exported from `MessageList`. A run is consecutive messages on the same side, on the same local day and in the same displayed minute, with the same "Sent by" label and, on our side, the same receipt state (sent, or read). A pending, failed or future-scheduled message is a run of its own. So the one time row a run shows in Part C carries exactly what each bubble's row carried. The avatar sits on a run's last bubble.
  - Part A without Part C (the case where the human vetoes F8): the time row stays inside each bubble and the 14px list gap stays, and only the avatar uses runs.
- **Schema.** None. No storage, no relay model change.
- **Contracts.**
  - No new relay route and no new call per row or per message. Per-bubble translate uses the existing `POST /admin/translate` (`{texts, target: "en"}` → `{results}`) through `useTranslations` unchanged. Avatars come from data the Thread already holds: the Fan's from what `ChatSurface` already resolves for the Chat header (`ChatSurface.tsx:807`), and the Creator's from the `/me` query `ChatSurface` already runs (`meQ`).
  - Pin, reply, like and unsend call the same parent callbacks, so their relay calls are unchanged.
  - The extras catalogue gains `{ name: "Tip reward", automation: true, off: [], on: ["Message list"] }`. The header comment's count goes up by one.
  - DOM hooks the harness and tests read: `data-msg-id` stays on the bubble box. The action row carries `role="group"` with `aria-label="Message actions"`. The avatar slot carries `data-msg-avatar="fan" | "creator"`. The Date divider stays `role="separator"` with `aria-label=<label>`. In Part C, the time row carries `data-time-row` and is the bubble box's next sibling inside the bubble's column.
- **Geometry and colour.**
  - Geometry goes in the token module (ADR-0001's Geometry half), and every value comes from the Gap table. Phone values are prefixed `max-md:` or set by default with `md:` overrides, as ML1-ML5 do.
  - Colours go through Phase 1's `InflowwPalette` variables wherever one holds the value (ADR-0010; Phase 1 Story 28, "the next colour change is one edit"). The target values are the Gap table's: action glyphs `#666666`, hover `#d9d9d9`, liked heart `#f0483e` (m.html:260), pinned in the Messages Pro accent, the divider line `#333639`, its label and the time row `#999999`, the empty Fan avatar `#232323`, the person glyph `#666666`, and the chip `#2f2f2f` on `#e5e5e5`. For each, the element uses the colour token class whose `InflowwPalette` variable the Colour inventory maps to that value (for example `text-accent` for the pinned state, and `border-border` for the divider if `--color-border` holds `#333639`). A raw hex literal is written only where no palette variable holds the value, and each such literal gets its own `### Literals` line on the Compare page. Expected literals, since no shell or text variable carries them: the liked heart `#f0483e` (the `err` status colour is "keep", so its palette value stays ours) and the light chip pair `#2f2f2f` on `#e5e5e5`.
    ASSUMPTION: which of `#666666`, `#d9d9d9`, `#333639`, `#999999` and `#232323` a palette variable already holds is read from the Colour inventory when the ticket is cut (Phase 0 has not run yet); rung 3 (Phase 1's palette is the house home for Messages Pro colours). Overturned by the inventory: a value no variable holds becomes a listed literal, never a new shared token (ADR-0010).
  - Each new class or literal is added to the Colour inventory row it belongs to. Through the palette variables they follow Phase 1's light-theme rule automatically; a literal follows it only because Phase 1 makes Messages Pro one palette under both themes.
- **Hover and focus.** From md up, the row's visibility is CSS on the bubble line's `group` (`md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100`). It never uses `display:none`, so the row keeps its width and the bubble does not shift on hover. Below md it is always opaque and interactive. The `touchOpen` state and the tap handler that set it are removed.
- **Layout.** A bubble line is a flex row. For incoming it holds avatar slot, bubble column, row. For outgoing it holds row, bubble column, avatar slot. The bubble column keeps its max width (`MP.messageList.bubbleColumn`) and can shrink (`min-w-0`), so at 390px the row and avatar always fit.
- **Stickers.** The ♥ and 📌 stickers on liked and pinned bubbles stay as they are. They are state marks, not actions.
- **Jump chip.** It is not an Inflowwww extra in the catalogue sense: it is status text with no control. This follows the parity doc's ruling on the AI reply countdown (`docs/messages-pro-parity.md:54`, "status text with no control, so not an extra"). It gets no "Inflowwww extra" title and no catalogue entry.

## Testing Decisions

Three seams, all existing.

1. **`MessageList.test.tsx`** and its sibling **`MessageList.timeRow.test.tsx`** (the Part C time-row cases, split out to keep the main file under 1000 lines; same component test through `renderWithProviders`, relay mocked by URL as the file already does). This is the main seam. It tests through `MessageList`'s props and the DOM, never `BubbleActions` alone.
   - **Action row, incoming:** the "Message actions" group of an incoming bubble names Pin, Reply, Like and Translate in DOM order. A pinned and liked message reads Unpin and Unlike with `aria-pressed="true"`. Each button calls its callback with the message.
   - **Action row, outgoing:** an outgoing bubble shows Translate and "More message actions". Opening the menu shows Reply, Pin and Unsend, and each calls its callback. Escape closes the menu, and so does a pointer-down outside it.
   - **States:** a pending, failed or scheduled message has no "Message actions" group.
   - **Tip reward:** with `onSendReward` passed, a tip shows "Tip reward" fifth, and its title starts "Inflowwww extra — Tip reward". Without it, no such button shows.
   - **Translate:** clicking Translate POSTs `/admin/translate` with exactly that message's stripped text, and the bubble then shows the mocked translation. A second click shows the original again. A mocked failure keeps the original and sets the title to "No translation available". A media-only message has no Translate.
   - **Date dividers:** with `vi.setSystemTime`, messages on two days show separators named "Sep 29" (or the locale's form) and "Today", each above its day's first message, and no element inside a separator carries the `uppercase` class (today's `DateSeparator` does, ML:1555-1566). `dateDividerLabel` covers today, another day this year and another year.
   - **Avatars:** in a run of three Fan messages, only the last bubble's line has `data-msg-avatar="fan"`, and the Fan avatar's `img` uses `fanAvatar`. Outgoing runs get `creator`. With null URLs, the fallback circle or glyph renders and no `img` does. Rendering with avatar URLs makes no relay request the same render without them does not (the URL-mocked fetch records the same request list both ways).
   - **Jump chip:** "↓ Jumping to latest…" renders with the chip tokens and `pointer-events-none`.
   - **Part C:** "Sent by" and the receipt sit in the `data-time-row` under the run's last bubble, outside its `data-msg-id` box. This replaces today's "inside the bubble's time row" test. Earlier bubbles in the run have no time row. Two same-minute outgoing messages, the first read and the second not, are two runs, each with its own time row and receipt.
   - The existing "hover actions" describe (`MessageList.test.tsx:630-661`) is rewritten to the new names and places. The reply-strip-with-real-Composer test keeps passing unchanged, and so does every existing test of media, PPV and unlock state, receipts, "Sent by" and the sending, failed and scheduled status lines (story 35). The only existing assertion a ticket may rewrite is Part C's time-row placement.
2. **The extras audit, `app/messages-pro/extras.test.tsx`.** Its fixture thread gains one incoming tip message (invented identifiers). With the flag on, Tip reward is found once at "Message list". With the flag off, it is absent. The catalogue and audit assertions are otherwise unchanged.
3. **The visual loop, `scripts/ui-shots.sh`.** These are new checks on existing shots, and no new state is added (plan Phase 0).
   - `messages-pro-desktop`:
     - Before any hover, the first incoming fixture bubble's "Message actions" group has computed opacity 0. After hovering the bubble it is 1, and it names Pin, Reply, Like and Translate in order, each within the thread pane. With the pointer moved away and its Pin button given focus, the group's opacity is 1 again (story 5).
     - The first separator's label has computed `text-transform: none`.
     - Every bubble line has an avatar slot on the run's last bubble.
     - A separator sits above the first fixture message, reading "Today", or the short month and day when the fixture spans midnight (the check computes the label the same way).
     - `check_time_in_bubble` becomes `check_time_under_bubble` (Part C): the time's box starts below the bubble box's bottom, inside the bubble's column.
     - `check_receipt` looks in the bubble's column instead of the bubble box (Part C; without Part C both checks stay as they are).
   - `messages-pro-phone-thread`: with no hover, an incoming bubble's "Message actions" group is visible (opacity 1) and wholly inside the 390px viewport, each of its buttons' boxes is at least 24×24px (story 7), and the shot keeps `overflowX: false`.
   - Check names (the Acceptance reads them): "the first incoming bubble's Message actions show on hover only", "the first incoming bubble's Message actions show on focus", "every run's last bubble has its avatar", "a Date separator sits above the first fixture message", "the Date separator label is not uppercase", "the first fixture message's time sits under its bubble" (Part C), and on the phone shot "an incoming bubble's Message actions show with no hover" and "the phone Message actions buttons are at least 24px".
   - The Jump chip has no harness check: it shows only during a jump, which no fixture shot holds still. Its look is covered by the component test's tokens and by the manual comparison.
   - `docs/ui-shots.md`'s shot rows name the new and renamed checks.

The colour check in `app/lib/messagesPro.test.ts` keeps guarding that no colour enters the token module.

Prior art: `MessageList.test.tsx` (bubbles, the hover-actions describe, the read pointer, the reply strip with the real Composer), `app/messages-pro/extras.test.tsx` (catalogue against the tree, flag on and off), `ChatHeader.test.tsx` (a menu that closes on Escape), and the `check_*` functions in `scripts/ui-shots.sh`.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# the Phase's seams
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/MessageList.test.tsx components/chat/MessageList.timeRow.test.tsx app/messages-pro/extras.test.tsx lib/messagesPro.test.ts
# Tip reward is catalogued as an automation hosted in the Message list
grep -q 'name: "Tip reward", automation: true, off: \[\], on: \["Message list"\]' app/lib/openinflowwwwExtras.ts
grep -q 'Tip reward' docs/messages-pro-parity.md
# the old top-edge toolbar's phone tap state is gone
! grep -q 'touchOpen' app/components/chat/MessageList.tsx || exit 1
# no relay/service change in this Phase
git diff --quiet "$(git merge-base HEAD main)" -- service/
# full suite (typecheck, lint, vitest)
.scratch/messages-pro-look-and-feel/suite.sh
# visual loop: ok=True, and the Phase's checks present and passing
scripts/ui-shots.sh
python3 -I - <<'EOF'
import json
r = json.load(open("docs/screenshots/messages-pro-report.json"))
assert r["ok"] is True, "harness not ok"
shots = {s["name"]: s for s in r["shots"]}
def names(shot): return [c["name"] for c in shots[shot]["checks"] if c["ok"]]
d, p = " ".join(names("messages-pro-desktop")), " ".join(names("messages-pro-phone-thread"))
for want in ("Message actions show on hover only", "Message actions show on focus", "avatar", "separator sits above", "not uppercase"):
    assert want in d, f"desktop check missing or failing: {want}"
for want in ("Message actions show with no hover", "at least 24px"):
    assert want in p, f"phone check missing or failing: {want}"
assert shots["messages-pro-phone-thread"]["overflowX"] is False
print("phase 4 harness checks ok")
EOF
# Part C only: runs only when the Compare page carries Part C's rows (TH7-TH9, Difference "Part C:", owned by a ticket, Phase 0).
# A vetoed Part C leaves those rows `unowned`, so this block skips itself; nothing depends on a human skipping it.
if grep -E '^[|] TH[0-9]+ [|] [^|]*[|] Part C:' docs/screenshots/messages-pro-compare.md | grep -qvE '[|] unowned [|]'; then
python3 -I - <<'EOF'
import json
r = json.load(open("docs/screenshots/messages-pro-report.json"))
d = [c["name"] for s in r["shots"] if s["name"] == "messages-pro-desktop" for c in s["checks"] if c["ok"]]
assert any("time sits under" in n for n in d), "Part C check missing or failing: time sits under"
print("phase 4 Part C harness check ok")
EOF
fi
# the Compare page's Thread rows: TH1-TH6 exist; each owned TH row (Part C's TH7-TH9 too, when owned) is matched, TH2 may be ours, or differs naming the remaining px with a reason
python3 -I - TH 1 6 TH2 <<'PY'
import re, sys
pre, lo, hi, ours = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]
named = re.compile(r"remaining: (-?\d+(\.\d+)?px|#[0-9a-fA-F]{3,8}) [—-] \S")
rows = {}
for l in open("docs/screenshots/messages-pro-compare.md"):
    c = [x.strip() for x in l.strip().strip("|").split("|")]
    if l.startswith("|") and re.fullmatch(pre + r"\d+", c[0]):
        assert len(c) == 7, f"{c[0]}: {len(c)} cells, want 7"
        rows[c[0]] = c
need = [f"{pre}{i}" for i in range(lo, hi + 1)]
missing = [i for i in need if i not in rows]
assert not missing, f"Compare rows missing: {missing}"
check = [i for i, c in rows.items() if i in need or c[5] != "unowned"]
bad = [i for i in check if not (rows[i][6] == "matched" or (rows[i][6] == "ours" and i in ours) or (rows[i][6] == "differs" and named.search(rows[i][4])))]
assert not bad, f"{pre} rows neither matched nor naming the remaining px with a reason: {bad}"
print(f"{len(check)} {pre} Compare rows matched or named")
PY
# manual: open messages-pro-desktop.png beside the Infloww capture (never committed) and clone-messages-pro.png; hover an incoming bubble in a headed run and compare the row, dividers, avatars and chip; up to three rounds, then record what remains as VISUAL GAP: with its reason
# manual: open messages-pro-phone-thread.png and confirm the row shows beside incoming bubbles with no horizontal scroll
```

## Depends on

- **Phase 0 — Measure and pin.** It provides the Compare page with the Thread rows this Phase flips to "matched", and the Colour inventory that the new colours are added to.
- **Phase 1 — Colour and shell.** It provides the Infloww bubble, shell and accent colours that the action row, dividers and avatars sit on, and the rule for what Messages Pro shows under the light theme, which the new colours follow. Part A can be built before Phase 1 lands, but its Compare rows cannot be judged "matched" until then.

## Out of Scope

- **Bubble fills, the PPV card colour and text colours.** Phase 1 owns them (plan Phase 1). The Cap shows our outgoing bubble grey where the plan says blue. That is Phase 1's binding decision and is not re-opened here.
- **The time format ("5:41 pm" against our "05:41 PM").** `docs/messages-pro-parity.md:54` gives it to the human (tickets 97, 101, 116). Part C moves the time row but does not change its text.
- **The "↓ Latest" button.** The plan names only the "Jumping to latest…" pill. The button keeps its look until the Compare page gives it a row.
- **The thread-wide translate toggle.** Its place is the Composer's (Phase 5). This Phase only reads its state.
- **The ♥ and 📌 stickers, the PPV status line and unlock bar, the reply quote card, Free previews and the media strip.** They are unchanged. The plan's Phase 4 does not name them, and nothing in the Cap contradicts them.
- **The pinned bar and the pinned-messages overlay.** They are not in the plan's Phase 4, and the parity doc already carries their open wording item for the human.
- **Message grouping beyond avatar placement, when Part C is vetoed.** Without Part C, runs only place avatars.

## Further Notes

**F1 — hover at desktop.** The Cap shows the row on every incoming bubble at once, which may mean Infloww shows it always. The plan says "visible on hover at desktop", and the plan binds (constraint), so the row is hover-only from md up. The overturn is a human instruction to show it always, which is a one-class change (drop the `md:opacity-0`).

**F2 — glyphs.** Infloww's icons are line glyphs (pin, speech bubble, heart outline, the 文A translate mark). We draw them as inline SVG paths of our own at the measured size, never copied from Infloww's files.
ASSUMPTION: house precedent is inline SVG for Messages Pro icons (the Chat header's 22px chevron, parent Phase 3 H2). Overturned if the repo has an icon set the Chat header already uses for the same glyphs, in which case we use that.

**F3 — our side's actions.**
ASSUMPTION: Reply, Pin and Unsend on our bubbles move into the ⋮ menu that the Cap shows beside outgoing bubbles. Infloww's ⋮ contents are not visible in any capture, and the binding "nothing we built is removed" keeps all three. Overturned by a capture of Infloww's outgoing ⋮ menu, or if the human prefers them as icons in the row.

**F4 — per-bubble translate.**
ASSUMPTION: the translate icon translates one bubble through the existing `useTranslations` cache and `POST /admin/translate`, OR-ed with the thread-wide mode (rung 5: no new route or hook). Overturned if Infloww's icon opens a menu (target language, copy translation) that a capture shows.

**F5 — Date divider wording.**
ASSUMPTION: only "Today" and the short month-day form are used. Yesterday reads as a date, because the Cap shows "Sep 29" and "Today" and no "Yesterday" case (rung 5). Another year adds ", <year>", because without it the label would be ambiguous (rung 4). The label follows the browser locale, as today's `fmtDateSeparator` does (rung 3). Overturned by a capture showing "Yesterday" or a year form.

**F6 — avatar size and alignment.**
ASSUMPTION: the avatar is 36px from the Cap, not the Clone's 38px `.mini-avatar`, because the capture outranks the Clone in the plan's ground-truth order. Both sides are bottom-aligned with the run's last bubble (m.html:238 `align-items:flex-end`). The Cap's outgoing avatar sits about 10px lower than its bubble's bottom; if that remains after the visual loop, TH5 stays `differs` with `remaining: 10px — <reason>` in Ours (Phase 0's Named remainder), which the Compare gate passes, rather than being forced to `matched`. Overturned if the Compare page's Clone px is ruled the target for avatars.
ASSUMPTION: below md the avatar keeps 36px with an 8px gap, because the Clone has no phone layout and a 390px Thread still fits a bubble, avatar and row with the bubble shrinking. Overturned if `messages-pro-phone-thread.png` shows bubbles too narrow, in which case phone avatars drop to 28px.

**F7 — Tip reward behind the flag.**
ASSUMPTION: Tip reward is an automation extra. Its own comment says it "fires the tip_reward automation" (`MessageList.tsx:654-656`). Under ADR-0003 it renders only with the Legacy flag on, hosted in the Message list, and is catalogued (rung 3: the "Automation restrict" precedent, an automation action placed after Infloww's controls with the flag on). Phase 7 of the parent effort missed it. Overturned if the human rules a click-fired reward is not an automation, in which case it becomes a non-automation extra with a flag-off host (an Extras overflow on the bubble), which changes the catalogue entry.

**F7a — Tip reward is its own ticket.** The flag-gating of Tip reward (T9, F7) is cut as its own ticket in the Tickets step, separate from the action row, so the human can veto it alone. Hiding a control default users have today sits against the plan's "nothing we built is removed" (plan:18-19) as much as it follows ADR-0003; if vetoed, Tip reward stays where it is with the flag off, uncatalogued, and Story 19, the extras-audit fixture and the catalogue grep drop.
ASSUMPTION: the gating stays the spec's default (ADR-0003 binds automation extras to the flag, rung 2 for the ADR, rung 3 for reading Tip reward as an automation), only isolated for veto. Overturned by a human veto of that ticket.

**F8 — Part C, bubble shape.** The plan's Phase 4 lists four items and does not mention the bubble's shape or the time row. The Cap shows a flatter bubble (6px radius, square tail, 10px padding, about 16px text), bubbles of one run 2px apart, and the time under the run's last bubble. The parent effort's in-bubble time came from the Clone (L2-L5).
ASSUMPTION: these are specced as Part C, a separate ticket, because the plan's goal ("sees Infloww") needs them and the capture outranks the Clone (brief: evidence never shrinks the goal). Overturned if the human keeps the Clone's bubble or the Compare page assigns these rows elsewhere. In that case Part C is dropped whole, and Parts A and B stand without it.
ASSUMPTION: a run is consecutive same-side messages in the same displayed minute with the same "Sent by" label. On our side a run also breaks where the receipt state changes, so the receipt shown once under the run is true of every bubble in it (adversary review). That way, showing the time and receipt once loses no information the per-bubble rows carried (rung 5). Overturned if Infloww's grouping rule is observed to differ, for example a five-minute window.
ASSUMPTION: the 16px text is measured from glyph heights (an 'h' ascender of 12px and an x-height of 8.5px at 2×), assuming a Roboto-like face. Overturned by a direct font-size reading from Infloww, in which case only the token changes.

**F9 — Compare row IDs.**
The Thread Compare rows are TH1–TH6 (and Part C's TH7–TH9) in Phase 0's seven-column table, rows starting with the ID and Status the seventh cell (`phase-00-measure-and-pin.md`, Interfaces; rung 1, the spec now exists). The Acceptance gate reads them by ID.

## Review

Reviewer: codex (`codex exec`, read-only sandbox, reasoning high, blind workspace), 2026-10-15. Blind call (B) without the spec, draft call (D) with it.

- B1 alternatives (narrow parity pass on `MessageList`, rebuild from the Clone, desktop-from-capture with our own phone) — **reject**: the spec already takes the first, measured against the capture where the Clone is silent (Gap table preamble); a Clone rebuild loses pin and translate, which the reviewer confirms the Clone lacks (`messages.js:851-899`).
- B2 the Clone has no pin or translate controls — **reject**: already the reason T1/T8 cite the Cap, which outranks the Clone in the plan's ground-truth order.
- B3 "always on phone" is a product decision with no Infloww phone reference (`docs/infloww-screens.md:601-604`) — **reject**: it is the plan's own text (constraint, rung 2), and T3 cites it as such.
- B4 date format and timezone unspecified — **reject**: decided in `dateDividerLabel` (browser locale and local day) and F5.
- B5 action eligibility on our side and on pending, failed or scheduled messages unspecified — **reject**: Interfaces keep today's `can*` rules, stories 15 and 17 and the States test cover both.
- B6 per-bubble translate vs the thread-wide mode undefined — **reject**: decided in Interfaces (per-bubble toggle OR-ed with the thread mode) and F4.
- B7 run boundaries and avatar source undefined — **reject**: `messageRuns` and the Contracts bullet (`ChatSurface.tsx:807`, `meQ`) define both.
- B8 preservation of media, PPV, receipts, "Sent by" and send status should be explicit acceptance — **accept**: Testing Decisions now requires every existing test of those states to keep passing unchanged, with Part C's time-row placement the only assertion a ticket may rewrite.
- B9 phone tap behaviour and accessibility need a decision — **partial**: the decision exists (T3, story 7), but story 7 had no check; covered by D3c.
- B10 seams: `MessageList` component test plus the browser harness — **reject** (agreement, no change): those are the spec's seams 1 and 3.
- B11 date dividers, action toolbar and the latest pill already exist, so "add" is false — **reject**: the Gap table states what exists (ML:697-768, ML:1555-1569, `autoPin`) and specs a restyle and move, not an addition.
- B12 the report asserts no avatars, divider style or row placement today — **reject**: the spec adds exactly those harness checks.
- D1 Part C is vetoable yet the Acceptance required "time sits under" unconditionally — **accept**: the main harness block no longer reads it; a separate "Part C only" block does, and the `check_receipt` change is marked Part C.
- D2 the Compare check passed rows still marked "ours" — **accept** (narrowed): TH1–TH6 must all be present and "matched"; "ours" is allowed only on TH2, whose phone half has no Infloww counterpart (Phase 0 spec, story 15). Story 32 is reworded to match.
- D3a focus reveal (story 5) untested — **accept**: new desktop check, the row's opacity is 1 with the Pin button focused and no hover.
- D3b outside-click dismissal (story 16) untested — **accept**: the outgoing component test also closes the menu by a pointer-down outside it.
- D3c phone tap target at least 24px (story 7) untested — **accept**: new phone check on each button's box, read by the Acceptance.
- D3d Jump chip has no visual check — **partial**: the chip shows only during a jump, which no fixture shot holds still, and the plan bars new harness states (Phase 0). Its tokens and `pointer-events-none` stay component-tested and its look stays in the manual comparison; this is now stated in Testing Decisions.
- D3e sentence case and divider gap not tested; a CSS `uppercase` would pass the DOM text check (ML:1555-1566) — **accept**: the component test asserts no `uppercase` class in a separator and a desktop check reads computed `text-transform: none`. The 12px gap stays a token value covered by the manual comparison.
- D3f "no extra relay calls" for avatars (story 27) untested — **accept**: the avatar test compares the mocked fetch's request list with and without avatar URLs.
- D4 Part C's run-level receipt hid an earlier read bubble behind a later unread one — **accept**: on our side a run now also breaks where the receipt state changes, so one time row per run carries what each bubble's row did; F8's assumption is rewritten and the Part C test covers a mixed-receipt pair.
- D5 Depends on Phase 0 and Phase 1 — **reject** (agreement, no change): the reviewer found no missing or false dependency.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- Black, TH5 gated on `matched` while F6 expects a ~10px outgoing-avatar gap: **accept**. The Thread gate now passes `matched` or `differs` with `remaining: <n>px — <reason>` (Phase 0's Named remainder); F6 says TH5 records the 10px that way. Story 32 matches.
- Black, raw hex literals in JSX bypass `InflowwPalette` and the light-theme rule: **accept**. "Geometry and colour" now routes each colour through the palette variable the Colour inventory maps to its value; a literal only where none does (expected: `#f0483e` and the chip pair), each a Literals line. Flagged ASSUMPTION, since the inventory does not exist yet.
- White/Red, Part C cannot be skipped inside Phase 6's `bash -e`: **accept**. The Part C block is now guarded: it runs only when the Compare page carries owned Part C rows (TH7–TH9, "Part C:", Phase 0); a veto leaves them `unowned` and the block skips itself.
- Green, Tip reward flag-gating takes a control from default users: **partial**. The gating stays the decision (ADR-0003), but it becomes its own clearly vetoable ticket in the Tickets step (F7a); tickets are cut later, not here.
- Red, Part C and Tip reward read as a second effort: **partial**. Both are now separately vetoable tickets; Part C stays specced because the capture outranks the Clone and evidence never shrinks the goal.
- Green/Black, gate strictness for TH rows: **accept**, as the first bullet.
- Blue, split: **accept** (recorded in plan-review.md): Part A action row and translate; dividers, avatars and chip; Tip reward gating; Part C.
