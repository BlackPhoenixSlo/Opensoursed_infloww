/**
 * Creator reports' filters: the range (a preset, or the days typed in), the Creators picked and the one "Shown by"
 * bucket every chart draws in. They change together (Reset puts all three back), so one pure reducer holds them;
 * CompetitorReports only dispatches. A preset's days are derived by the caller each render, so they follow the
 * report time zone; only the custom days are kept here.
 */
import type { Gran } from "@/components/stats/chart";
import { DEFAULT_RANGE, type RangeKey } from "./reportsMath";

export interface CreatorReportsFilters {
  preset: RangeKey;
  /** The days typed in; they stay while a preset is picked. */
  custom: { from: string | null; to: string | null };
  /** null ≡ every Creator; a Set ≡ the Creators picked. */
  selectedIds: Set<string> | null;
  /** The toolbar's "Shown by" bucket, used by the Overview's charts and Creator performance alike (#4). */
  gran: Gran;
}

export type Action =
  /** A preset brings its own days (derived by the caller); the custom days stay. */
  | { type: "preset"; preset: RangeKey }
  /** Custom: the days typed in, or (picking Custom) the days shown (#14). */
  | { type: "custom"; from: string | null; to: string | null }
  | { type: "select"; ids: Set<string> | null }
  | { type: "gran"; gran: Gran }
  | { type: "reset" };

/** #21, #37: the default range, every Creator, Day. */
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
      // The custom days typed in stay, as they do when a preset is picked.
      return { ...INITIAL_FILTERS, custom: state.custom };
  }
}
