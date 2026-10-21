# Phase 06 — Geometry pass

**Objective.** Every Messages Pro Region takes its Geometry from one token module, `app/lib/messagesPro.ts`. That covers pane widths, row heights, paddings, radii, font sizes and icon sizes. The numbers in the module equal the measured table below, which reconciles the numbers Phases 1–5 measured, and a snapshot test pins the module to that table. No Messages Pro component carries a magic number in JSX. At 1280×800 and 1440×900, in the app and in the Pop-out window, Messages Pro shows three panes with no horizontal scroll. Colours come only from the `app/app/globals.css` tokens (ADR-0001).

## Gap table

**Sources.**
- `m.html` is `ui-redesign/infloww-exact/messages.html`, with CSS at `:11-576` and markup at `:578-880`.
- `m.js` is `ui-redesign/infloww-exact/messages.js`.
- `kit` is `ui-redesign/infloww-exact/_shared/components.html`. It is the Inflowwww fx kit (`:28-195`), and only three of its rules apply to Messages Pro: `.fx-new` `:188-189`, `.fx-note` `:191-192` and `.fx-select` `:106-107`.
- `orig` is the Clone's screenshot build, `git show 4e83397:ui-redesign/infloww-exact/messages.html`.
- `_shared/palette.js` is a ⌘K command palette that "The real app has no such thing" (`palette.js:5-6`). It supplies no Messages Pro Geometry.

**Row references.**
- P1 `<selector>` is the Phase 1 Gap table row for that selector.
- P2 #n, P3 Hn, Mn or Ln, P4 #n and P5 Gn are those Phases' numbered Gap table rows.
- P0 #3 is the Phase 0 pane row.

**Gap kinds.**
- **lift**: the owning Phase applies the value inline, and this Phase moves it into the module unchanged.
- **lift + notation**: as lift. Earlier drafts rewrote the Phase's Tailwind scale classes as `[Npx]`; since tickets 106 and 110 (D1) the token keeps the scale class, with the same pixel value.
- **change**: our value differs, and this Phase changes it.
- **new**: no Phase claimed the element, and this Phase applies the Clone value.
- **no element**: the owning Phase draws no element for this Clone rule, so the row has no token.

**The Change column is the canonical table.** It holds the exact class string of each token `MP.<region>.<element>`, and the snapshot test transcribes it (Implementation Decisions, D2). A value that is in neither the Clone nor §3.3 carries an `ASSUMPTION:` in the decision it belongs to. Notation (ticket 110): a pixel value the Tailwind 4 scale has is its scale class (`h-11.5` = 46px, `size-1.75` = 7px, `rounded-lg` = 8px, `py-px` = 1px, `leading-normal` = 1.5); an arbitrary value stays only where the scale lacks it (`rounded-[9px]`, `tracking-[.5px]`, `leading-[1.4]`, `w-[52%]`). Font sizes stay `text-[Npx]`, because a scale font class also sets a line height (`--text-xs--line-height`, `app/node_modules/tailwindcss/theme.css:347-358`), so the line takes PN1's inherited 1.4. A scale font class stays only where the Change column holds it: PN1, CP11 (reconcile item 5), and the phone values of ML3, CP7, PV4 and FI33 (reconcile item 6). Where a Phase wrote a scale font class and the row holds `text-[Npx]` (FL29, FL37, FI6, FI11, FI14, FI28), the row wins (tickets 113 and 118). Either notation passes the guard, because a Tailwind scale class is not a magic number (plan, "Decisions from the human (2026-10-12, resuming the run)", Scale classes). Where Phase 1, Phase 3 or tickets 106 and 108 already wrote the token, the Change column holds the module's string as it renders today, layout keywords included (`flex`, `items-center`, `truncate`), and colour stays in JSX (ADR-0001); the lift ticket of its Region checks it against the Clone. Where such a token's Geometry differs from the Clone, the Gap column reads `change (<ticket>)` and the Clone's string follows the token string in parentheses: that ticket sets the token to it, and updates the row and the snapshot together.

ASSUMPTION: the Change column, not a Phase's earlier notation, decides a font size's notation; this settles the conflict ticket 118's review found between this paragraph's old "except where a Phase already wrote the scale class" and the `text-[Npx]` rows (ticket 120; rung 5: the rows and the snapshot already agree, so only this sentence changes). Overturned if the human wants the six rows back on their Phase's scale class, which changes those tokens, the rows and the snapshot together.

### Panes and page

| # | Clone selector · CSS (line) | Ours after Phases 0–5 (row) | Gap | Change: token = class string |
|---|---|---|---|---|
| PN1 | `body` font-size 14px, line-height 1.4 (`m.html:37`) | P0 #3: none; the page inherits the `globals.css` body | new | `MP.panes.root` = `text-sm leading-[1.4]` |
| PN2 | `.list` width 390px, min-width 390px, border-right 1px (`:116`) | P0 #3, P1 `.list`, P2 #1 (all deferred here): `app/app/messages-pro/page.tsx:189` grid column `320px` | change 320→390; 400 since the 2026-10-18 Infloww capture (531px / 1.32, page-parity 07 FL12) | `MP.panes.fanList` = `lg:w-100 lg:min-w-100 border-r` |
| PN3 | `.center` flex 1, min-width 0 (`:193`) | P0 #3: `page.tsx:189` `minmax(0,1fr)` | no number | No token. JSX keeps `flex-1 min-w-0` and adds `@container` (D4). The `lg:grid-cols-[…320px…]` value at `page.tsx:189` goes with the roster (Phase 1) |
| PN4 | `.right` width 280px, min-width 280px, border-left 1px (`:292`) | P5 G1: inline, was `w-[360px]` (`FanDrawer.tsx:332`) | lift | `MP.panes.insights` = `lg:w-70 lg:min-w-70 lg:border-l` |
| PN5 | Follows `.list` (`:116`). The Clone has no pinned-messages overlay | `components/chat/PinnedPanel.tsx:39` `CHAT_LIST_WIDTH = 320`, used at `:165` | change 320→390; 400 with PN2 (page-parity 07) | `MP.panes.pinnedOverlay` = `w-full max-w-100` |

### Window header

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| WH1 | `.topstrip` height 46px, min-height 46px, padding 0 14px, border-bottom 1px (`:50-53`, `:101`) | P1 `.topstrip` | lift | `MP.windowHeader.bar` = `h-11 min-h-11 px-3.5 border-b` |
| WH2 | `.htab` gap 7px, 12.5px/600, padding 6px 16px, radius 8px 8px 0 0 (`:87-88`) | P1 `.htab`, and Group chat in the Fan tabs row | lift | `MP.windowHeader.home` = `ml-1 w-41 h-6 gap-1.75 rounded-tl-lg text-[13px] font-semibold [clip-path:polygon(0_0,calc(100%-10px)_0,100%_100%,0_100%)]` |
| WH3 | `.htab svg` 15px (`:89`) | P1 `.htab` | lift | `MP.windowHeader.homeIcon` = `size-3.75` |
| WH4 | `.am-hero` height 30px, padding 0 14px, margin-left 2px, gap 7px, radius 8px, 13px/700, margin-bottom 5px (`:92-94`, `:104`) | P1 `.am-hero` (flag on) | lift | `MP.windowHeader.allModels` = `mb-1.25 ml-0.5 gap-1.75 h-7.5 px-3.5 rounded-lg text-[13px] font-bold` |
| WH5 | `.am-hero svg` 16px (`:95`) | P1 `.am-hero` | lift | `MP.windowHeader.allModelsIcon` = `size-4` |
| WH6 | `.add-creator` gap 7px, 13px/500, padding 0 14px (`:68`) | P1 `.add-creator` | lift | `MP.windowHeader.addCreator` = `gap-1.75 px-3.5 text-[13px] font-medium` |
| WH7 | `.add-creator svg` 15px (`:69`) | P1 `.add-creator` | lift | `MP.windowHeader.addCreatorIcon` = `size-3.75` |
| WH8 | `.top-right` gap 14px (`:70`) | P1 `.top-right` | lift | `MP.windowHeader.right` = `gap-3.5` |
| WH9 | `.sfw` column, gap 3px (`:71`) | P1 `.sfw` | lift | `MP.windowHeader.sfw` = `gap-0.75` |
| WH10 | `.sfw span` 10px/600, letter-spacing .5px (`:72`) | P1 `.sfw` | lift | `MP.windowHeader.sfwLabel` = `text-[10px] font-semibold tracking-[.5px]` |
| WH11 | `.switch` 26×14, radius 8px (`:73`) | P1 `.switch` | lift | `MP.windowHeader.switch` = `w-6.5 h-3.5 rounded-lg` |
| WH12 | `.switch:before` top 2px, left 2px, 10×10, round (`:74`) | P1 `.switch` | lift | `MP.windowHeader.switchKnob` = `top-0.5 left-0.5 size-2.5 rounded-full` |
| WH13 | None: the Clone draws only the off state (`:73-74`) | P1 `.switch` | new | `MP.windowHeader.switchKnobOn` = `translate-x-3` (D10) |
| WH14 | `.icon-btn` 26×26, radius 7px (`:77`): the Window header's Extras overflow "+" | P1 Extras overflow; Phase 7 trigger | removed | removed 2026-10-18 with the in-app layout's shell controls, its last user (ADR-0002) |
| WH15 | `.icon-btn svg` 18px (`:79`) | P1, Phase 7 | removed | removed 2026-10-18 with WH14 |

### Creator tabs

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| CT1 | `.ctabs` gap 4px, max-width 58vw (`:332`) | P1 `.ctabs` | lift | `MP.creatorTabs.strip` = `gap-1 max-w-[58vw]` |
| CT2 | `.ctab` height 36px, padding 0 10px 0 6px, gap 8px, radius 9px 9px 0 0, max-width 220px, 1px border with no bottom edge (`:56-58`, `:334`) | P1 `.ctab` | lift | `MP.creatorTabs.tab` = `gap-2 h-9 pl-1.5 pr-2.5 max-w-55 rounded-t-[9px] border border-b-0` |
| CT3 | `.ctab.active` `box-shadow: inset 0 2px 0` (`:336`), inside the tab's 1px border (`:334`) | P1 `.ctab` | lift | `MP.creatorTabs.tabActive` = `inset-shadow-[0_2px_0]` (D10) |
| CT4 | `.ctab .cav` 26×26, radius 6px; initials 800 11px (`:60`, `:340`) | P1 `.ctab .cav` | lift | `MP.creatorTabs.avatar` = `size-6.5 rounded-md text-[11px] font-extrabold` |
| CT5 | `.ctab .cname` 13px/700 (`:62`) | P1 `.ctab .cname` | lift | `MP.creatorTabs.name` = `text-[13px] font-bold` |
| CT6 | `.mini-badge` min-width 16px, height 16px, padding 0 4px, radius 8px, 10px/700 (`:63-64`) | P1 `.mini-badge` (Creator tab), and the Fan tab badge (P1 ASSUMPTION) | lift; a pill since page-parity 07 (Infloww radius 22px) | `MP.creatorTabs.badge` = `min-w-4 h-4 px-1 rounded-full text-[10px] font-bold` |
| CT7 | `.ctab .cclose` 16×16, margin-left 2px (`:67`) | P1 `.ctab .cclose` | lift | `MP.creatorTabs.close` = `size-4 ml-0.5` |
| CT8 | `.ctabs-empty` 12px, padding 0 10px (`:358`) | P1 `.ctabs-empty` | lift | `MP.creatorTabs.empty` = `px-2.5 text-[12px]` |

### Fan tabs

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| FT1 | `.hometabs` height 34px, min-height 34px, padding 0 14px, border-bottom 1px (`:82`) | P1 `.hometabs` | lift | `MP.fanTabs.bar` = `h-8 min-h-8 pr-3.5 border-b` |
| FT2 | `.thread-tabs` gap 3px (`:194`); inside `.hometabs`, margin-left 4px (`:108`) | P1 `.hometabs .thread-tabs` | lift | `MP.fanTabs.strip` = `gap-0.75 ml-1` |
| FT3 | `.ttab` gap 8px, padding 7px 11px, radius 8px 8px 0 0, 12.5px/600, max-width 190px, 1px border with no bottom edge (`:195`) | P1 `.ttab` | lift | `MP.fanTabs.tab` = `gap-2 py-1.75 px-2.75 max-w-47.5 rounded-t-lg border border-b-0 text-[12.5px] font-semibold leading-[1.4]` |
| FT4 | `.ttab.active` `box-shadow: inset 0 2px 0` (`:197`), inside the tab's 1px border (`:195`) | P1 `.ttab` | lift | `MP.fanTabs.tabActive` = `inset-shadow-[0_2px_0]` (D10) |
| FT5 | `.ttab-dot` 7×7, round (`:110`) | P1 `.ttab-dot` | lift | `MP.fanTabs.dot` = `size-1.75 rounded-full` |
| FT6 | `.ttab-x` 11px, line-height 1, radius 4px, padding 2px 4px (`:199`) | P1 `.ttab-dot` row | lift | `MP.fanTabs.close` = `px-1 py-0.5 rounded-sm text-[11px] leading-none` |

### Fan List

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| FL1 | `.list-head` padding 16px 16px 12px, gap 6px (`:117`) | P2 #2 | lift | `MP.fanList.head` = `h-13 pl-2.75 pr-3 gap-3 border-b` |
| FL2 | `.list-head h1` 22px/700 (`:118`) | P2 #3 | lift | `MP.fanList.title` = `text-[20px] font-medium` |
| FL3 | `.icon-btn` 26×26, radius 7px (`:77`) | P2 #4, with a 36px or larger phone tap target (P2 decisions, `ChatList.tsx:1244`) | lift | `MP.fanList.iconButton` = `size-9 md:size-6.5 rounded-[7px]` |
| FL4 | `.list-head .icon-btn svg` 20px (`:119`) | P2 #4 | lift | `MP.fanList.iconButtonIcon` = `size-5` |
| FL5 | `.big-btns` gap 12px, padding 4px 16px 14px (`:122`) | P1 `.big-btns` | lift | `MP.fanList.buttons` = `gap-7 pt-4.5 px-2.5 pb-2.5` |
| FL6 | `.big-btns button` height 42px, radius 9px, gap 8px, 14px/600 (`:123`) | P1 `.big-btns` | lift | `MP.fanList.button` = `h-7 gap-1.5 rounded-sm text-[14px] font-medium` |
| FL7 | `.big-btns svg` 18px (`:126`) | P1 `.big-btns` | lift | `MP.fanList.buttonIcon` = `size-4` |
| FL8 | `.notif-badge` top −7px, right −6px, min-width 22px, height 22px, radius 11px, 12px/700, 2px border (`:127-128`) | P1 `.notif-badge` | lift | `MP.fanList.notifBadge` = `-top-2.5 -right-2.5 min-w-5 h-5 px-1.5 rounded-full text-[13px] font-medium border` |
| FL9 | Online Fans pressed: 2px outline (`m.js:3103-3107`) | P1 pressed-state row | lift | `MP.fanList.buttonPressed` = `ring-2` |
| FL10 | `.filter-row` gap 10px, padding 2px 16px 12px, wraps with row-gap 6px (`:130`, `:357`) | P2 #7 | lift | `MP.fanList.filters` = `gap-x-2.5 gap-y-1.5 px-2.75 pb-3` |
| FL11 | `.inbox-box` gap 8px, border 1px, radius 9px, padding 9px 11px, 13.5px, min-width 150px (`:131`, `:354`) | P2 #8 | lift | `MP.fanList.inbox` = `gap-2 px-2.75 h-8.5 rounded-sm text-[14px] min-w-37.5 border` |
| FL12 | `.inbox-box svg` 16px (`:132`) | P2 #8 | lift | `MP.fanList.inboxIcon` = `size-4` |
| FL13 | `.filter-row .gear` 34×34, radius 8px (`:134`) | P2 #9 | lift | `MP.fanList.gear` = `w-9 h-8.5 rounded-sm` |
| FL14 | `.gear svg` 19px (`:136`) | P2 #9 | lift | `MP.fanList.gearIcon` = `size-4.75` |
| FL15 | `.sortline` gap 9px, 13px (`:137`) | P2 #10 | lift | `MP.fanList.sort` = `gap-2.25 text-[14px]` |
| FL16 | `.sortline svg` 17px (`:139`) | P2 #10 | lift | `MP.fanList.sortIcon` = `size-4.25` |
| FL17 | `.chips` gap 8px, padding 0 16px 12px (`:141`) | P2 #11 | lift | `MP.fanList.chips` = `gap-2.5 px-2.75 pb-3` |
| FL18 | `.chip` padding 7px 15px, radius 16px, 13px/500 (`:143`) | P2 #12; phone keeps `px-3 py-1.5 min-h-[36px]` (`ChatList.tsx:1244`) | lift | `MP.fanList.chip` = `px-3 py-1.5 min-h-[36px] md:h-6.5 md:py-0 md:min-h-0 rounded-2xl text-[14px]` |
| FL19 | `.chip .cbadge` top −5px, right −4px, min-width 17px, height 17px, padding 0 3px, radius 9px, 10px/700 (`:145`) | P2 #14 | lift | `MP.fanList.chipBadge` = `-top-2 -right-1.5 min-w-4 h-4 px-0.75 rounded-full text-[11px] font-medium` |
| FL20 | `.chips.folders` padding-bottom 10px (`:147`) | P2 #15 | lift; retired by page-parity 07 (the OF lists sit in the chip row, Infloww 2026-10-18) | none |
| FL21 | `.fchip` gap 6px, padding 6px 13px, 12.5px/500, radius 16px, border 1px (`:148-149`) | P2 #15, #16 | lift | `MP.fanList.folderChip` = `gap-1.5 px-3.25 py-1.5 rounded-2xl text-[12.5px] font-medium border` |
| FL22 | `.fchip svg` 13px (`:152`) | P2 #15 | lift; retired by page-parity 07 (Infloww's list chip has no icon) | none |
| FL23 | `.conv` gap 12px, padding 13px 16px, border-bottom 1px (`:159`) | P2 #17 | lift; page-parity 07: the divider stops 9px short of the right edge (2026-10-18 capture) | `MP.fanList.row` = `h-24 gap-2.5 px-4.75 pt-4 after:absolute after:bottom-0 after:left-15 after:right-2.25 after:h-px` |
| FL24 | `.av` 48×48, round, 13px/700 (`:162-163`) | P2 #18 | lift | `MP.fanList.avatar` = `size-12 rounded-full text-[13px] font-bold` |
| FL25 | `.av svg` 22px (`:168`) | P2 #18 | lift | `MP.fanList.avatarIcon` = `size-5.5` |
| FL26 | `.dot` bottom 1px, right 1px, 12×12, 2px ring (`:169`) | P2 #19 | lift | `MP.fanList.onlineDot` = `bottom-px right-px size-3 rounded-full border-2` |
| FL27 | `.spend` bottom −7px, left −3px, 11px/700, padding 1px 5px, radius 8px (`:171`) | P2 #20 | lift | `MP.fanList.spend` = `top-full left-1/2 -translate-x-1/2 mt-1 h-4 px-1 rounded-xs text-[13px] leading-4 font-bold` |
| FL28 | `.conv-top` gap 5px (`:174`) | P2 #21 | lift | `MP.fanList.top` = `gap-1.25` |
| FL29 | `.cname` 14px/700, max-width 170px (`:175`) | P2 #21 | lift | `MP.fanList.name` = `text-[15px] font-medium max-w-42.5` |
| FL30 | `.chandle` 13px (`:176`) | P2 #21 | lift | `MP.fanList.handle` = `text-[15px]` |
| FL31 | `.off-label` margin-top 3px, 11px/800, letter-spacing .5px (`:179`) | P2 #22 | lift | `MP.fanList.offLabel` = `mt-0.75 text-[11px] font-extrabold tracking-[.5px]` |
| FL32 | `.fx-new` 9px/700, letter-spacing .03em, padding 2px 6px, radius 5px (`kit:188-189`) | P2 #22 | lift | `MP.fanList.newBadge` = `px-1.5 py-0.5 rounded-[5px] text-[9px] font-bold tracking-[.03em]` |
| FL33 | `.conv-bot` gap 6px, margin-top 4px (`:181`) | P2 #23 | lift | `MP.fanList.bottom` = `gap-1.5 mt-1` |
| FL34 | `.cprev` 13px, gap 5px (`:182`) | P2 #23 | lift | `MP.fanList.preview` = `gap-1.25 text-[14px]` |
| FL35 | `.cprev.bold` 600 (`:183`) | P2 #23 | lift | `MP.fanList.previewUnread` = `font-semibold` |
| FL36 | `.cprev svg` 14px (`:184`) | P2 #23 | no element | none: our preview draws its 💰/🔒/📎 markers as text, so no icon takes the size (ticket 119) |
| FL37 | `.ctime` 12px (`:185`) | P2 #23 | lift | `MP.fanList.time` = `text-[14px]` |
| FL38 | `.ud` 9×9, round (`:187`) | P2 #24 | lift | `MP.fanList.unreadDot` = `size-2.25 rounded-full` |
| FL39 | `.owe-dot` 9×9, round, 2px halo (`:188-189`) | P2 #24 (extra) | lift | `MP.fanList.oweDot` = `size-2.25 rounded-full ring-2` |
| FL40 | `.mute-i` 14×14 (`:190`) | P2 #25 | lift | `MP.fanList.muteIcon` = `size-3.5` |
| FL41 | Empty state padding 24px 16px, 13px (`m.js:481-482`) | P2 #26 | lift | `MP.fanList.empty` = `px-4 py-6 text-[13px]` |
| FL42 | `.skel-row` gap 12px, padding 13px 16px, border-bottom 1px (`:566`) | P2 #27 | lift | `MP.fanList.skeletonRow` = `gap-3 px-4 py-3.25 border-b` |
| FL43 | `.skel-av` 48×48, round (`:567`) | P2 #27 | lift | `MP.fanList.skeletonAvatar` = `size-12 rounded-full` |
| FL44 | `.skel-lines` gap 10px (`:568`) | P2 #27 | lift | `MP.fanList.skeletonLines` = `gap-2.5` |
| FL45 | `.skel-bar` height 11px, radius 6px (`:569`) | P2 #27 | lift | `MP.fanList.skeletonBar` = `h-2.75 rounded-md` |
| FL46 | `.skel-bar.w1` 52% (`:570`) | P2 #27 | lift | `MP.fanList.skeletonBarShort` = `w-[52%]` |
| FL47 | `.skel-bar.w2` 78% (`:571`) | P2 #27 | lift | `MP.fanList.skeletonBarLong` = `w-[78%]` |
| FL48 | `.load-more` padding 14px 16px, 13px/600, border-top 1px (`:155-156`) | P2 #28 | lift | `MP.fanList.loadMore` = `px-4 py-3.5 text-[13px] font-semibold border-t` |
| FL49 | `.fx-note` gap 10px, border 1px, radius 10px, padding 11px 14px, 13px, line-height 1.5 (`kit:191-192`) | P2 #29 | lift | `MP.fanList.focusBanner` = `gap-2.5 px-3.5 py-2.75 rounded-[10px] text-[13px] leading-normal border` |
| FL50 | `.fx-select` height 38px, border 1px, radius 9px, 13.5px, padding 0 12px (`kit:106-107`), and padding-right 32px for its chevron (`kit:108-110`) | P2 #30 | lift | `MP.fanList.splitSelect` = `h-9.5 pl-3 pr-8 rounded-[9px] text-[13.5px] border` |

### Chat header

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| CH1 | `.thread-head` gap 14px, padding 12px 18px, border-bottom 1px, min-height 58px (`:201`, `:350`) | P3 H1 from md up; the phone keeps `px-3 py-3 gap-2` (`ChatSurface.tsx:878`, P3 F14) | lift | `MP.chatHeader.bar` = `px-3 py-3 gap-2 md:px-4.5 md:py-3 md:gap-3.5 md:min-h-14.5 border-b` |
| CH2 | `.back` 22×22 (`:202`) | P3 H2 | lift | `MP.chatHeader.back` = `size-5.5` |
| CH3 | None: the Clone header has no avatar. Ours is 36px (`ChatSurface.tsx:898`) | P3 H3, F16 | lift | `MP.chatHeader.avatar` = `size-9 rounded-full` |
| CH4 | `.th-id` column, gap 2px, margin-right 6px (`:203`) | P3 H4 | lift | `MP.chatHeader.identity` = `gap-0.5 mr-1.5` |
| CH5 | `.th-name-row` gap 6px (`:204`) | P3 H4 | no element | none: our name line holds the name alone (the verified tick is out of scope), so there is no row to space (ticket 119) |
| CH6 | `.th-name` 16px/700 (`:205`) | P3 H4 | lift | `MP.chatHeader.name` = `text-[16px] font-bold` |
| CH7 | `.th-status` gap 6px, 12px (`:206`) | P3 H5 | lift | `MP.chatHeader.status` = `gap-1.5 text-[12px]` |
| CH8 | `.th-status .sdot` 8×8, round (`:207`) | P3 H5 | lift | `MP.chatHeader.statusDot` = `size-2 rounded-full` |
| CH9 | `.th-tools` gap 4px (`:210`) | P3 H6 | lift | `MP.chatHeader.tools` = `gap-1` |
| CH10 | `.th-tools .icon-btn` 30×30 (`:211`), radius 7px (`:77`) | P3 H6, H8 (Persona, `#tbModel`, mh:703), H10, H11, H16, and the Extras overflow "+" (Phase 7) | lift | `MP.chatHeader.iconButton` = `size-7.5 rounded-[7px]` |
| CH11 | `.th-tools .icon-btn svg` 19px (`:212`) | P3 H6 | lift | `MP.chatHeader.iconButtonIcon` = `size-4.75` |
| CH12 | `.th-tools .lbl` gap 6px, padding 6px 8px, radius 7px, 13px (`:213`) | P3 H7 | lift | `MP.chatHeader.label` = `gap-1.5 py-1.5 px-2 rounded-[7px] text-[13px] leading-[1.4]` |
| CH13 | `.lbl svg` 17px (`:215`) | P3 H7 | lift | `MP.chatHeader.labelIcon` = `size-4.25` |
| CH14 | None. Measured: the Clone's labelled header needs 768px at 1440×900 and overflows at 1280×800 (Further Notes) | P3 H7, H9: always labelled | new | `MP.chatHeader.labelText` = `sr-only @min-[886px]:not-sr-only` (D4) |
| CH15 | `.th-right` gap 4px (`:216`) | P3 H9 | lift | `MP.chatHeader.right` = `gap-1` |
| CH16 | `.open-new` gap 6px, 13px/600, padding 6px 8px, radius 7px (`:217`) | P3 H9 | lift | `MP.chatHeader.openNew` = `gap-1.5 py-1.5 px-2 rounded-[7px] text-[13px] font-semibold leading-[1.4]` |
| CH17 | `.open-new svg` 16px (`:218`) | P3 H9 | lift | `MP.chatHeader.openNewIcon` = `size-4` |
| CH18 | `.ai-strip` gap 5px 12px, padding 7px 18px, 11.5px, line-height 1.35, border-bottom 1px (`:475-476`) | P3 H14 (flag on) | lift | `MP.chatHeader.aiStrip` = `gap-x-3 gap-y-1.25 px-3 py-1.75 md:px-4.5 text-[11.5px] leading-[1.35] border-b` (the phone keeps `px-3`, P3 F14, pinned by `ChatHeader.test.tsx:669`; ticket 114) |

### Menus (`.pop`)

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| MN1 | `.pop` radius 10px, padding 6px, min-width 238px, max-width 360px, max-height 72vh, 13px, border 1px (`:361-363`) | P1 `.pop`, P2 #5, P3 M1, P4 #24: four Phases, one rule | lift (one token) | `MP.menu.panel` = `min-w-59.5 max-w-90 max-h-[72vh] rounded-[10px] p-1.5 text-[13px] border` |
| MN2 | `.pop .prow` gap 9px, padding 8px 10px, radius 7px, line-height 1.3 (`:364`) | The same rows; the phone keeps `py-3` (P3 F14) | lift | `MP.menu.row` = `gap-2.25 px-2.5 py-3 md:py-2 rounded-[7px] leading-[1.3]` |
| MN3 | `.pop .phead` 10.5px/700, letter-spacing .5px, padding 8px 10px 4px, uppercase (`:370`) | P1 `.pop`, P3 M1, P4 #24 | lift | `MP.menu.head` = `px-2.5 pt-2 pb-1 text-[10.5px] font-bold tracking-[.5px]` |
| MN4 | `.pop .pdiv` 1px, margin 5px 2px (`:371`) | P3 M1 | lift | `MP.menu.divider` = `h-px mx-0.5 my-1.25` |
| MN5 | `.pop .pav` 22×22, radius 5px, 800 9px (`:373-374`) | P1 `.pop` | lift | `MP.menu.avatar` = `size-5.5 rounded-[5px] text-[9px] font-extrabold` |
| MN6 | `.pop .pmeta` 11px (`:376`) | P1 `.pop` | lift | `MP.menu.meta` = `text-[11px]` |

### Sheets

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| SH1 | `.sheet` width min(900px, 92vw), max-height 84vh, radius 14px, border 1px (`:383`) | P3 M4 (Gallery); P4 row 25 (Vault picker, through `Composer`) | lift | `MP.sheet.panel` = `md:w-[min(900px,92vw)] md:max-h-[84vh] md:rounded-[14px] md:border` (below md the sheet is full-screen, P3 F14, so the Clone's values sit under `md:`; ticket 114) |
| SH2 | `.sheet-h` gap 10px, padding 13px 16px, 14px/700, border-bottom 1px (`:385`) | P3 M4; P4 row 25 | lift | `MP.sheet.head` = `gap-2.5 px-4 py-3.25 text-[14px] font-bold border-b`; the Vault picker's from md up (P4 row 25; ticket 117, so below md it keeps its full-screen pane): `MP.sheet.pickerHead` = `md:py-3.25` on its head row (its `px-4` and `border-b` are its own at every width) and `MP.sheet.pickerTitle` = `md:text-[14px] md:font-bold` on its title |
| SH3 | `.sheet-h .x` 17px, line-height 1, padding 2px 6px, radius 6px (`:386`) | P3 M4 | lift | `MP.sheet.close` = `px-1.5 py-0.5 rounded-md text-[17px] leading-none` |
| SH4 | `.sheet-b` padding 14px 16px, min-height 90px, 13px (`:388`) | P3 M4 | lift | `MP.sheet.body` = `py-3.5 px-4 min-h-22.5 text-[13px]` |
| SH5 | `.mgrid` `repeat(auto-fill,minmax(118px,1fr))`, gap 10px (`:390`) | P3 M4; P4 row 26 | lift | `MP.sheet.grid` = `grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2.5`; the Vault picker's from md up (P4 row 26; ticket 117, below md it keeps its 3 and 4 columns): `MP.sheet.pickerGrid` = `md:grid-cols-[repeat(auto-fill,minmax(118px,1fr))] md:gap-2.5` |
| SH6 | `.mgrid .mt` radius 9px, border 1px (`:391`) | P3 M4; P4 row 26 | lift | `MP.sheet.tile` = `rounded-[9px] border`; the Vault picker's from md up (P4 row 26; ticket 117, its tiles draw their own 2px status ring): `MP.sheet.pickerTile` = `md:rounded-[9px]` |
| SH7 | `.mgrid .mt .tag` left 6px, bottom 6px, padding 2px 6px, radius 6px, 10.5px/700 (`:393`) | P3 M4 | lift | `MP.sheet.tileTag` = `left-1.5 bottom-1.5 rounded-md py-0.5 px-1.5 text-[10.5px] font-bold` |

### Message list

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| ML1 | `.thread-body` padding 22px 26px, column, gap 14px (`:220`) | P3 L1 from md up; the phone keeps `px-2 py-3` and an 8px gap (`MessageList.tsx:405`, P3 F25) | lift | `MP.messageList.body` = `px-2 py-3 gap-2 md:px-6.5 md:py-5.5 md:gap-3.5` |
| ML2 | `.bubble` max-width 60% (`:243`) | P3 L2; the phone keeps 88% (`MessageList.tsx:672`) | lift | `MP.messageList.bubbleColumn` = `max-w-[88%] md:max-w-[60%]` |
| ML3 | `.bubble` padding 11px 15px, radius 16px, 14.5px/1.45 (`:243`) | P3 L2; the phone keeps `px-3 py-2 text-sm` (`MessageList.tsx:763`) | lift | `MP.messageList.bubble` = `rounded-2xl px-3 py-2 text-sm md:px-3.75 md:py-2.75 md:text-[14.5px] md:leading-[1.45]` |
| ML4 | `.bubble.in` bottom-left radius 5px (`:245`) | P3 L2; the phone keeps `rounded-bl-md` (`MessageList.tsx:766`) | lift | `MP.messageList.bubbleTailIn` = `rounded-bl-md md:rounded-bl-[5px]` |
| ML5 | `.bubble.out` bottom-right radius 5px (`:246`) | P3 L2; the phone keeps `rounded-br-md` (`MessageList.tsx:765`) | lift | `MP.messageList.bubbleTailOut` = `rounded-br-md md:rounded-br-[5px]` |
| ML6 | `.bubble .btime` 11px, margin-top 5px (`:244`) | P3 L3 | lift | `MP.messageList.time` = `mt-1.25 text-[11px]` |
| ML7 | `.seen-tick` 10px, margin-left 5px (`:261`) | P3 L4 | lift | `MP.messageList.seen` = `ml-1.25 text-[10px]` |
| ML8 | `.sent-by` 10px/700, margin-left 7px (`:262`) | P3 L5 | lift | `MP.messageList.sentBy` = `ml-1.75 text-[10px] font-bold` |
| ML9 | `.msg-meta` 12.5px (`:241`) | P3 L8 | lift | `MP.messageList.meta` = `text-[12.5px]` |
| ML10 | `.ppv-mini` radius 14px, padding 14px 16px, max-width 320px, column gap 8px, border 1px (`:248`; in the screenshot build at `orig:203`) | None claimed: a PPV message is a normal bubble plus a 10px chip (`MessageList.tsx:743-757`) | new | `MP.messageList.ppv` = `max-w-80 gap-2 px-4 py-3.5 rounded-[14px] border` |
| ML11 | `.ppv-mini .pm-title` 600 (`:249`) | None claimed | new | `MP.messageList.ppvTitle` = `font-semibold` |
| ML12 | `.ppv-mini .paid-tag` 12px/600 (`:250`) | P3 L6 | lift | `MP.messageList.paidTag` = `text-[12px] font-semibold` |
| ML13 | `.unlock-btn` height 52px, radius 9px, 15px/700, letter-spacing .4px (`orig:187-188`, `:232-233`) | P3 L7 | lift | `MP.messageList.unlock` = `h-13 rounded-[9px] text-[15px] font-bold tracking-[.4px]` |
| ML14 | `.msg-acts` top −11px, gap 3px, no box (`:253`) | P3 Out of Scope gives it here. Ours: `-top-7 gap-1 px-1 py-0.5`, bordered box (`MessageList.tsx:678-679`) | new | `MP.messageList.actions` = `-top-7 gap-1 px-1 py-0.5 border rounded-md md:-top-2.75 md:gap-0.75 md:p-0 md:border-0` (D7) |
| ML15 | `.bubble.out .msg-acts` right 6px (`:254`) | `MessageList.tsx:682` `right-1` | new | `MP.messageList.actionsOut` = `right-1 md:right-1.5` |
| ML16 | `.bubble.in .msg-acts` left 6px (`:255`) | `MessageList.tsx:682` `left-1` | new | `MP.messageList.actionsIn` = `left-1 md:left-1.5` |
| ML17 | `.msg-acts .ma` 24×24, round, 13px, border 1px, glyph only (`:257-258`, `m.js:877-880`) | `MessageList.tsx:689`: `text-[11px] px-2 py-2 md:text-[10px] md:px-1.5 md:py-0.5`, glyph plus word | new | `MP.messageList.action` = `px-2 py-2 text-[11px] rounded md:p-0 md:size-6 md:rounded-full md:text-[13px] md:border` (D7; phone `rounded` is today's 4px tap-target radius, ticket 115) |
| ML18 | `.load-older` margin 2px 0 8px, padding 7px 16px, radius 99px, 12.5px/600, border 1px (`:532-533`) | `MessageList.tsx:434` `text-[11px] px-3 py-1 rounded-full` | new | `MP.messageList.loadOlder` = `mt-0.5 mb-2 px-4 py-1.75 rounded-full text-[12.5px] font-semibold border` (D7) |
| ML19 | `.pinbar` gap 8px, padding 7px 18px, 12px, border-bottom 1px (`:538-539`) | `PinnedPanel.tsx:57-58` `px-4 py-1.5 gap-2 text-[11px]` | new | `MP.messageList.pinBar` = `gap-2 px-4.5 py-1.75 text-[12px] border-b` (D7) |
| ML20 | `.pinbar svg` 14px (`:541`) | None | new | `MP.messageList.pinBarIcon` = `size-3.5` |
| ML21 | `.pinbar .pincount` 700 (`:543`) | None | new | `MP.messageList.pinCount` = `font-bold` |

### Composer and PPV row

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| CP1 | `.composer` padding 12px 16px 14px, border-top 1px (`:269`) | P4 #1 `px-4 pt-3 pb-[max(14px,env(safe-area-inset-bottom))]` | lift + notation | `MP.composer.root` = `px-4 pt-3 pb-[max(14px,env(safe-area-inset-bottom))] border-t` |
| CP2 | `.comp-r1` gap 10px, margin-bottom 6px (`:270`) | P4 #2 | lift | `MP.composer.buttonRow` = `gap-2.5 mb-1.5` |
| CP3 | `.icon-btn` 26×26, radius 7px (`:77`) | P4 #3 | lift | `MP.composer.buttonRowButton` = `size-6.5 rounded-[7px]` |
| CP4 | `.comp-r1 .icon-btn svg` 20px (`:272`) | P4 #3 | lift | `MP.composer.buttonRowIcon` = `size-5` |
| CP5 | `.pill` gap 6px, border 1px, radius 16px, padding 6px 12px, 13px/600 (`:273-274`) | P4 #4 `gap-1.5 px-3 py-1.5` | lift + notation | `MP.composer.pill` = `gap-1.5 px-3 py-1.5 rounded-2xl text-[13px] font-semibold border` |
| CP6 | `.pill svg` 15px (`:275`) | P4 #4 | lift | `MP.composer.pillIcon` = `size-3.75` |
| CP7 | `.comp-input input` 15px, padding 6px 2px (`:277`) | P4 #5 `px-0.5 py-1.5 text-base md:text-[15px]`; `text-base` below md is the iOS no-zoom rule (`Composer.tsx:961-965`) | lift | `MP.composer.input` = `px-0.5 py-1.5 text-base md:text-[15px] md:leading-[normal]` (ticket 120: the Clone's input sets no line height, so it takes the browser's `normal`; `md:text-[15px]` alone kept `text-base`'s 1.5, a 35px row against the Clone's 30px) |
| CP8 | `.comp-r2` gap 6px (`:280`) | P4 #7 `gap-1.5` | lift + notation | `MP.composer.toolbar` = `gap-1.5` |
| CP9 | `.comp-r2 .icon-btn` 34×34 (`:281`), radius 7px (`:77`) | P4 #7 | lift | `MP.composer.toolbarButton` = `size-8.5 rounded-[7px]` |
| CP10 | `.comp-r2 .icon-btn svg` 20px (`:282`) | P4 #7 | lift | `MP.composer.toolbarIcon` = `size-5` |
| CP11 | `.send-btn` padding 10px 26px, radius 9px, 14px/700 (`:283`) | P4 #9 `text-sm` | lift + notation | `MP.composer.send` = `px-6.5 py-2.5 rounded-[9px] text-sm font-bold` |
| CP12 | `#cbAa` 800 15px (markup `:761`) | P4 #20 | lift | `MP.composer.aa` = `text-[15px] font-extrabold` |
| CP13 | `.reply-strip` gap 9px, padding 8px 12px, margin-bottom 8px, border-left 3px, radius 8px, 13px (`:525-526`) | P3 L10 | lift | `MP.composer.replyStrip` = `gap-2.25 px-3 py-2 mb-2 border-l-3 rounded-lg text-[13px]` (ticket 117: `flex items-center` moved to JSX) |
| CP14 | `.reply-strip svg` 15px (`:527`) | P3 L10 | lift | `MP.composer.replyStripIcon` = `size-3.75` (ticket 117: `flex-none` moved to JSX) |
| CP15 | `.reply-strip .rs-x` 22×22, radius 6px, 14px (`:529`) | P3 L10 | lift | `MP.composer.replyStripClose` = `size-5.5 rounded-md text-[14px]` (ticket 117: the Clone's string; `flex-none grid place-items-center` moved to JSX) |
| PV1 | `.comp-x` gap 8px, padding 0 0 8px, 12.5px (`:514`) | P4 #10 `gap-2 pb-2 text-[12.5px]` | lift + notation | `MP.ppvRow.row` = `gap-2 pb-2 text-[12.5px]` |
| PV2 | "PPV" label, 700 (markup `:739-753`) | P4 #11 | lift | `MP.ppvRow.label` = `font-bold` |
| PV3 | "$" with its input, and the checkbox with "lock text", each gap 5px (markup `:739-753`) | P4 #11 | lift | `MP.ppvRow.group` = `gap-1.25` |
| PV4 | `.comp-x input` border 1px, radius 7px, padding 6px 8px, 13px (`:516-517`) | P4 #10 `px-2 py-1.5`; `text-base` below md is the iOS no-zoom rule (`PpvRow.tsx` `FIELD`, ticket 30) | lift + notation | `MP.ppvRow.input` = `px-2 py-1.5 rounded-[7px] text-base md:text-[13px] border` (ticket 117: the phone `text-base` kept, as CP7) |
| PV5 | `.comp-x input[type=number]` width 92px (`:518`) | P4 #10 | lift | `MP.ppvRow.price` = `w-23` |
| PV6 | `.btn-sm` radius 7px, padding 7px 12px, 12.5px/600 (`:499`) | P4 #12 `px-3 py-[7px]` | lift + notation | `MP.ppvRow.clear` = `px-3 py-1.75 rounded-[7px] text-[12.5px] font-semibold` |
| PV7 | `.att` gap 6px (`:519`) | P4 #13 | no element | none: the attachment tiles sit straight in the PPV row (`PpvRow` children) at its PV1 gap, with no `.att` box, so tiles are 8px apart where the Clone has 6px (a VISUAL GAP, ticket 119) |
| PV8 | `.att .a` 42×42, radius 7px, border 1px (`:520`) | P4 #13 | lift | `MP.ppvRow.attachment` = `size-10.5 rounded-[7px] border` |
| PV9 | `.att .a b` 10px, padding 0 4px, bottom-left radius 5px (`:522`) | P4 #13 | lift | `MP.ppvRow.attachmentRemove` = `px-1 text-[10px] rounded-bl-[5px]` |

### Fan insights

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| FI1 | `.right-head` padding 16px 16px 10px, 16px/700 (`:293`) | P5 G2 | lift | `MP.insights.head` = `px-4 pt-4 pb-2.5 text-[16px] font-bold` |
| FI2 | `.right-body` padding 0 12px 12px, gap 12px (`:294`) | P5 G3 | lift | `MP.insights.body` = `px-3 pb-3 gap-3` |
| FI3 | `.card` border 1px, radius 12px, padding 14px (`:295`) | P5 G4 | lift | `MP.insights.block` = `p-3.5 rounded-xl border` |
| FI4 | `.card-head` gap 8px, margin-bottom 12px (`:296`) | P5 G5 | lift | `MP.insights.blockHead` = `gap-2 mb-3` |
| FI5 | `.drag svg` 14px (`:298`) | P5 G5 | lift | `MP.insights.dragIcon` = `size-3.5` |
| FI6 | `.card-head .ct` 14px/600 (`:299`) | P5 G5 | lift | `MP.insights.blockTitle` = `text-[14px] font-semibold` |
| FI7 | `.card-head .chev svg` 15px (`:301`) | P5 G5 | lift | `MP.insights.chevron` = `size-3.75` |
| FI8 | `.mrow` padding 6px 0 (`:310`) | P5 G6 | lift | `MP.insights.metric` = `py-1.5` |
| FI9 | `.mrow .k` 13.5px (`:311`) | P5 G6 | lift | `MP.insights.metricKey` = `text-[13.5px]` |
| FI10 | `.mrow .v .vt` 13.5px/600 (`:313`) | P5 G6 | lift | `MP.insights.metricValue` = `text-[13.5px] font-semibold` |
| FI11 | `.mrow .v .va` 12px (`:314`) | P5 G6 | lift | `MP.insights.metricAvg` = `text-[12px]` |
| FI12 | `.mrow.plain .v` 13.5px (`:316`) | P5 G6 | lift | `MP.insights.metricPlain` = `text-[13.5px]` |
| FI13 | `.spend-top` gap 24px, margin-bottom 6px (`:304`) | P5 G7 | lift; page-parity 07 FI1 splits the columns evenly with a rule (2026-10-18 capture) | `MP.insights.spendTop` = `mb-1.5`, `MP.insights.spendSplit` = `border-l pl-2.25` |
| FI14 | `.spend-col .lbl` 12px, margin-bottom 5px (`:305`) | P5 G7 | lift | `MP.insights.spendLabel` = `mb-1.25 text-[12px]` |
| FI15 | `.spend-col .big` 22px/700 (`:306`) | P5 G7 | lift | `MP.insights.spendBig` = `text-[22px] font-bold` |
| FI16 | `.spend-col .sub` 15px (`:307`) | P5 G7 | lift | `MP.insights.spendSub` = `text-[15px]` |
| FI17 | `.hr` 1px, margin 10px 0 (`:309`) | P5 G9 | lift | `MP.insights.rule` = `h-px my-2.5` |
| FI18 | `.bars` height 62px, gap 3px, margin 6px 0 4px (`:493`) | P5 G11 draws the Clone's bars, 62px tall with a 3px gap (`phase-05-fan-insights-panel.md:21`, `:36`). The margins are this table's | lift | `MP.insights.chart` = `h-15.5 gap-0.75 mt-1.5 mb-1` |
| FI19 | `.bars i` radius 2px 2px 0 0, min-height 2px (`:494`) | P5 G11: radius 2px 2px 0 0. The min-height is this table's | lift | `MP.insights.bar` = `rounded-t-xs min-h-0.5` |
| FI20 | `.axis` 10px (`:496`) | P5 G11 | lift | `MP.insights.axis` = `text-[10px]` |
| FI21 | `.badge-val` 11.5px/600, padding 3px 9px, radius 7px (`:315`) | P5 G12 | lift | `MP.insights.badge` = `px-2.25 py-0.75 rounded-[7px] text-[11.5px] font-semibold` |
| FI22 | `.info-i` 14×14 (`:302`) | P5 G15 | lift | `MP.insights.info` = `size-3.5` |
| FI23 | `.nick-edit` gap 8px (`:320`) | P5 G15 | lift | `MP.insights.nickEdit` = `gap-2` |
| FI24 | `.nick-edit svg` 13px (`:321`) | P5 G15 | lift | `MP.insights.pencil` = `size-3.25` |
| FI25 | `.loc-box` gap 8px, border 1px, radius 8px, padding 8px 10px, 13px; margin-top 10px (`:317`, markup `:833`) | P5 G14, G17 | lift | `MP.insights.location` = `mt-2.5 gap-2 px-2.5 py-2 rounded-lg text-[13px] border` |
| FI26 | `.loc-box svg` 15px (`:318`) | P5 G17 | lift | `MP.insights.locationIcon` = `size-3.75` |
| FI27 | `.right-tabs` border-top 1px (`:324`) | P5 G18 | lift; page-parity 07: Infloww's tile bar, no rule (2026-10-18 capture) | `MP.insights.tabs` = `px-2 pt-2 pb-3` |
| FI28 | `.rtab` gap 4px, padding 11px 0, 12px/600 (`:325`) | P5 G18 | lift; page-parity 07: a 52px tile, radius 8px (2026-10-18 capture) | `MP.insights.tab` = `gap-1 py-1.5 rounded-lg text-[12px] font-semibold` |
| FI29 | `.rtab svg` 20px (`:326`) | P5 G18 | lift | `MP.insights.tabIcon` = `size-5` |
| FI30 | `.stab` 12px (`:488`) | P5 G19 builds the Clone's Date / Gross / Net / Sent by table at 12px (`phase-05-fan-insights-panel.md:29`, `:134`). The purchased-media rows under it keep their literals in `MP.ours.FanDrawer` | lift | `MP.insights.salesTable` = `text-[12px]` |
| FI31 | `.stab th` padding 4px 5px, 10.5px/600, letter-spacing .3px, uppercase, border-bottom 1px (`:489-490`) | P5 G19: the table's header cells | lift | `MP.insights.salesHead` = `px-1.25 py-1 text-[10.5px] font-semibold tracking-[.3px] uppercase border-b` |
| FI32 | `.stab td` padding 6px 5px, border-bottom 1px (`:491`) | P5 G19: the table's body cells | lift | `MP.insights.salesCell` = `px-1.25 py-1.5 border-b` |
| FI33 | `.note-ta` min-height 132px, radius 9px, padding 10px, 13px/1.5, border 1px (`:497-498`) | P5 G20; `text-base` below md is the iOS no-zoom rule (`FanDrawer.tsx`, the Fan notes field) | lift | `MP.insights.note` = `min-h-33 p-2.5 rounded-[9px] text-base md:text-[13px] leading-normal border` (ticket 118: the phone `text-base` kept, as CP7 and PV4) |

### Thread empty state

| # | Clone selector · CSS (line) | Ours (row) | Gap | Change |
|---|---|---|---|---|
| ES1 | `.empty` column, gap 22px (`:287`, markup `:719-722`) | P1 `.empty`. Phase 3 dropped L9 to Phase 1 (P3 F22) | lift | `MP.emptyState.root` = `gap-5.5` |
| ES2 | `.empty svg` 130×130 (`:288`) | P1 `.empty` | lift | `MP.emptyState.icon` = `size-25 stroke-1` |
| ES3 | `.empty p` 26px (`:289`) | P1 `.empty` | lift | `MP.emptyState.text` = `text-[20px]` |

### How the table reconciles Phases 1–5

1. **`.pop` has one source.** Four Phases claim `.pop`: P1 `.pop`, P2 #5, P3 M1 and P4 #24. They all get the one `MP.menu` region (MN1–MN6). P3 F14's phone `py-3` touch row applies to every menu. That is harmless for the Window header's pickers, because the Window header is hidden below lg (Phase 1).
2. **`.icon-btn` has five overrides.** The base rule is 26px with radius 7 (`:77`). Each Region overrides it differently:
   - Window header: SVG 18 (`:79`), WH14–15.
   - Fan List: SVG 20 (`:119`), plus Phase 2's phone tap target, FL3–4.
   - Chat header: 30px with SVG 19 (`:211-212`), CH10–11.
   - Composer button row: SVG 20 (`:272`), CP3–4.
   - Composer bottom toolbar: 34px with SVG 20 (`:281-282`), CP9–10.

   So the module has one token per Region, not a shared one.
3. **Two `.cname` rules.** The Creator tab name is 13/700 (`.ctab .cname`, `:62`). The Fan row name is 14/700 with a 170px cap (`.cname`, `:175`). They are separate tokens (CT5, FL29).
4. **Three badges.** `.mini-badge` is 16px: the Creator tab badge, and the Fan tab badge per P1's ASSUMPTION. `.cbadge` is 17px (P2 #14). `.notif-badge` is 22px (P1). They are three tokens. Their colours are reconciled in D6.
5. **Phase 4 notation.** Phase 4 wrote some values as scale classes. CP1, CP5, CP7, CP8, CP11, PV1, PV4 and PV6 keep them as scale classes with the same pixels (D1, ticket 110), and CP11 keeps Phase 4's `text-sm`.
6. **Phone values.** The phone values that Phases 2–5 keep live in the same token, under no prefix, with the Clone value under `md:` or `lg:`:
   - Phase 2: chips and the header icon buttons (FL3, FL18).
   - Phase 3: the header, the thread body, bubbles and menu rows (CH1, ML1–ML5, MN2).
   - Phase 4: the input's `text-base` (CP7), and the PPV row's fields' (PV4, ticket 117). From md CP7 adds `md:leading-[normal]`, because `text-base` also sets a 1.5 line height that `md:text-[15px]` does not undo (ticket 120).
     ASSUMPTION: `normal` matches the Clone's unstated input line height in kind, not in pixels. The Clone renders its input in the browser's default control font, and ours renders in the app's font, whose `normal` line height may differ by a pixel or two (ticket 120, rung 5). Overturned if the measured row differs from the Clone's 30px by more than that, in which case CP7 takes a numeric leading.
   - Phase 5: the Fan notes field's `text-base` (FI33, ticket 118).
7. **Pane widths.** P0 #3, P1 `.list` and P2 #1 deferred the Fan List width here (PN2). P5 G1 already set Fan insights (PN4).
8. **The reply strip.** P3 L10 owns its behaviour. Its token sits in `composer`, because the glossary places the reply strip inside the Composer (CONTEXT.md, "Composer"; P3 F26).
9. **The Thread empty state.** Phase 1 owns it alone, because Phase 3 dropped L9 (P3 F22), so `MP.emptyState` has one reader.
10. **§1.4 is a cross-check only.** `docs/infloww-screens.md:97-104` says "Radii: cards 12, buttons 8-10, pills full".
    - Cards agree: 12 (`.card`, `:295`).
    - Buttons partly disagree. The Clone uses 7 (`.icon-btn`, `.lbl`, `.open-new`, `.btn-sm`) and 9 (`.send-btn`, `.big-btns`), and the Clone wins (plan: "§1.4 is reference only").
    - Pills agree. At 13px × 1.4 plus 12–14px of padding they are about 32px tall, so a 16px radius is fully round.

## Problem Statement

An Employee coming from Infloww opens Messages Pro and finds the panes the wrong size. The Fan List is 320px against Infloww's 390px, and the pinned Fan insights column was 360px against 280px. Rows, bubbles, menus and the hover actions are spaced and sized differently.

Phases 1–5 fix each Region, but their numbers end up as literals in JSX, as one interim constant in the Fan List module, or partly in a token module that two Phases may create. Today the modules Messages Pro renders hold 234 numeric arbitrary values, counted with the guard's R1 pattern (D2). For example, `FanDrawer` has 53, `MessageList` 39, `ChatList` 27 and `Composer` 26. So a maintainer who wants to change one number has to hunt for it, and nothing stops a new magic number from landing.

At 1280×800 in the app, the 252px docked sidebar (`Sidebar.tsx:106`) leaves the Thread 1280 − 252 − 390 − 280 = 358px wide. That is too narrow for the Chat header or the Composer. Even Infloww's own Clone overflows its Chat header at 1280×800 and hides it with `overflow:hidden` (`m.html:39`, `:47`).

Nothing checks any of this. The Visual loop harness renders only 1440×900 and 390×844.

## Solution

1. **One token module.** `app/lib/messagesPro.ts` holds every Messages Pro Geometry number. Each value is a full Tailwind class string, one per Clone selector, grouped by Region and element. Every Messages Pro component reads its Geometry from the module, and JSX keeps only layout keywords and colour tokens. The one exception is the 58 tokens Phases 1 and 3 and tickets 106 and 108 wrote before ticket 110: they still carry their layout keywords (`flex`, `items-center`, `truncate`), as the Change column records, until their Region's lift ticket (112 to 118) moves the keywords to JSX and amends the row and the snapshot together (Implementation Decisions, Interfaces).
2. **The lift.** This Phase moves the numbers that Phases 1–5 applied into the module. It applies the values no Phase claimed: the Fan List width, the hover actions, the pinned bar, "Load older", the PPV message box and the pinned-messages overlay. It deletes Phase 2's interim constant.
3. **A test that guards both.** It pins the module to this spec's table, and it fails when any Messages Pro module carries a numeric arbitrary value, a numeric geometry style or a numeric size attribute, overrides a token beside it, or leaves a token unread. The guard's scope is computed from the Messages Pro routes, after the house precedent.
4. **Three panes at 1280.** On Messages Pro routes the app sidebar opens as the off-canvas drawer at every width. The Chat header drops the visible words "Gallery", "Find" and "Open in new tab" when the Thread is too narrow, and keeps them as accessible names.
5. **An overflow sweep.** An opt-in harness mode renders 1440, 1280, 768 and 390 in the app and in the Pop-out window. It fails on horizontal overflow, a clipped control, or three panes missing at 1280 and above, and Acceptance runs it once more with the Legacy flag on.

## User Stories

Token module
1. As a maintainer, I want every Messages Pro Geometry number in one module, `app/lib/messagesPro.ts`, so that changing a width, padding, radius, font size or icon size is one edit.
2. As a maintainer, I want the module grouped by Region and element under glossary names (`panes`, `windowHeader`, `creatorTabs`, `fanTabs`, `fanList`, `chatHeader`, `menu`, `sheet`, `messageList`, `composer`, `ppvRow`, `insights`, `emptyState`), so that I can find a number by what I see on screen.
3. As a maintainer, I want each token to be a complete Tailwind class string with no interpolation, so that Tailwind's static scan generates every class and no component needs a runtime style.
4. As a maintainer, I want each token to carry its phone value and its desktop value together, so that the phone rules Phases 2–4 kept survive the lift.
5. As a reviewer, I want every number in the module to match a row of this spec's Gap table, with its Clone selector and line, so that I can trace any value back to the Clone.
6. As a reviewer, I want the measured numbers taken from `messages.html` and, for the three fx rules Messages Pro uses, `_shared/components.html`, so that the plan's sources are the only sources.
7. As a maintainer, I want the module to hold no colour, so that colours come only from the `globals.css` tokens (ADR-0001).
8. As a maintainer, I want literals with no Clone source (extras, charts, overlays) lifted unchanged into an `ours` section, so that the no-magic-numbers rule holds without inventing measurements.
9. As an implementer of a Phase that lands after this one, I want the module's shape and key names fixed in this spec, so that I write my numbers into the right keys.
10. As a maintainer, I want Phase 2's interim geometry constant deleted once its values are in the module, so that the Fan List has one source.
11. As the Phase 7 implementer, I want the Extras overflow trigger to read the "+" sizes from the module (`MP.windowHeader.iconButton`, `MP.chatHeader.iconButton`, `MP.composer.buttonRowButton`) and the overflow menu to read `MP.menu`, so that the trigger matches its Region.

Measured Geometry
12. As an Employee, I want the Fan List 390px wide, Fan insights 280px wide and the Thread to take the rest from 1024px up, so that the panes sit where they do in Infloww.
13. As an Employee, I want the Window header 46px tall and the Fan tabs row 34px tall, so that the top rows match Infloww's.
14. As an Employee, I want Fan rows, Chat header, bubbles, Composer rows and Insights blocks at Infloww's heights and paddings, so that the density matches what I am used to.
15. As an Employee, I want Infloww's radii, font sizes and icon sizes in every Region, so that controls look the same size as in Infloww.
16. As an Employee, I want Messages Pro body text at 14px with line-height 1.4, so that unsized text matches Infloww's base.
17. As an Employee, I want the hover actions on a message to be Infloww's small round buttons, 24px with 3px gaps sitting on the bubble's top edge, so that they cover less of the conversation.
18. As a screen reader user, I want each hover action to keep a spoken name (Reply, Like or Unlike, Pin or Unpin, Unsend, Reward) when it shows only a glyph, so that I can still find it.
19. As an Employee, I want the pinned bar and "Load older" at Infloww's size, so that they read as Infloww's controls.
20. As an Employee, I want a PPV message drawn as Infloww's PPV box (320px wide, 14px radius), so that paid messages stand out the same way.
21. As an Employee, I want the pinned-messages overlay to cover exactly the Fan List, which is now 390px, so that it does not leave a strip of the list showing.
22. As an Employee on a phone, I want chips, header buttons, menu rows, bubbles and the Composer input to keep today's phone sizes, so that the Clone's small desktop sizes never shrink my tap targets or zoom the iOS keyboard.

Colours
23. As an Employee, I want Messages Pro in the same colours as the rest of Inflowwww, so that it does not look like a different product.
24. As an Employee, I want every unread count and unread dot in the same colour, `info`, so that "unread" means one thing everywhere in Messages Pro.
25. As a maintainer, I want §1.4's palette and radii treated as reference only, so that where §1.4 and the Clone disagree (button radii 8–10 against 7 and 9) the Clone wins.

No horizontal scroll
26. As an Employee at 1280×800, I want three panes and no sideways scroll, both in the app and in the Pop-out window, so that I can work on a common laptop screen.
27. As an Employee at 1440×900, I want three panes and no sideways scroll, both in the app and in the Pop-out window.
28. As an Employee in Messages Pro in the app at 1024px and up, I want "Toggle sidebar" to open the app sidebar as a drawer over the panes, so that opening it never squeezes the Thread.
29. As an Employee on any other page at 1024px and up, I want the sidebar to stay docked and to collapse as it does today.
30. As an Employee with a narrow Thread, I want the Chat header to show icons only for Gallery, Find and Open in new tab, and their words to come back when the Thread is wide enough, so that the header never pushes controls off screen.
31. As a screen reader user, I want "Gallery", "Find" and "Open in new tab" to keep those names when their words are hidden.
32. As an Employee, I want a long Fan name or status to end in an ellipsis rather than push the Chat header's buttons out of view.
33. As an Employee below 1024px, I want one pane at a time and the drawer sidebar, as `docs/routes.md` says.

Checks
34. As a maintainer, I want a snapshot test that fails when the token module drifts from this spec's measured table.
35. As a maintainer, I want a test that fails when a Messages Pro module carries a magic number, with its scope computed from the Messages Pro routes, so that a new component is covered on the day it is imported.
36. As a maintainer of a shared component that other screens use, I want to take Messages Pro Geometry as a class-name prop, so that the guard does not drag other screens' numbers into the Messages Pro module.
37. As an implementer, I want one command that renders 1440×900, 1280×800, 768×1024 and 390×844, in the app and in the Pop-out window, and exits non-zero on horizontal overflow or missing panes.
38. As an implementer, I want the harness's default run and its fixed shot list unchanged, so that every other Phase's acceptance still means the same thing.
39. As an implementer, I want PNGs at 1280 and 768 to look at beside the Clone, so that I can run the Visual loop on the new widths.
40. As a maintainer, I want `docs/routes.md` and `docs/ui-shots.md` to state the Messages Pro sidebar rule and the sweep, so that the next reader knows both exist.

## Implementation Decisions

- **Owns.**
  - New: `app/lib/messagesPro.ts` and `app/lib/messagesPro.test.ts`.
  - Modified, Geometry classes only (no behaviour, label or order change except D7's hover-action names). These are the modules the guard's scope reaches (D2):
    - Phase 0's `MessagesPro` tree and the Messages Pro page.
    - Phase 1: `WindowHeader`, `CreatorTabs`, `FanTabs`, `OpenInNewTabButton`, `FanListButtons`, `OpenInNewWindowMenu`.
    - Phase 2: `FanList`, `FanListHeader`, `FanListFilters`, `FanRow`, `SplitInbox`, with the interim constant deleted.
    - Phase 3: `ChatHeader`, `ChatHeaderExtras`, `FanAvatarMenu`, `ChatGallery`, `MessageStatsLink`, `ReplyStrip`, `ChatActionsMenu`, `MessageList`, `ChatSurface`.
    - Phase 4: `Composer`, `ComposerToolbar`, `PpvRow`, `TimedMessagePopover`, and `VaultPicker`'s Messages Pro mode only: its row 25–26 literals become class-name props that `Composer` fills from `MP.sheet` (Shared modules).
    - Phase 5: `FanDrawer`.
    - Also: `PinnedPanel`, `ChatSearch`, `ScheduledForChat`, `ModelInfoButton`, `AiStatusStrip`, `PersonaClaims`, `MediaTile`, `ImageDescCaption`.
  - Modified, shell: `app/components/shell/AppShell.tsx` and `app/lib/nav.ts` (one predicate). In `app/components/shell/AppShell.test.tsx`, three cases are added and none removed.
  - Modified, one case: `app/components/chat/MessageList.test.tsx` (hover-action names).
  - Modified, harness: `scripts/ui-shots.sh`, which gains the sweep mode. Phase 0's ASSUMPTION already makes this file the plan-named exception to "nothing outside `app/` and `docs/`".
  - Modified, docs: `docs/ui-shots.md` (one paragraph) and `docs/routes.md` (the Sidebar line).
  - New outputs: `docs/screenshots/messages-pro-sweep.json`, `messages-pro-1280.png` and `messages-pro-768.png`.
  - Untouched: `app/app/globals.css` (including `.h-chat` and `--shell-top`), `service/`, and the shared pickers' other screens (`VaultPicker`, `EmojiBar`, `TemplatePicker`, `TagCreatorsPicker`, `GifPicker`, `LinesPicker`), apart from an optional class-name prop.

- **Interfaces.**
  - The token module:
    ```ts
    // app/lib/messagesPro.ts — Messages Pro Geometry (ADR-0001). Class strings only, no colours.
    export const MP = {
      panes: { root: "text-sm leading-[1.4]", fanList: "lg:w-100 lg:min-w-100 border-r", /* … PN rows */ },
      windowHeader: { /* WH rows */ }, creatorTabs: { /* CT */ }, fanTabs: { /* FT */ },
      fanList: { /* FL */ }, chatHeader: { /* CH */ }, menu: { /* MN */ }, sheet: { /* SH */ },
      messageList: { /* ML */ }, composer: { /* CP */ }, ppvRow: { /* PV */ },
      insights: { /* FI */ }, emptyState: { /* ES */ },
      ours: { /* <ComponentName>: { <name>: "<today's literal, unchanged>" } */ },
    } as const;
    export type MessagesProTokens = typeof MP;
    ```
    Every leaf is the exact string in the Gap table's Change column.
  - **How components consume it.** `className={cn(MP.fanList.row, "flex cursor-pointer hover:bg-bg-elev-1")}`. The token holds Geometry. JSX adds layout keywords (`flex`, `items-center`, `truncate`, `min-w-0`) and colour tokens. A leaf is never built by interpolation. Exception: a token an earlier Phase or ticket wrote before ticket 110 keeps its layout keywords until its Region's lift ticket (112 to 118) moves them to JSX, amending the Gap row and the snapshot in the same change; ticket 111's R4 is unaffected, because a layout keyword carries no Geometry number.
    ASSUMPTION: those tokens keep their layout keywords for now, because ticket 110 renamed keys with their values unchanged so nothing rendered differently (rung 4: nothing on screen changes and one lift change undoes it; the ticket's "nothing looks different" box). Overturned if the human wants Geometry-only leaves at once, in which case one change moves the keywords of all 58 tokens into their readers' JSX and amends the rows and the snapshot together.
  - **Shared modules.** A module that is reachable from a non-Messages-Pro route, and whose other screens use their own numbers, takes Messages Pro Geometry through a class-name prop (`className`, or a named prop such as `triggerClassName`) from its Messages-Pro-only caller. It does not import the module. `Composer` is the exception: other modules import it only for `sanitizePriceInput`, and only `ChatSurface.tsx:1105` renders it, so it imports the module directly.
  - **`nav.isPopoutRoute(pathname: string): boolean`.** It is true when the pathname equals the href of a `popout` link or sits under it (`/messages-pro`, `/messages-pro/<acc>/<fan>`). Phase 0's `isPopoutWindow(pathname, searchParams)` may be rewritten as `window=1 && isPopoutRoute(pathname)` with no change in behaviour.
  - **`AppShell`.** Phase 0's Pop-out window branch runs first and is unchanged. Then:
    - `overlay = isPopoutRoute(pathname)` and `docked = desktop && !overlay`.
    - `toggle` collapses the docked sidebar when `docked`, and otherwise opens or closes the drawer.
    - `drawerOpen = !docked && drawerPath === pathname`.
    - The TopBar gets `sidebarExpanded = docked ? !collapsed : drawerOpen` and `sidebarId = docked ? "app-sidebar" : "app-sidebar-drawer"`.
    - The docked Sidebar gets `lg:hidden` when `collapsed || overlay`. It stays in the DOM, so Phase 0's `windowed.test.tsx` case 2 still finds `#app-sidebar`.
    - The drawer's overlay and content drop `lg:hidden` when `overlay`.
  - **Harness.** `UI_SHOTS_SWEEP=1 scripts/ui-shots.sh` runs the sweep. Without the variable, the script behaves exactly as Phase 0 specifies.

- **Schema.** None. No data, storage or migration changes.

- **Contracts.**
  - No relay route is added or changed, and `service/` is untouched.
  - The one new contract is the sweep report `docs/screenshots/messages-pro-sweep.json`:
    ```json
    {"ok": true,
     "runs": [{"name": "inapp-1280", "url": "/messages-pro", "viewport": [1280, 800],
               "file": "docs/screenshots/messages-pro-1280.png",
               "overflowX": false, "wide": [], "panes": "three",
               "consoleErrors": [], "offHostRequests": [], "failures": [], "ok": true}]}
    ```
    - **`runs`.** Eight runs: `inapp-` and `window-` (`/messages-pro?window=1`), each at 1440×900, 1280×800, 768×1024 and 390×844.
    - **`file`.** Set only for `inapp-1280` and `inapp-768`, and null otherwise. The 1440 and 390 PNGs are Phase 0's shots.
    - **`wide`.** Lists `{selector, scrollWidth, clientWidth}` for each failing element.
    - **`panes`.** `"three"`, `"one"` or `"bad"`.
    - **`failures`.** One line per failed check, (b) to (h) in D5.
    - **`ok`.** True only when every run is ok.

- **D1. The module's shape.** `MP.<region>.<element>`, two levels, `as const`. Each leaf is the full Tailwind class string for one Clone selector. It holds every class that carries a measured number: size, spacing, radius, font size, weight, line height, letter spacing and border width. A breakpoint prefix sits wherever a Phase keeps a phone value. Clone values are written as Tailwind scale classes (amended by ticket 106; the earlier `[Npx]` rule is withdrawn): the module writes Tailwind scale classes at the table's pixel values, with an arbitrary value only where the scale lacks the value (e.g. `leading-[1.4]`), and the Change column carries those strings (every row since ticket 110; house precedent in the Phase 1 and 3 tokens, and the plan's 2026-10-14 decision that scale classes are not magic numbers). Phone values keep the notation their Phase used. Tailwind generates the classes because they are complete literals in a scanned file: `app/lib` is already scanned, and `lib/runStats.tsx:357` renders `text-err`.
  ASSUMPTION: tokens are full Tailwind class strings, one per Clone selector, grouped as `MP.<region>.<element>`. This is rung 3: the house keeps Geometry as class-string constants (`Sidebar.tsx:33` `ROW`, `sellerShared.tsx:51-53` `INPUT`/`TH`/`TD`, `MediaTile.tsx:47` `SKELETON_MIN_H` (since ticket 116, `MP.ours.MediaTile.skeleton`), and Phase 2's interim constant). CSS variables were rejected because a variable cannot drive a breakpoint or a container threshold, and because a variable set on the Messages Pro root does not reach portaled popovers (`EmojiBar`, `TemplatePicker`, `TagCreatorsPicker`, `VaultPicker` and the `MessageList` zoom use `createPortal`). Inline style was rejected because it cannot carry the phone values. The one runtime value, `page.tsx:190-192` `--roster-w`, leaves with the roster. Overturned if the human wants numeric tokens (for example to feed SVG or canvas maths), in which case a numeric leaf is added beside its class string.
  ASSUMPTION (overturned by ticket 106's rung-3 ASSUMPTION, which follows the plan's 2026-10-14 decision and the Phase 1 and 3 token precedent; kept for the record): Clone values are written as `[Npx]` arbitrary values even where an equal Tailwind scale class exists (Phase 4's `px-4 pt-3 gap-1.5 text-sm` become `px-[16px] pt-[12px] gap-[6px] text-[14px]`), so that every number in the module reads as the Clone's pixel value (rung 5). Overturned if the human prefers scale classes wherever one matches exactly.

- **D2. The snapshot test and the magic-number guard share one file.** `app/lib/messagesPro.test.ts` has four parts:
  1. **The snapshot.** `MP` without `ours` deep-equals an `EXPECTED` object transcribed from this Gap table's Change column.
  2. **The colour check.** Every leaf, `ours` included, is a non-empty string with no colour-token class and no hex, `rgb`, `hsl` or `oklch` value.
  3. **The guard.** It runs over a computed scope (below) and reports `file:line` for each hit.
  4. **Consumption.** Every measured leaf `MP.<region>.<element>` is referenced as source text in at least one file of the scope, and every `MP.ours.<ComponentName>` group in that component's file. A token that nothing reads fails, so the snapshot cannot pass over an unwired Region.

  The guard has four rules:
  - **R1.** No Tailwind arbitrary value contains a digit (`/-\[[^\]\s]*\d[^\]\s]*\]/`).
  - **R2.** No `style={{…}}` object gives a geometry property a numeric literal, or a string literal with a digit. The geometry properties are width, height, the min and max variants, top, right, bottom, left, inset, margin and padding and their sides, gap, fontSize, lineHeight, borderRadius and flexBasis.
  - **R3.** No `size`, `width` or `height` JSX attribute takes a numeric literal.
  - **R4.** A `cn(…)` call or `className` expression that references `MP.` adds no class carrying a Geometry number, scale or arbitrary. `cn(MP.fanList.row, "px-4")` fails, because `cn` runs `twMerge` and the later class wins (`lib/utils.ts:2-8`), so `px-4` would silently replace the token's `px-[16px]`.

  R2 also catches a geometry property given an identifier that the same file binds to a numeric literal: `PinnedPanel.tsx:37` `CHAT_LIST_WIDTH = 320` reaches `style={{ … width: CHAT_LIST_WIDTH }}` at `:165`. Numeric constants that feed a computation stay beside it, for example `MessageList.tsx:1422-1423` for `mediaTileBox` (pinned by `MediaGrid.test.tsx`) and `MessageList.tsx:100` `AT_BOTTOM_PX`.

  Comments are stripped first (precedent). The scope is built like this:
  - Seed at `app/app/messages-pro/**/{page,layout}.tsx`.
  - Seed the other set at every other `app/app/**/{page,layout}.tsx`, including the root layout.
  - Follow `@/components/…`, `@/app/…` and relative imports, and fail on an unresolvable `@/components` import (precedent).
  - Scope = the modules reachable from the Messages Pro seeds and not from the others, plus every file under `app/components` and `app/app` that imports `@/lib/messagesPro`, minus the module itself and test files.

  This follows `components/settings/sellerCopyLane.test.tsx`, whose header warns that "a scope you type is a scope you forget". Prior art for a shared table is `lib/boolKnob.test.ts`, and for a source-reading test `components/assistant/answerLinks.test.ts`.
  ASSUMPTION: "no magic numbers in JSX" means rules R1–R4. Tailwind scale classes such as `gap-2` stay allowed as the house scale, except beside a token (R4). Overturned if the human counts scale classes as magic numbers, in which case R1 also rejects numeric and named-size Geometry utilities. This is the open needs-human item in ## Review.
  ASSUMPTION: "used by all Messages Pro components" is checked as part 4 (every measured leaf is read somewhere in scope) plus R4 (nothing overrides a token), not as per-Region assertions on rendered DOM, which jsdom cannot style anyway (rung 5). Overturned if the human wants each Region's rendered classes asserted.
  ASSUMPTION: the guard's scope is every module reachable only from the Messages Pro routes, plus every module that imports `@/lib/messagesPro` (rung 3: `sellerCopyLane.test.tsx`). A shared module whose other screens use their own numbers takes Messages Pro Geometry by a class-name prop instead of importing the module. Overturned if the human wants shared pickers (for example `VaultPicker`, which has 18 importers) converted whole.
  ASSUMPTION: the snapshot test holds the expected object transcribed by hand from this Gap table, and does not parse this Markdown file (rung 5; there is no `toMatchSnapshot` precedent in `app/`). Overturned if the human wants the test to read the table from `docs/spec/` directly.
  ASSUMPTION: numeric literals in scope that have no Clone selector (extras, the spend chart, overlays, z-indexes) are lifted unchanged into `MP.ours.<ComponentName>`, and the test checks only that they are strings without colour, not their values. Overturned if the human wants those values measured too, which needs Clone evidence that does not exist.

- **D3. The app sidebar on Messages Pro.** On in-app Messages Pro routes the docked sidebar is hidden at every width, and "Toggle sidebar" opens the existing drawer (Interfaces, `AppShell`). Every other route is unchanged, and so is the Pop-out window (Phase 0). `docs/routes.md`'s Sidebar line gains: "except on Messages Pro, where it is the off-canvas drawer at every width".
  ASSUMPTION: on in-app Messages Pro routes the app sidebar is a drawer at every width. At 1280px a docked 252px sidebar (`Sidebar.tsx:106`) leaves the Thread 1280 − 252 − 390 − 280 = 358px, below even the Clone's compact Chat header (563px measured). The Clone's window also has no app sidebar: `.app` is 100vw (`m.html:47`), and the way back is the "Home" tab (`:87-88`, markup `:585-588`). Overturned if the human wants the docked sidebar kept, in which case the 1280 rule holds only while the sidebar is collapsed.
  plan:36 reads "Responsive rules in `docs/routes.md` stay: below 1024px one pane at a time, drawer sidebar." The colon names the rules that stay, and both are below 1024px, where D3 changes nothing. The docked sidebar at lg and up (`docs/routes.md:40`) is not among them. Collapsing is no way out at 1280: `AppShell` keeps `collapsed` in `useState(false)` (`AppShell.tsx:32`), so the sidebar comes back docked on every load.
  ASSUMPTION: plan:36 binds only the below-1024px rules, so D3 may change the sidebar from lg up on Messages Pro routes to meet plan:196's three panes at 1280. This is overturned if the human reads plan:36 as freezing the docked sidebar at lg and up, in which case D3 becomes "docked, but collapsed by default on Messages Pro routes", and the 1280 sweep runs collapsed.

- **D4. Chat header compaction.**
  - The Thread column (`ChatSurface.tsx:877`) gets `@container`.
  - The visible words of "Gallery", "Find" and "Open in new tab" sit in a span with `MP.chatHeader.labelText`. The icon and the button stay, and the accessible name stays because `sr-only` text is still read.
  - The Fan name and status line get `min-w-0` and `truncate` in JSX, with the identity block allowed to shrink.
  - Tailwind 4.3 has `@container`, `@min-[…]:` and `not-sr-only` in core (checked in `app/node_modules/tailwindcss/dist/lib.js`).
  ASSUMPTION: the Chat header hides the visible words "Gallery", "Find" and "Open in new tab" when the Thread column is narrower than 886px (a container query), and keeps them as accessible names. 886 is the Clone's measured labelled minimum, 768px at 1440×900, plus our additions sized from this table: the avatar, 36 + 14 gap (CH3), and the 📈 and "+" buttons, 30 + 4 each (CH10, CH9). The Clone gives no 1280 layout to copy, because it overflows its own header there (`.thread-head` scrollWidth 750 in a 610px column). Overturned if the sweep measures our labelled header at a different width, in which case CH14 and the module change together.
  ASSUMPTION: the Fan name and status line end in an ellipsis although the Clone only sets `nowrap` (`m.html:351`, `:353`), so that the compact header fits a 610px Thread (estimated at 570–590px; Further Notes). Overturned if the sweep shows the compact header fits without it.

- **D5. The overflow sweep.** `UI_SHOTS_SWEEP=1 scripts/ui-shots.sh` reuses Phase 0's relay, app, fixtures and request blocking.
  - **Runs.** For each of the eight runs (Contracts) it opens the URL, clicks the first Fan row and waits for the Composer's textbox.
  - **Per-run checks.**
    - (a) `document.documentElement.scrollWidth > innerWidth` is false.
    - (b) Nothing is clipped. Every element under `main` (the window root in `window-` runs) that is at least half the viewport tall has `scrollWidth ≤ clientWidth + 1`, which catches content clipped inside the Thread's `overflow-hidden` (`ChatSurface.tsx:869`) that (a) cannot see. Every visible button and textbox inside a pane also lies inside its pane's rect, with 1px tolerance, unless an `overflow-x: auto` or `scroll` ancestor inside the pane holds it (the Clone's chips and tab strips scroll, `m.html:141`, `:194`, `:332`). This catches a short row, such as the Chat header or a Composer row, that clips its own controls.
    - (c) From 1024px up, the three `[data-mp-pane]` roots (D9) are present and each is wider than 0. They are ordered `fan-list`, `thread`, `insights`, with `fanList.right ≤ thread.left + 1`, `thread.right ≤ insights.left + 1` and `insights.right ≤ innerWidth`. They sit side by side: their tops differ by at most 1px, and each is at least half the viewport tall. If Fan insights is closed, the sweep presses the "Fan insights" toggle once first. Three panes means Fan insights open; a Deep link opens with it closed (plan, Phase 0), which is why the toggle step exists.
    - (d) Below 1024px, exactly one of the Fan List and the Thread is visible.
    - (e) Phase 0's per-shot console-error and off-host checks.
    - (f) From 1024px up, (a) and (b) also run with Fan insights closed, the Thread's widest state, so a CH14 threshold set too low shows as clipping.
    - (g) Chat header words (D4). In `inapp-1440` and `window-1440`, with Fan insights closed (Thread 1440 − 390 = 1050px, above CH14's 886px), the visible word of "Gallery" is wider than 1px. With Fan insights open (770px) it is not, and a button named "Gallery" still resolves. Both sides of CH14's threshold are exercised.
    - (h) Long names. In `inapp-1280`, the sweep sets the Chat header's Fan name to a 60-character string in the page and re-runs (b). This tests story 32.
  - **Pane locators.** Each pane root carries `data-mp-pane` (D9). The house already marks rows this way (`data-chat-row`, `ChatList.tsx:1019`).
  - **Output.** It writes the report and two PNGs, and exits non-zero unless every run is ok. `docs/ui-shots.md` gains one paragraph describing the mode.
  ASSUMPTION: the plan's "Playwright `# manual:` overflow check" becomes an opt-in harness mode (`UI_SHOTS_SWEEP=1`) that checks and exits non-zero, plus a `# manual:` look at the PNGs. The default run and Phase 0's fixed shot list do not change (rung 4: additive and off by default). Overturned if the human wants the check left fully manual, in which case the mode is dropped and a `# manual:` line carries the four viewports.
  ASSUMPTION: the 768 run uses 768×1024, a portrait tablet, because neither the plan nor `docs/routes.md` gives its height. Overturned by a named tablet size.
  ASSUMPTION: the sweep finds the panes by `data-mp-pane` on the three pane roots (rung 3: `data-chat-row`), not by landmarks, because only Fan insights is a landmark. Phase 5 now names the pinned column "Fan insights", as Phase 0 asks (`phase-05-fan-insights-panel.md:120`, its review D2), but the Fan List and the Thread have no landmark of their own. Overturned if Phases 1–3 give the Fan List and the Thread landmarks, in which case the landmarks become the locators and the attributes go.
  ASSUMPTION: (f) to (h) reuse the four viewports and Phase 0's fixtures, toggling Fan insights and editing the name text in the page, instead of adding a viewport or a fixture (rung 5). Overturned if Phase 0's fixtures gain a long-name Fan, which then replaces the in-page edit.
  ASSUMPTION (evidence blocked): `OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 scripts/ui-shots.sh` runs the sweep with the Legacy flag on, because the harness passes its environment to the app it starts and `lib/flags.ts:18-19` reads the flag from that environment. `scripts/ui-shots.sh` does not exist yet (Phase 0 creates it), so this cannot be observed. Overturned if Phase 0's harness fixes the app's environment, in which case the flag-on run sets the variable for the build as well.

- **D6. Colours.** The module holds none. The per-Phase colour mappings are confirmed as written (P1, P2, P3, P5 "overturned by Phase 6's token table"), with one reconciliation.
  ASSUMPTION: every unread count and unread dot uses `info` (`globals.css:38`: "used for unread / 'new' signals"), because the Clone draws all of them in one colour, `--coral` (`.mini-badge.red` `:65`, `.cbadge` `:145`, `.ud` `:187`). This moves Phase 2's chip count badge from `err` to `info`. Owe stays `warn`. Overturned if the human reads the coral badge as an alert colour, in which case all of them move to `err` together.

- **D7. Clone rules that only the rewired Clone has.** The Geometry of `.msg-acts`, `.pinbar` and `.load-older` is applied (ML14–ML21). `.ppv-mini` comes from the screenshot build (`orig:203`) and is applied to the PPV message container (ML10–ML11). The hover actions show only a glyph from md up. Their word becomes the `aria-label`, and the existing `title` stays. Below md they keep today's labelled tap sizes. One `MessageList.test.tsx` case pins the names.
  ASSUMPTION: the Geometry of `.msg-acts`, `.pinbar` and `.load-older` is applied although these rules are absent from the Clone's screenshot build (`git show 4e83397:ui-redesign/infloww-exact/messages.html` has none of them), because the plan names the Clone as the reference (rung 2). Overturned by an Infloww capture of those controls.
  ASSUMPTION: from md up, each hover action shows only its current leading glyph (↩, ♥ or ♡, 📌, 🗑, 🎁, `MessageList.tsx:692-738`) and drops its word. The accessible name is the action's word in its current state, as today's `title` already gives it (Reply, Like or Unlike, Pin or Unpin, Unsend, Reward), matching the Clone's glyph-only buttons with a `title` (`m.js:877-880`). Below md the buttons keep today's glyph-and-word tap targets. Overturned if the Visual loop shows the glyphs read badly at 24px.

- **D8. Shell heights.** `.h-chat` and Phase 0's `--shell-top` stay as they are. The module does not take over shell heights, so Phase 0's `.h-chat` ASSUMPTION stands.

- **D9. Pane tokens.** The pane row is a flex row from lg up (`.body`, `m.html:113`):
  - the Fan List with `MP.panes.fanList`;
  - the Thread column with `flex-1 min-w-0 @container`;
  - Fan insights with `MP.panes.insights`.

  Each of the three roots carries `data-mp-pane="fan-list"`, `"thread"` or `"insights"` for the sweep (D5).

  `page.tsx:189`'s grid value leaves with the roster (Phase 1). Below lg the Fan List and the slide-over keep their full-width phone behaviour (`docs/routes.md`). The slide-over's own widths (`FanDrawer.tsx:333`) are ours and are lifted unchanged into `MP.ours.FanDrawer`.
  ASSUMPTION: the pinned-messages overlay follows the Fan List width (`w-full max-w-[390px]`), because it is drawn over the Fan List (`PinnedPanel.tsx:165`, `left: 0`) and the Clone has no such overlay. Overturned if Phase 3's pinned bar replaces the overlay.

- **D10. Values derived from Clone values.**
  The Clone's 2px inset top line on the active Creator tab and Fan tab (`m.html:336`, `:197`, `box-shadow: inset 0 2px 0`) sits inside the tab's 1px border (`:334`, `:195`), so it adds no height. The token is `inset-shadow-[0_2px_0]` and the tab's 1px border stays. The colour is an `inset-shadow-<token>` class in JSX. Tailwind 4.3.0 compiles `inset-shadow-[0_2px_0]` to `inset 0 2px 0 var(--tw-inset-shadow-color, currentcolor)`, and `inset-shadow-accent` sets `--tw-inset-shadow-color` (checked with `compile()` from `app/node_modules/tailwindcss/dist/lib.mjs`). This is rungs 1 and 2: the Clone's own geometry, and an observed way to hold it without colour.
  ASSUMPTION: the SFW knob's on position, 12px, is derived as 26 − 10 − 2 × 2, because the Clone draws only the off state (`m.html:73-74`). Overturned by a measured on state.

- **D11. Typeface.**
  ASSUMPTION: the font family stays Sora (`globals.css:40-41`), not the Clone's Inter (`m.html:35`, §1.4), because a typeface is brand rather than Geometry. Widths measured in Inter may differ by a few pixels in Sora, and the sweep catches any overflow that causes. Overturned if the human treats the typeface as Geometry.

- **D12. Ticket order.** This Phase lands in two parts. First: the pane widths (PN2, PN4), D3's sidebar with D9's pane tokens, and D5's sweep, because they decide whether plan:196's three panes at 1280×800 and 1440×900 hold. Then: the module, the guard and the lift of every Gap table row (D1, D2). The plan binds both parts (plan:194-199), so a short budget defers the second part and does not cut it.
  ASSUMPTION: the lift does not wait for the scale-class question (needs-human, below). Both readings keep R1's ban on digits inside arbitrary values (B6, D1), so the human's answer can only widen the lift, never undo it (rung 4). This is overturned if the human's answer also lets arbitrary values stay in JSX, which neither position proposes. In that case the lift shrinks to what the answer still bans.

## Testing Decisions

- **What a good test is here.** A good test checks external behaviour through existing seams. The token test is the one deliberate snapshot, because the plan asks for it and because the module's values are the deliverable. jsdom applies no Tailwind CSS, so widths, overflow, the container query and the three panes are proven only in the browser, by the sweep.
- **Seam 1 (new, the plan's seam): `app/lib/messagesPro.test.ts`.** It takes the module import and the source files of the computed scope. Its outputs are equality with `EXPECTED`, a colour check, and a list of `file:line` hits that must be empty.
  1. `MP` without `ours` deep-equals `EXPECTED`. That is the 13 measured regions, with one key per Gap table row from PN1 to ES3, except the rows with no token (PN3, and the no-element rows FL36, CH5 and PV7, ticket 119).
  2. Every leaf, `ours` included, is a non-empty string with no colour-token class and no colour literal.
  3. The computed scope includes known members (`components/chat/MessageList.tsx`, `components/chat/FanDrawer.tsx` and Phase 0's `MessagesPro`) and excludes the shell (`components/shell/AppShell.tsx`). A broken import walk therefore cannot pass with an empty scope.
  4. Rules R1–R4 over the scope return no hits.
  5. Every measured leaf is read by a file in the scope, and every `MP.ours` group by its component (D2 part 4).
  - Prior art: `components/settings/sellerCopyLane.test.tsx` (a computed render graph seeded at routes), `lib/boolKnob.test.ts` (a shared fixture table) and `components/assistant/answerLinks.test.ts` (a source-reading drift guard).
- **Seam 2 (existing): `app/components/shell/AppShell.test.tsx`.** It already mocks `usePathname` and `matchMedia`. Three cases are added, and the two existing ones stay unchanged.
  1. Desktop (`matches: true`) on `/messages-pro`: "Toggle sidebar" has `aria-controls="app-sidebar-drawer"` and `aria-expanded="false"`. Clicking it opens the dialog named "Menu", and Escape closes it.
  2. Desktop on a Deep link, `/messages-pro/acc1/123`: clicking opens the dialog "Menu".
  3. Desktop on `/`: "Toggle sidebar" has `aria-controls="app-sidebar"`, and clicking opens no dialog and sets `aria-expanded="false"`. This pins today's collapse so that D3 cannot leak onto other routes.
- **Seam 3 (existing): `app/components/chat/MessageList.test.tsx`.** One case: with the action handlers passed, the hover actions are buttons named "Reply", "Like", "Pin", "Unsend" and "Reward", for those that apply to the message (D7).
- **Seam 4 (existing, browser): `scripts/ui-shots.sh`.** The default run must stay green, and `UI_SHOTS_SWEEP=1` checks overflow, clipped controls and panes at the four sizes, with the Legacy flag off and on, including the Chat header words on both sides of CH14 (story 30) and a long Fan name (story 32) (D5). The harness has no unit tests of its own: its exit code against its report is its test (Phase 0).
- **Existing tests that must stay green with no edit.**
  - Phase 0's `windowed.test.tsx`: case 2 still finds `#app-sidebar`.
  - Phase 3's Chat header tests: "Gallery", "Find" and "Open in new tab" still resolve as names through the `sr-only` text.
  - Phases 1–5's suites, which assert roles, names and payloads, not Geometry classes.
- **Not tested.** Pixel values in jsdom. Whether Tailwind generated each class, which the sweep and the Visual loop show. The 1024–1279 band (Out of Scope).

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# the token module and its seam exist (vitest passes with no tests, so check the files)
test -f app/lib/messagesPro.ts
test -f app/lib/messagesPro.test.ts
# the module holds Geometry only: no colour-token class and no colour literal
if grep -nE '(^|[ "`:])(bg|text|border|ring|fill|stroke|outline|shadow|divide|placeholder|caret|decoration|from|via|to)-(bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current)([-/ "`]|$)' app/lib/messagesPro.ts; then echo "colour class in the token module"; exit 1; fi
if grep -nEi '#[0-9a-f]{3,8}([^0-9a-z]|$)|rgba?\(|hsla?\(|oklch\(' app/lib/messagesPro.ts; then echo "colour literal in the token module"; exit 1; fi
# the Phase's seams: snapshot + magic-number guard, the sidebar rule, hover-action names, Phase 0's windowed case
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run lib/messagesPro.test.ts components/shell/AppShell.test.tsx components/chat/MessageList.test.tsx app/messages-pro/windowed.test.tsx
# binding commands
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
# no relay/service change in this Phase
git diff --quiet "$(git merge-base HEAD main)" -- service/
# Visual loop harness (Phase 0): the default run is unchanged and still green
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-desktop.png
test -s docs/screenshots/clone-messages-pro.png
test -s docs/screenshots/messages-pro-report.json
# overflow sweep: 1440x900, 1280x800, 768x1024, 390x844, in the app and in the Pop-out window
# first with the Legacy flag on (its extras widen the Chat header and the Window header); its exit code is the check
OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
# then flag off, which writes the committed report and PNGs
UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-sweep.json
test -s docs/screenshots/messages-pro-1280.png
test -s docs/screenshots/messages-pro-768.png
venv/bin/python -c 'import json,sys; r=json.load(open("docs/screenshots/messages-pro-sweep.json")); [print(x["name"], x["viewport"], x["panes"], "ok" if x["ok"] else "FAIL", x["wide"], x["failures"]) for x in r["runs"]]; sys.exit(0 if r["ok"] and len(r["runs"]) == 8 and all(x["ok"] and not x["failures"] for x in r["runs"]) else 1)'
# manual: open messages-pro-1280.png and messages-pro-desktop.png beside clone-messages-pro.png; write the visual-diff list for pane widths, row heights, paddings, radii, font sizes and icon sizes in every Region; fix, re-run, up to three rounds; record what remains as VISUAL GAP: lines with the reason
# manual: open messages-pro-768.png, messages-pro-phone-list.png and messages-pro-phone-thread.png and confirm one pane at a time, phone tap sizes kept and nothing cut off at the right edge
# manual: in a desktop browser at 1280x800 on /messages-pro, press "Toggle sidebar" and confirm the sidebar opens over the panes and Escape closes it; on / confirm it still docks and collapses
# manual: record the messages-pro-report.json and messages-pro-sweep.json summaries, and our measured labelled Chat header width (CH14), in the Phase result
```

## Depends on

- **Phase 0.** This Phase needs:
  - the harness that the sweep extends, with its relay, fixtures and request blocking;
  - the `MessagesPro` tree;
  - `nav`'s `isPopoutWindow` and `AppShell`'s Pop-out window branch;
  - `aria-current` on the selected Fan row;
  - `windowed.test.tsx`.
- **Phases 1–5.** They supply the Regions and inline numbers this Phase lifts, and Phase 2's interim constant. Phases 1 and 3 may create `app/lib/messagesPro.ts` first. If they do, they write into this shape and these keys. Phases 4 and 5 read the module if it exists when they land. They are merged into `main` before this Phase starts, which is what makes Acceptance's `git merge-base HEAD main` baseline for `service/` right: Phase 2 changes `service/` (`phase-02-fan-list-pane.md:135-147`).
  ASSUMPTION: the Phases land on `main` one at a time, as the Phase 3 spec's identical check assumes (`phase-03-chat-header-message-list.md:266`, rung 3). Overturned if the Phases are stacked on one branch, in which case the baseline becomes the commit this Phase starts from.
- **Phase 3's spec is in git.** An earlier draft found `docs/spec/phase-03-chat-header-message-list.md` ignored by `.gitignore:121` (`*CHAT*.md`). Commit `ad06cdc3` added `!docs/spec/*.md` (`.gitignore:124`): `git check-ignore -v` on the file now exits 1, and `git ls-files docs/spec` lists it. Every P3 Hn, Mn, Ln and Fn reference here points at a tracked file.
- **Blocks Phase 7.** The Extras overflow trigger and menu read their sizes from this module (`phase-07-ours-kept-marked.md:107`, `:132`).

## Out of Scope

- **Colours in the module, and any palette change beyond D6's one reconciliation.** ADR-0001 keeps colour in `globals.css`.
- **The Vault picker's own Geometry.** `VaultPicker` has 18 importers and keeps its own numbers, including row 27's `.vdur` and rows 28–29. In scope instead: P4 rows 25–26 apply the Clone's `.sheet`, `.sheet-h`, `.mgrid` and `.mt` values in the Messages Pro mode that only `Composer` passes (`phase-04-composer-ppv-vault.md`, rows 25–27 and its review D4). Those are the same rules as P3 M4, so they share SH1, SH2, SH5 and SH6: `Composer` passes the `MP.sheet` tokens to `VaultPicker` as class-name props (Shared modules), and `VaultPicker` never imports the module. The picker reads SH1 and its own `md:` variants of SH2, SH5 and SH6 (`pickerHead`, `pickerTitle`, `pickerGrid`, `pickerTile`), so below md it stays the full-screen pane it is everywhere else (ticket 117).
- **`.typing-line` (`:523`).** We have no typing indicator.
- **`.tr-box` and the top-right `.icon-btn` (`:75-79`, markup `:600-606`).** Phase 1 leaves them out, because they are not in §3.3's header list.
- **`.nlist` and the notifications sheet (`:466-472`).** Phase 1 reuses the shared `NotificationBell`.
- **The Vault rules:** `.vid-*`, `.vault-*`, `.vfolder`, `.vtb`, `.vchips`, `.vcap*`, `.vmore-row`, and the tile overlays `.vdur`, `.vplay` and `.vhover-cd` (`:396-465`).
- **Clone styling of extras that no Phase adopted:**
  - `.creator-chip` (`:509-511`)
  - `.mi-*` (`:547-552`)
  - `.tip-reward` (`:264-265`)
  - the `.ai-strip .meter` (`:482`)

  Their current literals are lifted unchanged into `MP.ours`.
- **The screenshot build's large PPV card:** `.ppv-card`, `.ppv-badge`, `.ppv-text` and `.mini-avatar` (`:223-240`). Phase 3 chose the status line and unlock bar.
- **`.tiny-line` (P5 G8) and `.cal-i` (P5 G16).** Phase 5 renders neither.
- **`.sheet-f`, `.pop input` and `.pop .pdot`.** No Region uses them.
- **Element order and labels.** Phases 1–5 own them, and this Phase changes sizes only. The exception is D7's hover-action names.
- **Pane resizing or user-adjustable widths.**
- **A fit check between 1024 and 1279px.** The plan names 1280 and 1440 only.
  ASSUMPTION: between 1024 and 1279px the three panes still render side by side (D9; `docs/routes.md:42`, "`lg` and up keep the three-pane grid") and the page still does not scroll sideways (`docs/routes.md:44`), but the sweep asserts neither there, and the Thread's controls may be clipped inside its column (`ChatSurface.tsx:869` `overflow-hidden`) while Fan insights is open. Overturned if the human adds a 1024 rule, which would need Fan insights closed by default below 1280.
- **Phone layout beyond what Phases 2–4 keep.** `messages.html`'s own CSS has one `@media` rule, reduced motion (`:575`), but the `_shared/infloww-rea.js` it loads (`:876`) injects a 760px one-pane rule (`infloww-rea.js:1056-1062`). We keep `docs/routes.md`'s 1024px breakpoint (`routes.md:42`), so at 768px ours shows one pane where the Clone shows three.
- **Flag-on PNGs.** The sweep runs once with the Legacy flag on as a check (D5, Acceptance) but writes its PNGs flag off. Phase 7 renders no flag-on shot either (`phase-07-ours-kept-marked.md:269`).
- **The typeface (D11) and shell heights (D8).**
- **An ESLint rule for magic numbers.** The vitest guard covers the rule after the house precedent.
- **Measuring live Infloww.** The Clone is the only reference, and nothing leaves the machine.

## Further Notes

- **Clone measurements (rung 1).** The Clone was rendered offline from `file://` with Python Playwright (`venv/bin/python`, after `scripts/make-extension-screenshots.py`), with every non-file request aborted.
  - **At 1440×900.** The panes are `.list` 390, `.center` 770 and `.right` 280. `.topstrip` is 46 and `.hometabs` 34. The `.thread-head` min-content is 768 with its labels ("Jessica Martinez", "Last seen 5 min ago"). It is 633 with the Gallery, Find and "Pop out" words hidden, and 563 when the back chevron and the persona button are also removed. Its parts are `.th-id` 151, `.th-tools` 206 and `.th-right` 136. `.comp-r1` min-content is 334, `.comp-r2` 453 and `.topstrip` 718.
  - **At 1280×800.** `.center` is 610, but `.thread-head` has scrollWidth 750 against clientWidth 610. The Clone overflows its own Chat header, and `body`/`.app` `overflow:hidden` (`:39`, `:47`) hides it.
- **The width budget.**
  - **Thread width.** With the drawer sidebar (D3), the Thread is 1280 − 390 − 280 = 610 at 1280, and 770 at 1440. With a docked sidebar it would be 358 and 518.
  - **Compact Chat header at 1280.** Our estimate starts from the Clone's compact header without back and persona, 563. Our additions bring it to 681: the avatar 50, 📈 34 and "+" 34. The persona button is flag-gated (P3 H8), and the back chevron is below lg only (P3 H2). The ellipsized identity block (151 → about 40) brings it to about 570, which fits 610.
  - **Labelled Chat header.** About 886 (CH14), so the words show only in Threads at least that wide, for example a 1920px window.
  - **These are estimates.** The sweep measures the real values, and the Phase result records ours (Acceptance).
- **Plan lines and where they are covered.**
  - "pane widths": stories 12 and 21.
  - "row heights": 13–14.
  - "paddings", "radii", "font sizes", "icon sizes": 14–17 and 19–20.
  - "measured from `messages.html` and `_shared/components.html`": 5–6.
  - "colours from our tokens (§1.4 is reference only)": 7 and 23–25.
  - "One `messagesPro.ts` token file in `app/lib/`": 1–3.
  - "holding the measured numbers": 5 and 9.
  - "used by all Messages Pro components": 10–11 and 35–36.
  - "no magic numbers in JSX": 8 and 35.
  - "1280x800 and 1440x900 … three panes without horizontal scroll": 26–33.
  - "Snapshot test of the token file against the measured table": 34.
  - "Playwright `# manual:` overflow check at 1280, 1440, 768, 390": 37–39 and the `# manual:` lines.
- **Earlier ASSUMPTIONs this Phase settles.**
  - P1's colour mapping is confirmed.
  - P1's "creates the module if missing" and P3 F13's `chatHeader`/`messageList` sections are both honoured: the shape and keys are fixed here.
  - P2's interim constant moves here and is deleted.
  - P2's colour mapping is confirmed, except the chip count badge, which moves to `info` (D6).
  - P4's and P5's inline values are lifted.
  - P5's colour mapping is confirmed.
  - P0's `.h-chat` ASSUMPTION stands (D8).
- **Disagreements between other specs.**
  - **The Fan insights landmark.** Settled: Phase 5 now names the pinned column "Fan insights" (`phase-05-fan-insights-panel.md:120`), as Phase 0 asks. The Fan List and the Thread have no landmark, so the sweep keeps `data-mp-pane` on all three pane roots (D5, D9).
  - **`#tbOpen`.** Settled: Phase 1 (story 20, `phase-01-window-chrome-tabs.md:79`) and Phase 3 H9 both ship "Open in new tab", which adds a Fan tab, and ADR-0002 is amended to match. CH14 hides that label.
- **Rung 1 evidence for D4 and D5.** Tailwind 4.3.0 is in use (`@import "tailwindcss"`, no config file), and `@container`, `@min-[…]:` and `not-sr-only` are in core. Playwright and Chromium are already available to the harness (`venv/bin/python`, `~/Library/Caches/ms-playwright`).

## Review

codex (`codex exec`, reasoning effort high, read-only sparse worktree with no `docs/spec/`), 2026-10-12. Both calls exited 0 and wrote fresh output. The blind call could not open a browser, so its width budgets are arithmetic. The draft call read the spec at the worktree's `HEAD`.

Blind call (B), before the spec was shown:
- B1. The plan has no layout contract, and ADR-0001 does not weigh token implementations. **reject**: D1 records the options weighed (class strings, CSS variables, inline style) with evidence, and the plan names the file (`messages-pro-parity.md:194`).
- B2. The Clone's three-pane fit is unproven, and a docked 252px sidebar leaves 358px. **reject**: D3 settles the sidebar on that same arithmetic, and Further Notes records the Clone measured at 1280 (a 610px Thread, header scrollWidth 750).
- B3. "No horizontal scroll" can pass while controls are clipped under `overflow:hidden` (`m.html:39`, `ChatSurface.tsx:869`). **accept**: D5 (b) now requires every visible button and textbox to sit inside its pane's rect, and (f) repeats the checks with Fan insights closed.
- B4. Four token designs; it prefers a numeric TS module feeding scoped CSS variables. **reject**: a CSS variable cannot drive a breakpoint or a container threshold, and it does not reach the portaled pickers (D1). The class strings hold the measured numbers as literals, which is what the plan asks for.
- B5. Geometry held in JS escapes a JSX-only rule: `PinnedPanel.tsx:37` (320), `EmojiBar.tsx:956` (384) and `TagCreatorsPicker.tsx:101` (320). **partial**: R2 now catches a numeric constant from the same file used as a style geometry value, which covers PinnedPanel, and PN5 replaces that value. The picker constants are each picker's own panel size for viewport clamping (`EmojiBar.tsx:953-957`), not pane geometry, and they live in shared modules outside the scope.
- B6. Allowing scale classes leaves Geometry spread through JSX (`ChatList.tsx:1040`, `MessageList.tsx:763`). **needs-human**: see the item below.
- B7. Which source wins is undefined (the kit's switch is 40×22, the Clone's is 26×14). **reject**: Sources put `messages.html` first and allow only three kit rules, and WH11 uses the Clone's 26×14 (`m.html:73`).
- B8. "Fit" ignores shell state, and the Deep link opens with Fan insights closed (plan `:68-70`). **partial**: D3 and the eight runs already cover the sidebar and the in-app and windowed cases. D5 now says that three panes means Fan insights open, explains the toggle step by the Deep link's closed default, and checks overflow with Fan insights closed too.
- B9. The Clone also has a 760px phone rule (`_shared/infloww-rea.js:1056`). **partial**: the false claim in Out of Scope ("only `@media` rule is reduced motion") is corrected. The decision stays on `docs/routes.md:42`'s 1024px breakpoint.
- B10. Inter against Sora. **reject**: D11 decides it, with a flag, and the sweep catches any overflow it causes.
- B11. Vertical invariants (`--vvh`, the safe area, scroll anchoring, media placeholders). **reject**: D8 leaves `.h-chat` and `--shell-top` alone, and CP1 keeps `env(safe-area-inset-bottom)`. D2 now says the `mediaTileBox` constants (`MessageList.tsx:1422-1423`) and `AT_BOTTOM_PX` stay where they are. Owns allows Geometry classes only.
- B12. The checkout still has the roster grid and `forcePinnedPanelOpen`, and vault code imports `chat/VaultPicker`. **reject**: Depends on requires Phases 0–5, which remove both, and `VaultPicker` is Out of Scope.
- B13. Geometry must be checked with the flag off and with it on. **accept**: Acceptance runs the sweep with `OPENINFLOWW_LEGACY_AUTOMATIONS=1` (see D8 below).
- B14. Nothing tests token to consumer, so a removed consumer leaves the snapshot green. **accept**: D2 part 4 (every measured leaf must be read in scope) and R4 (nothing may override a token beside it).
- B15. Provenance: a token and its snapshot can change together without remeasuring. **reject**: the plan's seam is a snapshot against the spec's table, and the table carries each value's Clone `file:line`. Remeasuring is the Visual loop's job. A test that parses `messages.html` would be a second measuring tool, which the plan never asked for.
- B16. The browser matrix needs long names, populated tabs, and PPV, reply and attachments. **partial**: D5 (h) adds a long Fan name. The PPV row and the attachments wrap in the Clone (`m.html:514`, `:519`), so they grow down and not sideways. The tab strips and chips scroll (`m.html:141`, `:194`, `:332`), which (b) allows.

Draft call (D), on this spec:
- D1. R1–R3 pass `w-80 p-10 text-4xl rounded-3xl`, so components can bypass the module. **needs-human**: see below. Accepted in part: R4 and D2 part 4 catch an override beside a token and a token nothing reads.
- D2. The sweep locates child controls, not panes, so stacked panes pass (c), and (b) skips short clipped rows. **accept**: `data-mp-pane` roots (D9) with a same-top and minimum-height check in (c), and the in-pane control rect check in (b).
- D3. FL32, FL49 and FL50 drop kit Geometry: `.fx-new` letter-spacing, `.fx-note` border and line-height, `.fx-select` border and `padding-right:32px`. **accept**: the rows are rewritten from `kit:106-110`, `:188-189` and `:191-192`.
- D4. FI19 and FI30–FI32 claim elements that Phase 5 does not draw (a line chart, media rows). **accept**: FI18 becomes `MP.insights.chart` (height and margins only). FI19 and FI30–FI32 are "no element" rows with no token, and their literals go to `MP.ours.FanDrawer`.
- D5. No seam ever shows the words coming back, because 1440 gives a 770px Thread. **accept**: D5 (g) runs at 1440 with Fan insights closed (1050px, words shown) and open (770px, words hidden, name kept).
- D6. The 1024–1279 exclusion contradicts `docs/routes.md:42`. **partial**: D9 keeps three panes from lg, so the contract holds. The Out of Scope line now says so and names what goes unasserted. No 1024 run is added, because the plan names 1280 and 1440.
- D7. `border-t-2` is not the Clone's inset line and changes the box. **accept**: CT3 and FT4 become `inset-shadow-[0_2px_0]` inside the kept 1px border, which compiles in Tailwind 4.3.0 with the colour class in JSX (D10).
- D8. Flag-on checks are handed to Phase 7, which excludes them (`phase-07-ours-kept-marked.md:228-229`). **accept**: the false handoff is removed, and Acceptance runs the sweep with the flag on. The env pass-through is flagged as evidence blocked.
- D9. `merge-base HEAD main` rejects Phase 2's `service/` changes if the Phases are stacked. **partial**: the check stays (Phase 3 uses the same one, `phase-03-chat-header-message-list.md:255`). Depends on now says Phases 0–5 merge to `main` first, with a flag.
- D10. The Phase 3 spec is absent from `HEAD`, so its references cannot be checked. **accept** as a fact: `.gitignore:121` (`*CHAT*.md`) ignores it. This is recorded in Depends on for whoever commits the specs.

**needs-human: do Tailwind scale classes count as "magic numbers in JSX"?** (B6, D1)
- The spec's position: R1 rejects digits inside arbitrary values only. Scale classes (`gap-2`, `rounded-md`) stay as the house scale, except beside a token (R4), and every measured token must be read (part 4).
- Codex's position (both calls): a scale class is a number in JSX too. `w-80` or `p-4` in a component that skips the token passes the guard, so Clone Geometry can live outside the module (plan `:194-195`, ADR-0001:3). Codex would ban numeric and named-size Geometry utilities in scope.
- The cost of codex's position: by the regex run over five scope modules, they hold about 585 such classes (FanDrawer 192, MessageList 173, Composer 150, ChatSurface 41, PinnedPanel 29). Each would move into a token or `MP.ours`, against 234 arbitrary values today.
- What settles it: the human's reading of "no magic numbers in JSX", that is, whether a Tailwind scale step is a magic number.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: rows FI18–FI32 (`:259-273`) contradict Phase 5's G11 bars and G19 table (`phase-05-fan-insights-panel.md:21`, `:29`). **accept**: verified. FI18 now lifts `h-[62px] gap-[3px] mt-[6px] mb-[4px]`. FI19 lifts `MP.insights.bar`, and FI30–FI32 lift `salesTable`, `salesHead` and `salesCell`. Seam 1 now exempts only PN3. The purchased-media rows' literals still go to `MP.ours.FanDrawer`.
- Black: the Vault picker Out of Scope entry (`:609`) is stale against Phase 4's rows 25–27. **accept**: verified against `phase-04-composer-ppv-vault.md:35-37`, `:139` and `:456`. The entry is rewritten: rows 25–26 share SH1, SH2, SH5 and SH6 through class-name props from `Composer`, and only the picker's own numbers stay out. SH rows and Owns name it.
- Black: Owns lists `ThreadEmptyState` under Phase 3 (`:388`). **accept**: Phase 3 dropped it to Phase 1 (P3 F22). It is gone from Owns, and ES1–ES3 and reconcile item 9 cite Phase 1 only.
- Black: the "Phase 3 not in git" note (`:603`) is false since `ad06cdc3`. **accept**: verified with `git check-ignore -v` (exit 1) and `git ls-files docs/spec`. The note now says the file is tracked.
- Black, cross-check: the landmark ASSUMPTION and Further Notes said Phase 5 leaves the pinned column unlabelled, and the `#tbOpen` note expected two labels. **accept**: Phase 5 now names it (`phase-05-fan-insights-panel.md:120`), and both Phases ship "Open in new tab". The `data-mp-pane` locators stay, for the Fan List and the Thread.
- Black: the sidebar change (D3, `:476`) contradicts plan:36. **reject**: plan:36's colon names two below-1024px rules, and D3 keeps both. plan:196 needs three panes at 1280, and collapsing does not persist (`AppShell.tsx:32`). The reading is a new ASSUMPTION under D3, with the fallback "docked, collapsed by default on Messages Pro routes".
- Black: the snapshot is copied by hand. **reject**: plan:199 asks for a snapshot "against the measured table", and the table is prose in this spec, so a hand transcription is the test (D2). The rows it copies are the rows reviewed here.
- Black: the 234-value lift is large. **partial**: the plan binds it (plan:194-195), so it stays. D12 now lands it after the panes, the sidebar and the sweep.
- Green: trim this Phase to PN2/PN4, D3 and the sweep, and hold the lift. **partial**: the order is accepted as D12. Holding the lift until the scale-class question is answered is rejected: both positions in the needs-human block keep R1, so the answer can only widen the lift (D12 ASSUMPTION).
- Blue: the Phase 6 lift is second in the cut order. **partial**: it is deferred, not cut, because the plan names it.
- White: the scale-class question still needs the human. **accept**: it is listed verbatim under "Needs the human" in `plan-review.md`. This spec does not change.

**Update 2026-10-18.** WH1, WH2, FT1, FL1, FL2, FL5 to FL8, FL10, FL11, FL13, FL15, FL17 to FL19, FL23, FL27, FL29, FL30, FL34, FL37, ES2 and ES3 now take the live Infloww Messages Pro capture of 2026-10-18 over the Clone's values (`docs/infloww-sidebar-palette.md`, "Messages Pro polish"). Home (WH2) moved from the Window header to the start of the Fan tabs row and links to `/messages-pro`.
