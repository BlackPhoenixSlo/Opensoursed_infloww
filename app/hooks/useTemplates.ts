"use client";


import { useQuery } from "@tanstack/react-query";

import { relay, type OFMessageTemplate } from "@/lib/relay";
import { useCan } from "@/hooks/useCan";

export function useTemplates(accountId: string | null) {
  const allowed = useCan(accountId, "native_templates");
  return useQuery<OFMessageTemplate[]>({
    queryKey: ["templates", accountId],
    enabled: !!accountId && allowed,
    queryFn: () =>
      relay.get<OFMessageTemplate[]>("/api/of/v2/messages/templates", {
        accountId: accountId ?? undefined,
      }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
