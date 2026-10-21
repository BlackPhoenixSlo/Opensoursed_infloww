/**
 * Messages Pro's own literals (spec D2): the Geometry numbers in the token
 * module's scope that have no Clone selector, per component, unchanged from
 * the JSX they left. `MP.ours` in `messagesPro.ts` is this object, so callers
 * read `MP.ours.<Component>.<name>`. Class strings only: ADR-0001's colour
 * rule holds here too, and `messagesPro.test.ts`'s colour check walks every
 * leaf. The snapshot does not pin these values (no Clone source to measure).
 */
export const OURS = {
  CreatorTabs: {
    /** The tab's pick target, `role="tab"`: the avatar, name and
     *  unread total at the tab's 8px gap (`.ctab`, mh:56). */
    tabPick: "gap-2",
    /** The drop marker, `.ctab.dropmark` (mh:339): a 2px line
     *  drawn inside the tab the dragged one is over, on the side it will
     *  land: `before` (the Clone's left line) when it moves left, `after`
     *  (mirrored) when it moves right. It replaces the active tab's top line,
     *  as in the Clone. */
    dropMarkBefore: "inset-shadow-[2px_0_0]",
    /** The drop marker's `after` side, mirrored: when the tab moves right. */
    dropMarkAfter: "inset-shadow-[-2px_0_0]",
    /** The Creator picker's place: from "+ Add a Creator"'s left
     *  edge (the Clone's `popover()` aligns every `.pop` left, mj:117),
     *  4px below it (ours: Phase 2's Fan List menus; the Clone's is 6px,
     *  mj:118), above the panes. */
    pickerPlace: "left-0 mt-1 z-30",
  },
  FanTabs: {
    /** The tab's pick target, `role="tab"`: the name, unread badge
     *  and signal at the tab's 8px gap (mh:195). */
    tabPick: "gap-2",
  },
  OpenInNewWindowMenu: {
    /** "Open in a new window"'s menu, pinned to the viewport (the
     *  caller sets `top` and `left` to the child's bottom-left corner, so a
     *  tab strip's sideways scroller cannot clip it), 4px below (ours, as
     *  `CreatorTabs.pickerPlace`), above the panes. */
    place: "mt-1 z-30",
  },
  FanListButtons: {
    /** Notifications' panel, passed to the bell (a shared module, spec
     *  Shared modules) and opened against the row so it stays inside
     *  the Fan List pane, and so inside the viewport, at every width: the
     *  row's 16px insets, 4px under the buttons (the row's 4px top padding
     *  plus the 42px button). At most 480px tall, and never past the bottom
     *  of the Messages Pro area (`.h-chat` ends at `--vvh`, which hides
     *  overflow): its top is at most 247px down the viewport (desktop: top
     *  bar, Window header, Fan tabs, Fan List header, buttons), so 16rem off
     *  `--vvh` keeps its bottom above the viewport's on a short screen. */
    notifPanel: "inset-x-4 top-12.5 max-h-[min(30rem,calc(var(--vvh)-16rem))]",
    /** The "Notif" (Buys & tips) switch (Compare FL11, ours: Infloww has
     *  none) at the Fan List header's right end: its label over the 26×14
     *  track (`windowHeader.switch`), at least the house 36px tap target on
     *  a phone, the header icons' 7px radius. */
    panelSwitch: "min-w-9 min-h-9 md:min-w-0 md:min-h-0 px-0.5 rounded-[7px]",
  },
  FanListHeader: {
    /** The "+" New menu's place: from the trigger's right edge, 4px below
     *  it (ours, as `CreatorTabs.pickerPlace`), above the panes. */
    menuPlace: "right-0 mt-1 z-30",
  },
  FanListFilters: {
    /** The gear and the sort-line menus' place: from the trigger's right
     *  edge, 4px below it (ours, as `CreatorTabs.pickerPlace`). */
    menuPlace: "right-0 mt-1 z-30",
    /** The "All inboxes" menu's place: from the selector's left edge, as
     *  the Clone's `popover()` places every `.pop` (mj:109-117), 4px below
     *  it, so it stays inside the pane. */
    menuPlaceStart: "left-0 mt-1 z-30",
    /** The gear's box: a 1px border (Infloww's own screenshot, ranked above
     *  the Clone's bare icon, mh:134), and below md the house 36px tap
     *  target. */
    gear: "border min-w-9 min-h-9 md:min-w-0 md:min-h-0",
    /** The sort line's icon buttons: radius 6px, and below md the house
     *  36px tap target. */
    sortButton: "rounded-md min-w-9 min-h-9 md:min-w-0 md:min-h-0",
    /** The chip row's pull: 8px up into the filter row's 12px bottom
     *  padding (FL10), where its scrollers' badge room sits, so the chips
     *  stay 12px under the filter row as in the Clone. The folder row
     *  takes the same pull under the chip row (FL17). */
    rowPull: "-mt-2",
    /** A chip scroller: the chips 8px apart (`.chips`, mh:141), with 8px of
     *  room above them so a corner badge's 5px overhang is not clipped by
     *  `overflow-x:auto`. */
    chipScroller: "gap-2.5 pt-2",
    /** The "+" Extras overflow's anchor, outside the scroller so its menu
     *  is not clipped: the same 8px badge room. */
    extrasAnchor: "pt-2",
    /** Every chip at the Clone's 1.4 line height (mh:37), held on the chip
     *  so it does not depend on the Messages Pro root (Group chat). */
    chip: "leading-[1.4]",
    /** A folder chip: the same 1.4, and below md the house 36px tap target
     *  the chips keep (FL18). */
    folderChip: "leading-[1.4] min-h-9 md:min-h-0",
    /** The count in a chip's corner badge on one 10px line. */
    chipBadge: "leading-none",
    /** A menu row's sub-line under its name: a sort order's explanation,
     *  Focus mode's hint. */
    menuSubLine: "text-[10px] leading-tight",
  },
  FanRow: {
    /** Row badges 🔥 and ❄️ (no Clone CSS): a 13px glyph, the size the
     *  spec gives them (Rows). */
    glyphBadge: "text-[13px]",
    /** All Models' Creator chip on line one below lg: 10px on one line,
     *  padding 2px 6px, round, at most 40% of the line. */
    accountChip: "text-[10px] leading-none px-1.5 py-0.5 rounded-full max-w-[40%]",
    /** Bulk select's check on the avatar's top-left edge: 16px, round, a
     *  1px border. */
    pickMark: "-top-1 -left-1 size-4 rounded-full border",
  },
  FanListBulkBar: {
    /** Bulk select's bar under the filters: 4px gaps, 6px 8px padding,
     *  12px, a 1px top border. */
    bar: "gap-1 px-2 py-1.5 text-[12px] border-t",
    /** A bar button: 24px tall, 8px sides, radius 6px, a 1px border, and
     *  below md the house 36px tap target. */
    button: "h-6 px-2 rounded-md border min-h-9 md:min-h-0",
    /** "Add to lists"'s menu: from the button's left edge, 4px below it. */
    menuPlace: "left-0 mt-1 z-30",
  },
  FanList: {
    /** The list's last line while no "Load more" shows: 40px tall, 11px,
     *  8px sides. */
    sentinel: "h-10 px-2 text-[11px]",
    /** Owe reply's "keep scanning" link: a 40px tap target with 16px sides
     *  below md, bare from md up. */
    keepScanning: "px-4 py-2 md:px-0 md:py-0 min-h-[40px] md:min-h-0",
  },
  SplitInbox: {
    /** The Split Inbox dialog, centred: 360px wide and never past the
     *  window's 16px margins, padding 20px, radius 8px, a 1px border. */
    dialog: "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-90 max-w-[calc(100vw-2rem)] p-5 rounded-lg border",
  },
  FolderPicker: {
    /** The folder picker's panel: 96px down, centred, 320px wide and never
     *  past 12px margins, at most 70vh tall, radius 8px, a 1px border. */
    panel: "top-24 left-1/2 -translate-x-1/2 w-[min(320px,calc(100vw-1.5rem))] max-h-[70vh] rounded-lg border",
  },
  ChatHeader: {
    /** The Fan insights toggle and the kebab, `#tbKebab`
     *  (mh:709): an `.icon-btn` (`MP.chatHeader.iconButton`) from md up;
     *  below md they keep today's 40×40px touch size (spec F14). Shown at
     *  every width. */
    rightIcon: "size-10 md:size-7.5 rounded-[7px]",
  },
  FanAvatarMenu: {
    /** The Avatar menu's place: under the Chat header row, 8px in
     *  from each side below md; from md up 8px from the Region's left, 4px
     *  below it (ours, as `CreatorTabs.pickerPlace`), above the Thread. */
    place: "left-2 right-2 md:right-auto mt-1 z-40",
  },
  ToggleListsSubmenu: {
    /** "Add to lists ▸"'s membership box: 16px, a 1px border, radius
     *  4px, the ✓ at 10px (ours). */
    check: "size-4 rounded border text-[10px]",
    /** A list's Fan count and its "…" while it saves: 11px (ours, as
     *  `MP.menu.meta`'s size). */
    count: "text-[11px]",
  },
  ChatActionsMenu: {
    /** The Kebab menu's place, with its "Inflowwww extras ▸" submenu
     *  (ticket 140): from the row's right edge less 8px, 4px below it (ours,
     *  as `CreatorTabs.pickerPlace`), above the Thread; the two boxes 4px
     *  apart, the submenu beside the Kebab menu from md up and under it
     *  below md, their tops level. */
    place: "right-2 mt-1 z-40 gap-1 flex flex-col items-end md:flex-row-reverse md:items-start",
    /** The Kebab menu's box: below md 88vw wide and at most 320px, from md
     *  up as wide as its rows. */
    box: "w-[min(88vw,320px)] md:w-auto",
    /** A row's leading emoji: a 16px column at 11px (ours). */
    rowIcon: "w-4 text-[11px]",
  },
  ChatHeaderExtras: {
    /** The Extras overflow's box, the Kebab menu's submenu (ticket 140;
     *  its place is `ChatActionsMenu.place`): as wide as the Kebab menu's
     *  box below md, from md up as wide as its rows. */
    box: "w-[min(88vw,320px)] md:w-auto",
  },
  ChatSearch: {
    /** The "Searching…" status and the error line: 11px (ours). */
    note: "text-[11px]",
    /** The close ✕: below md a 40px tap target at 16px; from md up its
     *  own size at 11px, 4px at the sides (ours). */
    close: "w-10 h-10 md:w-auto md:h-auto text-base md:text-[11px] md:px-1",
    /** The match count line and a hit's time: 10px (ours). */
    small: "text-[10px]",
    /** A hit: padding 10px at the sides, 12px top and bottom below md
     *  (touch) and 6px from md up, 12px (ours). */
    hit: "px-2.5 py-3 md:py-1.5 text-[12px]",
    /** A hit's "you" / "fan" / "not loaded": 10px / 600 (ours). */
    who: "text-[10px] font-semibold",
  },
  PersonaClaims: {
    /** "Creator facts" and "What this fan was told": 11px / 500,
     *  letter-spaced (ours). */
    heading: "text-[11px] font-medium tracking-wide",
    /** A count and the footnote: 10px (ours). */
    small: "text-[10px]",
    /** The empty notes and "Earlier versions given": 11px (ours). */
    text: "text-[11px]",
    /** The empty canon's note, 6px under its heading: 11px (ours). */
    canonEmpty: "mt-1.5 text-[11px]",
    /** A canon fact and an earlier version: 11px, line height 1.375 (ours). */
    line: "text-[11px] leading-snug",
    /** A claim row: label, value and date 6px apart, 11px, line height
     *  1.375 (ours). */
    row: "gap-1.5 text-[11px] leading-snug",
    /** An edited claim's label: 10px, letter-spaced (ours). */
    editLabel: "text-[10px] tracking-wide",
  },
  MenuStatusLine: {
    /** A Chat header menu's status line under its rows (ours; the
     *  Clone's menus report no outcome): 11px, padding 4px 10px, lined up
     *  with `MP.menu.row`'s 10px (`.prow`, mh:364), a 1px top border. */
    root: "px-2.5 py-1 text-[11px] border-t",
  },
  ChatGallery: {
    /** `.sheet-back` (mh:382): the whole window, above the app (JSX
     *  centres the sheet from md up; below md the sheet fills it, spec F14). */
    backdrop: "inset-0 z-[60]",
    /** "↻ Refresh", a `.btn-sm` (mh:499): radius 7px, padding 7px
     *  12px, 12.5px / 600. */
    refresh: "rounded-[7px] py-1.75 px-3 text-[12.5px] font-semibold",
    /** The empty and error notices, `.honest` (mh:504-505): a dashed
     *  1px border, radius 10px, padding 14px, 12.5px / 1.55, the title at
     *  600 (JSX: a dashed column). */
    notice: "gap-2.5 rounded-[10px] border p-3.5 text-[12.5px] leading-[1.55]",
    /** "Load more" under the grid, as Fan insights' "Load more from
     *  server" (`FanDrawer.tsx:1278-1286`): 10px below the grid, radius 6px,
     *  a 1px border, 6px tall padding (JSX: full width, dashed). */
    more: "mt-2.5 rounded-md border py-1.5",
    /** A failed "Load more"'s notice under the loaded tiles: 10px
     *  below them, as "Load more" itself. */
    moreError: "mt-2.5",
  },
  BubbleActions: {
    /** Our bubble's "More message actions" menu: under its bubble line, its
     *  right edge on the line's, 4px down, above the next bubbles (ours). */
    menu: "right-0 mt-1 z-30",
    /** A Details panel row (in the menu's box): label left, value right,
     *  12px apart, the menu row's 10px sides. */
    detailsRow: "gap-3 px-2.5 py-1",
  },
  MessageList: {
    /** "No messages yet": 32px around it. */
    empty: "p-8",
    /** "↓ Jumping to latest…": 8px under the list's top, centred, in the
     *  Clone's `.chip` (m.html:143): padding 7px 15px, radius 16px, 13px / 500
     *  (Phase 4 spec T7), on one line. */
    autoPin: "top-2 left-1/2 -translate-x-1/2 px-3.75 py-1.75 rounded-2xl text-[13px] font-medium whitespace-nowrap",
    /** "↓ Latest": an 11px pill 12px above the bottom, 16px from the right. */
    latest: "bottom-3 right-4 px-2.5 py-1 rounded-full text-[11px]",
    /** The load-error notice: stuck to the top, bleeding over the list's
     *  padding to its edges, 11px, a 1px bottom border (the list's gap
     *  spaces it from what follows). */
    notice: "top-0 -mx-2 -mt-3 px-3 py-1.5 text-[11px] leading-snug border-b md:-mx-6.5 md:-mt-5.5",
    /** "Start of conversation.": 11px, 8px above and below. */
    start: "py-2 text-[11px]",
    /** A "Message withdrawn" line where one of our unsent bubbles stood:
     *  11px, as "Start of conversation.", 2px above and below. */
    withdrawn: "py-0.5 text-[11px]",
    /** The bubble's column: 4px between the status line, the bubble and
     *  our status row. */
    column: "gap-1",
    /** A tip bubble: a 1px line, which wins over the others. */
    tipBorder: "!border",
    /** A scheduled bubble of ours: a 2px dashed line. */
    scheduledBorder: "border-2",
    /** "PAID" / "FREE" before an outbound PPV's text: 9px / 700. */
    textBadge: "px-1 rounded text-[9px] font-bold leading-tight",
    /** A release-form tag: a 10px pill. */
    releaseTag: "gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] leading-tight",
    /** A Giphy gif: 6px under the text, radius 6px. */
    gif: "mt-1.5 rounded-md",
    /** Its width: at most 155px, 100px in compact media. */
    gifWidth: "max-w-[155px]",
    gifWidthCompact: "max-w-[100px]",
    /** The ♥ sticker on the bubble's bottom corner, 13px. */
    heart: "-bottom-2 text-[13px] leading-none",
    /** The 📌 sticker on the bubble's top corner, 11px. */
    pinSticker: "-top-2 text-[11px] leading-none",
    /** Both stickers sit 4px out of the bubble: left on ours, right on the
     *  Fan's. */
    stickerOut: "-left-1",
    stickerIn: "-right-1",
    /** A media tile's "BOUGHT" / "FREE" / price badge, 4px in from the
     *  top left: 9px / 700. */
    tileBadge: "top-1 left-1 px-1 rounded text-[9px] font-bold leading-tight",
    /** A refused tile's "REMOVE" bar along its bottom: 9px / 700. */
    refusedBar: "inset-x-0 bottom-0 py-0.5 text-[9px] font-bold leading-tight",
    /** A locked tile (🔒): radius 6px, 11px, a 1px border. */
    lockedTile: "rounded-md text-[11px] leading-tight border",
    /** A tile with no thumbnail yet (…): radius 6px, 9px. */
    pendingTile: "px-1 rounded-md text-[9px] leading-tight",
    /** A video tile's ▶, a 28px circle centred on the tile: 11px. */
    tilePlay: "top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-7 rounded-full text-[11px] leading-none",
    /** A video tile's duration, 4px in from the bottom right (the badge
     *  holds the top left): 9px / 700. */
    tileDuration: "bottom-1 right-1 px-1 rounded text-[9px] font-bold leading-tight",
    /** "2 photos · 1 video" above a bundle's tiles: 10px, 4px under it. */
    mediaCount: "mb-1 text-[10px] leading-tight",
    /** "Video not available" under the poster in the viewer: 14px pill. */
    zoomNotice: "mt-2 px-3 py-1 rounded-full text-sm",
    /** "remove N of M" under the tiles: 10px / 700. */
    refusedCount: "mt-1 px-1 py-0.5 rounded text-[10px] font-bold leading-tight",
    /** "show less" under the tiles: 11px, a 1px border. */
    showLess: "mt-1.5 py-1 rounded-md border text-[11px]",
    /** The full-size image's backdrop: the whole window, above the app. */
    zoomBackdrop: "inset-0 z-[80]",
    /** The full-size image, at most 92% of the window each way. */
    zoomFrame: "max-w-[92vw] max-h-[92vh]",
    zoomImage: "max-w-[92vw] max-h-[92vh] rounded-md",
    /** The quoted message at a reply's top: 11px, a 2px left line. */
    quote: "mb-1.5 pl-2 pr-2 py-1 rounded-md border-l-2 text-[11px] leading-tight",
    /** A translation's language tag: 9px / 700, letter-spaced. */
    langTag: "text-[9px] font-bold tracking-wide",
    /** A bubble line picked by search: its ring's 6px radius. */
    highlight: "rounded-md",
  },
  BubbleMeta: {
    /** Our status row under a bubble (sending…, failed — retry, scheduled,
     *  cancel): 10px, 6px apart. */
    status: "gap-1.5 px-1 text-[10px]",
  },
  MediaTile: {
    /** A tile still loading, and one that failed: the reserved skeleton
     *  box, radius 6px. The real per-image size is not known on first
     *  paint, so the box reserves a neutral minimum height (96px), not an
     *  aspect ratio, which would letterbox wide images and only move the
     *  reflow. The caller (MediaStrip) sizes the actual box through a
     *  definite-height parent and the tile's `h-full`, so the placeholder
     *  and the image always match; this is the floor without one. */
    skeleton: "min-h-[6rem] rounded-md",
    /** A failed tile's "failed": 10px. */
    failedLabel: "text-[10px]",
  },
  PinnedPanel: {
    /** The pinned-messages overlay: on the window's left edge and down to
     *  its bottom, a 1px line on top and right. */
    overlay: "left-0 bottom-0 border-t border-r",
    /** Its "📌 Pinned messages · N ✕" head: 12px, a 1px bottom line. */
    head: "gap-2 px-3 py-2 text-[12px] border-b",
    /** A pin's sender and time: 11px. */
    who: "gap-2 text-[11px]",
    /** A pin's text: 12px, 2px under the sender. */
    preview: "mt-0.5 text-[12px]",
    /** "📎 N media — click to view": 10px, 4px under the text. */
    media: "mt-1 gap-1 text-[10px]",
  },
  ScheduledForChat: {
    /** A queued send's time: 10px. */
    time: "text-[10px]",
    /** Its 📎 count and 🔒 price: 10px, 6px apart. */
    meta: "gap-1.5 text-[10px]",
    /** Its "Cancel": 10px, today's touch height below md, a 1px border. */
    cancel: "px-2 py-1.5 md:py-0.5 rounded border text-[10px]",
  },
  Composer: {
    /** The notice stack above row 1: 8px between notices, today's 16px side
     *  and 12px top inset (the root's padding before look-and-feel C1 moved
     *  it onto the rows), 8px above row 1. */
    notices: "space-y-2 px-4 pt-3 pb-2",
    /** The reply strip, directly under row 2 and above the PPV row
     *  (look-and-feel C10): today's 16px side inset, the root's before C1
     *  moved it onto the rows. The PPV row carries its own (PV1). */
    reply: "px-4",
    /** A notice above the button row (sending disabled, a send toast, the
     *  next script step, the Timed reminder): 11px, padding 6px 10px,
     *  radius 6px, a 1px border, 8px between its parts. */
    notice: "gap-2 px-2.5 py-1.5 rounded-md border text-[11px]",
    /** The input's border (none) and its growth cap, 192px. */
    input: "max-h-48 border-0",
    /** The free ↑ / paid ↓ divider between attachments: 42px tall, padding
     *  0 4px, 8px / 600 with wide tracking, 2px dashed sides. */
    divider: "gap-0.5 h-[42px] px-1 text-[8px] font-semibold tracking-wide border-l-2 border-r-2",
    /** An attachment with no thumbnail: its type at 10px. */
    tileType: "text-[10px]",
    /** An attachment's FREE / PPV / BOUGHT badge, in its bottom-left corner:
     *  8px / 700, padding 0 2px, top-right radius 4px. */
    tileBadge: "bottom-0 left-0 px-0.5 rounded-tr text-[8px] font-bold leading-tight",
    /** An attachment's ✕ (PV9), in its top-right corner. */
    tileRemove: "top-0 right-0 leading-tight",
    /** A failed upload's chip: as wide as its error (to 224px) and Retry, 6px
     *  apart, 6px left inset, 20px right for the ✕, 11px. */
    uploadFailed: "max-w-56 gap-1.5 pl-1.5 pr-5 text-[11px]",
  },
  ComposerToolbar: {
    /** A button-row pill's line height (CP5 sets none). */
    pill: "leading-tight",
    /** Send's line height (CP11 sets none). */
    send: "leading-tight",
    /** "N sending…" before Send: 10px. */
    inflight: "text-[10px]",
    /** A button-row popover (the ⏱ Timed message, the Translator): from its
     *  trigger's right edge, 8px above it. */
    pop: "right-0 mb-2",
    /** The "+" Extras overflow's popover (look-and-feel C12): from the "+"'s
     *  right edge, 8px above it, and never wider than the viewport less 24px
     *  (the `.pop` box's 360px cap below that), so at 390 it opens wholly
     *  on-screen. */
    extrasPop: "right-0 mb-2 max-w-[min(360px,calc(100vw-24px))]",
    /** ⚙ emoji favourites' popover (look-and-feel C13): ⚙ sits at row 1's
     *  left end, so it opens from its trigger's left edge, toward the inside
     *  of the screen, 8px above it. */
    popStart: "left-0 mb-2",
    /** A popover's primary action (⏱ "Start", the ⚙ editor's "Save"):
     *  radius 7px, padding 7px 12px, 12.5px / 600. */
    popPrimary: "rounded-[7px] px-3 py-[7px] text-[12.5px] font-semibold",
    /** The Translator's "English" row: 600. */
    translateTarget: "font-semibold",
  },
  TimedMessagePopover: {
    /** Its two tabs, 12px apart. */
    tabs: "gap-3",
    /** "Send in" / "Remind in", the minutes field and "min": 5px apart. */
    label: "gap-[5px]",
    /** The minutes field: 56px wide. */
    minutes: "w-14",
  },
  FanDrawer: {
    /** Fan insights as the slide-over below lg: the whole width up to
     *  420px, 360px from sm, a 1px left line. It may shrink below its
     *  content's minimum width (look-and-feel C14), so at 390 it fills x
     *  56-390 beside the 56px tap-to-close gutter. */
    slideOver: "w-full min-w-0 max-w-[420px] sm:w-[360px] sm:max-w-[360px] border-l",
    /** The head's title, "+" and ×: 4px apart (FI1 holds its padding and
     *  type). */
    head: "gap-1",
    /** The "+" menu of removed Insights blocks: from the "+"'s right edge,
     *  4px below it (as `CreatorTabs.pickerPlace`), above the blocks. */
    addMenu: "right-0 mt-1 z-30",
    /** A collapsed block's head: no margin under it (FI4's 12px is for an
     *  open block). */
    blockHeadCollapsed: "gap-2",
    /** A block row's term and value: 12px apart (FI8 holds its padding). */
    row: "gap-3",
    /** A term and its ⓘ: 6px apart. */
    term: "gap-1.5",
    /** "Purchases over time" with "Full history ↗": 12px apart, 4px above
     *  the chart (the Clone's inline `margin-bottom:4px`, mh:791). */
    sparkRow: "gap-3 mb-1",
    /** FI17's `<hr>`: its own top border off, so the 1px fill is the line. */
    rule: "border-0",
    /** The editable Profile values: 16px below md (iOS does not zoom),
     *  13.5px from md, radius 2px for the focus ring. */
    inlineEdit: "text-base md:text-[13.5px] rounded-sm",
    /** A Lists chip: a 10px pill, a 1px border. */
    listChip: "px-2 py-0.5 rounded-full border text-[10px]",
    /** "Loading purchase history…" and "No PPV purchases yet.": 10px. */
    status: "text-[10px]",
    /** The Fan block: the Fan's @handle, 11px. */
    extrasHandle: "text-[11px]",
    /** Its Creator and Fan id line: 10px, 2px under the handle. */
    extrasMeta: "mt-0.5 text-[10px]",
    /** A mass-exclude switch's hint, from md: 10px, 2px under its title. */
    excludeHint: "mt-0.5 text-[10px] leading-tight",
    /** "AI profile": 11px / 500, letter-spaced. */
    sectionHeading: "text-[11px] font-medium tracking-wide",
    /** The purchased-media rows' "loading media…" and refresh time: 9px. */
    mediaStamp: "text-[9px]",
    /** Their ↻: a 36px tap target below md, 12px from md. */
    mediaRefresh: "w-9 h-9 md:w-auto md:h-auto text-base md:text-[12px] leading-none",
    /** "Show N more" / "Show less": a 1px dashed box, radius 6px, the
     *  phone's tap height below md, 10px from md. */
    showMore: "py-3 md:py-1.5 rounded-md border text-xs md:text-[10px]/[1.5]",
    /** "Load more from server": as "Show N more", 11px from md. */
    loadMore: "py-3 md:py-1.5 rounded-md border text-sm md:text-[11px]/[1.5]",
    /** A sold or unsold PPV's price pill: 11px / 600. */
    pricePill: "gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold",
    /** Its date: 11px. */
    rowDate: "text-[11px]",
    /** A sold PPV's ▾: 10px. */
    rowChevron: "text-[10px]",
    /** A sold PPV's open body: 11px, 4px between its lines. */
    saleBody: "px-2 pb-2 space-y-1 text-[11px]",
    /** Its net · fee · VAT line: 10px, 8px apart, a 1px top line. */
    saleAccounting: "gap-x-2 pt-0.5 border-t text-[10px]",
    /** An unsold PPV's "Send to chat": 10px, radius 4px. */
    sendToChat: "px-2 py-0.5 rounded text-[10px]",
    /** An unsold PPV's text: 11px. */
    unsoldText: "px-2 pb-2 text-[11px]",
    /** A media tile with no thumbnail: its — at 9px. */
    thumbEmpty: "text-[9px]",
    /** The same on a video tile, over the whole tile. */
    scrubEmpty: "inset-0 text-[9px]",
    /** A cold video's countdown: 16px / 600 with a 1px-down, 3px-blur
     *  shadow (its colour in the JSX). */
    countdown: "text-base font-semibold drop-shadow-[0_1px_3px]",
    /** The media preview's ×: 12px in from the top right (under the
     *  notch below md), 44px below md and 36px from md, round. */
    lightboxClose: "right-3 top-[calc(0.75rem_+_env(safe-area-inset-top))] md:top-3 w-11 h-11 md:w-9 md:h-9 rounded-full text-2xl leading-none",
    /** AI profile: the language chip, a 10px pill. */
    langChip: "px-1.5 py-0.5 rounded-full border text-[10px]",
    /** Its 10px lines: the generated time, a timeline date, the openers. */
    profileMeta: "text-[10px]",
    /** Its 11px lines: "No profile yet", a fact, a timeline event. */
    profileText: "text-[11px]",
    /** Its note: 11px at a relaxed line height. */
    profileNote: "text-[11px] leading-relaxed",
    /** "Timeline": 10px, letter-spaced, 4px above the list. */
    timelineLabel: "mb-1 text-[10px] tracking-wide",
  },
} as const;
