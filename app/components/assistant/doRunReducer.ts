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
 */

import type { DoDraft, MassPremadeSlots } from "./doFlows";

type Planned = { request: string; draft: DoDraft };

export type DoRun =
  | { phase: "off" }
  | { phase: "idle" }
  | { phase: "drafting"; id: string; request: string }
  | ({ phase: "planned" } & Planned)
  | ({ phase: "running"; step: number; instant: boolean; saving: boolean } & Planned)
  | ({ phase: "done"; ruleSaved: true } & Planned)
  | ({ phase: "aborted"; reason: string } & Planned)
  | { phase: "failed"; request: string; draft: DoDraft | null; msg: string };

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
  /** `id`: a drafting request's failure (dropped when stale); none: the running run's. */
  | { type: "fail"; msg: string; id?: string }
  | { type: "reset" };

export const initialDoRun: DoRun = { phase: "off" };

/** The draft a run would act on: a flow, its slots, no error. */
export const canStart = (d: DoDraft | null | undefined): d is DoDraft & { flow: NonNullable<DoDraft["flow"]>; slots: MassPremadeSlots } =>
  !!d && d.flow !== null && d.slots !== null && !d.error;

/** The plan a new request refines: the planned draft's slots (a chat reply while planned), else none. */
export const previousOf = (s: DoRun): MassPremadeSlots | null => (s.phase === "planned" ? s.draft.slots : null);

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
      return s.phase === "drafting" && s.id === a.id ? { phase: "planned", request: s.request, draft: a.draft } : s;
    case "start":
    case "skipAnimation": {
      if (s.phase === "running") return a.type === "skipAnimation" && !s.instant ? { ...s, instant: true } : s;
      const runnable = s.phase === "planned" || s.phase === "aborted" || (s.phase === "failed" && s.draft !== null);
      if (!runnable || !canStart(s.draft)) return s;
      return { phase: "running", request: s.request, draft: s.draft, step: 0, instant: a.type === "skipAnimation", saving: false };
    }
    case "step":
      return s.phase === "running" && s.step !== a.index ? { ...s, step: a.index } : s;
    case "saving":
      return s.phase === "running" && !s.saving ? { ...s, saving: true } : s;
    case "abort":
      return s.phase === "running" && !s.saving ? { phase: "aborted", request: s.request, draft: s.draft, reason: a.reason } : s;
    case "saved":
      return s.phase === "running" ? { phase: "done", request: s.request, draft: s.draft, ruleSaved: true } : s;
    case "fail":
      if (a.id !== undefined) {
        return s.phase === "drafting" && s.id === a.id ? { phase: "failed", request: s.request, draft: null, msg: a.msg } : s;
      }
      return s.phase === "running" ? { phase: "failed", request: s.request, draft: s.draft, msg: a.msg } : s;
    case "reset":
      return s.phase === "off" ? s : { phase: "idle" };
  }
}

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The draft POST's 200, read defensively: a missing field never crashes the card, and a blank answer still reads. */
export function draftFrom(r: Partial<DoDraft> | null | undefined, accountId: string): DoDraft {
  const flow = r?.flow === "mass_premade" ? r.flow : null;
  return {
    id: String(r?.id ?? ""),
    flow,
    account_id: r?.account_id || accountId,
    summary: r?.summary ?? "",
    slots: flow && r?.slots ? r.slots : null,
    assumptions: strs(r?.assumptions),
    unresolved: strs(r?.unresolved),
    answer: (r?.answer || "").trim()
      || (flow ? "" : "I can only set up an Auto Mass for now — ask it as a question and I'll point you to the page."),
    error: r?.error ?? null,
  };
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
