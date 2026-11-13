/** Creator statistics' column layout: the shown columns' keys, in display order. The owner's pick is the Agency's
 *  (Applied settings `reports.creator_cols`); a never-saved Agency shows the capture's defaults in its order. */

import { type StatCol, STAT_COLS } from "./reportsMath";

const INDEX = new Map(STAT_COLS.map((c, i) => [c.key, i]));
const BY_KEY = new Map(STAT_COLS.map((c) => [c.key, c]));

export const DEFAULT_KEYS: readonly string[] = STAT_COLS.filter((c) => c.show).map((c) => c.key);

/** The stored pick, less keys this build has no column for (renamed or dropped) and repeats; none stored: defaults. */
export function shownKeys(stored: readonly string[] | null | undefined): string[] {
  if (!Array.isArray(stored)) return [...DEFAULT_KEYS];
  return [...new Set(stored)].filter((k) => INDEX.has(k));
}

/** Show or hide `key`. A column shown again goes before the first shown one that follows it in the capture's order,
 *  so an untouched layout stays in the capture's order. */
export function toggleCol(keys: readonly string[], key: string): string[] {
  if (keys.includes(key)) return keys.filter((k) => k !== key);
  const at = INDEX.get(key);
  if (at === undefined) return [...keys];
  const before = keys.findIndex((k) => (INDEX.get(k) ?? -1) > at);
  return before < 0 ? [...keys, key] : [...keys.slice(0, before), key, ...keys.slice(before)];
}

/** Move a shown column one place up (-1) or down (1); at either end, or hidden, nothing changes. */
export function moveCol(keys: readonly string[], key: string, dir: -1 | 1): string[] {
  const i = keys.indexOf(key);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= keys.length) return [...keys];
  const next = [...keys];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

export function colsOf(keys: readonly string[]): StatCol[] {
  return keys.flatMap((k) => BY_KEY.get(k) ?? []);
}

/** The hidden columns, in the capture's order. */
export function hiddenCols(keys: readonly string[]): StatCol[] {
  const shown = new Set(keys);
  return STAT_COLS.filter((c) => !shown.has(c.key));
}
