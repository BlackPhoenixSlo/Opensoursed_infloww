/**
 * An Ultra plan's state (the plan page app/app/ultra/plans/[id] and the help bot's Ultra panel; ultra ticket 06):
 * the plan as the Relay last answered (GET /admin/ultra/plans/{id}, service/ultra_run.py `view`), how its load
 * went, the one OK / Cancel / pick in flight and the owner's ticks on a `needs_you` pick card. A pure reducer (the
 * components only dispatch) plus `canApprove` / `canCancel` / `okPayload` (the OK posts the hash the owner was
 * shown), `actRequest` (what each action posts), `canPick` / `buildPickPayload` (exactly pick_n ticked), `planActions`
 * (the buttons both surfaces draw), `pollMs` and `statusNote` / `STEP_LABEL`. Every word about a step comes from the server's card; nothing is recomposed here.
 */

export type PlanStatus = "planning" | "awaiting_ok" | "running" | "needs_you" | "done" | "failed" | "cancelled"
  | "interrupted" | "expired" | "capped";
export type StepState = "pending" | "started" | "needs_you" | "done" | "failed" | "uncertain" | "skipped";

/** Per status, in one place (a new status must say all three): `final` = service/ultra_decide.py FINAL (nothing
 *  changes on the server any more), `cancellable` = the Relay takes a cancel, `pollMs` = re-read every so often while
 *  something can still change (planning, a run's steps, an OK's expiry). */
const STATUS: Record<PlanStatus, { final: boolean; cancellable: boolean; pollMs: number | null }> = {
  planning: { final: false, cancellable: true, pollMs: 1500 },
  awaiting_ok: { final: false, cancellable: true, pollMs: 15000 },
  running: { final: false, cancellable: true, pollMs: 2000 },
  needs_you: { final: false, cancellable: true, pollMs: 5000 },
  done: { final: true, cancellable: false, pollMs: null },
  failed: { final: true, cancellable: false, pollMs: null },
  cancelled: { final: true, cancellable: false, pollMs: null },
  interrupted: { final: true, cancellable: false, pollMs: null },
  expired: { final: true, cancellable: false, pollMs: null },
  capped: { final: true, cancellable: false, pollMs: null },
};

/** STATUS's row; a status this build does not know (a newer server) gets a forward-compatible default: not over,
 *  no Cancel, re-read every 15 s until it turns into one it knows. */
const statusRow = (status: PlanStatus) => STATUS[status] ?? { final: false, cancellable: false, pollMs: 15000 };

export const isFinal = (status: PlanStatus): boolean => statusRow(status).final;

export interface PlanCard {
  id: string;
  tool: string;
  effect: "read" | "write" | "send" | "judge";
  title: string;
  rows: [string, string][];
  /** A send's FULL text, as it will go out (after the send chain). */
  text?: string;
}

/** A judge's candidate (ultra_judge_decide.candidates): `thumb` a relay path, `description` the AI's words. */
export interface Candidate { id: number; type: string | null; thumb: string | null; description: string }

/** `result.id`: the id a done step made (a send's OnlyFans mass message / post id; ultra_decide.step_end);
 *  `result.ids` + `picked_by`: a done judge's picks. `note`: a done mass that went to fewer fans than approved.
 *  A `needs_you` judge (ultra_judge_decide.needs_you): `question`, `pick_n`, ≤6 `candidates`, the AI's `picks`. */
export interface StepStatus {
  id: string;
  state: StepState;
  error?: string;
  note?: string;
  open_url?: string | null;
  result?: { id?: string | number; ids?: number[] };
  picked_by?: "ai" | "owner";
  question?: string;
  pick_n?: number;
  candidates?: Candidate[];
  picks?: number[];
}

/** An in-app plan still planning (ultra_plan_decide.progress): progress only, never model text. */
export interface Planning { turns: number; max_turns: number; last_tool: string | null; error?: string }

export interface PlanView {
  id: string;
  status: PlanStatus;
  source?: string;
  summary: string;
  sha256: string;
  card: PlanCard[];
  step_states: StepStatus[];
  created_at: string;
  /** null while there is no plan yet (planning): no OK window. */
  expires_at: string | null;
  approved_at: string | null;
  finished_at: string | null;
  planning?: Planning;
}

export interface UltraRun {
  plan: PlanView | null;
  /** `missing` = 404 (no such plan, or another owner's); `error` = no plan read yet and the read failed. */
  load: "loading" | "ready" | "missing" | "error";
  /** The last read's failure; a failed re-poll keeps the plan on screen. */
  loadError: string | null;
  /** A read was refused (401/403: signed out, or not allowed): polling stops until a read succeeds (Try again). */
  pollStopped: boolean;
  busy: "ok" | "cancel" | "pick" | null;
  actionError: string | null;
  /** The owner's ticks on the waiting judge's card (starts at the AI's picks); null when nothing waits. */
  picked: { step: string; ids: number[] } | null;
}

export type ActKind = "ok" | "cancel" | "pick";

export type Action =
  | { type: "loaded"; plan: PlanView }
  | { type: "loadFailed"; status: number; message: string }
  | { type: "act"; kind: ActKind }
  | { type: "acted"; plan: PlanView }
  | { type: "actFailed"; message: string }
  | { type: "tick"; id: number };

export const INITIAL_RUN: UltraRun = {
  plan: null, load: "loading", loadError: null, pollStopped: false, busy: null, actionError: null, picked: null,
};

/** The judge step waiting for the owner, if any. */
export const waitingStep = (plan: PlanView | null): StepStatus | null =>
  plan?.step_states.find((s) => s.state === "needs_you") ?? null;

function withPlan(state: UltraRun, plan: PlanView): UltraRun {
  const w = waitingStep(plan);
  const picked = !w ? null
    : state.picked?.step === w.id ? state.picked : { step: w.id, ids: [...(w.picks ?? [])] };
  return { ...state, plan, picked };
}

export function ultraRunReducer(state: UltraRun, action: Action): UltraRun {
  switch (action.type) {
    case "loaded":
      return { ...withPlan(state, action.plan), load: "ready", loadError: null, pollStopped: false };
    case "loadFailed": {
      if (action.status === 404) return { ...state, plan: null, load: "missing", loadError: null, picked: null };
      const pollStopped = action.status === 401 || action.status === 403;
      return state.plan ? { ...state, loadError: action.message, pollStopped }
        : { ...state, load: "error", loadError: action.message, pollStopped };
    }
    case "act":
      return state.busy ? state : { ...state, busy: action.kind, actionError: null };
    case "acted":
      return { ...withPlan(state, action.plan), load: "ready", busy: null, actionError: null };
    case "actFailed":
      return { ...state, busy: null, actionError: action.message };
    case "tick": {
      const w = waitingStep(state.plan);
      if (!state.picked || state.busy || !w?.candidates?.some((c) => c.id === action.id)) return state;
      const ids = state.picked.ids.includes(action.id)
        ? state.picked.ids.filter((i) => i !== action.id) : [...state.picked.ids, action.id];
      return { ...state, picked: { ...state.picked, ids } };
    }
  }
}

export const canApprove = (s: UltraRun): boolean => s.plan?.status === "awaiting_ok" && s.busy === null;

export const canCancel = (s: UltraRun): boolean => !!s.plan && statusRow(s.plan.status).cancellable && s.busy === null;

/** Send these: the plan waits on this judge and exactly its pick_n are ticked. */
export function canPick(s: UltraRun): boolean {
  const w = waitingStep(s.plan);
  return s.plan?.status === "needs_you" && s.busy === null && !!w && s.picked?.step === w.id
    && s.picked.ids.length === w.pick_n;
}

/** POST …/pick's body: the ticks in the card's order. */
export function buildPickPayload(s: UltraRun): { step: string; ids: number[] } | null {
  if (!canPick(s)) return null;
  const order = (waitingStep(s.plan)!.candidates ?? []).map((c) => c.id);
  return { step: s.picked!.step, ids: order.filter((id) => s.picked!.ids.includes(id)) };
}

export interface PlanAction {
  kind: ActKind;
  label: string;
  enabled: boolean;
  /** The red / primary button (OK, Send these); Cancel is the plain one. */
  primary: boolean;
}

function cancelLabel(s: UltraRun): string {
  if (s.busy === "cancel") return "Cancelling…";
  if (s.plan?.status === "planning") return "Stop planning";
  return s.plan?.status === "running" || s.plan?.status === "needs_you" ? "Cancel the rest" : "Cancel plan";
}

/** The buttons under a plan, in order (the panel and the plan page both draw exactly these): OK while the plan
 *  awaits it and no cancel is in flight; "Send these" while a judge waits on the owner or the pick is in flight;
 *  Cancel while the plan can be cancelled or the cancel is in flight (hidden while an OK / pick is in flight). */
export function planActions(s: UltraRun): PlanAction[] {
  const out: PlanAction[] = [];
  const plan = s.plan;
  const status = plan?.status;
  if (plan?.status === "awaiting_ok" && s.busy !== "cancel") {
    const n = plan.card.length;
    out.push({ kind: "ok", label: s.busy === "ok" ? "Starting…" : `OK, run ${n} step${n === 1 ? "" : "s"}`,
      enabled: canApprove(s), primary: true });
  }
  if (status === "needs_you" || s.busy === "pick") {
    out.push({ kind: "pick", label: s.busy === "pick" ? "Sending…" : "Send these", enabled: canPick(s), primary: true });
  }
  if (canCancel(s) || s.busy === "cancel") {
    out.push({ kind: "cancel", label: cancelLabel(s), enabled: canCancel(s), primary: false });
  }
  return out;
}

/** The OK's body: the hash of exactly the plan on screen (the Relay answers 409 if it is not the stored one). */
export const okPayload = (s: UltraRun): { sha256: string } | null => (canApprove(s) ? { sha256: s.plan!.sha256 } : null);


/** Per action: its body now (undefined: none), or null when it may not post. */
const ACT_BODY: Record<ActKind, (s: UltraRun) => object | null | undefined> = {
  ok: okPayload,
  pick: buildPickPayload,
  cancel: (s) => (canCancel(s) ? undefined : null),
};
/** What an OK / Cancel / pick posts now: `{ body }` (cancel: none), or null when it may not post. */
export function actRequest(kind: ActKind, s: UltraRun): { body: object | undefined } | null {
  const body = ACT_BODY[kind](s);
  return body === null ? null : { body };
}

/** The line when a re-poll failed (the plan stays on screen): its words, and `retry` = polling stopped (401/403), so
 *  the owner gets a Try again button instead of "Trying again." */
export function refreshNote(s: UltraRun): { text: string; retry: boolean } | null {
  if (!s.plan || !s.loadError) return null;
  return s.pollStopped
    ? { text: `Could not refresh: ${s.loadError}.`, retry: true }
    : { text: `Could not refresh: ${s.loadError}. Trying again.`, retry: false };
}

/** How often to re-read now (STATUS.pollMs); none once FINAL or after a refused read. */
export const pollMs = (s: UltraRun): number | null => (s.plan && !s.pollStopped ? statusRow(s.plan.status).pollMs : null);

export const STEP_LABEL: Record<StepState, string> = {
  pending: "Waiting",
  started: "Running",
  needs_you: "Needs you",
  done: "Done",
  failed: "Failed",
  uncertain: "Uncertain",
  skipped: "Not run",
};

const UNCERTAIN = "may or may not have gone out. Check OnlyFans before sending it again.";
/** A non-send write with no answer (ultra_decide.outcome) may still have finished. */
const UNCERTAIN_WRITE = "may or may not have finished. Check it before running it again.";

/** How long the OK stays open, from the server's own times (expires_at − created_at; ultra_decide.OK_TTL). */
export function okWindow(plan: PlanView): string | null {
  const m = Math.round((Date.parse(plan.expires_at ?? "") - Date.parse(plan.created_at)) / 60000);
  return Number.isFinite(m) && m > 0 ? `${m} minute${m === 1 ? "" : "s"}` : null;
}

/** The one plain statement under the summary: what happened, and what the owner should do. */
export function statusNote(plan: PlanView): string {
  const ids = (st: StepState) => plan.step_states.filter((s) => s.state === st).map((s) => s.id);
  const uncertain = ids("uncertain");
  // The send wording unless the card says every uncertain step is a non-send (unknown → send: fail closed).
  const sendish = uncertain.some((id) => plan.card.find((c) => c.id === id)?.effect !== "write");
  const unsure = uncertain.length
    ? ` Step ${uncertain.join(", ")} got no clear answer and ${sendish ? UNCERTAIN : UNCERTAIN_WRITE}` : "";
  const failed = ids("failed");
  const ttl = okWindow(plan);
  const p = plan.planning;
  // No hash: the planning loop ended without a plan; its own sentence says why.
  const noPlan = !plan.sha256;
  switch (plan.status) {
    case "planning":
      return `Planning… turn ${p?.turns ?? 0} of ${p?.max_turns ?? "?"}${p?.last_tool ? ` · last: ${p.last_tool}` : ""}. Nothing runs before your OK.`;
    case "awaiting_ok":
      return `Nothing has run yet. Check every step below; OK runs them in order.${
        ttl ? ` The plan expires ${ttl} after it was made.` : ""}`;
    case "running":
      return "Running, one step at a time. Cancel stops it before the next step; a send already going out still finishes.";
    case "needs_you":
      return "Waiting for you: tick the picks below, then Send these. Nothing after this step runs until then.";
    case "done":
      return "Done: every step ran.";
    case "failed":
      if (noPlan) return `Planning stopped: ${p?.error ?? "no plan."}`;
      if (unsure) return `Stopped.${unsure} Nothing after it ran.`;
      return failed.length ? `Stopped: step ${failed.join(", ")} failed. Nothing after it ran.`
        : "Stopped: the run hit an error before the next step. Nothing after it ran.";
    case "capped":
      if (noPlan) return `Planning stopped: ${p?.error ?? "a cap was hit."}`;
      return `Stopped at the AI budget${failed.length ? ` (step ${failed.join(", ")})` : ""}. Nothing after it ran.`;
    case "cancelled":
      return noPlan ? "Cancelled before a plan was made." : "Cancelled. The steps marked Not run did not run.";
    case "interrupted":
      return noPlan ? "The server restarted while planning, so it stopped. Ask again."
        : `The server restarted while this plan ran, so it stopped.${unsure} The steps marked Not run did not run.`;
    case "expired":
      return `Expired: it was not approved ${ttl ? `within ${ttl}` : "in time"}, so nothing ran. Ask for a new plan.`;
  }
}
