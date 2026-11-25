"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import { focusManager, useQueries, useQueryClient } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { compareFanIds, type FanId, sameUserId } from "@/lib/fanId";
import { stripHtmlPreview } from "@/lib/htmlPreview";
import type { AttributionEntry, AttributionResponse } from "@/hooks/useChatAttribution";
import { useOfReadGate } from "@/hooks/useOfReadGate";
import { gateOptions } from "@/lib/ofReadGate";
import {
  mapOfTypeToKey,
  readNotifHistory,
  type CachedNotification,
  type NotifTypeKey,
} from "@/lib/notifSettings";
import { MONEY_ROWS_CAP, MONEY_TYPES, isMoney, type MoneyTypeKey } from "@/lib/notifText";
import { readMoneyList } from "@/lib/moneyLists";
import {
  SEEN_KEY,
  SNAPSHOT_MAX_ITEMS,
  readMoneySnapshot,
  readSeenTs,
  resolveRailAccounts,
  slimNotif,
  snapshotKeyOf,
  unseenCountOf,
  writeMoneySnapshot,
  writeSeenTs,
  type NotificationItem,
  type RailSettings,
  type SnapshotMap,
} from "@/lib/moneyRailStorage";

const DETAIL_ROWS_LOOKAHEAD = 3;
const DETAIL_ROWS_MAX = 12;
const DETAIL_REFRESH_MIN_GAP_MS = 10_000;
const LIST_STALE_MS = 5 * 60_000;
const LIST_SAFETY_POLL_MS = 10 * 60_000;
const LIST_ROOTS = ["notif-list"] as const;

export interface MergedItem {
  n: NotificationItem;
  accountId: string;
  typeKey: NotifTypeKey;
  ts: number;
}

export interface ReplyState {
  text: string;
  outbound: boolean;
  seen: boolean;
  unread: boolean;
  byBot: boolean;
  stale: boolean;
}

export function lastOutboundOf(
  resp: AttributionResponse | undefined,
): { messageId: FanId; automationKind: string | null } | null {
  const entries = Object.entries(resp?.by_msg_id ?? {});
  if (entries.length === 0) return null;
  let best: { messageId: FanId; automationKind: string | null } | null = null;
  for (const [id, entry] of entries) {
    // Keep the id as exact text: Number(id) rounds Fansly snowflakes and broke the string === against the wire id (byBot never fired).
    if (!/^\d+$/.test(id)) continue;
    if (!best || compareFanIds(id, best.messageId) > 0) {
      best = { messageId: id, automationKind: (entry as AttributionEntry).automation_kind ?? null };
    }
  }
  return best;
}

function msgTs(m?: { createdAt?: string } | null): number {
  return m?.createdAt ? Date.parse(m.createdAt) || 0 : 0;
}

export function replyStateOf(
  detail: OFChatItem | null,
  cached: OFChatItem | null,
  accountId: string,
  lastOutbound: { messageId: FanId; automationKind: string | null } | null = null,
): ReplyState | null {
  const dLm = detail?.lastMessage ?? null;
  const cLm = cached?.lastMessage ?? null;
  const cacheIsNewer = !!cLm && msgTs(cLm) > msgTs(dLm);
  const lm = cacheIsNewer ? cLm : (dLm ?? cLm);
  if (!lm) return null;

  // Receipt ids compare via compareFanIds, not Math.max: float64 mangles Fansly snowflakes.
  const lastReadCandidates = [detail?.lastReadMessageId, cached?.lastReadMessageId]
    .filter((v): v is NonNullable<typeof v> => v != null && String(v) !== "0");
  const lastRead: FanId | null = lastReadCandidates.length
    ? lastReadCandidates.reduce((a, b) => (compareFanIds(a, b) >= 0 ? a : b))
    : null;
  // String-normalized: a Fansly fromUser.id is a string snowflake, Number() never matched it.
  const outbound = sameUserId(lm.fromUser?.id, accountId);
  const text = lm.text?.trim()
    ? stripHtmlPreview(lm.text, 60)
    : lm.mediaCount
      ? `(${lm.mediaCount} media)`
      : "";
  const stale = cacheIsNewer && !!dLm;

  // Claim a bot sent it only when the attribution row is FOR this exact message; else stay silent (no false orange dot).
  const byBot =
    outbound &&
    !stale &&
    lm.id != null &&
    lastOutbound != null &&
    sameUserId(lastOutbound.messageId, lm.id) &&
    !!lastOutbound.automationKind;

  return {
    text,
    outbound,
    seen: outbound && !stale && lastRead != null && lm.id != null && compareFanIds(lastRead, lm.id) >= 0,
    unread: !outbound && ((cached?.unreadMessagesCount ?? detail?.unreadMessagesCount ?? 0) > 0
      || !!(cached?.hasUnread ?? detail?.hasUnread)),
    byBot,
    stale,
  };
}

export function payerIdOf(m: MergedItem): FanId | undefined {
  return m.n.user?.id ?? m.n.fromUser?.id;
}

export function distinctPayers(
  rows: readonly MergedItem[], cap = Infinity,
): { accountId: string; fanId: FanId }[] {
  const out: { accountId: string; fanId: FanId }[] = [];
  const seen = new Set<string>();
  for (const m of rows) {
    const fanId = payerIdOf(m);
    if (!fanId) continue;
    const key = `${m.accountId}:${fanId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ accountId: m.accountId, fanId });
    if (out.length >= cap) break;
  }
  return out;
}

export function mergeMoneyRows(
  lists: readonly { aid: string; type: MoneyTypeKey; rows: readonly NotificationItem[] | undefined }[],
  history: Readonly<Record<string, readonly CachedNotification[]>>,
  accountIds: readonly string[],
): MergedItem[] {
  const acc: MergedItem[] = [];
  const seenIds = new Set<string>();
  for (const { aid, type, rows } of lists) {
    for (const n of rows ?? []) {
      const ts = n.createdAt ? Date.parse(n.createdAt) || 0 : 0;
      if (n.id != null) seenIds.add(`${aid}:${n.id}`);
      acc.push({ n, accountId: aid, typeKey: type, ts });
    }
  }
  for (const aid of accountIds) {
    for (const c of history[aid] ?? []) {
      const key = c.typeKey ?? mapOfTypeToKey(c.type);
      if (!isMoney(key)) continue;
      if (seenIds.has(`${aid}:${c.id}`)) continue;
      const ts = c.createdAt ? Date.parse(c.createdAt) || 0 : 0;
      acc.push({
        n: {
          id: c.id,
          type: c.type,
          text: c.text,
          createdAt: c.createdAt,
          user: c.user,
          replacePairs: c.replacePairs,
        },
        accountId: aid,
        typeKey: key,
        ts,
      });
    }
  }
  acc.sort((a, b) => b.ts - a.ts);
  return acc.slice(0, MONEY_ROWS_CAP);
}

function useTabVisible(): boolean {
  const [visible, setVisible] = useState(() => focusManager.isFocused());
  useEffect(() => focusManager.subscribe(setVisible), []);
  return visible;
}

interface StoredFeed {
  snapshot: SnapshotMap;
  seenTs: number;
  hydrated: boolean;
}

export function useMoneyRailFeed({
  settings,
  activeAccounts,
  open,
}: {
  settings: RailSettings;
  activeAccounts: readonly { id: string; session_dead_at?: string | null }[];
  open: boolean;
}) {
  const [stored, setStored] = useState<StoredFeed>({ snapshot: {}, seenTs: 0, hydrated: false });
  // No useScope() on purpose: the rail watches every active model so money on another model is never missed.
  const { snapshot, seenTs, hydrated } = stored;
  useEffect(() => {
    let seen = readSeenTs();
    if (!seen) {
      seen = Date.now();
      writeSeenTs(seen);
    }
    setStored({ snapshot: readMoneySnapshot(), seenTs: seen, hydrated: true });
  }, []);
  
  const targetAccountIds = useMemo<string[]>(
    () => resolveRailAccounts(settings, activeAccounts.filter((a) => !a.session_dead_at)),
    [settings, activeAccounts],
  );
  const gateOf = useOfReadGate(targetAccountIds, LIST_ROOTS);

  const visible = useTabVisible();
  const missedWhileHiddenRef = useRef(false);
  const [historyTick, bumpHistory] = useState(0);
  useEffect(() => {
    const bump = () => {
      if (focusManager.isFocused()) bumpHistory((n) => n + 1);
      else missedWhileHiddenRef.current = true;
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === "chatterly:notif-history:v1") bump();
      if (e.key === SEEN_KEY) {
        const ts = readSeenTs();
        setStored((s) => (s.seenTs === ts ? s : { ...s, seenTs: ts }));
      }
    };
    window.addEventListener("chatterly:notif-history", bump);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("chatterly:notif-history", bump);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  // Not gated on open (a collapsed rail still renders live rows); keys match the bell's so both share one cache entry.
  const queryDefs = useMemo(
    () => targetAccountIds.flatMap((aid) => MONEY_TYPES.map((type) => ({ aid, type }))),
    [targetAccountIds],
  );
  const listQueries = useQueries({
    queries: queryDefs.map(({ aid, type }) => ({
      queryKey: ["notif-list", aid, type] as const,
      queryFn: ({ signal }) => readMoneyList(aid, type, signal),
      enabled: hydrated,
      staleTime: LIST_STALE_MS,
      refetchOnWindowFocus: true,
      // eslint-disable-next-line local/no-fixed-polling -- safety re-read of OF's feed for rows SSE missed (TODO verify: could be ssePoll)
      refetchInterval: LIST_SAFETY_POLL_MS,
      ...gateOptions(gateOf(aid)),
      placeholderData: () => snapshot[snapshotKeyOf(aid, type)]?.items,
    })),
  });

  const dataSig = listQueries.map((q) => q.dataUpdatedAt).join(",");

  useEffect(() => {
    if (!hydrated) return;
    const map = readMoneySnapshot();
    let dirty = false;
    listQueries.forEach((q, i) => {
      const def = queryDefs[i];
      if (!def || !q.data || q.isPlaceholderData || !q.dataUpdatedAt) return;
      const key = snapshotKeyOf(def.aid, def.type);
      if (map[key]?.at === q.dataUpdatedAt) return;
      map[key] = { at: q.dataUpdatedAt, items: q.data.slice(0, SNAPSHOT_MAX_ITEMS).map(slimNotif) };
      dirty = true;
    });
    if (dirty) writeMoneySnapshot(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, dataSig]);

  const placeholderAids = new Set<string>();
  listQueries.forEach((q, i) => {
    if (q.isPlaceholderData) {
      const def = queryDefs[i];
      if (def) placeholderAids.add(def.aid);
    }
  });
  const anyRefreshing = listQueries.some((q) => q.isFetching);

  const merged = useMemo<MergedItem[]>(
    () => mergeMoneyRows(
      queryDefs.map(({ aid, type }, i) => ({ aid, type, rows: listQueries[i]?.data })),
      readNotifHistory(),
      targetAccountIds,
    ),
    // `snapshot` stays a dep: placeholder rows arrive via q.data without moving dataUpdatedAt (dataSig).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dataSig, queryDefs, targetAccountIds, historyTick, snapshot],
  );

  const unseen = unseenCountOf(merged, seenTs);
  useEffect(() => {
    if (!hydrated || merged.length === 0) return;
    if ((open ? settings.bigRows : settings.smallRows) === 0) return;
    const newest = merged[0]?.ts ?? 0;
    if (newest > seenTs) {
      writeSeenTs(newest);
      setStored((s) => ({ ...s, seenTs: newest }));
    }
  }, [hydrated, merged, open, settings, seenTs]);

  const detailTargets = useMemo(() => {
    const want = (open ? settings.bigRows : settings.smallRows) + DETAIL_ROWS_LOOKAHEAD;
    return distinctPayers(merged.slice(0, Math.min(want, DETAIL_ROWS_MAX)))
      .map(({ accountId, fanId }) => ({ aid: accountId, fanId }));
  }, [merged, open, settings.bigRows, settings.smallRows]);

  const chatQueries = useQueries({
    queries: detailTargets.map(({ aid, fanId }) => ({
      queryKey: ["chat-detail", aid, fanId] as const,
      queryFn: () => relay.get<OFChatItem>(
        // background: up to 12 OF calls per account re-fired on each SSE money event; 'user' priority would crowd out real clicks in the per-account lane.
        `/api/of/v2/chats/${fanId}`, { accountId: aid, priority: "background" },
      ),
      enabled: hydrated,
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    })),
  });

  const qc = useQueryClient();
  const [chatsCacheTick, setChatsCacheTick] = useState(0);
  useEffect(() => qc.getQueryCache().subscribe((e) => {
    if (e.query.queryKey?.[0] === "chats" && e.type === "updated") {
      if (!focusManager.isFocused()) { missedWhileHiddenRef.current = true; return; }
      queueMicrotask(() => setChatsCacheTick((t) => t + 1));
    }
  }), [qc]);

  useEffect(() => {
    if (!visible || !missedWhileHiddenRef.current) return;
    missedWhileHiddenRef.current = false;
    bumpHistory((n) => n + 1);
    setChatsCacheTick((t) => t + 1);
  }, [visible]);

  const cachedChats = useMemo(() => {
    type Page = { rows: OFChatItem[] };
    type Infinite = { pages?: Page[] };
    const map = new Map<string, OFChatItem>();
    for (const q of qc.getQueryCache().findAll({ queryKey: ["chats"] })) {
      const data = q.state.data as Infinite | undefined;
      for (const p of data?.pages ?? []) {
        for (const c of p.rows ?? []) {
          const aid = c.__accountId ?? "";
          if (aid && c.withUser?.id) map.set(`${aid}:${c.withUser.id}`, c);
        }
      }
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qc, chatsCacheTick]);

  const attribQueries = useQueries({
    queries: detailTargets.map(({ aid, fanId }) => ({
      queryKey: ["money-rail-attrib", aid, fanId] as const,
      queryFn: () => relay.get<AttributionResponse>(
        `/admin/messages/${encodeURIComponent(aid)}/${fanId}/attribution?limit=1`,
      ),
      enabled: hydrated,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    })),
  });

  const chatSig = chatQueries.map((q) => q.dataUpdatedAt).join(",");
  const attribSig = attribQueries.map((q) => q.dataUpdatedAt).join(",");
  const replyStates = useMemo(() => {
    const map = new Map<string, ReplyState>();
    detailTargets.forEach((t, i) => {
      const key = `${t.aid}:${t.fanId}`;
      const detail = chatQueries[i]?.data ?? null;
      const cached = cachedChats.get(key) ?? null;
      const st = replyStateOf(detail, cached, t.aid, lastOutboundOf(attribQueries[i]?.data));
      if (st) map.set(key, st);
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatSig, attribSig, detailTargets, cachedChats]);

  // Rate-limited per fan: OF can echo the old lastMessage briefly after a send, so an unguarded invalidate would spin.
  const refreshedAtRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    if (!visible) return;
    const now = Date.now();
    // Iterate detailTargets, never parse the aid:fanId string: react-query hashes 12345 and "12345" differently, so rebuilt ids miss Fansly/OF keys.
    for (const { aid, fanId } of detailTargets) {
      const key = `${aid}:${fanId}`;
      const st = replyStates.get(key);
      if (!st?.stale) continue;
      const last = refreshedAtRef.current.get(key) ?? 0;
      if (now - last < DETAIL_REFRESH_MIN_GAP_MS) continue;
      refreshedAtRef.current.set(key, now);
      void qc.invalidateQueries({ queryKey: ["chat-detail", aid, fanId] });
      // The attribution row lands a beat after the optimistic patch; refetch or the previous message's automation_kind sticks.
      void qc.invalidateQueries({ queryKey: ["money-rail-attrib", aid, fanId] });
    }
  }, [replyStates, detailTargets, qc, visible]);

  const anyLoading = listQueries.some((q) => q.isLoading);

  return { targetAccountIds, merged, unseen, replyStates, placeholderAids, anyRefreshing, anyLoading };
}
