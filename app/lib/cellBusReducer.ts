import type { QueryKey } from "@tanstack/react-query";

import type { CellMap } from "@/lib/cellInbox";
import { RETRY_MAX_MS, RETRY_MIN_MS, type Scope } from "@/lib/eventBusReducer";

export type Proto = "ok" | "h1" | "unknown";

// "" is a cached/bfcache entry, not a protocol: unknown opens streams rather than banner a working h2 page.
export function protoOf(nextHop: string | null | undefined): Proto {
  if (!nextHop) return "unknown";
  return /^h[23]/.test(nextHop) ? "ok" : "h1";
}

export interface Planned { cell: string; scope: Scope; accounts: readonly string[] }

export function planStreams(m: CellMap, scope: Scope): Planned[] {
  const out: Planned[] = m.control ? [{ cell: m.control, scope: "all", accounts: m.accounts.filter((a) => a.cell === m.control).map((a) => a.account_id) }] : [];
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
  for (const p of prev.planned) {
    const kept = next.planned.find((n) => n.cell === p.cell);
    const removed = p.accounts.filter((id) => !kept?.accounts.includes(id));
    if (prev.live[p.cell] && (removed.length || !kept)) out.push({ cell: p.cell, live: false, accounts: removed });
  }
  for (const p of next.planned) {
    const now = next.live[p.cell];
    if (now === undefined) continue;
    const prior = prev.planned.find((x) => x.cell === p.cell);
    if (now !== prev.live[p.cell]) out.push({ cell: p.cell, live: now, accounts: p.accounts });
    else if (now) {
      const added = p.accounts.filter((id) => !prior?.accounts.includes(id));
      if (added.length) out.push({ cell: p.cell, live: true, accounts: added });
    }
  }
  return out;
}

export type ResyncAction = "skip" | "invalidate" | "splice" | "retryTail";

const ACCOUNT_ROOTS = new Set<unknown>([
  "chat-messages", "messages", "mass-messages", "vault", "scheduled-sends", "automation-rules",
  "full-ai-today", "of-notif-count", "notif-list", "automation-restrict",
]);

function keyAccounts(key: QueryKey): string[] | null {
  if (key[0] === "chats") return typeof key[2] === "string" ? key[2].split(",") : [];
  let candidate = key[1];
  if (key[0] === "accounts" || key[0] === "roster-counts") return [];
  if (key[0] === "chats-local-seed") candidate = key[2];
  if (key[0] === "chatter") candidate = key[1] === "folder-access" ? key[2] : undefined;
  if (key[0] === "stats") {
    if (key[1] === "per-fan-data") candidate = key[2];
    else if (key[1] === "coverage" || key[1] === "fan-report" || key[1] === "referrals") candidate = key[4];
    else if (key[1] === "sales-records" && typeof key[2] === "string") {
      candidate = new URLSearchParams(key[2]).get("account_id");
    } else if (key[1] === "automation-runs") candidate = undefined;
    else return null;
  } else if (key[0] !== "chats-local-seed" && key[0] !== "chatter" && !ACCOUNT_ROOTS.has(key[0])) return null;
  const account = candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? (candidate as { accountId?: unknown }).accountId : candidate;
  return typeof account === "string" || typeof account === "number" ? [String(account)] : [];
}

// accounts empty = control's resync: refetch what names no placed Creator (agency reads), leave every Cell's alone.
export function resyncAction(
  key: QueryKey, accounts: ReadonlySet<string>, placed: ReadonlySet<string>, retryTail = false,
): ResyncAction {
  const ids = keyAccounts(key);
  if (ids === null) return "invalidate";
  const named = ids.filter((id) => placed.has(id));
  if (!accounts.size) return named.length ? "skip" : "invalidate";
  const hit = named.filter((id) => accounts.has(id));
  if (!hit.length) return "skip";
  if (key[0] === "chats" && retryTail) return "retryTail";
  return key[0] === "chats" && hit.length < named.length ? "splice" : "invalidate";
}

export type MapLoad = { phase: "ready" | "loading" | "waiting"; delay: number } | { phase: "denied" };
export const INITIAL_MAP_LOAD: MapLoad = { phase: "ready", delay: RETRY_MIN_MS };

type MapLoadAction = "reset" | "start" | "failed" | "denied" | "retry";

export function mapLoadReducer(state: MapLoad, action: MapLoadAction): MapLoad {
  if (action === "reset") return INITIAL_MAP_LOAD;
  if (state.phase === "ready" && action === "start") return { ...state, phase: "loading" };
  if (state.phase === "loading" && action === "denied") return { phase: "denied" };
  if (state.phase === "loading" && action === "failed") return { ...state, phase: "waiting" };
  if (state.phase === "waiting" && action === "retry") {
    return { phase: "ready", delay: Math.min(state.delay * 2, RETRY_MAX_MS) };
  }
  return state;
}
