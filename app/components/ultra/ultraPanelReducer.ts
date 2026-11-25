import { holdsLogin } from "@/lib/loginPaste";
import { INITIAL_RUN, isFinal, ultraRunReducer, type Action as RunAction, type PlanView, type UltraRun } from "./ultraRunReducer";

export const MAX_REQUEST = 4000;
export const RELAY_LOGIN_REFUSED = "paste logins in the Connect card";

export interface UltraPanel {
  /** The stored plan id has been read (persisting before that would wipe it). */
  hydrated: boolean;
  draft: string;
  planId: string | null;
  starting: boolean;
  startError: string | null;
  loginRefused: boolean;
  run: UltraRun;
}

export type PanelAction =
  | { type: "hydrate"; planId: string | null; starting?: boolean }
  | { type: "draft"; text: string }
  | { type: "start" }
  | { type: "started"; plan: PlanView }
  | { type: "startFailed"; status: number; message: string }
  | { type: "reset" }
  | { type: "run"; planId: string; action: RunAction };

export const INITIAL_PANEL: UltraPanel = {
  hydrated: false, draft: "", planId: null, starting: false, startError: null, loginRefused: false, run: INITIAL_RUN,
};

export function ultraPanelReducer(s: UltraPanel, a: PanelAction): UltraPanel {
  switch (a.type) {
    case "hydrate":
      return s.hydrated ? s
        : { ...s, hydrated: true, planId: a.planId, starting: !a.planId && !!a.starting, run: INITIAL_RUN };
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
      return a.status === 400 && a.message.includes(RELAY_LOGIN_REFUSED)
        ? { ...s, starting: false, draft: "", startError: null, loginRefused: true }
        : { ...s, starting: false, startError: a.message };
    case "reset":
      return { ...s, planId: null, starting: false, startError: null, loginRefused: false, run: INITIAL_RUN };
    case "run": {
      // A late answer for a plan no longer open is dropped.
      if (!s.planId || a.planId !== s.planId || ("plan" in a.action && a.action.plan.id !== s.planId)) return s;
      const run = ultraRunReducer(s.run, a.action);
      return run.load === "missing" ? { ...s, planId: null, run: INITIAL_RUN } : { ...s, run };
    }
  }
}

export const canSubmit = (s: UltraPanel): boolean =>
  s.hydrated && s.planId === null && !s.starting && s.draft.trim().length > 0 && s.draft.length <= MAX_REQUEST;

export const requestBody = (s: UltraPanel): { request: string } | null =>
  canSubmit(s) && !holdsLogin(s.draft) ? { request: s.draft.trim() } : null;

export const isOver = (s: UltraPanel): boolean => !!s.run.plan && isFinal(s.run.plan.status);

export const isRunning = (s: UltraPanel): boolean => s.run.plan?.status === "running";
