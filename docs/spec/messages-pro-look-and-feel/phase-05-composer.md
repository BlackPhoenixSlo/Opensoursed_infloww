# Phase 05 — Composer

**Objective.** The Composer stacks Infloww's three Composer rows (row 1 controls, row 2 the input with Infloww's placeholder, row 3 the media icons and Send) at the Infloww capture's px. The PPV button sits in row 1, and in PPV mode the PPV row shows the price field and Free previews in Infloww's input typography. "/" + keyword really searches Scripts. At 390 the Composer's "+" Extras overflow and the Fan insights slide-over both open fully on-screen.

## Measured gap table

Ground truth, ranked by the plan. (1) The Infloww capture of the Thread with Fan insights open, cropped to the Composer and measured with `python3 -I` + PIL in a scratch copy under `/tmp`. The capture is 2× retina, so every value below is device px ÷ 2, and the Composer spans the Thread pane, x 0 to 824 CSS px. (2) The Infloww stylesheet. Its chat Composer is OnlyFans' own DOM and has no rules there: `grep -c "quickly search" messages.css common.css` gives 0 and 0. The only Infloww input rules are the mass-message ones, `._online-input-price_1c4gm_122` (14px, line height 140%) and `._online-input-price_1c4gm_122 .ant-input-number-affix-wrapper` (width 85px, padding-left 5px), plus `._online-input_1c4gm_75` / `._online-desc_1c4gm_29` (radius 4px). (3) The Clone, `ui-redesign/infloww-exact/messages.html:269-284`, `:725-764`. Ours today: `app/lib/messagesPro.ts` CP1–CP15 and PV1–PV9, `app/components/chat/ComposerToolbar.tsx:100-216`, `app/components/chat/PpvRow.tsx`, and `app/lib/messagesProOurs.ts` (`ComposerToolbar.pop`, `FanDrawer.slideOver`).

| # | Ground truth | Ours (`file:line`) | Gap | Change |
|---|---|---|---|---|
| C1 | Composer: 1px top rule. Row 1 starts at the rule, with no top padding | CP1 `px-4 pt-3 pb-[…] border-t` (`messagesPro.ts:456`) | 12px top padding | The root keeps the top rule and the safe-area bottom. Side padding moves onto each row |
| C2 | Row 1: 44px tall, 12px side padding, a 1px full-width rule under it | CP2 `gap-2.5 mb-1.5`, wrapping, input inline (`ComposerToolbar.tsx:107-130`) | no rule, input inline, wraps | Row 1 is a 44px non-wrapping row with 12px side padding and a bottom rule. It holds no input |
| C3 | Row 1 left: emoji, then ⚙, centres 31px apart (26px boxes, 5px gap). Glyphs about 17px | CP3 26px box, CP4 20px icon | gap 10px | Left group gap 5px. CP3 and CP4 unchanged (a 20px lucide icon draws a ≈17px glyph) |
| C4 | Row 1 right: AI pill, Scripts pill 8px apart, then ⏱ 17px after Scripts, ⏱'s box ending 12px from the pane edge | AI, Scripts, PPV, ⏱, "+" 10px apart | gaps | Right group pushed to the end: AI, Scripts, PPV 8px apart; ⏱ 17px after PPV; "+" 8px after ⏱ (ours, last) |
| C5 | Pill: 26px tall, padding 0 8px, icon 16px, 6px icon–label gap, radius 3px, label 14px (cap height 10px), no border | CP5 `gap-1.5 px-3 py-1.5 rounded-2xl text-[13px] font-semibold border`, CP6 15px | shape, size | CP5 and CP6 take these values. The PPV button uses the same pill |
| C6 | Row 2: placeholder `Press "/" + keyword to quickly search scripts`, text 16px starting 16px in, cap top 19px under row 1's rule (`._editor-content_1c4gm_13` padding 16px, 16px) | CP7 15px inline input; ChatSurface passes `Message ${headerName}…` (`ChatSurface.tsx:942`) | own row, label, size | Row 2 is the input alone: padding 16px, 16px text, line height 20px. It grows with the text as today |
| C7 | Row 3: icon boxes 34px on a 40px pitch from 16px in, 16px above and below the row, Send's right edge 14px from the pane edge | CP8 gap 6px, CP9 34px, CP10 20px, root px-4 | right inset 16 vs 14 | CP8–CP10 unchanged. Row 3 padding 16px top, bottom and left, 14px right |
| C8 | Send: 72×32, fully round, label 16px (text 33px wide, so ≈19px side padding) | CP11 `px-6.5 py-2.5 rounded-[9px] text-sm font-bold` | size, radius | CP11 becomes 32px tall, 19px side padding, full radius, 16px; the weight stays |
| C9 | Composer total with an empty one-line draft: 166px including the top rule | about 170px, varies with the wrap | — | Falls out of C1–C8; the harness asserts the row boxes, not the total |
| C10 | Clone order: the PPV row `.comp-x` sits after the input row and before `.comp-r2` (`messages.html:738`, `:754`) | `children` render between the button row and the toolbar (`ComposerToolbar.tsx:132`) | — | Reply strip, then the PPV row, sit between row 2 and row 3. Row 3 and Send never move when PPV mode toggles |
| C11 | Infloww input styling: 14px at 140% (`_online-input-price`), field radius 4px, the price field 85px wide with its `$` prefix inside at 5px left padding (affix wrapper) | PV1 12.5px, PV4 radius 7px 13px, PV5 92px, `$` outside the field | type, field | PPV row: 16px side padding, 8px gap, 14px at 140%. PV4 radius 4px and 14px from md up (16px below md, as today). PV5 85px, with `$` drawn inside the field 5px in |
| C12 | — (ours) | "+" panel `right-0 mb-2` shared with ⏱, ⚙ and Translate (`messagesProOurs.ts:386`); at 390 the panel spans x −208 to 42 (`docs/messages-pro-parity.md:55`) | off-screen | The "+" gets its own placement token: right edge on the "+"'s right edge, 8px above, at most the viewport minus 24px wide |
| C13 | — (ours) | ⚙ favourites opens from its right edge (shared `pop`) | ⚙ moves to row 1's left end, so it would open off the left edge | A start placement token: the left edge on ⚙'s left edge, 8px above |
| C14 | — (ours) | slide-over `w-full max-w-[420px] sm:w-[360px] …` beside a `min-w-14` backdrop (`messagesProOurs.ts:404`, `FanDrawer.tsx:862-864`); at 390 the box is x 56–401.1 (`.scratch/messages-pro-parity/RUN.md:81`) | 11px overhang | The slide-over may shrink below its content's minimum width. At 390 it fills x 56–390 and no child is wider than it |

Measured colours, for Phase 0's Colour inventory and Phase 1 (this Phase changes no colour): Composer fill #151515, rules #444444, row icons #b8b8b8, placeholder #8c96a2, pill label #4166f6, Scripts pill fill #353535, Send disabled #666666 with label #999999.

## Problem Statement

An Infloww Employee opening our Composer finds Infloww's controls packed into one wrapping line. The input sits between ⚙ and AI, the pills are rounded and outlined, Send is a square-cornered block, and the placeholder reads "Message <Fan>…" where Infloww says to press "/". In PPV mode the price field and the free-preview divider use our own small type, not Infloww's. On a phone the "+" Extras overflow opens off the left edge of the screen, so Free previews, At presets and Quick emojis cannot be reached. The Fan insights slide-over also runs 11px past the right edge, so its cards sit flush against the glass.

## Solution

The Composer becomes Infloww's three rows. Row 1 holds emoji and ⚙ on the left, and AI, Scripts, our PPV button, ⏱ and our "+" on the right, under a full-width rule. Row 2 is the input with Infloww's placeholder, and typing "/" plus a keyword opens the matching Scripts. Row 3 holds the media and formatting icons, with a round Send at the right. Turning PPV mode on adds the PPV row between the input and row 3, in Infloww's 14px input typography: the price field with its `$` inside, lock text, the attachments with the free-preview divider, "at" and Clear. Row 3 and Send stay where they were. The "+" overflow and ⚙ each open in their own direction, so both stay on-screen at every width. At 390 the Fan insights slide-over ends at the screen edge.

## User Stories

1. As an Employee who knows Infloww, I want emoji and ⚙ at the left of the Composer's top row, and AI, Scripts and ⏱ at its right, so that my hands find Infloww's controls where Infloww puts them.
2. As an Employee, I want a thin rule under the Composer's top row, so that the controls read apart from what I type, as in Infloww.
3. As an Employee, I want the input on its own full-width row below the controls, so that long drafts have Infloww's room.
4. As an Employee, I want the placeholder `Press "/" + keyword to quickly search scripts`, so that the empty input teaches the same shortcut Infloww does.
5. As an Employee, I want typing "/" and a keyword as my whole draft to list the Scripts that match, without leaving the input, so that the shortcut in the placeholder works.
6. As an Employee, I want Enter on that list to load the first matching Script exactly as picking it from "Scripts" would (text, price and media), so that the shortcut and the pill do the same thing.
7. As an Employee, I want Enter never to send "/keyword" as a message while the list is open, and Escape to close the list, so that a search is never sent to a Fan by accident.
8. As an Employee, I want the media, GIF, vault, calendar, tag, @, Aa and translate icons on the bottom row's left and Send at its right, so that the bottom row matches Infloww's.
9. As an Employee, I want AI, Scripts and PPV as Infloww's flat, 26px, slightly rounded pills, so that the controls look like Infloww's.
10. As an Employee, I want Send as Infloww's 32px round button with 16px text, so that the primary action looks like Infloww's.
11. As an Employee, I want the PPV button in the top row right after Scripts, keeping its pressed state, so that PPV is one click from the other send helpers.
12. As an Employee, I want PPV mode to show the PPV row with the price field, lock text, my attachments, "at" and Clear, so that I keep every PPV control we built (decision: kept, never removed).
13. As an Employee, I want the price field drawn in Infloww's input style, 85px wide with the `$` inside and 14px text, so that pricing looks native.
14. As an Employee, I want the free-preview divider between free and paid tiles to stay in the PPV row whenever it separates them, so that I can see which items the Fan gets free.
15. As an Employee, I want the PPV row to open between the input and the bottom row, so that Send does not jump when I toggle PPV mode.
16. As an Employee replying to a message, I want the reply strip to stay just under the input, above the PPV row, so that the quote stays next to what I am typing, in the Clone's order.
17. As an Employee on a phone (390px), I want the "+" Inflowwww extras menu to open fully on-screen, so that I can reach Free previews, At presets and Quick emojis.
18. As an Employee, I want the ⚙ emoji favourites panel to open toward the inside of the screen now that ⚙ sits at the left end, so that it is never cut off.
19. As an Employee on a phone, I want the Composer's top row to stay on one line, with the AI, Scripts and PPV labels folding to icons that keep their names, so that nothing wraps or overflows.
20. As an Employee on a phone, I want the Fan insights slide-over to end at the screen's right edge with its padding visible, so that no card is cut off or flush against the glass.
21. As an Employee, I want every Composer extra to keep its "Inflowwww extra — <name>" tooltip and its place in the "+" overflow, so that ours stays marked (ADR 0003).
22. As a maintainer, I want every new Composer number in the Geometry token module, guarded by the existing snapshot and colour checks, so that ADR 0001's rule still holds.
23. As a maintainer, I want the screenshot harness to fail if the "+" overflow or the Fan insights slide-over leaves the 390px viewport, so that the two Phase 7 gaps cannot come back unseen.
24. As a reviewer, I want each Composer Compare row on the Compare page to read "matched" once this Phase lands, or to name its remaining px difference, so that the parity claim has evidence.

## Implementation Decisions

- **Owns.** `ComposerToolbar` (row layout, the PPV button, the "+" Extras overflow and the popover placements), `Composer` (the placeholder, the "/" search wiring, where the PPV row and reply strip render), `PpvRow` (row typography and the price field's inline `$`), `TemplatePicker` (a controlled "/" search mode), `ChatSurface` (stops passing its placeholder), `FanDrawer` (only the slide-over's shrink rule), the Composer and PPV row leaves of the Geometry token module `messagesPro`, and the `Composer`, `ComposerToolbar` and `FanDrawer` entries of `messagesProOurs`. In the harness `scripts/ui-shots.sh` it owns one new flow, plus new checks on the existing `messages-pro-composer-ppv` state.
- **Interfaces.**
  - `ComposerToolbar` keeps every slot and callback it has today, with the same names. What changes is the render order: row 1, the toolbar "Composer buttons" (emoji, favourites, then an end-pushed group with ai, scripts, the PPV button, timed and the "+"); row 2, the `input` slot alone in its own row, not inside either toolbar; then `children` (the reply strip and the PPV row); row 3, the toolbar "Composer toolbar", unchanged in content and order. The accessible names "Composer buttons", "Composer toolbar", "PPV", "Timed message" and "Inflowwww extras" are unchanged.
  - `PILL` (shared with LinesPicker and TemplatePicker) takes C5. Its label gets the same treatment as the Chat header's `labelText`: screen-reader only while the Thread, a size container, is narrower than the row-1 threshold, and shown from it up. The button keeps its name.
  - `TemplatePicker` gains an optional `slashQuery: string | null`. Null or absent means exactly today's behaviour. A string opens its panel filtered by that keyword with today's matching, without moving focus out of the Composer input. It also gains an optional `onSlashClose()`, called when the list closes. The Composer derives `slashQuery` from the draft: the whole draft is "/" followed by non-space characters, or "/" alone. While the list is open, Enter in the input picks the first match through the Composer's existing Script pick path, which replaces the draft, and never sends. With no match Enter does nothing, and Escape closes the list until the draft changes.
  - `Composer`'s fallback placeholder becomes `Press "/" + keyword to quickly search scripts`, and `ChatSurface` stops passing `Message ${headerName}…`. Composer has one caller, ChatSurface (`grep -rln '<Composer[ >]' app` lists only the test harness besides it), so no other surface changes.
  - `PpvRow`'s props are unchanged. The `$` moves inside the price field's box as a prefix, and the field keeps the accessible name "PPV price".
  - `FanDrawer`'s props are unchanged.
- **Schema.** None: no storage, relay or database change.
- **Contracts.** None cross a process boundary. Sends are unchanged, and a "/" pick sends what a Scripts pick sends today. The harness report keeps its fixed shape (`docs/ui-shots.md`, Report) and gains one flow record, `phone-composer-overflow`, plus new check names on `messages-pro-composer-ppv`.
- **Geometry tokens.** Every value in the Gap table lives in `messagesPro` (rows with an Infloww source: C1–C8, C11) or in `messagesProOurs` (C12–C14, which have no Infloww source), never as a literal in JSX (ADR 0001, rules R1–R4 in `messagesPro.test.ts`). The "+" overflow's placement is its own token, `ComposerToolbar.extrasPop`, which is no longer the shared `pop`. ⚙ gets `ComposerToolbar.popStart`. ⏱ and Translate keep `pop`. The slide-over token gains the shrink rule. The row-1 label threshold is a token beside `PILL`. New leaves are added to `EXPECTED` in `messagesPro.test.ts`, each with a comment citing its Gap row here (C-numbers). Changed CP/PV leaves change there too.
- **Colours.** None are decided here. New elements (row 1's rule, the inline `$`, the PPV pill) use the colour classes Phase 1 gives their siblings: the Composer's top rule, the existing field, and the AI and Scripts pills.
- **Extras.** The catalogue `openinflowwwwExtras` is unchanged. Free previews, At presets and Quick emojis stay in the Composer overflow. The free-preview divider stays in the PPV row with today's rule: it shows when the draft is priced, at least one tile is free, and at least one is paid.
- **Notices.** The notice stack above the toolbar (blocked, error, Timed reminder, Next-step Script, tagged Creator chips, GIF strip; `Composer.tsx:520-592`) stays where it is, above row 1, under the Composer's top rule, unchanged in order and content. Only the reply strip and the PPV row move between row 2 and row 3.
- **Phone.** Below md, GIF and Tag stay hidden in row 3 as today (`ComposerToolbar.tsx:148`, `:171`), so row 3 fits on one line at 390. Row 1 never wraps. Below the threshold its pills show their icon only.

## Testing Decisions

Three seams, all existing:

1. **Component tests through `composerTestHarness`** (relay mocked by URL), in `ComposerToolbar.test.tsx` and `PpvRow.test.tsx`. They cover:
   - "Composer buttons" holds emoji, ⚙, AI, Scripts, PPV, ⏱ and "+" in that order, and no textbox.
   - The textbox, found by its new placeholder, comes after "Composer buttons" and before "Composer toolbar" in the DOM. The PPV row group, once open, sits after the textbox and before "Composer toolbar".
   - "/" + keyword lists the matching Script, Enter loads its text, price and media without a send, Escape closes the list, and Enter with no match sends nothing. A following Send through the harness's `onSend` carries the same `SendArgs` (text, price, media ids) as picking that Script from "Scripts" and then Send. A draft not starting with "/" still sends on Enter, and Shift+Enter still adds a newline.
   - The "+" panel carries the `extrasPop` token's classes and ⚙'s panel carries `popStart`'s. jsdom has no layout, so the real position is the harness's job.
   - The price field is still named "PPV price", with the `$` inside its box.
   - Every existing send, PPV, free-preview and extras test stays green, with only the placeholder string updated.
2. **`messagesPro.test.ts`**: the snapshot (`EXPECTED`) carries every new or changed Composer, PPV row, `ComposerToolbar` and `FanDrawer` leaf. The colour check and R1–R4 find no hit.
3. **The visual loop, `scripts/ui-shots.sh`.**
   - New gated flow `phone-composer-overflow` at 390×844, flag off, no PNG, in the `phone-popout` flow's form. It picks an Employee and opens the first Fan, then checks that row 1's controls share one top (1px) and lie within the viewport. It opens the Composer "+" and checks its panel box lies within x 0 to 390 and y ≥ 0, then closes it. It opens ⚙ (emoji favourites) and checks its panel box the same way, then closes it. It turns PPV mode on and checks the PPV row box lies within x 0 to 390 with scrollWidth ≤ clientWidth, and Send's box is unmoved (±1px) from before the toggle, then turns it off. It opens Fan insights and checks the slide-over box lies within x 0 to 390, that its scrollWidth ≤ clientWidth, and that every card's right edge is at least the slide-over's computed padding-right inside the slide-over's right edge (padding visible), then closes it. Check names: `row 1 on one line`, `row 1 in viewport`, `'+' panel in viewport`, `⚙ panel in viewport`, `PPV row in viewport`, `Send unmoved by PPV`, `slide-over in viewport`, `slide-over no overflow`, `slide-over padding visible`.
   - New checks on the existing `messages-pro-composer-ppv` state at 1440: row 1 ("Composer buttons") is 44px tall (±1); the PPV row's top is below the textbox's bottom and above "Composer toolbar"'s top; Send is 32px tall (±1) and its bottom edge is 16px (±2) above the Composer's. Check names: `row 1 is 44px`, `PPV row between input and toolbar`, `Send is 32px`, `Send 16px above Composer bottom`, beside the existing two.
   - The Composer extras do not read the Legacy flag (ADR 0003, catalogue), so a flag-off run covers both flag states.

Prior art: `ComposerToolbar.test.tsx` ("the two rows", "the '+' Extras overflow"), `PpvRow.test.tsx`, `messagesPro.test.ts` (snapshot, colour check, R1–R4), the `phone-popout` flow and `check_composer_in_viewport` in `scripts/ui-shots.sh`.

## Acceptance

```sh
set -eu
.scratch/messages-pro-look-and-feel/suite.sh
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/chat/ComposerToolbar.test.tsx components/chat/PpvRow.test.tsx components/chat/FanInsights.test.tsx lib/messagesPro.test.ts app/messages-pro/extras.test.tsx
grep -q 'Press "/" + keyword to quickly search scripts' app/components/chat/Composer.tsx
! grep -n 'Message ${headerName}' app/components/chat/ChatSurface.tsx || exit 1
grep -q 'extrasPop' app/lib/messagesProOurs.ts
grep -q 'extrasPop' app/components/chat/ComposerToolbar.tsx
grep -q 'slashQuery' app/components/chat/TemplatePicker.tsx
bash scripts/ui-shots.sh
python3 -I -c '
import json
r = json.load(open("docs/screenshots/messages-pro-report.json"))
assert r["ok"], "harness not ok"
flows = {f["name"]: f for f in r["flows"]}
f = flows["phone-composer-overflow"]
assert f["viewport"] == [390, 844] and all(c["ok"] for c in f["checks"]), f["checks"]
need = {"row 1 on one line", "row 1 in viewport", "'\''+'\'' panel in viewport", "⚙ panel in viewport", "PPV row in viewport", "Send unmoved by PPV", "slide-over in viewport", "slide-over no overflow", "slide-over padding visible"}
assert need <= {c["name"] for c in f["checks"]}, need - {c["name"] for c in f["checks"]}
shots = {s["name"]: s for s in r["shots"]}
s = shots["messages-pro-composer-ppv"]
assert all(c["ok"] for c in s["checks"]), s["checks"]
need = {"row 1 is 44px", "PPV row between input and toolbar", "Send is 32px", "Send 16px above Composer bottom"}
assert need <= {c["name"] for c in s["checks"]}, need - {c["name"] for c in s["checks"]}
'
# Compare page (Phase 0): CP1-CP7 exist; each owned CP row is matched, or differs naming the remaining px with a reason (Phase 0, Named remainder)
python3 -I - CP 1 7 <<'PY'
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
# manual: the implementer Reads messages-pro-composer-ppv.png and messages-pro-phone-thread.png beside the Infloww capture crop over up to three Visual loop rounds and records any VISUAL GAP in the ticket
```

## Depends on

- **Phase 0 — Measure and pin.** The Compare page, with a Compare row for each Composer item above (the plan: "Every item in Phases 1–5 below must appear here first"), and the Colour inventory that the measured colours above feed.
- **Phase 1 — Colour and shell.** The Infloww palette classes for the Composer's fill, rules, pills and Send. This Phase's new elements reuse them and add no colour.

## Out of Scope

- Composer colours: Phase 1 owns them (plan, Phase 1). Here they are measured and listed only.
- The Clone's outline emoji icon and Infloww's AI robot glyph: parent tickets 27, 28, 33 and 117 left them with the human, and this plan does not re-open them.
- Wiring "Aa" formatting and Tag › "Release form": no relay endpoint exists, so they stay Not wired (parent ticket 34, 35).
- The Buys & tips rail overlapping the Composer edge and, at 768, its pills (parent tickets 34, 41, 109, owner the human): no line of this plan's Phase 5 covers it.
- The one-time "Text is no longer locked by default" notice in fresh harness contexts and the dev-mode "N" badge: harness artefacts, not Composer Geometry.
- Moving the Free previews stepper out of the "+" overflow: ADR 0003 keeps non-automation extras in their Region's overflow, and the plan keeps only the divider and the price field in the row (YAGNI).
- Opening the Vault picker or Timed message differently: not in this Phase's plan lines.
- A new harness PNG state: the plan's Phase 0 says the harness gains no new state for comparison. A flow with no PNG is enough to gate the two 390 fixes.
- GIF and Tag in row 3 below md: hidden today so row 3 fits at 390. Infloww has no phone app (`docs/messages-pro-parity.md`, Phone layout, ours-only).

## Further Notes

ASSUMPTION: the PPV row sits between row 2 (input) and row 3 (icons and Send), with Send unmoved. It does not sit under row 3, because the Clone puts `.comp-x` before `.comp-r2` (`messages.html:738`, `:754`) and that keeps Send still when PPV mode toggles (rung 3, house precedent; rung 4, one JSX reorder and one check to undo). The plan's "a fourth row shows" (plan:75-76) counts the rows; it does not place this one last. CONTEXT.md's PPV row and Composer row entries now say "shown between rows 2 and 3". Overturned if the human wants it under row 3: move the PPV row after "Composer toolbar" and drop the `Send unmoved by PPV` and `PPV row between input and toolbar` checks.
ASSUMPTION: the reply strip stays with the PPV row between row 2 and row 3, directly under the input, in the Clone's order (`messages.html:733-737` after the input row) (rung 3). Overturned if the human wants it above the input.
ASSUMPTION: the plan's binding placeholder needs the feature it advertises. The parent spec cut the placeholder because showing it without "/" search fakes it (`docs/spec/phase-04-composer-ppv-vault.md:397`). So this Phase specs a minimal "/" + keyword search over the existing Scripts list (the brief: "evidence never shrinks the goal", rung 5 for its size). Overturned if the human wants the placeholder alone, in which case user stories 5–7 drop.
ASSUMPTION: "/" search triggers only when the whole draft is "/" + a keyword, and Enter with no match does nothing. The Infloww capture shows no open list, and the extracted chunks hold no trigger rule (rung 5, the safest send behaviour). Overturned by Infloww evidence of a mid-draft trigger.
ASSUMPTION: the "free-preview notice" in the plan is the existing free-preview divider tile, shown under today's rule (CONTEXT.md, Free previews, Amended 2026-10-15) (rung 3). Overturned if the human wants a text notice whenever PPV mode is on.
ASSUMPTION: the price field's height is ant-design's default 32px and its radius is 4px, Infloww's input radius elsewhere (`._online-input_1c4gm_75`). No chat price field appears in any capture or rule (rung 3 on Infloww's own stylesheet). Overturned by a capture of Infloww's PPV price input.
ASSUMPTION: the pill label weight is left as the parent's. The capture's thin strokes suggest 400, but at 2× they cannot be measured, so CP5's 600 and CP11's 700 stay until the visual loop says otherwise (rung 4). Overturned by the visual loop's comparison with the capture.
ASSUMPTION: the row-1 label threshold starts at a 480px Thread width. That is about what row 1 needs with labels at C5's sizes: 12+26+5+26 on the left, 53+8+82+8+≈70+17+26+8+26 on the right, 12px padding each side and a 16px minimum gap, 449px in all, rounded up. It is settled in the visual loop and follows the Chat header's `labelText` container-query precedent (rung 3). Overturned if the human prefers row 1 to wrap on a phone.
ASSUMPTION: the slide-over fix keeps the 56px tap-to-close gutter and lets the panel shrink to 334px at 390, rather than removing the gutter (rung 4, the smaller change). Overturned if the human wants the slide-over full-width on a phone.
- The Compare page's Composer rows are CP1–CP7 in Phase 0's seven-column table `ID | Region | Difference | Clone px | Ours | Ticket | Status`, rows starting with the ID (`phase-00-measure-and-pin.md`, Interfaces), so the Acceptance gate reads them by ID (rung 1). A row passes as `matched`, or as `differs` with `remaining: <n>px — <reason>` in Ours (Phase 0's Named remainder).
- "/" search is its own ticket. Stories 5–7 (the `slashQuery` mode of `TemplatePicker`, the Composer's Enter and Escape handling) are cut as a separate ticket in the Tickets step, so the human can veto them alone. Its known cost: with the whole-draft trigger, a message that is exactly "/word" can't be sent with Enter; the Send button still sends the draft as typed. If vetoed, the smallest honest fallback is today's own placeholder (`Message ${headerName}…`, which ChatSurface keeps passing), not the Infloww placeholder without the feature it advertises; CP2 then stays `differs` with its reason, and the `Press "/"`, `ChatSurface` and `slashQuery` greps drop from the Acceptance.
  ASSUMPTION: the Send button is unchanged by "/" search and sends a "/word" draft as typed (rung 4, the smaller change). Overturned if the human wants Send disabled while the list is open.

## Review

Reviewer: codex (blind call, then draft call), 2026-10-15.

Blind call:
- B1 Phase numbering differs from the parent plan (Composer was parent Phase 4) — **reject**: this spec uses the look-and-feel plan's numbering (`docs/plans/messages-pro-look-and-feel.md:72`); no decision rests on the parent's.
- B2 Alternative: an explicit row API instead of reflowing the slots — **reject**: keeping every slot and callback is the smaller, reversible change (rung 4/5); row order is tested through accessible names and DOM order either way.
- B3 Placeholder is copy or a promised behaviour; ChatSurface's own placeholder wins over Composer's fallback — **reject (already decided)**: the spec specs "/" search and drops ChatSurface's placeholder (Interfaces; Acceptance greps both). Scope objection handled at D2.
- B4 Free previews stepper inline (Clone) vs in the "+" overflow (ADR 0003) — **reject**: Out of Scope keeps it in the overflow per ADR 0003 and plan line 22-23; only the divider and price field are in the row.
- B5 The plan gives no measured Composer geometry — **reject**: the Measured gap table C1–C14 supplies it from the Infloww capture.
- B6 No proof of the PPV row at 390 without a new PNG state — **accept**: the PNG-less `phone-composer-overflow` flow now toggles PPV mode and checks the PPV row in the viewport and Send unmoved.
- B7 Name regression checks for existing Composer behaviour (Enter, Shift+Enter, schedule, attachments, tags) — **partial**: Enter-sends and Shift+Enter-newline added beside the "/" test; the rest stay covered by "every existing send, PPV, free-preview and extras test stays green".
- B8 The 768px Buys & tips rail collision is not closed — **reject**: owner is the human (parent tickets 34, 41, 109) and no Phase 5 plan line covers it (Out of Scope).
- B9 Test at the Composer integration seam on `SendArgs` — **accept**: the "/" test now asserts the following send's `SendArgs` equal a "Scripts" pick's, through `composerTestHarness`.
- B10 Falsifiers (Clone not a proxy, layout not fitting, placeholder overpromising, `SendArgs` drift) — **partial**: the real capture outranks the Clone already; fit and `SendArgs` drift are now gated by B6 and B9.
- B11 A row redesign must say where notices, tagged Creator chips and the GIF strip go (`Composer.tsx:520-592`) — **accept**: new Implementation Decision "Notices" keeps them above row 1, unchanged.

Draft call:
- D1 PPV row order contradicts the plan's "a fourth row" and CONTEXT's "numbered from the top … 4 the PPV row" (`CONTEXT.md:189`) — **needs-human**. For the spec: the plan says only "a fourth row shows" (`docs/plans/messages-pro-look-and-feel.md:75-76`), which can mean a fourth row added rather than a position; the Clone puts `.comp-x` before `.comp-r2` (`messages.html:738`, `:754`) and that keeps Send still. CONTEXT's numbering was written by this run (commit 1d2a1995), so it is not rung 2. For codex: the plain reading of "fourth" in a top-down numbered list is last. Settled by the human's reading of the plan line; if "under row 3", move the PPV row after "Composer toolbar" and drop the `Send unmoved by PPV` check.
- D2 "/" search is scope the plan never asked for (`docs/messages-pro-parity.md:55` records it out of scope) — **reject**: the plan binds the placeholder, and the run brief says work the plan needs but did not list is specced and flagged, not dropped; it is flagged (Further Notes) and stories 5–7 drop cleanly if the human vetoes.
- D3 ⚙ panel's real position is never checked — **accept**: the phone flow opens ⚙ and checks `⚙ panel in viewport`.
- D4 "padding visible" (story 20) is not tested; scrollWidth can pass while clipped — **accept**: added `slide-over padding visible` (each card's right edge inside the slide-over's padding-right).
- D5 The Compare grep accepts "unmatched" and any stray "123px" — **accept**: the pattern now needs a cell that is exactly "matched", or a px cell naming a difference.
- D6 Acceptance counts checks rather than naming them — **accept**: the spec names every new check and the Acceptance asserts those names are present and ok.

Counts: accept 7, partial 2, reject 7 (the earlier tally said 6; B1–B5, B8 and D2 are seven), needs-human 1 (D1, downgraded to an ASSUMPTION by the six-hats reconcile below; now 0).

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- Red/Green, D1's PPV-row needs-human is not material: **accept**. Downgraded to an ASSUMPTION (Further Notes): the PPV row sits between the input and row 3, Send unmoved, by the Clone's order (rung 3) and cheap reversal (rung 4). The only counter-text, CONTEXT.md's "numbered from the top", was written by this run, so it is not rung 2, and CONTEXT.md's PPV row and Composer row entries now say "shown between rows 2 and 3". No material objection remains that the evidence can't settle. Needs-human for this spec is now 0.
- White, the Compare grep `^| Composer |` matches nothing: **accept**. Replaced by a gate that reads CP1–CP7 by ID in Phase 0's row form, fails on a missing row, and passes `matched` or a named remainder.
- Green/Black, gate strictness: **accept**, as above (Phase 0's Named remainder).
- Green, "/" search should be its own ticket; the whole-draft trigger blocks Enter-sending a real "/word": **partial**. It becomes its own clearly vetoable ticket in the Tickets step (Further Notes; tickets are cut later, not here), the "/word" cost is recorded, and the veto fallback is today's placeholder. Stories 5–7 stay the default because the plan binds the placeholder (plan:74).
- Blue, split: **accept** (recorded in plan-review.md): rows and PPV row; "/" search; the two 390 fixes.
