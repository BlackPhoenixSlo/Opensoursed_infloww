"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type FanRecord, type FanUpdate, type OFUserMini } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { mergeOFUserName, ofUserFullKey } from "@/hooks/useOFUser";
import { patchQueryData } from "@/lib/cacheWrite";

export function fanQueryOptions(accountId: string | null, fanId: FanId | null) {
  return {
    queryKey: ["fan", accountId, fanId] as const,
    queryFn: () => relay.get<FanRecord>(`/admin/fans/${accountId}/${fanId}`),
    staleTime: 24 * 60 * 60 * 1000,
  };
}

export function useFan(accountId: string | null, fanId: FanId | null) {
  const qc = useQueryClient();
  const { queryKey } = fanQueryOptions(accountId, fanId);

  const q = useQuery<FanRecord>({
    ...fanQueryOptions(accountId, fanId),
    enabled: !!accountId && fanId != null,
    refetchOnWindowFocus: false,
  });

  const update = useMutation({
    mutationFn: (patch: FanUpdate) =>
      relay.patch<FanRecord>(`/admin/fans/${accountId}/${fanId}`, patch),
    onSuccess: (next) => {
      qc.setQueryData(queryKey, next);
      if (accountId && fanId != null) {
        // Both fields: the drawer write-through also renames on OF, so the rail label updates whichever the row prefers.
        mergeOFUserName(qc, accountId, fanId, {
          customNickname: next.custom_nickname ?? null,
          displayName: next.custom_nickname ?? null,
        });
        patchQueryData<OFUserMini>(
          qc, ofUserFullKey(accountId, fanId),
          (prev) => prev && { ...prev, displayName: next.custom_nickname ?? null },
        );
      }
    },
  });

  return { ...q, update };
}
