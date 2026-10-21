"use client";

/**
 * useStats — data hooks for /stats dashboard.
 *
 * Endpoints (all under /admin/stats/*, fronted by the Next rewrite to the
 * Python relay):
 *   • /attribution-coverage         — coverage % per account + totals
 *   • /per-employee?by_account=…    — per-op revenue rollup
 *   • /per-model                    — per-account KPI grid
 *   • /attribution-coverage/recent  — most-recent unattributed sends
 *
 * Cache policy is intentionally short (30s stale) — chatters who just
 * made a sale should see it on the next focus, not 5 minutes later.
 * Every request is tagged `X-Priority: background` so dashboard polls
 * never starve user-initiated send_message calls in the relay's
 * upstream concurrency pool.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Gran } from "@/components/stats/chart";
import { ssePoll } from "@/lib/events";
import { relay, type RelayContext } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

const CACHE = {
  staleTime: 30_000,
  gcTime: 5 * 60_000,
  refetchOnWindowFocus: true as const,
  refetchOnMount: "always" as const,
  placeholderData: keepPreviousData,
};

const BG_CTX: RelayContext = { priority: "background" };

function dateParams(from: string | null, to: string | null): string {
  const qs = new URLSearchParams();
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// ── /admin/stats/attribution-coverage ────────────────────────────────

export interface CoverageAccountRow {
  account_id: string;
  display_name: string | null;
  outbound_total: number;
  attributed_count: number;
  attributed_to_human: number;
  attributed_to_automation: number;
  unattributed_count: number;
  coverage_pct: number;
}

export interface CoverageResp {
  from: string | null;
  to: string | null;
  automation_employee_present: boolean;
  per_account: CoverageAccountRow[];
  totals: { outbound_total: number; coverage_pct: number };
}

export function useAttributionCoverage(
  from: string | null,
  to: string | null,
  accountId?: string | null,
) {
  return useQuery<CoverageResp>({
    queryKey: ["stats", "coverage", from, to, accountId ?? null],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      if (accountId) qs.set("account_id", accountId);
      const s = qs.toString();
      return relay.get<CoverageResp>(
        `/admin/stats/attribution-coverage${s ? `?${s}` : ""}`,
        BG_CTX,
      );
    },
    ...CACHE,
  });
}

// ── /admin/stats/per-employee ────────────────────────────────────────

export interface PerEmployeeRevenueByKind {
  ppv: number;
  tip: number;
}

export interface PerEmployeeAccountRow {
  account_id: string | null;
  account_nickname: string | null;
  messages_sent: number;
  ppv_conversions: number;
  revenue_cents: number;
  revenue_by_kind: PerEmployeeRevenueByKind;
}

export interface PerEmployeeRow {
  employee_id: number | null;
  display_name: string | null;
  messages_sent: number;
  ppv_conversions: number;
  revenue_cents: number;
  revenue_by_kind: PerEmployeeRevenueByKind;
  per_account?: PerEmployeeAccountRow[];
}

export interface PerEmployeeResp {
  employees: PerEmployeeRow[];
  /** "Shift schedule needs Time tracking on; credited by Converters." while
   *  an Agency in scope has Shift schedule falling back, else null. */
  attribution_fallback: string | null;
}

const ZERO_KIND: PerEmployeeRevenueByKind = { ppv: 0, tip: 0 };

export function usePerEmployee(
  from: string | null,
  to: string | null,
  byAccount: boolean = true,
  /** "Show employees with chatter role only": the Employees holding the built-in Chatter role. */
  chatterOnly: boolean = false,
) {
  return useQuery<PerEmployeeResp>({
    queryKey: ["stats", "per-employee", from, to, byAccount, chatterOnly],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      if (byAccount) qs.set("by_account", "true");
      if (chatterOnly) qs.set("chatter_only", "true");
      return relay.get<PerEmployeeResp>(
        `/admin/stats/per-employee?${qs.toString()}`,
        BG_CTX,
      );
    },
    select: (data) => ({
      attribution_fallback: data.attribution_fallback ?? null,
      employees: (data.employees ?? []).map((r) => ({
        ...r,
        revenue_by_kind: r.revenue_by_kind ?? ZERO_KIND,
        per_account: r.per_account?.map((sub) => ({
          ...sub,
          revenue_by_kind: sub.revenue_by_kind ?? ZERO_KIND,
        })),
      })),
    }),
    ...CACHE,
  });
}

// ── /admin/stats/chatting-stats ──────────────────────────────────────

export interface ChattingStatsRow {
  employee_id: number;
  display_name: string | null;
  per_account: { account_id: string; account_nickname: string | null }[];
  sales_cents: number;
  ppv_sales_cents: number;
  tip_sales_cents: number;
  direct_message_sales_cents: number;
  mass_message_sales_cents: number;
  priority_mass_message_sales_cents: number;
  direct_messages_sent: number;
  direct_ppvs_sent: number;
  golden_ratio: number | null;
  ppvs_unlocked: number;
  unlock_rate: number | null;
  fans_chatted: number;
  fans_who_spent: number;
  fan_cvr: number | null;
  avg_spend_per_fan_cents: number | null;
  character_count: number;
  replies: number;
  avg_reply_seconds: number | null;
  /** Null for a chatter: clocked time is the Timesheet's, which refuses chatters. */
  clocked_minutes: number | null;
  sales_per_clocked_hour_cents: number | null;
  messages_per_clocked_hour: number | null;
  fans_chatted_per_clocked_hour: number | null;
}

export interface ChattingStatsResp {
  employees: ChattingStatsRow[];
  attribution_fallback: string | null;
}

/** Employee reports' Chatting statistics (roadmap W5 5.2); `chatterOnly` keeps the Chatter role's Employees. */
export function useChattingStats(from: string | null, to: string | null, chatterOnly: boolean = false,
  enabled: boolean = true) {
  return useQuery<ChattingStatsResp>({
    queryKey: ["stats", "chatting-stats", from, to, chatterOnly],
    queryFn: () => {
      const qs = dateParams(from, to);
      const only = chatterOnly ? `${qs ? "&" : "?"}chatter_only=true` : "";
      return relay.get<ChattingStatsResp>(`/admin/stats/chatting-stats${qs}${only}`, BG_CTX);
    },
    enabled,
    ...CACHE,
  });
}

/** A chart point's figures (`start` only on the summed series). */
export interface ChattingSeriesFigures {
  sales_cents: number;
  direct_messages_sent: number;
  direct_ppvs_sent: number;
  ppvs_unlocked: number;
  fans_chatted: number;
}

export interface ChattingSeriesPoint extends ChattingSeriesFigures {
  /** The bucket's start, wall time in the report time zone: "YYYY-MM-DDTHH:MM". */
  start: string;
}

export interface ChattingSeriesResp {
  bucket: Gran;
  /** Every Employee in scope summed. */
  series: ChattingSeriesPoint[];
  /** Each Employee's points by id, the same buckets in order. */
  by_employee: Record<string, ChattingSeriesFigures[]>;
  attribution_fallback: string | null;
}

/** Employee reports' charts (roadmap W5 5.10): chatting-stats per `bucket`, summed and per Employee, one read for
 *  the Overview and Employee performance tabs. */
export function useChattingSeries(from: string | null, to: string | null, bucket: Gran, chatterOnly: boolean = false) {
  const qs = new URLSearchParams(dateParams(from, to).replace(/^\?/, ""));
  qs.set("bucket", bucket);
  if (chatterOnly) qs.set("chatter_only", "true");
  return useQuery<ChattingSeriesResp>({
    queryKey: ["stats", "chatting-series", from, to, bucket, chatterOnly],
    queryFn: () => relay.get<ChattingSeriesResp>(`/admin/stats/chatting-stats?${qs}`, BG_CTX),
    ...CACHE,
  });
}

// ── /admin/stats/per-model ───────────────────────────────────────────

export interface PerModelRevenueByKind {
  ppv: number;
  /** Feed-post sales (ppv_post + tip_post) — broken out from ppv/tip. */
  post: number;
  tip: number;
  subscription: number;
  rebill: number;
  custom: number;
}

export interface PerModelRow {
  account_id: string;
  display_name: string | null;
  revenue_by_kind: PerModelRevenueByKind;
  /** Same 5 buckets as revenue_by_kind, but summed over rows whose
   *  status is not yet 'cleared' (OF still settling). Surfaced inline
   *  on each chip when > 0. */
  pending_by_kind: PerModelRevenueByKind;
  total_revenue_cents: number;
  /** OnlyFans' own post-fee net over the same rows (`transactions.net_cents`); VAT is not deducted. There is no
   *  net by kind. `net_missing_count` counts the rows with no net figure yet, which the net total leaves out. */
  total_net_revenue_cents: number;
  net_missing_count: number;
  /** Sum of amount_cents where status='loading' in the window. Always
   *  present (zero is a valid value). Renders as a dim sub-line under
   *  total revenue when > 0. */
  pending_revenue_cents: number;
  /** ISO-8601 timestamp; max(occurred_at + payout_pending_days) across
   *  this account's loading rows. Null when there are no pending rows. */
  pending_clears_by: string | null;
  /** The window's chargebacks and refunds (gross, and OnlyFans' net), dated by their sale. Optional: an older
   *  relay leaves them out. */
  refunded_cents?: number;
  refunded_net_cents?: number;
  messages_sent: number;
  /** With `engagement` only (Creator reports): of the Employees' own sends (no mass or automated message), the priced
   *  ones, the fans they went to (each once per Creator), and the replies' average wait in seconds, null with none
   *  (service/msg_stats.py). */
  ppvs_sent?: number;
  fans_chatted?: number;
  avg_reply_seconds?: number | null;
  ppv_conversions: number;
  new_subs_count: number;
  active_subs_count: number | null;
  ltv_cents: number | null;
  arpu_cents: number | null;
  /** The fans who bought content or tipped in the window (a subscription-only fan is no spender), and their spend
   *  over them and over their sales; null with none. */
  spenders_count: number;
  avg_spend_per_spender_cents: number | null;
  avg_spend_per_transaction_cents: number | null;
  /** OnlyFans' Statistics over the window's UTC days through yesterday (service/of_stats_daily.py), null unless every
   *  day is stored: Reach's profile visitors, the Subscriptions chart's Renews tab, its New tab over those visitors
   *  (%); the fans with renew on at the last day and their share of the roster then. */
  of_visitors: number | null;
  of_renewals: number | null;
  of_new_sub_conversion_pct: number | null;
  of_renew_on: number | null;
  of_renew_on_pct: number | null;
}

export interface PerModelResp {
  from: string | null;
  to: string | null;
  active_subs_source: "subscription_expires_at" | "unavailable" | string;
  per_model: PerModelRow[];
}

const ZERO_MODEL_KIND: PerModelRevenueByKind = {
  ppv: 0, post: 0, tip: 0, subscription: 0, rebill: 0, custom: 0,
};

/** `engagement` asks for the engagement columns too (two more message reads), which only Creator reports shows.
 *  `enabled` false holds the read (pending) until its window is known; with no window the Relay reads 30 days. */
export function usePerModel(
  from: string | null, to: string | null,
  { engagement = false, enabled = true }: { engagement?: boolean; enabled?: boolean } = {},
) {
  return useQuery<PerModelResp>({
    queryKey: ["stats", "per-model", from, to, engagement],
    enabled,
    queryFn: () => {
      const qs = dateParams(from, to);
      const extra = engagement ? `${qs ? "&" : "?"}engagement=true` : "";
      return relay.get<PerModelResp>(`/admin/stats/per-model${qs}${extra}`, BG_CTX);
    },
    select: (data) => ({
      ...data,
      per_model: (data.per_model ?? []).map((m) => ({
        ...m,
        revenue_by_kind: m.revenue_by_kind ?? ZERO_MODEL_KIND,
        // Older relay builds don't return pending_by_kind — coalesce so
        // chip rendering doesn't crash on undefined.
        pending_by_kind: m.pending_by_kind ?? ZERO_MODEL_KIND,
      })),
    }),
    ...CACHE,
  });
}

// ── /admin/stats/attribution-coverage/recent ─────────────────────────

export interface UnattributedRecentRow {
  account_id: string;
  fan_id: FanId | null;
  message_id: number | null;
  created_at: string | null;
  body: string;
  media_count: number;
}

export interface UnattributedRecentResp {
  messages: UnattributedRecentRow[];
}

export function useUnattributedRecent(limit: number = 20, enabled: boolean = false) {
  return useQuery<UnattributedRecentResp>({
    queryKey: ["stats", "unattributed-recent", limit],
    enabled,
    queryFn: () =>
      relay.get<UnattributedRecentResp>(
        `/admin/stats/attribution-coverage/recent?limit=${limit}`,
        BG_CTX,
      ),
    ...CACHE,
  });
}

// ── /admin/stats/automation-runs ─────────────────────────────────────
//
// Read-only audit log the automation executor writes (one row per run:
// kind, started/completed, status ∈ {running, ok, error}, stats_json TEXT
// verbatim, error_text). Most-recent first. Surfaced on /stats so each
// automation's last run / status / error is visible at a glance.

export interface AutomationRunRow {
  id: number;
  account_id: string | null;
  kind: string;
  started_at: string | null;
  completed_at: string | null;
  status: string;
  /** Runner-serialized JSON TEXT, returned verbatim. May be null. */
  stats_json: string | null;
  error_text: string | null;
}

export interface AutomationRunsResp {
  runs: AutomationRunRow[];
}

export function useAutomationRuns(limit: number = 200) {
  return useQuery<AutomationRunsResp>({
    queryKey: ["stats", "automation-runs", limit] as const,
    queryFn: () =>
      relay.get<AutomationRunsResp>(
        `/admin/stats/automation-runs?limit=${limit}`,
        BG_CTX,
      ),
    staleTime: 30_000,
    refetchInterval: ssePoll(5 * 60_000, 60_000), // SSE: rule_run_finished invalidates
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

// ── /admin/ingest/transactions/health ────────────────────────────────

export type IngestTier = "green" | "yellow" | "red";

export interface IngestAccountRow {
  account_id: string;
  display_name: string | null;
  last_scan_at: string | null;
  current_status: string;
  last_error: string | null;
  consecutive_failures: number;
  paused_until: string | null;
  rows_inserted_total: number;
  rows_patched_total: number;
  fully_backfilled: boolean;
  minutes_since_scan: number | null;
  tier: IngestTier;
}

export interface IngestHealthResp {
  overall_status: IngestTier;
  as_of: string;
  accounts: IngestAccountRow[];
}

const INGEST_HEALTH_KEY = ["stats", "ingest-health"] as const;

export function useIngestHealth() {
  return useQuery<IngestHealthResp>({
    queryKey: INGEST_HEALTH_KEY,
    queryFn: () =>
      relay.get<IngestHealthResp>(
        "/admin/ingest/transactions/health",
        BG_CTX,
      ),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

export function useIngestRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      relay.post(`/admin/ingest/transactions/${accountId}/run`, {}, BG_CTX),
    onSuccess: () => qc.invalidateQueries({ queryKey: INGEST_HEALTH_KEY }),
  });
}

export function useIngestPause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, hours }: { accountId: string; hours: number }) =>
      relay.post(
        `/admin/ingest/transactions/${accountId}/pause`,
        { duration_hours: hours },
        BG_CTX,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: INGEST_HEALTH_KEY }),
  });
}

export function useIngestResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      relay.post(`/admin/ingest/transactions/${accountId}/resume`, {}, BG_CTX),
    onSuccess: () => qc.invalidateQueries({ queryKey: INGEST_HEALTH_KEY }),
  });
}

// ── /admin/ingest/transactions/{id}/attribute + /attribute ──────────────

/** The attribute routes' `employee_id`: an Employee id, "no_one" (credited to nobody, roadmap W6 6.5) or null
 *  (the override cleared, so the Sales Settings rules credit the sale again). */
export type AttributeTo = number | "no_one" | null;

export function useAttributeTip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ txId, employeeId }: { txId: number; employeeId: AttributeTo }) =>
      relay.post(
        `/admin/ingest/transactions/${txId}/attribute`,
        { employee_id: employeeId },
        BG_CTX,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats", "orphan-tips"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

/** The most sales one batch reassign takes (the Relay's `sales_amend.MAX_BATCH`). */
export const MAX_BATCH = 500;

/** The batch reassign (roadmap W6 6.5): many sales by `txIds` (Sales records' selection) or one Clock event's
 *  sales by `clockEventId` (Shift records), every sale or none. A Clock event's split sales (Shift schedule shares
 *  with other Employees) are left as they are and counted in `skipped_split`. */
export function useBatchAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ employeeId, txIds, clockEventId }:
      { employeeId: AttributeTo; txIds?: number[]; clockEventId?: number }) =>
      relay.post<{ updated: number; attributed_employee_id: number | null; tx_ids: number[]; skipped_split: number }>(
        "/admin/ingest/transactions/attribute",
        clockEventId != null ? { employee_id: employeeId, clock_event_id: clockEventId }
          : { employee_id: employeeId, tx_ids: txIds },
        BG_CTX,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["shifts"] });
    },
  });
}

// ── /admin/ingest/transactions/sales-needing-attribution ─────────────
// Broader than orphan-tips: ALSO surfaces message-linked orphans (PPVs whose
// scraped message has no sender — the duplicate-price cases the auto-rule
// leaves ambiguous), each with the candidate 1:1 chatters to pick from.

export interface CandidateChatter {
  employee_id: number;
  name: string | null;
  last_at: string | null;
}
export interface SaleNeedingAttribution {
  id: number;
  account_id: string;
  fan_id: FanId | null;
  kind: string;
  status: string;
  amount_cents: number;
  occurred_at: string | null;
  description: string | null;
  attributed_employee_id: number | null;
  attributed_employee_name: string | null;
  candidate_chatters: CandidateChatter[];
}
export interface SalesNeedingAttributionResp {
  rows: SaleNeedingAttribution[];
}

export interface OrphanTipsOpts {
  from: string | null;
  to: string | null;
  includeAssigned: boolean;
}

export function useSalesNeedingAttribution(opts: OrphanTipsOpts) {
  const { from, to, includeAssigned } = opts;
  return useQuery<SalesNeedingAttributionResp>({
    queryKey: ["stats", "sales-attr", from, to, includeAssigned] as const,
    queryFn: () => {
      const qs = new URLSearchParams({ limit: "200" });
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      if (includeAssigned) qs.set("include_assigned", "true");
      return relay.get<SalesNeedingAttributionResp>(
        `/admin/ingest/transactions/sales-needing-attribution?${qs.toString()}`,
        BG_CTX,
      );
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

// ── Per-account OF profile (avatar + display name) ──────────────────
//
// /api/of/v2/users/me proxies to OF; takes X-Account-Id for scope.
// Cached aggressively because identity rarely changes — one OF call
// per account per ~30min. Failures swallowed so a broken session on
// one account doesn't blank out every model card on /stats.

export interface OfProfile {
  id?: number;
  username?: string | null;
  name?: string | null;
  avatar?: string | null;
  avatarThumbs?: { c50?: string | null; c144?: string | null } | null;
  /** OF's own truth: the model's monthly subscription price in cents,
   *  or null if subscriptions aren't enabled. 0 ≡ free page. */
  subscribePrice?: number | null;
  /** Convenience flag mirroring OF's profile view. True when subscribe
   *  is free (subscribePrice == 0). */
  isFree?: boolean | null;
}

export function useAccountProfile(accountId: string | null | undefined) {
  return useQuery<OfProfile | null>({
    queryKey: ["of-profile", accountId] as const,
    enabled: !!accountId,
    queryFn: async () => {
      try {
        return await relay.get<OfProfile>(
          "/api/of/v2/users/me",
          { accountId: accountId!, priority: "background" },
        );
      } catch {
        // Session expired / network blip / OF rate-limit — degrade
        // silently to "no profile" and let the card fall back to ID.
        return null;
      }
    },
    staleTime: 30 * 60_000,
    gcTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

// ── Live OF fan counts (the REAL numbers, not our thin DB roster) ─────
// OF's /subscriptions/count/all is ground truth for "how many fans" — the
// same population a mass message targets. Our `fans` table only holds fans
// we've actually chatted with (~hundreds), so per_model's transaction-
// derived sub counts read 0 for free pages that actually have thousands of
// fans. We pull the true count live per card (mirrors useAccountProfile).
//
//   subscribers.active = fans currently subscribed TO this model (the total)
//   subscribers.all    = active + expired (everyone who ever subscribed)
// `subscriptions.*` is the OTHER direction (creators the model follows) and
// must NOT be used as a fan count.

export interface OfSubscriberCounts {
  /** Currently-subscribed fans — the headline "total fans" number. */
  active: number;
  /** Ever-subscribed (active + expired + …). */
  all: number;
  expired: number;
}

export function useOfSubscriberCounts(accountId: string | null | undefined) {
  return useQuery<OfSubscriberCounts | null>({
    queryKey: ["of-sub-counts", accountId] as const,
    enabled: !!accountId,
    queryFn: async () => {
      try {
        const r = await relay.get<{ subscribers?: Record<string, number> }>(
          "/api/of/v2/subscriptions/count/all",
          { accountId: accountId!, priority: "background" },
        );
        const s = r?.subscribers ?? {};
        return {
          active: Number(s.active ?? 0),
          all: Number(s.all ?? 0),
          expired: Number(s.expired ?? 0),
        };
      } catch {
        // Session expired / rate-limit — degrade to null so the card shows
        // "—" for this account instead of blanking the whole grid.
        return null;
      }
    },
    staleTime: 30 * 60_000,
    gcTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

// New fans in a window, from OF's Statistics > Subscriptions chart
// (/subscriptions/subscribers/chart). The response carries TWO series:
//   • earnings   — new PAID subs (revenue-based; 0 for free pages)  ← NOT this
//   • subscribes — new subscriber COUNT per day (free-inclusive)    ← this
// plus a top-level `subscribers` == sum(subscribes[].count) — OF's own
// "N Subscribers" header. We use `subscribers`, so it's correct for BOTH
// free and paid pages (one account free = 279, one account paid = 113). `from`/`to` are
// the dashboard's ISO window (defaults to last 30 days upstream).
export function useOfNewFans(
  accountId: string | null | undefined,
  from: string | null,
  to: string | null,
) {
  return useQuery<number | null>({
    queryKey: ["of-new-fans", accountId, from, to] as const,
    enabled: !!accountId,
    queryFn: async () => {
      try {
        const qs = new URLSearchParams();
        if (from) qs.set("start", from);
        if (to) qs.set("end", to);
        const r = await relay.get<{
          subscribers?: number;
          subscribes?: Array<{ count?: number }>;
        }>(
          `/api/of/v2/subscriptions/subscribers/chart?${qs.toString()}`,
          { accountId: accountId!, priority: "background" },
        );
        if (typeof r?.subscribers === "number") return r.subscribers;
        // Fallback: sum the per-day subscriber-count series.
        const arr = Array.isArray(r?.subscribes) ? r.subscribes : [];
        return arr.reduce((sum, pt) => sum + Number(pt?.count ?? 0), 0);
      } catch {
        return null;
      }
    },
    staleTime: 30 * 60_000,
    gcTime: 24 * 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

// ── Per-fan user data (fan profiles + spend, read from our DB) ───

export interface FanDataRow {
  account_id: string;
  fan_name: string;
  fan_id: FanId;
  chat_id: number;
  nickname: string;
  short_bio: string;
  bullet_points: string;
  q1: string; q2: string; q3: string;
  tease1: string; tease2: string; tease3: string;
  total_spend: number;
  message_count: number;
  last_updated: string;
  note_on_of: string;
  language?: string | null;
}
export interface FanDataResp {
  rows: FanDataRow[];
  count: number;
  columns: string[];
}

/** Per-fan profile data (User data), read live from our DB, for one Creator. */
export function usePerFanData(accountId: string, limit = 2000) {
  return useQuery<FanDataResp>({
    queryKey: ["stats", "per-fan-data", accountId, limit] as const,
    queryFn: () => {
      const qs = new URLSearchParams();
      qs.set("account_id", accountId);
      qs.set("limit", String(limit));
      return relay.get<FanDataResp>(`/admin/stats/per-fan-data?${qs.toString()}`, BG_CTX);
    },
    ...CACHE,
  });
}

// ── /admin/stats/fan-report (Fan reports: Top fans, Traffic, New fans) ─

export type FanReportSort = "total" | "tips" | "ppv" | "subs";

export interface TopFanRow {
  account_id: string;
  fan_id: FanId;
  fan_name: string | null;
  username: string | null;
  total_cents: number;
  /** OF's net, else 80% of gross where OF gave none (net_or_80). */
  net_or_80_cents: number;
  tips_cents: number;
  ppv_cents: number;
  subs_cents: number;
  /** His current subscription's start on OF's roster; null when never crawled. */
  subscribed_at: string | null;
}
export interface TrafficRow {
  account_id: string;
  /** null = spenders who claimed no stored trial link or promotion. */
  kind: "trial" | "promo" | null;
  of_id: number | null;
  name: string | null;
  source: string | null;
  fans: number;
  total_cents: number;
}
export interface FanGrowthRow {
  day: string;
  new_fans: number;
  renewed_fans: number;
}
export interface FanReportResp {
  top_fans: TopFanRow[];
  traffic: TrafficRow[];
  growth: FanGrowthRow[];
}

/** The query string `/admin/stats/fan-report` reads (the CSV link reuses it). */
export function fanReportQuery(
  from: string | null, to: string | null, accountId: string, sort: FanReportSort,
): URLSearchParams {
  const qs = new URLSearchParams();
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  qs.set("account_id", accountId);
  qs.set("sort", sort);
  return qs;
}

/** Fan reports over the window, for one Creator. */
export function useFanReport(
  from: string | null, to: string | null, accountId: string, sort: FanReportSort,
) {
  return useQuery<FanReportResp>({
    queryKey: ["stats", "fan-report", from, to, accountId, sort] as const,
    queryFn: () => relay.get<FanReportResp>(
      `/admin/stats/fan-report?${fanReportQuery(from, to, accountId, sort).toString()}`, BG_CTX),
    ...CACHE,
  });
}

// ── Manual refresh ───────────────────────────────────────────────────

/** Invalidate every stats query — bound to the header refresh button so
 *  a chatter who just made a sale can force the next render to be live. */
export function useStatsRefresh() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["stats"] });
  };
}
