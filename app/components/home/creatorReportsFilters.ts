import type { Gran } from "@/components/stats/chart";
import { DEFAULT_RANGE, type RangeKey } from "./reportsMath";

export interface CreatorReportsFilters {
  preset: RangeKey;
  custom: { from: string | null; to: string | null };
  selectedIds: Set<string> | null;
  gran: Gran;
}

export type Action =
  | { type: "preset"; preset: RangeKey }
  | { type: "custom"; from: string | null; to: string | null }
  | { type: "select"; ids: Set<string> | null }
  | { type: "gran"; gran: Gran }
  | { type: "reset" };

export const INITIAL_FILTERS: CreatorReportsFilters = {
  preset: DEFAULT_RANGE,
  custom: { from: null, to: null },
  selectedIds: null,
  gran: "day",
};

export function creatorReportsFiltersReducer(state: CreatorReportsFilters, action: Action): CreatorReportsFilters {
  switch (action.type) {
    case "preset":
      return { ...state, preset: action.preset };
    case "custom":
      return { ...state, preset: "custom", custom: { from: action.from, to: action.to } };
    case "select":
      return { ...state, selectedIds: action.ids };
    case "gran":
      return { ...state, gran: action.gran };
    case "reset":
      return { ...INITIAL_FILTERS, custom: state.custom };
  }
}
