/**
 * The Messages Pro token module: seam 1 of docs/spec/phase-06-geometry-pass.md
 * (Testing Decisions). Ticket 106 starts it with the pane rows (Gap table
 * "Panes and page", PN1 to PN5); ticket 110 adds the full snapshot and the
 * colour check, and ticket 111 the magic-number guard over the computed scope.
 *
 * jsdom applies no Tailwind CSS, so the widths themselves are proven in the
 * browser (`scripts/ui-shots.sh`, the desktop and popout shots' pane check).
 * Here: the module holds the table's values, and the pane roots read them.
 * Ticket 108 adds CH14 (`MP.chatHeader.labelText`); its container query is
 * proven in the browser too (`check_kebab_in_thread`). Ticket 110 adds the
 * snapshot of every measured Region against the Gap table (spec D2 part 1)
 * and the colour check over every leaf (D2 part 2, ADR-0001). Ticket 119
 * runs the guard over the whole scope with no exception list, and adds
 * consumption: every token is read (D2 part 4).
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { MP } from "./messagesPro";
import { APP_ROOT as APP, importsOf, reachable, resolveSpec, stripComments } from "@/test-import-graph";


/** Every non-test .tsx under `dir`, as [path relative to app/, source]. */
function sources(dir: string): [string, string][] {
  return readdirSync(join(APP, dir), { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".tsx") && !/\.test\.tsx$/.test(f))
    .map((f) => [join(dir, f), readFileSync(join(APP, dir, f), "utf8")]);
}

/** The modules the Messages Pro panes live in: the routes and the chat components. */
const PANE_SOURCES = [...sources("app/messages-pro"), ...sources("components/chat")];

/**
 * The Gap table's Change column (docs/spec/phase-06-geometry-pass.md), one
 * key per row from PN1 to ES3, transcribed by hand: PN3 (the Thread) has no
 * number, and FL36, CH5 and PV7 no element (ticket 119), so no token. Change
 * the table and this object together.
 */
const EXPECTED = {
  panes: {
    root: "text-sm leading-[1.4]", // PN1
    fanList: "lg:w-100 lg:min-w-100 border-r", // PN2
    insights: "lg:w-70 lg:min-w-70 lg:border-l", // PN4
    pinnedOverlay: "w-full max-w-100", // PN5
  },
  windowHeader: {
    bar: "h-11 min-h-11 px-3.5 border-b", // WH1
    home: "ml-1 w-41 h-6 gap-1.75 rounded-tl-lg text-[13px] font-semibold [clip-path:polygon(0_0,calc(100%-10px)_0,100%_100%,0_100%)]", // WH2
    homeIcon: "size-3.75", // WH3
    allModels: "mb-1.25 ml-0.5 gap-1.75 h-7.5 px-3.5 rounded-lg text-[13px] font-bold", // WH4
    allModelsIcon: "size-4", // WH5
    addCreator: "gap-1.75 px-3.5 text-[13px] font-medium", // WH6
    addCreatorIcon: "size-3.75", // WH7
    right: "gap-3.5", // WH8
    sfw: "gap-0.75", // WH9
    sfwLabel: "text-[10px] font-semibold tracking-[.5px]", // WH10
    switch: "w-6.5 h-3.5 rounded-lg", // WH11
    switchKnob: "top-0.5 left-0.5 size-2.5 rounded-full", // WH12
    switchKnobOn: "translate-x-3", // WH13
  },
  creatorTabs: {
    strip: "gap-1 max-w-[58vw]", // CT1
    tab: "gap-2 h-9 pl-1.5 pr-2.5 max-w-55 rounded-t-[9px] border border-b-0", // CT2
    tabActive: "inset-shadow-[0_2px_0]", // CT3
    avatar: "size-6.5 rounded-md text-[11px] font-extrabold", // CT4
    name: "text-[13px] font-bold", // CT5
    badge: "min-w-4 h-4 px-1 rounded-full text-[10px] font-bold", // CT6
    close: "size-4 ml-0.5", // CT7
    empty: "px-2.5 text-[12px]", // CT8
  },
  fanTabs: {
    bar: "h-8 min-h-8 pr-3.5 border-b", // FT1
    strip: "gap-0.75 ml-1", // FT2
    tab: "gap-2 py-1.75 px-2.75 max-w-47.5 rounded-t-lg border border-b-0 text-[12.5px] font-semibold leading-[1.4]", // FT3
    tabActive: "inset-shadow-[0_2px_0]", // FT4
    dot: "size-1.75 rounded-full", // FT5
    close: "px-1 py-0.5 rounded-sm text-[11px] leading-none", // FT6
  },
  fanList: {
    head: "h-13 pl-2.75 pr-3 gap-3 border-b", // FL1
    title: "text-[20px] font-medium", // FL2
    iconButton: "size-9 md:size-6.5 rounded-[7px]", // FL3
    iconButtonIcon: "size-5", // FL4
    gallery: "size-9 md:size-6.5 rounded-[7px]", // Compare FL9
    buttons: "gap-7 pt-4.5 px-2.5 pb-2.5", // FL5
    button: "h-7 gap-1.5 rounded-sm text-[14px] font-medium", // FL6
    buttonIcon: "size-4", // FL7
    notifBadge: "-top-2.5 -right-2.5 min-w-5 h-5 px-1.5 rounded-full text-[13px] font-medium border", // FL8
    buttonPressed: "ring-2", // FL9
    filters: "gap-x-2.5 gap-y-1.5 px-2.75 pb-3", // FL10
    inbox: "gap-2 px-2.75 h-8.5 rounded-sm text-[14px] min-w-37.5 border", // FL11
    inboxIcon: "size-4", // FL12
    gear: "w-9 h-8.5 rounded-sm", // FL13
    gearIcon: "size-4.75", // FL14
    sort: "gap-2.25 text-[14px]", // FL15
    sortIcon: "size-4.25", // FL16
    chips: "gap-2.5 px-2.75 pb-3", // FL17
    chip: "px-3 py-1.5 min-h-[36px] md:h-6.5 md:py-0 md:min-h-0 rounded-2xl text-[14px]", // FL18
    chipBadge: "-top-2 -right-1.5 min-w-4 h-4 px-0.75 rounded-full text-[11px] font-medium", // FL19
    row: "h-24 gap-2.5 px-4.75 pt-4 after:absolute after:bottom-0 after:left-15 after:right-2.25 after:h-px", // FL23
    avatar: "size-10 rounded-full text-[13px] font-bold", // FL24
    avatarIcon: "size-5.5", // FL25
    onlineDot: "bottom-0 right-0 size-2.5 rounded-full border", // FL26
    spend: "top-full left-1/2 -translate-x-1/2 mt-1 h-4 px-1 rounded-xs text-[13px] leading-4 font-bold", // FL27
    top: "gap-1.25", // FL28
    name: "text-[15px] font-medium max-w-42.5", // FL29
    handle: "text-[15px]", // FL30
    verified: "size-3.5", // Compare FL2
    notWired: "text-[16px] leading-none", // Compare FL3
    offLabel: "mt-0.75 text-[11px] font-extrabold tracking-[.5px]", // FL31
    newBadge: "px-1.5 py-0.5 rounded-[5px] text-[9px] font-bold tracking-[.03em]", // FL32
    bottom: "gap-1.5 mt-5", // FL33
    preview: "gap-1.25 text-[14px]", // FL34
    previewUnread: "font-semibold", // FL35
    time: "text-[14px]", // FL37
    unreadDot: "size-2.25 rounded-full", // FL38
    oweDot: "size-2.25 rounded-full ring-2", // FL39
    edgeMarker: "left-1.25 top-9 -translate-y-1/2", // Compare FL8
    accountDot: "left-1.5 top-4 size-2 rounded-full border", // Compare FL1
    muteIcon: "size-3.5", // FL40
    empty: "px-4 py-6 text-[13px]", // FL41
    skeletonRow: "h-24 gap-2.5 px-4.75 border-b", // FL42
    skeletonAvatar: "size-10 rounded-full", // FL43
    skeletonLines: "gap-2.5", // FL44
    skeletonBar: "h-2.75 rounded-md", // FL45
    skeletonBarShort: "w-[52%]", // FL46
    skeletonBarLong: "w-[78%]", // FL47
    loadMore: "px-4 py-3.5 text-[13px] font-semibold border-t", // FL48
    splitSelect: "h-9.5 pl-3 pr-8 rounded-[9px] text-[13.5px] border", // FL50
  },
  chatHeader: {
    bar: "grid-cols-[auto_auto_minmax(0,1fr)_auto] gap-y-1 min-h-13 px-3 py-1 md:h-13 md:px-5 md:py-0 border-b", // Compare CH1
    back: "size-5", // Compare CH1
    backButton: "size-9 -ml-2.5 mr-0.75 rounded-lg", // Compare CH1
    nameRow: "gap-1.5", // Compare CH1
    name: "text-[18px] font-semibold leading-6", // Compare CH1
    verified: "size-2.5", // Compare CH1
    editName: "size-3.5", // Compare CH1
    editNameSlot: "-ml-px", // Compare CH1
    editNameAfterBadge: "ml-0.5", // Compare CH1
    editNameTarget: "-inset-1.25", // Compare CH1
    status: "gap-1.5 text-[10px] leading-3.5", // Compare CH3
    statusDot: "size-1.5 rounded-full", // Compare CH3
    tools: "h-3.5", // Compare CH3
    divider: "w-px h-3 mx-2.5", // Compare CH3
    lineIcon: "size-3.5", // Compare CH3
    lineTarget: "p-1.25 -m-1.25", // Compare CH3
    iconButton: "size-7.5 rounded-[7px]", // CH10
    iconButtonIcon: "size-4", // Compare CH2
    label: "gap-0.75 text-[10px] leading-3.5", // Compare CH3
    labelIcon: "size-3.25", // Compare CH3: a 13px box, the capture's 10.5px glyph (ticket 151)
    labelText: "sr-only @min-[448px]:not-sr-only", // Compare CH3
    right: "gap-1", // CH15
    openNew: "gap-1.5 py-1.5 px-2 rounded-[7px] text-[13px] font-semibold leading-[1.4]", // CH16
    openNewIcon: "size-3.5", // Compare CH2
    kebab: "md:-mr-3.5", // Compare CH2
    kebabIcon: "size-4.75", // Compare CH2
  },
  menu: {
    panel: "min-w-59.5 max-w-90 max-h-[72vh] rounded-[10px] p-1.5 text-[13px] border", // MN1
    row: "gap-2.25 px-2.5 py-3 md:py-2 rounded-[7px] leading-[1.3]", // MN2
    head: "px-2.5 pt-2 pb-1 text-[10.5px] font-bold tracking-[.5px]", // MN3
    divider: "h-px mx-0.5 my-1.25", // MN4
    avatar: "size-5.5 rounded-[5px] text-[9px] font-extrabold", // MN5
    meta: "text-[11px]", // MN6
  },
  sheet: {
    panel: "md:w-[min(900px,92vw)] md:max-h-[84vh] md:rounded-[14px] md:border", // SH1
    head: "gap-2.5 px-4 py-3.25 text-[14px] font-bold border-b", // SH2
    pickerHead: "md:py-3.25", // SH2, the Vault picker's
    pickerTitle: "md:text-[14px] md:font-bold", // SH2, the Vault picker's
    close: "px-1.5 py-0.5 rounded-md text-[17px] leading-none", // SH3
    body: "py-3.5 px-4 min-h-22.5 text-[13px]", // SH4
    grid: "grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2.5", // SH5
    pickerGrid: "md:grid-cols-[repeat(auto-fill,minmax(118px,1fr))] md:gap-2.5", // SH5, the Vault picker's
    tile: "rounded-[9px] border", // SH6
    pickerTile: "md:rounded-[9px]", // SH6, the Vault picker's
    tileTag: "left-1.5 bottom-1.5 rounded-md py-0.5 px-1.5 text-[10.5px] font-bold", // SH7
  },
  messageList: {
    body: "px-2 py-3 gap-2 md:px-6.5 md:py-5.5 md:gap-3.5", // ML1
    bubbleColumn: "max-w-[88%] md:max-w-[60%]", // ML2
    bubble: "rounded-2xl px-3 py-2 text-sm md:rounded-[6px] md:px-2.5 md:py-2.5 md:text-base md:leading-5", // ML3, Phase 4 T10
    bubbleTailIn: "rounded-bl-md md:rounded-bl-none", // ML4, T10
    bubbleTailOut: "rounded-br-md md:rounded-br-none", // ML5, T10
    time: "mt-1.25 text-[11px] leading-[15px] md:mt-0.5 md:leading-[14px]", // ML6, T12
    seen: "ml-1.25 text-[10px]", // ML7
    sentBy: "ml-1.75 text-[10px] font-bold", // ML8
    meta: "text-[12.5px]", // ML9
    ppv: "max-w-80 gap-2 px-4 py-3.5 rounded-[14px] border", // ML10
    ppvTitle: "font-semibold", // ML11
    paidTag: "text-[12px] font-semibold", // ML12
    actionsIn: "ml-0.75 md:ml-1.75 md:gap-1", // ML14
    actionsOut: "md:mr-0.75 md:gap-1.5", // ML15
    action: "size-6 rounded md:size-4", // ML16
    actionIcon: "size-3.5", // ML17
    loadOlder: "mt-0.5 mb-2 px-4 py-1.75 rounded-full text-[12.5px] font-semibold border", // ML18
    pinBar: "gap-2 px-4.5 py-1.75 text-[12px] border-b", // ML19
    pinBarIcon: "size-3.5", // ML20
    pinCount: "font-bold", // ML21
    divider: "gap-3", // ML22
    dividerLabel: "text-[11px]", // ML23
    avatar: "size-9 rounded-full", // ML24
    avatarIn: "mr-2", // ML25
    avatarOut: "ml-2", // ML26
    avatarGlyph: "size-5.5", // ML27
    runGap: "md:-mt-3", // ML28, T11
    timeRoom: "mb-6 md:mb-5", // ML29, T12
  },
  composer: {
    root: "pb-[env(safe-area-inset-bottom)] border-t", // CP1, look-and-feel C1
    buttonRow: "h-11 px-3 gap-1.25 border-b", // CP2, look-and-feel C2 and C3
    buttonRowEnd: "gap-2", // look-and-feel C4
    timed: "ml-2.25", // look-and-feel C4
    buttonRowButton: "size-6.5 rounded-[7px]", // CP3
    buttonRowIcon: "size-5", // CP4
    pill: "h-6.5 gap-1.5 px-2 rounded-[3px] text-sm font-normal", // CP5, look-and-feel C5
    pillLabel: "sr-only @min-[480px]:not-sr-only", // look-and-feel C5, the row-1 label threshold
    pillIcon: "size-4", // CP6, look-and-feel C5
    input: "p-4 text-base leading-5", // CP7, look-and-feel C6
    toolbar: "gap-1.5 py-4 pl-4 pr-3.5", // CP8, look-and-feel C7
    toolbarButton: "size-8.5 rounded-[7px]", // CP9
    toolbarIcon: "size-5", // CP10
    send: "h-8 px-4.75 rounded-full text-base font-normal", // CP11, look-and-feel C8
    aa: "text-[15px] font-extrabold", // CP12
    replyStrip: "gap-2.25 px-3 py-2 mb-2 border-l-3 rounded-lg text-[13px]", // CP13
    replyStripIcon: "size-3.75", // CP14
    replyStripClose: "size-5.5 rounded-md text-[14px]", // CP15
  },
  ppvRow: {
    row: "gap-2 px-4 pb-2 text-sm leading-[1.4]", // PV1, C11
    label: "font-bold", // PV2
    group: "gap-1.25", // PV3
    input: "px-2 py-1.25 rounded-[4px] text-base md:text-sm leading-[1.4] border", // PV4, C11
    price: "w-21.25 pl-1.25 gap-2.5", // PV5, C11
    clear: "px-3 py-1.75 rounded-[7px] text-[12.5px] font-semibold", // PV6
    attachment: "size-10.5 rounded-[7px] border", // PV8
    attachmentRemove: "px-1 text-[10px] rounded-bl-[5px]", // PV9
  },
  insights: {
    head: "px-4 pt-4 pb-2.5 text-[16px] font-bold", // FI1
    body: "px-3 pb-3 gap-3", // FI2
    block: "p-3.5 rounded-xl border", // FI3
    blockHead: "gap-2 mb-3", // FI4
    dragIcon: "size-3.5", // FI5
    blockTitle: "text-[14px] font-semibold", // FI6
    chevron: "size-3.75", // FI7
    metric: "py-1.5", // FI8
    metricKey: "text-[13.5px]", // FI9
    metricValue: "text-[13.5px] font-semibold", // FI10
    metricAvg: "text-[12px]", // FI11
    metricPlain: "text-[13.5px]", // FI12
    spendTop: "mb-1.5", // FI13
    spendSplit: "border-l pl-2.25", // FI13 (page-parity 07 FI1)
    spendLabel: "mb-1.25 text-[12px]", // FI14
    spendBig: "text-[22px] font-bold", // FI15
    spendSub: "text-[15px]", // FI16
    rule: "h-px my-2.5", // FI17
    chart: "h-15.5 gap-0.75 mt-1.5 mb-1", // FI18
    bar: "rounded-t-xs min-h-0.5", // FI19
    axis: "text-[10px]", // FI20
    badge: "px-2.25 py-0.75 rounded-[7px] text-[11.5px] font-semibold", // FI21
    info: "size-3.5", // FI22
    nickEdit: "gap-2", // FI23
    pencil: "size-3.25", // FI24
    location: "mt-2.5 gap-2 px-2.5 py-2 rounded-lg text-[13px] border", // FI25
    locationIcon: "size-3.75", // FI26
    tabs: "px-2 pt-2 pb-3", // FI27
    tab: "gap-1 py-1.5 rounded-lg text-[12px] font-semibold", // FI28
    tabIcon: "size-5", // FI29
    salesTable: "text-[12px]", // FI30
    salesHead: "px-1.25 py-1 text-[10.5px] font-semibold tracking-[.3px] uppercase border-b", // FI31
    salesCell: "px-1.25 py-1.5 border-b", // FI32
    note: "min-h-33 p-2.5 rounded-[9px] text-base md:text-[13px] leading-normal border", // FI33
  },
  emptyState: {
    root: "gap-5.5", // ES1
    icon: "size-25 stroke-1", // ES2
    text: "text-[20px]", // ES3
  },
};

/** The `MP.ours` placements with a look-and-feel Gap row and no Infloww
 *  source (phase-05-composer.md, C12-C14): EXPECTED's ours-only part. */
const EXPECTED_OURS = {
  ComposerToolbar: {
    extrasPop: "right-0 mb-2 max-w-[min(360px,calc(100vw-24px))]", // look-and-feel C12
    popStart: "left-0 mb-2", // look-and-feel C13
  },
  FanDrawer: {
    slideOver: "w-full min-w-0 max-w-[420px] sm:w-[360px] sm:max-w-[360px] border-l", // look-and-feel C14
  },
};

/** `MP` split once: the 13 measured Regions, and our own literals. */
const { ours: OURS, ...MEASURED } = MP;

/** Every leaf of a two-level token object, keyed `<region>.<element>`, so a
 *  drifting leaf is named by its key in the diff. */
function leaves(tokens: Record<string, Record<string, string>>): Record<string, string> {
  return Object.fromEntries(Object.entries(tokens).flatMap(([region, elements]) =>
    Object.entries(elements).map(([element, value]) => [`${region}.${element}`, value])));
}

/** A colour-token class (spec Acceptance's grep, per class): `bg-panel`,
 *  `text-accent/50`, `md:border-border`, `inset-shadow-accent` … */
const COLOUR_CLASS = /^(?:[\w@\[\]-]+:)*(?:bg|text|border|ring|fill|stroke|outline|shadow|inset-shadow|divide|placeholder|caret|decoration|from|via|to)-(?:bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current)(?:[-/].*)?$/;
/** A colour literal: hex, `rgb`/`rgba`, `hsl`/`hsla` or `oklch`. */
const COLOUR_LITERAL = /#[0-9a-f]{3,8}(?![0-9a-z])|rgba?\(|hsla?\(|oklch\(/i;

describe("MP (Gap table snapshot and colour check, spec D2 parts 1 and 2)", () => {
  it("the 13 measured Regions equal the Gap table's Change column, leaf for leaf", () => {
    expect(Object.keys(MEASURED)).toEqual(Object.keys(EXPECTED));
    expect(leaves(MEASURED)).toEqual(leaves(EXPECTED));
  });

  it("the Composer's ours-only placements equal Gap rows C12-C14: the '+' panel, ⚙'s panel and the slide-over", () => {
    expect(leaves(OURS)).toEqual(expect.objectContaining(leaves(EXPECTED_OURS)));
  });

  it("every leaf, ours included, is a non-empty class string with no colour class and no colour literal", () => {
    const all = { ...leaves(MEASURED), ...Object.fromEntries(Object.entries(OURS).flatMap(([component, names]) =>
      Object.entries(names).map(([name, value]) => [`ours.${component}.${name}`, value]))) };
    const bad = Object.entries(all).filter(([, value]) =>
      typeof value !== "string" || value.trim() === "" ||
      value.split(/\s+/).some((c) => COLOUR_CLASS.test(c)) || COLOUR_LITERAL.test(value));
    expect(bad).toEqual([]);
  });
});

describe("MP.panes (Gap table, Panes and page)", () => {
  it("holds PN1, PN2, PN4 and PN5: 14px / 1.4 base text, a 400px Fan List, 280px Fan insights and an overlay as wide as the Fan List", () => {
    // Tailwind scale classes where the scale has the value (400px = 100 × 4px,
    // 280px = 70 × 4px, 14px = text-sm), arbitrary only where it lacks it (1.4).
    // PN3 (the Thread) has no number, so no token.
    expect(MP.panes).toEqual({
      root: "text-sm leading-[1.4]",
      fanList: "lg:w-100 lg:min-w-100 border-r",
      insights: "lg:w-70 lg:min-w-70 lg:border-l",
      pinnedOverlay: "w-full max-w-100",
    });
  });

  it("each pane root carries its data-mp-pane marker with its MP.panes token, and the pinned overlay keeps no numeric width", () => {
    /** The opening tag, in some pane source, that carries `data-mp-pane="<pane>"`. */
    const tagsWith = (pane: string) => PANE_SOURCES.flatMap(([file, src]) =>
      // The value as a literal, or inside an expression (`{pinned ? "insights" : undefined}`).
      [...src.matchAll(/<[A-Za-z][^<>]*?data-mp-pane=(?:"([a-z-]+)"|\{[^}]*?"([a-z-]+)"[^}]*\})[^<>]*?>/gs)]
        .filter((m) => (m[1] ?? m[2]) === pane)
        .map((m) => ({ file, tag: m[0] })));

    // The Fan List and Fan insights roots read their width tokens on the marked tag.
    expect(tagsWith("fan-list").map((t) => t.tag.includes("MP.panes.fanList"))).toEqual([true]);
    expect(tagsWith("insights").map((t) => t.tag.includes("MP.panes.insights"))).toEqual([true]);
    // The Thread takes the rest and is a size container: one in ChatSurface,
    // and the empty state in its place when no Fan is open.
    const thread = tagsWith("thread");
    expect(thread.map((t) => t.file).sort()).toEqual(
      ["components/chat/ChatSurface.tsx", "components/chat/ThreadEmptyState.tsx"]);
    const surface = thread.find((t) => t.file.endsWith("ChatSurface.tsx"))!.tag;
    expect(surface).toMatch(/\bflex-1\b/);
    expect(surface).toMatch(/\bmin-w-0\b/);
    expect(surface).toMatch(/@container\b/);

    // The base text sits on the Messages Pro root: the first tag `MessagesPro` returns.
    const [, tree] = PANE_SOURCES.find(([f]) => f === "components/chat/MessagesPro.tsx")!;
    const body = tree.slice(tree.indexOf("export function MessagesPro("));
    const root = /\breturn \(\s*(<[A-Za-z][^<>]*?>)/s.exec(body)?.[1] ?? "";
    expect(root.includes("MP.panes.root")).toBe(true);

    // The pinned-messages overlay takes its width from the module, not a number.
    const [, pinned] = PANE_SOURCES.find(([f]) => f === "components/chat/PinnedPanel.tsx")!;
    expect(pinned).toContain("MP.panes.pinnedOverlay");
    expect(pinned).not.toMatch(/\bwidth:\s*[A-Z_0-9]/);
    expect(pinned).not.toMatch(/const\s+\w*WIDTH\w*\s*=\s*\d/);
  });
});

describe("MP.chatHeader.labelText (Gap table CH14, spec D4)", () => {
  it("is screen-reader only below a 448px Thread and shown from 448px up (Compare CH3, ticket 141; it was 886px)", () => {
    expect(MP.chatHeader.labelText).toBe("sr-only @min-[448px]:not-sr-only");
  });

  it("the words of Gallery and Find (ChatHeader) and Open in new tab (FanTabs) each sit in a span that reads it", () => {
    const source = (file: string) => PANE_SOURCES.find(([f]) => f === file)![1];
    /** The word, alone in a span whose class is the token, and an `aria-hidden` icon between
     *  the nearest preceding `<button` and that span, so the button keeps its icon and its name.
     *  Attribute order, the icon's form and other span attributes are not fixed (ticket 106's
     *  check accepts a tag that carries the token, nothing more). */
    const wrapped = (src: string, word: string) => {
      const span = new RegExp(`<span[^>]*\\bclassName=\\{MP\\.chatHeader\\.labelText\\}[^>]*>\\s*${word}\\s*</span>`).exec(src);
      if (!span) return false;
      const before = src.slice(0, span.index);
      return before.slice(before.lastIndexOf("<button")).includes("aria-hidden");
    };
    const header = source("components/chat/ChatHeader.tsx");
    expect([wrapped(header, "Gallery"), wrapped(header, "Find")]).toEqual([true, true]);
    expect(wrapped(source("components/chat/FanTabs.tsx"), "Open in new tab")).toBe(true);
  });
});

/* ── The magic-number guard (spec D2 part 3; Seam 1 items 3 and 4) ─────────
 *
 * A scope you type is a scope you forget (`components/settings/sellerCopyLane.test.tsx`).
 * So the scope is computed from the routes: the modules reachable from the
 * Messages Pro pages and layouts and from no other route's (the root layout
 * included, so the app shell drops out), plus every file under `components/`
 * and `app/` that imports the token module, by any spelling. A new component
 * is in scope on the day its import line lands. The comment blanking, the
 * specifier parser and the walk are the seller lane's, shared through
 * `test-import-graph.ts`. */

/** Every `.ts`/`.tsx` under `dir`, relative to app/. */
function filesUnder(dir: string): string[] {
  return readdirSync(join(APP, dir), { recursive: true, encoding: "utf8" })
    .filter((f) => /\.tsx?$/.test(f) && !f.includes("node_modules"))
    .map((f) => join(dir, f));
}

const isTest = (rel: string) => /\.test\.tsx?$/.test(rel);
/** The walk follows what renders: components and routes (`@/lib`, `@/hooks` render nothing). */
const rendering = (rel: string) => /^(components|app)\//.test(rel);
const TOKEN_MODULE = "lib/messagesPro.ts";

/** Every route's pages and layouts, split into Messages Pro's and the rest. */
const ROUTE_FILES = filesUnder("app").filter((f) => /(^|\/)(page|layout)\.tsx$/.test(f)).sort();
const MP_SEEDS = ROUTE_FILES.filter((f) => f.startsWith("app/messages-pro/"));
const OTHER_SEEDS = ROUTE_FILES.filter((f) => !f.startsWith("app/messages-pro/"));
const MP_WALK = reachable(MP_SEEDS, rendering);
const OTHER_WALK = reachable(OTHER_SEEDS, rendering);
/** The token readers: an import of any spelling (alias, relative, re-export)
 *  that resolves to the token module. */
const TOKEN_READERS = [...filesUnder("components"), ...filesUnder("app")]
  .filter((f) => importsOf(f).includes(TOKEN_MODULE));
/** The guard's scope (spec D2): reachable from Messages Pro and from no other
 *  route, plus every token reader, minus the token module and tests. */
const SCOPE = [...new Set([...MP_WALK.modules.filter((f) => !OTHER_WALK.modules.includes(f)), ...TOKEN_READERS])]
  .filter((f) => f !== TOKEN_MODULE && !isTest(f))
  .sort();

/** R2's geometry properties: width, height and their min/max, the four
 *  sides and inset, margin and padding and their sides, gap, fontSize,
 *  lineHeight, borderRadius and flexBasis. */
const SIZE_PROP = "(?:min|max)?(?:Width|Height)|width|height";
const SIDE_PROP = "top|right|bottom|left|inset|(?:margin|padding)(?:Top|Right|Bottom|Left|Inline|Block)?(?:Start|End)?";
const TYPE_PROP = "gap|rowGap|columnGap|fontSize|lineHeight|borderRadius|flexBasis";
const GEOMETRY_PROP = new RegExp(`^(?:${SIZE_PROP}|${SIDE_PROP}|${TYPE_PROP})$`);

/** A numeric literal standing alone (not part of a name or a longer number). */
const NUMBER = /(?<![\w$.])\d[\d_.]*(?![\w$])/;
/** A string or template literal; a template's `${…}` is blanked first. */
const STRING = /"[^"]*"|'[^']*'|`[^`]*`/g;

/** Is `expr` (one attribute or style value) a magic number? It is when it is
 *  made of literals, names and a conditional (`open ? 14 : 16`) and carries a
 *  numeric literal, a string with a digit, or a name this file binds to a
 *  number. Arithmetic or a call is a computation, which stays (spec D2: the
 *  media tile box, the spend chart's bars). */
function magic(expr: string, numericConsts: Set<string>): boolean {
  const statics = expr.replace(/\$\{[^}]*\}/g, "");
  const code = statics.replace(STRING, '""');
  if (/[*/+%,]|[\w$)\]]\s*-\s*[\w$(]|[\w$]\s*\(/.test(code)) return false;
  return NUMBER.test(code) || [...statics.matchAll(STRING)].some((s) => /\d/.test(s[0])) ||
    [...code.matchAll(/[A-Za-z_$][\w$]*/g)].some((n) => numericConsts.has(n[0]));
}

/** R4's Geometry utilities (D1: size, spacing, position, radius, font size,
 *  weight, line height, letter spacing, border width, plus translate), as
 *  `family-value` or a bare family. A scale class counts as much as an
 *  arbitrary one: `twMerge` lets either win over the token beside it. */
const SIZE_FAMILY = "size|(?:min-|max-)?[wh]|basis";
const SPACE_FAMILY = "p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]";
const POSITION_FAMILY = "inset(?:-[xy])?(?!-(?:shadow|ring))|top|right|bottom|left|start|end|translate-[xy]";
const RADIUS_FAMILY = "rounded(?:-(?:[tblrse]|tl|tr|bl|br|ss|se|es|ee))?";
const TYPE_FAMILY = "leading|tracking";
const GEOMETRY_UTILITY = new RegExp(
  `^-?(${SIZE_FAMILY}|${SPACE_FAMILY}|${POSITION_FAMILY}|${RADIUS_FAMILY}|${TYPE_FAMILY})(?:-(.+))?$`);
/** `text-`, `border-` and `font-` also name colours, styles and families:
 *  only a size, a width or a weight counts. */
const TEXT_SIZE = /^text-(?:xs|sm|base|lg|\d*xl|\[(?:length:)?[^\]]*\d[^\]]*\])$/;
const BORDER_WIDTH = /^border(?:-[xytrblse])?(?:-(?:\d+|\[[^\]]*\d[^\]]*\]))?$/;
const FONT_WEIGHT = /^font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black|\[\d+\])$/;
/** A value off Tailwind's scale: a number, an arbitrary value, `px`, or a named
 *  step (`rounded-md`, `leading-tight`, `max-w-xs`). Anything else is a layout
 *  keyword (`full`, `auto`, `screen`) or one of ours (`h-chat`), with no number. */
const SCALE_VALUE = /\d|^\[|^(?:px|xs|sm|md|lg|xl|base|none|tight|snug|normal|relaxed|loose|tighter|wide|wider|widest)$/;
/** Zero is a number, except the layout keywords the spec names (Interfaces: `min-w-0`). */
const LAYOUT_CLASS = /^min-[wh]-0$/;
/** A palette variable with its app fallback (`bg-[var(--inf-card,var(--color-bg-elev-1))]`,
 *  InflowwPalette) is a colour, not Geometry, though the fallback's name has a digit.
 *  The one exemption, for R1 and R4 alike: a colour utility, and a fallback that is an
 *  app colour or the one rule mix, so no size can hide in it (`w-[var(--inf-x,390px)]`). */
const PALETTE_VAR = new RegExp("^(?:bg|text|border|fill|stroke|ring)-\\[(?:color:)?var\\(--inf-[a-z-]+," +
  "(?:var\\(--color-[a-z0-9-]+\\)|color-mix\\(in_oklab,var\\(--color-border\\)_40%,transparent\\))\\)\\](?:/\\d+)?$");

/** A class's utility, after its variants (`md:`, `@min-[886px]:`) and without `!`. */
const utilityOf = (cls: string) => cls.replace(/^(?:(?:[^:[\]]|\[[^\]]*\])*:)*/, "").replace(/^!|!$/g, "");

/** The whole class around `src[start, end)`: out to the nearest space or quote. */
function classAround(src: string, start: number, end: number): string {
  while (start > 0 && !/[\s"'`{}]/.test(src[start - 1])) start--;
  while (end < src.length && !/[\s"'`{}]/.test(src[end])) end++;
  return src.slice(start, end);
}

function carriesGeometry(cls: string): boolean {
  const utility = utilityOf(cls);
  if (LAYOUT_CLASS.test(utility) || PALETTE_VAR.test(utility)) return false;
  if (TEXT_SIZE.test(utility) || BORDER_WIDTH.test(utility) || FONT_WEIGHT.test(utility)) return true;
  const m = GEOMETRY_UTILITY.exec(utility);
  if (!m) return false;
  if (m[2] === undefined) return /^rounded/.test(m[1]); // bare `rounded`; a bare `p` or `w` is no class
  return SCALE_VALUE.test(m[2]);
}

/** The balanced `open…close` span starting at `src[at]`. */
function balanced(src: string, at: number, open: string, close: string): string {
  let depth = 0;
  for (let i = at; i < src.length; i++) {
    if (src[i] === open) depth++;
    else if (src[i] === close && --depth === 0) return src.slice(at, i + 1);
  }
  return src.slice(at);
}

/** The top-level `name: value` pairs of an object literal's body. */
function properties(body: string): { at: number; name: string; value: string }[] {
  const out: { at: number; name: string; value: string }[] = [];
  let depth = 0;
  let start = 0;
  const inner = body.slice(1, -1);
  const flush = (end: number) => {
    const m = /^(\s*)([A-Za-z]+)\s*:\s*([\s\S]*?)\s*$/.exec(inner.slice(start, end));
    if (m) out.push({ at: 1 + start + m[1].length, name: m[2], value: m[3] });
  };
  for (let i = 0; i < inner.length; i++) {
    const c = inner[i];
    if ("([{".includes(c)) depth++;
    else if (")]}".includes(c)) depth--;
    else if (c === "`" || c === '"' || c === "'") {
      // Skip the literal, escapes included; an unclosed one ends the scan.
      let j = i + 1;
      while (j < inner.length && inner[j] !== c) j += inner[j] === "\\" ? 2 : 1;
      i = j;
    }
    else if (c === "," && depth === 0) { flush(i); start = i + 1; }
  }
  flush(inner.length);
  return out;
}

const lineAt = (src: string, offset: number) => src.slice(0, offset).split("\n").length;

/** A name as a regex source. */
const escaped = (name: string) => name.replace(/\$/g, "\\$");

/** `MP.` or one of `aliases`, as a regex source. */
const tokenPattern = (aliases: Set<string>) =>
  `(?:MP\\.${[...aliases].map((a) => `|${escaped(a)}\\b`).join("")})`;

/** An import specifier of ours → its module, relative to the app root, by the
 *  walk's own resolution (`index.tsx` included), or null when it names no file. */
function resolveRel(spec: string, fromRel: string): string | null {
  const file = resolveSpec(spec, fromRel);
  return file && /\.[jt]sx?$/.test(file) && existsSync(join(APP, file)) ? file : null;
}

/**
 * The names through which a module reads a token: a same-file alias (`const G =
 * MP.fanTabs`, `const { row } = MP.fanList`), a constant built on one (`const
 * ICON = cn(MP.chatHeader.iconButton, …)`, `cn(MENU_PANEL, …)`), and a named
 * import of such a constant from a module of ours (`MENU_ROW` from `./MenuParts`,
 * beside a default import too), or a re-export of one (`export { X } from`).
 */
const ALIAS_MEMO = new Map<string, Set<string>>();
function tokenAliases(rel: string, src: string): Set<string> {
  const aliases = new Set([
    ...[...src.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*MP\b/g)].map((m) => m[1]),
    ...[...src.matchAll(/\b(?:const|let)\s+\{([^}]*)\}\s*=\s*MP\b/g)]
      .flatMap((m) => m[1].split(",").map((n) => n.split(":").pop()!.trim()).filter(Boolean)),
  ]);
  for (const m of src.matchAll(/\b(?:import|export)\s+(?:type\s+)?(?:[A-Za-z_$][\w$]*\s*,\s*)?\{([^}]*)\}\s*from\s*["']((?:\.{1,2}|@)\/[^"']+)["']/g)) {
    const from = resolveRel(m[2], rel);
    if (!from) continue;
    if (!ALIAS_MEMO.has(from)) {
      ALIAS_MEMO.set(from, new Set()); // an import cycle reads as no token
      ALIAS_MEMO.set(from, tokenAliases(from, stripComments(readFileSync(join(APP, from), "utf8"))));
    }
    for (const spec of m[1].split(",")) {
      const [name, local = name] = spec.trim().split(/\s+as\s+/);
      if (name && ALIAS_MEMO.get(from)!.has(name)) aliases.add(local.trim());
    }
  }
  // `const X = cn(…)` with a token among its arguments, to a fixed point
  // (`CHAT = cn(PANEL, …)`, `PANEL = cn(MP.…)`).
  for (let grew = true; grew;) {
    grew = false;
    const ref = new RegExp(`(?<![\\w$.])${tokenPattern(aliases)}`);
    for (const m of src.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*cn\(/g)) {
      if (!aliases.has(m[1]) && ref.test(balanced(src, m.index! + m[0].length - 1, "(", ")"))) {
        aliases.add(m[1]);
        grew = true;
      }
    }
  }
  return aliases;
}

/** R1 to R4 over one module's comment-free source, as `file:line rule text`. */
function guardHits(rel: string, source = readFileSync(join(APP, rel), "utf8")): string[] {
  const src = stripComments(source);
  const hits = new Set<string>();
  const hit = (offset: number, rule: string, text: string) =>
    hits.add(`${rel}:${lineAt(src, offset)} ${rule} ${text.replace(/\s+/g, " ")}`);
  const numericConsts = new Set([...src.matchAll(
    /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*number\s*)?=\s*-?\d[\d_.]*\s*[;,\n]/g)].map((m) => m[1]));
  // R1: a Tailwind arbitrary value with a digit, except a palette variable (`PALETTE_VAR`).
  for (const m of src.matchAll(/-\[[^\]\s]*\d[^\]\s]*\]/g)) {
    if (!PALETTE_VAR.test(utilityOf(classAround(src, m.index!, m.index! + m[0].length)))) hit(m.index!, "R1", m[0]);
  }
  // R2: a style object's geometry property given a magic number.
  for (const s of src.matchAll(/\bstyle=\{\{/g)) {
    const at = s.index! + "style={".length;
    for (const p of properties(balanced(src, at, "{", "}"))) {
      if (GEOMETRY_PROP.test(p.name) && magic(p.value, numericConsts)) hit(at + p.at, "R2", `${p.name}: ${p.value}`);
    }
  }
  // R3: a size, width or height attribute given a magic number.
  for (const m of src.matchAll(/(?<=\s)(size|width|height)=(?:"([^"]*)"|\{)/g)) {
    const value = m[2] !== undefined ? m[2] : balanced(src, m.index! + m[1].length + 1, "{", "}").slice(1, -1);
    if (m[2] !== undefined ? /^\d[\d.]*$/.test(value) : magic(value, numericConsts)) {
      hit(m.index!, "R3", m[2] !== undefined ? m[0] : `${m[1]}={${value}}`);
    }
  }
  // R4: a class list that reads a token adds no Geometry class beside it.
  const tokenRef = new RegExp(`(?<![\\w$.])${tokenPattern(tokenAliases(rel, src))}`);
  const lists = [
    ...[...src.matchAll(/\bcn\(/g)].map((m) => ({ at: m.index! + 2, text: balanced(src, m.index! + 2, "(", ")") })),
    ...[...src.matchAll(/\bclassName=\{/g)].map((m) => ({ at: m.index! + 10, text: balanced(src, m.index! + 10, "{", "}") })),
  ].filter((l) => tokenRef.test(l.text));
  for (const l of lists) {
    for (const s of l.text.matchAll(/"([^"]*)"|'([^']*)'|`([^`]*)`/g)) {
      const literal = (s[1] ?? s[2] ?? s[3]).replace(/\$\{[^}]*\}/g, " ");
      for (const c of literal.matchAll(/\S+/g)) {
        if (carriesGeometry(c[0])) hit(l.at + s.index! + 1 + c.index!, "R4", c[0]);
      }
    }
  }
  return [...hits];
}

describe("the magic-number guard (spec D2 part 3; Seam 1 items 3 and 4)", () => {
  it("computes its scope from the routes: the message list, Fan insights and the Messages Pro tree are in, the app shell is out", () => {
    // Fail closed: an import the walk cannot follow would shrink the scope silently.
    expect([...MP_WALK.unresolved, ...OTHER_WALK.unresolved]).toEqual([]);
    expect(MP_SEEDS).toContain("app/messages-pro/page.tsx");
    expect(OTHER_SEEDS).toContain("app/layout.tsx");
    // "Open in a new window" (ticket 112) and the Fan List's modules (ticket
    // 113) are shared with Group chat (`/group` reaches them), and the
    // Composer's modules (ticket 117) with every screen that imports
    // `sanitizePriceInput`: they are in scope because they read the token module.
    for (const member of ["components/chat/MessageList.tsx", "components/chat/FanDrawer.tsx",
                          "components/chat/MessagesPro.tsx", "app/messages-pro/page.tsx",
                          "components/chat/OpenInNewWindowMenu.tsx",
                          ...["FanList", "FanListHeader", "FanListFilters", "FanListStates", "FanRow",
                              "SplitInbox", "FolderPicker"].map((m) => `components/chat/${m}.tsx`),
                          ...["Composer", "ComposerToolbar", "PpvRow", "TimedMessagePopover", "ReplyStrip"]
                            .map((m) => `components/chat/${m}.tsx`)]) {
      expect(SCOPE, `${member} is in scope`).toContain(member);
    }
    expect(SCOPE).not.toContain("components/shell/AppShell.tsx");
    // The top bar's bell takes the Fan List buttons' Geometry by class-name
    // props (spec, Shared modules), so it does not read the module.
    expect(SCOPE).not.toContain("components/NotificationBell.tsx");
    // So does the Vault picker, from the Composer (story 36): its other
    // screens keep their own numbers.
    expect(SCOPE).not.toContain("components/chat/VaultPicker.tsx");
    expect(SCOPE).not.toContain("lib/messagesPro.ts");
    expect(SCOPE).not.toContain("lib/messagesProOurs.ts"); // `MP.ours`, since ticket 118
    expect(SCOPE.filter(isTest)).toEqual([]);
  });

  it("R1 to R4 find no hit anywhere in the scope", () => {
    // The rules, on synthetic source, so a rule that matches nothing cannot pass.
    const sample = [
      '<div className="w-[390px] bg-[var(--inf-card,var(--color-bg-elev-1))]/40 w-[var(--x2)] w-[var(--inf-x,390px)]' +
        ' p-[var(--inf-pad,var(--color-bg-elev-1))] bg-[var(--inf-x,12px)] hover:text-[var(--inf-accent-text,var(--color-accent))]" />',
      "const W = 320;",
      "<div style={{ width: W, height: 12, top: \"4px\", flex: 1, left: `${x}%`,",
      "  minHeight: open ? 320 : 0, maxWidth: Math.max(2, x) }} />",
      '<Icon size={14} /> <svg width="16" /> <Icon size={open ? 14 : 16} /> <Icon size={s} />',
      'cn(MP.fanList.row, "px-4 min-w-0 rounded-md text-sm p-0 font-bold border md:w-full top-full w-[var(--inf-x,390px)]")',
      'cn(MP.fanList.row, "flex text-muted border-border text-left h-chat border-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))]")',
      "const G = MP.fanTabs;",
      'cn(G.tab, "gap-2")',
      "// w-[1px] in a comment",
      '<p style={{ content: "a\\"b", width: 2 }} />',
      '<p style={{ top: "4px }} />',
      'import { MENU_ROW as ROW } from "./components/chat/MenuParts";',
      'cn(ROW, "px-4")',
      'const TAB = cn(G.tab, "flex");',
      'const BIG_TAB = cn(TAB, "grow");',
      'cn(BIG_TAB, "mt-1")',
      'const LOOSE = cn("flex", open && MP.fanTabs.tab);',
      'cn(LOOSE, "mt-1")',
      'const PLAIN = cn("flex", TABS);',
      'cn(PLAIN, "mt-1")',
      'import Parts, { MENU_ITEM as ITEM } from "./components/chat/MenuParts";',
      'cn(ITEM, "px-4")',
    ].join("\n");
    expect(guardHits("x.tsx", sample)).toEqual([
      "x.tsx:1 R1 -[390px]",
      "x.tsx:1 R1 -[var(--x2)]", // a variable that is not the palette's is still caught
      // A palette variable off a colour utility, or with a fallback that is no app colour, is no exemption.
      "x.tsx:1 R1 -[var(--inf-x,390px)]",
      "x.tsx:1 R1 -[var(--inf-pad,var(--color-bg-elev-1))]",
      "x.tsx:1 R1 -[var(--inf-x,12px)]",
      "x.tsx:6 R1 -[var(--inf-x,390px)]",
      "x.tsx:3 R2 width: W",
      "x.tsx:3 R2 height: 12",
      'x.tsx:3 R2 top: "4px"',
      "x.tsx:4 R2 minHeight: open ? 320 : 0",
      // An escaped quote is skipped, and an unclosed one (line 12) ends the scan, not the run.
      "x.tsx:11 R2 width: 2",
      "x.tsx:5 R3 size={14}",
      'x.tsx:5 R3 width="16"',
      "x.tsx:5 R3 size={open ? 14 : 16}",
      // Scale or arbitrary, with or without a digit; `min-w-0` and `full` are layout keywords.
      ...["px-4", "rounded-md", "text-sm", "p-0", "font-bold", "border", "w-[var(--inf-x,390px)]"]
        .map((c) => `x.tsx:6 R4 ${c}`),
      "x.tsx:9 R4 gap-2", // through an alias
      // Through a constant built on a token anywhere in its `cn`, imported (line
      // 14) or same-file, to any depth; one built on no token is no alias (line 21).
      "x.tsx:14 R4 px-4",
      "x.tsx:17 R4 mt-1",
      "x.tsx:19 R4 mt-1",
      "x.tsx:23 R4 px-4", // beside a default import
    ]);
    // A re-export hands the constant on (`export { X } from`).
    expect(tokenAliases("y.tsx", 'export { MENU_ROW as ROW } from "./components/chat/MenuParts";').has("ROW")).toBe(true);

    // No exception list (ticket 119): every module of the scope, whole.
    expect(SCOPE.flatMap((f) => guardHits(f))).toEqual([]);
  });
});

/* ── Consumption (spec D2 part 4; Seam 1 item 5) ─────────────────────────────
 *
 * A token nothing reads fails, so the snapshot cannot pass over a Region
 * nobody wired, and a removed reader cannot leave it green (review B14). */

/** A module's comment-free source, or "" when no such file exists. */
const sourceOf = (rel: string) =>
  /\.[jt]sx?$/.test(rel) && existsSync(join(APP, rel)) ? stripComments(readFileSync(join(APP, rel), "utf8")) : "";

/** The module a JSX tag `<Name` in `rel` renders: a static import of `Name`
 *  (named or default), or `const Name = …import("…")…` (`next/dynamic`). */
function tagModule(name: string, src: string, rel: string): string | null {
  const n = escaped(name);
  const spec =
    new RegExp(`\\bimport\\s+(?:type\\s+)?(?:${n}\\b[^;]*?|[^;]*?\\{[^}]*?\\b${n}\\b[^}]*\\}[^;]*?)from\\s*["']([^"']+)["']`).exec(src) ??
    new RegExp(`\\b(?:const|let)\\s+${n}\\s*=[^;]*?\\bimport\\(\\s*["']([^"']+)["']`).exec(src);
  return spec ? resolveSpec(spec[1], rel) : null;
}

/**
 * The `<region>.<element>` names one scope file's comment-free source reads:
 * `MP.<region>.<element>`; through a same-file alias (`const G = MP.fanList`,
 * then `G.row`); and through a Region handed whole to a component as a prop
 * (`<VaultPicker … sheet={MP.sheet}` in `Composer`), whose leaves count where
 * that tag's module, resolved through its import, reads them off the prop
 * (`sheet?.pickerHead` in `VaultPicker`), and nowhere else. A `cn(MP…)`
 * constant (`MENU_ROW`, `CHIP_SCROLLER`) and an object of leaves handed to a
 * prop (`classNames={BELL}`) name each token as source text already.
 */
function leavesRead(src: string, rel: string, readModule = sourceOf): Set<string> {
  const read = new Set<string>();
  const via = (holder: string, region: string, text: string) => {
    for (const m of text.matchAll(new RegExp(`(?<![\\w$.])${holder}\\??\\.([A-Za-z_$][\\w$]*)`, "g"))) {
      read.add(`${region}.${m[1]}`);
    }
  };
  for (const region of Object.keys(MEASURED)) {
    via(`MP\\.${region}`, region, src);
    for (const a of src.matchAll(new RegExp(`\\b(?:const|let)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*MP\\.${region}(?![\\w$.])`, "g"))) {
      via(escaped(a[1]), region, src);
    }
    for (const p of src.matchAll(new RegExp(`(?<=\\s)([A-Za-z_$][\\w$]*)=\\{\\s*MP\\.${region}\\s*\\}`, "g"))) {
      const tag = [...src.slice(0, p.index).matchAll(/<([A-Z][\w$]*)/g)].pop();
      const receiver = tag && tagModule(tag[1], src, rel);
      if (receiver) via(escaped(p[1]), region, readModule(receiver));
    }
  }
  return read;
}

/** A `MP.ours` group's component file: `<Group>.tsx` in scope, or else the
 *  scope file that declares the component (`FanAvatarMenu` in `AvatarMenu.tsx`). */
function groupFile(group: string): string | undefined {
  return SCOPE.find((f) => f.endsWith(`/${group}.tsx`)) ??
    SCOPE.find((f) => new RegExp(`\\b(?:function|const|let)\\s+${escaped(group)}\\b`)
      .test(sourceOf(f)));
}

describe("consumption (spec D2 part 4; Seam 1 item 5)", () => {
  it("counts a direct read, a same-file alias and a Region handed whole to a prop", () => {
    const sample = [
      "const G = MP.fanList;",
      'cn(G.row, "flex"); <p className={MP.menu.panel} />',
      'import { Picker } from "./Picker";',
      'const Lazy = dynamic(() => import("./Lazy").then((m) => m.Lazy));',
      "<Picker open sheet={MP.sheet} /> <Lazy box={MP.composer} />",
      "const H = MP.fanTabsX;",
    ].join("\n");
    // The receivers are sample source too; an unrelated module's `sheet.panel` is not read.
    const modules: Record<string, string> = {
      "components/chat/Picker": "cn(sheet?.pickerHead); sheet.pickerTile",
      "components/chat/Lazy": "box.send",
      "components/chat/Other": "sheet.panel",
    };
    const read = leavesRead(sample, "components/chat/x.tsx", (f) => modules[f] ?? "");
    for (const leaf of ["fanList.row", "menu.panel", "sheet.pickerHead", "sheet.pickerTile", "composer.send"]) {
      expect(read.has(leaf), leaf).toBe(true);
    }
    expect(read.has("sheet.panel")).toBe(false);
    // An alias reads only what it names; a Region's name is matched whole.
    expect(read.has("fanList.name")).toBe(false);
    expect([...read].some((l) => l.startsWith("fanTabs."))).toBe(false);
  });

  it("every measured leaf is read by a file in the scope", () => {
    const read = new Set(SCOPE.flatMap((f) => [...leavesRead(sourceOf(f), f)]));
    expect(Object.keys(leaves(MEASURED)).filter((leaf) => !read.has(leaf))).toEqual([]);
  });

  it("every MP.ours group is read in its component's file", () => {
    const unread = Object.keys(OURS).filter((group) => {
      const file = groupFile(group);
      return !file || !new RegExp(`(?<![\\w$.])MP\\.ours\\.${group}(?![\\w$])`)
        .test(sourceOf(file));
    });
    expect(unread.map((g) => `ours.${g}`)).toEqual([]);
  });
});
