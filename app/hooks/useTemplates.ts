"use client";

/**
 * useTemplates — OF's message templates for one account (read-only).
 *
 * Each carries text + optional media + an optional `template` slot (currently
 * only `reply_on_subscribe` for the welcome message). Read through the
 * relay's `/api/of/v2/messages/templates` passthrough; the composer's
 * template picker lists them.
 */

import { useQuery } from "@tanstack/react-query";

import { relay, type OFMessageTemplate } from "@/lib/relay";

export function useTemplates(accountId: string | null) {
  return useQuery<OFMessageTemplate[]>({
    queryKey: ["templates", accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<OFMessageTemplate[]>("/api/of/v2/messages/templates", {
        accountId: accountId ?? undefined,
      }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
