/**
 * The Ultra start in flight (POST /admin/ultra/plans), kept outside the panel's lifetime: the owner may close the
 * panel (or untick Ultra) and reopen it before the planner answers. The answer's plan id is stored per browser first
 * (ULTRA_PLAN_KEY), then whichever panel is mounted follows it; a panel mounting while it is out shows the start as
 * in flight (no second, paid, request) and takes its answer.
 */
import { relay } from "@/lib/relay";
import type { PlanView } from "./ultraRunReducer";

/** The open plan's id, per browser: a reload resumes it until "New request". */
export const ULTRA_PLAN_KEY = "chatterly:ultra_plan";

let pending: Promise<PlanView> | null = null;

/** Post the request; the plan id is kept before anyone hears the answer. */
export function beginStart(body: { request: string }): Promise<PlanView> {
  const p: Promise<PlanView> = relay.post<PlanView>("/admin/ultra/plans", body)
    .then((plan) => {
      try { window.localStorage.setItem(ULTRA_PLAN_KEY, plan.id); } catch { /* quota */ }
      return plan;
    })
    .finally(() => { if (pending === p) pending = null; });
  pending = p;
  return p;
}

/** The start still out, if any. */
export const pendingStart = (): Promise<PlanView> | null => pending;
