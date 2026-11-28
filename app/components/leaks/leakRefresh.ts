import { parseUtc } from "@/lib/format";
import { RelayError } from "@/lib/relay";

import { when } from "./leakView";

type RefreshPhase = "ready" | "sending" | "failed";

export type RefreshState = {
  phase: RefreshPhase;
  nextRefreshAt: string | null;
  pending: boolean;
  message: string | null;
};

export type Action =
  | { type: "load"; nextRefreshAt: string | null; pending: boolean }
  | { type: "send" }
  | { type: "queued"; nextRefreshAt: string }
  | { type: "cooldown"; nextRefreshAt: string }
  | { type: "fail"; message: string };

export type RefreshView = { label: string; disabled: boolean; note: string | null; error: boolean };

const REFRESH_NOW = "Refresh now";
const REFRESHING = "Refreshing…";
const CHECKING = "Checking…";
const ONCE_A_DAY = "One refresh per Creator every 24 hours";

export const loaded = (nextRefreshAt: string | null, pending: boolean): RefreshState =>
  ({ phase: "ready", nextRefreshAt, pending, message: null });

export function refreshReducer(state: RefreshState, action: Action): RefreshState {
  const sending = state.phase === "sending";
  switch (action.type) {
    case "load":
      return sending ? { ...state, nextRefreshAt: action.nextRefreshAt, pending: action.pending } : loaded(action.nextRefreshAt, action.pending);
    case "send":
      return sending || state.pending ? state : { ...state, phase: "sending", message: null };
    case "queued":
      return sending ? loaded(action.nextRefreshAt, true) : state;
    case "cooldown":
      return sending ? loaded(action.nextRefreshAt, state.pending) : state;
    case "fail":
      return sending ? { ...state, phase: "failed", message: action.message } : state;
  }
}

export function refreshView(state: RefreshState, now: Date, tz: string): RefreshView {
  if (state.phase === "sending") return { label: REFRESHING, disabled: true, note: null, error: false };
  if (state.pending) return { label: CHECKING, disabled: true, note: null, error: false };
  const next = state.nextRefreshAt ? parseUtc(state.nextRefreshAt) : null;
  const at = state.nextRefreshAt && next && next.getTime() > now.getTime() ? when(state.nextRefreshAt, now, tz) : null;
  if (at) return { label: `Next refresh ${at}`, disabled: true, note: ONCE_A_DAY, error: false };
  const failed = state.phase === "failed";
  return { label: REFRESH_NOW, disabled: false, note: failed ? state.message : null, error: failed };
}

export function cooldownUntil(e: unknown): string | null {
  if (!(e instanceof RelayError) || e.status !== 429) return null;
  const body = e.body;
  if (typeof body !== "object" || body === null || !("next_refresh_at" in body)) return null;
  return typeof body.next_refresh_at === "string" ? body.next_refresh_at : null;
}

export const RECHECK_MS = 30_000;
export const RECHECK_FOR_MS = 10 * 60_000;

export function recheck(pending: boolean, since: number | null, now: number): { every: number | false; since: number | null } {
  if (!pending) return { every: false, since: null };
  const from = since ?? now;
  return { every: now - from < RECHECK_FOR_MS ? RECHECK_MS : false, since: from };
}
