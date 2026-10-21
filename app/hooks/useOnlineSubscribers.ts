"use client";

/**
 * useOnlineSubscribers — one page of a Creator's OnlyFans online subscribers
 * list (`/api/of/v2/subscribers?type=active&online=1`, latest activity
 * first). Messages Pro's Online Fans and the Mass Online panel's live count
 * share it, under one cache key. `null` account → not read.
 */

import { skipToken, useQuery } from "@tanstack/react-query";

import type { FanId } from "@/lib/fanId";
import { relay } from "@/lib/relay";

/** OnlyFans' list, bare or in its `list` envelope (as `of_client.py`
 *  `iter_online_subscribers` reads it). */
export type OnlineSubscribersResp = { id: FanId }[] | { list?: { id: FanId }[]; hasMore?: boolean };

/** OnlyFans caps `limit` at 20 for this list (`iter_online_subscribers`), so
 *  the `limit=50` asked (Messages Pro's read, unchanged) returns 20 at most. */
export const ONLINE_PAGE = 20;

export interface OnlineSubscribers {
  ids: ReadonlySet<string>;
  /** More online fans than the page holds. */
  hasMore: boolean;
}

export function useOnlineSubscribers(accountId: string | null, refetchInterval?: number) {
  return useQuery<OnlineSubscribers>({
    queryKey: ["of-online-subscribers", accountId],
    queryFn: accountId ? async () => {
      const resp = await relay.get<OnlineSubscribersResp>(
        "/api/of/v2/subscribers?type=active&online=1&limit=50",
        { accountId },
      );
      const list = Array.isArray(resp) ? resp : resp?.list ?? [];
      const ids = new Set(list.map((u) => String(u.id)));
      return { ids, hasMore: (!Array.isArray(resp) && !!resp?.hasMore) || ids.size >= ONLINE_PAGE };
    } : skipToken,
    staleTime: 30_000,
    refetchInterval,
    retry: false,
  });
}

/** "12", or "20+" when the page is full: one page is all that is read. */
export function onlineCountLabel(d: OnlineSubscribers): string {
  return `${d.ids.size}${d.hasMore ? "+" : ""}`;
}
