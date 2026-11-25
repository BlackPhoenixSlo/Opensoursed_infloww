"use client";


import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { reportQuery, type ReportQueryParams } from "@/hooks/reportQuery";
import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface TipsListFan {
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;
}

export interface TipsListRow {
  transaction_id: number;
  account_id: string;
  fan_id: FanId | null;
  fan: TipsListFan;
  amount_cents: number;
  occurred_at: string | null;
  message_id: number | null;
  tip_note: string | null;
  attributed_employee_id: number | null;
  attributed_employee_name: string | null;
  attribution_source: "tip_message" | null;
}

export interface TipsListPage {
  rows: TipsListRow[];
  limit: number;
  next_before_id: number | null;
}

export interface UseTipsListParams extends ReportQueryParams {
  fan_query?: string | null;
  limit?: number;
}

export function buildTipsListQuery(params: UseTipsListParams, beforeId: number | null, csv = false): string {
  const qs = reportQuery(params);
  if (params.fan_query && params.fan_query.length >= 2) {
    qs.set("fan_query", params.fan_query);
  }
  if (csv) {
    qs.set("format", "csv");
    return qs.toString();
  }
  qs.set("limit", String(params.limit ?? 50));
  if (beforeId != null) qs.set("before_id", String(beforeId));
  return qs.toString();
}

export function useTipsList(params: UseTipsListParams) {
  const enabled = !!params.from && !!params.to;

  return useInfiniteQuery<TipsListPage>({
    queryKey: [
      "tips-list",
      params.from,
      params.to,
      params.account_id ?? null,
      params.employee_id ?? null,
      params.fan_query && params.fan_query.length >= 2 ? params.fan_query : null,
      params.limit ?? 50,
    ],
    enabled,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      relay.get<TipsListPage>(
        `/admin/tips-list?${buildTipsListQuery(params, pageParam as number | null)}`,
      ),
    getNextPageParam: (lastPage) => lastPage.next_before_id ?? undefined,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    maxPages: 20,
    placeholderData: keepPreviousData,
  });
}
