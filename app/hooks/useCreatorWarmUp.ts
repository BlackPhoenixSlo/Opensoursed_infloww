"use client";


import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { prefetchModelChatList, refreshChatHead } from "@/hooks/useChatList";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRosterCountActions } from "@/hooks/useRosterCounts";

export const HOVER_INTENT_MS = 250;

const warming = new Map<string, Promise<void>>();

export function coalesceWarmUp(id: string, run: () => Promise<void>): Promise<void> {
  const had = warming.get(id);
  if (had) return had;
  const p = run().catch(() => {}).finally(() => warming.delete(id));
  warming.set(id, p);
  return p;
}

export function useCreatorWarmUp() {
  const { refreshOne } = useRosterCountActions();
  const qc = useQueryClient();
  const accounts = usePlatformAccounts();

  const warm = useCallback(
    (accountId: string) => {
      const account = accounts.find((a) => a.id === accountId);
      void prefetchModelChatList(qc, accountId);
      void coalesceWarmUp(`model:${accountId}`, () =>
        refreshOne(accountId).then(() => account && refreshChatHead(qc, { kind: "model", accountId }, [account])));
    },
    [refreshOne, qc, accounts],
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
