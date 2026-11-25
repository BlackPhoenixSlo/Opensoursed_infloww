"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

interface MassExcludeResp {
  do_not_mass: boolean;
  of_synced?: boolean;
  of_list_id?: number | null;
}

// account_id/fan_id/kind go in the query string: the relay's /admin/* read them as params, X-Account-Id is audit only.
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
