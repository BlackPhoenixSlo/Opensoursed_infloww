"use client";


import { useCallback, useEffect, useRef } from "react";
import { useQueryClient, type Query } from "@tanstack/react-query";

import { prefetchModelChatList } from "@/hooks/useChatList";
import { useRosterCountActions } from "@/hooks/useRosterCounts";

export const HOVER_INTENT_MS = 250;

// Refetching a list mid next-page would cancel that page and leave the list a page short.
export function warmUpMayRefetch(q: Query): boolean {
  return !(q.state.fetchStatus !== "idle" && q.state.fetchMeta?.fetchMore);
}

export function useCreatorWarmUp() {
  const { refreshOne } = useRosterCountActions();
  const qc = useQueryClient();

  const warm = useCallback(
    (accountId: string) => {
      // Invalidate after the bust resolves so the list snaps to the exact rows the badge counted (warm relay hit, no extra OF read).
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
