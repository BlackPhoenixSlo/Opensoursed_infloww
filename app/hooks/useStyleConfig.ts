"use client";

/**
 * useStyleConfig — read/write account_ai_config.style_config_json, the per-
 * automation opt-in for the "human texting style" package (short/casual girl
 * voice + 3-bubble splitting + casualized lowercase Q/Tease).
 *
 * Each flag gates ONE automation; when false that automation runs its current
 * prompt + 2-bubble cap unchanged. An absent key takes the per-automation
 * default (`_common._STYLE_DEFAULT_ON`): ON for autoreply, OFF for info-gather.
 * Surfaced in the Settings "Auto Convo" tab and, for autoreply, at the bottom of
 * My Automations > Auto-reply. Mirrors useAutoreplyConfig.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const KEY = "style-config";
const BG_CTX: RelayContext = { priority: "background" };

export interface StyleConfig {
  welcome_chatter_for_info?: boolean;
  autoreply?: boolean;
  // account-wide (not per-automation): strip every emoji at send time
  strip_emojis?: boolean;
  // Info-gather (welcome_chatter_for_info) rich-profile grounding — default ON
  factground_welcome_chatter_for_info?: boolean;
  // account-wide brevity/emotion framing ("painful texting") — default ON
  painful_texting?: boolean;
  // cat-sticker reaction pack (some chat replies end with a cat gif) — default ON
  cat_stickers?: boolean;
  /** Does the creator have a DAY the chat engines can answer with — "what are you
   *  up to?" gets something true and concrete instead of a bounced question.
   *  Account-wide (not per-automation) because the day belongs to the creator, not
   *  to whichever engine happened to answer. DEFAULT ON. */
  day_log_enabled?: boolean;
  // sticker rate knobs (numeric): % of replies that never see the pack (default 0),
  // % nudged to a gif-ONLY reply (default 5), per-fan minutes between gifs (default 0)
  cat_sticker_skip_pct?: number;
  cat_sticker_solo_pct?: number;
  cat_sticker_gap_min?: number;
  // independent thumb-typo injector toggle, per automation
  typos_welcome_chatter_for_info?: boolean;
  typos_autoreply?: boolean;
  // independent non-native English layer toggle, per automation
  nonnative_welcome_chatter_for_info?: boolean;
  nonnative_autoreply?: boolean;
  /** Space before "?" — "you like it ?". Part of the non-native register but its
   *  own key, so it can be turned off without losing the rest of the layer.
   *  Same tri-state default as its parent. */
  nonnative_spacing_welcome_chatter_for_info?: boolean;
  nonnative_spacing_autoreply?: boolean;
  // PHASE 2 pre-send self-consistency check. ONLY this engine calls it, so
  // there is deliberately no consistency_autoreply — a
  // flag nothing reads is a checkbox that lies. Costs a second LLM call on the
  // replies it fires for, so unlike the layers above it defaults OFF, never
  // tri-state.
  consistency_welcome_chatter_for_info?: boolean;
}

interface StyleConfigResponse {
  account_id: string;
  config: StyleConfig;
  defaults: StyleConfig;
}

export function useStyleConfig(accountId: string | null) {
  return useQuery<StyleConfigResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<StyleConfigResponse>(
        `/admin/style-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    // Short stale + always refetch on mount so the two surfaces that edit this
    // (the Auto Convo tab + the rule editor) always show the same fresh state.
    staleTime: 5_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
  });
}

export function useSaveStyleConfig(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { account_id: string; config: StyleConfig },
    Error,
    StyleConfig
  >({
    mutationFn: (config) =>
      relay.put(`/admin/style-config`, { account_id: accountId, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}
