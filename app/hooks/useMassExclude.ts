"use client";

/**
 * useMassExclude — read + toggle a fan's membership on the account's system
 * mass-exclude list, MASSdmEXCLUDE: a fan on it is skipped from every mass send,
 * priced or not. (Its PPV-only twin, MASSppvEXCLUDE, was merged into it
 * 2026-10-21.) Backed by a local kind='exclude' list mirrored to a same-named
 * pinned OF list (service/lists.py + audiences.exclude_list_fan_ids). Optimistic
 * toggle; account_id/fan_id/kind go in the query string (the relay's /admin/*
 * endpoints read them as params — the X-Account-Id header is for audit/scope only).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

interface MassExcludeResp {
  /** Backend endpoint is /admin/do-not-mass (kind param); response key is
   *  do_not_mass for backward-compat with the single-list callers. */
  do_not_mass: boolean;
  /** False when the OnlyFans-list mirror couldn't be synced (no session / OF
   *  down). The local exclusion still applies; the UI flags a pending sync. */
  of_synced?: boolean;
  of_list_id?: number | null;
}

function url(accountId: string, fanId: FanId) {
  return `/admin/do-not-mass?account_id=${encodeURIComponent(accountId)}&fan_id=${fanId}&kind=dm`;
}

export function useMassExclude(accountId: string, fanId: FanId) {
  const qc = useQueryClient();
  const key = ["mass-exclude", accountId, fanId] as const;

  const q = useQuery({
    queryKey: key,
    enabled: !!accountId && !!fanId,
    staleTime: 60_000,
    queryFn: () => relay.get<MassExcludeResp>(url(accountId, fanId), { accountId }),
  });

  const toggle = useMutation({
    mutationFn: (next: boolean): Promise<MassExcludeResp> =>
      next
        ? relay.post<MassExcludeResp>(url(accountId, fanId), undefined, { accountId })
        : relay.delete<MassExcludeResp>(url(accountId, fanId), { accountId }),
    onMutate: async (next: boolean) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<MassExcludeResp>(key);
      qc.setQueryData<MassExcludeResp>(key, { do_not_mass: next });
      return { prev };
    },
    onError: (_e, _next, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  return { isOn: !!q.data?.do_not_mass, isLoading: q.isLoading, toggle };
}
