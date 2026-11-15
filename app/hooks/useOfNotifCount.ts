"use client";

/**
 * useOfNotifCount — a Creator's OnlyFans notification count
 * (`/api/of/v2/users/notifications/count`, its `all`), under the
 * `["of-notif-count", accountId]` key the OF Manager Creator column reads too,
 * so every reader shares one cache entry. `accountId` null reads nothing (the
 * callers pass null for a Dead-session Creator). A failed read counts 0.
 * Re-read only while this tab leases the Creator; an unleased one reads once
 * armed and then only on its next `creator_warmed` (lib/ofReadGate.ts).
 * `staleMs`: how long a read stays fresh (OF Manager's column: 60 s, as Infloww's).
 */

import { skipToken, useQuery } from "@tanstack/react-query";

import { useOfReadGate } from "@/hooks/useOfReadGate";
import { relay } from "@/lib/relay";
import { gateOptions } from "@/lib/ofReadGate";

interface NotifCountResp { all?: number }

const NO_IDS: readonly string[] = [];
/** The count's key, for the lease-gain refetch. */
export const COUNT_ROOTS = ["of-notif-count"] as const;

export function useOfNotifCount(accountId: string | null, staleMs = 30_000) {
  const gate = useOfReadGate(accountId ? [accountId] : NO_IDS, COUNT_ROOTS)(accountId ?? "");
  const { enabled, ...gated } = gateOptions(gate);
  const q = useQuery<number>({
    queryKey: ["of-notif-count", accountId],
    // A badge: background (queued behind clicks, lib/relaySchedule), dropped when its screen goes (signal).
    queryFn: accountId && enabled !== false
      ? async ({ signal }) => Number((await relay.get<NotifCountResp>(
        "/api/of/v2/users/notifications/count", { accountId, priority: "background" }, signal))?.all) || 0
      : skipToken,
    staleTime: staleMs,
    retry: false,
    ...gated,
  });
  return { count: q.isError ? 0 : q.data ?? 0, refetch: q.refetch };
}
