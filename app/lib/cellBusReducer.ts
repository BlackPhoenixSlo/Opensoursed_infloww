import type { QueryKey } from "@tanstack/react-query";

import type { CellMap } from "@/lib/cellInbox";
import type { Scope } from "@/lib/eventBusReducer";

export type Proto = "ok" | "h1" | "unknown";

// "" is a cached/bfcache entry, not a protocol: unknown opens streams rather than banner a working h2 page.
export function protoOf(nextHop: string | null | undefined): Proto {
  if (!nextHop) return "unknown";
  return /^h[23]/.test(nextHop) ? "ok" : "h1";
}

export interface Planned { cell: string; scope: Scope; accounts: readonly string[] }

export function planStreams(m: CellMap, scope: Scope): Planned[] {
  const out: Planned[] = m.control ? [{ cell: m.control, scope: "all", accounts: [] }] : [];
  const one = scope.startsWith("model:") ? scope.slice("model:".length) : null;
  for (const cell of [...m.cells].sort()) {
    if (cell === m.control) continue;
    const accounts = m.accounts.filter((a) => a.cell === cell).map((a) => a.account_id);
    if (one === null) out.push({ cell, scope: "all", accounts });
    else if (accounts.includes(one)) out.push({ cell, scope, accounts: [one] });
  }
  return out;
}

export interface CellBusState { proto: Proto | null; planned: readonly Planned[]; live: Readonly<Record<string, boolean>> }
export const INITIAL_CELL_BUS: CellBusState = { proto: null, planned: [], live: {} };

export type CellBusAction =
  | { type: "Plan"; map: CellMap; scope: Scope; proto: Proto }
  | { type: "Live"; cell: string; live: boolean };

export function cellBusReducer(s: CellBusState, a: CellBusAction): CellBusState {
  if (a.type === "Live") {
    if (!s.planned.some((p) => p.cell === a.cell) || s.live[a.cell] === a.live) return s;
    return { ...s, live: { ...s.live, [a.cell]: a.live } };
  }
  const planned = a.proto === "h1" ? [] : planStreams(a.map, a.scope);
  const live: Record<string, boolean> = {};
  for (const p of planned) if (p.cell in s.live) live[p.cell] = s.live[p.cell];
  return { proto: a.proto, planned, live };
}

export interface StreamDiff { open: Planned[]; close: string[]; rescope: Planned[] }

export function streamDiff(prev: readonly Planned[], next: readonly Planned[]): StreamDiff {
  const was = new Map(prev.map((p) => [p.cell, p]));
  const now = new Set(next.map((p) => p.cell));
  return {
    open: next.filter((p) => !was.has(p.cell)),
    close: prev.filter((p) => !now.has(p.cell)).map((p) => p.cell),
    rescope: next.filter((p) => was.has(p.cell) && was.get(p.cell)!.scope !== p.scope),
  };
}

export function blocked(s: CellBusState): boolean {
  return s.proto === "h1";
}

export function allLive(s: CellBusState): boolean {
  return s.planned.length > 0 && s.planned.every((p) => s.live[p.cell] === true);
}

export function accountLive(s: CellBusState, accountId: string): boolean {
  const p = s.planned.find((x) => x.accounts.includes(accountId));
  return !!p && s.live[p.cell] === true;
}

export function downAccounts(s: CellBusState): ReadonlySet<string> {
  const out = new Set<string>();
  for (const p of s.planned) if (s.live[p.cell] === false) for (const id of p.accounts) out.add(id);
  return out;
}

export interface LiveChange { cell: string; live: boolean; accounts: readonly string[] }

export function liveChanges(prev: CellBusState, next: CellBusState): LiveChange[] {
  const out: LiveChange[] = [];
  for (const p of next.planned) {
    const now = next.live[p.cell];
    if (now !== undefined && now !== prev.live[p.cell]) out.push({ cell: p.cell, live: now, accounts: p.accounts });
  }
  return out;
}

export type ResyncAction = "skip" | "invalidate" | "splice";

function keyAccounts(key: QueryKey): string[] {
  const out: string[] = [];
  const add = (v: unknown) => {
    if (typeof v === "number") out.push(String(v));
    else if (typeof v === "string") out.push(...v.split(","));
  };
  for (const part of key) {
    if (part && typeof part === "object" && !Array.isArray(part)) Object.values(part).forEach(add);
    else add(part);
  }
  return out;
}

// accounts empty = control's resync: refetch what names no placed Creator (agency reads), leave every Cell's alone.
export function resyncAction(
  key: QueryKey, accounts: ReadonlySet<string>, placed: ReadonlySet<string>,
): ResyncAction {
  const named = keyAccounts(key).filter((id) => placed.has(id));
  if (!accounts.size) return named.length ? "skip" : "invalidate";
  const hit = named.filter((id) => accounts.has(id));
  if (!hit.length) return "skip";
  return key[0] === "chats" && hit.length < named.length ? "splice" : "invalidate";
}
