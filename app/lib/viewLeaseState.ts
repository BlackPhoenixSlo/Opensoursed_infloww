/**
 * This tab's View lease (ADR-0031, phase-01): the Creators it holds on screen, per lease source, and where this
 * document load's opening post stands. A pure reducer (ViewLeaseHeartbeat only dispatches), `union` (the Creators
 * the next post leases), `leaseBody` (that post) and `shouldPostNow` (a change that posts at once, not at the next
 * VIEW_LEASE_RENEW_MS tick).
 *
 * SELECTED_SOURCE is the scope provider's selected Creator: its one id is the post's `selected` too. The other
 * sources are the on-screen holds, one per key (`holdLease` / `useViewLease`): the open chat, the rail's, the strip's
 * and OF Manager's column's visible rows. A source's Hold replaces its set; Release drops it.
 *
 * `hidden` (the page's visibilityState) and `idle` (Idle mode, useIdleMode): such a tab renews nothing (`canPost`), so
 * its lease lapses within the Relay's TTL; shown again or back from Idle, it posts at once. A load that opens hidden or
 * idle still sends its opening post (every document load is an App-open warm), leasing nothing (`leases`).
 *
 * `ready`: the event stream opened, or OPENED_WAIT_MS passed (Opened); nothing posts before it. `openSent`: a post
 * carrying `opened: true` (the Relay's App-open warm) was answered (Posted); until then every post carries it, so a
 * failed first post is retried by the next one. A remount (a sign-in without a reload) starts over: a fresh login is
 * an app open.
 */

export const SELECTED_SOURCE = "selected";

export interface ViewLeaseState {
  sources: Readonly<Record<string, readonly string[]>>;
  ready: boolean;
  openSent: boolean;
  hidden: boolean;
  idle: boolean;
}

export type Action =
  | { type: "Hold"; source: string; accountIds: readonly string[] }
  | { type: "Release"; source: string }
  | { type: "Visibility"; hidden: boolean }
  | { type: "Idle"; idle: boolean }
  | { type: "Opened" }
  | { type: "Posted"; opened: boolean };

export interface LeaseBody {
  tab: string;
  account_ids: string[];
  selected: string | null;
  opened: boolean;
}

export const INITIAL_LEASE: ViewLeaseState = { sources: {}, ready: false, openSent: false, hidden: false, idle: false };

/** `ids` once each, sorted; `prev` itself when it holds the same Creators, so a change that changes nothing keeps
 *  its identity (a reducer's same state, a hook's same set). */
export function sortedIds(ids: readonly string[], prev?: readonly string[]): readonly string[] {
  const next = [...new Set(ids)].sort();
  return prev && prev.length === next.length && prev.every((x, i) => x === next[i]) ? prev : next;
}

export function viewLeaseReducer(state: ViewLeaseState, action: Action): ViewLeaseState {
  switch (action.type) {
    case "Hold": {
      const prev = state.sources[action.source];
      const ids = sortedIds(action.accountIds, prev);
      return ids === prev ? state : { ...state, sources: { ...state.sources, [action.source]: ids } };
    }
    case "Release": {
      if (!(action.source in state.sources)) return state;
      const rest = { ...state.sources };
      delete rest[action.source];
      return { ...state, sources: rest };
    }
    case "Visibility":
      return state.hidden === action.hidden ? state : { ...state, hidden: action.hidden };
    case "Idle":
      return state.idle === action.idle ? state : { ...state, idle: action.idle };
    case "Opened":
      return state.ready ? state : { ...state, ready: true };
    case "Posted":
      return action.opened && !state.openSent ? { ...state, openSent: true } : state;
  }
}

export function selectedOf(state: ViewLeaseState): string | null {
  return state.sources[SELECTED_SOURCE]?.[0] ?? null;
}

/** Every source's Creators, once each, sorted. */
export function union(state: ViewLeaseState): string[] {
  return [...sortedIds(Object.values(state.sources).flat())];
}

/** Whether this tab's posts lease anything: ready, shown and not in Idle mode. */
export function leases(state: ViewLeaseState): boolean {
  return state.ready && !state.hidden && !state.idle;
}

export function leaseBody(state: ViewLeaseState, tab: string): LeaseBody {
  const on = leases(state);
  return { tab, account_ids: on ? union(state) : [], selected: on ? selectedOf(state) : null, opened: !state.openSent };
}

/** Whether this tab posts at all: one that leases, or a ready one whose opening post is still unanswered (a load
 *  opened hidden or idle). The renewal tick asks it too. */
export function canPost(state: ViewLeaseState): boolean {
  return leases(state) || (state.ready && !state.openSent);
}

/** Post now: the tab just became able to post (ready: the opening post), it leases again (shown again or back from
 *  Idle mode), the selected Creator changed (its Select refresh), or the union gained a Creator. A loss waits for the
 *  next tick. Never while it cannot post; a change while it leases nothing waits for it to lease. */
export function shouldPostNow(prev: ViewLeaseState, next: ViewLeaseState): boolean {
  if (!canPost(next)) return false;
  if (!canPost(prev)) return true;
  if (!leases(next)) return false;
  if (!leases(prev)) return true;
  if (selectedOf(next) !== selectedOf(prev)) return true;
  const had = new Set(union(prev));
  return union(next).some((a) => !had.has(a));
}
