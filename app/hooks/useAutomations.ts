"use client";

/**
 * useAutomations — the data layer for the /automations control surface.
 *
 * Reads/writes the `automation_rules` table via the relay's
 * /admin/automation-rules/* routes. A "rule" is one automation_rules row: a
 * kind + an `every_seconds` cadence + a JSON `payload` (the per-run knob bag) +
 * an enabled flag. The executor materialises every enabled rule on its cadence;
 * `runNow` enqueues one immediate job, bypassing the timer.
 *
 * Per-account list (owner-only routes; a chatter session 403s). Mutations
 * invalidate the per-account list so the table reflects the new state.
 */

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

// ── Types (mirror automation_rules_api.py) ────────────────────────────

interface KnobHint {
  key: string;
  type: "int" | "bool" | "str" | "ids" | "json";
  hint: string;
  /** Input widget the editor renders (derived from `type` server-side). */
  widget?: "number" | "switch" | "text" | "ids" | "json" | "select" | "vault_media";
  min?: number;
  max?: number;
  default?: number | string | boolean;
  /** Seed the editor field with `default` when the payload has no value. */
  prefill?: boolean;
  /** Allowed values for a "select"/str knob. */
  enum?: (string | number)[];
}

export interface AutomationKind {
  kind: string;
  label: string;
  /** false = action-style kind (does nothing on a bare timer without a payload). */
  recurring: boolean;
  summary: string;
  knobs: KnobHint[];
  /** When set, the editor builds this kind's whole payload with the named rich
   *  composer (instead of the per-knob fields). The knobs stay as the raw-JSON
   *  fallback. See automation_rules_api._CATALOG. */
  composer?: "mass_message" | "premade";
  /** Which control surface this kind belongs to: "rules" | "brain" | "ready_made"
   *  | "settings" | "internal". The /automations rule editor only lists "rules"
   *  kinds; everything else is driven from its own surface. */
  surface?: string;
  /** Suggested default cadence (seconds) for a NEW rule of this kind. The editor
   *  seeds the cadence field from it on kind-pick; absent → fall back to 300. */
  cadence_default_s?: number;
  /** One-line "good settings" example shown under the kind picker. */
  example?: string;
  /** Editor grouping for the kind dropdown: "advanced" → utility optgroup;
   *  absent / anything else → "core". */
  group?: string;
}

export interface RuleLastRun {
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error_text: string | null;
  stats: Record<string, unknown> | null;
}

/** Rich trigger (mirrors automation_rules_api._validate_trigger). Exactly one
 *  of `every_seconds` (interval) or `daily_at` (clock times) drives cadence;
 *  `max_runs` optionally auto-disables the rule after N total runs. */
export interface Trigger {
  every_seconds?: number;
  daily_at?: string[];            // ["09:00","20:30"] in the local zone
  tz_offset_minutes?: number;     // minutes to add to UTC for local
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
  /** Opt-in quiet hours [start, end] in creator-local hours; null = off (24/7). */
  quiet_hours: number[] | null;
  created_at: string | null;
  last_run: RuleLastRun | null;
  next_due_at: string | null;
  has_pending_job: boolean;
  /** List read only, Smart Messages' rules (welcome, purchase, lifecycle): the
   *  messages it really sent — fans welcomed, for a welcome. Absent elsewhere. */
  sent?: number;
}

// ── Reads ─────────────────────────────────────────────────────────────

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
    // The catalog is process-static — refetch rarely.
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
    // Poll so a running/last-run state refreshes without a manual reload;
    // while SSE is live, rule_run_finished invalidates and this is a safety net.
    staleTime: 15_000,
    refetchInterval: ssePoll(5 * 60_000, 30_000),
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

// ── Writes ────────────────────────────────────────────────────────────

export interface RuleDraft {
  account_id: string;
  kind: string;
  name?: string | null;
  every_seconds?: number;
  trigger?: Trigger;              // wins over every_seconds when present
  payload?: Record<string, unknown>;
  quiet_hours?: number[];         // [start, end] local hours; omit/[0,0] = off
  is_enabled?: boolean;
}

export interface RulePatch {
  name?: string;
  every_seconds?: number;
  trigger?: Trigger;
  payload?: Record<string, unknown>;
  quiet_hours?: number[];         // [0,0] clears, [start, end] sets
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

/** Turn a KIND on/off for the account — one request, whatever the account's rule
 *  rows happen to look like. The client used to decide this itself (create vs.
 *  wake vs. park-them-all, and the cadence a new row gets), which meant two
 *  copies of one policy either side of the wire and N requests to park N rows.
 *  The server owns it now: `automation_rules_api.ensure_kind_rule`. */
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
      // The Smart Messages editors seed their form from these reads once, on
      // open: dropping the cached copy makes the next open wait for the rule as
      // it is now, not show a stale "On" and save it back.
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
