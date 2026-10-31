"use client";

/**
 * useCreatorWarmUp — the Creator warm-up the roster strip and the Messages Pro
 * Creator tabs share, so both behave alike: `warm(accountId)` prefetches the
 * Creator's Fan List and refreshes its unread count, and `hoverThen(fn)` runs
 * `fn` once the pointer (or keyboard focus) has settled for HOVER_INTENT_MS.
 * `clearHover` cancels a pending hover warm (pointer left, or a pick).
 */

import { useCallback, useEffect, useRef } from "react";
import { useQueryClient, type Query } from "@tanstack/react-query";

import { prefetchModelChatList } from "@/hooks/useChatList";
import { useRosterCountActions } from "@/hooks/useRosterCounts";

/** Hover intent: only warm after the pointer settles, so sweeping the mouse
 *  across the Creators doesn't fire a live OF read per Creator it crosses. */
export const HOVER_INTENT_MS = 250;

/** Whether the warm-up's invalidation may refetch this chat list: not while it is loading its
 *  next page (the refetch would cancel that page and the list would come back a page short).
 *  `fetchMeta` keeps `fetchMore` after that page settles or fails, so only `fetchStatus` says it
 *  is still loading; a settled list is refetched like any other. */
export function warmUpMayRefetch(q: Query): boolean {
  return !(q.state.fetchStatus !== "idle" && q.state.fetchMeta?.fetchMore);
}

export function useCreatorWarmUp() {
  const { refreshOne } = useRosterCountActions();
  const qc = useQueryClient();

  // Prewarm a model the instant it's touched: force its unread badge fresh from
  // OF (bust the 5-min server cache) AND prefetch its chat list, so a swap paints
  // authoritative + spinner-free instead of waiting on the 60s poll. `refreshOne`
  // is per-account cooldown-guarded, so hover→click doesn't double-read OF.
  //
  // The ?bust= behind refreshOne re-reads OF's chat window AND rewarms the
  // server-side "list_chats" page-0 entry the list is served from — the badge
  // counts are folded from those same rows. Invalidating the model's chat-list
  // queries AFTER it resolves therefore snaps the visible list to the exact
  // rows the badge counted (a warm relay hit, no extra OF read) — without this,
  // the prefetch's stale snapshot stays "fresh" for 30s and the list shows 2
  // while the badge says 3. Every refreshOne path is safe to chain on: a real
  // bust resolves after the rewarm; riding an in-flight bust resolves with it;
  // a cooldown no-op means a bust ran <8s ago. If that bust FAILED (OF error —
  // refreshOne swallows it), the refetch just re-reads whatever the relay has;
  // badge and list still agree because both come from that same window.
  // A list loading its next page is left alone (warmUpMayRefetch).
  const warm = useCallback(
    (accountId: string) => {
      void prefetchModelChatList(qc, accountId);
      void refreshOne(accountId).then(() =>
        qc.invalidateQueries({ queryKey: ["chats", "model", accountId], predicate: warmUpMayRefetch }),
      );
    },
    [refreshOne, qc],
  );

  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearHover = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  }, []);
  const hoverThen = useCallback(
    (fn: () => void) => {
      clearHover();
      hoverTimerRef.current = setTimeout(fn, HOVER_INTENT_MS);
    },
    [clearHover],
  );
  useEffect(() => clearHover, [clearHover]);

  return { warm, hoverThen, clearHover };
}
