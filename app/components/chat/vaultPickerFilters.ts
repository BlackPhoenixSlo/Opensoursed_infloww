import type { FanId } from "@/lib/fanId";
import type { DurationRange } from "./vaultDurationFilter";
import type { StatsSort } from "./vaultPickerStats";

export type MediaType = "all" | "photo" | "video" | "gif";
export type Sort = "newest" | "oldest" | StatsSort;

export interface VaultFilterState {
  type: MediaType;
  listId: FanId | null;
  sort: Sort;
  hideSeen: boolean;
  lengthRange: DurationRange;
  queryInput: string;
  query: string;
}

export type PickerFanState = Pick<VaultFilterState, "listId" | "sort" | "type">;

export type VaultFilterAction =
  | { type: "setType"; value: MediaType }
  | { type: "setListId"; value: FanId | null }
  | { type: "setSort"; value: Sort }
  | { type: "setHideSeen"; value: boolean }
  | { type: "setLengthRange"; value: DurationRange }
  | { type: "setQueryInput"; value: string }
  | { type: "commitQuery"; value: string }
  | { type: "clearQuery" }
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

export function fetchSort(sort: Sort): "newest" | "oldest" {
  return sort === "oldest" ? "oldest" : "newest";
}
