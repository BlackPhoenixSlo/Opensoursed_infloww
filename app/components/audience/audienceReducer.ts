import { DEFAULT_BROADCAST_LISTS, type FanList } from "@/components/audience/fanLists";

// Standing "never mass send" list: per-account, exact name, matched trimmed and case-insensitively.
export const MASS_EXCLUDE_LIST_NAME = "MASSDMEXCLUDE";

export interface AudienceState {
  accountId: string | null;
  includes: Set<string>;
  excludes: Set<string>;
  seededFor: string | null;
}

export type AudienceAction =
  | { type: "toggleInclude"; id: string }
  | { type: "toggleExclude"; id: string }
  | { type: "setAccount"; id: string | null }
  | { type: "seedExclude"; accountId: string; listId: string | null };

export function initAudience(
  accountId: string | null,
  includes: readonly string[] = DEFAULT_BROADCAST_LISTS,
): AudienceState {
  return { accountId, includes: new Set(includes), excludes: new Set(), seededFor: null };
}

export function toggled<T>(set: ReadonlySet<T>, id: T): Set<T> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

export function without<T>(set: Set<T>, id: T): Set<T> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}

export function isAccountSwitch(prev: string | null, next: string | null): boolean {
  return prev !== null && next !== prev;
}

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

export function massExcludeListId(lists: readonly FanList[]): string | null {
  const match = lists.find((l) => String(l.name ?? "").trim().toUpperCase() === MASS_EXCLUDE_LIST_NAME);
  return match ? String(match.id) : null;
}

export function audienceError(s: Pick<AudienceState, "includes">): string | null {
  return s.includes.size === 0 ? "Pick at least one audience to include." : null;
}

export function buildAudiencePayload(s: Pick<AudienceState, "includes" | "excludes">): {
  user_lists: string[];
  excluded_user_lists: string[];
} {
  return { user_lists: [...s.includes], excluded_user_lists: [...s.excludes] };
}
