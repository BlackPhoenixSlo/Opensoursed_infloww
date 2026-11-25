import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { MP } from "./messagesPro";
import { APP_ROOT as APP, importsOf, reachable, resolveSpec, stripComments } from "@/test-import-graph";


function sources(dir: string): [string, string][] {
  return readdirSync(join(APP, dir), { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".tsx") && !/\.test\.tsx$/.test(f))
    .map((f) => [join(dir, f), readFileSync(join(APP, dir, f), "utf8")]);
}

const PANE_SOURCES = [...sources("app/messages-pro"), ...sources("components/chat")];

const EXPECTED = {
  panes: {
    root: "text-sm leading-[1.4]",
    fanList: "lg:w-100 lg:min-w-100 border-r",
    insights: "lg:w-70 lg:min-w-70 lg:border-l",
    pinnedOverlay: "w-full max-w-100",
  },
  windowHeader: {
    bar: "h-11 min-h-11 px-3.5 border-b",
    home: "ml-1 w-41 h-6 gap-1.75 rounded-tl-lg text-[13px] font-semibold [clip-path:polygon(0_0,calc(100%-10px)_0,100%_100%,0_100%)]",
    homeIcon: "size-3.75",
    allModels: "mb-1.25 ml-0.5 gap-1.75 h-7.5 px-3.5 rounded-lg text-[13px] font-bold",
    allModelsIcon: "size-4",
    addCreator: "gap-1.75 px-3.5 text-[13px] font-medium",
    addCreatorIcon: "size-3.75",
    right: "gap-3.5",
    sfw: "gap-0.75",
    sfwLabel: "text-[10px] font-semibold tracking-[.5px]",
    switch: "w-6.5 h-3.5 rounded-lg",
    switchKnob: "top-0.5 left-0.5 size-2.5 rounded-full",
    switchKnobOn: "translate-x-3",
  },
  creatorTabs: {
    strip: "gap-1 max-w-[58vw]",
    tab: "gap-2 h-9 pl-1.5 pr-2.5 max-w-55 rounded-t-[9px] border border-b-0",
    tabActive: "inset-shadow-[0_2px_0]",
    avatar: "size-6.5 rounded-md text-[11px] font-extrabold",
    name: "text-[13px] font-bold",
    badge: "min-w-4 h-4 px-1 rounded-full text-[10px] font-bold",
    close: "size-4 ml-0.5",
    empty: "px-2.5 text-[12px]",
  },
  fanTabs: {
    bar: "h-8 min-h-8 pr-3.5 border-b",
    strip: "gap-0.75 ml-1",
    tab: "gap-2 py-1.75 px-2.75 max-w-47.5 rounded-t-lg border border-b-0 text-[12.5px] font-semibold leading-[1.4]",
    tabActive: "inset-shadow-[0_2px_0]",
    dot: "size-1.75 rounded-full",
    close: "px-1 py-0.5 rounded-sm text-[11px] leading-none",
  },
  fanList: {
    head: "h-13 pl-2.75 pr-3 gap-3 border-b",
    title: "text-[20px] font-medium",
    iconButton: "size-9 md:size-6.5 rounded-[7px]",
    iconButtonIcon: "size-5",
    gallery: "size-9 md:size-6.5 rounded-[7px]",
    buttons: "gap-7 pt-4.5 px-2.5 pb-2.5",
    button: "h-7 gap-1.5 rounded-sm text-[14px] font-medium",
    buttonIcon: "size-4",
    notifBadge: "-top-2.5 -right-2.5 min-w-5 h-5 px-1.5 rounded-full text-[13px] font-medium border",
    buttonPressed: "ring-2",
    filters: "gap-x-2.5 gap-y-1.5 px-2.75 pb-3",
    inbox: "gap-2 px-2.75 h-8.5 rounded-sm text-[14px] min-w-37.5 border",
    inboxIcon: "size-4",
    gear: "w-9 h-8.5 rounded-sm",
    gearIcon: "size-4.75",
    sort: "gap-2.25 text-[14px]",
    sortIcon: "size-4.25",
    chips: "gap-2.5 px-2.75 pb-3",
    chip: "px-3 py-1.5 min-h-[36px] md:h-6.5 md:py-0 md:min-h-0 rounded-2xl text-[14px]",
    chipBadge: "-top-2 -right-1.5 min-w-4 h-4 px-0.75 rounded-full text-[11px] font-medium",
    row: "h-24 gap-2.5 px-4.75 pt-4 after:absolute after:bottom-0 after:left-15 after:right-2.25 after:h-px",
    avatar: "size-10 rounded-full text-[13px] font-bold",
    avatarIcon: "size-5.5",
    onlineDot: "bottom-0 right-0 size-2.5 rounded-full border",
    spend: "top-full left-1/2 -translate-x-1/2 mt-1 h-4 px-1 rounded-xs text-[13px] leading-4 font-bold",
    top: "gap-1.25",
    name: "text-[15px] font-medium max-w-42.5",
    handle: "text-[15px]",
    verified: "size-3.5",
    notWired: "text-[16px] leading-none",
    offLabel: "mt-0.75 text-[11px] font-extrabold tracking-[.5px]",
    newBadge: "px-1.5 py-0.5 rounded-[5px] text-[9px] font-bold tracking-[.03em]",
    bottom: "gap-1.5 mt-5",
    preview: "gap-1.25 text-[14px]",
    previewUnread: "font-semibold",
    time: "text-[14px]",
    unreadDot: "size-2.25 rounded-full",
    oweDot: "size-2.25 rounded-full ring-2",
    edgeMarker: "left-1.25 top-9 -translate-y-1/2",
    accountDot: "left-1.5 top-4 size-2 rounded-full border",
    muteIcon: "size-3.5",
    empty: "px-4 py-6 text-[13px]",
    skeletonRow: "h-24 gap-2.5 px-4.75 border-b",
    skeletonAvatar: "size-10 rounded-full",
    skeletonLines: "gap-2.5",
    skeletonBar: "h-2.75 rounded-md",
    skeletonBarShort: "w-[52%]",
    skeletonBarLong: "w-[78%]",
    loadMore: "px-4 py-3.5 text-[13px] font-semibold border-t",
    splitSelect: "h-9.5 pl-3 pr-8 rounded-[9px] text-[13.5px] border",
  },
  chatHeader: {
    bar: "grid-cols-[auto_auto_minmax(0,1fr)_auto] gap-y-1 min-h-13 px-3 py-1 md:h-13 md:px-5 md:py-0 border-b",
    back: "size-5",
    backButton: "size-9 -ml-2.5 mr-0.75 rounded-lg",
    nameRow: "gap-1.5",
    name: "text-[18px] font-semibold leading-6",
    verified: "size-2.5",
    editName: "size-3.5",
    editNameSlot: "-ml-px",
    editNameAfterBadge: "ml-0.5",
    editNameTarget: "-inset-1.25",
    status: "gap-1.5 text-[10px] leading-3.5",
    statusDot: "size-1.5 rounded-full",
    tools: "h-3.5",
    divider: "w-px h-3 mx-2.5",
    lineIcon: "size-3.5",
    lineTarget: "p-1.25 -m-1.25",
    iconButton: "size-7.5 rounded-[7px]",
    iconButtonIcon: "size-4",
    label: "gap-0.75 text-[10px] leading-3.5",
    labelIcon: "size-3.25",
    labelText: "sr-only @min-[448px]:not-sr-only",
    right: "gap-1",
    openNew: "gap-1.5 py-1.5 px-2 rounded-[7px] text-[13px] font-semibold leading-[1.4]",
    openNewIcon: "size-3.5",
    kebab: "md:-mr-3.5",
    kebabIcon: "size-4.75",
  },
  menu: {
    panel: "min-w-59.5 max-w-90 max-h-[72vh] rounded-[10px] p-1.5 text-[13px] border",
    row: "gap-2.25 px-2.5 py-3 md:py-2 rounded-[7px] leading-[1.3]",
    head: "px-2.5 pt-2 pb-1 text-[10.5px] font-bold tracking-[.5px]",
    divider: "h-px mx-0.5 my-1.25",
    avatar: "size-5.5 rounded-[5px] text-[9px] font-extrabold",
    meta: "text-[11px]",
  },
  sheet: {
    panel: "md:w-[min(900px,92vw)] md:max-h-[84vh] md:rounded-[14px] md:border",
    head: "gap-2.5 px-4 py-3.25 text-[14px] font-bold border-b",
    pickerHead: "md:py-3.25",
    pickerTitle: "md:text-[14px] md:font-bold",
    close: "px-1.5 py-0.5 rounded-md text-[17px] leading-none",
    body: "py-3.5 px-4 min-h-22.5 text-[13px]",
    grid: "grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2.5",
    pickerGrid: "md:grid-cols-[repeat(auto-fill,minmax(118px,1fr))] md:gap-2.5",
    tile: "rounded-[9px] border",
    pickerTile: "md:rounded-[9px]",
    tileTag: "left-1.5 bottom-1.5 rounded-md py-0.5 px-1.5 text-[10.5px] font-bold",
  },
  messageList: {
    body: "px-2 py-3 gap-2 md:px-6.5 md:py-5.5 md:gap-3.5",
    bubbleColumn: "max-w-[88%] md:max-w-[60%]",
    bubble: "rounded-2xl px-3 py-2 text-sm md:rounded-[6px] md:px-2.5 md:py-2.5 md:text-base md:leading-5",
    bubbleTailIn: "rounded-bl-md md:rounded-bl-none",
    bubbleTailOut: "rounded-br-md md:rounded-br-none",
    time: "mt-1.25 text-[11px] leading-[15px] md:mt-0.5 md:leading-[14px]",
    seen: "ml-1.25 text-[10px]",
    sentBy: "ml-1.75 text-[10px] font-bold",
    meta: "text-[12.5px]",
    ppv: "max-w-80 gap-2 px-4 py-3.5 rounded-[14px] border",
    ppvTitle: "font-semibold",
    paidTag: "text-[12px] font-semibold",
    actionsIn: "ml-0.75 md:ml-1.75 md:gap-1",
    actionsOut: "md:mr-0.75 md:gap-1.5",
    action: "size-6 rounded md:size-4",
    actionIcon: "size-3.5",
    loadOlder: "mt-0.5 mb-2 px-4 py-1.75 rounded-full text-[12.5px] font-semibold border",
    pinBar: "gap-2 px-4.5 py-1.75 text-[12px] border-b",
    pinBarIcon: "size-3.5",
    pinCount: "font-bold",
    divider: "gap-3",
    dividerLabel: "text-[11px]",
    avatar: "size-9 rounded-full",
    avatarIn: "mr-2",
    avatarOut: "ml-2",
    avatarGlyph: "size-5.5",
    runGap: "md:-mt-3",
    timeRoom: "mb-6 md:mb-5",
  },
  composer: {
    root: "pb-[env(safe-area-inset-bottom)] border-t",
    buttonRow: "h-11 px-3 gap-1.25 border-b",
    buttonRowEnd: "gap-2",
    timed: "ml-2.25",
    buttonRowButton: "size-6.5 rounded-[7px]",
    buttonRowIcon: "size-5",
    pill: "h-6.5 gap-1.5 px-2 rounded-[3px] text-sm font-normal",
    pillLabel: "sr-only @min-[480px]:not-sr-only",
    pillIcon: "size-4",
    input: "p-4 text-base leading-5",
    toolbar: "gap-1.5 py-4 pl-4 pr-3.5",
    toolbarButton: "size-8.5 rounded-[7px]",
    toolbarIcon: "size-5",
    send: "h-8 px-4.75 rounded-full text-base font-normal",
    aa: "text-[15px] font-extrabold",
    replyStrip: "gap-2.25 px-3 py-2 mb-2 border-l-3 rounded-lg text-[13px]",
    replyStripIcon: "size-3.75",
    replyStripClose: "size-5.5 rounded-md text-[14px]",
  },
  ppvRow: {
    row: "gap-2 px-4 pb-2 text-sm leading-[1.4]",
    label: "font-bold",
    group: "gap-1.25",
    input: "px-2 py-1.25 rounded-[4px] text-base md:text-sm leading-[1.4] border",
    price: "w-21.25 pl-1.25 gap-2.5",
    clear: "px-3 py-1.75 rounded-[7px] text-[12.5px] font-semibold",
    attachment: "size-10.5 rounded-[7px] border",
    attachmentRemove: "px-1 text-[10px] rounded-bl-[5px]",
  },
  insights: {
    head: "px-4 pt-4 pb-2.5 text-[16px] font-bold",
    body: "px-3 pb-3 gap-3",
    block: "p-3.5 rounded-xl border",
    blockHead: "gap-2 mb-3",
    dragIcon: "size-3.5",
    blockTitle: "text-[14px] font-semibold",
    chevron: "size-3.75",
    metric: "py-1.5",
    metricKey: "text-[13.5px]",
    metricValue: "text-[13.5px] font-semibold",
    metricAvg: "text-[12px]",
    metricPlain: "text-[13.5px]",
    spendTop: "mb-1.5",
    spendSplit: "border-l pl-2.25",
    spendLabel: "mb-1.25 text-[12px]",
    spendBig: "text-[22px] font-bold",
    spendSub: "text-[15px]",
    rule: "h-px my-2.5",
    chart: "h-15.5 gap-0.75 mt-1.5 mb-1",
    bar: "rounded-t-xs min-h-0.5",
    axis: "text-[10px]",
    badge: "px-2.25 py-0.75 rounded-[7px] text-[11.5px] font-semibold",
    info: "size-3.5",
    nickEdit: "gap-2",
    pencil: "size-3.25",
    location: "mt-2.5 gap-2 px-2.5 py-2 rounded-lg text-[13px] border",
    locationIcon: "size-3.75",
    tabs: "px-2 pt-2 pb-3",
    tab: "gap-1 py-1.5 rounded-lg text-[12px] font-semibold",
    tabIcon: "size-5",
    salesTable: "text-[12px]",
    salesHead: "px-1.25 py-1 text-[10.5px] font-semibold tracking-[.3px] uppercase border-b",
    salesCell: "px-1.25 py-1.5 border-b",
    note: "min-h-33 p-2.5 rounded-[9px] text-base md:text-[13px] leading-normal border",
  },
  emptyState: {
    root: "gap-5.5",
    icon: "size-25 stroke-1",
    text: "text-[20px]",
  },
};

const EXPECTED_OURS = {
  ComposerToolbar: {
    extrasPop: "right-0 mb-2 max-w-[min(360px,calc(100vw-24px))]",
    popStart: "left-0 mb-2",
  },
  FanDrawer: {
    slideOver: "w-full min-w-0 max-w-[420px] sm:w-[360px] sm:max-w-[360px] border-l",
  },
};

const { ours: OURS, ...MEASURED } = MP;

function leaves(tokens: Record<string, Record<string, string>>): Record<string, string> {
  return Object.fromEntries(Object.entries(tokens).flatMap(([region, elements]) =>
    Object.entries(elements).map(([element, value]) => [`${region}.${element}`, value])));
}

const COLOUR_CLASS = /^(?:[\w@\[\]-]+:)*(?:bg|text|border|ring|fill|stroke|outline|shadow|inset-shadow|divide|placeholder|caret|decoration|from|via|to)-(?:bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current)(?:[-/].*)?$/;
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
    expect(MP.panes).toEqual({
      root: "text-sm leading-[1.4]",
      fanList: "lg:w-100 lg:min-w-100 border-r",
      insights: "lg:w-70 lg:min-w-70 lg:border-l",
      pinnedOverlay: "w-full max-w-100",
    });
  });

  it("each pane root carries its data-mp-pane marker with its MP.panes token, and the pinned overlay keeps no numeric width", () => {
    const tagsWith = (pane: string) => PANE_SOURCES.flatMap(([file, src]) =>
      [...src.matchAll(/<[A-Za-z][^<>]*?data-mp-pane=(?:"([a-z-]+)"|\{[^}]*?"([a-z-]+)"[^}]*\})[^<>]*?>/gs)]
        .filter((m) => (m[1] ?? m[2]) === pane)
        .map((m) => ({ file, tag: m[0] })));

    expect(tagsWith("fan-list").map((t) => t.tag.includes("MP.panes.fanList"))).toEqual([true]);
    expect(tagsWith("insights").map((t) => t.tag.includes("MP.panes.insights"))).toEqual([true]);
    const thread = tagsWith("thread");
    expect(thread.map((t) => t.file).sort()).toEqual(
      ["components/chat/ChatSurface.tsx", "components/chat/ThreadEmptyState.tsx"]);
    const surface = thread.find((t) => t.file.endsWith("ChatSurface.tsx"))!.tag;
    expect(surface).toMatch(/\bflex-1\b/);
    expect(surface).toMatch(/\bmin-w-0\b/);
    expect(surface).toMatch(/@container\b/);

    const [, tree] = PANE_SOURCES.find(([f]) => f === "components/chat/MessagesPro.tsx")!;
    const body = tree.slice(tree.indexOf("export function MessagesPro("));
    const root = /\breturn \(\s*(<[A-Za-z][^<>]*?>)/s.exec(body)?.[1] ?? "";
    expect(root.includes("MP.panes.root")).toBe(true);

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


function filesUnder(dir: string): string[] {
  return readdirSync(join(APP, dir), { recursive: true, encoding: "utf8" })
    .filter((f) => /\.tsx?$/.test(f) && !f.includes("node_modules"))
    .map((f) => join(dir, f));
}

const isTest = (rel: string) => /\.test\.tsx?$/.test(rel);
const rendering = (rel: string) => /^(components|app)\//.test(rel);
const TOKEN_MODULE = "lib/messagesPro.ts";

const ROUTE_FILES = filesUnder("app").filter((f) => /(^|\/)(page|layout)\.tsx$/.test(f)).sort();
const MP_SEEDS = ROUTE_FILES.filter((f) => f.startsWith("app/messages-pro/"));
const OTHER_SEEDS = ROUTE_FILES.filter((f) => !f.startsWith("app/messages-pro/"));
const MP_WALK = reachable(MP_SEEDS, rendering);
const OTHER_WALK = reachable(OTHER_SEEDS, rendering);
const TOKEN_READERS = [...filesUnder("components"), ...filesUnder("app")]
  .filter((f) => importsOf(f).includes(TOKEN_MODULE));
const SCOPE = [...new Set([...MP_WALK.modules.filter((f) => !OTHER_WALK.modules.includes(f)), ...TOKEN_READERS])]
  .filter((f) => f !== TOKEN_MODULE && !isTest(f))
  .sort();

const SIZE_PROP = "(?:min|max)?(?:Width|Height)|width|height";
const SIDE_PROP = "top|right|bottom|left|inset|(?:margin|padding)(?:Top|Right|Bottom|Left|Inline|Block)?(?:Start|End)?";
const TYPE_PROP = "gap|rowGap|columnGap|fontSize|lineHeight|borderRadius|flexBasis";
const GEOMETRY_PROP = new RegExp(`^(?:${SIZE_PROP}|${SIDE_PROP}|${TYPE_PROP})$`);

const NUMBER = /(?<![\w$.])\d[\d_.]*(?![\w$])/;
const STRING = /"[^"]*"|'[^']*'|`[^`]*`/g;

function magic(expr: string, numericConsts: Set<string>): boolean {
  const statics = expr.replace(/\$\{[^}]*\}/g, "");
  const code = statics.replace(STRING, '""');
  if (/[*/+%,]|[\w$)\]]\s*-\s*[\w$(]|[\w$]\s*\(/.test(code)) return false;
  return NUMBER.test(code) || [...statics.matchAll(STRING)].some((s) => /\d/.test(s[0])) ||
    [...code.matchAll(/[A-Za-z_$][\w$]*/g)].some((n) => numericConsts.has(n[0]));
}

const SIZE_FAMILY = "size|(?:min-|max-)?[wh]|basis";
const SPACE_FAMILY = "p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]";
const POSITION_FAMILY = "inset(?:-[xy])?(?!-(?:shadow|ring))|top|right|bottom|left|start|end|translate-[xy]";
const RADIUS_FAMILY = "rounded(?:-(?:[tblrse]|tl|tr|bl|br|ss|se|es|ee))?";
const TYPE_FAMILY = "leading|tracking";
const GEOMETRY_UTILITY = new RegExp(
  `^-?(${SIZE_FAMILY}|${SPACE_FAMILY}|${POSITION_FAMILY}|${RADIUS_FAMILY}|${TYPE_FAMILY})(?:-(.+))?$`);
const TEXT_SIZE = /^text-(?:xs|sm|base|lg|\d*xl|\[(?:length:)?[^\]]*\d[^\]]*\])$/;
const BORDER_WIDTH = /^border(?:-[xytrblse])?(?:-(?:\d+|\[[^\]]*\d[^\]]*\]))?$/;
const FONT_WEIGHT = /^font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black|\[\d+\])$/;
const SCALE_VALUE = /\d|^\[|^(?:px|xs|sm|md|lg|xl|base|none|tight|snug|normal|relaxed|loose|tighter|wide|wider|widest)$/;
const LAYOUT_CLASS = /^min-[wh]-0$/;
const PALETTE_VAR = new RegExp("^(?:bg|text|border|fill|stroke|ring)-\\[(?:color:)?var\\(--inf-[a-z-]+," +
  "(?:var\\(--color-[a-z0-9-]+\\)|color-mix\\(in_oklab,var\\(--color-border\\)_40%,transparent\\))\\)\\](?:/\\d+)?$");

const utilityOf = (cls: string) => cls.replace(/^(?:(?:[^:[\]]|\[[^\]]*\])*:)*/, "").replace(/^!|!$/g, "");

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
  if (m[2] === undefined) return /^rounded/.test(m[1]);
  return SCALE_VALUE.test(m[2]);
}

function balanced(src: string, at: number, open: string, close: string): string {
  let depth = 0;
  for (let i = at; i < src.length; i++) {
    if (src[i] === open) depth++;
    else if (src[i] === close && --depth === 0) return src.slice(at, i + 1);
  }
  return src.slice(at);
}

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

const escaped = (name: string) => name.replace(/\$/g, "\\$");

const tokenPattern = (aliases: Set<string>) =>
  `(?:MP\\.${[...aliases].map((a) => `|${escaped(a)}\\b`).join("")})`;

function resolveRel(spec: string, fromRel: string): string | null {
  const file = resolveSpec(spec, fromRel);
  return file && /\.[jt]sx?$/.test(file) && existsSync(join(APP, file)) ? file : null;
}

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
      ALIAS_MEMO.set(from, new Set());
      ALIAS_MEMO.set(from, tokenAliases(from, stripComments(readFileSync(join(APP, from), "utf8"))));
    }
    for (const spec of m[1].split(",")) {
      const [name, local = name] = spec.trim().split(/\s+as\s+/);
      if (name && ALIAS_MEMO.get(from)!.has(name)) aliases.add(local.trim());
    }
  }
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

function guardHits(rel: string, source = readFileSync(join(APP, rel), "utf8")): string[] {
  const src = stripComments(source);
  const hits = new Set<string>();
  const hit = (offset: number, rule: string, text: string) =>
    hits.add(`${rel}:${lineAt(src, offset)} ${rule} ${text.replace(/\s+/g, " ")}`);
  const numericConsts = new Set([...src.matchAll(
    /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*number\s*)?=\s*-?\d[\d_.]*\s*[;,\n]/g)].map((m) => m[1]));
  for (const m of src.matchAll(/-\[[^\]\s]*\d[^\]\s]*\]/g)) {
    if (!PALETTE_VAR.test(utilityOf(classAround(src, m.index!, m.index! + m[0].length)))) hit(m.index!, "R1", m[0]);
  }
  for (const s of src.matchAll(/\bstyle=\{\{/g)) {
    const at = s.index! + "style={".length;
    for (const p of properties(balanced(src, at, "{", "}"))) {
      if (GEOMETRY_PROP.test(p.name) && magic(p.value, numericConsts)) hit(at + p.at, "R2", `${p.name}: ${p.value}`);
    }
  }
  for (const m of src.matchAll(/(?<=\s)(size|width|height)=(?:"([^"]*)"|\{)/g)) {
    const value = m[2] !== undefined ? m[2] : balanced(src, m.index! + m[1].length + 1, "{", "}").slice(1, -1);
    if (m[2] !== undefined ? /^\d[\d.]*$/.test(value) : magic(value, numericConsts)) {
      hit(m.index!, "R3", m[2] !== undefined ? m[0] : `${m[1]}={${value}}`);
    }
  }
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
    expect([...MP_WALK.unresolved, ...OTHER_WALK.unresolved]).toEqual([]);
    expect(MP_SEEDS).toContain("app/messages-pro/page.tsx");
    expect(OTHER_SEEDS).toContain("app/layout.tsx");
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
    expect(SCOPE).not.toContain("components/NotificationBell.tsx");
    expect(SCOPE).not.toContain("components/chat/VaultPicker.tsx");
    expect(SCOPE).not.toContain("lib/messagesPro.ts");
    expect(SCOPE).not.toContain("lib/messagesProOurs.ts");
    expect(SCOPE.filter(isTest)).toEqual([]);
  });

  it("R1 to R4 find no hit anywhere in the scope", () => {
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
      "x.tsx:1 R1 -[var(--x2)]",
      "x.tsx:1 R1 -[var(--inf-x,390px)]",
      "x.tsx:1 R1 -[var(--inf-pad,var(--color-bg-elev-1))]",
      "x.tsx:1 R1 -[var(--inf-x,12px)]",
      "x.tsx:6 R1 -[var(--inf-x,390px)]",
      "x.tsx:3 R2 width: W",
      "x.tsx:3 R2 height: 12",
      'x.tsx:3 R2 top: "4px"',
      "x.tsx:4 R2 minHeight: open ? 320 : 0",
      "x.tsx:11 R2 width: 2",
      "x.tsx:5 R3 size={14}",
      'x.tsx:5 R3 width="16"',
      "x.tsx:5 R3 size={open ? 14 : 16}",
      ...["px-4", "rounded-md", "text-sm", "p-0", "font-bold", "border", "w-[var(--inf-x,390px)]"]
        .map((c) => `x.tsx:6 R4 ${c}`),
      "x.tsx:9 R4 gap-2",
      "x.tsx:14 R4 px-4",
      "x.tsx:17 R4 mt-1",
      "x.tsx:19 R4 mt-1",
      "x.tsx:23 R4 px-4",
    ]);
    expect(tokenAliases("y.tsx", 'export { MENU_ROW as ROW } from "./components/chat/MenuParts";').has("ROW")).toBe(true);

    expect(SCOPE.flatMap((f) => guardHits(f))).toEqual([]);
  });
});


const sourceOf = (rel: string) =>
  /\.[jt]sx?$/.test(rel) && existsSync(join(APP, rel)) ? stripComments(readFileSync(join(APP, rel), "utf8")) : "";

function tagModule(name: string, src: string, rel: string): string | null {
  const n = escaped(name);
  const spec =
    new RegExp(`\\bimport\\s+(?:type\\s+)?(?:${n}\\b[^;]*?|[^;]*?\\{[^}]*?\\b${n}\\b[^}]*\\}[^;]*?)from\\s*["']([^"']+)["']`).exec(src) ??
    new RegExp(`\\b(?:const|let)\\s+${n}\\s*=[^;]*?\\bimport\\(\\s*["']([^"']+)["']`).exec(src);
  return spec ? resolveSpec(spec[1], rel) : null;
}

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
