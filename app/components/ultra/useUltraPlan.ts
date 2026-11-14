"use client";

/**
 * One Ultra plan's I/O, shared by the plan page and the help bot's Ultra panel: read it on mount, re-read every
 * `pollMs` while it can still change (none once FINAL), and post OK / Cancel / pick (each answers the plan; an OK
 * or pick is read again at once).
 * State stays in the caller's reducer (ultraRunReducer actions); `planId` null = nothing to read.
 */
import { useCallback, useEffect } from "react";

import { errText } from "@/lib/errText";
import { relay, RelayError } from "@/lib/relay";
import { actRequest, pollMs, type Action, type ActKind, type PlanView, type UltraRun } from "./ultraRunReducer";

export const planPath = (id: string) => `/admin/ultra/plans/${encodeURIComponent(id)}`;

export function useUltraPlan(planId: string | null, state: UltraRun, dispatch: (a: Action) => void) {
  const read = useCallback(async () => {
    if (!planId) return;
    try {
      dispatch({ type: "loaded", plan: await relay.get<PlanView>(planPath(planId)) });
    } catch (e) {
      dispatch({ type: "loadFailed", status: e instanceof RelayError ? e.status : 0, message: errText(e) });
    }
  }, [planId, dispatch]);

  useEffect(() => { void read(); }, [read]);

  const every = planId ? pollMs(state) : null;
  useEffect(() => {
    if (every === null) return;
    const t = window.setInterval(() => { void read(); }, every);
    return () => window.clearInterval(t);
  }, [every, read]);

  const act = useCallback(async (kind: ActKind) => {
    if (!planId) return;
    const req = actRequest(kind, state);
    if (!req) return;
    dispatch({ type: "act", kind });
    try {
      dispatch({ type: "acted", plan: await relay.post<PlanView>(`${planPath(planId)}/${kind}`, req.body) });
      // The run goes on in the background: read at once so the steps show it, not after a poll interval.
      if (kind !== "cancel") void read();
    } catch (e) {
      dispatch({ type: "actFailed", message: errText(e) });
      void read();
    }
  }, [planId, state, dispatch, read]);

  return { read, act };
}
