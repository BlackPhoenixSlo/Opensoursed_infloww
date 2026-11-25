"use client";


import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay, type RelayContext } from "@/lib/relay";

const KEY = "automation-rules";
const BG_CTX: RelayContext = { priority: "background" };


interface KnobHint {
  key: string;
  type: "int" | "bool" | "str" | "ids" | "json";
  hint: string;
  widget?: "number" | "switch" | "text" | "ids" | "json" | "select" | "vault_media";
  min?: number;
  max?: number;
  default?: number | string | boolean;
  prefill?: boolean;
  enum?: (string | number)[];
}

export interface AutomationKind {
  kind: string;
  label: string;
  recurring: boolean;
  summary: string;
  knobs: KnobHint[];
  composer?: "mass_message" | "premade";
  surface?: string;
  cadence_default_s?: number;
  example?: string;
  group?: string;
}

export interface RuleLastRun {
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error_text: string | null;
  stats: Record<string, unknown> | null;
}

export interface Trigger {
  every_seconds?: number;
  daily_at?: string[];
  tz_offset_minutes?: number;
  max_runs?: number;
}

export interface AutomationRule {
  id: number;
  account_id: string;
  name: string;
  kind: string;
  is_enabled: boolean;
  every_seconds: number | null;
  trigger: Trigger;
  payload: Record<string, unknown>;
  quiet_hours: number[] | null;
  created_at: string | null;
  last_run: RuleLastRun | null;
  next_due_at: string | null;
  has_pending_job: boolean;
  sent?: number;
}


export function useAutomationKinds() {
  return useQuery<AutomationKind[]>({
    queryKey: ["automation-kinds"],
    queryFn: async () => {
      const r = await relay.get<{ kinds: AutomationKind[] }>(
        "/admin/automation-kinds",
        BG_CTX,
      );
      return r.kinds ?? [];
    },
    staleTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useAutomationRules(accountId: string | null) {
  return useQuery<AutomationRule[]>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: async () => {
      const r = await relay.get<{ rules: AutomationRule[] }>(
        `/admin/automation-rules?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      );
      return r.rules ?? [];
    },
    staleTime: 15_000,
    refetchInterval: ssePoll(5 * 60_000, 30_000),
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}


export interface RuleDraft {
  account_id: string;
  kind: string;
  name?: string | null;
  every_seconds?: number;
  trigger?: Trigger;
  payload?: Record<string, unknown>;
  quiet_hours?: number[];
  is_enabled?: boolean;
}

export interface RulePatch {
  name?: string;
  every_seconds?: number;
  trigger?: Trigger;
  payload?: Record<string, unknown>;
  quiet_hours?: number[];
  is_enabled?: boolean;
}

export function useCreateRule(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<AutomationRule, Error, RuleDraft>({
    mutationFn: (draft) =>
      relay.post<AutomationRule>("/admin/automation-rules", draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useUpdateRule(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<AutomationRule, Error, { id: number } & RulePatch>({
    mutationFn: ({ id, ...patch }) =>
      relay.patch<AutomationRule>(`/admin/automation-rules/${id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useSaveRule(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<AutomationRule, Error, { id: number; patch: RulePatch } | { create: RuleDraft }>({
    mutationFn: (req) => "create" in req
      ? relay.post<AutomationRule>("/admin/automation-rules", req.create)
      : relay.patch<AutomationRule>(`/admin/automation-rules/${req.id}`, req.patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useSwitchKind(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { action: string }, Error, { kind: string; enable: boolean }
  >({
    mutationFn: ({ kind, enable }) =>
      relay.post("/admin/automation-rules/switch",
        { account_id: accountId, kind, enable }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, accountId] });
      qc.resetQueries({ queryKey: ["lifecycle-message-config", accountId] });
      qc.resetQueries({ queryKey: ["purchase-followup-config", accountId] });
    },
  });
}

export function useDeleteRule(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/automation-rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useRunRuleNow(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { enqueued_job_id: number; kind: string },
    Error,
    number
  >({
    mutationFn: (id) =>
      relay.post(`/admin/automation-rules/${id}/run-now`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}
