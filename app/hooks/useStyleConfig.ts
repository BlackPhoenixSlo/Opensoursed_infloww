"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const KEY = "style-config";
const BG_CTX: RelayContext = { priority: "background" };

export interface StyleConfig {
  welcome_chatter_for_info?: boolean;
  autoreply?: boolean;
  strip_emojis?: boolean;
  factground_welcome_chatter_for_info?: boolean;
  painful_texting?: boolean;
  cat_stickers?: boolean;
  day_log_enabled?: boolean;
  cat_sticker_skip_pct?: number;
  cat_sticker_solo_pct?: number;
  cat_sticker_gap_min?: number;
  typos_welcome_chatter_for_info?: boolean;
  typos_autoreply?: boolean;
  nonnative_welcome_chatter_for_info?: boolean;
  nonnative_autoreply?: boolean;
  nonnative_spacing_welcome_chatter_for_info?: boolean;
  nonnative_spacing_autoreply?: boolean;
  // Only info-gather calls the pre-send consistency check (no consistency_autoreply: an unread flag is a checkbox that lies); it costs a second LLM call, so default OFF, never tri-state.
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
      relay.put(`/admin/style-config`, { account_id: accountId, config }, { cellAccountId: accountId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}
