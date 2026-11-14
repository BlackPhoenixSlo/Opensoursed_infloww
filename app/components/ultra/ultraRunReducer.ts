/**
 * An Ultra plan page's state (app/app/ultra/plans/[id]; ultra ticket 06): the plan as the Relay last answered
 * (GET /admin/ultra/plans/{id}, service/ultra_run.py `view`), how its load went, and the one OK / Cancel in
 * flight. A pure reducer (UltraPlanPage only dispatches) plus `canApprove` / `canCancel` / `okPayload` (the OK
 * posts the hash the owner was shown), `showOk` / `okLabel` / `cancelLabel` (the buttons), `pollMs` (how often
 * to re-read) and `statusNote` / `STEP_LABEL`, the plain statements the page shows. Every word about a step comes from the server's card; nothing is recomposed here.
 */

export type PlanStatus = "awaiting_ok" | "running" | "done" | "failed" | "cancelled" | "interrupted" | "expired";
export type StepState = "pending" | "started" | "done" | "failed" | "uncertain" | "skipped";

export interface PlanCard {
  id: string;
  tool: string;
  effect: "read" | "write" | "send";
  title: string;
  rows: [string, string][];
  /** A send's FULL text, as it will go out (after the send chain). */
  text?: string;
}

/** `result.id`: the id a done step made (a send's OnlyFans mass message / post id; ultra_decide.step_end).
 *  `note`: a done mass that went to fewer fans than approved ("sent to 1 of 2 fans by id: 1 skipped …"). */
export interface StepStatus {
  id: string;
  state: StepState;
  error?: string;
  note?: string;
  open_url?: string | null;
  result?: { id: string | number };
}

export interface PlanView {
  id: string;
  status: PlanStatus;
  summary: string;
  sha256: string;
  card: PlanCard[];
  step_states: StepStatus[];
  created_at: string;
  expires_at: string;
  approved_at: string | null;
  finished_at: string | null;
}

export interface UltraRun {
  plan: PlanView | null;
  /** `missing` = 404 (no such plan, or another owner's); `error` = no plan read yet and the read failed. */
  load: "loading" | "ready" | "missing" | "error";
  /** The last read's failure; a failed re-poll keeps the plan on screen. */
  loadError: string | null;
  busy: "ok" | "cancel" | null;
  actionError: string | null;
}

export type Action =
  | { type: "loaded"; plan: PlanView }
  | { type: "loadFailed"; status: number; message: string }
  | { type: "act"; kind: "ok" | "cancel" }
  | { type: "acted"; plan: PlanView }
  | { type: "actFailed"; message: string };

export const INITIAL_RUN: UltraRun = { plan: null, load: "loading", loadError: null, busy: null, actionError: null };

export function ultraRunReducer(state: UltraRun, action: Action): UltraRun {
  switch (action.type) {
    case "loaded":
      return { ...state, plan: action.plan, load: "ready", loadError: null };
    case "loadFailed":
      if (action.status === 404) return { ...state, plan: null, load: "missing", loadError: null };
      return state.plan ? { ...state, loadError: action.message } : { ...state, load: "error", loadError: action.message };
    case "act":
      return state.busy ? state : { ...state, busy: action.kind, actionError: null };
    case "acted":
      return { ...state, plan: action.plan, load: "ready", busy: null, actionError: null };
    case "actFailed":
      return { ...state, busy: null, actionError: action.message };
  }
}

export const canApprove = (s: UltraRun): boolean => s.plan?.status === "awaiting_ok" && s.busy === null;

export const canCancel = (s: UltraRun): boolean =>
  (s.plan?.status === "awaiting_ok" || s.plan?.status === "running") && s.busy === null;

/** The OK button is gone once the plan runs or a cancel is in flight (Cancel stays). */
export const showOk = (s: UltraRun): boolean => s.plan?.status !== "running" && s.busy !== "cancel";

export function okLabel(s: UltraRun): string {
  if (s.busy === "ok") return "Starting…";
  const n = s.plan?.card.length ?? 0;
  return `OK, run ${n} step${n === 1 ? "" : "s"}`;
}

export function cancelLabel(s: UltraRun): string {
  if (s.busy === "cancel") return "Cancelling…";
  return s.plan?.status === "running" ? "Cancel the rest" : "Cancel plan";
}

/** The OK's body: the hash of exactly the plan on screen (the Relay answers 409 if it is not the stored one). */
export const okPayload = (s: UltraRun): { sha256: string } | null => (canApprove(s) ? { sha256: s.plan!.sha256 } : null);

/** Re-read every so often while something can still change on the server: a run's steps, an OK's expiry. */
export function pollMs(s: UltraRun): number | null {
  if (s.plan?.status === "running") return 2000;
  if (s.plan?.status === "awaiting_ok") return 15000;
  return null;
}

export const STEP_LABEL: Record<StepState, string> = {
  pending: "Waiting",
  started: "Running",
  done: "Done",
  failed: "Failed",
  uncertain: "Uncertain",
  skipped: "Not run",
};

const UNCERTAIN = "may or may not have gone out. Check OnlyFans before sending it again.";

/** How long the OK stays open, from the server's own times (expires_at − created_at; ultra_decide.OK_TTL). */
export function okWindow(plan: PlanView): string | null {
  const m = Math.round((Date.parse(plan.expires_at) - Date.parse(plan.created_at)) / 60000);
  return Number.isFinite(m) && m > 0 ? `${m} minute${m === 1 ? "" : "s"}` : null;
}

/** The one plain statement under the summary: what happened, and what the owner should do. */
export function statusNote(plan: PlanView): string {
  const ids = (st: StepState) => plan.step_states.filter((s) => s.state === st).map((s) => s.id);
  const uncertain = ids("uncertain");
  const unsure = uncertain.length ? ` Step ${uncertain.join(", ")} got no clear answer and ${UNCERTAIN}` : "";
  const ttl = okWindow(plan);
  switch (plan.status) {
    case "awaiting_ok":
      return `Nothing has run yet. Check every step below; OK runs them in order.${
        ttl ? ` The plan expires ${ttl} after it was made.` : ""}`;
    case "running":
      return "Running, one step at a time. Cancel stops it before the next step; a send already going out still finishes.";
    case "done":
      return "Done: every step ran.";
    case "failed":
      return unsure
        ? `Stopped.${unsure} Nothing after it ran.`
        : `Stopped: step ${ids("failed").join(", ")} failed. Nothing after it ran.`;
    case "cancelled":
      return "Cancelled. The steps marked Not run did not run.";
    case "interrupted":
      return `The server restarted while this plan ran, so it stopped.${unsure} The steps marked Not run did not run.`;
    case "expired":
      return `Expired: it was not approved ${ttl ? `within ${ttl}` : "in time"}, so nothing ran. Ask for a new plan.`;
  }
}
