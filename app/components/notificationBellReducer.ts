import { accountCan } from "@/lib/platform";
import type { AccountMeta } from "@/lib/relay";

export const BADGE_MAX = 999;

export const OPEN_AGENCY_EVENT = "chatterly:open-agency-notifications";

export type BellPane = "of" | "agency" | "settings";

export interface BellState {
  open: boolean;
  pane: BellPane;
  arrivals: number;
  tabsFull: boolean;
  markRead: MarkRead;
}

export type MarkRead = "none" | "due" | "sent";

export type BellAction =
  | { type: "open"; agencyUnread: number }
  | { type: "openAgency" }
  | { type: "close" }
  | { type: "pane"; pane: BellPane }
  | { type: "tabsFull"; full: boolean }
  | { type: "arrived" }
  | { type: "cleared" }
  | { type: "markReadSent" };

export const initialBellState: BellState = { open: false, pane: "of", arrivals: 0, tabsFull: false, markRead: "none" };

export function ofListOnScreen(s: BellState): boolean {
  return s.open && s.pane === "of";
}

export function notificationBellReducer(state: BellState, action: BellAction): BellState {
  switch (action.type) {
    case "open": {
      if (state.open) return state;
      const pane: BellPane = state.arrivals === 0 && action.agencyUnread > 0 ? "agency" : "of";
      return { open: true, pane, arrivals: 0, tabsFull: false, markRead: pane === "of" ? "due" : "none" };
    }
    case "openAgency":
      if (state.open) return state.pane === "agency" ? state : { ...state, pane: "agency", tabsFull: false };
      return { ...state, open: true, pane: "agency", tabsFull: false, markRead: "none" };
    case "close":
      return state.open ? { ...state, open: false } : state;
    case "pane": {
      const ofShown = state.open && action.pane === "of";
      return {
        ...state, pane: action.pane,
        arrivals: ofShown ? 0 : state.arrivals,
        markRead: ofShown && state.markRead === "none" ? "due" : state.markRead,
      };
    }
    case "tabsFull":
      return state.tabsFull === action.full ? state : { ...state, tabsFull: action.full };
    case "arrived":
      return ofListOnScreen(state) ? state : { ...state, arrivals: Math.min(BADGE_MAX, state.arrivals + 1) };
    case "cleared":
      return state.arrivals === 0 ? state : { ...state, arrivals: 0 };
    case "markReadSent":
      return state.markRead === "due" ? { ...state, markRead: "sent" } : state;
  }
}

export type CachedCount = (accountId: string) => number | undefined;

export function cachedCountSum(ids: readonly string[], countOf: CachedCount): number {
  return ids.reduce((sum, id) => sum + (countOf(id) ?? 0), 0);
}

export function markAllTargets(
  ids: readonly string[], countOf: CachedCount, readAt: (accountId: string) => number, since: number,
): string[] {
  return ids.filter((id) => !(countOf(id) === 0 && readAt(id) > since));
}

type PlatformAccount = Pick<AccountMeta, "id" | "platform">;

export function markAllControl(liveIds: readonly string[], accounts: readonly PlatformAccount[]): { ids: string[]; shown: boolean } {
  const ids = liveIds.filter((id) => accountCan(accounts, id, "notifications_read"));
  return { ids, shown: liveIds.length === 0 || ids.length > 0 };
}

export function markAllStatus(failed: number, of: number): string | null {
  return failed > 0 ? `${failed} of ${of} Creator${of === 1 ? "" : "s"} failed` : null;
}

export interface MarkAllState { marking: boolean; status: string | null }

export type MarkAllAction = { type: "start" } | { type: "done"; failed: number; of: number };

export const initialMarkAll: MarkAllState = { marking: false, status: null };

export function markAllReducer(_state: MarkAllState, action: MarkAllAction): MarkAllState {
  switch (action.type) {
    case "start":
      return { marking: true, status: null };
    case "done":
      return { marking: false, status: markAllStatus(action.failed, action.of) };
  }
}
