"use client";


import { useQuery } from "@tanstack/react-query";

import type { FullAiRevenueApi } from "@/components/automations/fullAiRevenueView";
import { ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";

export const fullAiRevenueKey = (accountId: string) => ["full-ai-revenue", accountId] as const;

export function useFullAiRevenue(accountId: string) {
  return useQuery<FullAiRevenueApi>({
    queryKey: fullAiRevenueKey(accountId),
    queryFn: () => relay.get<FullAiRevenueApi>(
      `/admin/full-ai/revenue?account_id=${encodeURIComponent(accountId)}`,
      { accountId, priority: "background" },
    ),
    staleTime: 60_000,
    refetchInterval: ssePoll(5 * 60_000, 60_000),
    refetchOnWindowFocus: true,
  });
}
