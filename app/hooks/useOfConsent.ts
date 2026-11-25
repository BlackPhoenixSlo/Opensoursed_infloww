"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { relay } from "@/lib/relay";

const KEY = ["of-consent"] as const;

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

export function useSetOfConsent() {
  const qc = useQueryClient();
  return useMutation<OfConsent, Error, { accountId: string; autoAccept: boolean }>({
    mutationFn: ({ accountId, autoAccept }) => relay.put<OfConsent>(
      `/admin/of-consent/${encodeURIComponent(accountId)}`, { auto_accept: autoAccept }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
