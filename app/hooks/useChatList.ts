"use client";


import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import {
  focusManager,
  hashKey,
  keepPreviousData,
  replaceEqualDeep,
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";

import { useScope, type Scope } from "@/contexts/ScopeContext";
import { eventBus } from "@/lib/events";
import { cellMode } from "@/lib/cellFlag";
import { isDeepRefused, isRateLimited, isUnknownAccount, relay, relayFocus, type OFChatItem, type OFChatsResp, type OFUserMini, type AccountMeta } from "@/lib/relay";
import { askCells, cellBundle, cellScopeToken, currentCellMap, useCellMap } from "@/lib/cellMap";
import { bundleChats, cellSort, mergeCellRows, nextCellCursors, retryTail, spliceHead, tokenOf, type CellMap } from "@/lib/cellInbox";
import { resyncAction } from "@/lib/cellBusReducer";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { CHATS_PAGE } from "@/lib/screenBundle";
import {
  chatRowKey, commitChatPages, compareChats, completeUnreadView, decodeChatsKey, isLiveView, localSeq, replayCachedPage,
  type StampedPage, type UnreadView,
} from "@/lib/chatsCache";
import { relayNow, relayOffsetKnown } from "@/lib/ageClock";
import { platformHonours, type ChatListFilter } from "@/lib/chatFilters";
import { accountPlatform, type AccountPlatform } from "@/lib/platform";
import { perfDelivered, perfError, perfLog, perfOpId, perfPaintPending } from "@/lib/perfLog";
import { directIds, markDirect, markUnknown, seenNow, unknownIds, useUnknownAccounts, type Seen } from "@/lib/unknownAccounts";
import { useAccounts, usePlatformAccounts } from "./useAccounts";
import { useAccountPlatform } from "./useCan";
import { avatarThumb, mergeOFUserName, ofUserNameKey, type OFUserName } from "./useOFUser";
import {
  initialLoadMore, listCaller, loadMoreReducer, mayAutoPage, pendingFor, startedBy, type Busy, type ListCaller, type LoadMoreAction, type Pending,
} from "./chatListLoadMore";

const PAGE_SIZE = CHATS_PAGE;

export function shareChatPages(prev: unknown, next: unknown): unknown {
  const p = prev as InfiniteData<StampedPage> | undefined;
  const n = next as InfiniteData<StampedPage> | undefined;
  if (!p?.pages || !n?.pages) return replaceEqualDeep(prev, next);
  if (p === n) return p;
  const old = new Map<string, OFChatItem>();
  for (const pg of p.pages) for (const c of pg.rows) old.set(chatRowKey(c), c);
  let allSame = p.pages.length === n.pages.length;
  const pages = n.pages.map((pg, i) => {
    const was = p.pages[i];
    if (pg === was) return was;
    let same = !!was && was.hasMore === pg.hasMore && was.session === pg.session && was.scanned === pg.scanned &&
      !was.partial === !pg.partial &&
      replaceEqualDeep(was.splitVersions, pg.splitVersions) === was.splitVersions &&
      replaceEqualDeep(was.missing, pg.missing) === was.missing &&
      replaceEqualDeep(was.cellCursors, pg.cellCursors) === was.cellCursors &&
      replaceEqualDeep(was.moreAccounts, pg.moreAccounts) === was.moreAccounts &&
      was.rows.length === pg.rows.length;
    const rows = pg.rows.map((c, j) => {
      const prevRow = old.get(chatRowKey(c));
      const row = prevRow ? replaceEqualDeep(prevRow, c) : c;
      if (same && was.rows[j] !== row) same = false;
      return row;
    });
    if (same) return was;
    allSame = false;
    return { ...pg, rows };
  });
  const pageParams = replaceEqualDeep(p.pageParams, n.pageParams);
  if (allSame && pageParams === p.pageParams) return p;
  return { ...n, pages, pageParams };
}
const POLL_MS = 90_000;
const HIDDEN_POLL_MS = 5 * 60_000;
export const IDLE_POLL_MS = 30_000;
const RETURN_GAP_MS = 5_000;

export function headPollDelay(s: { paused: boolean; hidden: boolean; connected: boolean; idlePoll: boolean }): number | null {
  if (s.paused) return s.idlePoll ? IDLE_POLL_MS : null;
  return s.hidden || s.connected ? HIDDEN_POLL_MS : POLL_MS;
}

export type { ChatListFilter } from "@/lib/chatFilters";
export type ChatListOrder = "recent" | "old";

interface ChatListParams {
  filter?: ChatListFilter | null;
  listId?: string | null;
  query?: string | null;
  limit?: number;
  order?: ChatListOrder;
  enabled?: boolean;
}

interface UserListResp { [id: string]: OFUserMini & {
  avatarThumbs?: { c50?: string; c144?: string };
  isActive?: boolean;
  lastSeen?: string | null;
} }

export function normalizeChats(resp: OFChatsResp, accountId: string): OFChatItem[] {
  const list = resp.list || resp.chats || [];
  return list.map((c) => {
    const cnt =
      (c as OFChatItem & { unreadMessagesCount?: number }).unreadMessagesCount ?? 0;
    return {
      ...c,
      __accountId: accountId,
      // OF sends a count; the app reads `hasUnread`, derived here so every consumer sees one flag.
      unreadMessagesCount: cnt,
      hasUnread: cnt > 0 || !!c.hasUnread,
    };
  });
}

// Measured: each 90 s poll re-sent by-ids for every row (13 of an idle open chat's 27 calls/min).
export const ENRICH_TTL_MS = 10 * 60_000;

export function unenriched(ids: FanId[], accountId: string, now: number, qc: QueryClient): FanId[] {
  return ids.filter((id) => now - (qc.getQueryData<OFUserName>(ofUserNameKey(accountId, id))?.enrichedAt ?? 0) >= ENRICH_TTL_MS);
}

export async function enrichWithUsers(
  chats: OFChatItem[],
  accountId: string,
  qc: QueryClient,
): Promise<OFChatItem[]> {
  if (chats.length === 0) return chats;
  const now = Date.now();
  const ids = unenriched(Array.from(new Set(chats.map((c) => c.withUser.id))).filter(Boolean), accountId, now, qc);
  if (ids.length === 0) return chats;

  const byId = new Map<FanId, {
    id: FanId;
    name?: string;
    username?: string;
    avatar?: string | null;
    isActive?: boolean;
    lastSeen?: string | null;
    customNickname?: string | null;
    displayName?: string | null;
    notice?: string | null;
  }>();

  try {
    const qs = new URLSearchParams();
    qs.set("ids", ids.join(","));
    const local = await relay.get<{
      fans: Record<string, {
        id: number;
        name: string | null;
        username: string | null;
        avatar: string | null;
        customNickname: string | null;
      }>;
    }>(`/admin/fans/${accountId}/by-ids?${qs.toString()}`);
    for (const [k, f] of Object.entries(local.fans || {})) {
      const nid = fanIdFromParam(k);
      if (nid == null) continue;
      if (!f.name && !f.username) continue;
      const profile = {
        id: nid,
        name: f.name ?? undefined,
        username: f.username ?? undefined,
        avatar: f.avatar ?? null,
        customNickname: f.customNickname ?? null,
      };
      byId.set(nid, profile);
      mergeOFUserName(qc, accountId, nid, (prev) => ({
        id: nid,
        name: profile.name,
        username: profile.username,
        avatar: profile.avatar,
        customNickname: profile.customNickname ?? prev?.customNickname ?? null,
        enrichedAt: now,
      }));
    }
  } catch (err) {
    console.warn("[chats] local fans/by-ids failed", err);
  }

  const missing = ids.filter((id) => !byId.has(id));
  if (missing.length > 0) {
    const chunks: FanId[][] = [];
    // /users/list takes at most ~50 ids per call (OF's batch cap).
    for (let i = 0; i < missing.length; i += 50) chunks.push(missing.slice(i, i + 50));

    const fetchChunk = async (chunk: FanId[]) => {
      const qs = new URLSearchParams();
      for (const id of chunk) qs.append("ids", String(id));
      qs.set("view", "m");
      try {
        const resp = await relay.get<UserListResp>(
          `/api/of/v2/users/list?${qs.toString()}`,
          { accountId, priority: "background" },
        );
        for (const [k, u] of Object.entries(resp || {})) {
          const nid = fanIdFromParam(k);
          if (nid == null) continue;
          const profile = {
            id: nid,
            name: u.name,
            username: u.username,
            avatar: avatarThumb(u),
            // `isActive` on /users/list is exists/not banned, not live presence; OF exposes none here.
            isActive: u.isActive,
            lastSeen: u.lastSeen ?? null,
            customNickname: u.customNickname ?? null,
            displayName: u.displayName ?? null,
            notice: u.notice ?? null,
          };
          byId.set(nid, profile);
          mergeOFUserName(qc, accountId, nid, (prev) => ({
            id: nid,
            name: u.name,
            username: u.username,
            avatar: profile.avatar,
            customNickname: profile.customNickname ?? prev?.customNickname ?? null,
            displayName: profile.displayName,
            notice: profile.notice,
            enrichedAt: now,
          }));
        }
      } catch (err) {
        console.warn("[chats] enrich users/list failed", err);
      }
    };

    // Serialize enrichment batches to reduce contention with the vault picker.
    await fetchChunk(chunks[0]);
    for (let i = 1; i < chunks.length; i++) {
      // eslint-disable-next-line no-await-in-loop
      await fetchChunk(chunks[i]);
    }
  }

  return chats.map((c) => {
    const u = byId.get(c.withUser.id);
    if (!u) return c;
    return { ...c, withUser: { ...c.withUser, ...u } };
  });
}


const SESSION = Math.random().toString(36).slice(2);

export function cachedUnreadView(qc: QueryClient, key: QueryKey): UnreadView | null {
  return completeUnreadView(qc.getQueryData(key), SESSION);
}

export function useCachedChatPages(key: QueryKey): InfiniteData<StampedPage> | undefined {
  const qc = useQueryClient();
  const hash = hashKey(key);
  const subscribe = useCallback((cb: () => void) => qc.getQueryCache().subscribe((e) => {
    if (e.query.queryHash === hash && e.type !== "observerAdded" && e.type !== "observerRemoved") cb();
  }), [qc, hash]);
  const get = useCallback(() => qc.getQueryCache().get(hash)?.state.data as InfiniteData<StampedPage> | undefined, [qc, hash]);
  return useSyncExternalStore(subscribe, get, get);
}

export function listPaintKey(
  scope: ReturnType<typeof useScope>["scope"],
  filter: ChatListParams["filter"],
  listId: ChatListParams["listId"],
  query: ChatListParams["query"],
): string {
  const scopeKey = scope.kind === "model" ? `model:${scope.accountId}` : "all";
  return `chat.list:${scopeKey}:${filter ?? ""}:${listId ?? ""}:${query ?? ""}`;
}

type ScannedChatsResponse = OFChatsResp & { scanned?: number; split_version?: string };

function readChatPage(resp: ScannedChatsResponse, accountId: string, qc: QueryClient) {
  const rows = normalizeChats(resp, accountId);
  void enrichWithUsers(rows, accountId, qc).catch(() => {});
  return { rows, hasMore: !!resp.hasMore, scanned: resp.scanned ?? rows.length, splitVersion: resp.split_version };
}

async function fetchPage(
  scope: ReturnType<typeof useScope>["scope"],
  readFrom: readonly string[],
  offset: number,
  filter: ChatListParams["filter"],
  listId: ChatListParams["listId"],
  query: ChatListParams["query"],
  limit: number,
  qc: QueryClient,
  // `priority` is explicit, never ambient: untagged calls default to 'user' relay-side and eat a reserved per-account user slot.
  { refresh = false, priority = "user", order = "recent", signal, caller = "auto", intent, cellCursors }: {
    refresh?: boolean;
    priority?: "user" | "background";
    order?: ChatListOrder;
    signal?: AbortSignal;
    caller?: ListCaller;
    intent?: "explicit";
    cellCursors?: Record<string, number>;
  },
): Promise<StampedPage> {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  qs.set("offset", String(offset));
  qs.set("order", order);
  const sort = order === "old" ? (a: OFChatItem, b: OFChatItem) => compareChats(b, a) : compareChats;
  if (filter) qs.set("filter", filter);
  if (listId) qs.set("list_id", listId);
  if (query) qs.set("query", query);
  const path = `/api/of/v2/chats?${qs.toString()}`;
  const tag = { caller, ...(intent ? { intent } : {}) };
  const stamp = { session: SESSION, askedAt: relayNow(), askedSeq: localSeq(), ...(relayOffsetKnown() ? {} : { askedAtGuess: true as const }) };
  if (readFrom.length === 0) return { rows: [], hasMore: false, moreAccounts: [], scanned: 0, ...stamp };

  const opId = perfOpId("chat.list");
  perfLog(opId, "chat.list", "requested", {
    scope: scope.kind, offset, limit, filter, listId, query,
    phase: offset === 0 ? "initial" : "page",
    accountCount: scope.kind === "all" ? readFrom.length : 1,
  });
  if (offset === 0 && priority === "user") {
    perfPaintPending(listPaintKey(scope, filter, listId, query), opId);
  }
  const seen = seenNow();

  if (scope.kind === "model") {
    const [accountId] = readFrom;
    try {
      const resp = await relay.get<ScannedChatsResponse>(
        path, { accountId, priority, ...tag }, signal, { refresh },
      );
      const page = readChatPage(resp, accountId, qc);
      const { rows, hasMore, scanned, splitVersion } = page;
      perfDelivered(opId, "chat.list", { count: rows.length, hasMore });
      return {
        rows: rows.sort(sort), hasMore, moreAccounts: hasMore ? [accountId] : [], scanned, ...stamp,
        ...(splitVersion ? { splitVersions: { [accountId]: splitVersion } } : {}),
      };
    } catch (err) {
      perfError(opId, "chat.list", { message: (err as Error)?.message });
      markIfUnknown(accountId, err, seen);
      throw err;
    }
  }

  const cells = cellMode() ? currentCellMap() : null;
  if (cells) {
    const bundle = !filter && !listId && !query && order === "recent" && limit === PAGE_SIZE && !refresh && intent !== "explicit";
    const ids = cellCursors ? readFrom.filter((id) => cellCursors[id] !== undefined) : readFrom;
    const page = await fetchCellsPage(cells, ids, offset, qs, qc,
      { bundle, refresh, priority, order, signal, tag, cellCursors, limit, seen });
    perfDelivered(opId, "chat.list", {
      count: page.rows.length, hasMore: page.hasMore, accountCount: readFrom.length, failed: page.missing?.length ?? 0,
    });
    return { ...page, ...stamp };
  }

  const focus = relayFocus();
  const results = await Promise.allSettled(
    readFrom.map(async (accountId) => {
      const r = await relay.get<ScannedChatsResponse>(
        path, { accountId, priority: accountId === focus ? priority : "background", ...tag }, signal, { refresh },
      );
      return readChatPage(r, accountId, qc);
    }),
  );
  signal?.throwIfAborted();
  const refused = results.find((r): r is PromiseRejectedResult =>
    r.status === "rejected" && (isDeepRefused(r.reason) || (offset > 0 && isRateLimited(r.reason))));
  if (refused) {
    perfError(opId, "chat.list", { message: (refused.reason as Error)?.message });
    throw refused.reason;
  }
  const merged: OFChatItem[] = [];
  let scanned = 0;
  const moreAccounts: string[] = [];
  const missing: string[] = [];
  const splitVersions: [string, string][] = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") {
      merged.push(...r.value.rows);
      scanned += r.value.scanned;
      if (r.value.hasMore) moreAccounts.push(readFrom[i]);
      if (r.value.splitVersion) splitVersions.push([readFrom[i], r.value.splitVersion]);
    } else {
      missing.push(readFrom[i]);
      markIfUnknown(readFrom[i], r.reason, seen);
    }
  });
  const failed = missing.length;
  const anyMore = moreAccounts.length > 0;
  perfDelivered(opId, "chat.list", {
    count: merged.length, hasMore: anyMore, accountCount: readFrom.length, failed,
  });
  return {
    rows: merged.sort(sort), hasMore: anyMore, moreAccounts, scanned, ...stamp,
    ...(splitVersions.length ? { splitVersions: Object.fromEntries(splitVersions) } : {}),
    ...(failed ? { partial: true, missing } : {}),
  };
}

type CellPart = { accountId: string; rows: OFChatItem[]; hasMore: boolean; scanned: number };

function markIfUnknown(accountId: string, err: unknown, seen: Seen): void {
  if (isUnknownAccount(err)) markUnknown(accountId, seen);
}

async function fetchCellsPage(
  m: CellMap, readFrom: readonly string[], offset: number, qs: URLSearchParams, qc: QueryClient,
  { bundle, refresh, priority, order, signal, tag, cellCursors, limit, seen }: {
    bundle: boolean; refresh: boolean; priority: "user" | "background"; order: ChatListOrder; signal?: AbortSignal;
    tag: { caller: ListCaller; intent?: "explicit" }; cellCursors?: Record<string, number>; limit: number; seen: Seen;
  },
): Promise<Omit<StampedPage, "session" | "askedAt" | "askedSeq">> {
  const focus = relayFocus();
  let refused: unknown = null;
  const excluded = bundle ? directIds() : null;
  const results = await askCells<CellPart[]>(m, readFrom, signal, async ({ cell, accounts, signal: s }) => {
    const cursorOf = (id: string) => cellCursors?.[id] ?? offset;
    const bundled = bundle ? accounts.filter((id) => !excluded?.has(id)) : [];
    const first = cursorOf(bundled[0]);
    const canBundle = bundled.length > 0 && bundled.every((id) => cursorOf(id) === first);
    const parts: CellPart[] = [];
    let partial: string[] = [];
    const direct = new Map<string, Promise<void>>();
    const settled = new Map<string, PromiseSettledResult<ScannedChatsResponse>>();
    const readDirect = (id: string) => {
      const search = new URLSearchParams(qs);
      search.set("offset", String(cursorOf(id)));
      direct.set(id, relay.get<ScannedChatsResponse>(
        `/api/of/v2/chats?${search}`, { accountId: id, priority: id === focus ? priority : "background", ...tag }, s, { refresh },
      ).then(
        (value) => { if (!s.aborted) settled.set(id, { status: "fulfilled", value }); },
        (reason: unknown) => { if (!s.aborted) settled.set(id, { status: "rejected", reason }); },
      ));
    };
    for (const id of accounts) {
      if (!canBundle || excluded?.has(id)) readDirect(id);
    }
    if (canBundle) {
      const b = bundleChats(await cellBundle(m, cell, bundled, first, s, tag.caller));
      s.throwIfAborted();
      for (const id of b.gone) markUnknown(id, seen);
      for (const id of b.unsupported) {
        markDirect(id, seen);
        if (bundled.includes(id)) readDirect(id);
      }
      for (const c of b.chats) parts.push({ accountId: c.accountId, ...readChatPage(c.body as ScannedChatsResponse, c.accountId, qc) });
      partial = [...new Set([...b.partial, ...b.failed])].filter((id) => !direct.has(id));
    }
    if (direct.size && !s.aborted) {
      let stop: () => void;
      const deadline = new Promise<void>((resolve) => { stop = resolve; });
      s.addEventListener("abort", stop!, { once: true });
      try {
        await Promise.race([Promise.all(direct.values()), deadline]);
      } finally {
        s.removeEventListener("abort", stop!);
      }
    }
    signal?.throwIfAborted();
    if (!canBundle) s.throwIfAborted();
    for (const id of direct.keys()) {
      const r = settled.get(id);
      if (r?.status === "fulfilled") {
        parts.push({ accountId: id, ...readChatPage(r.value, id, qc) });
        continue;
      }
      partial.push(id);
      if (r?.status === "rejected") {
        markIfUnknown(id, r.reason, seen);
        if (isDeepRefused(r.reason) || (cursorOf(id) > 0 && isRateLimited(r.reason))) refused ??= r.reason;
      }
    }
    return { value: parts, partial };
  });
  signal?.throwIfAborted();
  if (refused) throw refused;
  const parts = results.flatMap((r) => r.ok ? r.value : []);
  const missing = [...new Set(results.flatMap((r) => r.ok ? r.partial : r.accounts))];
  const sort = cellSort(order);
  const moreAccounts = [...new Set([...parts.filter((p) => p.hasMore).map((p) => p.accountId), ...missing])];
  const page = {
    rows: mergeCellRows(parts.map((p) => p.rows), sort), hasMore: moreAccounts.length > 0, moreAccounts,
    scanned: parts.reduce((n, p) => n + p.scanned, 0), ...(missing.length ? { partial: true, missing } : {}),
  };
  return { ...page, cellCursors: nextCellCursors(page, offset, limit, cellCursors) };
}

export function prefetchModelChatList(
  qc: QueryClient,
  accountId: string,
  limit: number = PAGE_SIZE,
): Promise<void> {
  if (!accountId || unknownIds().has(accountId)) return Promise.resolve();
  const scope = { kind: "model", accountId } as const;
  const queryKey = chatsQueryKey("model", chatListAccountKey(scope, []), { limit });
  return qc.prefetchInfiniteQuery({
    queryKey,
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const offset = (pageParam as number) ?? 0;
      const kept = replayCachedPage(qc.getQueryState<InfiniteData<StampedPage>>(queryKey), offset, limit);
      if (kept) return kept;
      return fetchPage(scope, [accountId], offset, null, null, null, limit, qc, { priority: "background", caller: "prefetch" });
    },
    // MUST mirror useChatList's infinite-query config: same key, a missing getNextPageParam fails the list to load.
    getNextPageParam: (lastPage: StampedPage, allPages: StampedPage[]) =>
      lastPage.hasMore ? allPages.length * limit : undefined,
    staleTime: 30_000,
    structuralSharing: commitChatPages(qc, queryKey, shareChatPages),
  });
}

function withHead(prev: InfiniteData<StampedPage> | undefined, head: StampedPage): InfiniteData<StampedPage> | undefined {
  if (!prev?.pages?.length) return prev;
  if ((prev.pages[0].askedSeq ?? -Infinity) > (head.askedSeq ?? -Infinity)) return prev;
  return { ...prev, pages: [head, ...prev.pages.slice(1)] };
}

function untilIdle(qc: QueryClient, hash: string): Promise<void> {
  return new Promise((resolve) => {
    const check = () => {
      const fetchStatus = qc.getQueryCache().get(hash)?.state.fetchStatus;
      if (fetchStatus && fetchStatus !== "idle") return;
      off();
      resolve();
    };
    const off = qc.getQueryCache().subscribe((e) => { if (e.query.queryHash === hash) check(); });
    check();
  });
}

type ChatAccount = Pick<AccountMeta, "id" | "platform">;

function readFromIds(
  scope: Scope, accountIds: readonly string[], platformOf: (accountId: string) => AccountPlatform | null,
  filter: ChatListParams["filter"], listId: ChatListParams["listId"], unknown: ReadonlySet<string>,
): string[] {
  return (scope.kind === "model" ? [scope.accountId] : accountIds)
    .filter((id) => !unknown.has(id) && platformHonours(platformOf(id), filter, listId));
}

export async function refreshChatHead(
  qc: QueryClient, scope: Scope, accounts: readonly ChatAccount[],
): Promise<void> {
  const prefix = ["chats", scope.kind, chatListAccountKey(scope, accounts)];
  const matches = qc.getQueryCache().findAll({ queryKey: prefix });
  const platforms = new Map(accounts.map((a) => [a.id, accountPlatform(a)]));
  const platformOf = (id: string) => platforms.get(id) ?? null;
  await Promise.allSettled(matches.map(async (query) => {
    const { queryKey: key, queryHash } = query;
    await untilIdle(qc, queryHash);
    if (qc.getQueryCache().get(queryHash) !== query) return;
    if (!query.getObserversCount()) return query.invalidate();
    const { filter, listId, query: search, limit, order, gated } = decodeChatsKey(key);
    if (!(query.state.data as InfiniteData<StampedPage> | undefined)?.pages?.length || gated) return;
    const ids = readFromIds(scope, accounts.map((a) => a.id), platformOf, filter, listId, unknownIds());
    if (!ids.length) return;
    const head = await fetchPage(
      scope, ids, 0, filter, listId, search, limit, qc,
      { priority: "user", order, caller: "warmup" },
    );
    qc.setQueryData<InfiniteData<StampedPage>>(key, (prev) => withHead(prev, head));
  }));
}

type HeadUpdate = (prev: InfiniteData<StampedPage> | undefined) => InfiniteData<StampedPage> | undefined;

function spliceInto(ids: readonly string[], head: StampedPage, order: ChatListOrder): HeadUpdate {
  const sort = cellSort(order);
  return (prev) => prev?.pages?.length
    ? { ...prev, pages: [spliceHead(prev.pages[0], head, new Set(ids), sort), ...prev.pages.slice(1)] }
    : prev;
}

export async function spliceCellHeads(
  qc: QueryClient, accounts: ReadonlySet<string>, placed: ReadonlySet<string>,
): Promise<void> {
  await Promise.allSettled(qc.getQueryCache().findAll({ queryKey: ["chats", "all"] }).map(async (query) => {
    const k = decodeChatsKey(query.queryKey);
    const unknown = unknownIds();
    const ids = k.accountKey.split(",").filter((id) => accounts.has(id) && !unknown.has(id));
    if (resyncAction(query.queryKey, accounts, placed) === "skip") return;
    await untilIdle(qc, query.queryHash);
    const data = query.state.data as InfiniteData<StampedPage> | undefined;
    const tail = data && data.pages.length > 1 ? data.pages.at(-1) : undefined;
    const missing = tail?.missing?.filter((id) => accounts.has(id) && !unknown.has(id) && tail.cellCursors?.[id] !== undefined) ?? [];
    const action = resyncAction(query.queryKey, accounts, placed, missing.length > 0);
    if (action === "invalidate" || !k.unfiltered || !query.getObserversCount() || !data?.pages.length) {
      return invalidateVaultQueries(qc, { queryKey: query.queryKey, exact: true });
    }
    const head = fetchPage({ kind: "all" }, ids, 0, null, null, null, k.limit, qc,
      { priority: "background", order: k.order, caller: "warmup" }).then((page) =>
      qc.setQueryData<InfiniteData<StampedPage>>(query.queryKey, spliceInto(ids, page, k.order)));
    if (action === "retryTail" && tail) {
      const repair = fetchPage(
        { kind: "all" }, missing, 0, null, null, null, k.limit, qc,
        { priority: "background", order: k.order, caller: "warmup", intent: "explicit", cellCursors: tail.cellCursors },
      ).then((retry) => qc.setQueryData<InfiniteData<StampedPage>>(query.queryKey, (prev) => prev?.pages.at(-1) === tail
        ? { ...prev, pages: [...prev.pages.slice(0, -1), retryTail(tail, retry, new Set(missing), cellSort(k.order))] }
        : prev));
      await Promise.allSettled([head, repair]);
    } else {
      await head;
    }
  }));
}

// Head page only, not refetchInterval: that re-walks every loaded page (a multi-account fan-out each), ~27% of inbox list traffic.
function useHeadPagePoll(args: {
  enabled: boolean;
  queryKey: QueryKey;
  fetchHead: () => Promise<HeadUpdate>;
  live: () => boolean;
}) {
  const qc = useQueryClient();
  const latest = useRef(args);
  latest.current = args;

  const { enabled, queryKey } = args;
  const keyHash = hashKey(queryKey);

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    let inFlight = false;
    let lastRun = 0;
    let dueAt = Infinity;

    const tick = async (): Promise<void> => {
      const { queryKey: key, fetchHead } = latest.current;
      const state = qc.getQueryState(key);
      if (state && state.fetchStatus !== "idle") return;
      if (!(state?.data as InfiniteData<StampedPage> | undefined)?.pages?.length) {
        void qc.refetchQueries({ queryKey: key, exact: true });
        return;
      }
      try {
        const update = await fetchHead();
        if (cancelled) return;
        qc.setQueryData<InfiniteData<StampedPage>>(key, update);
      } catch {
      }
    };

    const idlePoll = isLiveView(decodeChatsKey(queryKey));
    const delay = () => headPollDelay({
      paused: eventBus.isPaused(),
      hidden: typeof document !== "undefined" && document.hidden,
      connected: latest.current.live(),
      idlePoll,
    });
    const schedule = (immediate = false) => {
      if (cancelled || inFlight) return;
      const ms = delay();
      if (ms === null) {
        if (timer) clearTimeout(timer);
        timer = undefined;
        return;
      }
      if (immediate) {
        run();
        return;
      }
      const at = Date.now() + ms;
      if (timer && at >= dueAt) return;
      if (timer) clearTimeout(timer);
      dueAt = at;
      timer = setTimeout(run, ms);
    };
    const run = () => {
      if (inFlight) return;
      if (timer) clearTimeout(timer);
      timer = undefined;
      inFlight = true;
      lastRun = Date.now();
      void tick().catch(() => {}).then(() => {
        inFlight = false;
        if (!cancelled) schedule();
      });
    };
    const onReturn = () => {
      if (document.visibilityState === "visible") schedule(Date.now() - lastRun >= RETURN_GAP_MS);
    };

    schedule();
    const offFocus = focusManager.subscribe(() => queueMicrotask(() => schedule()));
    document.addEventListener("visibilitychange", onReturn);
    window.addEventListener("focus", onReturn);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      offFocus();
      document.removeEventListener("visibilitychange", onReturn);
      window.removeEventListener("focus", onReturn);
    };
  }, [enabled, keyHash, qc]);
}

export function chatListAccountKey(scope: Scope, accounts: ReadonlyArray<{ id: string }>): string {
  const key = scope.kind === "model" ? scope.accountId : accounts.map((a) => a.id).sort().join(",");
  const token = cellScopeToken();
  return token ? `${key},${token}` : key;
}

export function chatsQueryKey(
  scopeKind: Scope["kind"], accountKey: string,
  { filter = null, listId = null, query = null, limit = PAGE_SIZE, order = "recent", gated = false }:
    Omit<ChatListParams, "enabled"> & { gated?: boolean } = {},
) {
  return ["chats", scopeKind, accountKey, filter ?? null, listId ?? null, query ?? null, limit,
    ...(order === "recent" && !gated ? [] : [order]), ...(gated ? [true] as const : [])] as const;
}

export function useChatList(params: ChatListParams = {}) {
  const { scope } = useScope();
  const accounts = usePlatformAccounts(undefined, cellMode());
  const scopedId = scope.kind === "model" ? scope.accountId : null;
  const knownAccounts = useAccounts().data?.accounts;
  const scopedAccount = scopedId ? knownAccounts?.find((a) => a.id === scopedId) : undefined;
  const scopedPlatform = useAccountPlatform(scopedId) ?? (scopedAccount ? accountPlatform(scopedAccount) : null);
  const qc = useQueryClient();
  const { filter, listId, query, limit = PAGE_SIZE, order = "recent", enabled: wanted = true } = params;
  const rosterPlatforms = useMemo(() => new Map(knownAccounts?.map((a) => [a.id, accountPlatform(a)])), [knownAccounts]);
  const platformOf = useCallback((accountId: string) =>
    scope.kind === "model" ? scopedPlatform : rosterPlatforms.get(accountId) ?? null, [scope.kind, scopedPlatform, rosterPlatforms]);
  const honours = useCallback((accountId: string | undefined) =>
    platformHonours(platformOf(accountId ?? ""), filter, listId), [platformOf, filter, listId]);
  const cellMap = useCellMap();
  const waitCells = cellMode() && !cellMap;
  const placed = useMemo(() => cellMap ? new Set(cellMap.accounts.map((a) => a.account_id)) : null, [cellMap]);
  const unknown = useUnknownAccounts();
  const readFrom = readFromIds(scope, accounts.map((a) => a.id), platformOf, filter, listId, unknown)
    .filter((id) => !placed || placed.has(id));
  const gated = scope.kind === "model" && readFrom.length === 0;
  const unknownAccount = scopedId !== null && unknown.has(scopedId);

  const eligibleFallbackRows = useCallback((rows: OFChatItem[]) => {
    const kept = rows.filter((row) => honours(row.__accountId));
    return kept.length === rows.length ? rows : kept;
  }, [honours]);

  const accountKey = chatListAccountKey(scope, accounts);

  const scopeKey = ["chats", scope.kind, accountKey] as const;

  const queryKey = chatsQueryKey(scope.kind, accountKey, { filter, listId, query, limit, order, gated });

  const refreshOnceRef = useRef(false);
  const keyHash = hashKey(queryKey);
  const keyRef = useRef(keyHash);
  keyRef.current = keyHash;
  const loadMoreState = useRef(initialLoadMore(keyHash));
  const step = (a: LoadMoreAction): Pending | null => {
    const prev = loadMoreReducer(loadMoreState.current, { type: "reset", key: keyRef.current });
    loadMoreState.current = loadMoreReducer(prev, a);
    return startedBy(prev, loadMoreState.current);
  };

  const enabled =
    wanted && !waitCells && (scope.kind === "model" ? !!scope.accountId : accounts.length > 0);

  const q = useInfiniteQuery<StampedPage>({
    queryKey,
    enabled,
    initialPageParam: 0,
    // MUST mirror prefetchModelChatList's config: both share one key, and a missing getNextPageParam corrupts the query.
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.hasMore) return undefined;
      const offset = allPages.length * limit;
      return lastPage.cellCursors ? { offset, cellCursors: lastPage.cellCursors } : offset;
    },
    queryFn: (ctx) => {
      const param = ctx.pageParam as number | { offset: number; cellCursors: Record<string, number> };
      const offset = typeof param === "object" ? param.offset : param ?? 0;
      const state = qc.getQueryState<InfiniteData<StampedPage>>(ctx.queryKey);
      const fetchMore = !!state?.fetchMeta?.fetchMore;
      const kept = replayCachedPage(state, offset, limit, param);
      if (kept) return kept;
      const lm = loadMoreState.current;
      const pending = fetchMore && lm.key === hashKey(ctx.queryKey) ? pendingFor(lm, offset) : null;
      if (pending && pending === lm.pending) loadMoreState.current = loadMoreReducer(lm, { type: "taken", pending, offset });
      const bypass = refreshOnceRef.current && offset === 0;
      const caller = listCaller({
        fetchMore, pending: pending?.caller ?? null, refresh: refreshOnceRef.current && !fetchMore,
        cached: !!state?.data?.pages?.length, offset, query: !!query,
      });
      return fetchPage(
        scope, readFrom, offset, filter, listId, query, limit, qc,
        // Only a search may read ctx.signal: React Query cancels a fetch whose signal was read once its key loses its last observer, dropping a next page in flight.
        { refresh: bypass, order, signal: query ? ctx.signal : undefined, caller, intent: pending?.explicit ? "explicit" : undefined,
          cellCursors: typeof param === "object" ? param.cellCursors : undefined },
      );
    },
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    placeholderData: (prev, prevQuery) => {
      if (gated) return undefined;
      const prevKey = prevQuery?.queryKey;
      const sameScope =
        prevKey?.[0] === scopeKey[0] &&
        prevKey[1] === scopeKey[1] &&
        (scope.kind !== "model" || prevKey[2] === scopeKey[2]) &&
        tokenOf(String(prevKey[2] ?? "")) === tokenOf(accountKey);
      const previous = sameScope ? keepPreviousData(prev) : undefined;
      if (!previous) return previous;
      const pages = previous.pages.map((page) => {
        const rows = eligibleFallbackRows(page.rows);
        return rows === page.rows ? page : { ...page, rows };
      });
      return pages.every((page, i) => page === previous.pages[i]) ? previous : { ...previous, pages };
    },
    structuralSharing: commitChatPages(qc, queryKey, shareChatPages),
  });

  const headOf = (ids: readonly string[]) => fetchPage(
    scope, ids, 0, filter, listId, query, limit, qc,
    { priority: "background", order, caller: "poll" },
  );
  const fetchHead = async (): Promise<HeadUpdate> => {
    const down = cellMap ? readFrom.filter((id) => !eventBus.isConnected(id)) : [];
    if (!down.length || down.length === readFrom.length) {
      const head = await headOf(readFrom);
      return cellMap && head.partial ? spliceInto(readFrom, head, order) : (prev) => withHead(prev, head);
    }
    return spliceInto(down, await headOf(down), order);
  };
  const live = () => (cellMap ? readFrom.every((id) => eventBus.isConnected(id)) : eventBus.isConnected());

  useHeadPagePoll({ enabled: enabled && readFrom.length > 0, queryKey, fetchHead, live });

  const rows = useMemo(() => {
    const out: OFChatItem[] = [];
    const seen = new Set<string>();
    for (const p of q.data?.pages ?? []) {
      for (const c of p.rows) {
        if (placed && !placed.has(c.__accountId ?? "")) continue;
        const key = chatRowKey(c);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(c);
      }
    }
    return out;
  }, [q.data, placed]);

  const fetchedLive = enabled && !q.isPlaceholderData && q.data?.pages[0]?.session === SESSION;

  const nextPage = (p: Pending) =>
    q.fetchNextPage({ cancelRefetch: false }).finally(() => step({ type: "taken", pending: p }));

  const loadMore = (caller: ListCaller, visibleRows?: number): Promise<unknown> => {
    const state = qc.getQueryState<InfiniteData<StampedPage>>(queryKey);
    const busy: Busy = !state || state.fetchStatus === "idle" ? "idle" : state.fetchMeta?.fetchMore ? "next" : "walk";
    const started = step({
      type: "request", caller, busy, hasMore: !!q.hasNextPage, failed: state?.status === "error",
      mayAuto: mayAutoPage({ pagesLoaded: state?.data?.pages?.length ?? 0, visibleRows: visibleRows ?? rows.length }),
    });
    if (started) return nextPage(started);
    return busy === "next" ? q.fetchNextPage({ cancelRefetch: false }) : Promise.resolve();
  };

  const settledRef = useRef<() => void>(() => {});
  settledRef.current = () => {
    const started = step({ type: "settled", ok: !q.isError, hasMore: !!q.hasNextPage });
    if (started) void nextPage(started);
  };
  useEffect(() => {
    if (!q.isFetching) settledRef.current();
  }, [q.isFetching, keyHash]);

  const refresh = useCallback(() => {
    refreshOnceRef.current = true;
    return q.refetch().finally(() => {
      refreshOnceRef.current = false;
    });
  }, [q]);

  return {
    ...q,
    data: rows,
    pages: q.data?.pages.map((p) => p.rows),
    hasMore: !!q.hasNextPage,
    scanned: q.data?.pages.reduce((sum, p) => sum + (p.scanned ?? p.rows.length), 0) ?? 0,
    loadMore,
    isFetchingMore: q.isFetchingNextPage,
    refresh,
    fetchedLive,
    eligibleFallbackRows,
    canUseSeed: q.isPending && !gated,
    unknownAccount,
  };
}
