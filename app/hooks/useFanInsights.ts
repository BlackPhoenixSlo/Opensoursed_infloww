"use client";

/**
 * useFanInsights — Fan insights' money figures: Spending power, Chargeback
 * risk, and Buy rate / Highest / Lowest price over the last 30 PPVs.
 *
 * Backend: GET /admin/fans/{aid}/{fid}/insights (service/fan_insights_api.py),
 * a few local index scans, no OnlyFans call. `transaction_recorded` invalidates
 * it with the rest of the fan's money caches (useInboxRealtime); the 60s
 * staleTime plus focus refetch is the safety net, as for useFanPpvHistory.
 */

import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface FanInsights {
  spending_power: {
    /** "Top 1%" … "Top 50%", "Bottom", "No Spending History", "Insufficient Data". */
    label: string;
    spend_30d_cents: number;
    population: number;
  };
  chargeback_risk: {
    /** "High" | "Medium" | "Low"; null with nothing paid. */
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

/** The query's key, fetcher and freshness — shared with any prefetch
 *  so a warm lands where this reads. */
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
