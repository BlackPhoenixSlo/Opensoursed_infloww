import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import type { AudienceResult } from "@/components/automations/fullAiTestChat";

export type StoredFans = NonNullable<FullAiConfig["fans"]>;
export const NO_FANS: StoredFans = { include: [], exclude: [] };
export type FanSide = "include" | "exclude" | "none";
export type FansPick = { include: number[]; exclude: number[] };

export type Action =
  | { type: "set"; id: number; side: FanSide }
  | { type: "everyone" }
  | { type: "reset"; stored: StoredFans };

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

export const everyoneOn = (s: FansPick): boolean => s.include.length === 0;

export const buildPayload = (s: FansPick): StoredFans => ({ include: [...s.include], exclude: [...s.exclude] });

export function fansSummary(stored: StoredFans): string {
  const inc = stored.include.length, exc = stored.exclude.length;
  return `${inc === 0 ? "Every Fan" : `${inc} included`}${exc > 0 ? ` · ${exc} excluded` : ""}`;
}

export interface OfList { id: number | string; name?: string; usersCount?: number }
export interface FanRow { id: number; name: string; count: number | null }

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

export type AudienceSave =
  | { phase: "idle"; error: string | null }
  | { phase: "saving" }
  | { phase: "saved" };

export type AudienceSaveAction =
  | { type: "save" }
  | { type: "result"; result: AudienceResult }
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
