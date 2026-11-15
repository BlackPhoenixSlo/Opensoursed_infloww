"use client";

/**
 * useFullAiMode — the Full AI page's Mode control (GET / PUT /admin/full-ai/mode, service/full_ai_api.py, ticket 74).
 * `mode` is "off" | "shadow" (a legacy rule: records only, not settable) | "live"; `off_switch` = FULL_AI_CHAT_OFF is
 * set (nothing sends whatever the Mode); `blockers` = why Live would be refused now. The PUT answers with the same
 * shape, written straight into the cache; the rules read is refetched (the rule row changed).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export type FullAiMode = "off" | "shadow" | "live";

export interface FullAiModeApi {
  mode: FullAiMode;
  off_switch: boolean;
  blockers: string[];
}

export const fullAiModeKey = (accountId: string) => ["full-ai-mode", accountId] as const;

export function useFullAiMode(accountId: string) {
  return useQuery<FullAiModeApi>({
    queryKey: fullAiModeKey(accountId),
    queryFn: () => relay.get<FullAiModeApi>(`/admin/full-ai/mode?account_id=${encodeURIComponent(accountId)}`,
      { accountId }),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });
}

export function useSetFullAiMode(accountId: string) {
  const qc = useQueryClient();
  return useMutation<FullAiModeApi, Error, "off" | "live">({
    mutationFn: (mode) => relay.put<FullAiModeApi>("/admin/full-ai/mode", { account_id: accountId, mode }, { accountId }),
    onSuccess: (data) => {
      qc.setQueryData(fullAiModeKey(accountId), data);
      qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
    },
    // A refusal (409) means the blockers moved: read them again.
    onError: () => { qc.invalidateQueries({ queryKey: fullAiModeKey(accountId) }); },
  });
}
