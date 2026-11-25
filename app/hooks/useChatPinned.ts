"use client";


import { useQuery } from "@tanstack/react-query";

import { relay, type OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { useCan } from "@/hooks/useCan";

interface PinnedResp {
  list?: OFMessage[];
}

export function useChatPinned(
  accountId: string | null,
  fanId: FanId | null,
  enabled = true,
) {
  const allowed = useCan(accountId, "pin_message");
  return useQuery<OFMessage[]>({
    queryKey: ["chat-pinned", accountId ?? "", String(fanId ?? "")],
    enabled: !!accountId && !!fanId && enabled && allowed,
    staleTime: 60_000,
    queryFn: async (): Promise<OFMessage[]> => {
      if (!accountId || !fanId) return [];
      // One request, no paging: OF's hasMore lies on the pinned filter (of_client.get_pinned_messages)
      const r = await relay.get<PinnedResp>(
        `/api/of/v2/chats/${fanId}/pinned`,
        { accountId },
      );
      return r.list ?? [];
    },
  });
}
