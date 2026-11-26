"use client";


import { useIsFetching, useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const BG_CTX: RelayContext = { priority: "background" };

export interface BrainConfig {
  persona: string | null;
  location: string | null;
  persona_facts: Record<string, string>;
  language: string;
  // Save PUTs the whole config: a field this type drops is silently reset (a male creator back in the female lane).
  voice: string;
  timezone: string | null;
  utc_offset: number;
  daily_cost_cap_cents: number;
  model: string | null;
  reasoning_effort: string | null;
  model_by_purpose: Record<string, string>;
  time_activities: Record<string, string>;
  time_images: Record<string, number>;
  // Must stay on this type and travel with the form (Save PUTs it all); absent key = unchanged, shadow before enforce unless override rides the PUT.
  audience_mode: string;
  audience_of_list_id: number | null;
  audience_list_id?: number | null;
  audience_auto_add: boolean;
  audience_enforce_override?: boolean;
  // Server: absent key = unchanged, so an old client can't clear these while saving something else.
  cotag_tag_videos?: boolean;
  cotag_username?: string | null;
  model_notes?: string | null;
}

export interface PersonaFactField {
  key: string;
  label: string;
  operator_only: boolean;
  placeholder: string;
}

export interface LanguageOption {
  code: string;
  label: string;
}

export interface AccountConfigResp {
  account_id: string;
  config: BrainConfig;
  defaults: BrainConfig;
  // Read by the SELECTED voice: the dropdown is local until Save, so the stored column refilled a male account with the female brain.
  defaults_by_voice: Record<string, BrainConfig>;
  persona_fact_fields_by_voice: Record<string, PersonaFactField[]>;
  slots: string[];
  model_options: string[];
  default_model: string;
  effort_options: Record<string, string[]>;
  purposes: string[];
  purpose_defaults?: Record<string, string>;
  languages: LanguageOption[];
  persona_fact_fields: PersonaFactField[];
  model_notes_template?: string;
  ai_spend_today?: AiSpendToday;
}

export interface AiSpendToday {
  day: string;
  providers: { provider: string; spent_millicents: number; flagged: boolean }[];
}

export function useAccountConfig(accountId: string | null) {
  return useQuery<AccountConfigResp>({
    queryKey: ["account-config", accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<AccountConfigResp>(
        `/admin/account-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

// `cap`: only the cap card sends the cap (server: absent = unchanged), so a stale echoed cap can't undo a limit set elsewhere.
export function useSaveAccountConfig(accountId: string | null, { cap = false }: { cap?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation<{ account_id: string; config: BrainConfig }, Error, BrainConfig>({
    mutationKey: ["account-config", accountId],
    mutationFn: (config) => {
      const { daily_cost_cap_cents, ...rest } = config;
      return relay.put("/admin/account-config",
        { account_id: accountId, config: cap ? { ...rest, daily_cost_cap_cents } : rest }, { cellAccountId: accountId });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-config", accountId] });
      qc.invalidateQueries({ queryKey: ["ai-key-status", accountId] });
    },
  });
}

// Each PUT replaces the whole brain: two Saves on one page wait on this, or one lands on the other's stale copy.
export function useAccountConfigBusy(accountId: string | null) {
  return useIsMutating({ mutationKey: ["account-config", accountId] }) + useIsFetching({ queryKey: ["account-config", accountId] }) > 0;
}
