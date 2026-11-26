"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SmartExtras } from "@/components/growth/SmartMessageFields";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "purchase-followup-config";
const BG_CTX: RelayContext = { priority: "background" };

export interface PurchaseFollowupConfig extends SmartExtras {
  enabled: boolean;
  text: string;
}

interface PurchaseFollowupResponse {
  account_id: string;
  config: PurchaseFollowupConfig;
  defaults: PurchaseFollowupConfig;
}

export function usePurchaseFollowupConfig(accountId: string | null) {
  return useQuery<PurchaseFollowupResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<PurchaseFollowupResponse>(
        `/admin/purchase-followup-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    refetchOnWindowFocus: false,
  });
}

export function useSavePurchaseFollowupConfig(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<{ account_id: string; config: PurchaseFollowupConfig }, Error, Partial<PurchaseFollowupConfig>>({
    mutationFn: (config) =>
      relay.put(`/admin/purchase-followup-config`, { account_id: accountId, config }, { cellAccountId: accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, accountId] });
      qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
    },
  });
}
