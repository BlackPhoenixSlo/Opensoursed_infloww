# Phase 03 — Chat header

**Objective.** The Chat header is Infloww's two-line header (line 1: back, name, verified badge, edit pencil, then "Open in new tab", refresh and the Kebab menu at the right; line 2: presence, star, bell, notes, pin, Gallery, Find), and every Inflowwww extra that sat inline in it (📈, the "+" Extras overflow trigger, the Persona button) is reached through the Kebab menu, so nothing extra renders inline and the flag-on 44px shift of the icon row is gone.

## Problem Statement

Someone who knows Infloww opens a Thread in our Messages Pro and the Chat header looks wrong. Ours is one line: a 36px avatar, the name over the presence line, and then one cluster of icons pushed to the right end (star, mute, notes, pin, Gallery, Find, "+", 📈, "Open in new tab", refresh, the Fan insights toggle, the kebab). In Infloww, line 2 starts under the name, right after "Available now", with thin dividers between the icons, and only "Open in new tab", refresh and the kebab sit at the right. Our header has three things Infloww lacks sitting inline: the "+" Extras overflow, 📈 and, with the Legacy flag on, the Persona ⓘ. Because the Persona ⓘ joins the cluster that is anchored to the right group, turning the flag on moves the whole Infloww icon row 44px left (`docs/messages-pro-parity.md:53`, ticket 127). There is no verified badge and no edit pencil. On a phone the header runs three rows.

## Solution

The Chat header becomes two lines, as in the real Infloww capture. Line 1 holds the phone back control, the Fan's name, the verified badge when the Fan is verified, and an edit pencil that opens Fan insights on the Nickname field. Its right end holds "Open in new tab", refresh, our Fan insights toggle and the kebab. Line 2 holds the presence dot and text, then star, bell, notes, pin, "Gallery" and "Find", with a 1px divider between each item. The 36px avatar is not drawn; pressing the name opens the Avatar menu, as pressing the avatar did. The Kebab menu keeps its Infloww rows and gains, under dividers, the two message-statistics rows that 📈 held and a last row, "Inflowwww extras ▸", which opens the Chat header Extras overflow as a submenu. With the flag on, that overflow also holds "Persona". Nothing between the presence line and "Find" depends on the flag, so the icon row stays in the same place in both flag states. On a phone the header is two lines: the words "Gallery" and "Find" fold to icons, and "Open in new tab" and refresh stay hidden below md, as today.

## User Stories

1. As an Employee who knows Infloww, I want the Chat header to be two lines, with the name on line 1 and the presence and icons on line 2, so that the header reads like Infloww.
2. As an Employee, I want line 2 to start right after the presence text ("Available now", "Last seen …", "Offline"), so that the icons sit under the name where Infloww puts them.
3. As an Employee, I want star, bell, notes, pin, "Gallery" and "Find" in that order, separated by 1px dividers at Infloww's spacing, so that the row matches the capture.
4. As an Employee, I want the Fan's name at Infloww's size and weight, ending in an ellipsis when it is long, so that long names never push the right group off the line.
5. As an Employee, I want a verified badge after the name when the Fan's OnlyFans profile says it is verified, and no badge otherwise, so that the badge never claims something we don't know.
6. As an Employee, I want an edit pencil after the name (or after the badge) that opens Fan insights and puts the cursor in the Nickname field, so that I can rename the Fan from the header as I can in Infloww.
7. As an Employee, I want "Open in new tab", refresh and the kebab at the right end of line 1, vertically centred on the header, so that the right group matches Infloww.
8. As an Employee, I want our Fan insights toggle kept between refresh and the kebab at every width, so that I can still open and close Fan insights (it is the only way to reach it on a phone).
9. As an Employee, I want to press the name to open the Avatar menu (Subscription status, Earnings, Special offers, Add to lists ▸), so that the Avatar menu stays reachable with no avatar drawn in the header.
10. As an Employee, I want 📈's "Mass message statistics" and "Online fans message statistics" as rows in the Kebab menu, so that both stay reachable while the header shows only Infloww's icons.
11. As an Employee, I want the "+" Extras overflow reached from the Kebab menu's last row, "Inflowwww extras ▸", so that our extras (Scheduled, Group chat, Mark as unread, the MASS toggles, focus on a phone) stay one click away without sitting in the header.
12. As an Employee with the Legacy flag on, I want "Persona" as a row in the Chat header Extras overflow that opens the same Persona card, so that the Persona button is kept but no longer sits inline.
13. As an Employee with the Legacy flag on, I want the Infloww icon row in the same place as with the flag off, so that turning the flag on never moves Priority to Find (the 44px shift is gone).
14. As an Employee with the Legacy flag on, I want the AI strip to stay as a band under the two lines, so that the automation state stays visible without entering either line.
15. As an Employee, I want every moved extra to keep its "Inflowwww extra — <name>" tooltip, and the Extras overflow row to keep the name and tooltip "Inflowwww extras", so that I can always tell which controls are ours.
16. As an Employee on a 390px phone, I want the header to be two lines with no horizontal scroll, back and Fan insights visible, and "Open in new tab" and refresh hidden, so that it fits a phone.
17. As an Employee in focus mode on a phone, I want the kebab to stay visible, so that I can reach "Inflowwww extras ▸" and turn focus off.
18. As an Employee in a narrow Thread, I want the words "Gallery", "Find" and "Open in new tab" to fold to icons only when line 2 or line 1 really does not fit, so that at 1440 with Fan insights open the words show as in Infloww.
19. As the person checking parity, I want the Compare page's Chat header rows to read "matched", or name the px still different, so that this Phase's result is visible next to the Clone shot.
20. As the extras audit, I want the catalogue to record the Persona button's flag-on host as the Chat header overflow, so that the audit still accounts for every extra in both flag states.

## Implementation Decisions

- **Owns.**
  - `ChatHeader` (modified): the two-line layout, the verified badge, the edit pencil, the name as the Avatar menu trigger, no avatar image, no inline 📈, "+" or Persona button.
  - `ChatActionsMenu`, the Kebab menu (modified): gains the message-statistics section and the "Inflowwww extras ▸" row.
  - `MessageStatsLink` (modified): its button and own menu go; it becomes the two Kebab rows it held, same targets and Not wired rendering.
  - `ChatHeaderExtras`, the Chat header Extras overflow (modified): its trigger becomes a Kebab row that opens it as a submenu; it gains the flag-on "Persona" row.
  - `ModelInfoButton` (modified): can render as an Extras overflow row that opens the same Persona card.
  - `FanDrawer` (modified, additive): a `focusNicknameRequest` prop, the twin of `focusNotesRequest`.
  - `ChatSurface` (modified): owns the `focusNicknameRequest` counter and passes `onEditName` to `ChatHeader`.
  - The Geometry token module in `app/lib/` (`MP.chatHeader`): new and changed Chat header tokens, no colour.
  - The Inflowwww extras catalogue (`openinflowwwwExtras`): the Persona button's flag-on host.
  - The OF user type in the relay client: an optional `isVerified` field (type only).
  - The harness `scripts/ui-shots.sh`: one new check on the desktop shot, one on the phone-thread shot, and the rewrite of the two existing checks that assert the old inline 📈 and "+" (`check_chat_header_right`, `check_chat_header_extras`).
  - The Compare page's Chat header rows (status only).

- **Interfaces.**
  - `ChatHeader` props: `avatar` is dropped; `onEditName: () => void` is added. All other props are unchanged.
  - `ChatActionsMenu` props are unchanged except that it now renders the statistics rows and the "Inflowwww extras ▸" row itself; it receives `focusMode` and `onToggleFocus` to pass to the overflow.
  - `ChatHeaderExtras({accountId, fanId, focusMode, onToggleFocus, open, onClose})` renders its menu only, no trigger and no `useMenuDismiss` of its own. `ChatActionsMenu` owns both layers' open state and renders the submenu inside the element its own `useMenuDismiss` watches, so a pointer-down in the submenu is "inside". Its Escape handler closes the submenu when it is open and the Kebab menu otherwise, so one Escape closes one layer (two `document` listeners would both fire on one Escape, since `stopPropagation` does not stop listeners on the same target, `app/components/chat/useMenuDismiss.ts:18-21`).
  - `MessageStatsLink` exports `MessageStatsRows()`, two menu rows, and no longer renders a button.
  - `ModelInfoButton({accountId, asRow?: boolean})`: `asRow` renders a menu row named "Persona" with the title `extraTitle("Persona button", <its old tooltip>)` that opens the existing card.
  - `FanDrawer` gains `focusNicknameRequest?: number`: a count higher than the instance has answered switches to the Insights tab, expands the block that holds Nickname, and focuses the Nickname field, by the same mechanism as `focusNotesRequest`.
  - `OFUser` (relay client type) gains `isVerified?: boolean`. If Phase 2 has already added the field for Fan List rows, this Phase reuses it.

- **Schema.** None.

- **Contracts.** No new relay route and no change under `service/`. The pencil saves through Fan insights' existing Nickname save (local `custom_nickname` and the OnlyFans custom-name write) with its read-before-edit freshness check. The header writes nothing itself. The verified badge reads `isVerified` from the cached OF user (`useCachedOFUser`, no new request) or from `chat.withUser`, as the Clone does (`ui-redesign/infloww-exact/messages.js:1458-1462`).

- **Layout, left to right.** Sources: the real Infloww thread capture of 2026-10-12, measured at 2 device px per CSS px. Values are CSS px.
  - **Region.** 52px tall, 1px bottom border. Padding 20px left and right from md up (the back glyph starts 20px from the pane edge and the kebab glyph ends 20px from it). Below md it keeps today's 12px (house precedent, parent spec F14).
  - **Line 1.** The back control (phone only, below lg, as today) with a 16px chevron glyph, 13px before the name. Then the name: 18px, semibold, one line with an ellipsis. Then the verified badge (a 10px glyph, 6px after the name). Then the pencil (a 12px glyph, 9px after the badge, or 6px after the name with no badge). The line's glyphs sit 10px below the Region's top.
  - **Line 2.** It starts at the name's left edge, about 9px under line 1. The 6px presence dot, 6px before the 10px presence text, which ends in an ellipsis. Then star, bell, notes, pin (12px glyphs), then "Gallery" and "Find" (an 11px glyph, 5px before the 10px word). A 1px × 12px divider sits between every two items, 11px from each, so the icons are 36px apart. The line does not wrap.
  - **Right group, line 1's end, vertically centred on the Region.** "Open in new tab" (a 12px icon, 7px before the 13px semibold word, from md up), refresh (a 14px glyph, about 20px after it, from md up), the Fan insights toggle, the kebab (a vertical-dots glyph 14px tall, about 21px after refresh). Each keeps its button target. The toggle keeps the phone's 40px target below md.
  - **AI strip.** With the flag on, it stays a band under the Region's two lines (`MP.chatHeader.aiStrip`, unchanged), outside both lines.
  - Every number is a token in `MP.chatHeader`. The JSX holds colours only (ADR-0001, ADR-0010). The new divider, badge and pencil take Phase 1's divider, muted-text and icon colour mapping.

- **The word fold.** `MP.chatHeader.labelText` changes its threshold from an 886px Thread to a 448px Thread. Two lines leave room the one line did not: line 2 is about 340px wide. The words show at 1440 with Fan insights open, as in the capture, and fold to icons in a 390px phone Thread.

- **Kebab menu order.** Restrict, Block, Report (Not wired), Hide chats, Mute notifications. A divider, then Copy chat link. A divider, then "Mass message statistics" and "Online fans message statistics" (Not wired), exactly as the 📈 menu had them. With the flag on only, a divider and the automation-restrict row, unchanged. Last, a divider and "Inflowwww extras ▸" (accessible name and title `EXTRAS_OVERFLOW_LABEL`), present whenever the overflow has a row to show, which is always, because Group chat is always there. The submenu opens beside the Kebab menu, after the precedent of the Avatar menu's "Add to lists ▸". Escape closes one layer at a time. An outside pointer-down closes both.

- **Extras overflow rows.** Scheduled, Group chat, Mark as unread, the two MASS toggles, focus (below lg only), and, with the flag on only, "Persona". Each row keeps its existing `extraTitle` tooltip, mutation and status line. Nothing is removed from the catalogue.

- **Catalogue.** The Persona button's `on` host changes from "Chat header" to "Chat header overflow". The AI strip stays at "Chat header" (the band). No other entry changes.

- **The 44px shift.** It goes because nothing in line 2 or line 1 depends on the flag. Only the AI strip band under them does.

- **The name as Avatar menu trigger.** The name, the badge and the presence line are one button titled "Avatar menu", with the tooltip "@username · Creator" kept on the name. The pencil is a separate button titled "Edit name" and is not inside it.

## Testing Decisions

Two seams carry the Phase, plus one recorded measurement (CH5). Both seams already exist. A test asserts what the Employee sees and what the relay is asked, never internal state.

1. **`ChatHeader`**, in the existing `ChatHeader.test.tsx` and its sibling `ChatHeader.avatarMenu.test.tsx` (the Avatar menu cases, split out to keep the main file under 1000 lines), rendered with the house provider wrapper, the relay mocked by URL and the flag set through `FlagsProvider`. It covers:
   - **The two lines.** In DOM order, line 1's accessible names are back (phone), the Avatar menu button, "Edit name", then "Open in new tab", "Refresh", "Fan insights", "More actions". Line 2's are Priority, mute, Notes, Pinned chat, "Gallery", "Find" (the words are the accessible names; "Chat gallery" and "Search this conversation" are their titles, `ChatHeader.tsx:222,236`). The lists are identical with the flag off and on, the line 1 and line 2 containers have the same children in both states, the AI strip (flag on) is outside both containers, and no Persona button, 📈 button or "Inflowwww extras" button is in the header in either state. That is the 44px-shift guard at the DOM level; the px guard is CH5 below.
   - **Verified badge.** Present with `isVerified: true` on the cached OF user, absent without it.
   - **Pencil.** Calls `onEditName`.
   - **No avatar.** No `img` in the header. The name opens the Avatar menu with its four rows.
   - **Kebab.** The order above in both flag states. The two statistics rows behave as 📈's did ("Mass message statistics" targets `/growth/smart-messages`, the other is Not wired). "Inflowwww extras ▸" opens the overflow, whose rows carry "Inflowwww extra", and with the flag on include "Persona", which opens the Persona card. Escape closes the submenu first, then the Kebab menu.
   - **Unchanged cases.** The existing Kebab, mute, Gallery, Find, refresh and toggle cases stay, with the trigger path updated where the "+" or 📈 moved.
2. **The harness**, `scripts/ui-shots.sh`, on the `messages-pro-desktop` shot (1440, flag off). A new check, "Chat header is two lines and line 2 follows the presence line", passes when:
   - the header is 52px tall (1px);
   - "Priority" starts no more than 24px right of the presence text's right edge;
   - "Priority", "Gallery" and "Find" sit below the name's box;
   - "Open in new tab", "Refresh" and "More actions" share one vertical centre (1px) within the header.

   On the `messages-pro-phone-thread` shot (390), a new check, "Chat header is two lines on a phone", passes when "Priority" sits below the name's box, "Find" sits on Priority's line, and the header's `scrollWidth` is at most its `clientWidth`.

   Two existing checks assert the old header and are rewritten in this Phase: `check_chat_header_right` drops "Message statistics" from `CHAT_HEADER_RIGHT` (`scripts/ui-shots.sh:778`), and `check_chat_header_extras` (`scripts/ui-shots.sh:792-801`) becomes "no 'Inflowwww extras' or 'Message statistics' button in the Chat header, and no translate toggle". `check_chat_header`, `check_chat_header_icons`, `check_phone_header` and `check_chat_header_legacy_off` stay.

3. **CH5, the flag-on position.** Measured as Phase 0 measures its flag-on rows (`phase-00-measure-and-pin.md:64`): the harness's isolated localhost servers with `OPENINFLOWW_LEGACY_AUTOMATIONS=1`, a Thread open at 1440, Priority's x read in the browser and compared with the flag-off shot's. CH5 reads `matched` only when the two differ by at most 1px, and the row's Ours column records both x values; otherwise it stays `differs` with `remaining: <n>px — <reason>`.

Supporting, on existing tests:
- `fanDrawerEditFreshness.test.tsx`: a higher `focusNicknameRequest` focuses the Nickname field (twin of the Notes case).
- `extras.test.tsx`: the reach routine opens the Chat header overflow through the Kebab row, and the Persona button is found there with the flag on.
- `messagesPro.test.ts`: the `chatHeader` expectations and the no-colour-in-tokens check.

Prior art: `ChatHeader.test.tsx` (header order, Kebab and flag cases), `fanDrawerEditFreshness.test.tsx` (the Notes focus request), `extras.test.tsx` (the reach routine), `check_phone_header` in `scripts/ui-shots.sh` (a header geometry check).

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# the Phase's seams and the tests it touches
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/ChatHeader.test.tsx components/chat/ChatHeader.avatarMenu.test.tsx components/chat/fanDrawerEditFreshness.test.tsx app/messages-pro/extras.test.tsx app/messages-pro/windowed.test.tsx lib/messagesPro.test.ts
# no extra renders inline in the Chat header: no "+" trigger, 📈 button or Persona button in ChatHeader's JSX
! grep -nE '<(ChatHeaderExtras|MessageStatsLink|ModelInfoButton)\b' app/components/chat/ChatHeader.tsx
# the Persona button is catalogued in the Chat header overflow with the flag on
grep -q 'name: "Persona button", automation: true, off: \[\], on: \["Chat header overflow"\]' app/lib/openinflowwwwExtras.ts
# full suite (typecheck, lint, vitest)
.scratch/messages-pro-look-and-feel/suite.sh
# no relay/service change
git diff --quiet "$(git merge-base HEAD main)" -- service/
# visual loop: exits non-zero on a failed check, overflow, console error or missing shot
scripts/ui-shots.sh
python3 -I -c 'import json,sys; d=json.load(open("docs/screenshots/messages-pro-report.json")); s=[s for s in d["shots"] if s["name"]=="messages-pro-desktop"][0]; c=[c for c in s.get("checks",[]) if c["name"].startswith("Chat header is two lines")]; sys.exit(0 if c and all(x["ok"] for x in c) else 1)'
UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
# the Compare page's Chat header rows: CH1-CH5 exist; each is matched, or differs naming the remaining px with a reason (Phase 0, Named remainder)
python3 -I - CH 1 5 <<'PY'
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
python3 -I -c 'import json,sys; d=json.load(open("docs/screenshots/messages-pro-report.json")); s=[s for s in d["shots"] if s["name"]=="messages-pro-phone-thread"][0]; c=[c for c in s.get("checks",[]) if c["name"].startswith("Chat header is two lines on a phone")]; sys.exit(0 if c and all(x["ok"] for x in c) else 1)'
# manual (recorded in CH5's Ours column): with OPENINFLOWW_LEGACY_AUTOMATIONS=1 on the harness's isolated localhost servers, open a Thread at 1440 and confirm Priority's x is within 1px of the flag-off shot's
# manual: open messages-pro-desktop.png beside the Infloww thread capture and confirm the two lines, dividers and right group; record any px still different on the Compare page
# manual: open messages-pro-phone-thread.png and confirm two lines, no horizontal scroll, back and Fan insights visible, "Open in new tab" and refresh hidden
```

## Depends on

- **Phase 0:** the Compare page and its Chat header rows, which this Phase turns to "matched", and the Colour inventory rows for the header.
- **Phase 1:** the Infloww palette in Messages Pro JSX, whose divider, muted-text, accent and icon colours the new divider, badge, pencil and "Open in new tab" take. If Phase 1 has not landed, the new elements use the colour classes their neighbours use today, and Phase 1's sweep recolours them.

## Out of Scope

- **Colour values in the header.** Phase 1 owns the colour switch. This Phase sets no colour of its own.
- **Inline renaming in the header.** The pencil reuses Fan insights' Nickname save, because that save carries a read-before-edit freshness guard that a second edit path would have to copy.
- **The Fan insights panel's own layout and its 390px overhang.** Phase 5.
- **Bubble actions, date dividers and the message list.** Phase 4.
- **Making Star (Priority), Pin, Report, Special offers and Online fans message statistics work.** They stay Not wired, as the parent effort left them. No new relay route.
- **A flag-on harness run.** The harness runs with the flag unset by design (`docs/ui-shots.md`). The flag-on position is guarded by the DOM-order test and the CH5 measurement on the isolated localhost servers, recorded on the Compare page.
- **The Clone's anchored Find popover.** Find keeps opening our search panel (parent spec, Out of Scope).

## Further Notes

- The plan names an "All Models marker" among the Chat header's extras, but the Chat header renders no All Models marker today. `grep -rn -i "all models" app/components/chat/ChatHeader*.tsx app/components/chat/ChatSurface.tsx` finds nothing. The All Models Creator marker lives on Fan List rows (`FanRow.tsx:73`). The only Creator mark in the header is the name's "@username · Creator" tooltip, which stays. The catalogue's "All Models" entry is hosted in the Window header and its overflow, not the Chat header (`app/lib/openinflowwwwExtras.ts:49`), so it is another Region's and this Phase does not move it. There is nothing to move, and nothing new is added (rung 1).
ASSUMPTION: the plan's "All Models marker" means nothing in the Chat header today; overturned if the human names a header marker, which would then go into the Chat header Extras overflow with an `extraTitle`.
- 📈 is Infloww's per `docs/infloww-screens.md:204`, but the plan lists it as "ours" and says it moves. It moves into the Kebab menu, not into the Extras overflow, and is not given an "Inflowwww extra" tooltip, because it is not in the catalogue.
ASSUMPTION: 📈's two rows go into the Kebab menu (rung 3, the Kebab menu holds Infloww's own Fan actions); overturned if the human wants them in the Extras overflow as an extra.
ASSUMPTION: the "+" moving "into the kebab menu" means its trigger becomes the Kebab menu's last row, which opens the existing overflow as a submenu (rung 3, the Avatar menu's "Add to lists ▸"); overturned if the human wants the overflow rows inline in the Kebab menu, or the "+" kept as an icon in the right group.
ASSUMPTION: the Persona button goes into the Chat header Extras overflow rather than the Kebab menu (rung 5, the overflow already holds the Chat header's extras); overturned if the human wants it as a Kebab row.
ASSUMPTION: the 36px avatar is not drawn, because the Infloww capture's header has none, and the name takes over as the Avatar menu trigger (rung 1 for the capture, rung 4 for keeping the menu); overturned if the human wants the avatar kept on line 1.
ASSUMPTION: our Fan insights toggle stays between refresh and the kebab at every width, though the capture shows none (rung 4; below lg it is the only way into Fan insights, and it is not an Inflowwww extra in the catalogue); overturned if the human wants it hidden from lg up, with the pane's own ✕ to close it.
ASSUMPTION: the AI strip band under the two lines is not "inline", so it stays (rung 5; the plan's list of moved extras omits it, and it cannot shift the icon row); overturned if the human wants it in the overflow too.
ASSUMPTION: the pencil opens Fan insights and focuses Nickname (rung 3, the Notes icon's `focusNotesRequest`); overturned if the human wants Infloww's inline rename.
ASSUMPTION: the verified badge reads OnlyFans' `isVerified` on the Fan's user, as the Clone does; overturned if the relay never passes it, in which case the badge never shows and the Compare row names it.
ASSUMPTION: the capture's scale is 2 device px per CSS px (it is 3024px wide from a Retina Mac, and the Fan List measures about 400px against the Clone's 390px). The font sizes (18px name, 10px line 2, 13px "Open in new tab") are inferred from glyph heights at ±1px. Overturned if the Compare page's measurement against the Clone shows another scale.
ASSUMPTION: from md up the Region takes the capture's 20px padding and 52px height over the Clone's 18px and 58px (the plan's ground-truth order puts the capture first); below md it keeps today's 12px (parent spec F14).
ASSUMPTION: the word fold moves to a 448px Thread (rung 5: the existing container query with a threshold that fits line 2's ~340px plus padding); overturned if the harness shows the words clipping at 1280.
- The Compare page's Chat header rows are CH1–CH5 in the seven-column table `ID | Region | Difference | Clone px | Ours | Ticket | Status` (`phase-00-measure-and-pin.md:46-52`), so the Acceptance reads the ID and Status columns and fails when any of CH1–CH5 is missing (rung 1).

## Review

Reviewer: codex (blind call and draft call, `model_reasoning_effort=high`, read-only sparse workspace), 2026-10-15.

Blind call:
- B1 "Two lines" contradicts the Clone's single `.thread-head` row (`messages.html:201,690`): **reject**. The plan says two lines (`docs/plans/messages-pro-look-and-feel.md:59`) and ranks the real capture, which shows two lines, above the Clone; the Layout section is sourced from the capture, not the Clone.
- B2 Avatar and its menu unspecified: **reject**. Covered: no avatar, the name opens the Avatar menu (story 9, "The name as Avatar menu trigger"), tested under "No avatar".
- B3 The pencil is not in the Clone header: **reject**. The plan names it (line 59) and the capture shows it; its action is decided (Fan insights' Nickname, with the freshness guard) and flagged.
- B4 Extras' hosts per flag state unspecified by the plan: **reject**. The spec decides each host in both flag states (Kebab menu order, Extras overflow rows, Catalogue), consistent with ADR-0003.
- B5 "All Models marker" ambiguous, catalogue puts it in the Window header (`openinflowwwwExtras.ts:49`): **partial**. The Further Note now cites the catalogue host; the decision (nothing in the Chat header to move) stands and stays flagged.
- B6 Back, Not wired and existing behaviours need preserving: **reject**. "Unchanged cases" keeps the existing tests; back stays phone-only, Star/Pin stay Not wired (Out of Scope).
- B7 No geometry or visual acceptance: **reject**. The Layout section gives every px with its source, and the harness checks plus Compare rows CH1–CH5 are the visual acceptance.
- B8 Rule for the "+" trigger itself: **reject**. Decided: the trigger becomes the Kebab's last row, "Inflowwww extras ▸".
- B9 Test seams are `ChatHeader` and the full-page harness: **partial**. Agrees with the spec; the phone-thread shot is added under D9.
- B10 The current report checks the old order, so it is no evidence for the new state: **accept**. Same root as D1; the two stale checks are rewritten.
- B11 Several listed paths are absent from the workspace: **reject**. A workspace path-list matter (the tab hooks live under `app/components/chat/`); no spec decision rests on them.

Draft call:
- D1 The harness Acceptance fails, because `check_chat_header_right` expects "Message statistics" and `check_chat_header_extras` expects the inline "Inflowwww extras" (`scripts/ui-shots.sh:778,792-801`): **accept**. Both are now rewritten by this Phase (Owns, Testing 2). Fixed with it: line 2's accessible names are "Gallery" and "Find", not their titles.
- D2 Phase 3 must cover the message list (`docs/plans/messages-pro-parity.md:128,143`): **reject**. That is the parent effort's Phase 3; this effort's Phase 3 is the Chat header only, and bubbles are Phase 4.
- D3 The DOM-order test cannot prove the 44px shift is gone, and the manual check has no criterion: **accept**. The DOM test now also compares the two line containers' children across flag states, and CH5 is measured on the isolated localhost servers with the flag on and passes only within 1px, recorded on the Compare page.
- D4 The Compare grep passes on zero rows: **accept**, and it was worse: Phase 0's rows start with the ID (`phase-00-measure-and-pin.md:46`), so `^| Chat header |` never matches. Replaced by a check that CH1–CH5 all exist and read `matched`; the format ASSUMPTION is replaced by the rung-1 citation.
- D5 The spec contradicts the plan on All Models: **partial**. As B5: the catalogue citation is added; moving a Window header extra is not a Chat header change, and the ASSUMPTION names what overturns it.
- D6 The catalogue's "Chat header overflow" hosts go stale when the overflow is reached through the Kebab: **reject**. The overflow is still the Chat header's own overflow and still in the Chat header Region; only its trigger moves. `extras.test.tsx`'s reach routine is updated (Testing, Supporting).
- D7 `ChatHeaderExtras`'s interface is inconsistent (`open`/`onClose` missing, `chat` not a prop today, `ChatHeaderExtras.tsx:43-50`) and nested dismissal is unspecified: **accept**. One signature, without `chat`; `ChatActionsMenu` owns both layers and one Escape handler, since two `document` listeners would both fire (`useMenuDismiss.ts:18-21`).
- D8 No measured gap table and no committed shots (`docs/plans/messages-pro-parity.md:37,50`): **reject**. That is the parent plan's rule; this effort replaces gap tables with Phase 0's Compare page, and the coordinator commits.
- D9 390px is untested for two lines and no horizontal scroll (`scripts/ui-shots.sh:813`): **accept**. New phone-thread check and an Acceptance line for it.

Counts: accept 6, partial 3, reject 11, needs-human 0.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- Black, "all CH rows matched" contradicts Phase 6's "typography can't be graded" (`'Sora Fallback'`): **accept**. The Compare gate now passes a CH row that is `matched` or `differs` with `remaining: <n>px — <reason>` (Phase 0's Named remainder), as Story 19 already promised; the gate reads the seven-cell rows by ID and fails if any of CH1–CH5 is missing. CH5 keeps its 1px rule for `matched`.
- White, the zero-row Compare grep: **accept, already fixed here** (D4); the new gate keeps the ID form.
- Blue, serial landing and ticket split: **accept** (recorded in plan-review.md); this Phase is not split (one Region, one ticket).
