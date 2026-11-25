"use client";


import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { switchPayload } from "@/components/growth/autoReplyForm";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "autoreply-config";
const BG_CTX: RelayContext = { priority: "background" };

export interface AutoreplyConfig {
  enabled?: boolean;
  silence_min_minutes?: number;
  step_in_max_minutes?: number;
  silence_max_minutes?: number;
  max_nudges?: number;
  min_gap_minutes?: number;
  last_n_messages?: number;
  info_not_required?: boolean;
  quiet_hours_json?: [number, number] | null;
  folders_enabled?: boolean;
  list_ids?: number[];
  folder_max_spend_cents?: number | null;
  new_fans_enabled?: boolean;
  new_fan_hours?: number;
  new_fan_max_spend_cents?: number;
  describe_photos?: boolean;
  skip_photo_only?: boolean;
}

export interface AutoreplyKeyState {
  provider: string;
  available: boolean;
}

interface AutoreplyConfigResponse {
  account_id: string;
  config: AutoreplyConfig;
  defaults: AutoreplyConfig;
  llm_key?: AutoreplyKeyState;
  vision_key?: AutoreplyKeyState;
}

const readConfig = (accountId: string) =>
  relay.get<AutoreplyConfigResponse>(`/admin/autoreply-config?account_id=${encodeURIComponent(accountId)}`, BG_CTX);

export function useAutoreplyConfig(accountId: string | null) {
  return useQuery<AutoreplyConfigResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () => readConfig(accountId!),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

// Fresh read: a PUT built on a stale cached copy would overwrite a config another tab or operator replaced.
function readAutoreplyConfigFresh(qc: QueryClient, accountId: string): Promise<AutoreplyConfigResponse> {
  return qc.fetchQuery({ queryKey: [KEY, accountId], queryFn: () => readConfig(accountId), staleTime: 0 });
}

export function useSwitchAutoreply(accountId: string) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, boolean>({
    mutationFn: async (on) => {
      const fresh = await readAutoreplyConfigFresh(qc, accountId);
      const config = switchPayload(fresh.defaults ?? {}, fresh.config ?? {}, on);
      if (!config) throw new Error("pick who gets replies (folders or new fans) and Save first");
      return relay.put(`/admin/autoreply-config`, { account_id: accountId, config });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useSaveAutoreplyConfig(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { account_id: string; config: AutoreplyConfig },
    Error,
    AutoreplyConfig
  >({
    mutationFn: (config) =>
      relay.put(`/admin/autoreply-config`, { account_id: accountId, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}
