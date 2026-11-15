// Fans picker (Full AI Settings, live only): per OF fan list, Include / Exclude / neither. Empty include = every Fan;
// exclude wins (`full_ai_owner.in_fans`). Save sends the whole `fans` object (the config PUT replaces it whole).

import type { FullAiConfig } from "@/components/automations/fullAiConfig";

export type StoredFans = NonNullable<FullAiConfig["fans"]>;
/** A draft with no `fans`: every Fan. */
export const NO_FANS: StoredFans = { include: [], exclude: [] };
export type FanSide = "include" | "exclude" | "none";
export type FansPick = { include: number[]; exclude: number[] };

export type Action =
  | { type: "set"; id: number; side: FanSide }
  | { type: "reset"; stored: StoredFans };

/** The stored lists; an id on both reads exclude (exclude wins), so Save stores it once. */
export const initFans = (stored: StoredFans): FansPick =>
  ({ include: stored.include.filter((id) => !stored.exclude.includes(id)), exclude: [...stored.exclude] });

export function fansReducer(s: FansPick, a: Action): FansPick {
  switch (a.type) {
    case "set": {
      const include = s.include.filter((id) => id !== a.id);
      const exclude = s.exclude.filter((id) => id !== a.id);
      if (a.side === "include") include.push(a.id);
      if (a.side === "exclude") exclude.push(a.id);
      return { include, exclude };
    }
    case "reset":
      return initFans(a.stored);
  }
}

export const sideOf = (s: FansPick, id: number): FanSide =>
  s.exclude.includes(id) ? "exclude" : s.include.includes(id) ? "include" : "none";

export const buildPayload = (s: FansPick): StoredFans => ({ include: [...s.include], exclude: [...s.exclude] });

/** The row's line: "Every Fan", "2 included", plus " · 1 excluded". */
export function fansSummary(stored: StoredFans): string {
  const inc = stored.include.length, exc = stored.exclude.length;
  return `${inc === 0 ? "Every Fan" : `${inc} included`}${exc > 0 ? ` · ${exc} excluded` : ""}`;
}

/** An OF fan list as `/api/of/v2/lists` returns it (`useFanLists`). */
export interface OfList { id: number | string; name?: string; usersCount?: number }
export interface FanRow { id: number; name: string; count: number | null }

/** The dialog's rows: each OF list with a whole-number id (the only ids `fans` takes), then any picked id OF no longer
 *  lists ("List #id · not found"), so a stale one can be cleared. */
export function fanRows(lists: OfList[], s: FansPick): FanRow[] {
  const rows: FanRow[] = [];
  for (const l of lists) {
    const id = Number(l.id);
    if (!/^\d+$/.test(String(l.id)) || id <= 0) continue;
    rows.push({ id, name: l.name || `List #${id}`, count: l.usersCount ?? 0 });
  }
  const known = new Set(rows.map((r) => r.id));
  for (const id of [...s.include, ...s.exclude]) {
    if (!known.has(id)) {
      known.add(id);
      rows.push({ id, name: `List #${id} · not found`, count: null });
    }
  }
  return rows;
}
