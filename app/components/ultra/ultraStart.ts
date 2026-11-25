import { relay } from "@/lib/relay";
import type { PlanView } from "./ultraRunReducer";

export const ULTRA_PLAN_KEY = "chatterly:ultra_plan";

let pending: Promise<PlanView> | null = null;

export function keepPlanId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(ULTRA_PLAN_KEY, id);
    else window.localStorage.removeItem(ULTRA_PLAN_KEY);
  } catch { /* quota, safari private */ }
}

export function beginStart(body: { request: string }): Promise<PlanView> {
  const p: Promise<PlanView> = relay.post<PlanView>("/admin/ultra/plans", body)
    .then((plan) => {
      keepPlanId(plan.id);
      return plan;
    })
    .finally(() => { if (pending === p) pending = null; });
  pending = p;
  return p;
}

export const pendingStart = (): Promise<PlanView> | null => pending;
