"use client";


import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Gran } from "@/components/stats/chart";
import { ssePoll } from "@/lib/events";
import { ofProfileQuery } from "@/hooks/useAccountAvatar";
import { cellMode, relay, type RelayContext } from "@/lib/relay";
import { REFRESH_KEYS } from "@/lib/screenBundle";
import { type FanId } from "@/lib/fanId";

const CACHE = {
  // Short so a chatter's fresh sale shows on next focus.
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

export interface EmployeeSalesPoint {
  start: string; revenue_cents: number; messages_cents: number; tips_cents: number;
}

export interface PerEmployeeResp {
  employees: PerEmployeeRow[];
  attribution_fallback: string | null;
}

export interface EmployeeSalesResp extends PerEmployeeResp {
  series: EmployeeSalesPoint[];
}

const ZERO_KIND: PerEmployeeRevenueByKind = { ppv: 0, tip: 0 };

export function usePerEmployee(
  from: string | null,
  to: string | null,
  byAccount: boolean = true,
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
  clocked_minutes: number | null;
  sales_per_clocked_hour_cents: number | null;
  messages_per_clocked_hour: number | null;
  fans_chatted_per_clocked_hour: number | null;
}

export interface ChattingStatsResp {
  employees: ChattingStatsRow[];
  attribution_fallback: string | null;
  chatter_ids: number[] | null;
}

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

export interface ChattingSeriesFigures {
  sales_cents: number;
  direct_messages_sent: number;
  direct_ppvs_sent: number;
  ppvs_unlocked: number;
  fans_chatted: number;
}

export interface ChattingSeriesPoint extends ChattingSeriesFigures {
  start: string;
}

export interface ChattingSeriesResp {
  bucket: Gran;
  series: ChattingSeriesPoint[];
  by_employee: Record<string, ChattingSeriesFigures[]>;
  attribution_fallback: string | null;
}

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


export interface PerModelRevenueByKind {
  ppv: number;
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
  // Same buckets over rows not yet 'cleared' (OF still settling); pending sales stay in totals.
  pending_by_kind: PerModelRevenueByKind;
  total_revenue_cents: number;
  total_net_revenue_cents: number;
  net_revenue_by_kind?: PerModelRevenueByKind;
  other_by_kind?: Partial<PerModelRevenueByKind>;
  net_other_by_kind?: Partial<PerModelRevenueByKind>;
  net_missing_count: number;
  pending_revenue_cents: number;
  pending_clears_by: string | null;
  refunded_cents?: number;
  refunded_net_cents?: number;
  messages_sent: number;
  ppvs_sent?: number;
  fans_chatted?: number;
  avg_reply_seconds?: number | null;
  ppv_conversions: number;
  new_subs_count: number;
  active_subs_count: number | null;
  ltv_cents: number | null;
  arpu_cents: number | null;
  spenders_count: number;
  avg_spend_per_spender_cents: number | null;
  avg_spend_per_transaction_cents: number | null;
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
        pending_by_kind: m.pending_by_kind ?? ZERO_MODEL_KIND,
      })),
    }),
    ...CACHE,
  });
}


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


export interface AutomationRunRow {
  id: number;
  account_id: string | null;
  kind: string;
  started_at: string | null;
  completed_at: string | null;
  status: string;
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
    refetchInterval: ssePoll(5 * 60_000, 60_000),
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}


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
  full_walk_failures: number;
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
    // eslint-disable-next-line local/no-fixed-polling -- ingest staleness grows with time, no event when a feed goes quiet
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


export type AttributeTo = number | "no_one" | null;

export function useAttributeTip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ txId, employeeId, accountId }: { txId: number; employeeId: AttributeTo; accountId: string }) =>
      cellMode()
        ? relay.post(
          `/admin/ingest/transactions/${txId}/attribute`,
          { employee_id: employeeId, account_id: accountId },
          { ...BG_CTX, accountId },
        )
        : relay.post(
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

export const MAX_BATCH = 500;

export interface SaleRef {
  txId: number;
  accountId: string;
}

interface BatchAttributeResp {
  updated: number;
  attributed_employee_id: number | null;
  tx_ids: number[];
  skipped_split: number;
}

const BATCH_ROUTE = "/admin/ingest/transactions/attribute";

export async function postBatchAttribute(
  { employeeId, sales, clockEventId }: { employeeId: AttributeTo; sales?: SaleRef[]; clockEventId?: number },
): Promise<BatchAttributeResp> {
  if (clockEventId != null) {
    return relay.post<BatchAttributeResp>(BATCH_ROUTE, { employee_id: employeeId, clock_event_id: clockEventId }, BG_CTX);
  }
  const refs = sales ?? [];
  if (!cellMode()) {
    return relay.post<BatchAttributeResp>(
      BATCH_ROUTE, { employee_id: employeeId, tx_ids: [...new Set(refs.map((r) => r.txId))] }, BG_CTX);
  }
  const byAccount = new Map<string, number[]>();
  for (const r of refs) {
    const ids = byAccount.get(r.accountId) ?? [];
    if (!ids.includes(r.txId)) ids.push(r.txId);
    byAccount.set(r.accountId, ids);
  }
  const answers = await Promise.all([...byAccount].map(([accountId, txIds]) => relay.post<BatchAttributeResp>(
    BATCH_ROUTE, { employee_id: employeeId, tx_ids: txIds, account_id: accountId }, { ...BG_CTX, accountId })));
  return {
    updated: answers.reduce((n, a) => n + a.updated, 0),
    attributed_employee_id: answers[0]?.attributed_employee_id ?? null,
    tx_ids: answers.flatMap((a) => a.tx_ids),
    skipped_split: answers.reduce((n, a) => n + a.skipped_split, 0),
  };
}

export function useBatchAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postBatchAttribute,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["shifts"] });
    },
  });
}


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


export interface OfProfile {
  id?: number;
  username?: string | null;
  name?: string | null;
  avatar?: string | null;
  avatarThumbs?: { c50?: string | null; c144?: string | null } | null;
  subscribePrice?: number | null;
  isFree?: boolean | null;
}

export function useAccountProfile(accountId: string | null | undefined) {
  return useQuery<OfProfile | null>({
    ...ofProfileQuery<OfProfile>(accountId),
    staleTime: 30 * 60_000,
    placeholderData: keepPreviousData,
  });
}


export interface OfSubscriberCounts {
  active: number;
  all: number;
  expired: number;
}

export function useOfSubscriberCounts(accountId: string | null | undefined) {
  return useQuery<OfSubscriberCounts | null>({
    queryKey: [REFRESH_KEYS.subscriberCounts, accountId] as const,
    enabled: !!accountId,
    queryFn: async ({ signal }) => {
      try {
        const r = await relay.get<{ subscribers?: Record<string, number> }>(
          "/api/of/v2/subscriptions/count/all",
          { accountId: accountId!, priority: "background" }, signal,
        );
        // subscribers.* = fans of this model; subscriptions.* is the other direction, never a fan count.
        const s = r?.subscribers ?? {};
        return {
          active: Number(s.active ?? 0),
          all: Number(s.all ?? 0),
          expired: Number(s.expired ?? 0),
        };
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

export function useOfNewFans(
  accountId: string | null | undefined,
  from: string | null,
  to: string | null,
) {
  return useQuery<number | null>({
    queryKey: [REFRESH_KEYS.newFans, accountId, from, to] as const,
    enabled: !!accountId,
    queryFn: async ({ signal }) => {
      try {
        const qs = new URLSearchParams();
        if (from) qs.set("start", from);
        if (to) qs.set("end", to);
        const r = await relay.get<{
          subscribers?: number;
          subscribes?: Array<{ count?: number }>;
        }>(
          `/api/of/v2/subscriptions/subscribers/chart?${qs.toString()}`,
          { accountId: accountId!, priority: "background" }, signal,
        );
        // `subscribers` is OF's own header count (right for free and paid pages); `earnings` is paid-only.
        if (typeof r?.subscribers === "number") return r.subscribers;
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


export type FanReportSort = "total" | "tips" | "ppv" | "subs";

export interface TopFanRow {
  account_id: string;
  fan_id: FanId;
  fan_name: string | null;
  username: string | null;
  total_cents: number;
  net_or_80_cents: number;
  tips_cents: number;
  ppv_cents: number;
  subs_cents: number;
  subscribed_at: string | null;
}
export interface TrafficRow {
  account_id: string;
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


export function useStatsRefresh() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["stats"] });
  };
}
