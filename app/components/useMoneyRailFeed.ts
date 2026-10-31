"use client";

/**
 * useMoneyRailFeed — the Buys & tips rail's data (`MoneyRail`): OF's money
 * lists per account × type (cold-started from the localStorage snapshot),
 * merged with the notif-history mirror, the not-yet-seen count, and each
 * visible payer's reply state from the per-fan chat detail, the inbox's
 * chat-list cache and our own attribution rows.
 *
 * OF CALL BUDGET (20 Creators = 40 lists): SSE keeps the lists live — the
 * toaster seeds each tip/sale straight into them (`seedMoneyList`) — so OF's
 * feed is only re-read to reconcile: on mount or tab return once a list is
 * LIST_STALE_MS old, every LIST_SAFETY_POLL_MS while the tab is visible, and
 * on `resync` (useAccountStateEvents). No SSE arrival (DM, like, tip) refetches
 * a list. A hidden tab (or an idle one, useIdleMode) pays nothing: it skips
 * the safety poll and defers its SSE-driven re-renders and chat-detail
 * refreshes to one catch-up on return.
 *
 * COLD START: a page refresh wipes the react-query cache, and each model's
 * OF fan-out lands at its own pace — so every successful fetch is mirrored
 * into a localStorage snapshot, and the next mount shows those rows
 * immediately (dimmed) while each model revalidates independently. The rail
 * never blanks back to "Loading…" just because the tab reloaded.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { focusManager, useQueries, useQueryClient } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { compareFanIds, type FanId, sameUserId } from "@/lib/fanId";
import { stripHtmlPreview } from "@/lib/htmlPreview";
import type { AttributionEntry, AttributionResponse } from "@/hooks/useChatAttribution";
import {
  mapOfTypeToKey,
  readNotifHistory,
  type CachedNotification,
  type NotifTypeKey,
} from "@/lib/notifSettings";
import { MONEY_ROWS_CAP, MONEY_TYPES, isMoney, notifPath, parseList, type MoneyTypeKey } from "@/lib/notifText";
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

/** How deep we fetch chat detail (last text + seen state): what's visible plus
 *  a little lookahead, since the window scrolls. One OF roundtrip per fan, so
 *  it's hard-capped — rows past it render without the status line. */
const DETAIL_ROWS_LOOKAHEAD = 3;
const DETAIL_ROWS_MAX = 12;
/** Floor between two forced re-fetches of the same fan's chat detail. */
const DETAIL_REFRESH_MIN_GAP_MS = 10_000;
/** A money list older than this is re-read from OF on mount / tab return.
 *  Long, because SSE seeds every sale into it in between (OF CALL BUDGET). */
const LIST_STALE_MS = 5 * 60_000;
/** Safety re-read of every list while the tab is visible — catches a row the
 *  SSE path missed. react-query skips the tick in a hidden or idle tab. */
const LIST_SAFETY_POLL_MS = 10 * 60_000;

export interface MergedItem {
  n: NotificationItem;
  accountId: string;
  typeKey: NotifTypeKey;
  ts: number;
}

/** Where the conversation with this payer stands right now.
 *  `outbound` = WE spoke last, so nobody owes the fan anything. */
export interface ReplyState {
  text: string;
  outbound: boolean;
  /** Outbound only: the fan's lastReadMessageId has reached our last msg. */
  seen: boolean;
  /** Inbound only: their message is still unread by us. */
  unread: boolean;
  /** Outbound only: an automation sent it, not a person. The thread still
   *  wants a human, so it keeps the orange dot. */
  byBot: boolean;
  /** The chat-list cache knows a message the detail fetch hasn't seen yet
   *  (we just sent, or one just arrived over SSE) — so the detail fetch,
   *  and with it the read receipt, is behind. The feed refetches it. */
  stale: boolean;
}

/** The newest outbound row from the attribution endpoint. `automationKind`
 *  is null when a human chatter sent it. */
export function lastOutboundOf(
  resp: AttributionResponse | undefined,
): { messageId: FanId; automationKind: string | null } | null {
  const entries = Object.entries(resp?.by_msg_id ?? {});
  if (entries.length === 0) return null;
  // limit=1, but don't depend on that — take the highest id.
  //
  // The id stays the exact key text. `Number(id)` rounded every Fansly
  // snowflake (900805852249276416 -> ...400), and the rounded value was then
  // `===`-compared against the wire's string id below — a comparison that is
  // false for BOTH reasons at once, so `byBot` never fired on Fansly and the
  // rail could not tell a bot's reply from a chatter's.
  let best: { messageId: FanId; automationKind: string | null } | null = null;
  for (const [id, entry] of entries) {
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

/** Derive the seen / owes-a-reply state for one fan. Mirrors the inbox's
 *  rule: a `lastMessage.fromUser.id` that isn't ours means the FAN spoke last
 *  and we owe them a reply (the orange dot), and `lastReadMessageId >=
 *  lastMessage.id` means they read what we sent (the blue ✓✓).
 *
 *  Two sources, neither one sufficient:
 *    • `detail`  — the per-fan /chats/{id} fetch. Authoritative ids and the
 *      read receipt, but up to 60s stale.
 *    • `cached`  — the inbox chat-list row. Patched OPTIMISTICALLY on send
 *      and on SSE arrival, so it's the only source that reflects a message
 *      sent seconds ago — but that patch reuses the previous `lastMessage.id`
 *      (useSendMessage), so its id cannot be trusted for the receipt compare.
 *
 *  So: newest `createdAt` wins for the text, and a message newer than the
 *  detail fetch is by definition not yet seen (the receipt can't have caught
 *  up), which also avoids reading the stale optimistic id. Returns null for
 *  an empty thread. */
export function replyStateOf(
  detail: OFChatItem | null,
  cached: OFChatItem | null,
  accountId: string,
  lastOutbound: { messageId: FanId; automationKind: string | null } | null = null,
): ReplyState | null {
  const dLm = detail?.lastMessage ?? null;
  const cLm = cached?.lastMessage ?? null;
  // Strictly newer, so a tie keeps the trustworthy detail row.
  const cacheIsNewer = !!cLm && msgTs(cLm) > msgTs(dLm);
  const lm = cacheIsNewer ? cLm : (dLm ?? cLm);
  if (!lm) return null;

  // Receipts only move forward, so the higher of the two is the truth.
  //
  // Ordered with compareFanIds, NOT Math.max: a receipt id is a snowflake on
  // Fansly, and Math.max forces it through float64 (…416 -> …400) before it is
  // compared against the message id. Fansly sends no receipts yet, which is the
  // only reason this never showed as a wrong ✓✓ — it would have the day they do.
  const lastReadCandidates = [detail?.lastReadMessageId, cached?.lastReadMessageId]
    .filter((v): v is NonNullable<typeof v> => v != null && String(v) !== "0");
  const lastRead: FanId | null = lastReadCandidates.length
    ? lastReadCandidates.reduce((a, b) => (compareFanIds(a, b) >= 0 ? a : b))
    : null;
  // String-normalized compare: a Fansly `fromUser.id` is a string snowflake,
  // so `Number(accountId)` never matched it and every answered thread still
  // reported "they spoke last" (orange dot).
  const outbound = sameUserId(lm.fromUser?.id, accountId);
  const text = lm.text?.trim()
    ? stripHtmlPreview(lm.text, 60)
    : lm.mediaCount
      ? `(${lm.mediaCount} media)`
      : "";
  // `stale` only when the detail fetch actually exists and is behind — a fan
  // the detail fetch hasn't loaded at all isn't stale, just uncovered.
  const stale = cacheIsNewer && !!dLm;

  // An automation answering doesn't discharge the thread — only a person
  // does. We can only claim "a bot sent it" when the attribution row we have
  // is FOR this exact message; if the ids don't line up (the send hasn't been
  // written to our DB yet, i.e. `stale`), stay silent rather than flash a
  // false orange dot at a chatter who just replied.
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

/** The fan who paid for a row (OF puts him in `user`, older rows `fromUser`). */
export function payerIdOf(m: MergedItem): FanId | undefined {
  return m.n.user?.id ?? m.n.fromUser?.id;
}

/** The distinct payers of `rows`, in row order (newest money first), one per
 *  account × fan; rows with no payer are skipped. Stops at `cap`. */
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

/** The rail's rows: every row of OF's money lists, plus each money row of the
 *  notif-history mirror (for `accountIds`) that no list row of its account
 *  already carries by id — the mirror holds SSE arrivals OF hasn't listed
 *  yet. Newest first (ties keep list order, then the mirror's), at most
 *  MONEY_ROWS_CAP. */
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

/** Whether this tab is visible (and not idle) — react-query's own focus
 *  signal, so it agrees with when the lists' polls run. */
function useTabVisible(): boolean {
  const [visible, setVisible] = useState(() => focusManager.isFocused());
  useEffect(() => focusManager.subscribe(setVisible), []);
  return visible;
}

interface StoredFeed {
  /** Last session's fetched rows, served as query placeholders below. After
   *  the first real fetches land, it's inert. */
  snapshot: SnapshotMap;
  /** Timestamp of the newest money row the user has actually had on screen. */
  seenTs: number;
  /** Both have been read from localStorage (client only); gates every fetch,
   *  so the queries enable together with their placeholders. */
  hydrated: boolean;
}

/** The panel's feed. `open` picks how many rows are on screen (bigRows /
 *  smallRows), which decides how deep the chat detail goes and whether the
 *  seen watermark may advance. */
export function useMoneyRailFeed({
  settings,
  activeAccounts,
  open,
}: {
  settings: RailSettings;
  activeAccounts: readonly { id: string }[];
  open: boolean;
}) {
  // The snapshot and the watermark are global (not per surface), so they are
  // read once per mount.
  const [stored, setStored] = useState<StoredFeed>({ snapshot: {}, seenTs: 0, hydrated: false });
  const { snapshot, seenTs, hydrated } = stored;
  useEffect(() => {
    // First-ever use: nothing that predates the rail counts as "new" — a
    // fresh install greeting the user with "50 new" is noise, not signal.
    let seen = readSeenTs();
    if (!seen) {
      seen = Date.now();
      writeSeenTs(seen);
    }
    setStored({ snapshot: readMoneySnapshot(), seenTs: seen, hydrated: true });
  }, []);
  
  // NOTE: no useScope() here, by design. The rail watches every active model
  // by default even when the rest of the UI is scoped to one — money landing
  // on another model is exactly what you don't want to miss. Narrow it in the
  // rail's own settings if you really only care about a subset.
  const targetAccountIds = useMemo<string[]>(
    () => resolveRailAccounts(settings, activeAccounts),
    [settings, activeAccounts],
  );

  // Re-render whenever the SSE toaster mirrors a new arrival into the
  // localStorage history (same-tab custom event + cross-tab storage event).
  // That fires per DM in EVERY tab, so a hidden tab only notes it and
  // catches up once on return (with the chats-cache tick below).
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
      // Another tab saw the rows — this tab's "new" badge clears too.
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

  // OF fan-out — one query per account × money type. Gated only on hydration
  // (the snapshot is a localStorage read); the surface question was
  // already answered by MoneyRail, or this panel wouldn't exist. Deliberately
  // NOT gated on `open` either: a COLLAPSED rail still renders `smallRows`
  // live rows. Query keys intentionally match the bell's so both share one
  // cache entry per (account, type).
  const queryDefs = useMemo(
    () => targetAccountIds.flatMap((aid) => MONEY_TYPES.map((type) => ({ aid, type }))),
    [targetAccountIds],
  );
  const listQueries = useQueries({
    queries: queryDefs.map(({ aid, type }) => ({
      queryKey: ["notif-list", aid, type] as const,
      queryFn: async () => parseList(await relay.get(notifPath(type), { accountId: aid })),
      enabled: hydrated,
      // OF CALL BUDGET (header): SSE keeps these live; OF is
      // re-read on return to a hidden tab only past LIST_STALE_MS.
      staleTime: LIST_STALE_MS,
      refetchOnWindowFocus: true,
      refetchInterval: LIST_SAFETY_POLL_MS,
      // Cold start: show this account's rows from the last session at once
      // (dimmed) while the real fetch runs, instead of blanking the rail.
      placeholderData: () => snapshot[snapshotKeyOf(aid, type)]?.items,
    })),
  });

  const dataSig = listQueries.map((q) => q.dataUpdatedAt).join(",");

  // Mirror every real fetch into the snapshot for the NEXT page load.
  // Read-merge-write so accounts outside the current pick keep their rows.
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

  // Accounts still on placeholder rows — their fetch hasn't landed yet, so
  // their rows render dimmed until it does. Not memoised: trivially cheap,
  // and listQueries is a fresh array every render anyway.
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
    // `snapshot` is a dep because placeholder rows surface through q.data
    // WITHOUT touching dataUpdatedAt — when the snapshot loads on mount,
    // nothing else here changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dataSig, queryDefs, targetAccountIds, historyTick, snapshot],
  );

  // Header count of not-yet-seen sales. The watermark advances only while
  // rows are actually rendered (≥1 visible row on a shown surface) — a
  // bar-only dock or a hidden surface lets it climb instead. Scrolling depth
  // is deliberately ignored: rows-on-screen counts as seen.
  const unseen = unseenCountOf(merged, seenTs);
  useEffect(() => {
    if (!hydrated || merged.length === 0) return;
    if ((open ? settings.bigRows : settings.smallRows) === 0) return;
    const newest = merged[0]?.ts ?? 0; // merged is sorted newest-first
    if (newest > seenTs) {
      writeSeenTs(newest);
      setStored((s) => ({ ...s, seenTs: newest }));
    }
  }, [hydrated, merged, open, settings, seenTs]);

  // ── Per-fan chat detail: the last message in the thread + whether the
  // fan has read it. OF's /chats/{fanId} carries `lastMessage` and
  // `lastReadMessageId` (the highest message id the fan marked read) —
  // the same pair the inbox uses for its ✓✓ / awaiting-reply markers.
  // Only for the rows we actually render, deduped by fan.
  const detailTargets = useMemo(() => {
    // Fetch a little past what's visible (the window scrolls), but never for
    // all 50 — each row is an OF roundtrip. At 0 collapsed rows this still
    // pre-warms the lookahead, so expanding doesn't start from nothing.
    const want = (open ? settings.bigRows : settings.smallRows) + DETAIL_ROWS_LOOKAHEAD;
    return distinctPayers(merged.slice(0, Math.min(want, DETAIL_ROWS_MAX)))
      .map(({ accountId, fanId }) => ({ aid: accountId, fanId }));
  }, [merged, open, settings.bigRows, settings.smallRows]);

  const chatQueries = useQueries({
    queries: detailTargets.map(({ aid, fanId }) => ({
      queryKey: ["chat-detail", aid, fanId] as const,
      // 'background': up to DETAIL_ROWS_MAX (12) OF calls per account, re-fired
      // on every SSE money event. Nobody is waiting on the rail's read-receipt
      // ticks, and at 'user' priority this fan-out crowds out the actual click
      // in the relay's per-account lane.
      queryFn: () => relay.get<OFChatItem>(
        `/api/of/v2/chats/${fanId}`, { accountId: aid, priority: "background" },
      ),
      enabled: hydrated,
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    })),
  });

  // The inbox's chat-list rows are the source we KNOW carries
  // `lastReadMessageId` (ChatSurface drives its ✓✓ off exactly this). When
  // the inbox is loaded these rows are free and already fresh, so we prefer
  // them for the read receipt and fall back to the per-fan detail fetch.
  const qc = useQueryClient();
  const [chatsCacheTick, setChatsCacheTick] = useState(0);
  useEffect(() => qc.getQueryCache().subscribe((e) => {
    if (e.query.queryKey?.[0] === "chats" && e.type === "updated") {
      if (!focusManager.isFocused()) { missedWhileHiddenRef.current = true; return; }
      queueMicrotask(() => setChatsCacheTick((t) => t + 1));
    }
  }), [qc]);

  // Back on screen: one catch-up for everything a hidden tab skipped.
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

  // Who sent the last outbound message — a chatter or an automation. Served
  // from our own SQLite (no OF roundtrip): `automation_kind` is stamped on
  // every bot send and is null for a human. limit=1 gives just the newest
  // outbound row, which is all the rail needs.
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

  // When the chat-list cache shows a message the detail fetch doesn't know
  // about (we just sent one, or SSE delivered one), the detail row — and so
  // the read receipt — is behind. Pull it again. Rate-limited per fan because
  // OF can keep echoing the old lastMessage for a beat after a send, and an
  // unguarded invalidate-on-stale would spin.
  const refreshedAtRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    // A hidden tab spends no OF calls on read receipts nobody can see; this
    // re-runs on return (`visible` is a dep).
    if (!visible) return;
    const now = Date.now();
    // Iterate the TARGETS, not the string keys. The id is never reconstructed
    // from text here: `detailTargets` already holds the exact `{aid, fanId}`
    // the queries above were keyed with, so invalidation matches by
    // construction on both platforms. Round-tripping through the `aid:fanId`
    // string cannot do that — react-query hashes 12345 and "12345" to
    // different keys, so parsing the half back with `Number()` missed every
    // Fansly snowflake, and returning it as text missed every numeric
    // OnlyFans id. Either way the stale-detail refresh silently never fired
    // and the read-receipt tick + attribution dot stayed stale.
    for (const { aid, fanId } of detailTargets) {
      const key = `${aid}:${fanId}`;
      const st = replyStates.get(key);
      if (!st?.stale) continue;
      const last = refreshedAtRef.current.get(key) ?? 0;
      if (now - last < DETAIL_REFRESH_MIN_GAP_MS) continue;
      refreshedAtRef.current.set(key, now);
      void qc.invalidateQueries({ queryKey: ["chat-detail", aid, fanId] });
      // The attribution row for a just-sent message is written when OF echoes
      // it, so it lands a beat after the optimistic patch. Refetch it too, or
      // a chatter's reply keeps the bot's `automation_kind` from the previous
      // message and the dot never clears.
      void qc.invalidateQueries({ queryKey: ["money-rail-attrib", aid, fanId] });
    }
  }, [replyStates, detailTargets, qc, visible]);

  const anyLoading = listQueries.some((q) => q.isLoading);

  return { targetAccountIds, merged, unseen, replyStates, placeholderAids, anyRefreshing, anyLoading };
}
