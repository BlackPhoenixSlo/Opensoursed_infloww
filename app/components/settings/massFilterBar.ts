/**
 * The OF mass messages filter bar (capture growth-smart-messages #66 to #79) as a pure reducer: the typed
 * draft (search, Sending Date range), what Search applied, and the list's "Sent in" window, which a Sending
 * Date older than it widens (the cache read takes only `days_back`). Reset clears the draft and the applied
 * filter and returns the window to the user's last pick. `filterMassRows` applies a filter client side over the loaded rows; `massCsvRows` is Export's sheet.
 * The list's own filters live here too, as they decide the listed rows and the bulk targets with the bar: the model
 * chips (`models`, empty = every Creator; bulk actions take this scope) and "Hide unsent".
 */

import { dayOf } from "@/components/growth/automatedRows";
import type { MassMessageRow } from "@/hooks/useMassMessages";
import { ofPlainText } from "@/lib/ofRichText";

export interface MassFilters {
  q: string;
  /** Sending Date, YYYY-MM-DD in the report time zone; "" = open. */
  from: string;
  to: string;
}

export const NO_MASS_FILTERS: MassFilters = { q: "", from: "", to: "" };

/** The "Sent in" choices, in days (the cache read's `days_back`). */
export const RANGE_DAYS = [7, 30, 90, 365] as const;

export interface MassFilterState {
  draft: MassFilters;
  applied: MassFilters;
  daysBack: number;
  /** The last "Sent in" the user picked; Reset returns to it after a Sending Date widened the window. */
  pickedDays: number;
  /** The model chips' pick; empty = every Creator. Reset leaves it (it is the list's filter, not the bar's). */
  models: ReadonlySet<string>;
  hideUnsent: boolean;
}

export type MassFilterAction =
  | { type: "draft"; patch: Partial<MassFilters> }
  /** Search: the draft becomes the filter; `now` (ms) sizes the window a Sending Date start needs. */
  | { type: "apply"; now: number }
  | { type: "reset" }
  | { type: "daysBack"; days: number }
  | { type: "hideUnsent"; on: boolean }
  /** A model chip: in the pick or out of it. */
  | { type: "toggleModel"; id: string }
  /** "All": no model filter. */
  | { type: "allModels" }
  /** The active Creators now: a picked one no longer active leaves the pick. */
  | { type: "liveModels"; ids: readonly string[] };

export const initialMassFilter: MassFilterState = {
  draft: NO_MASS_FILTERS, applied: NO_MASS_FILTERS, daysBack: 30, pickedDays: 30, models: new Set(), hideUnsent: true,
};

/** The smallest "Sent in" window holding `from` (one day of slack for the time zone), the widest when none
 *  does; null without a start. */
export function daysToCover(from: string, now: number): number | null {
  if (!from) return null;
  const t = Date.parse(`${from}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  const need = Math.ceil((now - t) / 86_400_000) + 1;
  return RANGE_DAYS.find((d) => d >= need) ?? RANGE_DAYS[RANGE_DAYS.length - 1];
}

export function massFilterReducer(state: MassFilterState, action: MassFilterAction): MassFilterState {
  switch (action.type) {
    case "draft":
      return { ...state, draft: { ...state.draft, ...action.patch } };
    case "apply": {
      const applied = { ...state.draft, q: state.draft.q.trim() };
      return { ...state, applied, daysBack: Math.max(state.daysBack, daysToCover(applied.from, action.now) ?? 0) };
    }
    case "reset":
      return { ...state, draft: NO_MASS_FILTERS, applied: NO_MASS_FILTERS, daysBack: state.pickedDays };
    case "daysBack":
      return { ...state, daysBack: action.days, pickedDays: action.days };
    case "hideUnsent":
      return { ...state, hideUnsent: action.on };
    case "toggleModel": {
      const models = new Set(state.models);
      if (models.has(action.id)) models.delete(action.id);
      else models.add(action.id);
      return { ...state, models };
    }
    case "allModels":
      return state.models.size === 0 ? state : { ...state, models: new Set() };
    case "liveModels": {
      const models = new Set([...state.models].filter((id) => action.ids.includes(id)));
      return models.size === state.models.size ? state : { ...state, models };
    }
  }
}

/** The rows the applied filter keeps: the message text holds the search (any case), and the send day (report
 *  time zone) sits in the Sending Date range; a row with no send time fails any date bound. */
export function filterMassRows(rows: MassMessageRow[], f: MassFilters, timeZone: string | null): MassMessageRow[] {
  const q = f.q.trim().toLowerCase();
  if (!q && !f.from && !f.to) return rows;
  return rows.filter((m) => {
    if (q && !ofPlainText(m.text || m.rawText || "").toLowerCase().includes(q)) return false;
    if (f.from || f.to) {
      const day = dayOf(m.date ?? null, timeZone);
      if (!day || (f.from && day < f.from) || (f.to && day > f.to)) return false;
    }
    return true;
  });
}

/** Export's sheet: a header, then one line per row as listed. */
export function massCsvRows(
  rows: MassMessageRow[],
  creatorOf: (accountId?: string) => string,
): Array<Array<string | number>> {
  return [
    ["Message", "Sent at (UTC)", "Status", "Price", "Media", "Sent", "Viewed", "Purchased", "Earnings", "Creator"],
    ...rows.map((m) => [
      ofPlainText(m.text || m.rawText || ""),
      m.date ?? "",
      m.isCanceled ? "Unsent" : "Sent",
      m.isFree ? "Free" : "Paid",
      m.mediaCount ?? 0,
      m.sentCount ?? 0,
      m.viewedCount ?? 0,
      m.purchasedCount ?? 0,
      ((m.earningsCents ?? 0) / 100).toFixed(2),
      creatorOf(m.__accountId),
    ]),
  ];
}

/** The bulk confirm's note on what narrows the targets ("" when nothing does): the picked models (`modelNames`,
 *  empty = every Creator) and the applied search / Sending Date. */
export function narrowedBy(f: MassFilters, modelNames: readonly string[] = []): string {
  const of = modelNames.length ? ` of ${modelNames.join(", ")}` : "";
  const by = [f.q.trim() && "search", (f.from || f.to) && "date"].filter(Boolean);
  return of + (by.length ? ` matching your ${by.join("/")}` : "");
}

/** True when a search / Sending Date is applied and a listed Creator's read came back full (`limit` rows, the
 *  newest): its older broadcasts were never loaded, so matches among them are missing from the list, Export and bulk. */
export function mayHideOlder(f: MassFilters, rowsPerCreator: readonly number[], limit: number): boolean {
  const filtered = !!(f.q.trim() || f.from || f.to);
  return filtered && rowsPerCreator.some((n) => n >= limit);
}
