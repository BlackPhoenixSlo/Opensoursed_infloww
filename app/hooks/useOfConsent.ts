"use client";

/**
 * useOfConsent — a Creator's "Auto-accept OnlyFans consent" switch
 * (`GET`/`PUT /admin/of-consent/{id}`, service/of_consent_api.py).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { relay } from "@/lib/relay";

const KEY = ["of-consent"] as const;

/** The switch (`auto_accept`), `required` while OF wants the consent form (the
 *  consent_required notice), `changed` the newest change (null: never set, off). */
export interface OfConsent {
  account_id: string;
  auto_accept: boolean;
  required: boolean;
  changed: { enabled: boolean; user_id: string | null; username: string | null;
             employee_id: number | null; at: string } | null;
}

export function useOfConsent(accountId: string) {
  const { user } = useUser();
  return useQuery<OfConsent>({
    queryKey: [...KEY, user?.user_id ?? "anon", accountId],
    queryFn: () => relay.get<OfConsent>(`/admin/of-consent/${encodeURIComponent(accountId)}`),
    staleTime: 0,
  });
}

/** `PUT /admin/of-consent/{id}` (owner only): one click turns it on or off. */
export function useSetOfConsent() {
  const qc = useQueryClient();
  return useMutation<OfConsent, Error, { accountId: string; autoAccept: boolean }>({
    mutationFn: ({ accountId, autoAccept }) => relay.put<OfConsent>(
      `/admin/of-consent/${encodeURIComponent(accountId)}`, { auto_accept: autoAccept }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
