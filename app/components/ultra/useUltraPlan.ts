"use client";

/**
 * One Ultra plan's I/O, shared by the plan page and the help bot's Ultra panel: read it on mount, re-read every
 * `pollMs` while it can still change (none once FINAL), and post OK / Cancel / pick (each answers the plan; an OK
 * or pick is read again at once).
 * State stays in the caller's reducer (ultraRunReducer actions, each tagged with the plan id it is for);
 * `planId` null = nothing to read.
 *
 * Order: every read and act takes a number. One read at a time (a poll tick while one is out is skipped) and one act
 * at a time (a second press before the first answers posts nothing). Polling goes on while a press is out (`busy`
 * keeps the buttons right); when the press answers, the read out then is dropped (its number is no longer the one
 * out) and the plan is read once, so a slow pre-answer read can never put the OK back on screen. A new plan drops
 * everything out. A read gets READ_TIMEOUT_MS, a press ACT_TIMEOUT_MS (then it fails, is never re-posted, and the
 * plan is read to show what happened).
 */
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
  /** The read / act out now; a press or a new plan clears `reading`, so the read out then is dropped. */
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
    // A new plan: whatever was out for the last one is forgotten (and dropped when it lands).
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
    if (acting.current !== n) return;  // the plan changed meanwhile
    acting.current = null;
    // The answer to the press always lands (it clears busy); a read still out may predate it: dropped.
    reading.current = null;
    dispatch(a, planId);
    // The run goes on in the background: read at once so the steps show it, not after a poll interval.
    if (a.type === "actFailed" || kind !== "cancel") void read();
  }, [planId, state, dispatch, read]);

  return { read, act };
}
