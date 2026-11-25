import type { Scope } from "@/contexts/ScopeContext";

import type { ActiveChip } from "./FanListFilters";

// Hard cap on background pagination; search bypasses it.
export const SCROLL_CAP_STEP = 200;
// Live DMs grow the list unbounded (209 -> 583 rows in 4 min on All Models).
export const ROW_RENDER_STEP = 200;
export const AUTOFILL_MAX_BURSTS = 10;

export interface PagingState {
  view: string;
  capRows: number;
  renderCap: number;
  userScrolled: boolean;
  autofillBursts: number;
}

export type PagingAction =
  | { type: "resetFor"; view: string }
  | { type: "scrolled" }
  | { type: "extendCap"; loaded: number }
  | { type: "showMore" }
  | { type: "autofilled" };

export function pagingView(v: {
  scopeKind: Scope["kind"]; accountKey: string; active: ActiveChip; query: string;
}): string {
  const chip = v.active.kind === "builtin" ? `b:${v.active.key}` : `f:${v.active.listId}`;
  return JSON.stringify([v.scopeKind, v.accountKey, chip, v.query]);
}

export function initialPaging(view: string): PagingState {
  return { view, capRows: SCROLL_CAP_STEP, renderCap: ROW_RENDER_STEP, userScrolled: false, autofillBursts: 0 };
}

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
