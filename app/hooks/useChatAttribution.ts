"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface AttributionEntry {
  employee_id: number | null;
  display_name: string | null;
  automation_kind: string | null;
  sender_name: string | null;
  color: string | null;
  unsent_at?: string | null;
  unsent_reason?: string | null;
  created_at?: string | null;
}

export interface AttributionResponse {
  by_msg_id: Record<string, AttributionEntry>;
}

export function useChatAttribution(
  accountId: string | null,
  fanId: FanId | null,
  oldestId: number | null,
) {
  return useQuery<AttributionResponse>({
    queryKey: ["msg-attribution", accountId, fanId, oldestId],
    enabled: !!accountId && fanId != null,
    queryFn: () => {
      const params = new URLSearchParams();
      if (oldestId != null && Number.isFinite(oldestId)) {
        params.set("since_id", String(oldestId));
      }
      const qs = params.toString();
      const path = `/admin/messages/${encodeURIComponent(accountId!)}/${fanId}/attribution${qs ? `?${qs}` : ""}`;
      return relay.get<AttributionResponse>(path);
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
