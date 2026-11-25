"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface TenantKeyStatus {
  set: boolean;
  hint: string;
}

export type TenantKeysStatus = Record<string, TenantKeyStatus>;

export interface SharedAccount {
  account_id: string;
  nickname: string;
  owners: string[];
  pays: Record<string, string>;
  // Both owners hold a key: the relay refuses rather than guess whose money it is, so AI on that provider stays stopped.
  contested: string[];
}

export interface TenantKeysResp {
  providers: TenantKeysStatus;
  shared_accounts?: SharedAccount[];
}

export function useTenantKeys() {
  return useQuery<TenantKeysResp>({
    queryKey: ["my-llm-keys"],
    queryFn: () => relay.get<TenantKeysResp>("/admin/my-llm-keys"),
    staleTime: 30_000,
  });
}

export function useSaveTenantKeys() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string>) =>
      relay.put<TenantKeysResp>("/admin/my-llm-keys", values),
    onSuccess: (data) => qc.setQueryData(["my-llm-keys"], data),
  });
}
