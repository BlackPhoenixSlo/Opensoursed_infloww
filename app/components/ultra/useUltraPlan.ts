"use client";

import { useCallback, useEffect, useRef } from "react";

import { errText } from "@/lib/errText";
import { relay, RelayError } from "@/lib/relay";
import { actRequest, pollMs, type Action, type ActKind, type PlanView, type UltraRun } from "./ultraRunReducer";

export const planPath = (id: string) => `/admin/ultra/plans/${encodeURIComponent(id)}`;
export const READ_TIMEOUT_MS = 20_000;
export const ACT_TIMEOUT_MS = 30_000;

const timedOut = (e: unknown) => e instanceof DOMException && e.name === "TimeoutError";

export function useUltraPlan(planId: string | null, state: UltraRun, dispatch: (a: Action, planId: string) => void) {
  const seq = useRef(0);
  const reading = useRef<number | null>(null);
  const acting = useRef<number | null>(null);

  const read = useCallback(async () => {
    if (!planId || reading.current !== null) return;
    const n = ++seq.current;
    reading.current = n;
    let a: Action;
    try {
      a = { type: "loaded",
        plan: await relay.get<PlanView>(planPath(planId), undefined, AbortSignal.timeout(READ_TIMEOUT_MS)) };
    } catch (e) {
      a = { type: "loadFailed", status: e instanceof RelayError ? e.status : 0,
        message: timedOut(e) ? `no answer in ${READ_TIMEOUT_MS / 1000} s` : errText(e) };
    }
    if (reading.current !== n) return;
    reading.current = null;
    dispatch(a, planId);
  }, [planId, dispatch]);

  useEffect(() => {
    reading.current = null;
    acting.current = null;
    void read();
  }, [read]);

  const every = planId ? pollMs(state) : null;
  useEffect(() => {
    if (every === null) return;
    const t = window.setInterval(() => { void read(); }, every);
    return () => window.clearInterval(t);
  }, [every, read]);

  const act = useCallback(async (kind: ActKind) => {
    if (!planId || acting.current !== null) return;
    const req = actRequest(kind, state);
    if (!req) return;
    const n = ++seq.current;
    acting.current = n;
    dispatch({ type: "act", kind }, planId);
    let a: Action;
    try {
      a = { type: "acted", plan: await relay.post<PlanView>(`${planPath(planId)}/${kind}`, req.body, undefined,
        AbortSignal.timeout(ACT_TIMEOUT_MS)) };
    } catch (e) {
      a = { type: "actFailed", message: timedOut(e) ? `no answer in ${ACT_TIMEOUT_MS / 1000} s; check the steps above before pressing again` : errText(e) };
    }
    if (acting.current !== n) return;
    acting.current = null;
    reading.current = null;
    // a read still out may predate the answer: dropped, so it cannot put the OK back
    dispatch(a, planId);
    if (a.type === "actFailed" || kind !== "cancel") void read();
  }, [planId, state, dispatch, read]);

  return { read, act };
}
