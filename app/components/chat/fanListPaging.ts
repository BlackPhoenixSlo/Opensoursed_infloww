/**
 * The Fan List's paging budget as one pure reducer: the scroll cap on
 * background pagination, the rendered-row cap, the "user has scrolled" gate on
 * the scroll loader, and the autofill burst count. The pages themselves (rows,
 * offset, hasMore, loading) live in useChatList's infinite query, keyed by
 * scope, Creator set, filter, folder and search, so a page answering a list
 * left behind lands in that list's cache entry, never in the one on screen.
 *
 *   • `resetFor(view)` gives a new list a fresh budget, all four pieces in one
 *     action. `pagingView` is the list on screen: scope, the Creator set it is
 *     fetched for, the chip or folder, the search. Three effects on different
 *     deps used to do this; the caps and the scroll gate missed the Creator
 *     set, so in All Models a model joining or leaving started a new list that
 *     kept the old one's scroll permission. The same view resets nothing. The
 *     sort and the Split Inbox group order or narrow the loaded rows, not the
 *     list: no reset.
 *   • `autofilled` spends one of the bursts of the list on screen: its
 *     loadMore pages that list too (through useChatList), so the two agree.
 */

import type { Scope } from "@/contexts/ScopeContext";

import type { ActiveChip } from "./FanListFilters";

// Hard cap on background pagination. Search bypasses (otherwise typo'd
// queries dead-end after 200 rows). "Load more" click extends by another step.
export const SCROLL_CAP_STEP = 200;
// Rows rendered at most, per "Show more" step. Live messages insert rows for
// Fans not yet in the list (useInboxRealtime), so under a DM flood the list
// grows without bound (measured 209 -> 583 rows in 4 minutes on All Models);
// the rest stay in the data (chip counts, Select all) and wait
// behind a "Show N more" row at the end.
export const ROW_RENDER_STEP = 200;
/** Autofill bursts per list (confirmed sufficient at 80% zoom; 100% zoom
 *  users need at least this many to reach overflow). */
export const AUTOFILL_MAX_BURSTS = 10;

export interface PagingState {
  /** The list this budget belongs to (`pagingView`). */
  view: string;
  capRows: number;
  renderCap: number;
  userScrolled: boolean;
  autofillBursts: number;
}

export type PagingAction =
  | { type: "resetFor"; view: string }
  | { type: "scrolled" }
  /** "Load more conversations" at the cap: `loaded` = raw rows loaded. */
  | { type: "extendCap"; loaded: number }
  | { type: "showMore" }
  | { type: "autofilled" };

/** The list on screen. `accountKey` is useChatList's `chatListAccountKey`. */
export function pagingView(v: {
  scopeKind: Scope["kind"]; accountKey: string; active: ActiveChip; query: string;
}): string {
  const chip = v.active.kind === "builtin" ? `b:${v.active.key}` : `f:${v.active.listId}`;
  return JSON.stringify([v.scopeKind, v.accountKey, chip, v.query]);
}

export function initialPaging(view: string): PagingState {
  return { view, capRows: SCROLL_CAP_STEP, renderCap: ROW_RENDER_STEP, userScrolled: false, autofillBursts: 0 };
}

/** Paginated up to the cap with no search. Measured against the RAW loaded
 *  rows, not the filter view: owe-reply displays a handful of matches but
 *  each page still costs a roundtrip, so the cap bites either way. */
export function isCapped(s: PagingState, loaded: number, query: string): boolean {
  return !query && loaded >= s.capRows;
}

export function canAutofill(s: PagingState): boolean {
  return s.autofillBursts < AUTOFILL_MAX_BURSTS;
}

export function pagingReducer(state: PagingState, action: PagingAction): PagingState {
  switch (action.type) {
    case "resetFor":
      return action.view === state.view ? state : initialPaging(action.view);
    case "scrolled":
      return state.userScrolled ? state : { ...state, userScrolled: true };
    case "extendCap":
      return { ...state, capRows: action.loaded + SCROLL_CAP_STEP };
    case "showMore":
      return { ...state, renderCap: state.renderCap + ROW_RENDER_STEP };
    case "autofilled":
      return { ...state, autofillBursts: state.autofillBursts + 1 };
  }
}
