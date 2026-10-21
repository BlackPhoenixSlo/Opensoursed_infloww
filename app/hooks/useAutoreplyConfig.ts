"use client";

/**
 * useAutoreplyConfig — read/write account_ai_config.autoreply_config_json, the
 * per-account gate + knobs for the `autoreply` automation (Automations →
 * "Auto-reply").
 *
 * autoreply answers a fan nobody replied to: when he messaged and no one
 * answered within the delay, it sends ONE casual line (tone-matched to the
 * recent messages) — to the fans in the picked audience only. Default OFF.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const KEY = "autoreply-config";
const BG_CTX: RelayContext = { priority: "background" };

export interface AutoreplyConfig {
  enabled?: boolean;
  /** The reply delay: minutes he has waited before we answer. 0 = at once. */
  silence_min_minutes?: number;
  /** Top of the step-in range. Each waiting fan draws his own threshold in
   *  [silence_min, step_in_max]; 0 / absent / == silence_min = no spread. */
  step_in_max_minutes?: number;
  silence_max_minutes?: number;
  max_nudges?: number;
  min_gap_minutes?: number;
  last_n_messages?: number;
  /** Skip the "complete profile" gate — reply from the last few messages +
   *  whatever's already known, even for fans we don't fully know yet. */
  info_not_required?: boolean;
  /** [startHour, endHour] creator-local; null = 24/7 (never quiet). */
  quiet_hours_json?: [number, number] | null;
  /** WHO gets replies — a fan qualifies on EITHER source that is on. */
  /** (a) Folders: OF custom list ids. None picked = every fan. */
  folders_enabled?: boolean;
  list_ids?: number[];
  /** Folders only reply while his lifetime spend is under this; null = no cap. */
  folder_max_spend_cents?: number | null;
  /** (b) New fans: first seen under `new_fan_hours` ago AND spent under the cap. */
  new_fans_enabled?: boolean;
  new_fan_hours?: number;
  new_fan_max_spend_cents?: number;
  /** Describe the photo in the message being answered with the vision model
   *  (DeepInfra key). Default off. */
  describe_photos?: boolean;
  /** Skip a message that is only a photo, with no text. Default off. */
  skip_photo_only?: boolean;
}

/** Can this account bill the provider the engine calls? false = it skips. */
export interface AutoreplyKeyState {
  provider: string;
  available: boolean;
}

interface AutoreplyConfigResponse {
  account_id: string;
  config: AutoreplyConfig;
  defaults: AutoreplyConfig;
  llm_key?: AutoreplyKeyState;
  /** The vision provider "Describe photos fans send" bills (DeepInfra). */
  vision_key?: AutoreplyKeyState;
}

export function useAutoreplyConfig(accountId: string | null) {
  return useQuery<AutoreplyConfigResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<AutoreplyConfigResponse>(
        `/admin/autoreply-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
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
