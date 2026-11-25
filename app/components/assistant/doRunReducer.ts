import { exportSlotsFrom } from "./doExport";
import type { AutoStorySlots, DoDraft, DoFlowId, MassPremadeSlots } from "./doFlows";
import { slotsFrom as configSlotsFrom, type ConfigStatus } from "./fullAiConfigEdit";
import { editSlotsFrom, type EditResult } from "./massEdit";

type Planned = { id: string; request: string; draft: DoDraft };

export type DoOutcome =
  | { kind: "saved" }
  | { kind: "applied"; results: EditResult[] }
  | { kind: "downloaded"; file: string }
  | { kind: "config"; status: ConfigStatus; line: string };

const DIRECT_FLOWS: ReadonlySet<DoDraft["flow"]> = new Set(["mass_edit", "report_export", "full_ai_config"]);

export type DoRun =
  | { phase: "off" }
  | { phase: "idle" }
  | { phase: "drafting"; id: string; request: string; accountId: string | null }
  | ({ phase: "planned" } & Planned)
  | ({ phase: "running"; step: number; instant: boolean; saving: boolean; attempt: number; focus?: string | null } & Planned)
  | ({ phase: "done"; outcome: DoOutcome } & Planned)
  | ({ phase: "aborted"; reason: string; step: number } & Planned)
  | { phase: "failed"; id: string; request: string; draft: DoDraft | null; msg: string; attempt?: number; step?: number };

export type DoAction =
  | { type: "enter" }
  | { type: "exit" }
  | { type: "draft"; id: string; request: string; accountId: string | null }
  | { type: "drafted"; id: string; draft: DoDraft }
  | { type: "start" }
  | { type: "skipAnimation" }
  | { type: "step"; index: number }
  | { type: "abort"; reason: string }
  | { type: "saving" }
  | { type: "saved" }
  | { type: "applied"; results: EditResult[] }
  | { type: "downloaded"; file: string }
  | { type: "configApplied"; status: ConfigStatus; line: string }
  | { type: "fail"; msg: string; id?: string }
  | { type: "reset" }
  | { type: "focus"; accountId: string | null };

export const initialDoRun: DoRun = { phase: "off" };

export const canStart = (d: DoDraft | null | undefined): d is DoDraft & { slots: NonNullable<DoDraft["slots"]> } =>
  !!d && d.flow !== null && d.slots !== null && !d.error
  && (d.flow !== "report_export" || (d.unresolved.length === 0 && d.slots.recipe !== null));

export const previousOf = (s: DoRun): MassPremadeSlots | null =>
  (s.phase === "planned" && s.draft.flow === "mass_premade" ? s.draft.slots : null);

export function doRunReducer(s: DoRun, a: DoAction): DoRun {
  switch (a.type) {
    case "enter":
      return s.phase === "off" ? { phase: "idle" } : s;
    case "exit":
      return s.phase === "off" ? s : initialDoRun;
    case "draft":
      if (s.phase === "off" || s.phase === "running" || s.phase === "drafting") return s;
      return { phase: "drafting", id: a.id, request: a.request, accountId: a.accountId };
    // Lands only on the drafting request it answers: a late reply after Cancel or a newer request is dropped.
    case "drafted":
      return s.phase === "drafting" && s.id === a.id ? { phase: "planned", id: s.id, request: s.request, draft: a.draft } : s;
    case "start":
    case "skipAnimation": {
      if (s.phase === "running") return a.type === "skipAnimation" && !s.instant ? { ...s, instant: true } : s;
      const runnable = s.phase === "planned" || s.phase === "aborted" || (s.phase === "failed" && s.draft !== null);
      if (!runnable || !canStart(s.draft)) return s;
      const direct = DIRECT_FLOWS.has(s.draft.flow);
      const attempt = s.phase === "failed" ? (s.attempt ?? 0) + 1 : 0;
      return {
        phase: "running", id: s.id, request: s.request, draft: s.draft, step: 0, instant: direct || a.type === "skipAnimation",
        saving: direct, attempt,
      };
    }
    case "step":
      return s.phase === "running" && s.step !== a.index ? { ...s, step: a.index } : s;
    case "saving":
      return s.phase === "running" && !s.saving ? { ...s, saving: true } : s;
    // Once the save request is out (saving) abort is ignored: it lands either way and a retry would duplicate the rule.
    case "abort":
      if (s.phase !== "running" || s.saving) return s;
      return movedOff(s) ? { phase: "idle" }
        : { phase: "aborted", id: s.id, request: s.request, draft: s.draft, reason: a.reason, step: s.step };
    case "saved":
      return s.phase === "running" && !DIRECT_FLOWS.has(s.draft.flow)
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "saved" } } : s;
    case "applied":
      return s.phase === "running" && s.draft.flow === "mass_edit"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "applied", results: a.results } } : s;
    case "downloaded":
      return s.phase === "running" && s.draft.flow === "report_export"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "downloaded", file: a.file } } : s;
    // A 409 / 422 lands on done too, never failed, so no retry re-PUTs.
    case "configApplied":
      return s.phase === "running" && s.draft.flow === "full_ai_config"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "config", status: a.status, line: a.line } } : s;
    case "fail":
      if (a.id !== undefined) {
        return s.phase === "drafting" && s.id === a.id ? { phase: "failed", id: s.id, request: s.request, draft: null, msg: a.msg } : s;
      }
      if (s.phase !== "running") return s;
      return movedOff(s) ? { phase: "idle" }
        : { phase: "failed", id: s.id, request: s.request, draft: s.draft, msg: a.msg, attempt: s.attempt, step: s.step };
    case "reset":
      return s.phase === "off" ? s : { phase: "idle" };
    case "focus":
      if (s.phase === "drafting") return s.accountId === a.accountId ? s : { phase: "idle" };
      if (s.phase === "running") return s.focus === a.accountId ? s : { ...s, focus: a.accountId };
      if (s.phase === "planned" || s.phase === "aborted" || (s.phase === "failed" && s.draft !== null)) {
        return s.draft?.account_id === a.accountId ? s : { phase: "idle" };
      }
      return s;
  }
}

const movedOff = (s: Extract<DoRun, { phase: "running" }>) => s.focus !== undefined && s.focus !== s.draft.account_id;

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

export const DO_FLOW_IDS: Readonly<Record<DoFlowId, true>> = {
  mass_premade: true, auto_story: true, mass_edit: true, report_export: true, full_ai_config: true,
};
const isFlowId = (v: unknown): v is DoFlowId =>
  typeof v === "string" && Object.prototype.hasOwnProperty.call(DO_FLOW_IDS, v);

const objOf = <T,>(v: unknown): T | null => (v && typeof v === "object" && !Array.isArray(v) ? v as T : null);

const NO_FLOW_ANSWER = "I can only set up an Auto Mass or Auto Story, change an Auto Mass, or export a report of your "
  + "numbers, for now — ask it as a question and I'll point you to the page.";

export function draftFrom(r: Partial<Record<keyof DoDraft, unknown>> | null | undefined, accountId: string | null): DoDraft {
  const acct = typeof r?.account_id === "string" && r.account_id ? r.account_id : accountId;
  const named = isFlowId(r?.flow) ? r.flow : null;
  const base = (flowed: boolean) => ({
    id: String(r?.id ?? ""),
    summary: typeof r?.summary === "string" ? r.summary : "",
    assumptions: strs(r?.assumptions),
    unresolved: strs(r?.unresolved),
    answer: (typeof r?.answer === "string" ? r.answer : "").trim() || (flowed ? "" : NO_FLOW_ANSWER),
    error: typeof r?.error === "string" ? r.error : null,
  });
  const slots = r?.slots;
  if (named === "report_export") return { ...base(true), flow: named, account_id: acct, slots: exportSlotsFrom(slots) };
  if (named !== null && acct) {
    switch (named) {
      case "mass_premade": return { ...base(true), flow: named, account_id: acct, slots: objOf<MassPremadeSlots>(slots) };
      case "auto_story": return { ...base(true), flow: named, account_id: acct, slots: objOf<AutoStorySlots>(slots) };
      case "mass_edit": return { ...base(true), flow: named, account_id: acct, slots: editSlotsFrom(slots) };
      case "full_ai_config": return { ...base(true), flow: named, account_id: acct, slots: configSlotsFrom(slots) };
    }
  }
  return { ...base(false), flow: null, account_id: acct, slots: null };
}

export interface DoOffer { show: boolean; enabled: boolean; hint: string | null }

export const NO_KEY_HINT = "Add a DeepSeek key in Settings → AI keys to use this.";

export function doOfferOf(caps: { can_do?: unknown; reason?: unknown } | null | undefined, isUser: boolean): DoOffer {
  if (caps?.reason === "no_key") return { show: true, enabled: false, hint: NO_KEY_HINT };
  if (caps?.reason === "not_allowed") return { show: false, enabled: false, hint: null };
  const ok = typeof caps?.can_do === "boolean" ? caps.can_do : isUser;
  return { show: ok, enabled: ok, hint: null };
}

export function isTakeover(e: { isTrusted: boolean; type: string; key?: string }, insideBot: boolean): boolean {
  if (!e.isTrusted) return false;
  if (e.type === "keydown" && e.key === "Escape") return true;
  return !insideBot;
}
