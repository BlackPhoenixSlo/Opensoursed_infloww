import { dayOf } from "@/components/growth/automatedRows";
import type { CreatorMassPage, MassMessageRow } from "@/hooks/useMassMessages";
import { ofPlainText } from "@/lib/ofRichText";

export interface MassFilters {
  q: string;
  from: string;
  to: string;
}

export const NO_MASS_FILTERS: MassFilters = { q: "", from: "", to: "" };

export const RANGE_DAYS = [7, 30, 90, 365] as const;

export interface MassFilterState {
  draft: MassFilters;
  applied: MassFilters;
  daysBack: number;
  pickedDays: number;
  models: ReadonlySet<string>;
  hideUnsent: boolean;
}

export type MassFilterAction =
  | { type: "draft"; patch: Partial<MassFilters> }
  | { type: "apply"; now: number }
  | { type: "reset" }
  | { type: "daysBack"; days: number }
  | { type: "hideUnsent"; on: boolean }
  | { type: "toggleModel"; id: string }
  | { type: "allModels" }
  | { type: "liveModels"; ids: readonly string[] };

export const initialMassFilter: MassFilterState = {
  draft: NO_MASS_FILTERS, applied: NO_MASS_FILTERS, daysBack: 30, pickedDays: 30, models: new Set(), hideUnsent: true,
};

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

export function narrowedBy(f: MassFilters, modelNames: readonly string[] = []): string {
  const of = modelNames.length ? ` of ${modelNames.join(", ")}` : "";
  const by = [f.q.trim() && "search", (f.from || f.to) && "date"].filter(Boolean);
  return of + (by.length ? ` matching your ${by.join("/")}` : "");
}

export function mayHideOlder(f: MassFilters, rowsPerCreator: readonly number[], limit: number): boolean {
  const filtered = !!(f.q.trim() || f.from || f.to);
  return filtered && rowsPerCreator.some((n) => n >= limit);
}

export function moreNotLoaded(
  perCreator: readonly Pick<CreatorMassPage, "accountId" | "hasMore" | "incomplete">[],
): string[] {
  return perCreator.filter((c) => c.hasMore || c.incomplete).map((c) => c.accountId);
}
