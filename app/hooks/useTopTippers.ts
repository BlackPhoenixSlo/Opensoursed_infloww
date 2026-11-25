"use client";


import { useQuery } from "@tanstack/react-query";

import { reportQuery, type ReportQueryParams } from "@/hooks/reportQuery";
import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface TopTipperFan {
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;
}

export interface TopTipperRow {
  rank: number;
  fan_id: FanId;
  account_id: string;
  fan: TopTipperFan;
  total_cents: number;
  tip_count: number;
  last_tip_at: string | null;
}

export interface TopTippersResp {
  rows: TopTipperRow[];
}

export interface UseTopTippersParams extends ReportQueryParams {
  limit?: number;
}

export function buildTopTippersQuery(params: UseTopTippersParams, csv = false): string {
  const qs = reportQuery(params);
  if (csv) qs.set("format", "csv");
  else if (params.limit != null) qs.set("limit", String(params.limit));
  return qs.toString();
}

export function useTopTippers(params: UseTopTippersParams) {
  const enabled = !!params.from && !!params.to;

  return useQuery<TopTippersResp>({
    queryKey: [
      "top-tippers",
      params.from,
      params.to,
      params.account_id ?? null,
      params.employee_id ?? null,
      params.limit ?? 20,
    ],
    enabled,
    queryFn: () =>
      relay.get<TopTippersResp>(`/admin/top-tippers?${buildTopTippersQuery(params)}`),
    staleTime: 2 * 60_000,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
