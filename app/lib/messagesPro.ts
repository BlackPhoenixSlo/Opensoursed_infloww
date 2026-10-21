/**
 * Messages Pro Geometry (ADR-0001): Infloww's sizes as Tailwind class
 * strings, measured from the Clone (its `messages.html`, deleted; tag `legacy-ui-final`;
 * cited as mh:N) and Infloww's own screenshots, so the JSX carries no magic
 * numbers. Class strings only: colours stay in the JSX, from our tokens.
 *
 * `MP.<region>.<element>`, two levels: the 13 measured Regions hold one leaf
 * per row of the Gap table in docs/spec/phase-06-geometry-pass.md (PN1 to
 * ES3, the row id leads each comment), each leaf exactly that row's Change
 * column string, and `ours` holds our literals with no Clone selector. The
 * snapshot in `messagesPro.test.ts` pins the Regions to the table. A pixel
 * value the Tailwind scale has is its scale class; an arbitrary value only
 * where the scale lacks it (spec D1).
 */
import { OURS } from "./messagesProOurs";

export const MP = {
  /** Panes and page (PN). */
  panes: {
    /** PN1. PN1, `body` (mh:37): unsized text is 14px at line height 1.4. On
     *  the Messages Pro root. */
    root: "text-sm leading-[1.4]",
    /** PN2. PN2, `.list` (mh:116): 400px wide and never narrower from lg up
     *  (2026-10-18 capture: 531px / 1.32; the Clone's 390px), and a 1px right
     *  border at every width. Below lg the Fan List is the whole screen. */
    fanList: "lg:w-100 lg:min-w-100 border-r",
    /** PN4. PN4, `.right` (mh:292): 280px wide and never narrower, a 1px left
     *  border. The pinned Fan insights column, shown from lg up only. */
    insights: "lg:w-70 lg:min-w-70 lg:border-l",
    /** PN5. PN5: the pinned-messages overlay covers the Fan List, so it is as
     *  wide as PN2 (the Clone has no such overlay). */
    pinnedOverlay: "w-full max-w-100",
  },
  /** Window header (WH). */
  windowHeader: {
    /** WH1. The Window header, `.topstrip` (mh:51-55, override mh:101),
     *  at Infloww's 44px (2026-10-18 capture; the Clone's 46px): padding 0
     *  14px, children bottom-aligned, 1px bottom border. */
    bar: "h-11 min-h-11 px-3.5 border-b",
    /** WH2. Home, a folder tab first in the Fan tabs row (2026-10-18
     *  capture; the Clone's `.htab` sat in this header, mh:87-88): 164×24px,
     *  4px in, its label centred, 13px / 600, the top left corner rounded and
     *  the right edge slanted 10px. */
    home: "ml-1 w-41 h-6 gap-1.75 rounded-tl-lg text-[13px] font-semibold [clip-path:polygon(0_0,calc(100%-10px)_0,100%_100%,0_100%)]",
    /** WH3. Home's grid icon (mh:89). */
    homeIcon: "size-3.75",
    /** WH4. All Models, `.am-hero` (mh:92-93, mh:104):
     *  right after Home, bottom-aligned 5px above the row's edge, 2px left
     *  margin, 30px tall, padding 0 14px, 7px gap, radius 8px, 13px / 700, one
     *  line. */
    allModels: "mb-1.25 ml-0.5 gap-1.75 h-7.5 px-3.5 rounded-lg text-[13px] font-bold",
    /** WH5. All Models' layers icon, `.am-hero svg` (mh:95): 16px. */
    allModelsIcon: "size-4",
    /** WH6. "+ Add a Creator", `.add-creator` (mh:68): 7px gap, 13px / 500,
     *  padding 0 14px, one line. */
    addCreator: "gap-1.75 px-3.5 text-[13px] font-medium",
    /** WH7. Its "+" icon, `.add-creator svg` (mh:69): 15px. */
    addCreatorIcon: "size-3.75",
    /** WH8. The right-hand group, `.top-right` (mh:70, mh:102): pushed to the
     *  right end, vertically centred, 14px gap. */
    right: "gap-3.5",
    /** WH9. SFW, `.sfw` (mh:71): the label above the switch, centred, 3px
     *  apart. */
    sfw: "gap-0.75",
    /** WH10. The SFW label, `.sfw span` (mh:72): 10px / 600, letter-spacing
     *  .5px. */
    sfwLabel: "text-[10px] font-semibold tracking-[.5px]",
    /** WH11. The on/off switch's track, `.switch` (mh:73): 26×14px, radius 8px.
     *  Drawn by `SwitchTrack` (the Window header's SFW, the Fan List's rail switch). */
    switch: "w-6.5 h-3.5 rounded-lg",
    /** WH12. The knob, `.switch:before` (mh:74): a 10px circle 2px from the
     *  top and from the left (off). */
    switchKnob: "top-0.5 left-0.5 size-2.5 rounded-full",
    /** WH13. The knob's place when on: 12px further right, 2px from the
     *  right (spec D10; the Clone draws only the off state). */
    switchKnobOn: "translate-x-3",
  },
  /** Creator tabs (CT). */
  creatorTabs: {
    /** CT1. The strip, `.ctabs` (mh:332-333): a row 4px apart, bottom-aligned,
     *  capped at 58vw and scrolling sideways with no visible scrollbar, so SFW
     *  never leaves the row. */
    strip: "gap-1 max-w-[58vw]",
    /** CT2. A Creator tab, `.ctab` (mh:56-58, mh:105, mh:334): 36px tall,
     *  padding 0 10px 0 6px, 8px gap, radius 9px 9px 0 0, at most 220px, a 1px
     *  border with no bottom edge, never shrinking. It holds the tab's pick
     *  target (`tabPick`) and its ✕ (`close`) side by side. */
    tab: "gap-2 h-9 pl-1.5 pr-2.5 max-w-55 rounded-t-[9px] border border-b-0",
    /** CT3. The active tab's 2px top line, drawn inside (`.ctab.active`,
     *  mh:336). */
    tabActive: "inset-shadow-[0_2px_0]",
    /** CT4. The avatar, `.ctab .cav` (mh:60, mh:340): 26×26px, radius 6px;
     *  its initials fallback inherits 11px / 800. */
    avatar: "size-6.5 rounded-md text-[11px] font-extrabold",
    /** CT5. The name, `.ctab .cname` (mh:62): 13px / 700, one line with an
     *  ellipsis inside the tab's 220px. */
    name: "text-[13px] font-bold",
    /** CT6. An unread badge, `.mini-badge` (mh:63-64): at least 16px wide, 16px
     *  tall, padding 0 4px, a pill (Infloww's radius 22px, REA §1.7 "Message
     *  unread"), 10px / 700. The Creator tab's unread total and its
     *  notifications count, and the Fan tab's unread count (spec, Gap table
     *  ASSUMPTION), all through `UnreadMiniBadge.tsx`. */
    badge: "min-w-4 h-4 px-1 rounded-full text-[10px] font-bold",
    /** CT7. The tab's ✕, `.ctab .cclose` (mh:67, mh:345): 16×16px, 2px left
     *  margin; the glyph inherits the Clone's 14px / 1.4 body (mh:37). */
    close: "size-4 ml-0.5",
    /** CT8. The strip's empty text, `.ctabs-empty` (mh:358): 12px at the
     *  inherited 1.4, padding 0 10px. Rendered right after the (then empty)
     *  strip. */
    empty: "px-2.5 text-[12px]",
  },
  /** Fan tabs (FT). */
  fanTabs: {
    /** FT1. The Fan tabs row, `.hometabs` (mh:82), at Infloww's 32px
     *  (2026-10-18 capture; the Clone's 34px) even when empty, Home first at
     *  its start (WH2), children bottom-aligned, 1px bottom border. */
    bar: "h-8 min-h-8 pr-3.5 border-b",
    /** FT2. The Fan tabs strip, `.hometabs .thread-tabs` (mh:108-109) over
     *  `.thread-tabs` (mh:194): tabs 3px apart, 4px from the row's start,
     *  taking the row's width, bottom-aligned, scrolling sideways. */
    strip: "gap-0.75 ml-1",
    /** FT3. A Fan tab, `.ttab` (mh:195): 8px gap, a 1px border with no bottom
     *  edge, radius 8px 8px 0 0, padding 7px 11px, 12.5px / 600 at the Clone's
     *  1.4 line height (mh:37), one line, at most 190px, never shrinking (the
     *  strip scrolls instead). It holds the tab's pick target (`tabPick`) and
     *  its ✕ (`close`) side by side. */
    tab: "gap-2 py-1.75 px-2.75 max-w-47.5 rounded-t-lg border border-b-0 text-[12.5px] font-semibold leading-[1.4]",
    /** FT4. The active tab's 2px top line, drawn inside (`.ttab.active`,
     *  mh:197). */
    tabActive: "inset-shadow-[0_2px_0]",
    /** FT5. The online dot, `.ttab-dot` (mh:110): 7×7px, round, first in the
     *  tab, beside its pick target. */
    dot: "size-1.75 rounded-full",
    /** FT6. The tab's ✕, `.ttab-x` (mh:199-200): 11px at line height 1,
     *  radius 4px, padding 2px 4px. */
    close: "px-1 py-0.5 rounded-sm text-[11px] leading-none",
  },
  /** Fan List (FL). */
  fanList: {
    /** FL1: the Fan List header, 52px with its 1px divider, 11px in and
     *  12px from the right, icons 12px apart (2026-10-18 capture; the
     *  Clone's `.list-head`, mh:117, had no divider). */
    head: "h-13 pl-2.75 pr-3 gap-3 border-b",
    /** FL2: the title, 20px / 500 (2026-10-18 capture; the Clone's 22px/700,
     *  mh:118). */
    title: "text-[20px] font-medium",
    /** FL3: `.icon-btn` 26×26, radius 7px (mh:77). */
    iconButton: "size-9 md:size-6.5 rounded-[7px]",
    /** FL4: `.list-head .icon-btn svg` 20px (mh:119). */
    iconButtonIcon: "size-5",
    /** Compare FL9: the header's gallery icon, first of gallery, search and
     *  "+" (mh:628), at search's sizes (FL3, its svg FL4): the phone tap
     *  size, then `.icon-btn` 26×26, radius 7px. */
    gallery: "size-9 md:size-6.5 rounded-[7px]",
    /** FL5. The Fan List buttons row (2026-10-18 capture; the Clone's
     *  `.big-btns`, mh:122): 18px under the header's divider, 10px from the
     *  pane's sides and from the filters, buttons 28px apart. The
     *  Notifications panel opens against it. */
    buttons: "gap-7 pt-4.5 px-2.5 pb-2.5",
    /** FL6. A Fan List button (2026-10-18 capture; the Clone's 42px,
     *  mh:123): 28px tall, radius 4px, the icon and label 6px apart, 14px /
     *  500. */
    button: "h-7 gap-1.5 rounded-sm text-[14px] font-medium",
    /** FL7. Its icon (2026-10-18 capture; the Clone's 18px, mh:126): 16px. */
    buttonIcon: "size-4",
    /** FL8. Notifications' count badge (2026-10-18 capture; the Clone's
     *  `.notif-badge`, mh:127-128): 10px above and 10px past the button's
     *  top right corner, at least 20px wide, 20px tall, 6px sides, round,
     *  13px / 500, a 1px ring (its colour, the label's, in JSX). */
    notifBadge: "-top-2.5 -right-2.5 min-w-5 h-5 px-1.5 rounded-full text-[13px] font-medium border",
    /** FL9. Online Fans while on (messages.js:3103-3107): a 2px ring, added
     *  only while pressed. */
    buttonPressed: "ring-2",
    /** FL10: `.filter-row` gap 10px, wraps with row-gap 6px (mh:130,
     *  mh:357); 11px sides and 0 top as Infloww (2026-10-18 capture). */
    filters: "gap-x-2.5 gap-y-1.5 px-2.75 pb-3",
    /** FL11: `.inbox-box` gap 8px, border 1px, padding 0 11px, min-width
     *  150px (mh:131, mh:354); 34px tall, radius 4px, 14px as Infloww
     *  (2026-10-18 capture). */
    inbox: "gap-2 px-2.75 h-8.5 rounded-sm text-[14px] min-w-37.5 border",
    /** FL12: `.inbox-box svg` 16px (mh:132). */
    inboxIcon: "size-4",
    /** FL13: the gear, 36×34, radius 4px (2026-10-18 capture; the Clone's
     *  34×34 at 8px, mh:134). */
    gear: "w-9 h-8.5 rounded-sm",
    /** FL14: `.gear svg` 19px (mh:136). */
    gearIcon: "size-4.75",
    /** FL15: `.sortline` gap 9px (mh:137), 14px as Infloww (2026-10-18
     *  capture). */
    sort: "gap-2.25 text-[14px]",
    /** FL16: `.sortline svg` 17px (mh:139). */
    sortIcon: "size-4.25",
    /** FL17: `.chips` padding-bottom 12px (mh:141); 10px apart and 11px
     *  sides as Infloww (2026-10-18 capture). */
    chips: "gap-2.5 px-2.75 pb-3",
    /** FL18: a chip, 26px tall from md, 12px sides, radius 16px, 14px / 400
     *  (2026-10-18 capture; the Clone's `.chip`, mh:143, 13px/500). */
    chip: "px-3 py-1.5 min-h-[36px] md:h-6.5 md:py-0 md:min-h-0 rounded-2xl text-[14px]",
    /** FL19: a chip's corner badge, 8px above and 6px past its corner, a
     *  16px circle, 11px / 500 (2026-10-18 capture; the Clone's `.cbadge`,
     *  mh:145). */
    chipBadge: "-top-2 -right-1.5 min-w-4 h-4 px-0.75 rounded-full text-[11px] font-medium",
    /** FL21: `.fchip` gap 6px, padding 6px 13px, 12.5px/500, radius 16px,
     *  border 1px (mh:148-149). */
    folderChip: "gap-1.5 px-3.25 py-1.5 rounded-2xl text-[12.5px] font-medium border",
    /** FL23 (Compare FL7, ticket 137). A row, from the 2026-10-12 capture
     *  (CSS px), which outranks the Clone's 75px `.conv` (mh:159): a 96px
     *  pitch with its 1px divider, the avatar 16px under the divider and 19px
     *  in, the text 10px past it, 19px clear of the right edge. The divider
     *  starts 60px in, under the text column, and stops 9px short of the
     *  pane's right edge (2026-10-18 capture, x 81-517 of 531 at 1.32;
     *  page-parity 07 FL16); its colour is in JSX. */
    row: "h-24 gap-2.5 px-4.75 pt-4 after:absolute after:bottom-0 after:left-15 after:right-2.25 after:h-px",
    /** FL24 (Compare FL1): the capture's 40px avatar, round; initials at the
     *  Clone's 13px/700 (mh:163). */
    avatar: "size-10 rounded-full text-[13px] font-bold",
    /** FL25: `.av svg` 22px (mh:168). */
    avatarIcon: "size-5.5",
    /** FL26 (Compare FL1): the capture's online dot, 8px with a 1px ring,
     *  flush with the avatar's bottom-right edge. */
    onlineDot: "bottom-0 right-0 size-2.5 rounded-full border",
    /** FL27 (Compare FL1): the capture's spend pill, 4px under the avatar and
     *  centred on it, 16px tall, 4px sides, radius 2px, 13px / 700
     *  (2026-10-18 capture; the Clone's 11px, mh:171). */
    spend: "top-full left-1/2 -translate-x-1/2 mt-1 h-4 px-1 rounded-xs text-[13px] leading-4 font-bold",
    /** FL28: `.conv-top` gap 5px (mh:174). */
    top: "gap-1.25",
    /** FL29: `.cname` max-width 170px (mh:175), 15px / 500 as Infloww
     *  (2026-10-18 capture). */
    name: "text-[15px] font-medium max-w-42.5",
    /** FL30: `.chandle` (mh:176), 15px as Infloww (2026-10-18 capture). */
    handle: "text-[15px]",
    /** Compare FL2: the verified badge between the name and the @handle,
     *  `.vf` 14×14 (mh:177). */
    verified: "size-3.5",
    /** Compare FL3: the ✕ at line one's right end, `.cx` 16px on one line
     *  (mh:178). */
    notWired: "text-[16px] leading-none",
    /** FL31: `.off-label` margin-top 3px, 11px/800, letter-spacing .5px
     *  (mh:179). */
    offLabel: "mt-0.75 text-[11px] font-extrabold tracking-[.5px]",
    /** FL32: `.fx-new` 9px/700, letter-spacing .03em, padding 2px 6px, radius
     *  5px (`kit:188-189`). */
    newBadge: "px-1.5 py-0.5 rounded-[5px] text-[9px] font-bold tracking-[.03em]",
    /** FL33: `.conv-bot` gap 6px (mh:181); the capture's preview line starts
     *  40px under line one's top, 20px under line one (Compare FL4). */
    bottom: "gap-1.5 mt-5",
    /** FL34: `.cprev` gap 5px (mh:182), 14px as Infloww (2026-10-18
     *  capture). */
    preview: "gap-1.25 text-[14px]",
    /** FL35: `.cprev.bold` 600 (mh:183). */
    previewUnread: "font-semibold",
    /** FL37: `.ctime` (mh:185), 14px as Infloww (2026-10-18 capture). */
    time: "text-[14px]",
    /** FL38: `.ud` 9×9, round (mh:187). */
    unreadDot: "size-2.25 rounded-full",
    /** FL39: `.owe-dot` 9×9, round, 2px halo (mh:188-189). */
    oweDot: "size-2.25 rounded-full ring-2",
    /** Compare FL8: the unread or owe dot as an Edge marker, centred in the
     *  row's 19px left padding and on the avatar's centre, 36px down. */
    edgeMarker: "left-1.25 top-9 -translate-y-1/2",
    /** All Models' Creator colour dot, today's 8px with its 1px border, moved
     *  into the left padding level with the avatar's top, above the Edge
     *  marker, so the avatar stays 19px in (Compare FL1). */
    accountDot: "left-1.5 top-4 size-2 rounded-full border",
    /** FL40: `.mute-i` 14×14 (mh:190). */
    muteIcon: "size-3.5",
    /** FL41: Empty state padding 24px 16px, 13px (`m.js:481-482`). */
    empty: "px-4 py-6 text-[13px]",
    /** FL42: a skeleton row as tall as a row (FL23, Compare FL7), with its
     *  sides and gap. */
    skeletonRow: "h-24 gap-2.5 px-4.75 border-b",
    /** FL43: the row's 40px avatar, round (FL24). */
    skeletonAvatar: "size-10 rounded-full",
    /** FL44: `.skel-lines` gap 10px (mh:568). */
    skeletonLines: "gap-2.5",
    /** FL45: `.skel-bar` height 11px, radius 6px (mh:569). */
    skeletonBar: "h-2.75 rounded-md",
    /** FL46: `.skel-bar.w1` 52% (mh:570). */
    skeletonBarShort: "w-[52%]",
    /** FL47: `.skel-bar.w2` 78% (mh:571). */
    skeletonBarLong: "w-[78%]",
    /** FL48: `.load-more` padding 14px 16px, 13px/600, border-top 1px
     *  (mh:155-156). */
    loadMore: "px-4 py-3.5 text-[13px] font-semibold border-t",
    /** FL49: `.fx-note` gap 10px, border 1px, radius 10px, padding 11px 14px,
     *  13px, line-height 1.5 (`kit:191-192`). */
    focusBanner: "gap-2.5 px-3.5 py-2.75 rounded-[10px] text-[13px] leading-normal border",
    /** FL50: `.fx-select` height 38px, border 1px, radius 9px, 13.5px, padding
     *  0 12px (`kit:106-107`), and padding-right 32px for its chevron
     *  (`kit:108-110`). */
    splitSelect: "h-9.5 pl-3 pr-8 rounded-[9px] text-[13.5px] border",
  },
  /** Chat header (CH). */
  chatHeader: {
    /** Compare CH1 (ticket 141; the real Infloww thread capture of 2026-10-12
     *  wins over the Clone's one-line `.thread-head`, mh:201): the Chat header
     *  Region, Infloww's two lines. A grid (JSX): the back control, the
     *  name's column (as wide as the presence line), the rest of line 1 and
     *  line 2, then the right group; the lines 4px apart. From md up 52px tall
     *  with 20px side padding and the lines centred on it; below md today's
     *  12px sides (spec F14), 4px top and bottom, at least 52px. A 1px bottom
     *  border. */
    bar: "grid-cols-[auto_auto_minmax(0,1fr)_auto] gap-y-1 min-h-13 px-3 py-1 md:h-13 md:px-5 md:py-0 border-b",
    /** Compare CH1, CH6: the back arrow, 20px, at every width as Infloww's
     *  "←" (2026-10-18 capture: x 556-582 / 1.32); at lg it clears the open
     *  Fan as on a phone. */
    back: "size-5",
    /** Compare CH1: the back control's 36px target, pulled 10px into the
     *  padding so the chevron starts at the Region's padding edge, and 13px
     *  from the chevron to the name; radius 8px. */
    backButton: "size-9 -ml-2.5 mr-0.75 rounded-lg",
    /** Compare CH1: line 1's name and verified badge, 6px apart. */
    nameRow: "gap-1.5",
    /** Compare CH1: the Fan's name, 18px semibold on a 24px line (JSX: one
     *  line with an ellipsis). */
    name: "text-[18px] font-semibold leading-6",
    /** Compare CH1: the verified badge, a 10px glyph. */
    verified: "size-2.5",
    /** Compare CH1 (ticket 142): the edit pencil after the name, a 14px icon
     *  (a 12px glyph, 1px inset); also the slot the name row keeps for it. */
    editName: "size-3.5",
    /** Compare CH1: the slot's place, so the pencil's glyph sits 6px after
     *  the name (`nameRow`'s gap less the 1px inset) or, after the verified
     *  badge, 9px after it (the gap, 2px more and the inset). */
    editNameSlot: "-ml-px",
    editNameAfterBadge: "ml-0.5",
    /** The pencil's button over its slot: 5px past each side, a 24px target
     *  (WCAG 2.5.8) that leaves the drawn spacing alone. */
    editNameTarget: "-inset-1.25",
    /** Compare CH3: the presence line, line 2's start: the dot 6px before the
     *  10px text, on a 14px line (JSX: one line, the text ends in an
     *  ellipsis). */
    status: "gap-1.5 text-[10px] leading-3.5",
    /** Compare CH3: the presence dot, 6px, round. */
    statusDot: "size-1.5 rounded-full",
    /** Compare CH3: line 2's icon row after the presence line, 14px tall (JSX:
     *  one line that never wraps). */
    tools: "h-3.5",
    /** Compare CH3: the divider before each of line 2's items, 1px × 12px with
     *  10px either side, 11px from each 12px glyph in its 14px box, so the
     *  icons sit 35px apart. */
    divider: "w-px h-3 mx-2.5",
    /** Compare CH3: star, bell, notes and pin, a 14px icon (a 12px glyph). */
    lineIcon: "size-3.5",
    /** Line 2's buttons (star, bell, notes, pin, "Gallery", "Find"): 5px
     *  padding pulled back by a 5px negative margin, so each is at least a
     *  24px target (WCAG 2.5.8) above the "Avatar menu" button under it while
     *  the drawn spacing (11px from each glyph to a divider) is unchanged. */
    lineTarget: "p-1.25 -m-1.25",
    /** CH10. An icon button, `.icon-btn` (mh:77): 30×30px, radius 7px; JSX
     *  centres the icon. The right group's refresh. */
    iconButton: "size-7.5 rounded-[7px]",
    /** Compare CH2 (was CH11's 19px, mh:212): refresh's icon, 16px (a 14px
     *  glyph). Also the Fan insights toggle's. */
    iconButtonIcon: "size-4",
    /** Compare CH3: a label button ("Gallery", "Find"): the icon 3px before the
     *  10px word (5px from the glyph), on line 2's 14px line (JSX: one line). */
    label: "gap-0.75 text-[10px] leading-3.5",
    /** Compare CH3: its icon, 13px (an 11px glyph, the capture's 10.5px; ticket 151). */
    labelIcon: "size-3.25",
    /** Compare CH3 (was CH14, spec D4): the word of "Gallery", "Find" and "Open
     *  in new tab": screen-reader text only while the Thread, a size
     *  container, is narrower than 448px, so the button shows its icon and
     *  keeps its name; shown at 448px and up (at 1440 with Fan insights open,
     *  folded in a 390px phone Thread). */
    labelText: "sr-only @min-[448px]:not-sr-only",
    /** CH15. The right group, `.th-right` (mh:216): 4px apart (JSX: line 1's
     *  end, centred on the Region from md up). Order: "Open in new tab",
     *  refresh, Fan insights, the kebab (spec H9 to H11, H15). */
    right: "gap-1",
    /** CH16. "Open in new tab", `.open-new` (mh:217): the icon and label 6px
     *  apart (7px from the glyph, Compare CH2), 13px / 600 (the accent colour
     *  in JSX), padding 6px 8px, radius 7px. JSX keeps it on one line and
     *  hides it below md (spec F14). */
    openNew: "gap-1.5 py-1.5 px-2 rounded-[7px] text-[13px] font-semibold leading-[1.4]",
    /** Compare CH2 (was CH17's 16px, mh:218): its icon, 14px (a 12px glyph). */
    openNewIcon: "size-3.5",
    /** Compare CH2: from md up the kebab's 30px target reaches 14px into the
     *  padding, so its dots end 20px from the pane edge. */
    kebab: "md:-mr-3.5",
    /** Compare CH2: the kebab's icon, 19px (its dots 14px tall as drawn). */
    kebabIcon: "size-4.75",
  },
  /** Menus, `.pop` (MN): every Messages Pro menu. */
  menu: {
    /** MN1. Every Chat header menu (the 📈 menu, the Avatar menu, the Extras
     *  overflow and the Kebab menu, spec M1), from ticket 91 on, and the
     *  Window header's (the Creator picker, the Extras overflow and "Open in
     *  a new window"), from ticket 112 on. Its box,
     *  `.pop` (mh:361-363): at least 238px and at most 360px wide, at most 72vh
     *  tall (scrolling past it), radius 10px, padding 6px, 13px text, a 1px
     *  border. Colours, the scroll past 72vh and the shadow stay in the JSX
     *  (ADR-0001; `MENU_PANEL`, `MenuParts.tsx`); each menu adds its own
     *  position. */
    panel: "min-w-59.5 max-w-90 max-h-[72vh] rounded-[10px] p-1.5 text-[13px] border",
    /** MN2. A Chat header menu row, `.pop .prow` (mh:364): 9px gap, padding 8px
     *  10px, radius 7px, line height 1.3 (JSX: full width, `MENU_ROW`). Below
     *  md it keeps today's 12px top and bottom touch padding (spec F14). */
    row: "gap-2.25 px-2.5 py-3 md:py-2 rounded-[7px] leading-[1.3]",
    /** MN3. A Chat header menu heading, `.pop .phead` (mh:370): 10.5px / 700,
     *  letter-spacing .5px, padding 8px 10px 4px (JSX: uppercase). */
    head: "px-2.5 pt-2 pb-1 text-[10.5px] font-bold tracking-[.5px]",
    /** MN4. A Chat header menu divider, `.pop .pdiv` (mh:371): 1px, margin 5px
     *  2px. */
    divider: "h-px mx-0.5 my-1.25",
    /** MN5. A Creator picker row's avatar, `.pop .pav` (mh:373-374): 22×22px,
     *  radius 5px; its initials fallback inherits 9px / 800. */
    avatar: "size-5.5 rounded-[5px] text-[9px] font-extrabold",
    /** MN6. A row's "open" / "add", `.pop .pmeta` (mh:376): 11px (JSX pushes
     *  it to the right end). */
    meta: "text-[11px]",
  },
  /** Sheets (SH): the Chat gallery, and the Vault picker through class-name props. */
  sheet: {
    /** SH1. `.sheet` (mh:383): min(900px, 92vw) wide, at most 84vh tall, radius
     *  14px, a 1px border, from md up. Below md JSX makes it the whole screen
     *  (spec F14), so the Clone's values sit under `md:`. JSX makes it a column
     *  that clips. */
    panel: "md:w-[min(900px,92vw)] md:max-h-[84vh] md:rounded-[14px] md:border",
    /** SH2. `.sheet-h` (mh:385): a row (in JSX) 10px apart, padding 13px 16px,
     *  14px / 700, a 1px bottom border. */
    head: "gap-2.5 px-4 py-3.25 text-[14px] font-bold border-b",
    /** SH2, the Vault picker's from md up (spec P4 row 25): the head row's
     *  13px padding on its own row (its 16px sides and bottom line are the
     *  picker's at every width), and the type on its title. Below md the
     *  picker keeps its full-screen pane. */
    pickerHead: "md:py-3.25",
    pickerTitle: "md:text-[14px] md:font-bold",
    /** SH3. `.sheet-h .x` (mh:386): padding 2px 6px, radius 6px, 17px at line
     *  height 1. The title's auto margin pushes it (and "↻ Refresh") right. */
    close: "px-1.5 py-0.5 rounded-md text-[17px] leading-none",
    /** SH4. `.sheet-b` (mh:388): padding 14px 16px, at least 90px tall, 13px
     *  (JSX: it takes the rest of the sheet and scrolls). */
    body: "py-3.5 px-4 min-h-22.5 text-[13px]",
    /** SH5. `.mgrid` (mh:390): a grid (in JSX) of square tiles at least 118px
     *  wide, 10px apart. */
    grid: "grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2.5",
    /** SH5, the Vault picker's from md up (P4 row 26); below md it keeps
     *  its 3 and 4 columns. */
    pickerGrid: "md:grid-cols-[repeat(auto-fill,minmax(118px,1fr))] md:gap-2.5",
    /** SH6. `.mgrid .mt` (mh:391): radius 9px, a 1px border (JSX: square,
     *  clipped). */
    tile: "rounded-[9px] border",
    /** SH6, the Vault picker's from md up (P4 row 26): the radius only, since
     *  its tiles draw their own 2px status ring. */
    pickerTile: "md:rounded-[9px]",
    /** SH7. `.mgrid .mt .tag` (mh:393): the price, 6px in from the bottom left,
     *  radius 6px, padding 2px 6px, 10.5px / 700. */
    tileTag: "left-1.5 bottom-1.5 rounded-md py-0.5 px-1.5 text-[10.5px] font-bold",
  },
  /** Message list (ML). */
  messageList: {
    /** ML1. The message list, `.thread-body` (mh:220): a column (JSX: `flex
     *  flex-col`), from md up padding 22px 26px and a 14px gap between
     *  messages. Below md it keeps today's 12px 8px and 8px (spec L1, F25). */
    body: "px-2 py-3 gap-2 md:px-6.5 md:py-5.5 md:gap-3.5",
    /** ML2. A bubble's column (the bubble, the PPV status line and our status
     *  row), `.bubble` (mh:243): at most 60% of the list from md up, today's
     *  88% below md (spec L2, F25). */
    bubbleColumn: "max-w-[88%] md:max-w-[60%]",
    /** ML3. A bubble (Phase 4 spec T10, from the Infloww capture): from md up
     *  radius 6px, padding 10px, 16px text on a 20px line. Below md today's
     *  16px radius, 8px 12px padding and 14px. */
    bubble: "rounded-2xl px-3 py-2 text-sm md:rounded-[6px] md:px-2.5 md:py-2.5 md:text-base md:leading-5",
    /** ML4. The Fan's tail corner (T10): square bottom left from md up,
     *  today's 6px below md. */
    bubbleTailIn: "rounded-bl-md md:rounded-bl-none",
    /** ML5. Our tail corner (T10): square bottom right from md up. */
    bubbleTailOut: "rounded-br-md md:rounded-br-none",
    /** ML6. The time row under a run's last bubble (T12), 11px: from md up 6px
     *  under the bubble (the column's 4px gap, `MP.ours.MessageList.column`,
     *  and 2px) on a 14px line, 20px in all; below md today's 5px (9px with
     *  the gap) on a 15px line, 24px in all. */
    time: "mt-1.25 text-[11px] leading-[15px] md:mt-0.5 md:leading-[14px]",
    /** ML7. A receipt in the time row, `.seen-tick` (mh:261): ✓ or ✓✓ at 10px,
     *  5px after the time (spec L4). */
    seen: "ml-1.25 text-[10px]",
    /** ML8. "Sent by <name>" in the time row, `.sent-by` (mh:262): 10px / 700,
     *  7px after the time (JSX: one line; spec L5). */
    sentBy: "ml-1.75 text-[10px] font-bold",
    /** ML9. The empty conversation, `.msg-meta` (mh:241): 12.5px (spec L8). */
    meta: "text-[12.5px]",
    /** ML10: `.ppv-mini` radius 14px, padding 14px 16px, max-width 320px,
     *  column gap 8px, border 1px (mh:248; in the screenshot build at
     *  `orig:203`). */
    ppv: "max-w-80 gap-2 px-4 py-3.5 rounded-[14px] border",
    /** ML11: `.ppv-mini .pm-title` 600 (mh:249). */
    ppvTitle: "font-semibold",
    /** ML12. A PPV's status line, `.ppv-mini .paid-tag` (m.html:250): 12px /
     *  600 (spec L6). */
    paidTag: "text-[12px] font-semibold",
    /** ML14. The Bubble action row beside an incoming bubble (Phase 4 spec
     *  T1, from the Infloww capture): its first glyph 9px after the bubble,
     *  each glyph on a 20px pitch (16px boxes 4px apart) from md up. Below md
     *  the 24px boxes touch, the first glyph still 9px out (story 7). */
    actionsIn: "ml-0.75 md:ml-1.75 md:gap-1",
    /** ML15. The row before our bubble (T2): translate, then ⋮ with its dots
     *  10px from the bubble and 15px after translate's glyph. */
    actionsOut: "md:mr-0.75 md:gap-1.5",
    /** ML16. One action's box: a 24px target below md (story 7), 16px from md
     *  up (T1). */
    action: "size-6 rounded md:size-4",
    /** ML17. Its line glyph: 14px, which draws about 12px (T1). */
    actionIcon: "size-3.5",
    /** ML18: `.load-older` margin 2px 0 8px, padding 7px 16px, radius 99px,
     *  12.5px/600, border 1px (mh:532-533). */
    loadOlder: "mt-0.5 mb-2 px-4 py-1.75 rounded-full text-[12.5px] font-semibold border",
    /** ML19: `.pinbar` gap 8px, padding 7px 18px, 12px, border-bottom 1px
     *  (mh:538-539). */
    pinBar: "gap-2 px-4.5 py-1.75 text-[12px] border-b",
    /** ML20: `.pinbar svg` 14px (mh:541). */
    pinBarIcon: "size-3.5",
    /** ML21: `.pinbar .pincount` 700 (mh:543). */
    pinCount: "font-bold",
    /** ML22. A Date divider (Phase 4 spec T4, from the Infloww capture): the
     *  label centred in 12px of space on each side of it (JSX: a row of two
     *  1px lines and the label). */
    divider: "gap-3",
    /** ML23. Its label: about 11px, sentence case (T4). */
    dividerLabel: "text-[11px]",
    /** ML24. A run's avatar on its last bubble line, and the spacer that
     *  lines up the run's earlier bubbles: a 36px circle (T5, T6, F6). */
    avatar: "size-9 rounded-full",
    /** ML25. The Fan's avatar, 8px before the bubble, bottom-aligned (T5). */
    avatarIn: "mr-2",
    /** ML26. Ours, 8px after the bubble (T6). */
    avatarOut: "ml-2",
    /** ML27. The person glyph in ours without a picture: drawn about 15px
     *  wide and 16px tall (T6). */
    avatarGlyph: "size-5.5",
    /** ML28. A run's later bubble line (T11): 2px under the line before it
     *  from md up (the list's 14px gap, ML1, less 12px), so runs stay 14px
     *  apart. Below md the list's 8px stays. */
    runGap: "md:-mt-3",
    /** ML29. The room the time row (ML6) takes under a run's last bubble:
     *  the Fan's avatar and the Bubble action row keep it below them, so they
     *  stay level with and centred on the bubble, not the time row (T5, T1). */
    timeRoom: "mb-6 md:mb-5",
  },
  /** Composer (CP), the reply strip included. */
  composer: {
    /** CP1, look-and-feel C1: the capture's 1px top rule, row 1 starting at
     *  it with no top padding; the side padding is each row's own. The
     *  safe-area bottom keeps row 3 above iOS Safari's home-indicator bar. */
    root: "pb-[env(safe-area-inset-bottom)] border-t",
    /** CP2, look-and-feel C2 and C3: row 1, "Composer buttons", 44px tall
     *  with 12px side padding and a 1px full-width rule under it (JSX: one
     *  line that never wraps, no input); emoji and ⚙ 5px apart at its left. */
    buttonRow: "h-11 px-3 gap-1.25 border-b",
    /** Look-and-feel C4: row 1's right group (JSX: pushed to the end): AI,
     *  Scripts and PPV 8px apart, "+" 8px after ⏱. */
    buttonRowEnd: "gap-2",
    /** Look-and-feel C4: ⏱ 17px after PPV (the group's 8px plus 9px). */
    timed: "ml-2.25",
    /** CP3: `.icon-btn` 26×26, radius 7px (mh:77). */
    buttonRowButton: "size-6.5 rounded-[7px]",
    /** CP4: `.comp-r1 .icon-btn svg` 20px (mh:272); a 20px lucide icon draws
     *  the capture's ≈17px glyph (look-and-feel C3). */
    buttonRowIcon: "size-5",
    /** CP5, look-and-feel C5: the capture's flat pill (AI, Scripts and PPV):
     *  26px tall, padding 0 8px, 6px icon–label gap, radius 3px, 14px label,
     *  no border; 400, the capture's regular strokes (the spec ASSUMPTION's
     *  visual loop read, ticket 147; it was the parent's 600). */
    pill: "h-6.5 gap-1.5 px-2 rounded-[3px] text-sm font-normal",
    /** Look-and-feel C5, the row-1 label threshold beside the pill: a pill's
     *  word is screen-reader text only while the Thread, a size container, is
     *  narrower than 480px (row 1's labelled width, spec ASSUMPTION), so row 1
     *  never wraps on a phone and the button keeps its name; shown from 480px
     *  up (as `chatHeader.labelText`). */
    pillLabel: "sr-only @min-[480px]:not-sr-only",
    /** CP6, look-and-feel C5: the pill's icon, 16px. */
    pillIcon: "size-4",
    /** CP7, look-and-feel C6: row 2, the input alone, padding 16px, 16px text
     *  on a 20px line (`._editor-content` padding 16px 16px). It grows with
     *  the text (JSX), its height including the padding. */
    input: "p-4 text-base leading-5",
    /** CP8, look-and-feel C7: row 3, `.comp-r2` gap 6px (mh:280), so 34px
     *  boxes on a 40px pitch; padding 16px top, bottom and left, 14px right. */
    toolbar: "gap-1.5 py-4 pl-4 pr-3.5",
    /** CP9: `.comp-r2 .icon-btn` 34×34 (mh:281), radius 7px (mh:77). */
    toolbarButton: "size-8.5 rounded-[7px]",
    /** CP10: `.comp-r2 .icon-btn svg` 20px (mh:282). */
    toolbarIcon: "size-5",
    /** CP11, look-and-feel C8: Send, 32px tall, 19px side padding (72px wide
     *  with "Send"), fully round, 16px at 400, the capture's regular strokes
     *  (the spec ASSUMPTION's visual loop read, ticket 147; it was 700). */
    send: "h-8 px-4.75 rounded-full text-base font-normal",
    /** CP12: the Aa button (`cbAa`) 800 15px (markup mh:761). */
    aa: "text-[15px] font-extrabold",
    /** CP13. The reply strip, `.reply-strip` (mh:525-530, spec L10): one line
     *  (JSX: a centred flex row), 9px gap, padding 8px 12px, 8px under it, 3px
     *  left border, radius 8px, 13px. */
    replyStrip: "gap-2.25 px-3 py-2 mb-2 border-l-3 rounded-lg text-[13px]",
    /** CP14. The ↩ icon, `.reply-strip svg` (mh:527): 15px (JSX: it never
     *  shrinks). */
    replyStripIcon: "size-3.75",
    /** CP15. ✕ "Cancel reply", `.rs-x` (mh:529): 22×22, radius 6px, a 14px
     *  glyph (JSX: centred, it never shrinks). */
    replyStripClose: "size-5.5 rounded-md text-[14px]",
  },
  /** PPV row (PV). */
  ppvRow: {
    /** PV1, look-and-feel C11: the PPV row in Infloww's input typography,
     *  `._online-input-price` 14px at 140%, with 16px side padding (it sits
     *  between row 2 and row 3, C10, and the Composer root has none, C1);
     *  `.comp-x` gap 8px and padding 0 0 8px (mh:514). */
    row: "gap-2 px-4 pb-2 text-sm leading-[1.4]",
    /** PV2: "PPV" label, 700 (markup mh:739-753). */
    label: "font-bold",
    /** PV3: "$" with its input, and the checkbox with "lock text", each gap 5px
     *  (markup mh:739-753). */
    group: "gap-1.25",
    /** PV4, look-and-feel C11: a field, border 1px, Infloww's input radius
     *  4px (`._online-input`), 14px at 140% (`._online-input-price`) from md
     *  up; below md it keeps today's 16px, so iOS does not zoom into the field
     *  (as CP7). Padding 5px 8px, so the field is ant-design's 32px tall at
     *  14px (spec ASSUMPTION). Also the Timed message's minutes. */
    input: "px-2 py-1.25 rounded-[4px] text-base md:text-sm leading-[1.4] border",
    /** PV5, look-and-feel C11: the price field's box,
     *  `._online-input-price .ant-input-number-affix-wrapper`: 85px wide, its
     *  `$` prefix inside 5px in, then 10px to the digits
     *  (`.ant-input-number-prefix` margin-right 10px). */
    price: "w-21.25 pl-1.25 gap-2.5",
    /** PV6: `.btn-sm` radius 7px, padding 7px 12px, 12.5px/600 (mh:499). */
    clear: "px-3 py-1.75 rounded-[7px] text-[12.5px] font-semibold",
    /** PV8: `.att .a` 42×42, radius 7px, border 1px (mh:520). */
    attachment: "size-10.5 rounded-[7px] border",
    /** PV9: `.att .a b` 10px, padding 0 4px, bottom-left radius 5px (mh:522). */
    attachmentRemove: "px-1 text-[10px] rounded-bl-[5px]",
  },
  /** Fan insights (FI). */
  insights: {
    /** FI1: `.right-head` padding 16px 16px 10px, 16px/700 (mh:293). */
    head: "px-4 pt-4 pb-2.5 text-[16px] font-bold",
    /** FI2: `.right-body` padding 0 12px 12px, gap 12px (mh:294). */
    body: "px-3 pb-3 gap-3",
    /** FI3: `.card` border 1px, radius 12px, padding 14px (mh:295). */
    block: "p-3.5 rounded-xl border",
    /** FI4: `.card-head` gap 8px, margin-bottom 12px (mh:296). */
    blockHead: "gap-2 mb-3",
    /** FI5: `.drag svg` 14px (mh:298). */
    dragIcon: "size-3.5",
    /** FI6: `.card-head .ct` 14px/600 (mh:299). */
    blockTitle: "text-[14px] font-semibold",
    /** FI7: `.card-head .chev svg` 15px (mh:301). */
    chevron: "size-3.75",
    /** FI8: `.mrow` padding 6px 0 (mh:310). */
    metric: "py-1.5",
    /** FI9: `.mrow .k` 13.5px (mh:311). */
    metricKey: "text-[13.5px]",
    /** FI10: `.mrow .v .vt` 13.5px/600 (mh:313). */
    metricValue: "text-[13.5px] font-semibold",
    /** FI11: `.mrow .v .va` 12px (mh:314). */
    metricAvg: "text-[12px]",
    /** FI12: `.mrow.plain .v` 13.5px (mh:316). */
    metricPlain: "text-[13.5px]",
    /** FI13: `.spend-top` margin-bottom 6px (mh:304); its two columns
     *  split the card evenly (2026-10-18 capture, page-parity 07 FI1; the
     *  Clone's 24px gap). */
    spendTop: "mb-1.5",
    /** FI13 (page-parity 07 FI1): Last spend's column starts with a 1px
     *  rule, its text 9px after it (2026-10-18 capture: 12px / 1.32). */
    spendSplit: "border-l pl-2.25",
    /** FI14: `.spend-col .lbl` 12px, margin-bottom 5px (mh:305). */
    spendLabel: "mb-1.25 text-[12px]",
    /** FI15: `.spend-col .big` 22px/700 (mh:306). */
    spendBig: "text-[22px] font-bold",
    /** FI16: `.spend-col .sub` 15px (mh:307). */
    spendSub: "text-[15px]",
    /** FI17: `.hr` 1px, margin 10px 0 (mh:309). */
    rule: "h-px my-2.5",
    /** FI18: `.bars` height 62px, gap 3px, margin 6px 0 4px (mh:493). */
    chart: "h-15.5 gap-0.75 mt-1.5 mb-1",
    /** FI19: `.bars i` radius 2px 2px 0 0, min-height 2px (mh:494). */
    bar: "rounded-t-xs min-h-0.5",
    /** FI20: `.axis` 10px (mh:496). */
    axis: "text-[10px]",
    /** FI21: `.badge-val` 11.5px/600, padding 3px 9px, radius 7px (mh:315). */
    badge: "px-2.25 py-0.75 rounded-[7px] text-[11.5px] font-semibold",
    /** FI22: `.info-i` 14×14 (mh:302). */
    info: "size-3.5",
    /** FI23: `.nick-edit` gap 8px (mh:320). */
    nickEdit: "gap-2",
    /** FI24: `.nick-edit svg` 13px (mh:321). */
    pencil: "size-3.25",
    /** FI25: `.loc-box` gap 8px, border 1px, radius 8px, padding 8px 10px,
     *  13px; margin-top 10px (mh:317, markup mh:833). */
    location: "mt-2.5 gap-2 px-2.5 py-2 rounded-lg text-[13px] border",
    /** FI26: `.loc-box svg` 15px (mh:318). */
    locationIcon: "size-3.75",
    /** FI27: the tab bar, Infloww's (2026-10-18 capture; the Clone's
     *  `.right-tabs` border-top, mh:324): no rule, the tiles 8px in, 12px
     *  from the bottom. */
    tabs: "px-2 pt-2 pb-3",
    /** FI28: a tile, 52px tall: gap 4px, padding 6px 0, radius 8px,
     *  12px/600 (2026-10-18 capture; the Clone's `.rtab`, mh:325). */
    tab: "gap-1 py-1.5 rounded-lg text-[12px] font-semibold",
    /** FI29: `.rtab svg` 20px (mh:326). */
    tabIcon: "size-5",
    /** FI30: `.stab` 12px (mh:488). */
    salesTable: "text-[12px]",
    /** FI31: `.stab th` padding 4px 5px, 10.5px/600, letter-spacing .3px,
     *  uppercase, border-bottom 1px (mh:489-490). */
    salesHead: "px-1.25 py-1 text-[10.5px] font-semibold tracking-[.3px] uppercase border-b",
    /** FI32: `.stab td` padding 6px 5px, border-bottom 1px (mh:491). */
    salesCell: "px-1.25 py-1.5 border-b",
    /** FI33: `.note-ta` min-height 132px, radius 9px, padding 10px, 13px/1.5,
     *  border 1px (mh:497-498), the 13px from md up. Below md it keeps
     *  today's 16px, so iOS does not zoom into Fan notes (as CP7, PV4). */
    note: "min-h-33 p-2.5 rounded-[9px] text-base md:text-[13px] leading-normal border",
  },
  /** Thread empty state (ES). */
  emptyState: {
    /** ES1. The empty Thread, `.empty` (mh:287): a centred column, 22px gap. */
    root: "gap-5.5",
    /** ES2. Its icon, 100×100px with a 1px stroke (2026-10-18 capture; the
     *  Clone's `.empty svg`, mh:288, 130px). */
    icon: "size-25 stroke-1",
    /** ES3. Its line (2026-10-18 capture; the Clone's 26px, mh:289): 20px. */
    text: "text-[20px]",
  },
  /** Our own literals with no Clone selector, per component, unchanged
   *  (spec D2): `messagesProOurs.ts`. */
  ours: OURS,
} as const;
