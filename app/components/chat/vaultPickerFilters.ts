/**
 * VaultPicker's filter bar as a pure reducer: media type, folder, sort,
 * hide-seen, length range and the vault search (raw input + the debounced
 * query OF is asked for). The component owns the debounce timer and only
 * dispatches.
 */

import type { FanId } from "@/lib/fanId";
import type { DurationRange } from "./vaultDurationFilter";
import type { StatsSort } from "./vaultPickerStats";

export type MediaType = "all" | "photo" | "video" | "gif";
/** "newest" / "oldest" are OF's order; the stats sorts reorder what's loaded. */
export type Sort = "newest" | "oldest" | StatsSort;

export interface VaultFilterState {
  type: MediaType;
  listId: FanId | null;
  sort: Sort;
  /** "Hide content viewed or unlocked by fan, or posted on Creator's feed". */
  hideSeen: boolean;
  lengthRange: DurationRange;
  /** What's typed in the search box. */
  queryInput: string;
  /** The debounced, trimmed search sent to OF (wire param `query`). */
  query: string;
}

/** What's persisted per fan (vaultPickerPersist): folder, sort, type. */
export type PickerFanState = Pick<VaultFilterState, "listId" | "sort" | "type">;

export type VaultFilterAction =
  | { type: "setType"; value: MediaType }
  | { type: "setListId"; value: FanId | null }
  | { type: "setSort"; value: Sort }
  | { type: "setHideSeen"; value: boolean }
  | { type: "setLengthRange"; value: DurationRange }
  | { type: "setQueryInput"; value: string }
  /** The debounce fired: search for what was typed. */
  | { type: "commitQuery"; value: string }
  | { type: "clearQuery" }
  /** Picker opened (closed → open): restore this fan's folder / sort / type,
   *  or All / Newest / All-types when he has none. Search starts clean. */
  | { type: "hydrate"; saved: PickerFanState | null };

export const initialFilters: VaultFilterState = {
  type: "all",
  listId: null,
  sort: "newest",
  hideSeen: false,
  lengthRange: "any",
  queryInput: "",
  query: "",
};

/** `state` itself when nothing changes, so React bails out of the render
 *  exactly as the per-field useStates this replaced did. */
function patch(state: VaultFilterState, next: Partial<VaultFilterState>): VaultFilterState {
  const keys = Object.keys(next) as (keyof VaultFilterState)[];
  return keys.every((k) => Object.is(state[k], next[k])) ? state : { ...state, ...next };
}

export function vaultFiltersReducer(state: VaultFilterState, action: VaultFilterAction): VaultFilterState {
  switch (action.type) {
    case "setType":
      return patch(state, { type: action.value });
    case "setListId":
      return patch(state, { listId: action.value });
    case "setSort":
      return patch(state, { sort: action.value });
    case "setHideSeen":
      return patch(state, { hideSeen: action.value });
    case "setLengthRange":
      return patch(state, { lengthRange: action.value });
    case "setQueryInput":
      return patch(state, { queryInput: action.value });
    case "commitQuery":
      return patch(state, { query: action.value.trim() });
    case "clearQuery":
      return patch(state, { queryInput: "", query: "" });
    case "hydrate":
      return patch(state, {
        type: action.saved?.type ?? "all",
        sort: action.saved?.sort ?? "newest",
        listId: action.saved?.listId ?? null,
        queryInput: "",
        query: "",
      });
  }
}

/** The stats sorts reorder the newest-first pages OF serves. */
export function fetchSort(sort: Sort): "newest" | "oldest" {
  return sort === "oldest" ? "oldest" : "newest";
}
