# Phase 04 — Composer, PPV row, Vault picker

**Objective.** When this Phase is done, the Thread's Composer has the Clone's two rows in the Clone's order and Geometry (the button row with the input inside it, and the bottom toolbar ending in Send), plus a PPV row, Timed message and Timed reminder, emoji favourites, the AI Translator and an Extras overflow, and the Vault picker opened from it shows the Fan-specific card metadata the relay exposes — all without changing what a send puts on the wire.

## Gap table

Measured from `ui-redesign/infloww-exact/messages.html` (CSS and markup), `messages.js` (wiring), and `docs/infloww-screens.md` §3.3 (lines 209–227). Colours are left out on purpose: ADR-0001 takes colour from `app/app/globals.css` tokens, never from the Clone. `_shared/components.html` §6 (`.fx-composer`, line 159 on) is the Inflowwww mass-message composer, not Messages Pro, so this table does not use it.

| # | Clone selector · CSS (file:line) | Ours (file:line) | Gap | Change |
|---|---|---|---|---|
| 1 | `.composer` (messages.html:269): `border-top:1px; padding:12px 16px 14px` | Composer.tsx:501: `border-t px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] space-y-2` | x-padding 12→16; bottom 12→14; one 8px stack gap instead of per-row margins | `px-4 pt-3 pb-[max(14px,env(safe-area-inset-bottom))]`; per-row margins (rows 2, 10) replace `space-y-2` |
| 2 | `.comp-r1` (messages.html:270): `flex; align-items:center; gap:10px; margin-bottom:6px`. Children (726–731): emoji, ⚙, input, "AI", "Scripts", alarm | None. Our controls row (Composer.tsx:866) sits above a separate textarea (Composer.tsx:953) | No button row, and the input is not inline | New button row: `flex items-center gap-[10px] mb-[6px]`. Order: emoji, ⚙, input, "AI", "Scripts", "PPV", ⏱, "+" |
| 3 | `.icon-btn` (messages.html:77) `26×26; border-radius:7px`; `.comp-r1 .icon-btn svg` (272) `20px` | EmojiBar.tsx:1007 `w-8 h-8 rounded-md` (32px, 6px) | 32→26px; radius 6→7px | Button-row icons: `w-[26px] h-[26px] rounded-[7px]`, 20px glyph |
| 4 | `.pill` (messages.html:273–275): `gap:6px; border:1px; border-radius:16px; padding:6px 12px; font-size:13px; font-weight:600`; svg `15px` | TemplatePicker.tsx:221 `w-8 h-8` "⌘"; LinesPicker.tsx:108 `px-2 py-1 rounded-md text-xs` "Lines"; no PPV control | Labels, shape and size; "PPV" missing | Pills `gap-1.5 border rounded-[16px] px-3 py-1.5 text-[13px] font-semibold`, 15px icon, labelled "AI", "Scripts", "PPV" |
| 5 | `.comp-input input` (messages.html:276–277): `flex:1; background:transparent; border:none; font-size:15px; padding:6px 2px` | Composer.tsx:953–966: textarea on its own row, `bg-bg border rounded-lg px-3 py-2 text-base md:text-sm min-h-[44px] max-h-48 resize-y`, `rows={2}` | Position, border, 14→15px, two rows, resize handle | The textarea moves into the button row as `flex-1`. Transparent and borderless, `px-0.5 py-1.5 text-base md:text-[15px]`, one row that grows to `max-h-48`, no resize handle. `text-base` below md keeps the iOS no-zoom rule (Composer.tsx:961–965) |
| 6 | Placeholder (messages.html:728) `Press "/" + keyword to quickly search scripts` | ChatSurface.tsx:1160 passes `Message ${headerName}…`; Composer.tsx:960's "Type a message…" is only the fallback when no placeholder is passed | Label differs | No change: "/" search does not exist yet (see Out of Scope) |
| 7 | `.comp-r2` (messages.html:279) `gap:6px`; `.comp-r2 .icon-btn` (280–281) `34×34`, svg `20px`, radius `7px` (77) | Composer.tsx:866 `gap-1.5`, bordered `h-8` controls; Vault Composer.tsx:873 `h-8 px-2.5` "📎 Vault"; GifPicker.tsx:234 and TagCreatorsPicker.tsx:164 `w-8 h-8` bordered | 32→34px; borders; text label on Vault | Toolbar `flex items-center gap-1.5`; borderless `w-[34px] h-[34px] rounded-[7px]` icons, 20px glyphs |
| 8 | `.comp-r2` order (messages.html:755–763): upload, GIF, vault, calendar, tag, @, "Aa", translate, Send (§3.3:211 agrees) | Composer.tsx:866–950: Vault, `$` price, 🕐, emoji, GIF, ⌘, Lines, tag; Send in its own column (Composer.tsx:968) | upload, @, "Aa" and translate are missing; emoji, ⌘, Lines and `$` belong elsewhere | Clone order. Emoji goes to the button row, ⌘ becomes the "Scripts" pill, Lines becomes the "AI" pill, and `$` moves to the PPV row |
| 9 | `.send-btn` (messages.html:283–284): `margin-left:auto; font-size:14px; font-weight:700; padding:10px 26px; border-radius:9px`; inactive until `.active` | Composer.tsx:970–1013: `Button size="sm"` (primitives.tsx:40 `px-3 py-1.5 text-xs`, `rounded-lg`) plus a ▾ quick-send split (Composer.tsx:980–1012) | Smaller; different radius; the split menu is not in the Clone | `ml-auto px-[26px] py-[10px] rounded-[9px] text-sm font-bold`. The ▾ split and its +1…+15 min presets are removed, because Timed message covers 1–60 min |
| 10 | `.comp-x` (messages.html:514–518): hidden unless `.on`; `flex; flex-wrap; align-items:center; gap:8px; padding:0 0 8px; font-size:12.5px`; inputs `border:1px; border-radius:7px; padding:6px 8px; font:13px`; number input `width:92px` | Composer.tsx:579–608: a box (`bg-bg/60 border rounded-lg px-2.5 py-1.5`), `text-xs`; price input Composer.tsx:590 `w-20` with no border; shown only when `priceOpen && price > 0` (Composer.tsx:579) | Boxed instead of bare; 80→92px; borderless inputs; visibility rule | `PpvRow`: no box, `flex flex-wrap items-center gap-2 pb-2 text-[12.5px]`; inputs `border rounded-[7px] px-2 py-1.5 text-[13px]`; price `w-[92px]`; visibility rule from messages.js:1838 (see Implementation Decisions) |
| 11 | `.comp-x` children (messages.html:739–753): "PPV" (`font-weight:700`), "$" + input (gap 5px), checkbox + "lock text" (gap 5px), free previews, attachments, "at" + datetime-local, "Clear" | Composer.tsx:581–606: "PPV", "$", "lock text" and a "Fan pays $X to read" hint. Scheduling is a separate row (Composer.tsx:536–577) and attachments a separate tray (Composer.tsx:626–785) | "at", "Clear" and in-row attachments are missing; the hint is extra | Clone order. The hint becomes the price input's tooltip. Free previews move to the Extras overflow (row 15) |
| 12 | `.btn-sm` (messages.html:499): `border-radius:7px; padding:7px 12px; font-size:12.5px; font-weight:600` | None | "Clear" is missing | "Clear": `ml-auto rounded-[7px] px-3 py-[7px] text-[12.5px] font-semibold` |
| 13 | `.att .a` (messages.html:520–522): `42×42; border-radius:7px; border:1px`; ✕ top-right, 10px | Composer.tsx:710 `w-16 h-16 rounded-md`; ✕ Composer.tsx:743–750; a price input on every tile (Composer.tsx:752–772); GIF chips in their own tray (Composer.tsx:800–823) | 64→42px; 6→7px; a duplicate price input per tile; separate GIF tray | 42px tiles, `rounded-[7px]`, inside the PPV row. The per-tile price input is removed. GIF chips join the same row. Drag reorder and the FREE/PPV/BOUGHT badges stay |
| 14 | `#schedWrap` (messages.html:749–751): "at" + datetime-local, shown in schedule mode | Composer.tsx:536–577: a separate "Send at" row with +5/10/15/30/60m presets and descriptive text | A separate row; extra presets | "at" sits inside the PPV row. The presets move to the Extras overflow as an Inflowwww extra (see The PPV row), and the descriptive text becomes the input's tooltip |
| 15 | `#prevStep` (messages.html:742–747): the free previews stepper is in the row; §3.3:219 tags it ours | Composer.tsx:631–655 | It is an Inflowwww extra | Moves to the Composer's Extras overflow (plan Phase 4, ADR-0003) |
| 16 | `#cbSched` alarm clock (messages.html:731), last in the button row. The Clone wires it to the schedule sheet (messages.js:2475); §3.3:213 says ⏱ is Timed message / Timed reminder | Composer.tsx:980–1012, the ▾ +1…+15 min menu | Different control | The ⏱ trigger opens `TimedMessagePopover` |
| 17 | `#cbCal` (messages.html:758), which toggles schedule mode (messages.js:2476) | Composer.tsx:914–926: 🕐 `w-8 h-8` bordered | Icon and position | Calendar icon in the toolbar; toggles "at" in the PPV row |
| 18 | `#cbUpload` (messages.html:755), which opens the vault (messages.js:2415) | None | Missing | The upload icon opens the Vault picker |
| 19 | `#cbMention` (messages.html:760), which inserts `@` + the Fan's username (messages.js:2495–2500) | None | Missing | @ inserts the Fan's `@username` at the cursor |
| 20 | `#cbAa` (messages.html:761): `font-weight:800; font-size:15px`; marked static (messages.js:3386) | None | Missing | "Aa" at `font-extrabold text-[15px]`, Not wired |
| 21 | `#cbTranslate` (messages.html:762); §3.3:215 "Translate messages from fans into" > "Use translation" | Nothing in the Composer; the Chat header has a 🌐 toggle (ChatSurface.tsx:963–976) | Missing from the Composer | The translate icon opens the Translator popover over the existing translate mode |
| 22 | `#cbEmoji`, `#cbGear` (messages.html:726–727). The Clone's ⚙ is a composer-options menu (messages.js:3158–3171); §3.3:212 says ⚙ is emoji favourites (40, "Save") | Emoji button in the toolbar (Composer.tsx:928); EmojiQuickRow above it (Composer.tsx:526); keyboard hint (Composer.tsx:527–533) | ⚙ is missing; the quick row and the hint are not in the Clone | ⚙ = emoji favourites. The quick row moves to the Extras overflow. The hint moves to Send's tooltip |
| 23 | `.reply-strip` (messages.html:525–531, markup 733–737) between the button row and `.comp-x` | Composer.tsx:509–524, top of the Composer | Position | Moves below the button row. Its styling belongs to Phase 3 |
| 24 | `.pop` (messages.html:361–363): `border-radius:10px; padding:6px; min-width:238px; max-width:360px; max-height:72vh; font-size:13px`; `.phead` (370) `10.5px/700 uppercase; padding:8px 10px 4px`; `.prow` (364) `gap:9px; padding:8px 10px; border-radius:7px` | TemplatePicker.tsx:240 `w-80 rounded-lg`; LinesPicker.tsx:113 `w-80 max-h-80 rounded-lg p-2` | Width, radius and padding | Applied to this Phase's new popovers (Timed, Translator, favourites, Extras overflow). The panels of the existing pickers stay as they are, because other composers share them |
| 25 | `.sheet` (messages.html:383–384): centred, `width:min(900px,92vw); max-height:84vh; border-radius:14px`; `.sheet-h` (385) `padding:13px 16px; 14px/700`. The Clone's Vault opens through the same generic `sheet()` (messages.js:135–140, :2111) as its Chat gallery, GIF and Notifications | VaultPicker.tsx:1029 right slide-over `max-w-3xl`, full height; header VaultPicker.tsx:1030 `px-4 py-3` | Slide-over instead of a centred sheet; header padding and type | In Messages Pro mode only (a new optional `VaultPicker` prop that only `Composer` passes): centred `w-[min(900px,92vw)] max-h-[84vh] rounded-[14px] border`; header `px-4 py-[13px] text-[14px] font-bold`. Below md it stays full-screen, as Phase 3 does for its gallery sheet |
| 26 | `.mgrid` (messages.html:390) `repeat(auto-fill,minmax(118px,1fr)); gap:10px`; `.mgrid .mt` (391) `border-radius:9px` | VaultPicker.tsx:1242 `grid-cols-3…7 gap-2`; VaultPicker.tsx:1346 `rounded-md` | Grid and radius | In Messages Pro mode: `grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-[10px]`; tiles `rounded-[9px]` |
| 27 | `.mgrid .mt .vdur` (messages.html:396) `right:6px; bottom:6px` | VaultPicker.tsx:1544 `bottom-1 right-1` (4px) | 4 vs 6px | In Messages Pro mode: `right-[6px] bottom-[6px]` |
| 28 | `.vtb input[type=search]` (messages.html:442) `min-width:128px`; §3.3:226 search covers hashtag, note and previous PPV caption | VaultPicker.tsx:1113–1120 `w-32 md:w-40`, placeholder "Search vault…" | Label | When a Fan is in scope, placeholder "Search hashtag, note or caption". Width unchanged |
| 29 | §3.3:223–226 card (no Clone selector): red status icon, last price, notes, tags, grey overlay when the Fan has it, ⓘ "Media details", price history, unsend at the lower left, duration filter | VaultPicker.tsx:1584–1600 status pill (status + last price); a captions toggle (VaultPicker.tsx:1133–1150, off by default) that shows tags; no overlay, ⓘ, unsend or duration filter | Overlay, ⓘ, history, unsend, duration filter, always-on tags and notes are missing | Added when a Fan is in scope. Sizes are not in the Clone (see the ASSUMPTION lines under Implementation Decisions) |

ASSUMPTION: the picker shell (rows 25–27) follows the Clone's generic sheet. The comment at messages.js:2064–2066 claims parity with our picker in data source, filters, folder chips and caption overlays, not in Geometry, and our slide-over is not what the Clone draws. The card additions in row 29 have no Clone selector, so they take their offsets from the Clone's other tile badges (`.vdur`/`.vlock`, 6px insets, messages.html:396, :404). Overturned by a real Infloww Vault Pro window screenshot.

## Problem Statement

An Employee who learned Infloww opens our Thread and finds a different Composer. The input is a boxed textarea on its own row. Controls are text-labelled buttons in an order Infloww never used (📎 Vault, `$`, 🕐, emoji, GIF, ⌘, Lines, tag). The PPV fields appear only after a price is typed. Scheduling lives in a separate row of presets, and a ▾ menu hides the delayed sends. There is no ⏱ Timed message or Timed reminder, no emoji favourites, and no translate button where Infloww puts it. "Upload", "@" and "Aa" are missing altogether. The Vault picker shows a status pill. It does not grey out media the Fan already has, it cannot open media details or price history, and it cannot filter by duration. Muscle memory from Infloww fails on every send, and that slows the selling work.

## Solution

The Composer is rebuilt to Infloww's layout. It has a button row (emoji, ⚙ favourites, the input, "AI", "Scripts", "PPV", ⏱, and a "+" Extras overflow at the end) and a bottom toolbar (upload, GIF, vault, calendar, tag, @, "Aa", translate, "Send"). Between them sit the reply strip and a PPV row: "PPV", "$", "lock text", the attached media, "at" and "Clear". ⏱ holds a Timed message (1–60 min, "Start") and a Timed reminder (a countdown that sends nothing). ⚙ edits up to 40 favourite emojis. The translate icon turns on the existing "translate messages from fans" mode. Controls the relay cannot perform ("Aa", release forms, unsend) appear Not wired instead of pretending. Our extras (free previews, the "at" presets, the quick emoji row) are kept in the Composer's "+" overflow, marked "Inflowwww extra". The Vault picker opened from a Thread opens as the Clone's centred sheet, greys out media the Fan already has, and shows tags. ⓘ opens "Media details" with the Fan's price history, and a duration filter is added. Sends behave exactly as before.

## User Stories

1. As an Employee, I want the Composer laid out as Infloww's button row above a bottom toolbar, so that my Infloww muscle memory works here.
2. As an Employee, I want the button row ordered emoji, ⚙, input, "AI", "Scripts", "PPV", ⏱, so that every control sits where Infloww puts it.
3. As an Employee, I want the bottom toolbar ordered upload, GIF, vault, calendar, tag, @, "Aa", translate, "Send", so that I find each icon by position.
4. As an Employee, I want to type in an inline, borderless input that grows with my text, so that the Composer stays compact like Infloww's.
5. As an Employee, I want Enter to send and Shift+Enter to insert a newline, so that typing works as it did before.
6. As an Employee, I want the emoji button to open the emoji picker and insert at my cursor, so that I can add emojis mid-sentence.
7. As an Employee, I want ⚙ to open an emoji favourites editor where I pick up to 40 emojis and press "Save", so that my usual emojis are one click away.
8. As an Employee, I want the editor to refuse a 41st favourite and show my count out of 40, so that I know the limit.
9. As an Employee, I want my favourites shown first in the emoji picker and kept after a reload, so that I set them once.
10. As an Employee, I want the "AI" pill to show this Fan's suggested lines and insert my pick without sending it, so that I can edit before sending.
11. As an Employee, I want the "Scripts" pill to open my saved scripts and load the chosen one (text, media, price) into the Composer, so that I can send prepared content fast.
12. As an Employee, I want the suggestion for the next step of a script to keep appearing after I send a step, so that I can follow a sequence.
13. As an Employee, I want the "PPV" pill to open and close the PPV row, so that I can make the next send a PPV.
14. As an Employee, I want the PPV row to show "PPV", "$", "lock text", my attachments, "at" and "Clear" in that order, so that it reads like Infloww's.
15. As an Employee, I want the PPV row to open by itself when I attach media or a GIF, turn on scheduling, or set a price, so that I always see what will be sent.
16. As an Employee, I want a price above 0 to make the send a PPV at that price, with the text locked only when "lock text" is ticked, so that I control what the Fan sees before paying.
17. As an Employee, I want "lock text" to stay off by default, so that text is not locked unless I choose to lock it.
18. As an Employee, I want "Clear" to reset the price, lock text, "at", attachments, GIFs and free previews while keeping my typed text, so that I can start the paid part over without retyping.
19. As an Employee, I want the calendar icon to show the "at" field and the Send button to read "Schedule" when a future time is set, so that I can queue a Scheduled message.
20. As an Employee, I want ⏱ "Timed message" to take a whole number of minutes from 1 to 60 and send my draft that many minutes later when I press "Start", so that I can hold a message without picking a date.
21. As an Employee, I want "Start" disabled for an empty draft, a value outside 1–60, or GIFs that cannot be timed (more than one, or one beyond 15 minutes), so that I cannot queue something invalid or have part of it go out at once.
22. As an Employee, I want to cancel a queued Timed message the same way I cancel any scheduled send, so that I can undo it.
23. As an Employee, I want ⏱ "Timed reminder" to start a 1–60 minute countdown that sends nothing, so that I get a nudge to follow up with this Fan.
24. As an Employee, I want a running reminder shown as a countdown with ✕ to cancel it, so that I can see it and stop it.
25. As an Employee, I want an alert in the Thread when the reminder reaches zero, and an OS notification if I already allowed notifications, so that I notice it.
26. As an Employee, I want a reminder to survive switching chats and reloading, and to fire the next time I open the Thread if it ran out while I was away, so that I never lose a reminder silently.
27. As an Employee, I want the upload icon to open the Vault picker, so that I reach my media from the icon where Infloww puts upload.
28. As an Employee, I want the GIF icon to open GIF search and show a picked GIF in the PPV row, so that I can review it before sending.
29. As an Employee, I want the vault icon to open the Vault picker and show picked media as small tiles in the PPV row, with the price filled in from the most expensive pick, so that I never undercharge a bundle.
30. As an Employee, I want to reorder attached tiles and see the FREE/PPV/BOUGHT badges, so that I control the teaser order and avoid reselling bought media.
31. As an Employee, I want the tag icon to open "Tag other Creators" where I choose creators and press "Add", so that tagging works the way it does in Infloww.
32. As an Employee, I want "More" › "Add a tag" › "Release form" visible but marked not wired, so that I know it exists and that this app cannot do it yet.
33. As an Employee, I want @ to insert the Fan's @username at my cursor, and to be disabled when the username is unknown, so that I can mention the Fan.
34. As an Employee, I want "Aa" shown disabled with the tooltip "not wired", so that I am not misled into thinking formatting will reach the Fan.
35. As an Employee, I want the translate icon to open "Translate messages from fans into" with "Use translation", so that I can read Fans who write in other languages.
36. As an Employee, I want that switch to show and change the same state as the Thread's existing translate toggle, so that the two never disagree.
37. As an Employee, I want "Send" at the right end of the toolbar, highlighted only when there is something to send, so that I see at a glance whether the message is ready.
38. As an Employee, I want to see how many sends are in flight and find the keyboard hint in Send's tooltip, so that I keep that feedback without the extra row.
39. As an Employee, I want the free previews stepper inside the Composer's "+" overflow, enabled only for a priced PPV with attachments and marked "Inflowwww extra", so that our extra stays available without displacing Infloww's controls.
40. As an Employee, I want the quick emoji row inside the same overflow and marked "Inflowwww extra", so that I keep one-click recent emojis.
41. As an Employee, I want the Composer to keep showing why a chat cannot be sent to, with Send and Timed message "Start" disabled, so that I do not send a message that will fail.
42. As an Employee, I want the reply strip to stay attached to the Composer, between the button row and the PPV row, so that I can still see what I am replying to.
43. As an Employee on a phone, I want both Composer rows to wrap with no horizontal scroll and the input kept above the iOS home bar, so that the Composer works at 390px.
44. As an Employee, I want my sends to carry exactly the same text, price, lock, previews, media, tags, GIF and schedule as before for the same input, so that the redesign does not break selling.
45. As an Employee, I want media the Fan already has (bought, or sent free) greyed out in the Vault picker, so that I do not send it again.
46. As an Employee, I want every card to keep its status icon and last price, so that I see what happened with this media and this Fan.
47. As an Employee, I want a card to show its tags when the vault has them, and an empty notes slot when it has none, so that I see real metadata and nothing made up.
48. As an Employee, I want ⓘ on a card to open "Media details" with the media preview, its type, duration, date, tags and notes, so that I can inspect it without leaving the picker.
49. As an Employee, I want "Media details" and the card's price pill to show the price history ("Purchased", "Sent (free or paid)", "Unsent (free or paid)", "Posted in feed") from our data, with "—" where we have none, so that I price from facts.
50. As an Employee, I want an unsend icon at the lower left of each card already sent to this Fan, shown as not wired, so that I know the action exists and that it is not available yet.
51. As an Employee, I want vault search to say it covers hashtags, notes and captions, and to search tags, descriptions and OnlyFans captions, so that I find media the way I describe it.
52. As an Employee, I want a duration filter in the Vault picker, so that I can find videos of a given length.
53. As an Employee working elsewhere (settings, mass message, post, automations), I want those vault pickers and composers unchanged, so that this Phase changes only Messages Pro.
54. As a maintainer, I want vitest suites for the toolbar order, the PPV row, the Timed message range and the Vault picker overlay and search, so that regressions fail in CI.
55. As a maintainer, I want `messages-pro-composer-ppv.png` rendered by the harness and compared with the Clone, so that visual parity is checked and any remaining gaps are written down.
56. As an Employee, I want the "at" presets (+5, +10, +15, +30, +60 min) inside the Composer's "+" overflow, marked "Inflowwww extra", so that I can still fill "at" in one click.
57. As an Employee, I want the Vault picker opened from the Composer to open as a centred sheet with Infloww's grid, so that it sits where Infloww puts it.

## Implementation Decisions

- **Owns.**
  - `Composer`: keeps all its state, `submit`, `onPicked`, `onPickTemplate` and the script cursor. Only its render (the chrome) is replaced.
  - `ComposerToolbar` (new): the button row and the bottom toolbar.
  - `PpvRow` (new): the PPV row.
  - `TimedMessagePopover` (new): Timed message and Timed reminder.
  - `EmojiBar`: emoji favourites.
  - `TemplatePicker`, `LinesPicker`, `GifPickerButton` (in `GifPicker`), `TagCreatorsPicker`: an optional Messages Pro trigger and labels.
  - `VaultPicker`: the Messages Pro sheet shell, card additions when a Fan is in scope, and "Media details".
  - `ChatSurface`: one new prop on its `Composer` element (the Fan's username) and nothing else.
  - Reused unchanged: `VaultPreviewMedia` (vault browser), `useTranslateMode`, `useTranslations`, `useFanVaultHistory`, `useWallMedia`, `insertAtCursor`, `EmojiQuickRow`.

- **Interfaces.**
  - `Composer`: the props are unchanged except for a new optional `fanUsername`. `SendArgs`, `ComposerApi` and the exported `sanitizePriceInput` are unchanged. Four modules outside the chat folder import `sanitizePriceInput`.
  - `ComposerToolbar`: renders two `role="toolbar"` rows, labelled "Composer buttons" and "Composer toolbar".
    - It receives the input and each stateful picker as named slot nodes: emoji, favourites, AI, Scripts, Timed, GIF and tag. Each of those already owns its own popover.
    - It receives state flags: PPV row open, schedule on, can send, the send label, the in-flight count, disabled, and whether a mention is possible.
    - It receives one callback per plain control: toggle PPV, upload, vault, calendar, mention and send.
    - It owns the plain buttons (the "PPV" pill with `aria-pressed`, upload, vault, calendar, @, "Aa", "Send"), the Translator popover, and the Extras overflow ("+", whose content arrives as a slot).
    - It holds no send state.
  - `PpvRow`: a controlled `role="group"` labelled "PPV row". Props: price and its change handler, lock text and its handler, schedule-on with the "at" value and its handler, `onClear`, and the attachment tiles as children. `Composer` decides when it is visible.
  - `TimedMessagePopover`: the ⏱ trigger (accessible name "Timed message") with two tabs, "Timed message" and "Timed reminder". Each tab has a minutes field and "Start". Props: account, Fan, can-send, and `onStart(minutes)` for the Timed message.
    - The same module owns the Timed reminder outright: a reminder store at module level, persistence, and the countdown and alert strip, exported for the Composer's notice area.
  - `EmojiBar`: adds a ⚙ `EmojiFavouritesButton` (accessible name "Emoji favourites") and the favourites store. `EmojiPickerButton` takes an optional Messages Pro mode that puts a "Favourites" tab first when favourites exist.
  - `TemplatePicker`, `LinesPicker`, `GifPickerButton`, `TagCreatorsPicker`: each takes one optional prop that selects the Messages Pro trigger: "Scripts" pill, "AI" pill, 34px GIF icon, 34px tag icon.
    - For `TagCreatorsPicker`, that mode also stages the selection behind an "Add" button, titles the popover "Tag other Creators", and adds "More" › "Add a tag" › "Release form" (Not wired).
    - With the prop absent, every other caller renders exactly as today (rung 2: plan "Only Messages Pro").
  - `VaultPicker`: one new optional prop selects Messages Pro mode, the Clone's sheet shell (Gap rows 25–27). Only `Composer` passes it, and without it the shell renders exactly as today. Every card addition below applies only when a Fan is in scope. Only `Composer` passes a non-null Fan; the other 14 call sites, in 13 files, pass `fanId={null}` or omit it (observed: `grep -rn '<VaultPicker' app/components app/app`).

- **Schema.** None.

- **Contracts.**
  - **The send payload is frozen.** For the same inputs, `onSend` receives the same `SendArgs` as before.
    - A Timed message goes through the existing delayed-send path: `scheduledAt` = now + n minutes. Jobs of 15 minutes or less go to our executor queue, longer ones to OnlyFans' queue (Composer.tsx:254–256, :316).
    - "Start" is disabled while the draft holds more than one GIF, or one GIF with more than 15 minutes, and its tooltip says why. The existing submit sends every GIF after the first at once, without `scheduledAt` (Composer.tsx:329–332), and the over-15-minute route's body has no GIF field (`_ScheduleMessageBody`, service/server.py:6117–6126), so neither draft would go out as one Timed message. One GIF at 15 minutes or less rides the executor queue, which carries `giphy_id` (app/hooks/useSendMessage.ts:260–275) (rung 1).
    - A Timed message takes priority over an "at" value, as the quick-send delay does today (Composer.tsx:252–255) (rung 1).
  - **No relay or service change.**
    - The Translator reuses the existing translate mode. That mode drives the existing `POST /admin/translate` (service/translate_api.py:222) through `useTranslations` (app/hooks/useTranslations.ts:94) (rung 1: the endpoint exists, so the plan's "wire if one exists" applies).
    - Vault metadata comes only from the endpoints the picker already calls, including `GET /admin/vault/fan-history` (service/server.py:9652).
  - **localStorage.**
    - `chatterly:emoji_favourites`: a JSON array of up to 40 emoji strings.
    - `chatterly:timed-reminder:<accountId>:<fanId>`: the fire time in epoch milliseconds.
    - The existing `chatterly:translate-en` is reused as it is.
    - The `chatterly:` prefix follows house precedent (rung 3: EmojiBar.tsx:22, useTranslateMode.ts:15).
    ASSUMPTION: favourites are one list per browser, not per Employee, following the recents key (EmojiBar.tsx:22). Overturned if Employees share browsers and need separate lists.
  - **Harness DOM contract.** The PPV row opens from the button with accessible name "PPV". The row is the group named "PPV row". Its price input keeps the accessible name "PPV price", and once the per-tile inputs go it is the only element with that name.
    - Phase 0's harness reaches the `messages-pro-composer-ppv` state by typing a price into "PPV price", and the Phase 0 spec hands that state step to the Phase that owns the shot (docs/spec/phase-00-pop-out-window.md, "Harness: shots" table and the ASSUMPTION under it). The row is now closed until opened, so this Phase changes that one step to click "PPV" first and then type the price. No other harness step changes (rung 1).

- **Layout, top to bottom.**
  1. Notices: the blocked-chat banner, the send toast, the Timed reminder strip, the next-script step, the tagged-creator chips, and the GIF search strip.
  2. The button row.
  3. The reply strip.
  4. The PPV row.
  5. The bottom toolbar.

  Notices sit above the button row so they never displace an Infloww element (rung 2: plan's extras constraint). The reply strip keeps its current markup and props. Phase 3 owns how it looks.

- **What each control does.**

  | Control | Does | Built on |
  |---|---|---|
  | Emoji | Inserts at the cursor | `EmojiPickerButton` |
  | ⚙ | Opens the favourites editor | New, in `EmojiBar` |
  | "AI" | Opens this Fan's suggested lines | `LinesPicker` |
  | "Scripts" | Opens saved scripts and applies the pick | `TemplatePicker` |
  | "PPV" | Toggles the PPV row | `PpvRow` |
  | ⏱ | Opens Timed message / Timed reminder | `TimedMessagePopover` |
  | "+" | Opens the Extras overflow | `ComposerToolbar` |
  | Upload | Opens the Vault picker | `VaultPicker` |
  | GIF | Opens the GIF search strip | `GifPickerButton` |
  | Vault | Opens the Vault picker | `VaultPicker` |
  | Calendar | Toggles "at" in the PPV row | Existing schedule state |
  | Tag | Opens "Tag other Creators" | `TagCreatorsPicker` |
  | @ | Inserts `@username` at the cursor | `insertAtCursor` |
  | "Aa" | Not wired | — |
  | Translate | Opens the Translator popover | `useTranslateMode` |
  | "Send" | Sends, or schedules when "at" is set in the future | Existing `submit` |

  ASSUMPTION: the "PPV" pill goes in the button row after "Scripts". The Clone has no PPV button: its row opens from the ⚙ composer menu (messages.js:3158–3168), and §3.3:212 gives ⚙ to emoji favourites. This placement keeps the plan's label order AI · Scripts · PPV · Aa · Send. Overturned by an Infloww screenshot that shows PPV elsewhere.
  ASSUMPTION: "AI" opens the existing Lines picker, which is the Clone's own wiring (messages.js:1938). Infloww's AI Copilot modes are not built. Overturned if Copilot modes are wanted in this Phase.
  ASSUMPTION: "Scripts" opens the existing `TemplatePicker`, our saved scripts (rung 3, and the Clone's wiring at messages.js:1968). Overturned if Scripts must also list OnlyFans templates separately.
  ASSUMPTION: upload opens the Vault picker, as in the Clone (messages.js:2415). Upload from disk was deliberately removed from the chat Composer in commit 1ccd82f. Overturned if the human wants upload from disk back; `POST /api/of/v2/upload` (service/server.py:7636) and the `_claim`/`_uploading` attachment fields still exist.
  ASSUMPTION: @ inserts the Fan's username, as in the Clone (messages.js:2495–2500). Overturned if Infloww's @ mentions creators instead.
  ASSUMPTION (evidence blocked): OnlyFans strips markup from DM text (the Clone's note at messages.js:3386), so "Aa" is Not wired. Confirming this needs a live OnlyFans send. Overturned if formatting is shown to survive.
  ASSUMPTION: "Release form" is Not wired, because the relay exposes no release-form listing (relay.ts:384–397 only types the `rfTag` echo). Overturned when a release-form endpoint exists.
  ASSUMPTION: "Tag other Creators" stages the picks and applies them on "Add", following §3.3:214's "Add". Other callers keep tagging immediately. Overturned if Infloww applies on click.

- **The PPV row.**
  - **When it shows:** while the "PPV" pill is on, or while there are attachments, a GIF, schedule mode, or a price above 0 (rung 1: messages.js:1838).
  - **Price:** the row's `$` input is the only price field. It keeps `sanitizePriceInput`. A price above 0 is still the only paid signal. Picking vault media still auto-prices to the highest suggested price and opens the row.
  - **"Clear"** empties the price, unticks lock text, empties "at", turns schedule mode off, removes attachments and GIFs, zeroes free previews, and closes the row. The typed text stays (rung 1: messages.js:1857–1861).
  - **Labels:** "PPV" is bold, then "$" and the input, then "lock text", then "at" (dim). The "Fan pays $X to read" hint becomes the price input's tooltip.
  - **Removed:** the per-tile price inputs, which write the same `price` state as the row's `$` (Composer.tsx:752–754), and the ▾ quick-send menu (+1…+15 min), whose delayed send is what Infloww's Timed message does. Each is a second copy of a control that remains (rung 1).
  - **Kept as an Inflowwww extra:** the "at" presets (+5, +10, +15, +30, +60 min). They fill "at" without sending (Composer.tsx:547–551), which no remaining control does. They move into the Extras overflow, where each one turns schedule mode on and sets "at" to now plus n minutes.
  ASSUMPTION: the "at" presets count as an Inflowwww extra, by the same test this spec applies to the quick emoji row (in neither the Clone nor §3.3), and keeping them is cheaper to undo than deleting them (rung 4; plan Phase 7 "No extra is deleted"). Overturned if the human counts them as a copy of Timed message.

- **Timed message.**
  - Accepts whole minutes from 1 to 60 (§3.3:213). "Start" is disabled otherwise, while the draft cannot be sent (including a blocked chat), and for the GIF cases under Contracts.
  - "Start" calls the existing delayed submit with that many minutes.
  - Cancelling uses the existing scheduled-send cancel paths: the ghost bubble's "cancel" (MessageList.tsx:928–936) and `ScheduledForChat`. This Phase adds no cancel of its own.
  ASSUMPTION: the minutes field defaults to 5. The range is in §3.3; the default is not. Overturned by Infloww evidence.

- **Timed reminder.**
  - Same 1–60 minute field and "Start".
  - While it runs, the notice area shows "Timed reminder · m:ss" with ✕ to cancel.
  - At zero it shows a `role="alert"` strip, "Timed reminder — time's up", with ✕ to dismiss. It also fires an OS notification, but only if permission is already granted (rung 3: NotificationToaster.tsx:296–305).
  - It never calls `onSend`.
  ASSUMPTION: the reminder range is 1–60 minutes like the Timed message, because §3.3:213 gives no range for the reminder. Overturned by Infloww evidence of a different reminder range.
  ASSUMPTION: there is one reminder per Fan. It is held in a module-level timer (survives chat switches) and in localStorage (survives reloads). A reminder that expired while its Thread was closed fires the next time that Thread opens. There is no sound, because the app has no audio asset. Overturned if the human wants one global reminder or an audible alarm.

- **Emoji favourites.**
  - ⚙ opens a `.pop`-sized grid of every emoji in `EMOJI_LIST`, with a counter "n/40".
  - Toggles are disabled at 40.
  - "Save" persists the list and closes the editor. "Cancel" discards the changes.
  - The Messages Pro emoji picker opens on a "Favourites" tab when favourites exist.
  - The list keeps the order in which the Employee picked, holds no duplicates, and is read each time the picker opens, so another window sees a save the next time it opens the picker. There is no live sync.
  ASSUMPTION: pick order, no duplicates and read-on-open are our choice (rung 5); §3.3:212 gives only the cap of 40 and "Save". Overturned by Infloww evidence of another order.

- **Translator.**
  - Popover heading: "Translate messages from fans into".
  - Target: "English".
  - A "Use translation" switch (`role="switch"`) bound to `useTranslateMode`. The Chat header's 🌐 toggle stays in sync through the same hook.
  ASSUMPTION: English is the only target, because `useTranslations` keys its cache by text alone and always asks for `en` (useTranslations.ts:31, :94). Overturned if other languages are wanted; that needs a target-aware cache key.
  ASSUMPTION: the switch keeps today's scope. The mode translates every loaded bubble, the Fan's and ours (MessageList.tsx:114–117), and shows a translation only when the detected language is not English (MessageList.tsx:1556). Limiting it to the Fan's messages, as Infloww's label says, would change the message list, which Phase 3 owns, and our own bubbles are normally English already. Overturned if the human wants our own bubbles never translated.

- **Extras overflow.**
  - The "+" at the end of the button row opens a popover holding the free previews stepper, the "at" presets and the quick emoji row.
  - The stepper uses the existing `previewCount` logic and is enabled only when the price is above 0 and something is attached.
  - Each item's tooltip contains "Inflowwww extra".
  - No item is an automation, so the Composer does not read the Legacy flag (rung 2: ADR-0003).
  ASSUMPTION: the quick emoji row counts as an Inflowwww extra (it is not in the Clone or §3.3), so it moves into the overflow rather than being deleted. Overturned if the human wants it dropped or replaced by favourites.
  ASSUMPTION: the overflow is local to the Composer and sits last in the button row. If another Phase lands a shared Extras overflow component first, this Phase uses it. Overturned if a single app-wide "+" is meant (CONTEXT.md's own ASSUMPTION).

- **Send.**
  - Placed with `ml-auto`. The accent background appears only when the message can be sent (§3.3:210 C[PAL]); otherwise it uses the neutral elevated token.
  - The label "Schedule" when "at" is in the future is kept.
  - Tooltip: "Enter to send · Shift+Enter for newline".
  - While sends are in flight, "N sending…" shows just left of the button.

- **Colours (ADR-0001).**
  - Pills: `accent` at 15% fill and 35% border, with `accent` text (mirroring the Clone's alphas).
  - Icons: `fg-dim`, and `fg` on hover.
  - Send: `accent` when active, `bg-elev-2` with `fg-dim` when inactive.
  - Grey overlay: `bg` at 60% plus `grayscale`.
  - Not wired: the standard disabled opacity.

- **Geometry numbers.** Written as Tailwind arbitrary values taken from the Gap table.
  ASSUMPTION: these stay inline until Phase 6 creates the Messages Pro token module (ADR-0001), which then absorbs them. If Phase 6 lands first, this Phase reads its tokens instead. Overturned if the human wants Phase 4 blocked on Phase 6.

- **Phone (below 768px).**
  - Both rows `flex-wrap`, and the input takes its own full-width line, so nothing scrolls horizontally at 390px.
  - The GIF and tag triggers stay hidden below md (rung 3: Composer.tsx:933, :942).
  - The bottom padding keeps `env(safe-area-inset-bottom)` (docs/routes.md:43).

- **Vault picker, when a Fan is in scope.**
  - **Grey overlay** on a card when the Fan already has the media: `was_purchased` is true, or the latest send to this Fan was free (`last_price_cents` 0).
    - The overlay is advisory. A greyed card stays selectable, and the relay's re-sale guard stays the authority on priced re-sends (409, service/server.py:5197–5228).
    - While fan-history is loading or has failed, no card is greyed.
    ASSUMPTION: "has it" means bought, or the latest send was free. An earlier free send followed by a priced send the Fan did not buy is missed, because fan-history keeps only the latest send's price (service/server.py:9715–9717) and the plan allows a service change only for a missing endpoint. Overturned if Infloww greys out any media that was ever sent, or if the human approves an "ever sent free" field.
  - **Status icon and last price:** the status pill keeps `resolveStatus`. Its price becomes the last send price (`last_price_cents`). Today `tilePriceLabel` shows the cumulative `total_paid_cents` for a purchased item (VaultPicker.tsx:1858–1863), which is not a last price. The total paid stays in the tile's tooltip (`describeTile`) and in "Media details". The pill renders only with fan-history, so no other screen changes (rung 1: §3.3:223 "last price").
  - **Tags:** up to 3 tag chips from the vault mirror's `_ai.tags`, always shown. The live OnlyFans path carries no tags and shows none.
    ASSUMPTION: the vault's AI tags (editable in the vault manager) count as Infloww's card tags. Overturned if only operator-applied hashtags should count.
  - **Notes:** an empty slot.
    ASSUMPTION: the relay exposes no per-media operator note (the `_ai` overlay in service/vault_ai_api.py:442–455 has an AI description but no note), so notes render empty, not faked from the AI description. Overturned if the human accepts the description as the note.
  - **ⓘ "Media details"** (top-right, 6px inset). It opens a panel over the picker, shaped like the vault manager's details drawer (VaultManagePanel.tsx:998: `md:w-[430px]`, full height). The panel holds:
    - `VaultPreviewMedia` for the media itself;
    - type, duration, created date, tags, and notes ("—");
    - the price history:
      - "Purchased": yes or no, date and amount, from `was_purchased`, `last_purchase_at` and `total_paid_cents`.
      - "Sent (free or paid)": count, last date and last price, from `send_count`, `last_sent_at` and `last_price_cents`.
      - "Unsent (free or paid)": "—".
      - "Posted in feed": yes or no and price, from the wall scan.

    The card's price pill also opens this panel, scrolled to the price history.
    ASSUMPTION: the vault browser component reused is `VaultPreviewMedia`. The picker keeps its own tile rather than switching to `VaultTile`, because `VaultTile` has no per-Fan state. Overturned if the human meant `VaultTile` to replace the picker's tile.
    ASSUMPTION: price history lives in "Media details", and the price pill opens it; there is no separate history popover. Overturned by Infloww evidence of a separate popover.
  - **Unsend icon** at the lower left of cards already sent to this Fan, Not wired.
    ASSUMPTION: unsend is Not wired, and "Unsent" shows "—", because `GET /admin/vault/fan-history` returns no message id (service/server.py:9652–9728) and the plan allows service changes only for a missing endpoint. Overturned by the human approving a `last_message_id` field on that response, which would let unsend call the existing `useUnsendMessage`.
  - **Duration filter:** a select with "Any length", "Under 1 min", "1–5 min" and "Over 5 min". It filters the loaded items on the client by `duration` and hides non-video items when a range is chosen.
    ASSUMPTION: these ranges, and filtering only what is loaded (the relay has no duration parameter, service/vault_ai_api.py:483–492), are our own choice. Overturned by Infloww's actual ranges.
  - **Search:** the placeholder reads "Search hashtag, note or caption". The behaviour is unchanged. The mirror already matches tags, descriptions and OnlyFans captions (`of_terms`), and the live path uses OnlyFans' own search (service/vault_ai_api.py:508–516).
  - **Unchanged underneath:** the additions read only what the picker's existing queries already return. The routing between the vault mirror and the live OnlyFans vault, the folder restrictions (VaultPicker.tsx:374–413), SFW blur, and selection across filters are untouched.

- **Not wired** means `disabled` plus the tooltip "not wired" and no success state (CONTEXT.md).

## Testing Decisions

Two seams, both existing public modules, both as high as they can be:

1. **`Composer`**, rendered with `renderWithProviders`. `@/lib/relay` is mocked by URL, so the real hooks run. The `VaultPicker` module is replaced by a stub dialog whose button calls `onConfirm` with fixture media, because the picker is its own seam. What goes in: props, the `composerApiRef` (`applyTemplate`), clicks, typing and fake time. What comes out: the `onSend` arguments, the DOM's roles and accessible names, and localStorage.
2. **`VaultPicker`**, rendered directly with a Fan in scope. `@/lib/relay` is mocked by URL, and `IntersectionObserver` is stubbed. What comes out: the DOM, the relay's request URLs, and the `onConfirm` arguments.

Nothing below `onSend` changes (Contracts), so `onSend` is the lowest boundary this Phase can break; the send hook keeps its own suite (`app/hooks/useSendMessage.test.tsx`). `ComposerToolbar`, `PpvRow` and `TimedMessagePopover` are not rendered on their own. Their observable behaviour is the send payload and the Composer's DOM, which only `Composer` produces. Testing them alone would pin their props, which is implementation. The test files keep the plan's names (one per module covered) and all render through seam 1.

- `app/components/chat/ComposerToolbar.test.tsx` (seam 1):
  - The accessible names, in DOM order, inside "Composer buttons" are: emoji picker, Emoji favourites, the textbox, AI, Scripts, PPV, Timed message, Inflowwww extras.
  - Inside "Composer toolbar" they are: Upload, GIF, Vault, Schedule, Tag other Creators, Mention, Aa, Translate, Send.
  - "Aa" is disabled with title "not wired".
  - Upload and Vault each open the picker stub.
  - @ inserts `@sam` when `fanUsername` is "sam", and is disabled without a username.
  - Translate's "Use translation" flips `aria-checked`, and `readTranslateMode()` returns the new value.
  - Favourites: the 41st toggle is disabled at 40/40, "Save" writes 40 entries, and reopening the emoji picker shows "Favourites" first.
  - The "+" overflow holds the free previews stepper (disabled until there is a price and an attachment), the "at" presets and the quick emojis, each titled with "Inflowwww extra".
  - The "+15m" preset turns schedule mode on and sets "at" to now plus 15 minutes, and `onSend` is not called.
  - "AI": picking a line (Lines endpoint mocked) puts its text in the textbox, and `onSend` is not called.
  - "Scripts": picking step 1 of a two-step script (saved replies mocked) loads its text, price and media; after Send, the notice "Next in … step 2" appears.
  - A blocked chat (`canSend` false with a reason) shows the reason, and Send is disabled.
  - Tagging: picks are not applied until "Add"; then Send carries `taggedUsers`. "Release form" is disabled with "not wired".
  - Enter sends and Shift+Enter adds a newline.
- `app/components/chat/PpvRow.test.tsx` (seam 1):
  - The "PPV" pill toggles `aria-pressed` and the "PPV row" group.
  - The children are in order: "PPV", the price, "lock text", "at" (in schedule mode), "Clear".
  - "hi" with $12.5 and lock text sends `{text:"hi", price:12.5, lockedText:true}`; with an empty price it sends no `price`.
  - The calendar plus a future "at" relabels Send to "Schedule" and sends `scheduledAt`.
  - `applyTemplate` with a price and two media opens the row with two 42px tiles.
  - "Clear" resets everything, keeps the text and hides the row.
  - The picker stub confirms two media with suggested prices $10 and $25: the row opens with price 25 and two tiles, and Send carries `attached` with both ids in pick order and `price: 25`.
  - With the free previews stepper at 1, Send carries `previews` holding the first tile's id.
- `app/components/chat/TimedMessagePopover.test.tsx` (seam 1):
  - Timed message: "Start" is disabled for 0, 61, 2.5, an empty field, or an empty draft, and enabled for 1 and 60.
  - With the clock frozen, 60 sends once with `scheduledAt` equal to now plus 60 minutes.
  - "Start" is disabled with two GIFs, and with one GIF at 16. One GIF at 15 sends once, with `giphyId` and `scheduledAt` equal to now plus 15 minutes.
  - With "at" set to tomorrow, "Start" at 5 sends `scheduledAt` equal to now plus 5 minutes.
  - In a blocked chat, "Start" is disabled.
  - Timed reminder: 1 → "Start" shows a countdown, and after 60 s an alert appears while `onSend` is never called.
  - ✕ before zero means no alert.
  - Unmounting and remounting with the same account and Fan before zero keeps the countdown.
  - Reload: localStorage holding a past fire time for this account and Fan shows the alert on mount; a future fire time with a fresh module (`vi.resetModules`) shows the countdown.
- `app/components/chat/VaultPicker.test.tsx` (seam 2). Fixtures: a photo, three videos of 30 s, 120 s and 600 s, and fan-history with one purchased (`last_price_cents` 1500, `total_paid_cents` 2500), one sent free and one sent locked.
  - The grey overlay is on the purchased and free-sent cards only. While fan-history is pending, no card is greyed.
  - The purchased card's pill reads "$15.00", and its "Media details" shows "$25.00" under "Purchased".
  - Selecting two cards, one of them greyed, and confirming calls `onConfirm` with both media in pick order.
  - Clicking ⓘ opens "Media details" and leaves the selection unchanged.
  - With a Fan in scope, every relay path requested is one the picker already requests today (an allowlist in the test).
  - Typing in search issues a vault request carrying `query=<term>` after the debounce, and the placeholder reads "Search hashtag, note or caption".
  - "1–5 min" leaves only the 120 s video.
  - ⓘ opens "Media details" with the four history labels, and "Unsent (free or paid)" shows "—".
  - Unsend is disabled with "not wired".
  - A mirror item with `_ai.tags` shows its tags.
  - Rendered with no Fan, none of the above appears (the overlay, ⓘ, the duration filter and the new placeholder are all absent), which guards the 14 other call sites.

Prior art:
- `app/components/chat/AiStatusStrip.test.tsx`: mocks `relay.get` so the real hooks run.
- `app/components/chat/MessageList.test.tsx` and `MediaTile.test.tsx`: `IntersectionObserver` stub and `renderWithProviders`.
- `app/components/vault/VaultTile.test.tsx`: vault media fixtures.
- `app/components/chat/fanDrawerEditFreshness.test.tsx`: chat component through providers.
- `app/test-utils.tsx`: `renderWithProviders`.

## Acceptance

```sh
# Full suite (binding)
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run

# This Phase's suites
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run \
  components/chat/ComposerToolbar.test.tsx \
  components/chat/PpvRow.test.tsx \
  components/chat/TimedMessagePopover.test.tsx \
  components/chat/VaultPicker.test.tsx

# The three modules the plan names exist
test -f app/components/chat/ComposerToolbar.tsx
test -f app/components/chat/PpvRow.tsx
test -f app/components/chat/TimedMessagePopover.tsx

# Visual loop (harness from Phase 0)
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-composer-ppv.png
test -s docs/screenshots/clone-messages-pro.png
test -s docs/screenshots/messages-pro-report.json
# manual: Read messages-pro-composer-ppv.png and clone-messages-pro.png side by side; write the Composer-region visual diff (position, size, label, order, missing element); fix and re-run up to three rounds; record what remains as VISUAL GAP: lines with reasons.
# manual: record the messages-pro-report.json summary (overflow, console errors per shot) in the Phase result and commit the final PNGs with the code.
```

## Depends on

- **Phase 0:** `scripts/ui-shots.sh` and `docs/ui-shots.md`, which produce `messages-pro-composer-ppv.png`, `clone-messages-pro.png` and `messages-pro-report.json`. Only the visual-loop steps of Acceptance need it. The code and the vitest suites do not. This Phase edits one step of that harness, the `messages-pro-composer-ppv` state step (see Harness DOM contract), so the harness must exist before that edit.

No other Phase must land first.

## Out of Scope

- **"/" + keyword script search, and the Clone's placeholder that advertises it.** Not in Phase 4's target, and showing the placeholder before the feature exists would fake it.
- **The "Manage scripts" window, quick-adding a script, and AI Copilot modes** (Casual, Re-engage, Tip request, Sexting, Regenerate). Not in Phase 4's target.
- **Reply strip styling.** Phase 3 owns "Replying to: …" ✕. This Phase only moves the strip.
- **Fixing the existing scheduled-send gaps** (extra GIFs sent at once, no GIF on the over-15-minute route, no quote on scheduled sends). The plan keeps `Composer`'s send logic and allows no service change. This Phase only keeps the new Timed message out of them (Contracts). See Further Notes.
- **Moving the measured numbers into the Messages Pro token module.** Phase 6.
- **Unsend from the Vault picker and "Unsent" history.** Needs a message id on `fan-history`, a service change the plan does not allow (see ASSUMPTION).
- **Per-media notes.** The relay stores none.
- **Translation targets other than English.** No current need. The cache would need a target-aware key.
- **Release-form listing and attaching.** No relay endpoint.
- **Upload from disk in the chat Composer.** Removed on purpose in commit 1ccd82f. Upload opens the Vault picker.
  - Restored 2026-10-16 at the human's request: Upload opens the computer's file chooser (drop and paste too) and uploads through `POST /api/of/v2/upload` (`useComposerUploads`, `ComposerUpload.test.tsx`); Vault still opens the Vault picker.
- **"Aa" text formatting.** OnlyFans strips markup (see ASSUMPTION).
- **A sound for the Timed reminder.** No audio asset exists. The visual alert and OS notification cover it.
- **The list of scheduled sends behind the calendar** (the Clone's sheet, messages.js:2453–2473). The Scheduled chip (`ScheduledForChat`) already lists them. Phases 3 and 7 place it.
- **Vault Pro media statistics** (H766217) beyond the per-Fan price history. Not in the target.
- **The Chat header's 🌐 toggle.** Phase 3 removes it once this Phase has landed, because the Translator here drives the same mode (`phase-03-chat-header-message-list.md`, F12). Until then it stays in sync through the shared hook.
- **Any change to the other vault pickers, the mass-message / post / premade composers, or the settings tabs.** The plan says "Only Messages Pro".
- **The "Ours" entries and the Parity table in `docs/messages-pro-parity.md`.** Phase 7.

## Further Notes

- **For Phase 7's "Ours" catalogue:** this Phase puts three Inflowwww extras in the Composer's Extras overflow: free previews, the "at" presets and the quick emoji row. Phase 7 should list all three.
- **Overlap with Phase 3:** both Phases touch `ChatSurface` and the reply strip inside `Composer`. This Phase adds one prop at the `Composer` call site and moves the strip's position without changing its markup.
  ASSUMPTION: the second Phase to land rebases onto the first; no shared component is introduced for this. Overturned if the Phase 3 spec moves the reply strip out of `Composer`.
- **For the human:** the one-field service change that would wire unsend is adding the latest `VaultSend.message_id` per media to the `GET /admin/vault/fan-history` response (service/server.py:9702–9728).
  ASSUMPTION: this is left for the human rather than made here, under the plan's rule against service changes unless an endpoint is missing. Overturned by the human's go-ahead.
- **For the human: existing scheduled-send gaps found in review.** None is introduced by this Phase, and the plan does not ask for them to be fixed.
  - A scheduled send ("at") with two or more GIFs sends every GIF after the first at once (Composer.tsx:329–332).
  - A GIF on a send scheduled more than 15 minutes out is dropped: the app sends `giphy_id` (app/hooks/useSendMessage.ts:309), but `_ScheduleMessageBody` has no such field (service/server.py:6117–6126).
  - Scheduled sends carry no `replyToMessageId` (app/hooks/useSendMessage.ts:260–315, against :184 for an immediate send), and a refused schedule loses the quote, which `ChatSurface` clears before the send resolves (ChatSurface.tsx:1145).
- **For Phase 6:** resolved by the 2026-10-12 plan review. Phase 6 now lifts rows 25–26 into the shared `MP.sheet` tokens (SH1, SH2, SH5, SH6), which `Composer` passes to `VaultPicker` as class-name props. Row 27's `.vdur` stays in the picker. Phase 6's Thread locator no longer expects "Type a message…" (`grep -n 'Type a message' docs/spec/phase-06-geometry-pass.md` finds nothing).
- `ALLOW_ANONYMOUS_ADMIN` is not referenced anywhere in `app/` (grep). The variable is kept in the commands because they are binding as given. Running `pnpm -C app exec vitest run <files>` was checked on 2026-10-12 against two existing suites (2 files, 18 tests passed).

## Review

codex · 2026-10-12. Both calls ran on `codex exec --sandbox read-only -c model_reasoning_effort="high"` against the sparse review workspace, with no access to `docs/spec/`, and both exited 0 with fresh output. Counts: 6 accept, 9 partial, 9 reject, 0 needs-human.

Blind call (before the draft):

- B1. "Keep the send logic, rebuild only the chrome" is unsound, because extra GIFs lose the schedule (Composer.tsx:329–332) and the over-15-minute body has no GIF field (server.py:6117–6126). **partial**: both are confirmed and pre-existing. The plan binds the send logic ("`Composer.tsx` keeps its send logic"), so the fix is not made here. The new Timed message is kept out of both gaps (Contracts: "Start" disabled for those GIF cases), and the gaps go to the human (Further Notes).
- B2. The alternatives are a bounded presentation pass, capability slices, or a shared media layer, and `VaultManagePanel` would need an adapter. **reject**: the plan already chose "only the chrome is rebuilt". The spec keeps `chat/VaultPicker` and reuses only `VaultPreviewMedia` from `app/components/vault/`, never `VaultManagePanel`.
- B3. The plan's "AI · Scripts · PPV · Aa · Send" row disagrees with the Clone's two rows. **reject**: already settled. Gap rows 2 and 8 take the Clone's two rows, and the PPV placement is an ASSUMPTION with its evidence.
- B4. Timed message, Scheduled message and Timed reminder need lifecycle contracts (cancel, persistence, alarm, conflicts), and a past "at" falls through to an immediate send. **partial**: cancel, persistence and alarm were already specified. The conflict rule is now written (a Timed message beats "at", Composer.tsx:252–255) and tested. A past "at" is pre-existing and visible, since Send then reads "Send", not "Schedule" (Composer.tsx:976).
- B5. Scheduled sends drop the reply id, a refused schedule loses the quote, and Fansly rejects media and PPV schedules. **partial**: the first two are confirmed and pre-existing (useSendMessage.ts:260–315; ChatSurface.tsx:1145), and they go to the human (Further Notes). The Fansly 400 already reaches the Employee through the existing restore and toast (Composer.tsx:294–310).
- B6. PPV opening, Clear and pricing semantics are undefined. **reject**: The PPV row section already defines the visibility rule (pill on, so the first price can be typed), Clear (messages.js:1857–1861), auto-pricing on a vault pick, and free previews on the existing `previewCount`. Upload claims cannot occur, because upload from disk is gone (commit 1ccd82f).
- B7. "Has it" is not "purchased", selectability and loading are undefined, the 409 guard is the real rule, and the pill shows total paid rather than last price. **accept**: The overlay is now advisory (greyed cards stay selectable, and the 409 guard at server.py:5197–5228 stays the authority), there is no overlay while history loads or fails, and the pill shows `last_price_cents` (see D2). All of this is tested.
- B8. Unsend needs a message id, search has two contracts, and duration filtering might cover only the loaded pages. **reject**: already decided with evidence. Unsend is Not wired (server.py:9652–9728), search behaviour is unchanged on both paths (vault_ai_api.py:508–516), and the duration filter covers loaded items under an ASSUMPTION.
- B9. Translation should cover the Fan's messages only, and the language is hard-coded. **partial**: English-only was already an ASSUMPTION. The scope is now an ASSUMPTION too: the switch keeps today's all-bubbles mode (MessageList.tsx:114–117), which shows only non-English text (:1556), because the message list belongs to Phase 3.
- B10. Favourites need order, duplicate and cross-window rules; tagging commits at once; AI Copilot is not the automation strip. **partial**: pick order, no duplicates and read-on-open are now written (ASSUMPTION, rung 5). "Add" staging and "AI" = Lines were already decided.
- B11. Preserve the mirror/live routing, folder restrictions, SFW, selection across filters and the phone layout. **partial**: an explicit "Unchanged underneath" rule now sits in the Vault picker section, with a request-path allowlist test. The phone layout was already covered (Phone section, `messages-pro-phone-thread.png`).
- B12. Test through Composer → ChatSurface → send hook → relay. **reject**: nothing below `onSend` changes (Contracts), so `onSend` is the lowest boundary this Phase can break. The hook keeps `useSendMessage.test.tsx`. The defects the reviewer wanted that seam to catch are pre-existing and out of this Phase.
- B13. The VaultPicker seam should cover the mirror, live and restricted paths, unknown history, selection and confirmation. **partial**: added pending history, `onConfirm` with a greyed pick, ⓘ leaving the selection alone, and the request-path allowlist. The restricted and live paths are not re-tested, because this Phase does not touch the routing.
- B14. Translation should be tested through MessageList and the cache. **reject**: `useTranslateMode`, `useTranslations` and MessageList are reused unchanged. The seam asserts that the switch flips the shared mode (`readTranslateMode`).
- B15. Acceptance cannot be shown in this checkout, because there is no `node_modules` and no harness. **reject**: this describes the sparse review workspace, not the spec. The vitest command was run in the real tree on 2026-10-12, and the harness is a declared Phase 0 dependency.

Draft call:

- D1. A Timed message with two GIFs breaks story 20, because extra GIFs go out at once. **accept**: "Start" is now disabled for two or more GIFs, and for one GIF beyond 15 minutes, with tests (Contracts, story 21, TimedMessagePopover tests).
- D2. `tilePriceLabel` shows cumulative total paid, not last price (VaultPicker.tsx:1858–1863). **accept**: the pill shows `last_price_cents`, and total paid stays in the tooltip and "Media details". A $15/$25 fixture tests it.
- D3. The overlay misses an earlier free send that was followed by a priced send. **partial**: confirmed (fan-history keeps only the latest price, server.py:9715–9717). The ASSUMPTION now states the limitation. A fix would need a service field, which the plan allows only for a missing endpoint.
- D4. The Vault shell exemption misreads messages.js:2065, which claims data parity, not Geometry. **accept**: the Clone's Vault uses the same generic `sheet()` as its gallery (messages.js:135–140, :2111). Rows 25–27 now apply `.sheet`/`.mgrid` in a Messages Pro mode that only `Composer` passes, and the Out of Scope entry is gone. Phase 6's stale exclusion is noted in Further Notes.
- D5. Inline arbitrary values contradict ADR-0001's "no magic numbers in JSX". **reject**: the plan gives the token file to Phase 6 ("One `messagesPro.ts` token file", plan Phase 6). The Phase 6 spec defines "lift: the owning Phase applies the value inline" and has Phases 4 and 5 read the module only if it exists. The ADR states the end state, not the order.
- D6. Deleting the "at" presets breaks "No extra is deleted", and they differ from Timed message. **partial**: the "at" presets fill "at" without sending (Composer.tsx:547–551), so they move into the Extras overflow as an extra (rung 4). The per-tile price input (the same `price` state, Composer.tsx:752–754) and the ▾ quick-send (Infloww's own Timed message) stay removed as copies of controls that remain.
- D7. Acceptance passes even if attachments and free previews are broken. **accept**: tests now check `onConfirm` with media in pick order, `attached` and `price` on Send after a vault pick, and `previews` from the stepper.
- D8. There are no tests for AI/Scripts insertion, script advance, the blocked chat, reminder reload, or ⓘ preserving the selection. **accept**: all five are added. Story 41 is narrowed to today's behaviour: Send (and now "Start") are disabled, while the textarea is not (Composer.tsx:204–211, :526).
- D9. The "13 other callers" and the four `sanitizePriceInput` importers do not exist. **reject**: the review workspace is sparse. In the real tree, `grep -rn '<VaultPicker' app/components app/app` finds 15 call sites (14 outside Composer, in 13 files, each with `fanId={null}` or none), and `sanitizePriceInput` is imported by EditPostModal, PremadeComposer, MassMessageComposer and PostComposer. The count now reads "14 call sites, in 13 files".

Found while reconciling, not raised by the reviewer:

- O1. The Harness DOM contract's ASSUMPTION was false. The Phase 0 spec's harness types a price into "PPV price" and leaves that step to Phase 4, so the input keeps that name and this Phase now changes the step to click "PPV" first (Harness DOM contract, Depends on).
- O2. Gap row 6 cited the fallback placeholder. Messages Pro passes `Message ${headerName}…` (ChatSurface.tsx:1160), and the row is corrected. There is still no change to the label.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Green: this Phase lands before Phase 3, so that Phase 3 can drop translate. **accept**: it lands in Wave 1. Phase 3 now removes the Chat header's 🌐 toggle, because this Phase's Translator drives the same `useTranslateMode` (`:233`). The Out of Scope entry for the toggle says so.
- Yellow: this Phase stands alone after Phase 0. **accept**: Depends on names only Phase 0 (`:389-393`), so nothing changes.
- Black: Phase 6's Vault picker Out of Scope entry is stale against rows 25–27. **accept**: the fix is in Phase 6 (its Out of Scope entry, SH rows and Owns). This spec's "For Phase 6" note now says it is resolved, and rows 25–27 do not change.
