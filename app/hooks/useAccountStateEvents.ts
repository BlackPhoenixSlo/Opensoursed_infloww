"use client";


import { useEffect } from "react";
import { useQueryClient, type Query, type QueryClient, type QueryKey } from "@tanstack/react-query";
import {
  applyReadFlip, applyRestrictFlip, decodeChatsKey, freshestFanRow, isUnreadList, keyHoldsAccount, parseReadFlip,
  parseRestrictFlip, patchChatCaches, type ChatPages, type ReadFlip, type RestrictFlip,
} from "@/lib/chatsCache";
import { relayNow } from "@/lib/ageClock";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { ofUserFullKey, type OFUser } from "@/hooks/useOFUser";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";
import { resyncAction } from "@/lib/cellBusReducer";
import { cellMode } from "@/lib/cellFlag";
import { currentCellMap } from "@/lib/cellMap";
import { spliceCellHeads } from "@/hooks/useChatList";
import { armRead } from "@/lib/ofReadGate";
import { creatorFreshnessKey, dispatchCreatorFreshness } from "@/hooks/useCreatorFreshness";
import { badgeBehind, type CreatorFreshnessState } from "@/lib/creatorFreshness";
import { isUnreadChat } from "@/lib/chatUnread";
import { usePrincipalId } from "@/hooks/useEmployeeKey";

type Body = Record<string, unknown>;

const byAccount = (key: string, aid: string | undefined): QueryKey => (aid ? [key, aid] : [key]);

const KEYS: Record<string, (aid: string | undefined, body: Body) => QueryKey[]> = {
  // The chatter's own roster too (lib/chatterAccounts): a chatter's tabs show the Disconnected mark from it.
  session_dead: () => [["accounts"], ["chatter", "self", "accounts"], ["app-errors", "recent"]],
  agency_notifications: () => [["agency-notifications"]],  // the owner's centre (AgencyNotifications.tsx)
  account_active: () => [["accounts"], ["chatter"]],
  proxy_switched: () => [["proxies"], ["accounts"]],
  permissions_changed: () => [APPLIED_SETTINGS_KEY],
  assignment_changed: () => [["accounts"], ["chatter"], ["employees"]],
  scheduled_send_changed: (aid) => [byAccount("scheduled-sends", aid)],
  rule_run_finished: (aid, b) => [
    byAccount("automation-rules", aid),
    ["stats", "automation-runs"],
    ...(b.kind === "scheduled_send" ? [byAccount("scheduled-sends", aid)] : []),
    ...(b.kind === "full_ai_chat" ? [byAccount("full-ai-today", aid)] : []),
    ...(b.status === "error" ? [["app-errors", "recent"]] : []),
  ],
};

export const COALESCE_MS = 2_000;
const COALESCED = new Set(["rule_run_finished", "scheduled_send_changed"]);
export const RESYNC_MIN_MS = 30_000;
export const SALES_MIN_MS = 30_000;
const SALES_ROOTS = new Set<unknown>(["stats", "dashboard", "competitor"]);
const refetchedOnSale = (key: QueryKey) =>
  SALES_ROOTS.has(key[0]) && !(key[0] === "stats" && key[1] === "sales-records");

function throttle(fn: () => void, ms: number) {
  let last = -Infinity;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const run = () => { last = Date.now(); fn(); };
  return {
    call: () => {
      const wait = last + ms - Date.now();
      if (wait <= 0) return run();
      timer ??= setTimeout(() => { timer = null; run(); }, wait);
    },
    cancel: () => { if (timer) clearTimeout(timer); },
  };
}
interface WarmBody { notif_count?: number }

export type WarmMark = "write" | "must" | "unless" | "skip";

export function warmMark(
  s: { fetchStatus: string; dataUpdatedAt: number; errorUpdatedAt: number }, hasValue: boolean,
): WarmMark {
  if (s.fetchStatus === "fetching") return "must";
  if (hasValue) return "write";
  return s.dataUpdatedAt > 0 || s.errorUpdatedAt > 0 ? "unless" : "skip";
}

type FanFlipRecord = { at: number; generation: number };
type FlipRecord = { all: number; fans: Map<string, FanFlipRecord> };
const flipStamps = new WeakMap<QueryClient, Map<string, FlipRecord>>();

function takeFlip(qc: QueryClient, accountId: string, flip: ReadFlip, own: boolean): { skip: ReadonlySet<string>; record?: FanFlipRecord } | null {
  const byAccount = flipStamps.get(qc) ?? new Map<string, FlipRecord>();
  flipStamps.set(qc, byAccount);
  const rec: FlipRecord = byAccount.get(accountId) ?? { all: -Infinity, fans: new Map() };
  byAccount.set(accountId, rec);
  // This tab stamps its own write after the answer, later than the Relay's stamp: the Relay's echo records `at`.
  const at = own ? null : flip.at;
  if (at !== null && at < rec.all) return null;
  if (flip.fanId === null) {
    if (at !== null) rec.all = at;
    const skip = new Set<string>();
    for (const [fan, record] of rec.fans) {
      if (at !== null && record.at > at) skip.add(fan);
      else {
        record.generation++;
        if (at !== null || record.at === -Infinity) rec.fans.delete(fan);
      }
    }
    return { skip };
  }
  const fan = String(flip.fanId);
  const record = rec.fans.get(fan) ?? { at: -Infinity, generation: 0 };
  if (at !== null && at < record.at) return null;
  if (at !== null) record.at = at;
  record.generation++;
  rec.fans.set(fan, record);
  return { skip: new Set(), record };
}

function cachedFanRow(qc: QueryClient, accountId: string, fanId: FanId) {
  return freshestFanRow(qc.getQueryCache().findAll({ queryKey: ["chats"] })
    .filter((q) => keyHoldsAccount(decodeChatsKey(q.queryKey), accountId))
    .map((q) => q.state.data as ChatPages | undefined), accountId, fanId);
}

export function flipCachedReadState(
  qc: QueryClient, accountId: string, flip: ReadFlip, opts: { own?: boolean } = {},
): FanFlipRecord | undefined {
  const accepted = takeFlip(qc, accountId, flip, !!opts.own);
  if (!accepted) return undefined;
  const source = flip.unread && flip.fanId !== null ? cachedFanRow(qc, accountId, flip.fanId) : null;
  patchChatCaches(qc, accountId, (data, { key, observed, replay }) => applyReadFlip(data, accountId, flip, {
    unreadList: isUnreadList(key), keepRows: observed, source: replay ? null : source, skip: accepted.skip,
  }));
  return accepted.record;
}

export function optimisticRead(
  qc: QueryClient, accountId: string, fanId: FanId,
): { wasUnread: boolean; current(): boolean } {
  const source = cachedFanRow(qc, accountId, fanId);
  const record = flipCachedReadState(qc, accountId, { fanId, unread: false, at: relayNow() }, { own: true });
  const generation = record?.generation;
  return {
    wasUnread: source ? isUnreadChat(source) : false,
    current: () => record !== undefined && record.generation === generation,
  };
}

export function flipCachedRestrict(qc: QueryClient, accountId: string, flip: RestrictFlip): void {
  patchChatCaches(qc, accountId, (data) => applyRestrictFlip(data, accountId, flip));
  const fanId = fanIdFromParam(String(flip.fanId));
  if (fanId != null) {
    qc.setQueryData<OFUser>(ofUserFullKey(accountId, fanId), (u) =>
      u && !!u.isRestricted !== flip.restricted ? { ...u, isRestricted: flip.restricted } : u);
  }
  void qc.invalidateQueries({ queryKey: ["automation-restrict", accountId] });
}

const ACCOUNTS_LISTS: QueryKey[] = [["accounts"], ["chatter", "self", "accounts"]];

const placedAccounts = () => new Set(currentCellMap()?.accounts.map((a) => a.account_id));

const SSE_POLLED: QueryKey[] = [
  ["scheduled-sends"], ["automation-rules"], ["stats", "automation-runs"],
  ["app-errors", "recent"], ["roster-counts"], ["full-ai-today"],
];

export function useAccountStateEvents(): void {
  const qc = useQueryClient();
  const principalId = usePrincipalId();
  useEffect(() => {
    const offs = [
      eventBus.on("creator_refreshed", (e: EventEnvelope) => {
        dispatchCreatorFreshness(qc, principalId, { type: "refreshed", body: e.creator_refreshed, receivedAt: Date.now() });
      }),
      eventBus.on("ping", (e: EventEnvelope) => {
        const fresh = e.fresh as Record<string, number>;
        const now = typeof e.ts === "number" ? Math.round(e.ts * 1000) : NaN;
        dispatchCreatorFreshness(qc, principalId, { type: "confirmed", fresh, now, receivedAt: Date.now() });
        if (badgeBehind(qc.getQueryData<CreatorFreshnessState>(creatorFreshnessKey(principalId)), e.badge).length) {
          for (const queryKey of ACCOUNTS_LISTS) void qc.invalidateQueries({ queryKey });
        }
      }),
    ];
    return () => offs.forEach((off) => off());
  }, [qc, principalId]);
  useEffect(() => {
    const invalidate = (keys: QueryKey[]) => {
      for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
    };

    const pending = new Map<string, QueryKey>();
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const coalesce = (keys: QueryKey[]) => {
      for (const k of keys) pending.set(JSON.stringify(k), k);
      flushTimer ??= setTimeout(() => {
        flushTimer = null;
        const keys = [...pending.values()];
        pending.clear();
        invalidate(keys);
      }, COALESCE_MS);
    };

    const offs = Object.entries(KEYS).map(([type, keysFor]) =>
      eventBus.on(type, (e: EventEnvelope) => {
        const keys = keysFor(e.__account_id, (e[type] ?? {}) as Body);
        if (COALESCED.has(type)) coalesce(keys);
        else invalidate(keys);
      }),
    );

    const cache = qc.getQueryCache();
    const warmPending = new Map<string, { queryKey: QueryKey; must: boolean }>();
    let warmTimer: ReturnType<typeof setTimeout> | null = null;
    const markWarm = (q: Query, must: boolean) => {
      const had = warmPending.get(q.queryHash);
      warmPending.set(q.queryHash, { queryKey: q.queryKey, must: must || !!had?.must });
      warmTimer ??= setTimeout(() => {
        warmTimer = null;
        const due = [...warmPending.values()];
        warmPending.clear();
        for (const { queryKey } of due) void qc.invalidateQueries({ queryKey, exact: true });
      }, COALESCE_MS);
    };
    offs.push(cache.subscribe((ev) => {
      if (ev.type !== "updated") return;
      const p = warmPending.get(ev.query.queryHash);
      const a = ev.action;
      if (!p || !((a.type === "success" && !a.manual) || a.type === "error")) return;
      if (p.must) p.must = false;
      else warmPending.delete(ev.query.queryHash);
    }));
    const onWarmed = (e: EventEnvelope) => {
      const aid = e.__account_id;
      if (!aid) return;
      const b = (e.creator_warmed ?? {}) as WarmBody;
      const count = typeof b.notif_count === "number" ? b.notif_count : null;
      const own = [...cache.findAll({ queryKey: ["of-notif-count", aid] }), ...cache.findAll({ queryKey: ["notif-list", aid] })];
      for (const q of own) {
        const mark = warmMark(q.state, q.queryKey[0] === "of-notif-count" && count !== null);
        if (mark === "write") {
          qc.setQueryData(q.queryKey, count);
          warmPending.delete(q.queryHash);
        } else if (mark !== "skip") markWarm(q, mark === "must");
      }
    };
    // Written, then armed: a count written into an unarmed reader's empty entry is that reader's first read.
    offs.push(eventBus.on("creator_warmed", (e: EventEnvelope) => { onWarmed(e); armRead(e.__account_id); }));

    offs.push(eventBus.on("chat_read_changed", (e: EventEnvelope) => {
      const flip = parseReadFlip(e.chat_read_changed);
      if (e.__account_id && flip) flipCachedReadState(qc, e.__account_id, flip);
    }));

    offs.push(eventBus.on("chat_restrict_changed", (e: EventEnvelope) => {
      const flip = parseRestrictFlip(e.chat_restrict_changed);
      if (e.__account_id && flip) flipCachedRestrict(qc, e.__account_id, flip);
    }));

    const resync = throttle(() => void invalidateVaultQueries(qc), RESYNC_MIN_MS);
    let cellResynced = new Set<string>();
    let controlResynced = false;
    const cellResync = throttle(() => {
      const placed = placedAccounts();
      const accounts = cellResynced;
      const control = controlResynced;
      cellResynced = new Set();
      controlResynced = false;
      const hit = (q: Query) => (control && resyncAction(q.queryKey, new Set(), placed) === "invalidate")
        || (accounts.size > 0 && resyncAction(q.queryKey, accounts, placed) === "invalidate");
      void invalidateVaultQueries(qc, { predicate: hit });
      if (accounts.size) void spliceCellHeads(qc, accounts, placed);
    }, RESYNC_MIN_MS);
    offs.push(eventBus.on("resync", (e: EventEnvelope) => {
      if (!Array.isArray(e.accounts)) return resync.call();
      if (!e.accounts.length) controlResynced = true;
      for (const id of e.accounts) cellResynced.add(String(id));
      cellResync.call();
    }), resync.cancel, cellResync.cancel);

    const sale = throttle(
      () => void qc.invalidateQueries({ predicate: (q) => refetchedOnSale(q.queryKey) }), SALES_MIN_MS);
    offs.push(eventBus.on("transaction_recorded", sale.call), sale.cancel);

    const was = new Map<string, boolean>();
    offs.push(eventBus.onStreamState(({ connected, accounts }) => {
      if (accounts === null) return;
      const id = accounts.join(",");
      const placed = placedAccounts();
      const named = new Set(accounts);
      const mine = (roots: QueryKey[]) => (q: Query) => roots.some((r) => r.every((p, i) => q.queryKey[i] === p))
        && resyncAction(q.queryKey, named, placed) === "invalidate";
      if (was.get(id) && !connected && !eventBus.isPaused()) void qc.invalidateQueries({ predicate: mine(SSE_POLLED) });
      was.set(id, connected);
    }));

    let wasConnected = false;
    let dropped = false;
    offs.push(eventBus.onStateChange((connected) => {
      if (cellMode()) return;
      if (wasConnected && !connected && !eventBus.isPaused()) {
        invalidate(SSE_POLLED);
        dropped = true;
      }
      if (connected && dropped) {
        invalidate([["roster-counts"]]);
        dropped = false;
      }
      wasConnected = connected;
    }));

    return () => {
      offs.forEach((off) => off());
      if (flushTimer) clearTimeout(flushTimer);
      if (warmTimer) clearTimeout(warmTimer);
    };
  }, [qc]);
}
