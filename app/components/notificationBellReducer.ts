/**
 * NotificationBell's panel and arrival badge as a pure reducer: whether the
 * panel is open, which tab it shows (OnlyFans, or the owner's Agency), the
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
 *   • `tabsFull` (Messages Pro: the last row opened hit the Fan tab cap)
 *     shows the note until the next row opened, or the next open.
 *   • `cleared` (`chatterly:notif-cleared` — another bell opened, a toast
 *     clicked — or "Mark all read") zeroes the count.
 */

export const BADGE_MAX = 999;

export type BellPane = "of" | "agency";

export interface BellState {
  open: boolean;
  pane: BellPane;
  /** OnlyFans arrivals not yet seen. */
  arrivals: number;
  tabsFull: boolean;
}

export type BellAction =
  /** `agencyUnread`: the Agency tab's unread count, 0 when there is no tab. */
  | { type: "open"; agencyUnread: number }
  | { type: "close" }
  | { type: "pane"; pane: BellPane }
  | { type: "tabsFull"; full: boolean }
  | { type: "arrived" }
  | { type: "cleared" };

export const initialBellState: BellState = { open: false, pane: "of", arrivals: 0, tabsFull: false };

/** The OnlyFans list is what the panel shows: arrivals are seen as they land. */
export function ofListOnScreen(s: BellState): boolean {
  return s.open && s.pane === "of";
}

export function notificationBellReducer(state: BellState, action: BellAction): BellState {
  switch (action.type) {
    case "open": {
      if (state.open) return state;
      const pane: BellPane = state.arrivals === 0 && action.agencyUnread > 0 ? "agency" : "of";
      return { open: true, pane, arrivals: 0, tabsFull: false };
    }
    case "close":
      return state.open ? { ...state, open: false } : state;
    case "pane":
      return {
        ...state, pane: action.pane,
        arrivals: state.open && action.pane === "of" ? 0 : state.arrivals,
      };
    case "tabsFull":
      return state.tabsFull === action.full ? state : { ...state, tabsFull: action.full };
    case "arrived":
      return ofListOnScreen(state) ? state : { ...state, arrivals: Math.min(BADGE_MAX, state.arrivals + 1) };
    case "cleared":
      return state.arrivals === 0 ? state : { ...state, arrivals: 0 };
  }
}
