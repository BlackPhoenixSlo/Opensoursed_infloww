// Fans picker (Full AI's "Who Full AI answers when Live", beside the Mode): per OF fan list, Include / Exclude / neither.
// Empty include = every Fan; exclude wins (`full_ai_owner.in_fans`). Save sends the whole `fans` object to the audience
// write (applied at once on every side, never part of the draft / checkpoint split).

import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import type { AudienceResult } from "@/components/automations/fullAiTestChat";

export type StoredFans = NonNullable<FullAiConfig["fans"]>;
/** A draft with no `fans`: every Fan. */
export const NO_FANS: StoredFans = { include: [], exclude: [] };
export type FanSide = "include" | "exclude" | "none";
export type FansPick = { include: number[]; exclude: number[] };

export type Action =
  | { type: "set"; id: number; side: FanSide }
  | { type: "everyone" }
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
    case "everyone":
      return { include: [], exclude: [...s.exclude] };
    case "reset":
      return initFans(a.stored);
  }
}

export const sideOf = (s: FansPick, id: number): FanSide =>
  s.exclude.includes(id) ? "exclude" : s.include.includes(id) ? "include" : "none";

/** The top "Fans & Following" row, read-only state of the pick: on while no list is included (= every Fan), off once
 *  one is. Never stored; picking it (`everyone`) just clears the includes. */
export const everyoneOn = (s: FansPick): boolean => s.include.length === 0;

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

/** An audience control's save (the Fans dialog, the Top spend box): idle (with the last failure's words), a write out
 *  (`saving`), or stored (`saved`, the Top spend box's "Saved" until the next edit). */
export type AudienceSave =
  | { phase: "idle"; error: string | null }
  | { phase: "saving" }
  | { phase: "saved" };

export type AudienceSaveAction =
  | { type: "save" }
  | { type: "result"; result: AudienceResult }
  /** The value was edited again: drops "Saved" and the last failure. */
  | { type: "edit" };

export const AUDIENCE_SAVE_IDLE: AudienceSave = { phase: "idle", error: null };

export function audienceSaveReducer(s: AudienceSave, a: AudienceSaveAction): AudienceSave {
  switch (a.type) {
    case "save":
      return s.phase === "saving" ? s : { phase: "saving" };
    case "result":
      return a.result.kind === "failed" ? { phase: "idle", error: a.result.reason } : { phase: "saved" };
    case "edit":
      return s.phase === "saving" ? s : AUDIENCE_SAVE_IDLE;
  }
}
