"use client";

/**
 * useRosterCounts — per-model inbox badge counts for the left roster strip.
 *
 *   • unread    → number of CONVERSATIONS with unread messages (blue badge:
 *                 fans waiting to be read).
 *   • owe_reply → conversations READ but the fan spoke last, i.e. we owe a
 *                 reply (orange badge: seen, not yet answered).
 *
 * Backed by GET /admin/accounts/roster-counts, scoped to the signed-in
 * principal. Both principals get badges: an owner sees its own models, a
 * chatter sees the union across every linked owner (the same set its roster
 * strip already renders). SSE patches badges live; polls every 5 min (60s
 * while SSE is down).
 */

import { useCallback } from "react";
import { useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay, type OFChatItem } from "@/lib/relay";
import { useOptionalUser } from "@/contexts/UserContext";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { usePrincipalId } from "@/hooks/useEmployeeKey";

export interface RosterCount {
  unread: number;
  owe_reply: number;
  /** The relay's 25-chat window was full and all unread: more unread chats may sit past it, so the badge says
   *  "N+". Absent: `unread` is the whole count. `unread` stays the number (it sorts the tabs). */
  unread_capped?: boolean;
  /** Epoch ms of the chats window the server folded this from (0: unknown). An Idle Creator's count can be old
   *  (ADR-0031: no OF read unless leased), so a local patch newer than it wins. */
  as_of?: number;
}

export interface RosterCountsResp {
  counts: Record<string, RosterCount>;
  /** The server's epoch ms when it answered: the tab's clock skew is measured off it, so `as_of` (server clock)
   *  and local patch stamps (this tab's clock) compare in one clock. */
  now?: number;
}

const EMPTY: Record<string, RosterCount> = {};

/** Per-principal cache key. An owner's counts must never bleed into a chatter's
 *  view (or vice-versa) on an identity switch in the same browser. */
export function rosterCountsKey(principalId: string): readonly [string, string] {
  return ["roster-counts", principalId] as const;
}

export function useRosterCounts(): Record<string, RosterCount> {
  return useRosterCountsRead().counts;
}

/** The counts, and whether their first read is over (answered, failed, or
 *  never asked: no principal) — before it, every count reads 0. */
export function useRosterCountsRead(): { counts: Record<string, RosterCount>; settled: boolean } {
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  const principalId = usePrincipalId();
  const qc = useQueryClient();

  const q = useQuery<RosterCountsResp>({
    queryKey: rosterCountsKey(principalId),
    queryFn: async () => {
      const key = rosterCountsKey(principalId);
      // Stamp BEFORE the network read: any optimistic patchLocal that lands
      // while this poll is in flight stamps a LATER time, and mergeRosterCounts
      // then keeps the fresher local value instead of letting this (now stale)
      // server snapshot clobber it. Without this, removing the per-message
      // refreshOne — which used to cancelQueries the in-flight poll — would let
      // the 60s poll revert an instant badge back to a pre-event count.
      const fetchStartedAt = Date.now();
      const resp = await relay.get<RosterCountsResp>("/admin/accounts/roster-counts");
      // No answer cached yet: a warm's counts that came while this read was in flight (seedWarmedRosterCount).
      const prev = qc.getQueryData<RosterCountsResp>(key) ?? takeWarmSeed(JSON.stringify(key));
      return mergeRosterCounts(
        resp,
        prev,
        fetchStartedAt,
        (aid) => lastLocalPatchAt.get(`${principalId}:${aid}`) ?? 0,
      );
    },
    enabled: !!user || !!chatter,
    refetchInterval: ssePoll(5 * 60_000, 60_000), // SSE: rosterDelta patches badges live
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  return { counts: q.data?.counts ?? EMPTY, settled: !q.isPending || q.fetchStatus === "idle" };
}

/** Per-account cooldown (ms) so re-hovering / mass-send bursts don't fire a live
 *  OF re-read every time. The 60s poll is the slow reconcile; this is the fast
 *  one, and it only needs to run once per interaction cluster. */
const REFRESH_COOLDOWN_MS = 8_000;

// MODULE scope, not per-hook: the cooldown + in-flight coalescing must be SHARED
// across every useRosterCountActions() instance (roster strip, chat surface,
// realtime hook). Per-instance state would let a hover AND a read AND a WS event
// on the same model each fire their own OF re-read inside the window, and would
// let an older targeted refresh resolve after a newer one and overwrite the
// fresher badge. Keyed by `${principalId}:${accountId}`. Bounded by account count.
const lastRefreshAt = new Map<string, number>();
const inFlightRefresh = new Map<string, Promise<void>>();
// Last time an OPTIMISTIC local patch (e.g. a read dropping unread) rewrote a
// model's badge. A targeted refresh started BEFORE that patch read OF's pre-patch
// state, so if it resolves afterward it must NOT blindly overwrite the newer
// optimistic value — it would revert the badge. Latest-wins: refreshOne skips its
// write when a local patch landed after the refresh began. Keyed principalId:accountId.
const lastLocalPatchAt = new Map<string, number>();

/** Tests only: forget the module's refresh cooldowns, in-flight refreshes
 *  and local-patch stamps, so one case's refresh cannot swallow the next's. */
export function resetRosterCountsModuleState() {
  warmSeeds.clear();
  lastRefreshAt.clear();
  inFlightRefresh.clear();
  lastLocalPatchAt.clear();
}

/** A conversation's PRIOR state, distilled from its chat-list row, in the two
 *  dimensions the roster badge cares about. */
export interface RosterPrior {
  /** Had unread fan messages (blue) before this event. */
  wasUnread: boolean;
  /** The fan spoke last while the chat was READ (orange "owe reply"). Only
   *  meaningful when !wasUnread — an unread chat is blue, never orange. */
  fanSpokeLast: boolean;
}

export interface RosterDelta {
  dUnread: number;
  dOwe: number;
}

/** Pure: the per-model badge delta for ONE message, given the fan conversation's
 *  PRIOR state and the message direction. CONVERSATION-count semantics — a chat
 *  contributes at most 1 to unread OR owe_reply, so a burst of messages to the
 *  same chat only moves the badge on the FIRST state transition (dedupe). */
export function rosterDelta(isOutbound: boolean, prior: RosterPrior): RosterDelta {
  const { wasUnread, fanSpokeLast } = prior;
  if (isOutbound) {
    // We replied → the conversation is answered.
    //  • was unread (blue)     → clear blue (mirrors the server zeroing unread on
    //    an outbound reply + useSendMessage's optimistic row flip).
    //  • was owe_reply (orange) → clear orange.
    //  • was caught-up          → nothing to move.
    if (wasUnread) return { dUnread: -1, dOwe: 0 };
    if (fanSpokeLast) return { dUnread: 0, dOwe: -1 };
    return { dUnread: 0, dOwe: 0 };
  }
  // Inbound (the fan spoke).
  //  • already unread → still one unread conversation, no change (dedupe).
  //  • was owe_reply (orange) → becomes unread (blue): +blue, -orange.
  //  • was caught-up          → becomes unread (blue).
  if (wasUnread) return { dUnread: 0, dOwe: 0 };
  if (fanSpokeLast) return { dUnread: 1, dOwe: -1 };
  return { dUnread: 1, dOwe: 0 };
}

/** Pure: apply a delta to a count, clamped at zero so a duplicate/stale event
 *  can never drive a badge negative. */
export function applyRosterDelta(cur: RosterCount, d: RosterDelta): RosterCount {
  return {
    unread: Math.max(0, cur.unread + d.dUnread),
    owe_reply: Math.max(0, cur.owe_reply + d.dOwe),
    // A local patch never learns what sits past the window: the "may be more" stays.
    ...(cur.unread_capped ? { unread_capped: true } : {}),
  };
}

/** Pure: distill a chat-list row into the roster-relevant prior state. Returns
 *  null when there's no row (caller then falls back to an authoritative re-read).
 *  `fanSpokeLast` = the last message's author is the fan, not us. */
export function rosterPriorFromRow(row: OFChatItem | null | undefined): RosterPrior | null {
  if (!row) return null;
  const wasUnread = (row.unreadMessagesCount ?? 0) > 0 || row.hasUnread === true;
  const lastFrom = row.lastMessage?.fromUser?.id;
  const fanSpokeLast =
    lastFrom != null && String(lastFrom) === String(row.withUser?.id);
  return { wasUnread, fanSpokeLast };
}

// A warm's counts (`creator_warmed`) for a roster read that has no answer yet: its first answer merges over them
// (a newer `as_of` kept), so the warm needs no re-read. Keyed by the query hash; taken by that read.
const warmSeeds = new Map<string, Record<string, RosterCount>>();

export function takeWarmSeed(hash: string): RosterCountsResp | undefined {
  const seed = warmSeeds.get(hash);
  warmSeeds.delete(hash);
  return seed ? { counts: seed } : undefined;
}

/** A warm's count for one Creator (`creator_warmed` carries it: the relay's `roster_count` entry, with `as_of`),
 *  written into one cached roster answer instead of re-reading it. Kept out when the cached count is as new
 *  (`as_of`) or a local patch is newer (mergeRosterCounts; `serverNow` is the event's epoch ms, `receivedAt` this
 *  tab's clock when it came). No answer cached yet (its first read in flight): seeded for that read instead. */
export function writeWarmedRosterCount(
  qc: QueryClient, queryKey: QueryKey, accountId: string, count: RosterCount, serverNow: number | undefined,
  receivedAt: number,
): void {
  const prev = qc.getQueryData<RosterCountsResp>(queryKey);
  if (!prev) {
    const hash = JSON.stringify(queryKey);
    warmSeeds.set(hash, { ...warmSeeds.get(hash), [accountId]: count });
    return;
  }
  const cur = prev.counts?.[accountId];
  if (cur?.as_of && count.as_of && cur.as_of >= count.as_of) return;
  const principalId = String(queryKey[1]);
  qc.setQueryData<RosterCountsResp>(queryKey, mergeRosterCounts(
    { counts: { [accountId]: count }, now: serverNow }, prev, receivedAt,
    (aid) => lastLocalPatchAt.get(`${principalId}:${aid}`) ?? 0,
  ));
}

/** Pure: fold a fresh server roster response over the currently-cached one,
 *  PRESERVING any per-account value that a local patch (optimistic or SSE) rewrote
 *  after the server's snapshot. `patchedAt(aid)` returns an account's last local-patch
 *  timestamp (this tab's clock). A server count's `as_of` (when its chats window was
 *  read, server clock) is that snapshot's time, moved into this tab's clock by the
 *  skew `server.now - fetchStartedAt` (no `now`: no skew; `now` is stamped at or after the
 *  read began, so transit only ever moves the snapshot earlier: a patch is kept, never
 *  dropped); without an `as_of`, `fetchStartedAt` (when this poll began its network read). An account patched AFTER
 *  it keeps its local value, so an Idle Creator's held, older count never jumps a live
 *  badge back. An account the server left out (an Idle Creator it holds nothing for,
 *  e.g. after a Relay restart) keeps its cached value, and so does one whose cached
 *  count has a newer `as_of` (a warm's that came while this read was in flight). */
export function mergeRosterCounts(
  server: RosterCountsResp | undefined,
  prev: RosterCountsResp | undefined,
  fetchStartedAt: number,
  patchedAt: (accountId: string) => number,
): RosterCountsResp {
  const serverCounts = server?.counts ?? {};
  const prevCounts = prev?.counts ?? {};
  const skew = server?.now ? server.now - fetchStartedAt : 0;
  const out: Record<string, RosterCount> = { ...serverCounts };
  for (const aid of Object.keys(prevCounts)) {
    const fresh = serverCounts[aid];
    const held = prevCounts[aid];
    if (!fresh || patchedAt(aid) > (fresh.as_of ? fresh.as_of - skew : fetchStartedAt)
      || (fresh.as_of && held.as_of && held.as_of > fresh.as_of)) out[aid] = held;
  }
  return { counts: out };
}

export interface RosterCountActions {
  /** Force this ONE model's badge to authoritative NOW: bust its 5-min server
   *  cache, re-read from OF, merge just that account into the local map. Cooldown-
   *  guarded (skippable with `force`) so swap/hover/WS bursts stay cheap. */
  refreshOne: (accountId: string, opts?: { force?: boolean }) => Promise<void>;
  /** Optimistically rewrite one model's cached count in the same tick (no
   *  network) so the badge moves instantly; `refreshOne`/the poll then reconcile
   *  the exact value. */
  patchLocal: (accountId: string, fn: (cur: RosterCount) => RosterCount) => void;
}

export function useRosterCountActions(): RosterCountActions {
  const qc = useQueryClient();
  const principalId = usePrincipalId();

  const patchLocal = useCallback<RosterCountActions["patchLocal"]>(
    (accountId, fn) => {
      const existing = qc.getQueryData<RosterCountsResp>(rosterCountsKey(principalId));
      // No baseline yet (the roster query hasn't returned) → do NOT fabricate a
      // from-zero count. mergeRosterCounts would then pin that fake {0,…}+delta
      // over the real initial fetch (the stamp below marks it "newer"), so the
      // badge would show just this one delta instead of the true total for up to
      // 60s. The in-flight / next poll establishes truth and already counts this
      // event (it's in the DB the server aggregates).
      if (!existing) return;
      const counts = existing.counts ?? {};
      const cur = counts[accountId] ?? { unread: 0, owe_reply: 0 };
      qc.setQueryData<RosterCountsResp>(rosterCountsKey(principalId), {
        counts: { ...counts, [accountId]: fn(cur) },
      });
      // Stamp so an older targeted refresh (which read OF before this patch) can't
      // resolve later and revert it. See lastLocalPatchAt.
      lastLocalPatchAt.set(`${principalId}:${accountId}`, Date.now());
    },
    [qc, principalId],
  );

  const refreshOne = useCallback<RosterCountActions["refreshOne"]>(
    async (accountId, opts) => {
      if (!accountId) return;
      const cacheKey = `${principalId}:${accountId}`;
      // In-flight handling:
      //  • NOT forced → ride the pending read (coalesce hover/swap/WS bursts to a
      //    single bust).
      //  • forced → the caller needs state that may have changed AFTER that read
      //    began (e.g. a send that just landed), so we must NOT ride it. Wait it
      //    out, THEN do our own fresh read. Draining sequentially (not racing a
      //    second concurrent bust) means our `startedAt` is stamped after the prior
      //    write, so the latest-wins guard below lets our fresher read win.
      let pending = inFlightRefresh.get(cacheKey);
      if (pending && !opts?.force) return pending;
      while (pending) {
        await pending.catch(() => {});
        pending = inFlightRefresh.get(cacheKey);
      }
      const now = Date.now();
      if (!opts?.force && now - (lastRefreshAt.get(cacheKey) ?? 0) < REFRESH_COOLDOWN_MS) {
        return;
      }
      lastRefreshAt.set(cacheKey, now);
      const startedAt = now;
      const run = (async () => {
        // Cancel any in-flight full-map poll first: it may have read this account's
        // count from the server BEFORE we bust it, so letting it resolve after our
        // merge would clobber the fresh value back to stale.
        await qc.cancelQueries({ queryKey: rosterCountsKey(principalId) });
        try {
          const resp = await relay.get<RosterCountsResp>(
            `/admin/accounts/roster-counts?bust=${encodeURIComponent(accountId)}`,
          );
          // Latest-wins: if an optimistic local patch (e.g. a read dropping unread)
          // landed AFTER we kicked this read, our OF snapshot predates it — skip the
          // write so we don't revert the newer value. mark-read busted the server
          // cache, so the next poll/refresh reconciles to OF-truth cleanly.
          if ((lastLocalPatchAt.get(cacheKey) ?? 0) > startedAt) return;
          const fresh = resp?.counts?.[accountId];
          // Merge ONLY the target so we don't stomp fresher optimistic values on
          // the other models (the bust response carries only the target anyway).
          // Write DIRECTLY, not via patchLocal: this is an authoritative OF read,
          // so it must land even when the roster cache is still empty (patchLocal
          // skips a from-nothing write to avoid fabricating an optimistic baseline
          // — see its guard). Stamp so a racing poll can't clobber this fresh read.
          if (fresh) {
            qc.setQueryData<RosterCountsResp>(rosterCountsKey(principalId), (old) => {
              const counts = old?.counts ?? {};
              return { counts: { ...counts, [accountId]: fresh } };
            });
            lastLocalPatchAt.set(cacheKey, Date.now());
          }
        } catch {
          // Best-effort: the 60s poll reconciles if the targeted read fails.
        }
      })();
      inFlightRefresh.set(cacheKey, run);
      try {
        await run;
      } finally {
        inFlightRefresh.delete(cacheKey);
      }
    },
    [qc, principalId, patchLocal],
  );

  return { refreshOne, patchLocal };
}
