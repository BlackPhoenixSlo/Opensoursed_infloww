"use client";


import { skipToken, useQuery } from "@tanstack/react-query";

import type { FanId } from "@/lib/fanId";
import { relay } from "@/lib/relay";

export type OnlineSubscribersResp = { id: FanId }[] | { list?: { id: FanId }[]; hasMore?: boolean };

export const ONLINE_PAGE = 20;

export interface OnlineSubscribers {
  ids: ReadonlySet<string>;
  hasMore: boolean;
}

export function useOnlineSubscribers(accountId: string | null, refetchInterval?: number) {
  return useQuery<OnlineSubscribers>({
    queryKey: ["of-online-subscribers", accountId],
    queryFn: accountId ? async () => {
      const resp = await relay.get<OnlineSubscribersResp>(
        // OF caps limit at 20 for this list: limit=50 returns 20 at most.
        "/api/of/v2/subscribers?type=active&online=1&limit=50",
        { accountId },
      );
      const list = Array.isArray(resp) ? resp : resp?.list ?? [];
      const ids = new Set(list.map((u) => String(u.id)));
      return { ids, hasMore: (!Array.isArray(resp) && !!resp?.hasMore) || ids.size >= ONLINE_PAGE };
    } : skipToken,
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- caller's rate; OF online status has no relay event
    refetchInterval,
    retry: false,
  });
}

export function onlineCountLabel(d: OnlineSubscribers): string {
  return `${d.ids.size}${d.hasMore ? "+" : ""}`;
}
