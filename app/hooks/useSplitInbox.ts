"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import {
  splitInboxKey, splitInboxQueryOptions, type SplitInboxConfig, type SplitInboxResponse,
} from "@/lib/splitInbox";

export function useSplitInbox(accountId: string | null) {
  const qc = useQueryClient();
  const query = useQuery(splitInboxQueryOptions(accountId));
  const save = useMutation<SplitInboxResponse, Error, SplitInboxConfig>({
    mutationFn: (config) =>
      relay.put<SplitInboxResponse>(`/admin/split-inbox`, { account_id: accountId, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: splitInboxKey(accountId) }),
  });
  return { config: query.data?.config ?? null, myGroup: query.data?.my_group ?? null, query, save };
}
