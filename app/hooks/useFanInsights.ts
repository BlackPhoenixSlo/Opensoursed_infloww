"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface FanInsights {
  spending_power: {
    label: string;
    spend_30d_cents: number;
    population: number;
  };
  chargeback_risk: {
    label: string | null;
    pct: number | null;
    paid_cents: number;
    reversed_cents: number;
  };
  ppv_recent: {
    count: number;
    bought: number;
    buy_rate_pct: number | null;
    highest_cents: number | null;
    lowest_cents: number | null;
  };
}

export function fanInsightsQueryOptions(accountId: string | null, fanId: FanId | null) {
  return {
    queryKey: ["fan-insights", accountId, fanId] as const,
    queryFn: () => relay.get<FanInsights>(`/admin/fans/${accountId}/${fanId}/insights`),
    staleTime: 60 * 1000,
  };
}

export function useFanInsights(accountId: string | null, fanId: FanId | null, enabled = true) {
  return useQuery<FanInsights>({
    ...fanInsightsQueryOptions(accountId, fanId),
    enabled: enabled && !!accountId && fanId != null,
    refetchOnWindowFocus: true,
  });
}
