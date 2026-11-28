import { isUnknownDetail } from "@/lib/relay";
import type { OFChatItem } from "@/lib/relayTypes";
import { compareFanIds } from "@/lib/fanId";

export const CELL_PAINT_MS = 2_750;
export const CELL_DEADLINE_MS = 2_250;
export const ROSTER_WAIT_MS = 1_000;

export interface PlacedAccount { platform: string; account_id: string; cell: string }
export interface CellMap {
  actor: string;
  grant_gen: number;
  placement_gen: number | null;
  accounts: PlacedAccount[];
  cells: string[];
  control?: string | null;
}

export function cellToken(m: CellMap): string {
  return `@${m.actor}:${m.grant_gen}:${m.placement_gen ?? ""}`;
}

export function tokenOf(accountKey: string): string {
  return accountKey.split(",").find((p) => p.startsWith("@")) ?? "";
}

export function groupByCell(accounts: readonly string[], m: CellMap): [string, string[]][] {
  const cellOf = new Map(m.accounts.map((a) => [a.account_id, a.cell]));
  const out = new Map<string, string[]>();
  for (const id of accounts) {
    const cell = cellOf.get(id);
    if (cell) out.set(cell, [...(out.get(cell) ?? []), id]);
  }
  return [...out].sort(([a], [b]) => a.localeCompare(b));
}

export type Outcome = "none" | "ok" | "slow" | "down";
export interface CellFetch { accounts: readonly string[]; asking: boolean; outcome: Outcome; partial: readonly string[] }
export interface CellsState { scope: string; cells: Readonly<Record<string, CellFetch>> }
export const INITIAL_CELLS: CellsState = { scope: "", cells: {} };

export type Action =
  | { type: "ask"; scope: string; cell: string; accounts: readonly string[] }
  | { type: "answered"; scope: string; cell: string; partial: readonly string[] }
  | { type: "timedOut"; scope: string; cell: string }
  | { type: "failed"; scope: string; cell: string };

function settle(s: CellsState, cell: string, outcome: Outcome, partial: readonly string[]): CellsState {
  const was = s.cells[cell];
  if (!was) return s;
  return { ...s, cells: { ...s.cells, [cell]: { ...was, asking: false, outcome, partial } } };
}

export function cellsReducer(s: CellsState, a: Action): CellsState {
  if (a.type === "ask") {
    const base = a.scope === s.scope ? s.cells : {};
    const was = base[a.cell];
    return { scope: a.scope, cells: { ...base, [a.cell]: {
      accounts: a.accounts, asking: true, outcome: was?.outcome ?? "none", partial: was?.partial ?? [],
    } } };
  }
  if (a.scope !== s.scope) return s;
  if (a.type === "answered") return settle(s, a.cell, "ok", a.partial);
  return settle(s, a.cell, a.type === "timedOut" ? "slow" : "down", s.cells[a.cell]?.partial ?? []);
}

export function greyAccounts(s: CellsState): ReadonlySet<string> {
  const out = new Set<string>();
  for (const c of Object.values(s.cells)) {
    for (const id of c.outcome === "slow" || c.outcome === "down" ? c.accounts : c.partial) out.add(id);
  }
  return out;
}

export function partialIds(partial: unknown): string[] {
  return Array.isArray(partial) ? partial.filter((p): p is string => typeof p === "string").map((p) => p.split(":").pop()!) : [];
}

export function compareCellChats(a: OFChatItem, b: OFChatItem): number {
  const ta = a.lastMessage?.createdAt ?? "";
  const tb = b.lastMessage?.createdAt ?? "";
  if (!ta !== !tb) return ta ? 1 : -1;
  if (ta !== tb) return tb.localeCompare(ta);
  return compareFanIds(a.__accountId, b.__accountId) || compareFanIds(a.withUser?.id, b.withUser?.id);
}

export function cellSort(order: "old" | "recent") {
  return order === "old" ? (a: OFChatItem, b: OFChatItem) => compareCellChats(b, a) : compareCellChats;
}

export function mergeCellRows(lists: readonly (readonly OFChatItem[])[], sort = compareCellChats): OFChatItem[] {
  const seen = new Map<string, OFChatItem>();
  for (const list of lists) for (const c of list) {
    const k = `${c.__accountId ?? ""}:${c.withUser?.id}`;
    if (!seen.has(k)) seen.set(k, c);
  }
  return [...seen.values()].sort(sort);
}

export interface BundleChats { accountId: string; body: unknown }

export function bundleChats(body: unknown): { chats: BundleChats[]; failed: string[]; partial: string[]; gone: string[]; unsupported: string[] } {
  const b = (body ?? {}) as { answers?: unknown; partial?: unknown };
  const chats: BundleChats[] = [];
  const failed: string[] = [];
  const gone: string[] = [];
  const unsupported: string[] = [];
  for (const a of Array.isArray(b.answers) ? b.answers : []) {
    const ans = a as { accountId?: unknown; read?: unknown; body?: unknown; status?: unknown; detail?: unknown };
    if (typeof ans.accountId !== "string" || (ans.read !== "chats" && ans.read !== "*")) continue;
    if (ans.status != null || ans.read === "*") failed.push(ans.accountId);
    else chats.push({ accountId: ans.accountId, body: ans.body });
    if (ans.status === 404 && isUnknownDetail(ans.detail)) gone.push(ans.accountId);
    else if (ans.status === 404 && ans.read === "*") unsupported.push(ans.accountId);
  }
  return { chats, failed, partial: partialIds(b.partial), gone, unsupported };
}

export interface HeadPage {
  cellCursors?: Record<string, number>;
  rows: OFChatItem[]; hasMore: boolean; moreAccounts: string[]; scanned: number; partial?: boolean; missing?: string[];
}

export function nextCellCursors(page: HeadPage, cursor: number, limit: number, cursors?: Record<string, number>): Record<string, number> {
  const missing = new Set(page.missing);
  return Object.fromEntries(page.moreAccounts.map((id) => [id, (cursors?.[id] ?? cursor) + (missing.has(id) ? 0 : limit)]));
}

function splicePage<P extends HeadPage>(
  page0: P, head: HeadPage, ids: ReadonlySet<string>, sort: typeof compareCellChats, keepRows: boolean,
): P {
  const others = (list: readonly string[] | undefined) => (list ?? []).filter((id) => !ids.has(id));
  const moreAccounts = [...new Set([...others(page0.moreAccounts), ...head.moreAccounts,
    ...page0.moreAccounts.filter((id) => head.missing?.includes(id))])];
  const missing = [...others(page0.missing), ...(head.missing ?? [])];
  const failed = new Set(head.missing);
  const { partial: _p, missing: _m, ...rest } = page0;
  const cursors = page0.cellCursors || head.cellCursors ? {
    ...Object.fromEntries(Object.entries(page0.cellCursors ?? {}).filter(([id]) => !ids.has(id) || failed.has(id))),
    ...Object.fromEntries(Object.entries(head.cellCursors ?? {}).filter(([id]) => !failed.has(id) || page0.cellCursors?.[id] === undefined)),
  } : undefined;
  return {
    ...rest,
    ...(cursors ? { cellCursors: cursors } : {}),
    rows: mergeCellRows([head.rows, page0.rows.filter((r) => {
      const id = r.__accountId ?? "";
      return keepRows || !ids.has(id) || failed.has(id);
    })], sort),
    hasMore: moreAccounts.length > 0, moreAccounts,
    ...(missing.length ? { partial: true, missing } : {}),
  } as P;
}

export function spliceHead<P extends HeadPage>(
  page: P, head: HeadPage, ids: ReadonlySet<string>, sort = compareCellChats,
): P {
  return splicePage(page, head, ids, sort, false);
}

export function retryTail<P extends HeadPage>(
  page: P, retry: HeadPage, ids: ReadonlySet<string>, sort = compareCellChats,
): P {
  return splicePage(page, retry, ids, sort, true);
}
