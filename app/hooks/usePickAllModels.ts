"use client";


import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRosterCountActions } from "@/hooks/useRosterCounts";
import { CREATOR_POOL, settlePool } from "@/lib/settlePool";

export function usePickAllModels() {
  const accounts = usePlatformAccounts();
  const { refreshOne } = useRosterCountActions();
  const { setScope } = useScope();
  const qc = useQueryClient();

  const warmAll = useCallback(() => {
    void settlePool(accounts, CREATOR_POOL, (a) => refreshOne(a.id)).then(() =>
      qc.invalidateQueries({ queryKey: ["chats", "all"] }),
    );
  }, [accounts, refreshOne, qc]);

  const pickAll = useCallback(() => {
    setScope({ kind: "all" });
    warmAll();
  }, [setScope, warmAll]);

  return { pickAll, warmAll };
}
