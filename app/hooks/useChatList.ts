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
import { relay, relayFocus, type OFChatItem, type OFChatsResp, type OFUserMini } from "@/lib/relay";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { CHATS_PAGE } from "@/lib/screenBundle";
import {
  chatRowKey, commitChatPages, compareChats, completeUnreadView, decodeChatsKey, isLiveView, localSeq, type StampedPage, type UnreadView,
} from "@/lib/chatsCache";
import { relayNow, relayOffsetKnown } from "@/lib/ageClock";
import { perfDelivered, perfError, perfLog, perfOpId, perfPaintPending } from "@/lib/perfLog";
import { usePlatformAccounts } from "./useAccounts";
import { avatarThumb, mergeOFUserName, ofUserNameKey, type OFUserName } from "./useOFUser";

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
      replaceEqualDeep(was.missing, pg.missing) === was.missing &&
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

export type ChatListFilter = "unread" | "pinned" | "priority" | "who_tipped" | "unread_tips";
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

type ScannedChatsResponse = OFChatsResp & { scanned?: number };

function readChatPage(resp: ScannedChatsResponse, accountId: string, qc: QueryClient) {
  const rows = normalizeChats(resp, accountId);
  void enrichWithUsers(rows, accountId, qc).catch(() => {});
  return { rows, hasMore: !!resp.hasMore, scanned: resp.scanned ?? rows.length };
}

async function fetchPage(
  scope: ReturnType<typeof useScope>["scope"],
  accounts: ReturnType<typeof usePlatformAccounts>,
  offset: number,
  filter: ChatListParams["filter"],
  listId: ChatListParams["listId"],
  query: ChatListParams["query"],
  limit: number,
  qc: QueryClient,
  // `priority` is explicit, never ambient: untagged calls default to 'user' relay-side and eat a reserved per-account user slot.
  { refresh = false, priority = "user", order = "recent", signal }: {
    refresh?: boolean;
    priority?: "user" | "background";
    order?: ChatListOrder;
    signal?: AbortSignal;
  } = {},
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
  const stamp = { session: SESSION, askedAt: relayNow(), askedSeq: localSeq(), ...(relayOffsetKnown() ? {} : { askedAtGuess: true as const }) };

  const opId = perfOpId("chat.list");
  perfLog(opId, "chat.list", "requested", {
    scope: scope.kind, offset, limit, filter, listId, query,
    phase: offset === 0 ? "initial" : "page",
    accountCount: scope.kind === "all" ? accounts.length : 1,
  });
  if (offset === 0 && priority === "user") {
    perfPaintPending(listPaintKey(scope, filter, listId, query), opId);
  }

  if (scope.kind === "model") {
    try {
      const resp = await relay.get<ScannedChatsResponse>(
        path, { accountId: scope.accountId, priority }, signal, { refresh },
      );
      const page = readChatPage(resp, scope.accountId, qc);
      perfDelivered(opId, "chat.list", { count: page.rows.length, hasMore: page.hasMore });
      return { ...page, rows: page.rows.sort(sort), moreAccounts: page.hasMore ? [scope.accountId] : [], ...stamp };
    } catch (err) {
      perfError(opId, "chat.list", { message: (err as Error)?.message });
      throw err;
    }
  }

  const focus = relayFocus();
  const results = await Promise.allSettled(
    accounts.map(async (acc) => {
      const r = await relay.get<ScannedChatsResponse>(
        path, { accountId: acc.id, priority: acc.id === focus ? priority : "background" }, signal, { refresh },
      );
      return readChatPage(r, acc.id, qc);
    }),
  );
  signal?.throwIfAborted();
  const merged: OFChatItem[] = [];
  let scanned = 0;
  const moreAccounts: string[] = [];
  const missing: string[] = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") {
      merged.push(...r.value.rows);
      scanned += r.value.scanned;
      if (r.value.hasMore) moreAccounts.push(accounts[i].id);
    } else {
      missing.push(accounts[i].id);
    }
  });
  const failed = missing.length;
  const anyMore = moreAccounts.length > 0;
  perfDelivered(opId, "chat.list", {
    count: merged.length, hasMore: anyMore, accountCount: accounts.length, failed,
  });
  return {
    rows: merged.sort(sort), hasMore: anyMore, moreAccounts, scanned, ...stamp,
    ...(failed ? { partial: true, missing } : {}),
  };
}

export function prefetchModelChatList(
  qc: QueryClient,
  accountId: string,
  limit: number = PAGE_SIZE,
): Promise<void> {
  if (!accountId) return Promise.resolve();
  const scope = { kind: "model", accountId } as const;
  const queryKey = ["chats", "model", accountId, null, null, null, limit] as const;
  return qc.prefetchInfiniteQuery({
    queryKey,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      fetchPage(
        scope, [], (pageParam as number) ?? 0, null, null, null, limit, qc,
        { priority: "background" },
      ),
    // MUST mirror useChatList's infinite-query config: same key, a missing getNextPageParam fails the list to load.
    getNextPageParam: (lastPage: StampedPage, allPages: StampedPage[]) =>
      lastPage.hasMore ? allPages.length * limit : undefined,
    staleTime: 30_000,
    structuralSharing: commitChatPages(qc, queryKey, shareChatPages),
  });
}

// Head page only, not refetchInterval: that re-walks every loaded page (a multi-account fan-out each), ~27% of inbox list traffic.
function useHeadPagePoll(args: {
  enabled: boolean;
  queryKey: QueryKey;
  fetchHead: () => Promise<StampedPage>;
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
        const head = await fetchHead();
        if (cancelled) return;
        qc.setQueryData<InfiniteData<StampedPage>>(key, (prev) => {
          if (!prev?.pages?.length) return prev;
          if ((prev.pages[0].askedSeq ?? -Infinity) > (head.askedSeq ?? -Infinity)) return prev;
          return { ...prev, pages: [head, ...prev.pages.slice(1)] };
        });
      } catch {
      }
    };

    const idlePoll = isLiveView(decodeChatsKey(queryKey));
    const delay = () => headPollDelay({
      paused: eventBus.isPaused(),
      hidden: typeof document !== "undefined" && document.hidden,
      connected: eventBus.isConnected(),
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
  return scope.kind === "model" ? scope.accountId : accounts.map((a) => a.id).sort().join(",");
}

export function chatsQueryKey(
  scopeKind: Scope["kind"], accountKey: string,
  { filter = null, listId = null, query = null, limit = PAGE_SIZE, order = "recent" }: Omit<ChatListParams, "enabled"> = {},
) {
  return ["chats", scopeKind, accountKey, filter ?? null, listId ?? null, query ?? null, limit,
    ...(order === "recent" ? [] : [order])] as const;
}

export function useChatList(params: ChatListParams = {}) {
  const { scope } = useScope();
  const accounts = usePlatformAccounts();
  const qc = useQueryClient();
  const { filter, listId, query, limit = PAGE_SIZE, order = "recent", enabled: wanted = true } = params;

  const accountKey = chatListAccountKey(scope, accounts);

  const scopeKey = ["chats", scope.kind, accountKey] as const;

  const queryKey = chatsQueryKey(scope.kind, accountKey, { filter, listId, query, limit, order });

  const refreshOnceRef = useRef(false);

  const enabled =
    wanted && (scope.kind === "model" ? !!scope.accountId : accounts.length > 0);

  const q = useInfiniteQuery<StampedPage>({
    queryKey,
    enabled,
    initialPageParam: 0,
    // MUST mirror prefetchModelChatList's config: both share one key, and a missing getNextPageParam corrupts the query.
    getNextPageParam: (lastPage, allPages) =>
      lastPage.hasMore ? allPages.length * limit : undefined,
    queryFn: (ctx) => {
      const offset = (ctx.pageParam as number) ?? 0;
      const bypass = refreshOnceRef.current && offset === 0;
      return fetchPage(
        scope, accounts, offset, filter, listId, query, limit, qc,
        // Only a search may read ctx.signal: React Query cancels a fetch whose signal was read once its key loses its last observer, dropping a next page in flight.
        { refresh: bypass, order, signal: query ? ctx.signal : undefined },
      );
    },
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    placeholderData: (prev, prevQuery) => {
      const prevKey = prevQuery?.queryKey;
      const sameScope =
        prevKey?.[0] === scopeKey[0] &&
        prevKey[1] === scopeKey[1] &&
        (scope.kind !== "model" || prevKey[2] === scopeKey[2]);
      return sameScope ? keepPreviousData(prev) : undefined;
    },
    structuralSharing: commitChatPages(qc, queryKey, shareChatPages),
  });

  const fetchHead = () =>
    fetchPage(
      scope, accounts, 0, filter, listId, query, limit, qc,
      { priority: "background", order },
    );

  useHeadPagePoll({ enabled, queryKey, fetchHead });

  const rows = useMemo(() => {
    const out: OFChatItem[] = [];
    const seen = new Set<string>();
    for (const p of q.data?.pages ?? []) {
      for (const c of p.rows) {
        const key = chatRowKey(c);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(c);
      }
    }
    return out;
  }, [q.data]);

  const fetchedLive = enabled && !q.isPlaceholderData && q.data?.pages[0]?.session === SESSION;

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
    loadMore: () => q.fetchNextPage(),
    isFetchingMore: q.isFetchingNextPage,
    refresh,
    fetchedLive,
  };
}
