/**
 * audienceReducer — the include / exclude list picker's one state, reducer and
 * pure rules. The canonical home of the audience rules: PriorityMass and
 * FunnelLaunchPanel use it as is; compose/massMessageReducer embeds
 * AudienceState and delegates these actions here.
 *
 *   • Include / exclude stay mutually exclusive: toggling a list into one side
 *     takes it out of the other.
 *   • Custom list ids are per account, so a real account change (A → B) resets
 *     the audience to the system default (fans + following, no excludes) and
 *     forgets the standing-exclude seed. The first pick (null → A) keeps what
 *     was clicked; the same account again is a no-op.
 *   • `seedExclude` auto-excludes the standing MASSDMEXCLUDE list
 *     (`massExcludeListId`) once per account (since the last reset); a manual
 *     untick sticks.
 *   • `audienceError` is the one "can this audience send" check;
 *     `buildAudiencePayload` the `user_lists` / `excluded_user_lists` pair of the
 *     request body, in Set insertion order.
 *
 * Generic over the state, so a bigger form that extends AudienceState can
 * delegate these actions here (compose/massMessageReducer does, keeping its
 * allModels guards and its own reset of the rest of its form outside).
 */

import { DEFAULT_BROADCAST_LISTS, type FanList } from "@/components/audience/fanLists";

/** The standing "never mass send" exclude list, kept per account with this
 *  exact name (MASSppvEXCLUDE merged into it 2026-10-21). Matched trimmed and
 *  case-insensitively. */
export const MASS_EXCLUDE_LIST_NAME = "MASSDMEXCLUDE";

export interface AudienceState {
  /** The account whose lists the ids below belong to. */
  accountId: string | null;
  /** Never mutated — every change is a new Set. */
  includes: Set<string>;
  excludes: Set<string>;
  /** The account the standing exclude list was seeded for; null = not yet. */
  seededFor: string | null;
}

export type AudienceAction =
  | { type: "toggleInclude"; id: string }
  | { type: "toggleExclude"; id: string }
  | { type: "setAccount"; id: string | null }
  /** The account's lists settled: auto-exclude `listId` (null = the account
   *  has none) once for `accountId`. */
  | { type: "seedExclude"; accountId: string; listId: string | null };

export function initAudience(
  accountId: string | null,
  includes: readonly string[] = DEFAULT_BROADCAST_LISTS,
): AudienceState {
  return { accountId, includes: new Set(includes), excludes: new Set(), seededFor: null };
}

/** `set` with `id` flipped (a new Set). */
export function toggled<T>(set: ReadonlySet<T>, id: T): Set<T> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

/** `set` without `id` — the same reference when it wasn't there. */
export function without<T>(set: Set<T>, id: T): Set<T> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}

/** A real account change (A → B): not the first pick (null → A), not the same one. */
export function isAccountSwitch(prev: string | null, next: string | null): boolean {
  return prev !== null && next !== prev;
}

/** The system-default audience (fans + following, no excludes), the seed forgotten. */
export function resetAudience<S extends AudienceState>(s: S): S {
  return { ...s, includes: new Set(DEFAULT_BROADCAST_LISTS), excludes: new Set(), seededFor: null };
}

export function audienceReducer<S extends AudienceState>(s: S, a: AudienceAction): S {
  switch (a.type) {
    case "toggleInclude":
      return { ...s, includes: toggled(s.includes, a.id), excludes: without(s.excludes, a.id) };
    case "toggleExclude":
      return { ...s, excludes: toggled(s.excludes, a.id), includes: without(s.includes, a.id) };
    case "setAccount":
      if (a.id === s.accountId) return s;
      return isAccountSwitch(s.accountId, a.id) ? { ...resetAudience(s), accountId: a.id } : { ...s, accountId: a.id };
    case "seedExclude":
      if (s.accountId !== a.accountId || s.seededFor === a.accountId) return s;
      return {
        ...s,
        seededFor: a.accountId,
        // Additive, and never a list the operator has included.
        excludes: a.listId && !s.includes.has(a.listId) ? new Set(s.excludes).add(a.listId) : s.excludes,
      };
  }
}

/** The account's standing exclude list id, or null when it has none. */
export function massExcludeListId(lists: readonly FanList[]): string | null {
  const match = lists.find((l) => String(l.name ?? "").trim().toUpperCase() === MASS_EXCLUDE_LIST_NAME);
  return match ? String(match.id) : null;
}

/** Why this audience can't send, or null when it can. */
export function audienceError(s: Pick<AudienceState, "includes">): string | null {
  return s.includes.size === 0 ? "Pick at least one audience to include." : null;
}

/** The audience half of the request body. */
export function buildAudiencePayload(s: Pick<AudienceState, "includes" | "excludes">): {
  user_lists: string[];
  excluded_user_lists: string[];
} {
  return { user_lists: [...s.includes], excluded_user_lists: [...s.excludes] };
}
