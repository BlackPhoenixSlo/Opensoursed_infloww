import { parseUtc } from "@/lib/format";
import { RelayError } from "@/lib/relay";

import { when } from "./leakView";

export type RefreshState = {
  sending: boolean;
  localNextRefreshAt: string | null;
  error: Error | null;
};

export type RefreshServerState = { nextRefreshAt: string | null; pending: boolean; expired: boolean };
export type RefreshView = { label: string; disabled: boolean; note: string | null; error: boolean };

export function nextRefreshTime(local: string | null, server: string | null): string | null {
  return (parseUtc(local)?.getTime() ?? 0) > (parseUtc(server)?.getTime() ?? 0) ? local : server;
}

export function refreshView(state: RefreshState, server: RefreshServerState, now: Date, tz: string): RefreshView {
  if (state.sending) return { label: "Refreshing…", disabled: true, note: null, error: false };
  if (server.expired) return { label: "Check refresh status", disabled: false, note: null, error: false };
  if (server.pending) return { label: "Checking…", disabled: true, note: null, error: false };
  const until = nextRefreshTime(state.localNextRefreshAt, server.nextRefreshAt);
  const next = parseUtc(until);
  const at = until && next && next.getTime() > now.getTime() ? when(until, now, tz) : null;
  const limit = cooldown(state.error);
  if (at) {
    const note = limit?.note ?? "One refresh per Creator every 24 hours";
    return { label: `Next refresh ${at}`, disabled: true, note, error: false };
  }
  const error = state.error && !limit ? state.error.message : null;
  return { label: "Refresh now", disabled: false, note: error, error: error !== null };
}

export const unchanged = (e: Error) => e instanceof RelayError && (e.status === 429 || e.status === 503);

export function cooldown(e: unknown): { until: string; note: string | null } | null {
  if (!(e instanceof RelayError) || e.status !== 429) return null;
  const body = e.body;
  if (typeof body !== "object" || body === null || !("next_refresh_at" in body)) return null;
  if (typeof body.next_refresh_at !== "string") return null;
  return { until: body.next_refresh_at, note: "kind" in body && body.kind === "rate_limited" ? e.message : null };
}

export const RECHECK_MS = 30_000;
export const RECHECK_FOR_MS = 10 * 60_000;

type RefreshCheck =
  | { phase: "idle" | "expired" | "done" }
  | { phase: "checking"; started: number; next: string | null; seenPending: boolean; queuedAt: string | null };

type RefreshAction =
  | { type: "acked"; at: number; next: string; queuedAt: string }
  | { type: "read"; at: number; pending: boolean; fresh: boolean; next: string | null; checkedAt: string | null }
  | { type: "expired" | "settled" };

export function refreshCheck(state: RefreshCheck, action: RefreshAction): RefreshCheck {
  switch (action.type) {
    case "acked":
      return { phase: "checking", started: action.at, next: action.next, seenPending: false, queuedAt: action.queuedAt };
    case "expired":
      return state.phase === "checking" ? { phase: "expired" } : state;
    case "settled":
      return { phase: "idle" };
    case "read":
      if (state.phase === "idle" && action.pending) {
        return { phase: "checking", started: action.at, next: null, seenPending: true, queuedAt: null };
      }
      if (state.phase === "expired" && !action.pending && action.fresh) return { phase: "done" };
      if (state.phase !== "checking" || action.at < state.started) return state;
      if (action.pending) return state.seenPending ? state : { ...state, seenPending: true };
      const expected = parseUtc(state.next)?.getTime();
      const queued = parseUtc(state.queuedAt)?.getTime() ?? state.started;
      const checked = parseUtc(action.checkedAt)?.getTime();
      if (action.fresh && (state.seenPending || (checked !== undefined && checked >= queued)
        || (expected !== undefined && parseUtc(action.next)?.getTime() === expected))) return { phase: "done" };
      return state;
  }
}
