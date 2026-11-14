/**
 * "Do it for me" run state, one pure reducer (AssistantProvider dispatches; the POST and the runner stay there):
 *
 *   off → (enter) idle → (draft) drafting → (drafted) planned(draft)
 *       → (start | skipAnimation) running(step) → (saved) done | (abort) aborted | (fail) failed
 *
 *   • `draft` from idle / planned / a finished run re-drafts (the provider sends the planned slots as `previous`,
 *     previousOf: a chat reply refines the plan). `drafted` / a drafting `fail` only land on the drafting request
 *     they answer (`id`): a late response after Cancel or a newer request is dropped.
 *   • `start` only runs a runnable draft (a flow and slots, canStart); a flow:null draft is an answer, not a plan.
 *   • `skipAnimation` from planned starts instantly; while running it makes the remaining steps instant.
 *   • `abort` / `fail` / `saved` / `step` / `saving` only act on a running run (a stale runner callback after Stop is a
 *     no-op). Once the save request is out (`saving`), abort is ignored: the request lands either way, so the card
 *     must say what it did (`saved` → done; a retry would duplicate the rule).
 *   • `reset` (Cancel) goes back to an empty do-mode composer; `exit` leaves do-mode.
 *   • A `mass_edit` draft (D11) has no steps: `start` goes straight to `saving` (the provider's one apply POST is out,
 *     so Stop doesn't apply) and `applied` lands its per-rule results on `done`.
 *   • A `report_export` draft has no steps either: `start` (Download) goes straight to `saving` (the provider's one
 *     /admin/reports/run POST), `downloaded` lands the file on `done`. `attempt` counts starts of one draft: Try again
 *     from `failed` is attempt+1, so the provider's download effect (keyed on the plan's client `id` + attempt — a server
 *     draft id may be null, so two exports would collide) fires again.
 *   • A `full_ai_config` draft (phase 03c) has no steps either: `start` (Apply) goes straight to `saving` (useDoRunner's
 *     one draft PUT), `configApplied` lands its result line on `done` — a 409 / 422 too (the line says why), never
 *     `failed`, so no retry re-PUTs.
 */

import { exportSlotsFrom } from "./doExport";
import type { AutoStorySlots, DoDraft, MassPremadeSlots } from "./doFlows";
import { slotsFrom as configSlotsFrom, type ConfigStatus } from "./fullAiConfigEdit";
import { editSlotsFrom, type EditResult } from "./massEdit";

/** `id`: the drafting request's client id — the plan's own identity (a server draft id may be null). */
type Planned = { id: string; request: string; draft: DoDraft };

/** What a finished run did: a rule saved OFF, a mass_edit's per-rule results, or an export's saved file. */
export type DoOutcome =
  | { kind: "saved" }
  | { kind: "applied"; results: EditResult[] }
  | { kind: "downloaded"; file: string }
  /** A full_ai_config apply's answer: the PUT's status and the card's line. */
  | { kind: "config"; status: ConfigStatus; line: string };

/** Flows with no steps: `start` goes straight to `saving` (one POST by the provider), and `saved` never ends them. */
const DIRECT_FLOWS: ReadonlySet<DoDraft["flow"]> = new Set(["mass_edit", "report_export", "full_ai_config"]);

export type DoRun =
  | { phase: "off" }
  | { phase: "idle" }
  | { phase: "drafting"; id: string; request: string }
  | ({ phase: "planned" } & Planned)
  | ({ phase: "running"; step: number; instant: boolean; saving: boolean; attempt: number } & Planned)
  | ({ phase: "done"; outcome: DoOutcome } & Planned)
  | ({ phase: "aborted"; reason: string } & Planned)
  /** `attempt`: the failed run's (none for a failed draft). */
  | { phase: "failed"; id: string; request: string; draft: DoDraft | null; msg: string; attempt?: number };

export type DoAction =
  | { type: "enter" }
  | { type: "exit" }
  | { type: "draft"; id: string; request: string }
  | { type: "drafted"; id: string; draft: DoDraft }
  | { type: "start" }
  | { type: "skipAnimation" }
  | { type: "step"; index: number }
  | { type: "abort"; reason: string }
  /** The save request went out: Stop no longer applies. */
  | { type: "saving" }
  | { type: "saved" }
  /** A mass_edit run's apply answered: one result per planned rule. */
  | { type: "applied"; results: EditResult[] }
  /** A report_export run's file was saved. */
  | { type: "downloaded"; file: string }
  /** A full_ai_config run's draft PUT answered (200 / 409 / 422): `line` is the card's (fullAiConfigEdit.resultLine). */
  | { type: "configApplied"; status: ConfigStatus; line: string }
  /** `id`: a drafting request's failure (dropped when stale); none: the running run's. */
  | { type: "fail"; msg: string; id?: string }
  | { type: "reset" };

export const initialDoRun: DoRun = { phase: "off" };

/** The draft a run would act on: a flow, its slots, no error; an export also every name resolved (a recipe). */
export const canStart = (d: DoDraft | null | undefined): d is DoDraft & { slots: NonNullable<DoDraft["slots"]> } =>
  !!d && d.flow !== null && d.slots !== null && !d.error
  && (d.flow !== "report_export" || (d.unresolved.length === 0 && d.slots.recipe !== null));

/** The plan a new request refines: the planned Auto mass draft's slots (a chat reply while planned), else none. An
 *  edit or Auto Story plan is never refined: a reply re-asks from scratch. */
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
      return { phase: "drafting", id: a.id, request: a.request };
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
    case "abort":
      return s.phase === "running" && !s.saving ? { phase: "aborted", id: s.id, request: s.request, draft: s.draft, reason: a.reason } : s;
    case "saved":
      return s.phase === "running" && !DIRECT_FLOWS.has(s.draft.flow)
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "saved" } } : s;
    case "applied":
      return s.phase === "running" && s.draft.flow === "mass_edit"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "applied", results: a.results } } : s;
    case "downloaded":
      return s.phase === "running" && s.draft.flow === "report_export"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "downloaded", file: a.file } } : s;
    case "configApplied":
      return s.phase === "running" && s.draft.flow === "full_ai_config"
        ? { phase: "done", id: s.id, request: s.request, draft: s.draft, outcome: { kind: "config", status: a.status, line: a.line } } : s;
    case "fail":
      if (a.id !== undefined) {
        return s.phase === "drafting" && s.id === a.id ? { phase: "failed", id: s.id, request: s.request, draft: null, msg: a.msg } : s;
      }
      return s.phase === "running" ? { phase: "failed", id: s.id, request: s.request, draft: s.draft, msg: a.msg, attempt: s.attempt } : s;
    case "reset":
      return s.phase === "off" ? s : { phase: "idle" };
  }
}

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The draft POST's 200, read defensively: a missing field never crashes the card, and a blank answer still reads.
 *  `accountId` null: drafted in General (an export only — another flow with no model is no draft). */
export function draftFrom(r: Partial<Record<keyof DoDraft, unknown>> | null | undefined, accountId: string | null): DoDraft {
  const acct = typeof r?.account_id === "string" && r.account_id ? r.account_id : accountId;
  const named = r?.flow === "mass_premade" || r?.flow === "mass_edit" || r?.flow === "auto_story" || r?.flow === "report_export"
    || r?.flow === "full_ai_config" ? r.flow : null;
  const flow = named === "report_export" || acct ? named : null;
  const pair = flow === "mass_premade" ? { flow, slots: r?.slots ? r.slots as MassPremadeSlots : null }
    : flow === "auto_story" ? { flow, slots: r?.slots ? r.slots as AutoStorySlots : null }
    : flow === "mass_edit" ? { flow, slots: editSlotsFrom(r?.slots) }
    : flow === "report_export" ? { flow, slots: exportSlotsFrom(r?.slots) }
    : flow === "full_ai_config" ? { flow, slots: configSlotsFrom(r?.slots) }
    : { flow: null, slots: null };
  return {
    id: String(r?.id ?? ""),
    ...pair,
    account_id: acct,
    summary: typeof r?.summary === "string" ? r.summary : "",
    assumptions: strs(r?.assumptions),
    unresolved: strs(r?.unresolved),
    answer: (typeof r?.answer === "string" ? r.answer : "").trim()
      || (flow ? "" : "I can only set up an Auto Mass or Auto Story, change an Auto Mass, or export a report of your "
        + "numbers, for now — ask it as a question and I'll point you to the page."),
    error: typeof r?.error === "string" ? r.error : null,
  } as DoDraft;
}

/** The do-mode offer: hidden, shown, or shown disabled with a hint (`hint` is AnswerText-linked). */
export interface DoOffer { show: boolean; enabled: boolean; hint: string | null }

export const NO_KEY_HINT = "Add a DeepSeek key in Settings → AI keys to use this.";

/** Whether the asker gets "Do it for me", from GET /admin/assistant/do-caps `{account_id, can_do, reason}`:
 *  `reason` "no_key" → shown disabled with the key hint, "not_allowed" → hidden, else `can_do`. No answer (General,
 *  loading, a failed read) → a signed-in user yes, a chatter no. The one place to change when the server's shape moves. */
export function doOfferOf(caps: { can_do?: unknown; reason?: unknown } | null | undefined, isUser: boolean): DoOffer {
  if (caps?.reason === "no_key") return { show: true, enabled: false, hint: NO_KEY_HINT };
  if (caps?.reason === "not_allowed") return { show: false, enabled: false, hint: null };
  const ok = typeof caps?.can_do === "boolean" ? caps.can_do : isUser;
  return { show: ok, enabled: ok, hint: null };
}

/** A page input that takes over from the agent: any trusted Escape, or a trusted pointer / key press outside the bot
 *  and the cursor overlay. Synthetic events (the agent's own) never abort. */
export function isTakeover(e: { isTrusted: boolean; type: string; key?: string }, insideBot: boolean): boolean {
  if (!e.isTrusted) return false;
  if (e.type === "keydown" && e.key === "Escape") return true;
  return !insideBot;
}
