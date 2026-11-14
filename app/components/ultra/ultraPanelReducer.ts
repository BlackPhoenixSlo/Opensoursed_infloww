/**
 * The help bot's Ultra panel state (UltraPanel.tsx; ultra tickets 06 + 08): the request being typed, the start
 * (POST /admin/ultra/plans) in flight or refused, the open plan's id (kept per browser so a reload resumes it) and
 * that plan's run state (ultraRunReducer, wrapped as `run`). Pure; the panel only dispatches. `canSubmit` /
 * `requestBody` gate the composer; a 404 on the open plan drops it (back to the composer). A request holding an
 * OnlyFans login (email:password, lib/loginPaste) is refused before it leaves the browser, the draft cleared: logins go
 * through the Connect card (LOGINS_PAGE), never the planner (ultra ticket 11; the relay refuses it too, its one 400 on
 * the start). Both set `loginRefused`, the panel's link to that card.
 */
import { holdsLogin } from "@/lib/loginPaste";
import { FINAL, INITIAL_RUN, ultraRunReducer, type Action as RunAction, type PlanView, type UltraRun } from "./ultraRunReducer";

/** service/ultra_plan_decide.MAX_REQUEST: the route's pydantic max_length (422 past it). */
export const MAX_REQUEST = 4000;

export interface UltraPanel {
  /** The stored plan id has been read (persisting before that would wipe it). */
  hydrated: boolean;
  draft: string;
  planId: string | null;
  starting: boolean;
  startError: string | null;
  /** The request held an OnlyFans login (refused here or by the relay's 400): the panel links the Connect card. */
  loginRefused: boolean;
  run: UltraRun;
}

export type PanelAction =
  | { type: "hydrate"; planId: string | null }
  | { type: "draft"; text: string }
  | { type: "start" }
  | { type: "started"; plan: PlanView }
  | { type: "startFailed"; message: string; loginRefused?: boolean }
  | { type: "reset" }
  | { type: "run"; action: RunAction };

export const INITIAL_PANEL: UltraPanel = {
  hydrated: false, draft: "", planId: null, starting: false, startError: null, loginRefused: false, run: INITIAL_RUN,
};

export function ultraPanelReducer(s: UltraPanel, a: PanelAction): UltraPanel {
  switch (a.type) {
    case "hydrate":
      return s.hydrated ? s : { ...s, hydrated: true, planId: a.planId, run: INITIAL_RUN };
    case "draft":
      return { ...s, draft: a.text.slice(0, MAX_REQUEST) };
    case "start":
      if (!canSubmit(s)) return s;
      return holdsLogin(s.draft)
        ? { ...s, draft: "", startError: null, loginRefused: true }
        : { ...s, starting: true, startError: null, loginRefused: false };
    case "started":
      return { ...s, starting: false, draft: "", loginRefused: false, planId: a.plan.id,
        run: ultraRunReducer(INITIAL_RUN, { type: "loaded", plan: a.plan }) };
    case "startFailed":
      return a.loginRefused
        ? { ...s, starting: false, draft: "", startError: null, loginRefused: true }
        : { ...s, starting: false, startError: a.message };
    case "reset":
      return { ...s, planId: null, starting: false, startError: null, loginRefused: false, run: INITIAL_RUN };
    case "run": {
      // A late answer for a plan no longer open is dropped.
      if (!s.planId || ("plan" in a.action && a.action.plan.id !== s.planId)) return s;
      const run = ultraRunReducer(s.run, a.action);
      return run.load === "missing" ? { ...s, planId: null, run: INITIAL_RUN } : { ...s, run };
    }
  }
}

/** The composer sends: no plan open, nothing in flight, a request within the server's limit. */
export const canSubmit = (s: UltraPanel): boolean =>
  s.hydrated && s.planId === null && !s.starting && s.draft.trim().length > 0 && s.draft.length <= MAX_REQUEST;

export const requestBody = (s: UltraPanel): { request: string } | null =>
  canSubmit(s) && !holdsLogin(s.draft) ? { request: s.draft.trim() } : null;

/** The open plan ended: its report shows, with "New request". */
export const isOver = (s: UltraPanel): boolean => !!s.run.plan && FINAL.has(s.run.plan.status);

/** The header dot pulses while the plan runs. */
export const isRunning = (s: UltraPanel): boolean => s.run.plan?.status === "running";
