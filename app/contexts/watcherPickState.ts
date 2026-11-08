/**
 * watcherPickState — OF Manager's watcher pick (ScopeContext's WatcherScope) as pure functions plus a reducer:
 *
 *   • `resolveWatcherPick(pick, inputs)` → `{active, next}`: the watcher shown (`active`) and the pick to keep (`next`,
 *     the same object when nothing changes). Before the saved scope is read (`hydrated`) the outer scope is a
 *     placeholder: nothing shown, nothing judged stale but a pick the loaded list no longer offers. A pick made before
 *     then (`over` null) takes the outer scope once read. A pick holds while the outer scope is the one it was picked
 *     over and the watcher is `pickable`; it is dropped when the outer scope moved, or once `loaded` without it.
 *   • `pickOf(scope, ...)`: the pick a `setScope` makes (null: not a watcher, the outer scope's).
 *   • `watcherPickReducer`: `pick` (a setScope; `persist` false leaves the saved one alone) and `settle` (the
 *     resolver's `next`). `saved` is what the saved pick (localStorage) must hold; undefined: never touched, so a
 *     mount writes nothing. A drop clears it, as any setScope with `persist`.
 */

/** `over` null: picked before the saved scope was read (a Pop-out's `?account=` on mount); it takes the scope then. */
export interface WatcherPick { id: string; over: string | null }

export interface WatcherInputs {
  /** The saved outer scope has been read. */
  hydrated: boolean;
  /** The outer scope, serialized. */
  outerKey: string;
  /** The watchers OF Manager lists (a captured session, active). */
  pickable: readonly string[];
  /** The accounts list has been read. */
  loaded: boolean;
}

export function resolveWatcherPick(pick: WatcherPick | null, inp: WatcherInputs):
  { active: string | null; next: WatcherPick | null } {
  if (pick == null) return { active: null, next: null };
  const listed = inp.pickable.includes(pick.id);
  if (!inp.hydrated) return { active: null, next: inp.loaded && !listed ? null : pick };
  const bound = pick.over === null ? { id: pick.id, over: inp.outerKey } : pick;
  if (bound.over !== inp.outerKey) return { active: null, next: null };
  if (listed) return { active: bound.id, next: bound };
  return { active: null, next: inp.loaded ? null : bound };
}

/** The watcher pick a `setScope(s)` makes, or null for any other scope (it goes to the outer setScope). */
export function pickOf(s: { kind: "all" } | { kind: "model"; accountId: string }, watcherIds: readonly string[],
                       hydrated: boolean, outerKey: string): WatcherPick | null {
  return s.kind === "model" && watcherIds.includes(s.accountId)
    ? { id: s.accountId, over: hydrated ? outerKey : null } : null;
}

export interface WatcherPickState {
  pick: WatcherPick | null;
  /** What the saved pick must hold (null: removed); undefined: never touched. */
  saved: WatcherPick | null | undefined;
}

export type WatcherPickAction =
  | { type: "pick"; pick: WatcherPick | null; persist: boolean }
  | { type: "settle"; next: WatcherPick | null };

export function watcherPickReducer(s: WatcherPickState, a: WatcherPickAction): WatcherPickState {
  switch (a.type) {
    case "pick":
      return { pick: a.pick, saved: a.persist ? a.pick : s.saved };
    case "settle":
      if (a.next === s.pick) return s;
      // A drop clears the saved pick too; a bind (`over` filled in) leaves it as it is.
      return a.next === null ? { pick: null, saved: null } : { ...s, pick: a.next };
  }
}
