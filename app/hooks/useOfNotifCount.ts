"use client";

/**
 * useOfNotifCount — a Creator's OnlyFans notification count
 * (`/api/of/v2/users/notifications/count`, its `all`), under the
 * `["of-notif-count", accountId]` key the OF Manager Creator column reads too,
 * so every reader shares one cache entry. `accountId` null reads nothing.
 * A failed read counts 0.
 */

import { skipToken, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

interface NotifCountResp { all?: number }

export function useOfNotifCount(accountId: string | null) {
  const q = useQuery<number>({
    queryKey: ["of-notif-count", accountId],
    queryFn: accountId
      ? async () => Number((await relay.get<NotifCountResp>("/api/of/v2/users/notifications/count", { accountId }))?.all) || 0
      : skipToken,
    staleTime: 30_000,
    retry: false,
  });
  return { count: q.isError ? 0 : q.data ?? 0, refetch: q.refetch };
}
