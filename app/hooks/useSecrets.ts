"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export interface SecretKeyStatus {
  label: string;
  group: string;
  secret: boolean;
  multiline: boolean;
  help: string;
  set: boolean;
  clearable: boolean;
  source: "store" | "env" | "unset";
  hint: string;
}

export type SecretsStatus = Record<string, SecretKeyStatus>;
export interface SecretsResp {
  keys: SecretsStatus;
}

export function useSecrets() {
  return useQuery<SecretsResp>({
    queryKey: ["secrets"],
    queryFn: () => relay.get<SecretsResp>("/admin/secrets"),
    staleTime: 30_000,
  });
}

export function useSaveSecrets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string>) =>
      relay.put<SecretsResp>("/admin/secrets", values),
    onSuccess: (data) => qc.setQueryData(["secrets"], data),
  });
}
