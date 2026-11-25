"use client";


import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface VaultMediaStat {
  sent: number;
  priced: number;
  unlocks: number;
  unlock_rate: number | null;
  last_sent_at: string | null;
}

export interface VaultMediaStatsResp {
  by_media: Record<string, VaultMediaStat>;
}

export function useVaultMediaStats(accountId: string | null, enabled = true) {
  return useQuery<VaultMediaStatsResp>({
    queryKey: ["vault-media-stats", accountId],
    enabled: enabled && !!accountId,
    queryFn: async () => {
      const resp = await relay.get<Partial<VaultMediaStatsResp> | null>(
        `/admin/vault/media-stats?account_id=${encodeURIComponent(accountId!)}`,
      );
      return { by_media: resp?.by_media ?? {} };
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
