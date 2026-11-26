"use client";


import { hashKey, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { relay, type OFMessage, type OFMessagesResp } from "@/lib/relay";
import { compareFanIds, isValidFanId, sameUserId, type FanId } from "@/lib/fanId";
import type { SendFailure } from "@/lib/sendFailure";
import { eventBus } from "@/lib/events";
import { appendMsg, dropMsg, failMsg, reconcileMsg, THREAD_KEEP, toUtcIso, trimThread } from "@/lib/threadCache";
import { perfDelivered, perfError, perfLog, perfOpId, perfPaintPending } from "@/lib/perfLog";

import {
  canLoadOlder, hasOlder as pagerHasOlder, initialOlderPager, isLoadingOlder as pagerLoading, OLDER_TIMEOUT_MS,
  olderFailed as pagerFailed, olderPagerReducer, type OlderPager, type OlderPagerAction,
} from "./olderPager";

const PAGE_SIZE = 30;
// Mirrors service/attribution.py _MASS_PLACEHOLDER_BASE: per-recipient optimistic rows from mass-send; OF never returns an id this high
export const MASS_PLACEHOLDER_MIN = 5_000_000_000_000_000;
// 6e15 starts ledger-synthesized TIP rows (transaction_ingest _TIP_MSG_ID_BASE): permanent, the WS pump never saw them, so staleness rules must never touch them
export const MASS_PLACEHOLDER_END = 6_000_000_000_000_000;
// A placeholder only bridges send to delivery (OF's queue can lag minutes): uncorroborated while a fetched message is this much newer, it is stale
const MASS_PLACEHOLDER_GRACE_MS = 10 * 60_000;
const MASS_PLACEHOLDER_MAX_AGE_MS = 60 * 60_000;
const STALE_MS = 15_000;
const POLL_MS_OFFLINE = 30_000;
const POLL_MS_REALTIME = 2 * 60_000;

export interface UseChatMessagesOpts {
  accountId: string | null;
  fanId: FanId | null;
  enabled?: boolean;
  prefetchWindowMs?: number;
  // Head reads ask the relay to peek: OF leaves the chat unread
  peek?: boolean;
}

export function messagesPaintKey(accountId: string, fanId: FanId | null): string {
  return `chat.messages:${accountId}:${fanId ?? ""}`;
}

function oldestFetchedId(page: OFMessage[]): FanId | null {
  return page.find((m) => isValidFanId(m.id))?.id ?? null;
}

const headOldest = new Map<string, FanId>();
const headMore = new Map<string, boolean>();

async function fetchHeadPage(
  accountId: string,
  fanId: FanId,
  { priority, signal, peek = false }: { priority?: "background"; signal?: AbortSignal; peek?: boolean } = {},
): Promise<{ list: OFMessage[]; hasMore: boolean }> {
  const resp = await relay.get<OFMessagesResp>(
    `/api/of/v2/chats/${fanId}/messages?limit=${PAGE_SIZE}&order=desc${peek ? "&peek=1" : ""}`,
    { accountId, priority },
    signal,
  );
  const list = (resp.list || []).slice().reverse();
  const oldest = oldestFetchedId(list);
  if (oldest != null) headOldest.set(`${accountId}:${fanId}`, oldest);
  headMore.set(`${accountId}:${fanId}`, !!resp.hasMore);
  return { list, hasMore: !!resp.hasMore };
}

const backgroundFetches = new Set<string>();

export function prefetchChatMessages(
  qc: QueryClient,
  accountId: string,
  fanId: FanId,
  { staleTime = STALE_MS, yieldOnOpen = true, user = false }: { staleTime?: number; yieldOnOpen?: boolean; user?: boolean } = {},
): Promise<void> {
  const queryKey = ["messages", accountId, fanId] as const;
  const hash = hashKey(queryKey);
  return qc.prefetchQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      if (yieldOnOpen) backgroundFetches.add(hash);
      try {
        const { list } = await fetchHeadPage(accountId, fanId, {
          priority: user ? undefined : "background", signal, peek: true,
        });
        return mergeTopPage(qc.getQueryData<OFMessage[]>(queryKey) || [], list);
      } finally {
        if (yieldOnOpen) backgroundFetches.delete(hash);
      }
    },
    staleTime,
  });
}

export function useChatMessages({
  accountId, fanId, enabled = true, prefetchWindowMs, peek = false,
}: UseChatMessagesOpts) {
  const qc = useQueryClient();
  const ridesPrefetch = prefetchWindowMs !== undefined;

  const [sseConnected, setSseConnected] = useState(() => eventBus.isConnected(accountId ?? undefined));
  useEffect(() => eventBus.onStateChange(setSseConnected, accountId ?? undefined), [accountId]);

  // Load-older cursor prefers the lowest id FETCHED this mount over the cache minimum: a cached block below a gap would skip the unfetched middle for good
  const oldestCursorRef = useRef<FanId | null>(null);
  const lowerCursor = useCallback((page: OFMessage[]) => {
    const n = oldestFetchedId(page);
    if (n == null) return;
    const cur = oldestCursorRef.current;
    oldestCursorRef.current = cur == null || compareFanIds(n, cur) < 0 ? n : cur;
  }, []);
  const queryKey = ["messages", accountId, fanId] as const;

  const startPager = (): OlderPager => {
    const key = `${accountId}:${fanId}`;
    const head = ridesPrefetch ? headOldest.get(key) : undefined;
    const cached = qc.getQueryData<OFMessage[]>(queryKey) || [];
    return initialOlderPager(
      headMore.get(key) === false && head != null && cached.some((m) => sameUserId(m.id, head)),
    );
  };
  const [pager, setPager] = useState<OlderPager>(startPager);
  const pagerRef = useRef(pager);
  const dispatchPager = useCallback((action: OlderPagerAction) => {
    const next = olderPagerReducer(pagerRef.current, action);
    if (next === pagerRef.current) return;
    pagerRef.current = next;
    setPager(next);
  }, []);
  const olderSeqRef = useRef(0);
  const olderAbortRef = useRef<AbortController | null>(null);

  const chatKey = `${accountId ?? ""}:${fanId ?? ""}`;
  const chatRef = useRef(chatKey);
  if (chatRef.current !== chatKey) {
    chatRef.current = chatKey;
    oldestCursorRef.current = null;
    const fresh = startPager();
    pagerRef.current = fresh;
    if (pager !== fresh) setPager(fresh);
  }
  useEffect(() => () => {
    olderAbortRef.current?.abort();
    if (accountId && fanId != null) trimLeftThread(qc, accountId, fanId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatKey, qc]);

  const query = useQuery<OFMessage[]>({
    queryKey,
    enabled: enabled && !!accountId && fanId != null,
    queryFn: async ({ signal }) => {
      if (!accountId || fanId == null) return [];
      const opId = perfOpId("chat.messages");
      perfLog(opId, "chat.messages", "requested", {
        accountId, fanId, phase: "initial", limit: PAGE_SIZE,
      });
      if ((qc.getQueryData<OFMessage[]>(queryKey) || []).length === 0) {
        perfPaintPending(messagesPaintKey(accountId, fanId), opId);
      }
      try {
        const { list, hasMore: more } = await fetchHeadPage(accountId, fanId, { signal, peek });
        if (chatRef.current === `${accountId}:${fanId}`) {
          lowerCursor(list);
          dispatchPager({ type: "head", hasMore: more, settled: oldestCursorRef.current != null });
        }
        perfDelivered(opId, "chat.messages", {
          count: list.length, hasMore: more, phase: "initial",
        });
        // Refetch overwrites the cache: merge the fresh page so load-older pages and optimistic rows survive
        const prev = qc.getQueryData<OFMessage[]>(queryKey) || [];
        return mergeTopPage(prev, list);
      } catch (err) {
        perfError(opId, "chat.messages", {
          message: (err as Error)?.message, aborted: signal?.aborted, phase: "initial",
        });
        throw err;
      }
    },
    select: selectMessages,
    staleTime: prefetchWindowMs ?? STALE_MS,
    // eslint-disable-next-line local/no-fixed-polling -- already SSE-aware: live/offline rate picked from sseConnected
    refetchInterval: enabled ? (sseConnected ? POLL_MS_REALTIME : POLL_MS_OFFLINE) : false,
    // Two windows can show one chat; background-tab throttling slows the popout's poll, so refetch on focus
    refetchOnWindowFocus: true,
  });

  const queryRef = useRef(query);
  queryRef.current = query;
  const queryEnabled = enabled && !!accountId && fanId != null;
  useEffect(() => {
    if (!queryEnabled) return;
    const key = ["messages", accountId, fanId];
    if (!backgroundFetches.has(hashKey(key))) return;
    if (qc.getQueryState(key)?.dataUpdatedAt) return;
    let cancelled = false;
    void qc.cancelQueries({ queryKey: key, exact: true }).then(() => {
      if (!cancelled) void queryRef.current.refetch();
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatKey, queryEnabled, qc]);

  const olderCursor = useCallback((): FanId | null => {
    const current = qc.getQueryData<OFMessage[]>(queryKey) || [];
    if (oldestCursorRef.current != null) return oldestCursorRef.current;
    const head = ridesPrefetch ? headOldest.get(`${accountId}:${fanId}`) : undefined;
    if (head != null && current.some((m) => sameUserId(m.id, head))) return head;
    const oldest = current.find((m) =>
      isValidFanId(m.id) && !(typeof m.id === "number" && m.id >= MASS_PLACEHOLDER_MIN))?.id;
    return oldest ?? null;
  }, [qc, queryKey, accountId, fanId, ridesPrefetch]);

  const loadOlder = useCallback(async (): Promise<{ added: number; hasMore: boolean }> => {
    if (!accountId || fanId == null) return { added: 0, hasMore: false };
    if (!canLoadOlder(pagerRef.current)) return { added: 0, hasMore: pagerHasOlder(pagerRef.current) };
    const oldest = olderCursor();
    if (oldest == null) return { added: 0, hasMore: false };

    const seq = ++olderSeqRef.current;
    dispatchPager({ type: "start", seq });
    const ctrl = new AbortController();
    olderAbortRef.current = ctrl;
    const timer = setTimeout(
      () => ctrl.abort(new DOMException("older page timed out", "TimeoutError")), OLDER_TIMEOUT_MS,
    );
    const startedFor = chatRef.current;
    const opId = perfOpId("chat.messages");
    perfLog(opId, "chat.messages", "requested", {
      accountId, fanId, phase: "older", before_id: oldest, limit: PAGE_SIZE,
    });
    try {
      const resp = await relay.get<OFMessagesResp>(
        `/api/of/v2/chats/${fanId}/messages?limit=${PAGE_SIZE}&order=desc&before_id=${oldest}`,
        { accountId },
        ctrl.signal,
      );
      const older = (resp.list || []).slice().reverse();
      if (chatRef.current !== startedFor) return { added: 0, hasMore: false };
      const more = !!resp.hasMore;
      const low = oldestFetchedId(older);
      const progressed = low != null && compareFanIds(low, oldest) < 0;
      lowerCursor(older);
      dispatchPager({ type: "page", seq, hasMore: more, progressed });
      perfDelivered(opId, "chat.messages", {
        count: older.length, hasMore: more, progressed, phase: "older",
      });
      if (older.length === 0) return { added: 0, hasMore: more && progressed };

      qc.setQueryData<OFMessage[]>(queryKey, (prev = []) =>
        mergeOlderPage(prev, older),
      );
      return { added: older.length, hasMore: more && progressed };
    } catch (err) {
      const timedOut = (ctrl.signal.reason as Error | undefined)?.name === "TimeoutError";
      dispatchPager({ type: "fail", seq });
      perfError(opId, "chat.messages", { message: (err as Error)?.message, phase: "older", timedOut });
      if (ctrl.signal.aborted && !timedOut) return { added: 0, hasMore: false };
      throw err;
    } finally {
      clearTimeout(timer);
      if (olderAbortRef.current === ctrl) olderAbortRef.current = null;
    }
  }, [accountId, fanId, qc, queryKey, lowerCursor, olderCursor, dispatchPager]);

  const refresh = useCallback(async () => {
    await qc.invalidateQueries({ queryKey });
  }, [qc, queryKey]);

  const appendLocal = useCallback(
    (msg: OFMessage) => { qc.setQueryData<OFMessage[]>(queryKey, (prev = []) => appendMsg(prev, msg)); },
    [qc, queryKey],
  );

  const reconcileLocal = useCallback(
    (tempId: number, serverMsg: OFMessage) => {
      qc.setQueryData<OFMessage[]>(queryKey, (prev = []) => reconcileMsg(prev, tempId, serverMsg));
    },
    [qc, queryKey],
  );

  const failLocal = useCallback(
    (tempId: number, failure?: SendFailure) => {
      qc.setQueryData<OFMessage[]>(queryKey, (prev = []) => failMsg(prev, tempId, failure));
    },
    [qc, queryKey],
  );

  const dropLocal = useCallback(
    (tempId: number) => { qc.setQueryData<OFMessage[]>(queryKey, (prev = []) => dropMsg(prev, tempId)); },
    [qc, queryKey],
  );

  const prefetchHead = ridesPrefetch ? headOldest.get(`${accountId}:${fanId}`) : undefined;
  return {
    ...query,
    loadOlder,
    olderCursor,
    hasOlder: pagerHasOlder(pager),
    isLoadingOlder: pagerLoading(pager),
    olderFailed: pagerFailed(pager),
    headSettled: pager.headSettled
      || (prefetchHead != null && (query.data ?? []).some((m) => sameUserId(m.id, prefetchHead))),
    refresh,
    appendLocal,
    reconcileLocal,
    failLocal,
    dropLocal,
  };
}

function trimLeftThread(qc: QueryClient, accountId: string, fanId: FanId): void {
  setTimeout(() => {
    const q = qc.getQueryCache().find<OFMessage[]>({ queryKey: ["messages", accountId, fanId], exact: true });
    const list = q?.state.data;
    if (!q || !list || q.getObserversCount() > 0) return;
    const next = trimThread(list, THREAD_KEEP);
    if (next === list) return;
    qc.setQueryData(q.queryKey, next, { updatedAt: q.state.dataUpdatedAt });
    headMore.delete(`${accountId}:${fanId}`);
  }, 0);
}

function isWideExactMessageId(id: FanId): boolean {
  return typeof id === "string" && isValidFanId(id) && compareFanIds(id, Number.MAX_SAFE_INTEGER) > 0;
}

function numericMessageId(id: FanId): number {
  if (typeof id === "string" && (!isValidFanId(id) || isWideExactMessageId(id))) {
    return NaN;
  }
  const numeric = Number(id);
  return Number.isSafeInteger(numeric) ? numeric : NaN;
}

export function selectMessages(list: OFMessage[], now: number = Date.now()): OFMessage[] {
  const seen = new Set<string>();
  let changed = false;
  const out: OFMessage[] = [];
  for (const m of list) {
    const k = String(m.id);
    if (seen.has(k)) { changed = true; continue; }
    seen.add(k);
    const id = numericMessageId(m.id);
    if (id >= MASS_PLACEHOLDER_MIN && id < MASS_PLACEHOLDER_END) {
      const at = Date.parse(toUtcIso(m.createdAt));
      if (Number.isFinite(at) && now - at > MASS_PLACEHOLDER_MAX_AGE_MS) {
        changed = true;
        continue;
      }
    }
    out.push(m);
  }
  return changed ? out : list;
}

export function orderThread(rows: OFMessage[]): OFMessage[] {
  const timed: OFMessage[] = [];
  const tail: OFMessage[] = [];
  for (const m of rows) {
    const id = numericMessageId(m.id);
    // Tip rows carry a synthetic id (6e15 + tx.id) that says nothing about time: sort by created_at, not id
    const timePositioned =
      (Number.isFinite(id) && id > 0 && id < MASS_PLACEHOLDER_MIN) ||
      id >= MASS_PLACEHOLDER_END ||
      isWideExactMessageId(m.id);
    (timePositioned ? timed : tail).push(m);
  }
  timed.sort((a, b) => {
    const ta = Date.parse(toUtcIso(a.createdAt));
    const tb = Date.parse(toUtcIso(b.createdAt));
    const da = Number.isFinite(ta) ? ta : 0;
    const db = Number.isFinite(tb) ? tb : 0;
    return da !== db ? da - db : compareFanIds(a.id, b.id);
  });
  const out = [...timed, ...tail];
  let moved = out.length !== rows.length;
  for (let i = 0; !moved && i < out.length; i++) {
    if (out[i] !== rows[i]) moved = true;
  }
  return moved ? out : rows;
}

export function mergeTopPage(
  prev: OFMessage[],
  fresh: OFMessage[],
  now: number = Date.now(),
): OFMessage[] {
  if (prev.length === 0) return fresh;
  const freshIds = new Set(fresh.map((m) => String(m.id)));
  let minFreshId = Infinity;
  let maxFreshId = -Infinity;
  let maxFreshAt = 0;
  for (const m of fresh) {
    const id = numericMessageId(m.id);
    if (!Number.isFinite(id) || id <= 0 || id >= MASS_PLACEHOLDER_MIN) continue;
    if (id < minFreshId) minFreshId = id;
    if (id > maxFreshId) maxFreshId = id;
    const at = Date.parse(toUtcIso(m.createdAt));
    if (Number.isFinite(at) && at > maxFreshAt) maxFreshAt = at;
  }
  const older: OFMessage[] = [];
  const tail: OFMessage[] = [];
  for (const m of prev) {
    if (freshIds.has(String(m.id))) continue;
    const id = numericMessageId(m.id);
    if (id >= MASS_PLACEHOLDER_MIN && id < MASS_PLACEHOLDER_END) {
      const at = Date.parse(toUtcIso(m.createdAt));
      const stale = Number.isFinite(at) && (
        maxFreshAt > at + MASS_PLACEHOLDER_GRACE_MS
        || now - at > MASS_PLACEHOLDER_MAX_AGE_MS
      );
      if (stale) continue;
      tail.push(m);
      continue;
    }
    if (id > 0 && id < minFreshId) { older.push(m); continue; }
    // OF serves a contiguous newest slice: an id inside its span that it omitted was deleted/unsent upstream
    if (id > 0 && id <= maxFreshId) continue;
    tail.push(m);
  }
  if (older.length === 0 && tail.length === 0) return orderThread(fresh);
  return orderThread([...older, ...fresh, ...tail]);
}

export function mergeOlderPage(prev: OFMessage[], older: OFMessage[]): OFMessage[] {
  if (older.length === 0) return prev;
  const fresh = new Map(older.map((m) => [String(m.id), m]));
  let minFetchedId = Infinity;
  let maxFetchedId = -Infinity;
  for (const m of older) {
    const id = numericMessageId(m.id);
    // Synthetic bands never bound an OF id range: they would stretch max and make every cached row above look deleted
    if (!Number.isFinite(id) || id <= 0 || id >= MASS_PLACEHOLDER_MIN) continue;
    if (id < minFetchedId) minFetchedId = id;
    if (id > maxFetchedId) maxFetchedId = id;
  }
  const upgraded: OFMessage[] = [];
  for (const m of prev) {
    const hit = fresh.get(String(m.id));
    if (hit) { upgraded.push(hit); continue; }
    const id = numericMessageId(m.id);
    if (id > 0 && id < MASS_PLACEHOLDER_MIN
        && id >= minFetchedId && id <= maxFetchedId) continue;
    upgraded.push(m);
  }
  const have = new Set(prev.map((m) => String(m.id)));
  const added = older.filter((m) => !have.has(String(m.id)));
  return orderThread([...upgraded, ...added]);
}
