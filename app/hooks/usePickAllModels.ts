"use client";

/**
 * usePickAllModels — the All Models action: set the scope to every Creator
 * and warm each one. Shared by the roster's All Models icon and the Window
 * header's All Models extra (ADR-0003), so both behave alike.
 *
 * `warmAll` refreshes every Creator in the All Models aggregate (every
 * session-bearing Creator) and, once those busts
 * settle, refetches the All Models Fan List. The aggregate badge is the sum
 * of the per-Creator counts and picking All Models refreshes none of them,
 * so each is busted here. Each per-Creator bust rewarms that Creator's
 * server-side chat window, and the unified list fans out per-Creator page-0
 * reads against those exact keys, so the one invalidation refetches the All
 * tab as warm hits of the same rows the badges counted. Each `refreshOne` is
 * cooldown-guarded per Creator, so repeated picks cannot storm OnlyFans.
 * allSettled: one bad Creator must not keep the rest of the tab stale.
 */

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRosterCountActions } from "@/hooks/useRosterCounts";

export function usePickAllModels() {
  const accounts = usePlatformAccounts();
  const { refreshOne } = useRosterCountActions();
  const { setScope } = useScope();
  const qc = useQueryClient();

  const warmAll = useCallback(() => {
    void Promise.allSettled(accounts.map((a) => refreshOne(a.id))).then(() =>
      qc.invalidateQueries({ queryKey: ["chats", "all"] }),
    );
  }, [accounts, refreshOne, qc]);

  const pickAll = useCallback(() => {
    setScope({ kind: "all" });
    warmAll();
  }, [setScope, warmAll]);

  return { pickAll, warmAll };
}
