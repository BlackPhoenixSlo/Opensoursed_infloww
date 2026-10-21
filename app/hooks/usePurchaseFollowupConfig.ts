"use client";

/**
 * usePurchaseFollowupConfig — read/write the purchase_followup automation
 * (Smart Messages' "Purchased" Trigger: one message to a fan after he buys a
 * PPV). The Relay keeps the whole config in the account's purchase_followup
 * automation rule (`service/purchase_followup_config_api.py`), so a save also
 * refreshes the automation-rules read the Automated Messages list is built on.
 * Off by default: an account with no saved config reads `enabled: false`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SmartExtras } from "@/components/growth/SmartMessageFields";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "purchase-followup-config";
const BG_CTX: RelayContext = { priority: "background" };

/** On/off, the text and the Smart Message settings: media and price,
 *  frequency ("every" thanks each purchase, at most one per fan per 2 hours),
 *  Effective / Expiry, Infloww's random delay and Auto-unsend. */
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
      relay.put(`/admin/purchase-followup-config`, { account_id: accountId, config }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, accountId] });
      qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
    },
  });
}
