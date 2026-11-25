"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface OwnerToken {
  id: number;
  name: string;
  hint: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

const KEY = ["owner-tokens"];

export function useOwnerTokens() {
  return useQuery<{ tokens: OwnerToken[] }>({
    queryKey: KEY,
    queryFn: () => relay.get<{ tokens: OwnerToken[] }>("/admin/owner-tokens"),
  });
}

export function useCreateOwnerToken() {
  const qc = useQueryClient();
  return useMutation<OwnerToken & { token: string }, Error, { name: string; days: number }>({
    mutationFn: (body) => relay.post<OwnerToken & { token: string }>("/admin/owner-tokens", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRevokeOwnerToken() {
  const qc = useQueryClient();
  return useMutation<OwnerToken, Error, number>({
    mutationFn: (id) => relay.delete<OwnerToken>(`/admin/owner-tokens/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}
