"use client";

/**
 * useOwnerTokens — Settings → AI keys → Access tokens, the signed-in owner's own access tokens
 * (`Authorization: Bearer ifw_…` for an MCP client; service/owner_tokens_api.py).
 *
 *   GET    /admin/owner-tokens        { tokens: [...] } — hints only, never a token
 *   POST   /admin/owner-tokens        { name, days: 30|90|365 } → the row + `token`, shown once
 *   DELETE /admin/owner-tokens/{id}   revoke
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface OwnerToken {
  id: number;
  name: string;
  /** "ifw_…" + the last four. */
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
