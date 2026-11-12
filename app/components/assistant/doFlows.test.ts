import { describe, expect, it } from "vitest";

import { blankRow, rowReducer } from "@/components/compose/premadeRows";
import { initRuleEditor, ruleEditorReducer, buildBody, derive } from "@/components/automations/ruleEditorForm";
import { DO_FLOWS, flowForHref, folderLine, typingFrames, type AgentStep, type MassPremadeSlots } from "./doFlows";

const flow = DO_FLOWS.mass_premade;

/** The owner's pilot: "auto mass to fans every hour, delete after, everyone except mass-exclude, SFW folder,
 *  10 captions, leave it off". */
const PILOT: MassPremadeSlots = {
  name: "Hourly SFW tease",
  interval: { value: 1, unit: "hours" },
  captions: Array.from({ length: 10 }, (_, i) => `caption ${i + 1}`),
  captions_ai: 7,
  folder: { id: 42, name: "SFW teasers", photos: 60, tiers: { sfw: 30, suggestive: 11, explicit: 0, hardcore: 0, unknown: 19 } },
  online_only: false,
  includes: ["fans", "following"],
  excludes: ["9001"],
  unsend_after_hours: 8,
  exclude_last_chat_hours: null,
};

const shape = (steps: AgentStep[]) => steps.map((s) => [s.target, typeof s.action === "string" ? s.action : s.action]);

describe("mass_premade toActions", () => {
  it("turns the pilot slots into the exact steps, in form order", () => {
    const texts = (n: number) => PILOT.captions.slice(0, n);
    const row = (patch: object) => ({ type: "row", a: { type: "patch", patch } });
    expect(shape(flow.toActions(PILOT))).toEqual([
      ["rm-mass_premade-new", "open"],
      ["rm-mass_premade-name", { type: "field", patch: { name: "Hourly SFW tease" } }],
      ["rm-mass_premade-every", { type: "field", patch: { intervalValue: 1 } }],
      // unit "hours" is the blank form's: no step
      ...PILOT.captions.map((_, i) => [`pm-mass_premade-text-${i}`, row({ texts: texts(i + 1) })]),
      ["pm-mass_premade-folder", row({ folderId: "42" })],
      ["pm-mass_premade-online-only", row({ onlineOnly: false })],
      ["pm-mass_premade-unsend", row({ unsendAfterHours: "8" })],
      // exclude_last_chat_hours null, includes = the default audience: no steps
      ["pm-mass_premade-lists-panel", row({ excludes: ["9001"] })],
      ["rm-mass_premade-enabled", { type: "field", patch: { enabled: false, dryRun: false } }],
      ["rm-mass_premade-save", "save"],
    ]);
  });

  it("only the first caption types visibly", () => {
    const steps = flow.toActions(PILOT).filter((s) => s.target.startsWith("pm-mass_premade-text-"));
    expect(steps.map((s) => !!s.typing)).toEqual([true, ...Array(9).fill(false)]);
  });

  const BARE: MassPremadeSlots = {
    name: "", interval: { value: 24, unit: "hours" }, captions: ["hi"], captions_ai: 0, folder: null,
    online_only: true, includes: ["fans", "following"], excludes: [], unsend_after_hours: null, exclude_last_chat_hours: 1,
  };

  it.each<[string, Partial<MassPremadeSlots>, string[]]>([
    ["all defaults: open, one caption, OFF, save", {}, ["rm-mass_premade-new", "pm-mass_premade-text-0", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
    ["minutes: value and unit", { interval: { value: 30, unit: "minutes" } },
      ["rm-mass_premade-new", "rm-mass_premade-every", "rm-mass_premade-unit", "pm-mass_premade-text-0", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
    ["skip-chat 3h", { exclude_last_chat_hours: 3 },
      ["rm-mass_premade-new", "pm-mass_premade-text-0", "pm-mass_premade-last-chat", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
    ["a custom include list", { includes: ["fans", "555"] },
      ["rm-mass_premade-new", "pm-mass_premade-text-0", "pm-mass_premade-lists-panel", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
    ["includes in another order = default", { includes: ["following", "fans"] },
      ["rm-mass_premade-new", "pm-mass_premade-text-0", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
    ["blank captions dropped", { captions: ["  ", "x"] },
      ["rm-mass_premade-new", "pm-mass_premade-text-0", "rm-mass_premade-enabled", "rm-mass_premade-save"]],
  ])("%s", (_, patch, targets) => {
    expect(flow.toActions({ ...BARE, ...patch }).map((s) => s.target)).toEqual(targets);
  });

  it.each([PILOT, BARE])("always ends with Enabled off + Dry run off, right before Save", (slots) => {
    const steps = flow.toActions(slots);
    expect(steps.at(-1)!.action).toBe("save");
    expect(steps.at(-2)!.action).toEqual({ type: "field", patch: { enabled: false, dryRun: false } });
    expect(steps.filter((s) => s.action === "save")).toHaveLength(1);
  });

  it("played into the editor's own reducer, the pilot saves OFF with the asked-for payload", () => {
    let s = initRuleEditor("mass_premade", null);
    for (const step of flow.toActions(PILOT)) if (typeof step.action !== "string") s = ruleEditorReducer(s, step.action);
    const body = buildBody(s)!;
    expect(body.is_enabled).toBe(false);
    expect(body.every_seconds).toBe(3600);
    expect(body.name).toBe("Hourly SFW tease");
    const item = (body.payload as { messages: Record<string, unknown>[] }).messages[0];
    expect(item.texts).toEqual(PILOT.captions);
    expect(item.media_folder_id).toBe(42);
    expect(item.online_only).toBeUndefined();
    expect(item.unsend_after_hours).toBe(8);
    expect(item.user_lists).toEqual(blankRow().includes);
    expect(item.excluded_user_lists).toEqual(["9001"]);
    expect(item.exclude_last_chat_hours).toBe(1); // the default, untouched
    expect("dry_run" in (body.payload as object)).toBe(false);
  });
});

describe("mass_premade extras (price, photo count, More settings)", () => {
  const BASE: MassPremadeSlots = { ...PILOT, excludes: [], online_only: true, unsend_after_hours: null, name: "", captions: ["hi"] };
  const row = (patch: object) => ({ type: "row", a: { type: "patch", patch } });
  const XTRA: MassPremadeSlots = {
    ...BASE, price: 15, media_count: 3, exclude_replied_hours: 0, exclude_inbound_hours: 4, unread_limit: 50,
    recent_chat_hours: 12, recent_chat_limit: 20,
  };

  it("steps after the folder; More settings opened (reveal) before its fields; OFF + save stay last", () => {
    const steps = flow.toActions(XTRA);
    expect(shape(steps).slice(4, -2)).toEqual([
      ["pm-mass_premade-media-count", row({ mediaCount: "3" })],
      ["pm-mass_premade-price", row({ price: "15" })],
      ["pm-mass_premade-more-toggle", "reveal"],
      ["pm-mass_premade-replied", row({ excludeRepliedHours: "0" })],      // an explicit 0 = off
      ["pm-mass_premade-inbound", row({ excludeInboundHours: "4" })],
      ["pm-mass_premade-recent-hours", row({ recentChatHours: "12" })],
      ["pm-mass_premade-recent-limit", row({ recentChatLimit: "20" })],
      ["pm-mass_premade-unread", row({ unreadLimit: "50" })],
    ]);
    expect(steps.at(-2)!.action).toEqual({ type: "field", patch: { enabled: false, dryRun: false } });
  });

  it.each<[string, Partial<MassPremadeSlots>, string[]]>([
    ["nulls make no step", { price: null, media_count: null, unread_limit: null }, []],
    ["1 photo = the default: no step", { media_count: 1 }, []],
    ["no folder: no photo-count step (its box isn't shown)", { folder: null, media_count: 3 }, []],
    ["price without a folder still types (the form warns)", { folder: null, price: 9 }, ["pm-mass_premade-price"]],
    ["one More knob: reveal + it", { unread_limit: 5 }, ["pm-mass_premade-more-toggle", "pm-mass_premade-unread"]],
  ])("%s", (_, patch, want) => {
    const ids = flow.toActions({ ...BASE, ...patch }).map((st) => st.target);
    const extra = ids.filter((t) => /price|media-count|more-toggle|replied|inbound|recent|unread/.test(t));
    expect(extra).toEqual(want);
  });

  it("played into the editor's reducer, the payload carries every extra", () => {
    let st = initRuleEditor("mass_premade", null);
    for (const step of flow.toActions(XTRA)) if (typeof step.action !== "string") st = ruleEditorReducer(st, step.action);
    const item = (buildBody(st)!.payload as { messages: Record<string, unknown>[] }).messages[0];
    expect(item).toMatchObject({ price: 15, media_count: 3, exclude_replied_hours: 0, exclude_inbound_hours: 4,
      unread_limit: 50, recent_chat_hours: 12, recent_chat_limit: 20 });
  });

  it("plan lines say each extra", () => {
    const lines = flow.planLines(XTRA);
    for (const l of ["PPV $15", "3 photos per mass", "Doesn't skip fans you messaged", "Skips fans who messaged you in the last 4h",
      "Adds fans chatted with in the last 12h (up to 20)", "Adds fans with unread messages (up to 50)"]) expect(lines).toContain(l);
    expect(flow.planLines({ ...BASE, folder: null, price: 9 })).toContain("PPV $9 — needs photos: pick a folder");
    expect(lines.at(-1)).toBe("Saved OFF — you turn it on");
  });
});

describe("an unresolved include list (includes: [])", () => {
  const EMPTY = { ...PILOT, includes: [] };
  it("clears the audience in a step (never widened to everyone)", () => {
    const steps = flow.toActions(EMPTY);
    expect(steps.find((s) => s.target === "pm-mass_premade-lists-panel" && typeof s.action !== "string"
      && s.action.type === "row" && s.action.a.type === "patch" && "includes" in s.action.a.patch)?.action)
      .toEqual({ type: "row", a: { type: "patch", patch: { includes: [] } } });
    expect(steps.at(-1)!.action).toBe("save");
  });
  it("so the editor's own gate blocks Save on the audience", () => {
    let s = initRuleEditor("mass_premade", null);
    for (const step of flow.toActions(EMPTY)) if (typeof step.action !== "string") s = ruleEditorReducer(s, step.action);
    expect(derive(s).wait).toBe("audience");
    expect(buildBody(s)).toBeNull();
  });
  it("the plan says to pick it in the form", () => {
    expect(flow.planLines(EMPTY)).toContain("Audience: online and offline fans, audience: pick it in the form, excluding 1 list");
  });
});

describe("typingFrames", () => {
  it("grows the newest caption in chunks, earlier ones whole", () => {
    const step: AgentStep = { target: "t", label: "", typing: true, action: { type: "row", a: { type: "patch", patch: { texts: ["abcdefgh"] } } } };
    const out = typingFrames(step).map((a) => rowReducer(blankRow(), (a as { a: Parameters<typeof rowReducer>[1] }).a).texts);
    expect(out).toEqual([["ab"], ["abcd"], ["abcdef"], ["abcdefgh"]]);
  });
  it("a non-typing step is its own one frame; open/save none", () => {
    const action = { type: "field" as const, patch: { name: "x" } };
    expect(typingFrames({ target: "t", label: "", action })).toEqual([action]);
    expect(typingFrames({ target: "t", label: "", action: "save" })).toEqual([]);
  });
});

describe("flowForHref", () => {
  it.each([
    ["/growth/auto-mass", "mass_premade"],
    ["/growth/auto-mass?creator=1", "mass_premade"],
    ["/growth/auto-mass#steps=New", "mass_premade"],
    ["/growth/auto-post", null],
    ["/growth/auto-massive", null],
  ])("%s → %s", (href, id) => expect(flowForHref(href)).toBe(id));
});

describe("plan lines", () => {
  it("the pilot in plain words", () => {
    expect(flow.planLines(PILOT)).toEqual([
      "Name: Hourly SFW tease",
      "Every hour",
      "Captions: 10 (7 AI-written — edit later)",
      "Folder: SFW teasers — 41/60 flagged · 0 explicit · 19 unknown — likely SFW",
      "Audience: online and offline fans, excluding 1 list",
      "Unsend after 8h",
      "Saved OFF — you turn it on",
    ]);
  });
  it("defaults, minutes, online only, skip-chat, no folder", () => {
    expect(flow.planLines({
      ...PILOT, name: "", interval: { value: 30, unit: "minutes" }, captions: ["a", "b"], captions_ai: 0, folder: null,
      online_only: true, excludes: [], includes: ["fans", "77"], unsend_after_hours: null, exclude_last_chat_hours: 3,
    })).toEqual([
      "Name: Auto mass (default)",
      "Every 30 minutes",
      "Captions: 2",
      "No folder",
      "Audience: online fans only, to All fans + 1 list",
      "Skips fans chatted with in the last 3h",
      "Never unsent",
      "Saved OFF — you turn it on",
    ]);
  });
  it.each([
    [{ sfw: 0, suggestive: 0, explicit: 2, hardcore: 1, unknown: 0 }, 10, "F — 10/10 flagged · 3 explicit · 0 unknown — has explicit photos"],
    [{ sfw: 0, suggestive: 0, explicit: 0, hardcore: 0, unknown: 5 }, 5, "F — 0/5 flagged · 0 explicit · 5 unknown — not flagged yet"],
  ])("folder verdict %#", (tiers, photos, line) => {
    expect(folderLine({ id: 1, name: "F", photos, tiers })).toBe(line);
  });
});
