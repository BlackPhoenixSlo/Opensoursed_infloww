/**
 * NotificationBell's panel and arrival badge as a pure reducer: whether the
 * panel is open, which tab it shows (OnlyFans, the owner's Agency, or the
 * notification Settings), the
 * OnlyFans arrivals counted since they were last seen, and (Messages Pro) the
 * "Fan tabs full" note.
 *
 *   • `arrived` (the toaster's `chatterly:notif-arrived`) counts +1, capped at
 *     BADGE_MAX — unless the OnlyFans list is on screen (`ofListOnScreen`:
 *     open, on the OnlyFans tab). It used to be dropped whenever the panel was
 *     open, so arrivals while the owner read the Agency tab (where the
 *     OnlyFans feed isn't even fetched) never reached the badge: closed, it
 *     read 0 with unseen OnlyFans notifications.
 *   • The OnlyFans list coming on screen marks them seen (0): `open` (always
 *     — opening the bell counts as "seen everything", whichever tab), and
 *     `pane` back to OnlyFans while open.
 *   • `open` lands on Agency when only it has something new (no arrivals,
 *     unread agency notifications); no Agency tab reads as 0 unread, so it
 *     lands on OnlyFans; the tab going away is `pane` back to OnlyFans.
 *   • `openAgency` (the consent banner's "View") opens on Agency, or switches
 *     an open panel to it; the OnlyFans arrivals stay unseen.
 *   • `tabsFull` (Messages Pro: the last row opened hit the Fan tab cap)
 *     shows the note until the next row opened, or the next open.
 *   • `cleared` (`chatterly:notif-cleared` — another bell opened, a row or a
 *     toast clicked) zeroes the count.
 *   • `markRead`: the OnlyFans mark-read write, once per open, when the
 *     OnlyFans list first comes on screen in it (as OF web does on opening
 *     its notifications): "due" then, "sent" once the bell sent it
 *     (`markReadSent`); "none" until the list is shown.
 */

export const BADGE_MAX = 999;

/** Window event: open the top bar bell on its Agency tab (ConsentBanner's "View"). */
export const OPEN_AGENCY_EVENT = "chatterly:open-agency-notifications";

export type BellPane = "of" | "agency" | "settings";

export interface BellState {
  open: boolean;
  pane: BellPane;
  /** OnlyFans arrivals not yet seen. */
  arrivals: number;
  tabsFull: boolean;
  markRead: MarkRead;
}

export type MarkRead = "none" | "due" | "sent";

export type BellAction =
  /** `agencyUnread`: the Agency tab's unread count, 0 when there is no tab. */
  | { type: "open"; agencyUnread: number }
  | { type: "openAgency" }
  | { type: "close" }
  | { type: "pane"; pane: BellPane }
  | { type: "tabsFull"; full: boolean }
  | { type: "arrived" }
  | { type: "cleared" }
  | { type: "markReadSent" };

export const initialBellState: BellState = { open: false, pane: "of", arrivals: 0, tabsFull: false, markRead: "none" };

/** The OnlyFans list is what the panel shows: arrivals are seen as they land. */
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

/** A Creator's cached OnlyFans count (`["of-notif-count", id]`), undefined when never read. */
export type CachedCount = (accountId: string) => number | undefined;

/** Messages Pro's badge under All Models: the cached counts summed, an unknown one as 0. */
export function cachedCountSum(ids: readonly string[], countOf: CachedCount): number {
  return ids.reduce((sum, id) => sum + (countOf(id) ?? 0), 0);
}

/** "Mark all read"'s Creators: every one not known to be at 0 (no OF write for nothing). Known: its cached 0 was
 *  read (`readAt`, epoch ms) after `since`, the last notification this tab saw arrive (any Creator's). */
export function markAllTargets(
  ids: readonly string[], countOf: CachedCount, readAt: (accountId: string) => number, since: number,
): string[] {
  return ids.filter((id) => !(countOf(id) === 0 && readAt(id) > since));
}

/** "Mark all read"'s outcome line: null when every write went through. */
export function markAllStatus(failed: number, of: number): string | null {
  return failed > 0 ? `${failed} of ${of} Creator${of === 1 ? "" : "s"} failed` : null;
}

/** "Mark all read"'s run: whether one is going, and the last run's outcome line (`markAllStatus`). */
export interface MarkAllState { marking: boolean; status: string | null }

export type MarkAllAction = { type: "start" } | { type: "done"; failed: number; of: number };

export const initialMarkAll: MarkAllState = { marking: false, status: null };

/** A run clears the last outcome while it goes; its end sets the new one. */
export function markAllReducer(_state: MarkAllState, action: MarkAllAction): MarkAllState {
  switch (action.type) {
    case "start":
      return { marking: true, status: null };
    case "done":
      return { marking: false, status: markAllStatus(action.failed, action.of) };
  }
}
