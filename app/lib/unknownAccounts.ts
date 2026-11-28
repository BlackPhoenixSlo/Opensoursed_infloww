import { useSyncExternalStore } from "react";

export interface Seen { principal: string | null; roster: number | null }

export interface UnknownState extends Seen { ids: ReadonlySet<string>; directIds: ReadonlySet<string> }

export type Action =
  | { type: "roster"; principal: string; roster: number }
  | { type: "unknown" | "direct"; id: string; seen: Seen };

const NONE: ReadonlySet<string> = new Set();

export const initialUnknown: UnknownState = { principal: null, roster: null, ids: NONE, directIds: NONE };

// A 404 asked under an older principal or roster says nothing about the current one: the Creator may have reconnected since.
export function unknownReducer(s: UnknownState, a: Action): UnknownState {
  switch (a.type) {
    case "roster":
      if (s.principal === a.principal && s.roster === a.roster) return s;
      return { principal: a.principal, roster: a.roster, ids: NONE, directIds: NONE };
    case "unknown":
    case "direct": {
      const key = a.type === "unknown" ? "ids" : "directIds";
      if (a.seen.principal !== s.principal || a.seen.roster !== s.roster || s[key].has(a.id)) return s;
      return { ...s, [key]: new Set([...s[key], a.id]) };
    }
  }
}

let state = initialUnknown;
const listeners = new Set<() => void>();

function dispatch(a: Action): void {
  const next = unknownReducer(state, a);
  if (next === state) return;
  state = next;
  for (const l of listeners) l();
}

export function noteRoster(principal: string, roster: number): void {
  dispatch({ type: "roster", principal, roster });
}

export function seenNow(): Seen {
  return { principal: state.principal, roster: state.roster };
}

export function markUnknown(id: string, seen: Seen): void {
  dispatch({ type: "unknown", id, seen });
}

export function markDirect(id: string, seen: Seen): void {
  dispatch({ type: "direct", id, seen });
}

export function directIds(): ReadonlySet<string> {
  return state.directIds;
}

export function unknownIds(): ReadonlySet<string> {
  return state.ids;
}

export function resetUnknownAccounts(): void {
  state = initialUnknown;
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

export function useUnknownAccounts(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, unknownIds, () => NONE);
}
