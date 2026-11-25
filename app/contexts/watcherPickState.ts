export interface WatcherPick { id: string; over: string | null }

export interface WatcherInputs {
  hydrated: boolean;
  outerKey: string;
  pickable: readonly string[];
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

export function pickOf(s: { kind: "all" } | { kind: "model"; accountId: string }, watcherIds: readonly string[],
                       hydrated: boolean, outerKey: string): WatcherPick | null {
  return s.kind === "model" && watcherIds.includes(s.accountId)
    ? { id: s.accountId, over: hydrated ? outerKey : null } : null;
}

export interface WatcherPickState {
  pick: WatcherPick | null;
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
      return a.next === null ? { pick: null, saved: null } : { ...s, pick: a.next };
  }
}
