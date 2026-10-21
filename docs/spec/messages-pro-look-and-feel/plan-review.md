# Plan review — messages-pro-look-and-feel

Plan: `docs/plans/messages-pro-look-and-feel.md` (binding). Specs: `phase-00` to `phase-06` in this directory. Reviewed 2026-10-15: one codex adversary pass per spec (blind call and draft call), then one six-hats pass over the whole set (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`), reconciled into each spec's `## Review` under `### Six hats`.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 0 — Measure and pin | `phase-00-measure-and-pin.md` | none (claimed after the Phase 1–5 ticket files exist) |
| 2 | 1 — Colour and shell | `phase-01-colour-and-shell.md` | 0 |
| 2 | 2 — Fan List rows and header | `phase-02-fan-list-rows-and-header.md` | 0 |
| 3 | 3 — Chat header | `phase-03-chat-header.md` | 0, 1 |
| 3 | 4 — Thread and bubbles | `phase-04-thread-and-bubbles.md` | 0, 1 |
| 3 | 5 — Composer | `phase-05-composer.md` | 0, 1 |
| 4 | 6 — Sign-off | `phase-06-sign-off.md` | 0, 1, 2, 3, 4, 5 |

In practice, landing is serial: 0 → 1 → 2 → 3 → 4 → 5 → 6. The waves show what the specs depend on, but Phases 1–5 all edit the same shared files: the Geometry token module `app/lib/messagesPro.ts` and its `EXPECTED` snapshot in `messagesPro.test.ts`, `scripts/ui-shots.sh`, the extras catalogue `app/lib/openinflowwwwExtras.ts`, `ChatSurface`, and the Compare page `docs/screenshots/messages-pro-compare.md`. Running them in parallel would conflict on every one of those files. Phase 2 says Phase 1 is not a hard dependency, but it should land after Phase 1 so the colour diff stays separate (Phase 2, Depends on).

Suggested tracer bullets for the Tickets step (six hats, Blue). Each bullet is a ticket that fits one context window and ends green on its own. The tickets themselves are cut later, not here.
- **Phase 0:** (a) the Compare page header, shots and Compare rows CO–CP, including Part C's TH7–TH9; (b) the Colour inventory and its Literals, plus the page check.
- **Phase 1:** (a) `InflowwPalette`, the per-element splits and the portal roots, with the CO1–CO7 harness samples; (b) hiding the Top bar and moving the sidebar toggle, clock and avatar into the Window header (SH1–SH2); (c) the scope switcher and error badge extras and their catalogue entries.
- **Phase 2:** (a) the row layout (FL1–FL8) and its Gap table snapshot; (b) the header reorder and gallery (FL9–FL10); (c) the Notifications toggle (FL11).
- **Phase 3:** one ticket (one Region).
- **Phase 4:** (a) Part A's action row and per-bubble translate (TH1–TH2); (b) Date dividers, avatars and the Jump chip (TH3–TH6); (c) **Tip reward flag-gating, its own vetoable ticket** (F7a); (d) **Part C, its own vetoable ticket** (F8, TH7–TH9).
- **Phase 5:** (a) the three Composer rows and the PPV row (CP1–CP5); (b) **"/" search, its own vetoable ticket** (stories 5–7; the fallback is today's placeholder); (c) the two 390 fixes and the `phone-composer-overflow` flow (CP6–CP7).
- **Phase 6:** (a) the Visual loop and regression fixes; (b) the Compare re-pin and the parity-doc regrade; (c) the final Acceptance block.

## Adversary

| Spec | Reviewer | Accepted | Partial | Rejected | Needs-human |
|---|---|---|---|---|---|
| Phase 0 | codex (blind B, draft D) | 7 | 5 | 9 | 0 |
| Phase 1 | codex (blind B, draft D) | 6 | 3 | 7 | 0 |
| Phase 2 | codex (blind B, draft D) | 4 | 3 | 9 | 0 |
| Phase 3 | codex (blind B, draft D) | 6 | 3 | 11 | 0 |
| Phase 4 | codex (blind B, draft D) | 9 | 2 | 11 | 0 |
| Phase 5 | codex (blind B, draft D) | 7 | 2 | 7 | 1 → 0 (D1, the PPV row's position, downgraded to an ASSUMPTION by the six-hats reconcile) |
| Phase 6 | codex (blind B, draft D) | 7 | 2 | 7 | 0 |

Phase 5's own tally said 6 rejected. Recounting gives 7 (B1–B5, B8 and D2), and the spec's tally line has been corrected.

Six-hats reconcile lines added per spec: Phase 0: 7, Phase 1: 6, Phase 2: 3, Phase 3: 3, Phase 4: 7, Phase 5: 5, Phase 6: 4.

## Six hats

Each bullet of the report has one line here. A bullet about one or a few specs points to where it was reconciled. A bullet about the whole set is reconciled here.

- **White, CO2 blue vs grey [0/1]:** accept. The rule "a colour the plan names beats the capture" is now in Phase 0's Clone px rules and in Story 7's CO2 entry. The target is the Clone's `#4166f6` (`messages.html:246`), flagged ASSUMPTION. Phase 1 records it.
- **White, Compare gates missing or empty [2/5]:** accept. Phase 5's grep `^| Composer |` matched no row; it now reads CP1–CP7 by ID. Phase 2 gains a scripted gate: FL1–FL11 exist, and each row is matched, `ours` (FL11), or names its remaining px.
- **White, Part C unconditional inside Phase 6's `bash -e` [6]:** accept. Phase 4's Part C block now runs only when the Compare page carries owned Part C rows (TH7–TH9, set up in Phase 0). Phase 6 records the rule.
- **Red, too heavy, "matched" is self-set [0–5]:** partial (Phase 0). The rows and the inventory stay, because the plan requires every item on the page first (plan:33-35). The named-remainder rule replaces forced `matched` everywhere except the browser-checked CO rows.
- **Red, the PPV needs-human is not material [5]:** accept. It is downgraded to an ASSUMPTION at rung 3: the Clone's order, between the input and row 3, with Send unmoved. CONTEXT.md now says "shown between rows 2 and 3".
- **Red, Part C and Tip reward read as a second effort [4]:** partial. Each is now its own vetoable ticket (Phase 4 F7a and F8). Both stay specced, because evidence never shrinks the goal.
- **Black, "all matched" gates vs typography that can't be graded [3/4]:** accept. The per-Phase gates now accept "matched, or names the remaining px with a reason", which is Phase 6's partial rule. Strict `matched` stays only for CO1–CO7 and SH1–SH2 (plan:43-44). Recorded in Phases 0, 3, 4 and 6.
- **Black, raw hex in Phase 4 [4/1]:** accept. Phase 4's colours now go through `InflowwPalette` variables wherever a variable exists. A literal is used only where none does: the liked heart and the chip pair are expected to be literals, and each gets a Literals line. Flagged ASSUMPTION until the inventory exists.
- **Black, the harness is stateless only in name, the `ui-shots.sh` pin, one-off browser reads [0→6]:** partial (Phases 0 and 6). The plan's "no new state" is about outputs, and checks may be added (plan:30). Phase 6 re-pins before it re-runs Phase 0's block. Hover and phone reads moved into the harness through Phases 1, 4 and 5. CH5 stays a recorded browser read, because a flag-on 1440 shot would be new harness state.
- **Yellow, stable row IDs [0]:** accept, no change.
- **Yellow, palette scoping and the scope/error homes [1]:** accept, no change.
- **Yellow, out-of-plan work already split for veto [4/5]:** accept, set-level. The Tickets step keeps Part C, Tip reward gating and "/" search as three separate tickets (Workstreams).
- **Green, settle the PPV row at rung 3 [5]:** accept. Same as Red above.
- **Green, relax gates, guard Part C, use palette variables [2–5]:** accept. Same as the White and Black lines above.
- **Green, Tip reward and "/" search each get their own ticket [4/5]:** partial. Both become their own vetoable tickets (Phase 4 F7a; Phase 5 Further Notes). Both stay the default, because ADR-0003 binds Tip reward and the plan binds the placeholder. The "/word" Enter cost is recorded. If "/" search is vetoed, the fallback is today's placeholder.
- **Blue, serial order [0→6]:** accept, set-level. Workstreams records serial landing 0→1→2→3→4→5→6 and the shared files that force it.
- **Blue, split Phases 0, 1, 4, 5 and 6 into tickets [set]:** accept, set-level. The per-Phase tracer bullets are under Workstreams.
- **Blue, the pre-ticket fix list [2/4/5/6, CONTEXT]:** accept. Every item is fixed: Phase 5's grep, Phase 2's gate, the Part C guard, TH5 against F6, the hex, CO2, and CONTEXT.md's stale "language, pop-out already live there" (corrected in the Window header entry).
- **Recommendation:** accept, set-level. Every point is done above. Tickets are cut after this review.

## Cut (YAGNI)

- **A new harness state, flag, PNG or side-by-side output.** This includes a flag-on 1440 shot, a light-theme shot, open-menu shots and a Notifications-off shot. Reason: the plan says the harness gains no new state (plan:30-31). Phases 0, 3, 5 and 6.
- **A pixel-diff or image-overlay tool.** Reason: it would be a new dependency, it would need stable fonts that the harness refuses, and one manual read answers the question. Phases 0 and 6.
- **A vitest file that parses the Compare page during Phase 0.** Reason: the plan says "No code change yet". Phase 1 may add one. Phase 0.
- **Light-theme Infloww values and Infloww's light palette.** Reason: one dark value set meets the plan's near-black shell, and the Clone is dark-only. Phases 0 and 1.
- **The language box and pop-out icon in the Window header.** Reason: the plan's premise is false, because they don't exist today (`WindowHeader.tsx:32-50`). There is no language setting to drive a language box, and the sidebar already opens a Pop-out window. They stay as `unowned` Compare rows. Phase 1.
- **Changing the shared `--color-*` or `--if-*` tokens, and recolouring Group chat or anything outside Messages Pro.** Reason: ADR-0010 and ADR-0009. Phases 0 and 1.
- **Hiding the Top bar below lg.** Reason: the plan says "at desktop width". Phase 1.
- **A wired Fan List ✕ action.** Reason: no source names its action. Phase 2.
- **A new relay field or call for the verified flag, or any server-side or cross-device store for the toggle.** Reason: the plan binds the cache and forbids a new storage key. Phase 2.
- **Infloww's time format ("10:28 pm", "5:41 pm").** Reason: not a plan item; the parity doc leaves it with the human. Phases 2 and 4.
- **"Unread tips" chip, "Needs reply" order, Fan List pane width, and moving the Fan List buttons or the panel's contents.** Reason: not in this plan. Phase 2.
- **Making Star, Pin, Report, Special offers and Online fans statistics work; "Aa" formatting and Tag › "Release form".** Reason: no relay endpoint exists, so they stay Not wired. Phases 3 and 5.
- **Inline rename in the Chat header.** Reason: it would mean a second edit path without the Nickname freshness guard. Phase 3.
- **The Clone's anchored Find popover.** Reason: Find keeps our search panel, as the parent spec decided. Phase 3.
- **The "↓ Latest" button, the stickers, the PPV status line, the reply card, the media strip, the pinned bar and its overlay.** Reason: not in plan Phase 4. Phase 4.
- **Run grouping beyond avatar placement if Part C is vetoed.** Reason: without Part C, runs only place avatars. Phase 4.
- **The Clone's outline emoji icon and Infloww's AI robot glyph.** Reason: parent tickets left them with the human. Phase 5.
- **The Buys & tips rail overlapping the Composer at 768.** Reason: the human owns it, and no plan line covers it. Phases 5 and 6.
- **Moving the Free previews stepper out of the "+" overflow.** Reason: ADR-0003, and the plan keeps only the divider and the price field in the row. Phase 5.
- **Closing the parent's other "Needs the human" items, re-running parent Phase 0's self-test, adding new parity Regions (such as a Colour Region), and re-measuring the Clone.** Reason: none of these is named by the plan. Phase 6.
- **Colours in Phases 2–5.** Reason: Phase 1 owns them (ADR-0010), so each later Phase only measures and lists colour.

## Not yet specified

None. Every plan line maps to a spec. The plan's only text that leads to no build is Phase 1's "(SFW toggle, language, pop-out already live there)". Phase 1 found it false and cut the language box and pop-out icon; they stay visible as `unowned` Compare rows (see Cut).

## Open questions

Every ASSUMPTION across the specs, sharpest first. Each line says what falls if the assumption is wrong.

1. **CO2's target is the plan's blue (Clone `#4166f6`), not the capture's grey (P0).** If wrong, CO2 and one value in Phase 1's palette change, and Phase 1's CO2 harness sample changes with them.
2. **The Infloww accent is taken from a capture sample, not the stylesheet's orange `--element-action-primary-emphasis-00` (P0).** If wrong, CO1 and every accent use in the palette change.
3. **Per-Phase gates accept a named remainder; only CO and SH rows must be strictly `matched` (P0).** If wrong, every FL, CH, TH and CP gate goes back to strict `matched`, and text-width rows can block their Phase.
4. **Messages Pro stays Infloww-dark under the light theme (P1).** If wrong, `InflowwPalette` needs a second value set and the inventory needs a light column.
5. **One `InflowwPalette` component writing inline custom properties meets ADR-0010's "values in JSX" (P1).** If wrong, shared chat components need a colour prop from every Messages Pro caller.
6. **Phase 4's colours go through palette variables; literals are used only where none holds the value (P4).** If wrong (the inventory maps none of them), more Literals lines appear. No shared token is added.
7. **Tip reward is an automation extra and is hidden with the flag off, as its own vetoable ticket (P4).** If wrong, it becomes a non-automation extra with a flag-off overflow host, and the catalogue entry, Story 19 and the audit fixture change.
8. **The placeholder needs a working "/" search, triggered only by the whole draft, with Send unchanged (P5).** If wrong, stories 5–7 drop and the fallback is today's placeholder; if a mid-draft trigger is shown, the trigger rule changes.
9. **Part C (bubble shape, run gap, time under the run) is specced as its own ticket (P4).** If vetoed, TH7–TH9 go `unowned`, the Part C block skips itself, and the Message list Region stays `partial`.
10. **The PPV row sits between rows 2 and 3, with Send unmoved (P5).** If wrong, the PPV row moves under row 3, two checks drop, and CONTEXT.md's two entries revert.
11. **The Notifications toggle lives in `chatterly:notif-settings:v1` as a per-Employee `panelOffFor` list (P2).** If wrong (the human meant the `preferences` blob), it needs a per-Employee shape, a chatter-writable route and an ADR-0008 amendment.
12. **The scope switcher and error badge become catalogued Window header extras (P1).** If wrong, both leave Messages Pro at desktop and two catalogue entries drop.
13. **The relay passes `isVerified` through (P2, P3; evidence blocked).** If wrong, the verified badge never shows and its Compare rows name that.
14. **Re-pinning `Measured at` to the final commit is allowed (P6).** If wrong, Phase 0's block can't pass after Phase 1 and is recorded as `SUPERSEDED:`.
15. **A superseded parent Acceptance line is corrected in its parent spec (P6).** If wrong, those lines stay red and step 1 fails, naming them.
16. **The baseline is the parent of the commit that added the plan, not `main` (P6).** If wrong, the `service/` lines fail until the branch merges.
17. **This plan's own Phase 0–5 blocks are re-run at sign-off as well as the parent's (P6).** If wrong, step 1 runs only the parent's blocks.
18. **"matched" means ±1 CSS px, and the same rendered hex for colour (P0).** If the human names another tolerance, every status is re-read.
19. **The Compare row IDs (CO/SH/FL/CH/TH/CP) are coined in Phase 0 (P0).** If a Phase splits or merges an item, rows split or merge and the `need` lists follow.
20. **A capture's value sits in the Clone px cell marked "(wins)" or "(overridden by plan)", not in an eighth column (P0).** If wrong, the page format and every parser change.
21. **The Colour inventory is a section of the Compare page, with one line per base class (split by role) and one per literal, and no use-count column (P0).** If wrong, it moves to a separate doc or goes one line per variant.
22. **"Messages Pro JSX" means `app/components/chat/` and `app/app/messages-pro/` (P0).** If wrong, a shared component outside them joins the scope.
23. **Colours with no Infloww counterpart are "keep" (P0).** If wrong, a capture showing Infloww painting the same element maps that line to a sampled value.
24. **The Ticket cell names one ticket number, and extra rows may read `unowned` (P0).** If tickets are cut after Phase 0, required rows carry Phase labels and the ticket check is relaxed.
25. **The "nothing from captures" check only checks file names; a human skim covers content (P0).** A stronger check would replace the skim.
26. **The moved controls go after SFW and the Extras overflow (P1).** If wrong, the order in the Window header changes.
27. **Losing the Top bar's arrival counter on desktop Messages Pro is acceptable (P1).** If wrong, it becomes a third Window header extra.
28. **The error badge in the overflow always shows, reading "none" at zero (P1).** If wrong, the extras-audit fixture has to stub a non-zero count.
29. **The one-frame Top bar flash on first desktop load is accepted (P1).** If wrong, the hide moves to a pathname-keyed `lg:hidden`.
30. **Wrapping `pageTree` in `AppShell` is the page-through-shell seam (P1).** If wrong, those cases move into `AppShell.test.tsx`.
31. **"Language, pop-out already live there" is a mistaken premise, not a request to build them (P1).** If wrong, a later ticket builds both.
32. **Infloww's unread marker size is unknown (evidence blocked); the Clone's 9px stands (P2).** A capture of an unread row would replace it.
33. **The Fan List ✕ is inert (P2).** If the human names its action, the ✕ calls that existing action.
34. **The Notifications toggle is not catalogued as an extra (P2).** If wrong, it needs a new Host and an ADR-0003 amendment.
35. **"All inboxes" stays hidden in All Models (P2).** If wrong, it shows in All Models.
36. **The muted bell also shows on unread muted rows (P2).** A capture showing otherwise reverts it.
37. **The "All Models marker" is nothing in the Chat header (P3).** If the human names a marker, it goes into the Chat header overflow.
38. **📈's rows go into the Kebab menu, and the "+" becomes the Kebab's last row opening a submenu (P3).** If wrong, they go into the Extras overflow or inline, or the "+" stays an icon.
39. **The Persona button goes into the Chat header Extras overflow (P3).** If wrong, it becomes a Kebab row.
40. **The Chat header has no avatar, and the name opens the Avatar menu (P3).** If wrong, the 36px avatar returns to line 1.
41. **The Fan insights toggle stays at every width (P3).** If wrong, it hides from lg up.
42. **The AI strip band stays under the header (P3).** If wrong, it moves into the overflow.
43. **The pencil focuses Nickname in Fan insights (P3).** If wrong, Infloww's inline rename is built.
44. **The capture's scale is 2× and its font sizes are inferred at ±1px (P3).** If the Compare measurement shows another scale, every CH px is re-measured.
45. **The Chat header uses the capture's 20px padding and 52px height from md up (P3).** If wrong, the Clone's 18px and 58px apply.
46. **The word fold moves to a 448px Thread (P3).** If the words clip at 1280, the threshold rises.
47. **Bubble action icons are our own inline SVG (P4).** If the repo already has an icon set for these glyphs, that set is used.
48. **Reply, Pin and Unsend on our bubbles move into a ⋮ menu (P4).** A capture of Infloww's ⋮, or a human preference, changes it.
49. **Per-bubble translate goes through `useTranslations`, OR-ed with the thread-wide mode (P4).** If Infloww's icon opens a menu, that menu is built.
50. **Date dividers read "Today" or "Sep 29", with the year for another year and no "Yesterday" (P4).** A capture showing "Yesterday" adds it.
51. **The avatar is 36px and bottom-aligned, also below md (P4).** If the Clone's 38px is ruled the target, or phone bubbles are too narrow, it becomes 38px, or 28px on phone.
52. **A run is the same side, the same minute and the same "Sent by", and breaks on a receipt change (P4).** If Infloww's rule is observed to differ, the grouping changes.
53. **The 16px bubble text is measured from glyph heights (P4).** A direct reading changes the token only.
54. **The reply strip sits with the PPV row, under the input (P5).** If wrong, it moves above the input.
55. **The "free-preview notice" is the existing divider tile (P5).** If wrong, a text notice shows in PPV mode.
56. **The price field is 32px tall with a 4px radius (P5).** A capture of Infloww's price input replaces these.
57. **Pill label weights stay 600 and 700 (P5).** The visual loop may lower them to 400.
58. **The row-1 label threshold is a 480px Thread (P5).** If wrong, row 1 wraps on a phone instead.
59. **The slide-over keeps its 56px gutter and shrinks to 334px (P5).** If wrong, it goes full-width on a phone.
60. **A colour gap counts as the "px difference", written as a hex (P6).** If wrong, colour gaps are graded separately.
61. **The non-visual partial phrase is "no px difference remains" (P6).** If wrong, those Ours cells carry no phrase.
62. **The flag-on check uses the sweep's 1280 shot (P6).** A flag-on 1440 shot would be a new harness state.
63. **"Phone and desktop shots" means the existing default and sweep shots (P6).** A new 390 shot would be a new harness state.
64. **A multi-Region Compare row lists its Regions comma-separated (P6).** If Phase 0 uses another separator, step 4's split follows it.

## Needs the human

None after reconciliation.
- Phase 5 had one needs-human from codex, D1 (the PPV row's position). The six-hats reconcile downgraded it to an ASSUMPTION at rung 3: the Clone's order keeps Send still, and undoing it costs one JSX reorder and one check. The only counter-text was CONTEXT.md, which this run wrote, so it is not rung 2. No material objection remains that the evidence can't settle.
- Phases 0–4 and 6: none.

The human can veto any of three tickets on its own: Phase 4's Tip reward gating, Phase 4's Part C, and Phase 5's "/" search. Open questions 1–10 are the ones to read first.
