# Phase 02 — Fan List rows and header

**Objective.** Every Fan List row has Infloww's layout at 96px: the avatar with its online dot and spend under it, name, verified badge and @handle on one line with an inert ✕ at the right, a one-line preview with the time and muted bell at the right, and our unread and owe dots as Edge markers. The Fan List header's first row is the Creator's name with gallery, search and "+". The Fan List buttons row ends in the Notifications toggle, stored per Employee in the existing notification preferences key. The Fan List cache, its background refresh and its relay calls are unchanged.

## Problem Statement

Someone who knows Infloww opens our Fan List and sees a different list. Our rows are 75px tall, not Infloww's 96px. A Fan who has spent money gets an orange figure where the avatar should be, and the "$0" pill sits over the avatar's bottom edge instead of under it. There is no verified badge and no ✕ at the end of the name line. The unread dot and owe dot sit after the time, where Infloww shows only the time and the muted bell, and the bell disappears whenever a row is also unread. The Fan List header's first row has search and "+" but no gallery icon. The Notifications button always opens our Notifications panel, and an Employee who wants Infloww's plain badge-only button can't have it.

## Solution

Each row now reads like Infloww's. It is 96px tall with a 40px avatar at the left, the online dot on the avatar's bottom-right edge, and the spend pill directly under the avatar on every row whose spend is known ($0 included). A spender keeps their avatar. The first line holds the name, a verified badge when the Fan is verified, the @handle, and a muted ✕ at the right end. The second line holds the one-line preview, the time at the right, and a muted bell after the time whenever the Fan's notifications are muted. Our unread dot and owe dot move out of the second line and become Edge markers at the row's left edge, 9px, centred on the avatar. The Fan List header's first row gains the gallery icon before search and "+". Gallery opens the open Fan's Chat gallery, and with no Fan open it is disabled and says why. The second row (the "All inboxes" selector, the gear, "Newest first", sort and refresh) stays as it is, and so does everything under it: the built-in filters, the Fan List Extras overflow, the folder chips and "✎ Lists" keep their places (`FanListFilters.tsx:181-244`). A small switch at the right end of the Fan List buttons row turns the Notifications panel on or off for the signed-in Employee. On, the default, Notifications opens the panel as today. Off, Notifications shows only its count badge and opens nothing. The choice survives a reload, applies in the Pop-out window, and follows the Employee rather than the browser tab.

## User Stories

Rows (Compare rows FL1–FL8 from the Phase 0 Compare page):
1. As an Employee, I want every Fan List row to be 96px tall at 1440 and at 390, so that the list has Infloww's density (FL7).
2. As an Employee, I want the Fan's 40px avatar at the left of every row, including a spender's, so that I recognise Fans by face as I do in Infloww (FL1).
3. As an Employee, I want the online dot on the avatar's bottom-right edge, ringed in the row's background (selected and hovered rows included), so that "online now" reads at a glance (FL1).
4. As an Employee, I want the Fan's Total spend in a pill directly under the avatar, "$0" for a known zero, so that spend sits where Infloww puts it (FL1).
5. As an Employee, I want a row whose spend is still unknown to show no pill, so that a missing figure is never shown as $0.
6. As an Employee, I want an expired Fan's avatar to keep its red ✕ treatment with the spend pill still under it, so that this kept Inflowwww signal survives the restyle.
7. As an Employee, I want the name, a verified badge when the Fan is verified, and the @handle on one line, truncating the handle first, so that identity reads like Infloww's (FL2).
8. As an Employee, I want no verified badge for a Fan the cached data does not mark as verified, so that the badge never claims something the relay did not say.
9. As an Employee, I want the row badges New, 🔥, ❄️ and Off to stay on line one after the handle, so that nothing we built is removed.
10. As an Employee, I want a muted ✕ at the right end of line one, so that the row matches Infloww's silhouette (FL3).
11. As an Employee, I want clicking the ✕ to do nothing and say "not wired", without selecting the row, so that the ✕ never fakes an action we haven't built.
12. As an Employee, I want the preview on one line, truncated, bold while unread, so that the list reads like Infloww's (FL4).
13. As an Employee, I want the time at the right end of the preview line, so that recency sits where Infloww puts it (FL5).
14. As an Employee, I want the muted bell after the time whenever the Fan's notifications are muted, unread or not, so that muted Fans read as in Infloww (FL6).
15. As an Employee, I want the unread dot as an Edge marker at the row's left edge, 9px and centred on the avatar, with its count in its name and tooltip, so that unread stays visible without crowding the time (FL8).
16. As an Employee, I want the owe dot as an Edge marker in the same place and size, shown only when the unread dot is not, and only while FanList passes it today (Legacy flag on or Owe reply active), so that the Owe reply extra keeps its signal (FL8, ADR-0003).
17. As an Employee in All Models, I want the Creator's colour dot and, below lg, the Creator chip to stay on the row, so that I can still tell Creators apart.
18. As an Employee, I want the skeleton rows that show while the list loads to be 96px tall with a 40px circle, so that the list does not jump when rows land.
19. As an Employee, I want the selected row's background, the hover state, the right-click "Open in a new window" menu, the tooltip with spend details, and hover/press prefetch to behave as they do today, so that the restyle changes only the layout.

Header (Compare rows FL9–FL10):
20. As an Employee, I want the Fan List header's first row to hold the Creator's name (or "All Models") on the left and gallery, search and "+" on the right in that order, so that it matches Infloww (FL9).
21. As an Employee with a Fan open, I want the header's gallery icon to open that Fan's Chat gallery, the same sheet the Chat header's Gallery opens, so that I reach the media from the list as in the Clone.
22. As an Employee with no Fan open, I want the gallery icon disabled with the tooltip "Open a conversation to browse its media", so that it never opens an empty sheet.
23. As an Employee, I want search and the "+" New menu (Mass message, Message online fans, Post, and Broadcast behind the Legacy flag) to behave as today, so that the header change adds and moves nothing else.
24. As an Employee, I want the second header row to keep the "All inboxes" selector (Single-Creator scope only, as today), the gear, "Newest first" and the sort and refresh icons, so that it matches Infloww's second row (FL10), with the built-in filters, the Fan List Extras overflow, the folder chips and "✎ Lists" below it where they are today.
25. As an Employee on a phone, I want the gallery icon at the same phone tap size as search and "+", so that the header stays usable at 390.

Notifications toggle (Compare row FL11, `ours`):
26. As an Employee, I want a small switch at the right end of the Fan List buttons row, after Online Fans and Notifications, so that I can choose Infloww's badge-only button.
27. As an Employee, I want the switch on by default, so that nothing changes until I turn it off.
28. As an Employee with the switch on, I want Notifications to open the Notifications panel exactly as today (rows, filters, settings, quick Reply, Fan tabs), so that our panel stays.
29. As an Employee with the switch off, I want Notifications to show only its count badge and open nothing when clicked, so that it behaves as Infloww's does.
30. As an Employee with the switch off, I want the badge to keep counting new notifications, so that the count stays useful without the panel.
31. As an Employee who turns the switch off while the panel is open, I want the panel to close, so that the off state is what I see.
32. As an Employee, I want my choice to survive a reload and apply in Pop-out windows and other tabs of this browser, so that I set it once.
33. As one of two Employees sharing a browser, I want my switch to be mine, so that a colleague turning it off does not change my Fan List.
34. As an Employee whose identity has not resolved yet, I want the switch disabled and the panel behaving as on, so that a choice is never saved under the wrong Employee.
35. As an Employee using a screen reader, I want the switch to be a switch named "Notifications panel" that reports on or off, so that its state is announced.
36. As an Employee on a phone, I want the switch to fit the Fan List buttons row at 390 without overflow and at the phone tap size, so that the row stays one line.

Binding constraints:
37. As the product owner, I want the Fan List cache and the background refresh to stay exactly as they are, with the online dot, unread, owe dot, verified badge and spend read from the cached list and the existing spend batch, so that no row costs an extra relay call.
38. As a maintainer, I want every new px value in the Geometry token module and every colour left in JSX, so that ADR-0001 and ADR-0010 hold and the colour check still passes.
39. As a maintainer, I want the toggle to add no new storage key, so that the plan's storage decision holds.
40. As a reviewer, I want the Compare page rows FL1–FL11 to read "matched" (FL11 "ours"), or to name the remaining px with a reason (`remaining: <n>px — <reason>`, Phase 0's Named remainder), once this Phase lands, with a scripted check behind it, so that the Phase is graded with the plan's evidence.

## Implementation Decisions

- **Owns.** `FanRow`, `FanListHeader`, `FanListButtons`, `FanList` (it passes the open Fan to the header, and its skeleton rows come from `FanListStates`), `FanListStates` (skeleton row Geometry), the shared `NotificationBell` (the Messages Pro variant only), `notifSettings` and its hook `useNotificationSettings`, the `MP.fanList` Region of the Geometry token module `messagesPro`, and the Gap table snapshot in `messagesPro.test.ts`. The Compare page rows FL1–FL11 change status here. `scripts/ui-shots.sh` gains one check and no state.
- **Interfaces.**
  - `FanRow`: its props are unchanged. It already gets the chat, the profile, the spend facts, the selection, the owe dot and the All Models account. It reads the verified flag from the chat's `withUser` or the cached profile.
  - `OFUserMini` gains an optional `isVerified?: boolean`. This only types a field OnlyFans user objects carry. The relay does not change.
  - `FanListHeader` gains `galleryFan: { accountId: string; fanId: FanId } | null`. Non-null opens the Chat gallery for that Fan, and null disables the icon. It renders the existing `ChatGallery` component itself. Phase 3 still owns the Chat header's own Gallery.
  - `FanListButtons` takes no new props. It reads the Employee from `useEmployeeKey` and the choice from `useNotificationSettings`, renders the switch, and passes `panelEnabled` to the bell.
  - `NotificationBell`, Messages Pro variant only, gains `panelEnabled: boolean` (default true). While false, the button's click is a no-op apart from its title, the panel never renders, an open panel closes, and the arrival counter keeps counting. The top-bar variant is untouched.
  - `notifSettings` gets two pure helpers: `notifPanelOn(settings, employeeKey)` (true unless the key is listed) and `withNotifPanel(settings, employeeKey, on)`.
- **Schema.** The existing localStorage key `chatterly:notif-settings:v1` (`app/lib/notifSettings.ts:72`) gains one field. `NotifSettings` gets `panelOffFor: string[]`, the Employee keys (`useEmployeeKey` values) that turned the Notifications panel off. The default is `[]`, so every Employee starts on. `readNotifSettings` must carry the field through, because today it rebuilds the object from known fields only (`notifSettings.ts:74-83`) and would drop an unknown one on the next write. It keeps only string entries and reads a missing or malformed value as `[]`. No new key, no relay table, no migration.
- **Contracts.** No relay contract changes. The `chatterly:notif-settings` same-tab event and the cross-tab `storage` event, both already listened to by `useNotificationSettings`, carry the toggle to other bells and Pop-out windows.
- **Storage choice for the Notifications toggle.** The plan says "stored per Employee in the existing preferences key, no new storage key". Observation shows no key is both per-Employee and preferences:
  - The `preferences` Settings blob is per Agency, not per Employee. ADR-0007 keys it by `users.id`, it sits behind the admin-only `/admin/settings/{tab}`, which a chatter cannot write, and ADR-0008 says nothing reads it.
  - The per-Employee keys (`chatterly:creator-tabs:v1:<employeeKey>` and `chatterly:fan-tabs:v1:<employeeKey>`, `useCreatorTabs.ts:53`, `useFanTabs.ts:66`) hold tab state, not preferences.
  - `chatterly:notif-settings:v1` is the notification preferences key ("local preferences for the in-tab notification toaster", `notifSettings.ts:4`), and the Messages Pro bell already reads it through `useNotificationSettings` (`NotificationBell.tsx:181`).

  The toggle therefore lives in that key, made per Employee by listing `useEmployeeKey` values inside it. That is the same Employee identity the Creator tabs and Fan tabs stores file under (`hooks/useEmployeeKey.ts:33`).
  ASSUMPTION: the plan's "existing preferences key" is `chatterly:notif-settings:v1`, made per Employee by a `panelOffFor` list of Employee keys inside it (rung 3: the bell already reads that key, and per-Employee browser state is keyed by `useEmployeeKey`). Overturned if the human meant the `preferences` Settings blob. That would need a per-Employee shape inside an Agency blob, a chatter-writable route and an ADR-0008 amendment, because the blob would then be read.
- **Row Geometry** (from the 2026-10-12 empty-state capture, a 2x retina shot measured with `python3 -I` and PIL, in CSS px). Row pitch is 96px, the avatar is 40px with its top 17px below the row divider, the online dot is about 8px on the avatar's bottom-right edge, the spend pill sits directly under the avatar, and the ✕ is a small muted glyph near the right edge of line one. The shot outranks the Clone's 75px `.conv`, 48px `.av` and overlapping `.spend` (`messages.html:159-171`). The `MP.fanList` leaves for row, avatar, online dot, spend, skeleton row and skeleton avatar change to these values. New leaves cover the verified badge (14px, the Clone's `.vf`, `messages.html:177`), the ✕ (the Clone's `.cx`, 16px glyph, `messages.html:178`), the Edge marker placement and the gallery icon (FL3/FL4 sizes, like search). The Gap table snapshot in `messagesPro.test.ts` is updated leaf for leaf, and the leaves stay free of colour.
- **Edge markers.** They are absolute in the row's left padding, 9px (the existing unread and owe dot leaves), centred on the avatar's vertical centre. Unread wins over owe. They keep today's accessible names ("Unread (n)", "Read · awaiting your reply"). The muted bell leaves the unread/owe either-or and shows whenever `isMutedNotifications` is set.
  ASSUMPTION (evidence blocked): Infloww's own unread marker size is not in the extracted stylesheet (its chat-list rules belong to the embedded OnlyFans page, and grep of `messages.css` finds no list-row rule), and the captures show no unread row. The Clone's 9px `.ud` stands. Overturned by a capture that shows an unread row.
- **Spend under the avatar.** A spender now shows the avatar image and the spend pill. The orange figure no longer takes the avatar's place. This settles the parity doc's "the Clone's spend pill on every row" item (ticket 57, which was waiting on the human) by the plan's "spend under it" (rung 2). The spend tooltip is unchanged.
- **Verified badge.** It renders when `withUser.isVerified` or the cached profile's `isVerified` is true, and nothing new is fetched.
  ASSUMPTION (evidence blocked): the relay's cached chat rows and `/users/list` profiles pass OnlyFans's `isVerified` through. Confirming that needs a live payload, which is out of bounds. Overturned if they don't, in which case the badge ships dark, exactly as the parent effort's "New" badge did.
- **The ✕.** A span inside the row button, named "Not wired" with the tooltip "not wired". Its click and pointer-down stop propagation and do nothing, so it neither selects the row nor prefetches.
  ASSUMPTION: the ✕ is inert. The Clone gives it no handler, and no source names its action (parent Phase 2 spec, Out of Scope). Rung 4: an inert mark is cheaper to undo than a guessed write. Overturned if the human names the action (for example OnlyFans "hide chat", which the Kebab menu already offers). It would then call that existing action.
- **Gallery.** It follows the Clone's handler (`messages.js:3209-3212`): with a Fan open it opens that Fan's gallery, and otherwise it says "Open a conversation to browse its media". The Clone uses a toast. Ours uses a disabled icon with that tooltip, the house pattern for an unavailable control (`FanTabs.tsx:268`).
- **Notifications toggle drawing.** It reuses `SwitchTrack`, the Window header SFW's 26×14 track (house precedent). It is wrapped in a `role="switch"` button named "Notifications panel", with `aria-checked` and the tooltips "Notifications panel on" and "Notifications panel off". The button is `shrink-0`, after the two `flex-1` buttons, at the phone tap size used by the Fan List header icons. It is disabled while the Employee key is null.
  ASSUMPTION: the toggle is not added to the `openinflowwwwExtras` catalogue. It configures the Notifications panel, which is ours and is not catalogued either. Cataloguing it would put an extra outside any overflow with the Legacy flag off, which the plan's inline placement requires and the extras audit forbids. Rung 3 (the panel's precedent). Overturned if the human wants it catalogued. That needs a new Host and an ADR-0003 amendment.
- **Fan List cache and background refresh.** These are binding and untouched. No query is added, changed or re-keyed, there are no new `refetchInterval`s and no per-row requests, and `FanList`'s chats, spend batch and online list reads stay as they are. Every new row element derives from data already on the row or in the profile cache.
- **Colour.** This Phase adds no colour decisions. The new elements use the same token classes their neighbours use today (muted elements `text-fg-dim`, the verified badge `text-info`), and Phase 1 maps colours.

## Testing Decisions

The seams, highest first. No new test file is added.
- **The Messages Pro page render test** (`app/app/messages-pro/page.render.test.tsx`, the "Notifications (ticket 80)" block) covers the toggle end to end. It renders the page through the house provider wrapper with the relay mocked by URL. Its tests:
  - The switch is on by default and the panel opens.
  - Turning it off closes an open panel. A click then opens nothing, and the badge still shows the count route's number.
  - After a remount (a reload), the choice persists under the same Employee and is on again for a different Employee key.
  - `chatterly:notif-settings:v1` keeps its toast and bubble fields after a toggle.
  - No storage key other than the ones the page wrote before is written.
  - A `storage` event carrying another tab's write of `chatterly:notif-settings:v1` turns the switch off without a remount (the Pop-out and other-tab path, Story 32).
  - With the Employee key unresolved (null), the switch is disabled and Notifications opens the panel (Story 34).
  - The control is found by role `switch` and name "Notifications panel", and `aria-checked` flips with it (Story 35).
- **`FanRow` component tests** (`components/chat/FanRow.test.tsx`) render a row from raw facts with a fixed `now`. They cover:
  - Avatar present for a spender, and the pill text for known, zero and unknown spend. The existing assertion that spend replaces a spender's avatar (`FanRow.test.tsx:289-299`) is replaced by this one, not kept beside it.
  - The online dot.
  - The verified badge: one fixture with `isVerified: true` (on `withUser`, and separately on the cached profile) must render it, and one without the field must not.
  - The handle, and the badges after it.
  - The ✕ named "Not wired", where a click calls neither `onSelect` nor `prefetchNow`.
  - The muted bell shown on an unread muted row.
  - The Edge marker names: unread, owe, and unread winning.
- **`FanList` component tests** (`components/chat/FanList.test.tsx`): the header order (gallery, Search, New), the gallery disabled with no Fan open and opening "Chat gallery" with one open, and the relay URLs requested while rendering the fixture rows being the same set as before the Phase (no URL carrying a row's Fan id without hover or press).
- **The Gap table snapshot and colour check** (`lib/messagesPro.test.ts`): the updated `MP.fanList` leaves, and no colour in any leaf.
- **The extras audit** (`app/app/messages-pro/extras.test.tsx`) passes unchanged in both flag states. That proves the toggle and ✕ are not extras outside an overflow.
- **The visual loop** (`scripts/ui-shots.sh`) gets one new check, "a Fan List row is 96px tall", which reads the first fixture row's bounding box at 1440 and 390 and, in the same check, its avatar's box (40px square). Marker, bell, ✕ and header placement are graded by the `MP.fanList` snapshot and the manual Compare step, not by the harness. Its existing overflow sweep covers the buttons row at 390.

Prior art: `FanRow.test.tsx` (row from raw facts), the page test's ticket 80 block (Notifications badge from the count route), the SFW switch test in the page test (`role="switch"` flip), and `lib/messagesPro.test.ts` (Gap table snapshot).

## Acceptance

```sh
# Seams of this Phase
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run lib/messagesPro.test.ts components/chat/FanRow.test.tsx components/chat/FanList.test.tsx app/messages-pro/page.render.test.tsx app/messages-pro/extras.test.tsx

# The toggle lives in the existing notification preferences key; no new storage key
grep -q "panelOffFor" app/lib/notifSettings.ts
! grep -nE "localStorage|sessionStorage" app/components/chat/FanListButtons.tsx app/components/chat/FanRow.tsx app/components/chat/FanListHeader.tsx

# Fan List cache and background refresh untouched
# (1d2a1995 is the effort's last commit before any Phase code)
git diff --quiet 1d2a1995 -- app/hooks/useChatList.ts app/hooks/useFanSpend.ts app/hooks/useRecentChatsLocal.ts app/components/providers.tsx
! git diff 1d2a1995 -- app/components/chat/FanList.tsx app/components/chat/FanRow.tsx | grep -E "^\+.*(useQuery|useQueries|refetchInterval|relay\.(get|post|put))"

# Full suite
.scratch/messages-pro-look-and-feel/suite.sh

# Visual loop
scripts/ui-shots.sh
python3 -I -c "import json,sys; r=json.load(open('docs/screenshots/messages-pro-report.json')); sys.exit(0 if r['ok'] else 1)"
grep -q "a Fan List row is 96px tall" scripts/ui-shots.sh
# manual (before the gate below): Read docs/screenshots/messages-pro-desktop.png and messages-pro-phone-list.png beside the 2026-10-12 empty-state capture (never committed); set Compare rows FL1-FL10 to "matched" with ours' px, or leave "differs" with "remaining: <n>px — <reason>" in Ours; FL11 stays "ours"; record any remaining px difference as a VISUAL GAP: line.
# Compare page (Phase 0): FL1-FL11 exist; each owned FL row is matched, FL11 ours, or differs naming the remaining px with a reason
python3 -I - FL 1 11 FL11 <<'PY'
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
```

## Depends on

- **Phase 0 — Measure and pin.** A hard dependency. The plan says every Phase 1–5 item "must appear here first" (`docs/plans/messages-pro-look-and-feel.md:33`), so no Phase 2 ticket is claimed until `docs/screenshots/messages-pro-compare.md` exists with rows FL1–FL11. This Phase turns them to "matched" (FL11 "ours").
- Phase 1 (Colour and shell) is not a dependency. It edits the same components' colour classes, so whichever lands second rebases. The coordinator should land Phase 1 first to keep the colour diff separate.
- Phase 3 (Chat header) shares `ChatGallery`. This Phase only renders it from the Fan List header and does not change it. If Phase 3 changes its props, whichever lands second rebases.

## Out of Scope

- **A wired ✕ action.** No source names it, and building a guess would fake a control (see the ASSUMPTION above).
- **A new relay field or call for the verified flag.** This is binding: no extra relay calls per row, and the cache stays as it is.
- **Infloww's time format ("10:28 pm").** Not a plan item for this Phase. The parity doc keeps it with ticket 54 for the human.
- **The "Unread tips" chip and the "Needs reply" order.** Not in this plan. The parity doc keeps them out of this effort.
- **Fan List pane width (390 vs the capture's about 400).** Not a Phase 2 item. It stays as the parent effort pinned it (PN2) unless the Compare page assigns it.
- **Row colours, the muted row's dimmer preview tint, and the Fan List buttons' fills.** Colour is Phase 1's (ADR-0010).
- **A server-side or cross-device toggle store.** The plan forbids a new storage key, and the existing per-Employee browser stores set the precedent.
- **Moving the Online Fans / Notifications buttons or the Notifications panel's contents.** The plan keeps the panel as it is today.
- **Restyling the Chat gallery sheet.** Phase 3 owns the Chat header and its Gallery.

## Further Notes

- The capture the row Geometry was measured from holds real names and handles. Only px values were taken from it, nothing from it is committed, and no name or handle from it appears here.
- The Compare page's FL row IDs (Phase 0) are not the parent effort's FL1–FL50 Gap IDs in the token module's comments. The token comments keep their Gap IDs, and the spec and tickets cite Compare rows as "Compare row FLn".
- ASSUMPTION: the "All inboxes" selector stays hidden in All Models, as today (`FanList.tsx:809`), although the capture shows it in a single-Creator scope only. Rung 5: the plan asks only that it sit in the second row, which it already does. Overturned if the human wants it visible in All Models.
- ASSUMPTION: the muted bell shows on unread muted rows too, where today it is suppressed. Rung 1 for Infloww's row (the capture shows the bell after the time). Rung 6 for the unread case, which no capture shows. Overturned by a capture of an unread muted row without the bell.

## Review

Reviewer: codex, 2026-10-15. Blind call (B) then draft call (D).

- B1 Clone 75px row vs 96px; no capture in the repo. **reject**: the plan ranks the captures over the Clone (plan Decisions, ground-truth order), and the spec measured 96px from the 2026-10-12 capture under ~/Downloads, which floor 2 and the brief keep out of the repo by design.
- B2 ✕ decorative or an action. **reject**: already decided inert, with an ASSUMPTION and an overturn clause; the reviewer's own evidence (`messages.js:501-516`, no handler) supports that.
- B3 what the new gallery opens is unspecified by the plan. **reject**: the spec specifies it from the Clone's handler (`messages.js:3209-3212`).
- B4 the toggle must not turn the panel into a Legacy-gated or deleted extra. **reject**: covered: the panel stays on by default, and the extras audit runs unchanged in both flag states.
- B5 the plan gives Phase 2 no acceptance. **reject**: the spec supplies its own Acceptance block; that is what the spec is for.
- B6 the plan does not say if owe gating stays. **reject**: Story 16 keeps today's gating (`FanList.tsx:296-303`).
- B7 the plan's second row leaves out the filters, the Extras overflow and the folder chips / "✎ Lists". **accept**: the Solution and Story 24 now state they stay where they are.
- B8 the key is unnamed; unresolved Employee, cross-window and migration behaviour unspecified. **reject**: the Storage choice section names the key, keeps it per Employee by listing keys, handles a null key (Story 34) and cross-tab sync (Contracts), and needs no migration (default `[]`).
- B9 harness `ok` is not evidence of geometry, and unmatched requests are not gated. **partial**: the harness check now also measures the 40px avatar; the no-extra-relay-call proof stays in `FanList.test.tsx`, which does gate requested URLs, not in the harness.
- B10 a capture with different geometry would falsify the premise. **reject**: that capture was measured; the result is the spec's Row Geometry.
- D1 Phase 0 written as a soft dependency against the plan's "must appear here first". **accept**: Depends on now makes Phase 0 a hard dependency for claiming any Phase 2 ticket.
- D2 the inline owe marker conflicts with ADR-0003. **reject**: ADR-0003 puts the Owe reply filter in the overflow. The owe dot shows only with the Legacy flag on or after the Employee picks Owe reply from that overflow (`FanList.tsx:296-303`), which the parent effort recorded as the extra's own output (`docs/messages-pro-parity.md:51`, ticket 48). The plan names the owe dot as a row marker (rung 2), and the extras audit gates it unchanged.
- D3 the verified badge can ship dark, and "shown or absent" passes without a positive fixture. **partial**: the FanRow test now requires an `isVerified: true` fixture to render the badge. Whether the relay passes the field through still needs a live payload (out of bounds). OnlyFans payload fixtures carry it (`~/gateway/services/upstream/tests/fixtures/payloads/messages.received.json`), so the evidence-blocked ASSUMPTION stands.
- D4 no test for cross-tab/Pop-out sync, null identity or switch semantics, and the visual check only measures height. **accept** for the toggle: three page-test cases added (storage event, null key, role and `aria-checked`). **partial** for the visual: the avatar size was added; the rest of the placement is graded by the `MP.fanList` snapshot and the manual Compare step, since the plan grades by the Compare page.
- D5 the gallery behaviour is scope the plan never asked for, and Phase 3 overlap is missing from Depends on. **partial**: the behaviour stays, because an icon that opens nothing would fake a control and the Clone defines what it does. The `ChatGallery` overlap with Phase 3 is now in Depends on.
- D-note: `FanRow.test.tsx:289-299` asserts the old spender behaviour. **accept**: the Testing section now says that assertion is replaced.

Counts: accept 4 (D4 counted here; its visual half is partial), partial 3, reject 9, needs-human 0.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- White, FL1–FL10 flipped by hand with no scripted check: **accept**. The Acceptance now ends with a scripted Compare gate: FL1–FL11 exist with seven cells, and every required or owned FL row is `matched`, FL11 `ours`, or `differs` with `remaining: <n>px — <reason>` in Ours. Story 40 says so.
- Green/Black, gate strictness: **accept**. The gate takes Phase 0's Named remainder form, not strict `matched` (rung 5, plan:85 asks sign-off to name the px left; strict `matched` is only the CO rows', plan:44).
- Blue, serial landing: **accept** (recorded in plan-review.md). Depends on keeps Phase 1 a soft order; plan-review.md lands Phases serially 0→6 because they share `messagesPro.ts`, `ui-shots.sh`, `openinflowwwwExtras.ts`, `ChatSurface` and the Compare page.
