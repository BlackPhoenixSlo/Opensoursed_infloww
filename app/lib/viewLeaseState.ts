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

export function union(state: ViewLeaseState): string[] {
  return [...sortedIds(Object.values(state.sources).flat())];
}

export function leases(state: ViewLeaseState): boolean {
  return state.ready && !state.hidden && !state.idle;
}

export function leaseBody(state: ViewLeaseState, tab: string): LeaseBody {
  const on = leases(state);
  return { tab, account_ids: on ? union(state) : [], selected: on ? selectedOf(state) : null, opened: !state.openSent };
}

export function canPost(state: ViewLeaseState): boolean {
  return leases(state) || (state.ready && !state.openSent);
}

export function shouldPostNow(prev: ViewLeaseState, next: ViewLeaseState): boolean {
  if (!canPost(next)) return false;
  if (!canPost(prev)) return true;
  if (!leases(next)) return false;
  if (!leases(prev)) return true;
  if (selectedOf(next) !== selectedOf(prev)) return true;
  const had = new Set(union(prev));
  return union(next).some((a) => !had.has(a));
}
