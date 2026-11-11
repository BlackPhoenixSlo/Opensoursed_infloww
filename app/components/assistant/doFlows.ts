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
 */

import type { RuleEditorAction } from "@/components/automations/ruleEditorForm";
import type { Unit } from "@/components/automations/ruleInterval";
import { KIND_COPY } from "@/components/automations/readyMadeContent";
import { blankRow, type Row } from "@/components/compose/premadeRows";
import { SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import type { Kind } from "@/components/compose/payloadRules";

export type DoFlowId = "mass_premade";

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
}

/** POST /admin/assistant/draft's 200 (always 200). */
export interface DoDraft {
  id: string;
  flow: DoFlowId | null;
  account_id: string;
  summary: string;
  slots: MassPremadeSlots | null;
  assumptions: string[];
  unresolved: string[];
  /** A human sentence: the flow:null pointer to Q&A, or the error's words. */
  answer: string;
  error: string | null;
}

export type AgentAction = RuleEditorAction | "open" | "save";

export interface AgentStep {
  /** The element id the cursor goes to. */
  target: string;
  action: AgentAction;
  /** The cursor bubble's words. */
  label: string;
  /** A caption the runner may type in visibly (typingFrames). */
  typing?: boolean;
}

export interface DoFlow {
  kind: Kind;
  /** The page's path: a Q&A answer linking here offers the swap. */
  routeBase: string;
  route: (accountId: string) => string;
  toActions: (slots: MassPremadeSlots) => AgentStep[];
  /** The plan card's plain-words lines. */
  planLines: (slots: MassPremadeSlots) => string[];
  /** The saved rule's name as the table shows it (the done cursor rests on its Enabled switch). */
  savedName: (slots: MassPremadeSlots) => string;
}

const MP = "mass_premade";
const BLANK = blankRow();
const BLANK_INTERVAL = { value: 24, unit: "hours" as Unit };

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
function rowPatch(patch: Partial<Row>): RuleEditorAction {
  return { type: "row", a: { type: "patch", patch } };
}

function massToActions(s: MassPremadeSlots): AgentStep[] {
  const steps: AgentStep[] = [{ target: `rm-${MP}-new`, action: "open", label: "Opening a new Auto Mass…" }];
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
  // ALWAYS, last before Save: the rule is saved OFF (D2).
  steps.push({ target: `rm-${MP}-enabled`, action: { type: "field", patch: { enabled: false, dryRun: false } }, label: "Leaving it OFF — you turn it on" });
  steps.push({ target: `rm-${MP}-save`, action: "save", label: "Saving…" });
  return steps;
}

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
    "Saved OFF — you turn it on",
  ];
}

export const DO_FLOWS: Record<DoFlowId, DoFlow> = {
  mass_premade: {
    kind: "mass_premade",
    routeBase: "/growth/auto-mass",
    route: (accountId) => `/growth/auto-mass?creator=${encodeURIComponent(accountId)}`,
    toActions: massToActions,
    planLines: massPlanLines,
    savedName: (s) => s.name.trim() || KIND_COPY.mass_premade.namePlaceholder,
  },
};

/** The fixed note under every plan card. */
export const PLAN_NOTE = "Photos added to this folder later are included too.";

/** The flow whose page an answer link opens (query / hash ignored), or null. */
export function flowForHref(href: string): DoFlowId | null {
  const path = href.split(/[?#]/)[0].replace(/\/+$/, "");
  for (const [id, f] of Object.entries(DO_FLOWS) as Array<[DoFlowId, DoFlow]>) {
    if (path === f.routeBase) return id;
  }
  return null;
}

/** A typing step's visible frames: the newest caption growing in `chunks` slices (the earlier ones whole). Any other
 *  step is its own single frame. */
export function typingFrames(step: AgentStep, chunks = 4): RuleEditorAction[] {
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
