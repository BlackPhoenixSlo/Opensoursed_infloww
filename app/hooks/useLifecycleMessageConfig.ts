"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SmartExtras } from "@/components/growth/SmartMessageFields";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "lifecycle-message-config";
const BG_CTX: RelayContext = { priority: "background" };

const LIFECYCLE_KINDS = [
  "expiry_message", "expired_message", "resubscribe_message", "birthday_message",
] as const;
export type LifecycleKind = (typeof LIFECYCLE_KINDS)[number];

export interface LifecycleFollowUp {
  text: string;
  delay_minutes: number;
}

export interface LifecycleMessage {
  variants: string[];
  follow_ups: LifecycleFollowUp[];
  discount: { percent: number; months: number } | null;
}

export interface LifecycleMessageConfig extends SmartExtras {
  enabled: boolean;
  text: string;
  hours: number | null;
  messages: LifecycleMessage[];
}

interface LifecycleMessageResponse {
  account_id: string;
  kind: LifecycleKind;
  config: LifecycleMessageConfig;
  defaults: LifecycleMessageConfig;
  refusal: string | null;
}

export interface LifecycleBuyer {
  fan_id: number;
  username: string | null;
  name: string | null;
  message: number;
  sent_at: string;
  spent_cents: number;
  purchases: number;
  last_purchase_at: string;
}

export function useLifecycleMessageConfig(accountId: string | null, kind: LifecycleKind) {
  return useQuery<LifecycleMessageResponse>({
    queryKey: [KEY, accountId, kind],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<LifecycleMessageResponse>(
        `/admin/lifecycle-message-config?account_id=${encodeURIComponent(accountId!)}&kind=${kind}`,
        BG_CTX,
      ),
    refetchOnWindowFocus: false,
  });
}

export function useSaveLifecycleMessageConfig(accountId: string | null, kind: LifecycleKind) {
  const qc = useQueryClient();
  return useMutation<{ account_id: string; config: LifecycleMessageConfig }, Error, Partial<LifecycleMessageConfig>>({
    mutationFn: (config) =>
      relay.put(`/admin/lifecycle-message-config`, { account_id: accountId, kind, config }, { cellAccountId: accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, accountId, kind] });
      qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
    },
  });
}

interface BuyersResponse {
  window_days: number;
  buyers: LifecycleBuyer[];
}

export function useLifecycleMessageBuyers(accountId: string | null, kind: LifecycleKind) {
  return useQuery<BuyersResponse>({
    queryKey: [KEY, "buyers", accountId, kind],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<BuyersResponse>(
        `/admin/lifecycle-message-config/buyers?account_id=${encodeURIComponent(accountId!)}&kind=${kind}`,
        BG_CTX,
      ),
    refetchOnWindowFocus: false,
  });
}
