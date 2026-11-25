"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface PpvHistoryItem {
  transaction_id: number;
  message_id: number | null;
  price_cents: number;
  net_cents: number | null;
  fee_cents: number | null;
  vat_cents: number | null;
  purchased_at: string | null;
  sent_at: string | null;
  sent_by_employee_id: number | null;
  employee_name: string | null;
  employee_color: string | null;
}

export interface PpvHistorySummary {
  count: number;
  max_cents: number;
  avg_cents: number;
  tips_cents: number;
  messages_cents: number;
  posts_cents: number;
}

export interface PpvHistoryResp {
  items: PpvHistoryItem[];
  summary: PpvHistorySummary;
}

export function useFanPpvHistory(
  accountId: string | null,
  fanId: FanId | null,
  limit = 12,
) {
  return useQuery<PpvHistoryResp>({
    queryKey: ["fan-ppv-history", accountId, fanId, limit] as const,
    enabled: !!accountId && fanId != null,
    queryFn: () =>
      relay.get<PpvHistoryResp>(
        `/admin/fans/${accountId}/${fanId}/ppv-history?limit=${limit}`,
      ),
    placeholderData: (prev) => prev,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
  });
}
