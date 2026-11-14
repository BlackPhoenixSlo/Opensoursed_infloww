/**
 * "Do it for me" flows (docs/spec/assistant-do-mode.md): what the help bot's runner does for one draft.
 *
 * A flow is a RECIPE over a form's own reducer: `toActions` turns the server's draft slots
 * (POST /admin/assistant/draft) into the editor's existing `RuleEditorAction`s, one AgentStep each, in the order a
 * person would fill the form, plus where the cosmetic cursor points (an element id) and what its bubble says. The
 * runner (useDoRunner.ts) opens the page, dispatches the steps through the agent bridge and saves through the
 * editor's own Save. Pure, so the slots → steps table is tested (doFlows.test.ts).
 *
 * SAFETY: every recipe ends with Enabled OFF (and Dry run off) right before Save — the user's toggle is the go-live
 * (D2). A slot left at the blank form's default makes NO step: the agent never "touches" a default it wasn't asked to
 * change (onlineOnly, excludeLastChatHours, the audience).
 *
 * `mass_edit` (D11, existing rules) is no recipe: no editor, no cursor — the server applies it (massEdit.ts).
 * `auto_story` (D13) fills the Auto Story page's own form (autoStoriesForm.ts): no "open" step — the page IS the form.
 * `report_export` is no recipe either: Download POSTs the report recipe and saves the file (doExport.ts).
 * `full_ai_config` (phase 03c) is no recipe: Apply is one draft PUT (fullAiConfigEdit.ts, useDoRunner.ts).
 */

import type { RuleEditorAction } from "@/components/automations/ruleEditorForm";
import type { Unit } from "@/components/automations/ruleInterval";
import { KIND_COPY } from "@/components/automations/readyMadeContent";
import { blankRow, type Row } from "@/components/compose/premadeRows";
import { SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import { DEFAULT_FORM as STORY_BLANK, type AutoStoriesAction } from "@/components/settings/autoStoriesForm";
import type { AgentKind } from "./agentBridge";
import type { ExportSlots } from "./doExport";
import type { FullAiConfigSlots } from "./fullAiConfigEdit";
import type { MassEditSlots } from "./massEdit";

/** A flow the runner plays in a form (DO_FLOWS). */
export type EditorFlowId = "mass_premade" | "auto_story";
export type DoFlowId = EditorFlowId | "mass_edit" | "report_export" | "full_ai_config";

export interface FolderTiers {
  sfw: number;
  suggestive: number;
  explicit: number;
  hardcore: number;
  unknown: number;
}

/** The mass_premade draft's slots, as the server resolved them (ids, not names). */
export interface MassPremadeSlots {
  name: string;
  interval: { value: number; unit: Unit };
  captions: string[];
  /** How many of `captions` the AI wrote. */
  captions_ai: number;
  folder: null | { id: number | string; name: string; photos: number; tiers: FolderTiers };
  online_only: boolean;
  /** The include list ids, always explicit (default ['fans','following']); [] = a named list the server couldn't
   *  resolve (`unresolved` says which): the audience is cleared and Save's own gate stops. */
  includes: string[];
  excludes: string[];
  unsend_after_hours: number | null;
  exclude_last_chat_hours: number | null;
  /** The optional knobs (absent / null = the form's default). */
  price?: number | null;
  media_count?: number | null;
  exclude_replied_hours?: number | null;
  exclude_inbound_hours?: number | null;
  unread_limit?: number | null;
  recent_chat_hours?: number | null;
  recent_chat_limit?: number | null;
}

/** The auto_story draft's slots (the server fills every key; a key at the blank form's default makes no step). */
export interface AutoStorySlots {
  folder: null | { id: number | string; name: string; photos: number; tiers?: FolderTiers };
  mode: "clock" | "interval";
  /** "HH:MM", clock mode. */
  times: string[];
  every_hours: number;
  per_run: number;
  /** 0 = keep. */
  hours_to_live: number;
  /** null = forever. */
  max_runs: number | null;
}

interface DraftBase {
  id: string;
  summary: string;
  assumptions: string[];
  unresolved: string[];
  /** A human sentence: the flow:null pointer to Q&A, or the error's words. */
  answer: string;
  error: string | null;
}

/** POST /admin/assistant/draft's 200 (always 200). `account_id` null: asked in General (no model) — an export or
 *  no draft. */
export type DoDraft = DraftBase & (
  | { flow: "mass_premade"; account_id: string; slots: MassPremadeSlots | null }
  | { flow: "auto_story"; account_id: string; slots: AutoStorySlots | null }
  | { flow: "mass_edit"; account_id: string; slots: MassEditSlots | null }
  | { flow: "report_export"; account_id: string | null; slots: ExportSlots | null }
  | { flow: "full_ai_config"; account_id: string; slots: FullAiConfigSlots | null }
  | { flow: null; account_id: string | null; slots: null }
);

/** `reveal`: click a disclosure open (only when `aria-expanded="false"`) so the next fields show. */
export type AgentAction<A = RuleEditorAction | AutoStoriesAction> = A | "open" | "save" | "reveal";

/** `A`: the form's own action type (a flow's steps only ever dispatch into its one form). */
export interface AgentStep<A = RuleEditorAction | AutoStoriesAction> {
  /** The element id the cursor goes to. */
  target: string;
  action: AgentAction<A>;
  /** The cursor bubble's words. */
  label: string;
  /** A caption the runner may type in visibly (typingFrames). */
  typing?: boolean;
}

export interface DoFlow<S, A> {
  kind: AgentKind;
  /** The page's name in the runner's messages ("The Auto Mass page didn't open in time"). */
  title: string;
  /** The page's path: a Q&A answer linking here offers the swap. */
  routeBase: string;
  route: (accountId: string) => string;
  toActions: (slots: S) => AgentStep<A>[];
  /** The plan card's plain-words lines. */
  planLines: (slots: S) => string[];
  /** The saved rule's on/off switch, by its aria-label: the done cursor rests on it (never clicks it). */
  savedSwitch: (slots: S) => string;
  /** The done card's line. */
  doneText: string;
}

/** A draft's flow with its slots bound: what the runner and the plan card call. */
export interface BoundFlow {
  kind: AgentKind;
  title: string;
  /** The draft's model: the run opens its page and form. */
  accountId: string;
  route: (accountId: string) => string;
  steps: AgentStep[];
  planLines: string[];
  savedSwitch: string;
  doneText: string;
}

const MP = "mass_premade";
const BLANK = blankRow();
const BLANK_INTERVAL = { value: 24, unit: "hours" as Unit };

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
function rowPatch(patch: Partial<Row>): RuleEditorAction {
  return { type: "row", a: { type: "patch", patch } };
}

function massToActions(s: MassPremadeSlots): AgentStep<RuleEditorAction>[] {
  const steps: AgentStep<RuleEditorAction>[] = [{ target: `rm-${MP}-new`, action: "open", label: "Opening a new Auto Mass…" }];
  const name = s.name.trim();
  if (name) steps.push({ target: `rm-${MP}-name`, action: { type: "field", patch: { name } }, label: "Naming it…" });
  const value = Math.max(1, Math.round(s.interval.value) || 1);
  if (value !== BLANK_INTERVAL.value) {
    steps.push({ target: `rm-${MP}-every`, action: { type: "field", patch: { intervalValue: value } }, label: "Setting the schedule…" });
  }
  if (s.interval.unit !== BLANK_INTERVAL.unit) {
    steps.push({ target: `rm-${MP}-unit`, action: { type: "field", patch: { intervalUnit: s.interval.unit } }, label: "Setting the schedule…" });
  }
  const captions = s.captions.map((c) => c.trim()).filter(Boolean);
  captions.forEach((_, i) => {
    steps.push({
      target: `pm-${MP}-text-${i}`,
      action: rowPatch({ texts: captions.slice(0, i + 1) }),
      label: `Typing captions… ${i + 1}/${captions.length}`,
      ...(i === 0 ? { typing: true } : {}),
    });
  });
  if (s.folder) {
    steps.push({ target: `pm-${MP}-folder`, action: rowPatch({ folderId: String(s.folder.id) }), label: `Picking folder “${s.folder.name}”…` });
    // The count box shows only once a folder is set.
    if (pos(s.media_count) && s.media_count !== 1) {
      steps.push({ target: `pm-${MP}-media-count`, action: rowPatch({ mediaCount: String(s.media_count) }), label: `${s.media_count} photos per mass` });
    }
  }
  if (pos(s.price)) {
    steps.push({ target: `pm-${MP}-price`, action: rowPatch({ price: String(s.price) }), label: `Price $${s.price}` });
  }
  if (s.online_only !== BLANK.onlineOnly) {
    steps.push({
      target: `pm-${MP}-online-only`, action: rowPatch({ onlineOnly: s.online_only }),
      label: s.online_only ? "Online fans only" : "Online and offline fans",
    });
  }
  if (s.unsend_after_hours !== null && s.unsend_after_hours > 0) {
    steps.push({ target: `pm-${MP}-unsend`, action: rowPatch({ unsendAfterHours: String(s.unsend_after_hours) }), label: `Unsend after ${s.unsend_after_hours}h` });
  }
  if (s.exclude_last_chat_hours !== null && String(s.exclude_last_chat_hours) !== BLANK.excludeLastChatHours) {
    const h = s.exclude_last_chat_hours;
    steps.push({
      target: `pm-${MP}-last-chat`, action: rowPatch({ excludeLastChatHours: h > 0 ? String(h) : "" }),
      label: h > 0 ? `Skip fans chatted with in ${h}h` : "Not skipping recent chats",
    });
  }
  // Empty = a named list the server couldn't resolve: cleared, so Save's own gate stops on "no audience" — never
  // left at the default (that would widen it to everyone).
  if (!sameSet(s.includes, BLANK.includes)) {
    steps.push({ target: `pm-${MP}-lists-panel`, action: rowPatch({ includes: [...s.includes] }), label: "Picking who gets it…" });
  }
  if (!sameSet(s.excludes, BLANK.excludes)) {
    steps.push({ target: `pm-${MP}-lists-panel`, action: rowPatch({ excludes: [...s.excludes] }), label: "Excluding lists…" });
  }
  // Behind "More settings": opened first; each set knob one step (the two guards keep an explicit 0 = off).
  const more: AgentStep<RuleEditorAction>[] = [];
  for (const [key, field, id, label] of MORE) {
    const v = s[key];
    const guard = key === "exclude_replied_hours" || key === "exclude_inbound_hours";
    if (typeof v === "number" && (guard ? v >= 0 : v > 0)) {
      more.push({ target: `pm-${MP}-${id}`, action: rowPatch({ [field]: String(v) }), label: label(v) });
    }
  }
  if (more.length) steps.push({ target: `pm-${MP}-more-toggle`, action: "reveal", label: "Opening more settings…" }, ...more);
  // ALWAYS, last before Save: the rule is saved OFF (D2).
  steps.push({ target: `rm-${MP}-enabled`, action: { type: "field", patch: { enabled: false, dryRun: false } }, label: "Leaving it OFF — you turn it on" });
  steps.push({ target: `rm-${MP}-save`, action: "save", label: "Saving…" });
  return steps;
}

const pos = (v: number | null | undefined): v is number => typeof v === "number" && v > 0;

/** The "More settings" knobs: slot key, Row field, element id suffix, cursor label. */
const MORE: Array<[keyof MassPremadeSlots, keyof Row, string, (v: number) => string]> = [
  ["exclude_replied_hours", "excludeRepliedHours", "replied", (v) => (v > 0 ? `Skip fans I messaged in ${v}h` : "Not skipping fans I messaged")],
  ["exclude_inbound_hours", "excludeInboundHours", "inbound", (v) => (v > 0 ? `Skip fans who messaged in ${v}h` : "Not skipping fans who messaged")],
  ["recent_chat_hours", "recentChatHours", "recent-hours", (v) => `Adding fans chatted with in ${v}h`],
  ["recent_chat_limit", "recentChatLimit", "recent-limit", (v) => `At most ${v} recent-chat fans`],
  ["unread_limit", "unreadLimit", "unread", (v) => `Adding fans with unread, up to ${v}`],
];

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const SYSTEM_LABEL = new Map(SYSTEM_AUDIENCES.map((a) => [a.id, a.label]));

/** "Spring tease — 41/60 flagged · 0 explicit · 19 unknown — likely SFW". Never "safe": the tiers are a guess. */
export function folderLine(f: NonNullable<MassPremadeSlots["folder"]>): string {
  const t = f.tiers;
  const explicit = t.explicit + t.hardcore;
  const flagged = Math.max(0, f.photos - t.unknown);
  const verdict = explicit > 0 ? "has explicit photos" : flagged === 0 ? "not flagged yet" : "likely SFW";
  return `${f.name} — ${flagged}/${f.photos} flagged · ${explicit} explicit · ${t.unknown} unknown — ${verdict}`;
}

function massPlanLines(s: MassPremadeSlots): string[] {
  const name = s.name.trim();
  const value = Math.max(1, Math.round(s.interval.value) || 1);
  const unit = s.interval.unit === "hours" ? "hour" : "minute";
  const captions = s.captions.map((c) => c.trim()).filter(Boolean).length;
  const ai = Math.min(s.captions_ai, captions);
  const lists: string[] = [];
  if (!s.includes.length) lists.push("audience: pick it in the form");
  else if (!sameSet(s.includes, BLANK.includes)) {
    const sys = s.includes.filter((id) => SYSTEM_LABEL.has(id)).map((id) => SYSTEM_LABEL.get(id)!);
    const custom = s.includes.length - sys.length;
    lists.push(`to ${[...sys, ...(custom ? [plural(custom, "list")] : [])].join(" + ")}`);
  }
  if (s.excludes.length) lists.push(`excluding ${plural(s.excludes.length, "list")}`);
  const skip = s.exclude_last_chat_hours;
  return [
    `Name: ${name || `${KIND_COPY.mass_premade.namePlaceholder} (default)`}`,
    `Every ${value === 1 ? unit : `${value} ${unit}s`}`,
    `Captions: ${captions}${ai > 0 ? ` (${ai} AI-written — edit later)` : ""}`,
    s.folder ? `Folder: ${folderLine(s.folder)}` : "No folder",
    `Audience: ${s.online_only ? "online fans only" : "online and offline fans"}${lists.length ? `, ${lists.join(", ")}` : ""}`,
    ...(skip !== null ? [skip > 0 ? `Skips fans chatted with in the last ${skip}h` : "Doesn't skip recent chats"] : []),
    s.unsend_after_hours ? `Unsend after ${s.unsend_after_hours}h` : "Never unsent",
    ...(pos(s.price) ? [`PPV $${s.price}${s.folder ? "" : " — needs photos: pick a folder"}`] : []),
    ...(s.folder && pos(s.media_count) && s.media_count !== 1 ? [`${s.media_count} photos per mass`] : []),
    ...moreLines(s),
    "Saved OFF — you turn it on",
  ];
}

function moreLines(s: MassPremadeSlots): string[] {
  const out: string[] = [];
  const guard = (v: number | null | undefined, on: (h: number) => string, off: string) => {
    if (typeof v === "number" && v >= 0) out.push(v > 0 ? on(v) : off);
  };
  guard(s.exclude_replied_hours, (h) => `Skips fans you messaged in the last ${h}h`, "Doesn't skip fans you messaged");
  guard(s.exclude_inbound_hours, (h) => `Skips fans who messaged you in the last ${h}h`, "Doesn't skip fans who messaged you");
  if (pos(s.recent_chat_hours)) {
    out.push(`Adds fans chatted with in the last ${s.recent_chat_hours}h${pos(s.recent_chat_limit) ? ` (up to ${s.recent_chat_limit})` : ""}`);
  } else if (pos(s.recent_chat_limit)) out.push(`Recent-chat fans capped at ${s.recent_chat_limit}`);
  if (pos(s.unread_limit)) out.push(`Adds fans with unread messages (up to ${s.unread_limit})`);
  return out;
}

const storySet = (patch: Partial<typeof STORY_BLANK>): AutoStoriesAction => ({ type: "set", patch });
const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);
const whole = (v: number, lo: number) => Math.max(lo, Math.round(v) || 0);

/** The Auto Story page's own order: folder, when to post (mode, then its times or hours), stories per run, delete
 *  after, total runs; then Enabled OFF and Save. */
function storyToActions(s: AutoStorySlots): AgentStep<AutoStoriesAction>[] {
  const steps: AgentStep<AutoStoriesAction>[] = [];
  if (s.folder) {
    steps.push({ target: "story-folder", action: storySet({ folderId: Number(s.folder.id) }), label: `Picking folder “${s.folder.name}”…` });
  }
  if (s.mode === "interval") {
    steps.push({ target: "story-mode-interval", action: storySet({ mode: "interval" }), label: "Posting every few hours…" });
    const every = whole(s.every_hours, 1);
    if (every !== STORY_BLANK.everyHours) {
      steps.push({ target: "story-every", action: storySet({ everyHours: every }), label: `Every ${plural(every, "hour")}` });
    }
  } else if (s.times.length && !sameList(s.times, STORY_BLANK.times)) {
    steps.push({ target: "story-time-0", action: storySet({ times: [...s.times] }), label: `Posting daily at ${s.times.join(", ")}` });
  }
  const perRun = whole(s.per_run, 1);
  if (perRun !== STORY_BLANK.perRun) {
    steps.push({ target: "story-per-run", action: storySet({ perRun }), label: `${plural(perRun, "story", "stories")} each time` });
  }
  const ttl = whole(s.hours_to_live, 0);
  if (ttl !== STORY_BLANK.hoursToLive) {
    steps.push({ target: "story-ttl", action: storySet({ hoursToLive: ttl }), label: ttl ? `Delete after ${ttl}h` : "Keeping them up" });
  }
  if (pos(s.max_runs)) {
    const n = whole(s.max_runs, 1);
    steps.push({ target: "story-max-runs", action: storySet({ maxRuns: n }), label: `Stop after ${plural(n, "run")}` });
  }
  // ALWAYS, last before Save: the rule is saved OFF (D2).
  steps.push({ target: "story-enabled", action: storySet({ enabled: false }), label: "Leaving it OFF — you turn it on" });
  steps.push({ target: "story-save", action: "save", label: "Saving…" });
  return steps;
}

function storyPlanLines(s: AutoStorySlots): string[] {
  const ttl = whole(s.hours_to_live, 0);
  const every = whole(s.every_hours, 1);
  return [
    s.folder ? `Folder: ${s.folder.name} (${plural(s.folder.photos, "photo")})` : "Folder: pick it in the form",
    s.mode === "interval" ? `Every ${every === 1 ? "hour" : `${every} hours`}` : `Daily at ${s.times.join(", ") || "—"}`,
    `${plural(whole(s.per_run, 1), "story", "stories")} each time`,
    ttl ? `Each deleted after ${ttl}h` : "Kept up (never deleted)",
    pos(s.max_runs) ? `Stops after ${plural(whole(s.max_runs, 1), "run")}` : "Runs until you turn it off",
    "Saved OFF — you turn it on",
  ];
}

export const DO_FLOWS: {
  mass_premade: DoFlow<MassPremadeSlots, RuleEditorAction>;
  auto_story: DoFlow<AutoStorySlots, AutoStoriesAction>;
} = {
  mass_premade: {
    kind: "mass_premade",
    title: "Auto Mass",
    routeBase: "/growth/auto-mass",
    route: (accountId) => `/growth/auto-mass?creator=${encodeURIComponent(accountId)}`,
    toActions: massToActions,
    planLines: massPlanLines,
    savedSwitch: (s) => `Enabled: ${s.name.trim() || KIND_COPY.mass_premade.namePlaceholder}`,
    doneText: "Created OFF — turn it on in the table when ready",
  },
  auto_story: {
    kind: "auto_stories",
    title: "Auto Story",
    routeBase: "/growth/auto-story",
    route: (accountId) => `/growth/auto-story?creator=${encodeURIComponent(accountId)}`,
    toActions: storyToActions,
    planLines: storyPlanLines,
    // AutoStoriesTab's HeaderSwitch (its label is the page title).
    savedSwitch: () => "Auto Story",
    doneText: "Created OFF — turn it on with the Auto Story switch when ready",
  },
};

function bind<S, A extends RuleEditorAction | AutoStoriesAction>(f: DoFlow<S, A>, slots: S, accountId: string): BoundFlow {
  return {
    kind: f.kind, title: f.title, accountId, route: f.route, steps: f.toActions(slots), planLines: f.planLines(slots),
    savedSwitch: f.savedSwitch(slots), doneText: f.doneText,
  };
}

/** The runnable draft's flow, bound to its slots; null for a mass_edit draft (no form) or no slots. */
export function boundFlow(d: DoDraft): BoundFlow | null {
  if (d.flow === "mass_premade" && d.slots) return bind(DO_FLOWS.mass_premade, d.slots, d.account_id);
  if (d.flow === "auto_story" && d.slots) return bind(DO_FLOWS.auto_story, d.slots, d.account_id);
  return null;
}

/** The fixed note under every plan card. */
export const PLAN_NOTE = "Photos added to this folder later are included too.";

/** The flow whose page an answer link opens (query / hash ignored), or null. */
export function flowForHref(href: string): EditorFlowId | null {
  const path = href.split(/[?#]/)[0].replace(/\/+$/, "");
  for (const [id, f] of Object.entries(DO_FLOWS) as Array<[EditorFlowId, { routeBase: string }]>) {
    if (path === f.routeBase) return id;
  }
  return null;
}

/** A typing step's visible frames: the newest caption growing in `chunks` slices (the earlier ones whole). Any other
 *  step is its own single frame. */
export function typingFrames(step: AgentStep, chunks = 4): Array<RuleEditorAction | AutoStoriesAction> {
  const a = step.action;
  if (typeof a === "string") return [];
  if (!step.typing || a.type !== "row" || a.a.type !== "patch" || !a.a.patch.texts?.length) return [a];
  const texts = a.a.patch.texts;
  const last = texts[texts.length - 1];
  const n = Math.max(1, Math.min(chunks, last.length));
  const frames: RuleEditorAction[] = [];
  for (let i = 1; i <= n; i++) {
    const cut = i === n ? last.length : Math.ceil((last.length * i) / n);
    frames.push(rowPatch({ texts: [...texts.slice(0, -1), last.slice(0, cut)] }));
  }
  return frames;
}
