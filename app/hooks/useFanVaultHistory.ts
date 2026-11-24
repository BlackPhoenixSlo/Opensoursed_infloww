"use client";

/**
 * useFanVaultHistory — per-fan vault send/purchase history.
 *
 * Drives the VaultPicker's status badges ("sent · purchased · unseen")
 * and any future "show me what she's already paid for" filters. Backed
 * by the local SQLite tables `vault_sends` + `transactions` — shared
 * across all chatters on the same model account.
 *
 * Cache strategy:
 *   • Keyed on (accountId, fanId) so popping between chats is instant.
 *   • staleTime 60s — vault history rarely changes mid-session.
 *   • Persisted via the global PersistQueryClient layer (the `fan` /
 *     `vault-history` keys are whitelisted in providers.tsx).
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

export interface FanVaultEntry {
  send_count: number;
  last_sent_at: string | null;
  last_price_cents: number;
  was_purchased: boolean;
  last_purchase_at: string | null;
  total_paid_cents: number;
}

export interface FanVaultHistoryResp {
  by_media: Record<string, FanVaultEntry>;
}

/** A history answer (the read's, or the backfill's `history`) as the cache holds it: `by_media` always set, so
 *  every reader can index `by_media[id]` (a reply without it used to crash the whole Thread). */
export function normalizeVaultHistory(resp: Partial<FanVaultHistoryResp> | null | undefined): FanVaultHistoryResp {
  return { ...resp, by_media: resp?.by_media ?? {} };
}

export function vaultHistoryKey(accountId: string | null, fanId: FanId | null) {
  return ["vault-history", accountId, fanId] as const;
}

/** Writes a history answer to the fan's cache only when it carries `by_media`, so a reply without one never
 *  empties cached badges; false when nothing was written. */
export async function setVaultHistory(
  qc: QueryClient,
  accountId: string | null,
  fanId: FanId | null,
  history: Partial<FanVaultHistoryResp> | null | undefined,
): Promise<boolean> {
  if (!history || typeof history.by_media !== "object" || history.by_media === null) return false;
  const queryKey = vaultHistoryKey(accountId, fanId);
  await qc.cancelQueries({ queryKey, exact: true });
  qc.setQueryData<FanVaultHistoryResp>(queryKey, normalizeVaultHistory(history));
  return true;
}

export function useFanVaultHistory(
  accountId: string | null,
  fanId: FanId | null,
  enabled = true,
) {
  return useQuery<FanVaultHistoryResp>({
    queryKey: vaultHistoryKey(accountId, fanId),
    enabled: enabled && !!accountId && fanId != null,
    queryFn: async () => {
      const qs = new URLSearchParams({
        account_id: accountId!,
        fan_id: String(fanId),
      });
      return normalizeVaultHistory(await relay.get<Partial<FanVaultHistoryResp> | null>(`/admin/vault/fan-history?${qs.toString()}`));
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
