"use client";


import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { clearDraft, readDraft, stashDraft } from "@/lib/pendingDraft";

const KEY = "nudge-config";
const SAVE_KEY = [KEY, "save"];
const BG_CTX: RelayContext = { priority: "background" };

export interface NudgeSlotEntry {
  text: string[];
  image?: number[];
}
export type NudgeSlots = Record<string, Record<string, NudgeSlotEntry>>;

export interface NudgeConfig {
  enabled?: boolean;
  nudge_line_text?: boolean;
  nudge_line_image?: boolean;
  repeat_mode?: "new" | "same";
  delay_minutes?: number;
  jitter_minutes?: number;
  gap_minutes?: number;
  min_hours_between_nudges?: number;
  max_per_tick?: number;
  max_online_scan?: number;
  online_recent_minutes?: number;
  welcome_grace_hours?: number;
  active_convo_hours?: number;
  max_no_reply?: number;
  require_welcomed?: boolean;
  min_lifetime_spend_cents?: number | null;
  max_lifetime_spend_cents?: number | null;
  recent_spend_days?: number;
  min_recent_spend_cents?: number | null;
  max_recent_spend_cents?: number | null;
  quiet_hours?: [number, number];
  slots?: NudgeSlots;
}

export interface NudgeConfigWrite {
  account_id: string;
  config: NudgeConfig;
}

interface NudgeConfigResponse extends NudgeConfigWrite {
  defaults: NudgeConfig;
}

export function effectiveConfig(
  data: { defaults?: NudgeConfig; config?: NudgeConfig } | undefined,
): NudgeConfig {
  return { ...(data?.defaults ?? {}), ...(data?.config ?? {}) };
}

export const nudgeDraftKey = (accountId: string) => `chatterly:nudge-draft:${accountId}`;

export function useNudgeConfig(accountId: string | null) {
  return useQuery<NudgeConfigResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<NudgeConfigResponse>(
        `/admin/nudge-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useSaveNudgeConfig() {
  const qc = useQueryClient();
  return useMutation<NudgeConfigWrite, Error, NudgeConfigWrite>({
    mutationKey: SAVE_KEY,
    mutationFn: (vars) => {
      stashDraft(nudgeDraftKey(vars.account_id), {
        draft: vars.config, base: effectiveConfig(qc.getQueryData<NudgeConfigResponse>([KEY, vars.account_id])),
        at: Date.now(),
      });
      return relay.put(`/admin/nudge-config`, vars);
    },
    // Draft ack lives on the mutation, not mutate(): it must run after unmount; the stash drops only if still this PUT's.
    onSuccess: (echo, vars) => {
      const key = nudgeDraftKey(vars.account_id);
      const kept = clearDraft(key, vars.config) ? null : readDraft<NudgeConfig>(key);
      if (kept) {
        const d = qc.getQueryData<NudgeConfigResponse>([KEY, vars.account_id]);
        stashDraft(key, { ...kept, base: effectiveConfig({ defaults: d?.defaults, config: echo.config }) });
      }
      qc.setQueryData<NudgeConfigResponse>([KEY, vars.account_id], (old) =>
        old ? { ...old, config: echo.config } : old);
    },
    onSettled: (_r, _e, vars) => {
      qc.invalidateQueries({ queryKey: [KEY, vars.account_id] });
      qc.invalidateQueries({ queryKey: ["automation-rules", vars.account_id] });
    },
  });
}

export function useNudgeSavePending(accountId: string | null): boolean {
  const pending = useMutationState({
    filters: { mutationKey: SAVE_KEY, status: "pending" },
    select: (m) => (m.state.variables as NudgeConfigWrite).account_id,
  });
  return !!accountId && pending.includes(accountId);
}

export interface BulkApplyResult {
  applied: { account_id: string; rule: "created" | "updated" | "parked" | "unchanged" }[];
  count: number;
  enabled: boolean;
}

export interface NudgePreviewMessage {
  kind: "nudge" | string;
  text: string;
  media: number[];
}
export interface NudgePreviewResult {
  account_id: string;
  fan_id: FanId | null;
  slot: string;
  name: string;
  messages: NudgePreviewMessage[];
}

export function useNudgePreview() {
  return useMutation<
    NudgePreviewResult,
    Error,
    NudgeConfigWrite & { fan_id?: FanId | null; hour?: number | null; weekday?: string | null }
  >({
    mutationFn: (vars) => relay.post(`/admin/nudge-config/preview`, vars),
  });
}

export function useBulkApplyNudgeConfig() {
  const qc = useQueryClient();
  return useMutation<
    BulkApplyResult,
    Error,
    { account_ids: string[]; config: NudgeConfig }
  >({
    mutationFn: (vars) => relay.put(`/admin/nudge-config/bulk`, vars),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY] });
      qc.invalidateQueries({ queryKey: ["automation-rules"] });
    },
  });
}
