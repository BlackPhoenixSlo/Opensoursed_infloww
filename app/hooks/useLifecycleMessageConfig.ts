"use client";

/**
 * useLifecycleMessageConfig — read/write one of Smart Messages' lifecycle
 * Triggers (Nearing expiry, Expired, Resubscribe, Birthday). The Relay keeps
 * each one's config in the account's rule of that kind
 * (`service/lifecycle_message_config_api.py`), so a save also refreshes the
 * automation-rules read the Automated Messages list is built on. Off by default.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SmartExtras } from "@/components/growth/SmartMessageFields";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "lifecycle-message-config";
const BG_CTX: RelayContext = { priority: "background" };

const LIFECYCLE_KINDS = [
  "expiry_message", "expired_message", "resubscribe_message", "birthday_message",
] as const;
export type LifecycleKind = (typeof LIFECYCLE_KINDS)[number];

/** A follow-up: sent `delay_minutes` after the message (or the follow-up
 *  before it) unless the fan has replied. */
export interface LifecycleFollowUp {
  text: string;
  delay_minutes: number;
}

/** One message of a Trigger. Each fan gets one message and one of its
 *  variants, picked at random; the discount is Nearing expiry only. */
export interface LifecycleMessage {
  variants: string[];
  follow_ups: LifecycleFollowUp[];
  discount: { percent: number; months: number } | null;
}

/** Also the Smart Message settings: media and price, frequency ("once" per
 *  fan ever, or "every" event), Effective / Expiry and Auto-unsend. */
export interface LifecycleMessageConfig extends SmartExtras {
  enabled: boolean;
  /** The first message's first variant, kept for older readers. */
  text: string;
  /** N hours: Nearing expiry 1..120, Expired 12..120; null for the others. */
  hours: number | null;
  messages: LifecycleMessage[];
}

interface LifecycleMessageResponse {
  account_id: string;
  kind: LifecycleKind;
  config: LifecycleMessageConfig;
  defaults: LifecycleMessageConfig;
}

/** A fan this Trigger messaged who spent within `window_days` of the send. */
export interface LifecycleBuyer {
  fan_id: number;
  username: string | null;
  name: string | null;
  /** 1-based: which of the Trigger's messages he got. */
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
      relay.put(`/admin/lifecycle-message-config`, { account_id: accountId, kind, config }),
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
