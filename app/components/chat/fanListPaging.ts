import type { Scope } from "@/contexts/ScopeContext";

import type { ActiveChip } from "./FanListFilters";

// Live DMs grow the list unbounded (209 -> 583 rows in 4 min on All Models).
export const ROW_RENDER_STEP = 200;

export interface PagingState {
  view: string;
  renderCap: number;
  userScrolled: boolean;
}

export type PagingAction =
  | { type: "resetFor"; view: string }
  | { type: "scrolled" }
  | { type: "scrollUsed" }
  | { type: "showMore" };

export function pagingView(v: {
  scopeKind: Scope["kind"]; accountKey: string; active: ActiveChip; query: string;
}): string {
  const chip = v.active.kind === "builtin" ? `b:${v.active.key}` : `f:${v.active.listId}`;
  return JSON.stringify([v.scopeKind, v.accountKey, chip, v.query]);
}

export function initialPaging(view: string): PagingState {
  return { view, renderCap: ROW_RENDER_STEP, userScrolled: false };
}

export function pagingReducer(state: PagingState, action: PagingAction): PagingState {
  switch (action.type) {
    case "resetFor":
      return action.view === state.view ? state : initialPaging(action.view);
    case "scrolled":
      return state.userScrolled ? state : { ...state, userScrolled: true };
    case "scrollUsed":
      return state.userScrolled ? { ...state, userScrolled: false } : state;
    case "showMore":
      return { ...state, renderCap: state.renderCap + ROW_RENDER_STEP };
  }
}
