"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ofMeQuery } from "@/lib/ofMe";
import type { BundleForm, BundleSettings } from "@/lib/ofMirrorOffers";
import type { Bundle } from "@/lib/ofMirrorSubscription";
import { SUB_ROUTES } from "@/lib/ofSubRoutes";

import { relay, RelayError } from "@/lib/relay";
import type { LinkMetaPayload } from "@/components/growth/LinkMetaFields";
import { landed } from "@/components/growth/createPromotionForm";


const TRIAL_KEY = "trial-links";

export interface TrialLink {
  id: number | null;
  of_trial_id: number | null;
  name: string;
  url: string | null;
  subscribe_days: number;
  subscribe_counts: number;
  claim_counts: number;
  clicks_count: number | null;
  expired_at: string | null;
  status: "active" | "finished" | "unknown";
  created_at: string | null;
  source: "mirror" | "onlyfans";
  metrics: LinkFigures;
  promo_cost_cents: number | null;
  link_source: string | null;
  tags: string[];
  list_id?: string | null;
  list_name?: string | null;
  meta_saved?: boolean;
}

export interface LinkFigures {
  earnings_cents: number | null;
  earnings_net_cents: number | null;
  fans_who_spent: number | null;
  fans_counted: number | null;
  claimers: number | null;
  // Claimers OnlyFans sent no claim date for: spend unknown, not $0.
  spend_unknown: number;
  net_missing_count: number;
}

export interface MetricsState {
  metrics_updated_at: string | null;
  metrics_refreshing: boolean;
}

export interface TrialLinksResult extends MetricsState {
  links: TrialLink[];
  of_available: boolean;
  sources: string[];
  tags: string[];
}

export const GROWTH_VIEWED_REFRESH_MS = 3_600_000;

const whileRefreshing = (q: { state: { data?: Partial<MetricsState> } }) =>
  q.state.data?.metrics_refreshing ? 15_000 : GROWTH_VIEWED_REFRESH_MS;

export function useTrialLinks(accountId: string | null) {
  return useQuery<TrialLinksResult>({
    queryKey: [TRIAL_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- 15 s while the relay refreshes, else hourly while viewed
    refetchInterval: whileRefreshing,
    queryFn: () =>
      relay.get(`/admin/trial-links?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useCreateTrialLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    TrialLink, Error,
    {
      name: string; subscribe_days: number; subscribe_counts: number; expired_at?: string | null;
      expire_days?: number;
    } & Partial<LinkMetaPayload>
  >({
    mutationFn: (body) =>
      relay.post<TrialLink>("/admin/trial-links", { account_id: accountId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [TRIAL_KEY, accountId] }),
  });
}

export function useDeleteTrialLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/trial-links/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [TRIAL_KEY, accountId] }),
  });
}


const TRACK_KEY = "tracking-links";

export interface TrackingLink {
  id: number;
  account_id: string;
  name: string;
  slug: string;
  target_url: string;
  click_count: number;
  bot_check: boolean;
  path: string;
  created_at: string | null;
}

export interface TrackingLinksList {
  links: TrackingLink[];
  bot_check_available: boolean;
}

export type StatsDays = 7 | 30 | 90;

export interface StatsKeyRow { key: string; clicks: number }

export interface TrackingAnalytics {
  tz: string | null;
  from: string;
  to: string;
  days: StatsDays;
  series: Array<{ day: string; clicks: number }>;
  totals: { clicks: number; verified_clicks: number };
  opened_in: StatsKeyRow[];
  came_from: StatsKeyRow[];
  country: StatsKeyRow[];
}

export interface TrackingSummary {
  tz: string | null;
  today: string;
  clicks: { today: number; d7: number; d30: number };
  top: { id: number; name: string; clicks: number } | null;
  spark: Record<string, number[]>;
  verified_clicks: number;
}

export function useTrackingLinks(accountId: string | null) {
  return useQuery<TrackingLinksList>({
    queryKey: [TRACK_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    queryFn: async () => {
      const r = await relay.get<Partial<TrackingLinksList>>(
        `/admin/tracking-links?account_id=${encodeURIComponent(accountId!)}`,
      );
      return { links: r.links ?? [], bot_check_available: !!r.bot_check_available };
    },
  });
}

export function useCreateTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    TrackingLink, Error, { name: string; target_url: string; slug?: string; bot_check?: boolean }
  >({
    mutationFn: (body) =>
      relay.post<TrackingLink>("/admin/tracking-links", { account_id: accountId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [TRACK_KEY, accountId] }),
  });
}

export function useUpdateTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<TrackingLink, Error, { id: number; bot_check: boolean }>({
    mutationFn: ({ id, ...body }) => relay.patch<TrackingLink>(`/admin/tracking-links/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: [TRACK_KEY, accountId] }),
  });
}

export function useDeleteTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/tracking-links/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [TRACK_KEY, accountId] }),
  });
}

export function useTrackingSummary(accountId: string | null) {
  return useQuery<TrackingSummary>({
    queryKey: [TRACK_KEY, accountId, "summary"],
    enabled: !!accountId,
    staleTime: 15_000,
    queryFn: () => relay.get(`/admin/tracking-links/summary?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useTrackingAnalytics(accountId: string | null, linkId: number | null, days: StatsDays) {
  return useQuery<TrackingAnalytics>({
    queryKey: [TRACK_KEY, accountId, "analytics", linkId, days],
    enabled: !!accountId && !!linkId,
    staleTime: 15_000,
    queryFn: () =>
      relay.get(
        `/admin/tracking-links/${linkId}/analytics?account_id=${encodeURIComponent(accountId!)}&days=${days}`,
      ),
  });
}

const OF_TRACK_KEY = "of-tracking-links";

export interface OfTrackingLink {
  id: number | null;
  code: number | null;
  name: string;
  url: string | null;
  url_verified: boolean;
  clicks: number;
  subscribers: number;
  created_at: string | null;
  end_date: string | null;
  is_deleted: boolean;
  source: "onlyfans";
  earnings_cents?: number | null;
  fans_who_spent?: number | null;
  fans_counted?: number | null;
  earnings_partial?: boolean;
  promo_cost_cents?: number | null;
  link_source?: string | null;
  tags?: string[];
  list_id?: string | null;
  list_name?: string | null;
  meta_saved?: boolean;
}

export interface OfTrackingEarning {
  id: number;
  earnings_cents: number | null;
  earnings_net_cents: number | null;
  fans_who_spent: number | null;
  fans_counted: number | null;
  net_missing_count: number;
}

export interface OfTrackingEarnings {
  available: boolean;
  links: OfTrackingEarning[];
}

export interface OfTrackingFan {
  fan_id: number;
  name: string;
  username: string;
  total_cents: number; total_net_cents: number;
  subs_cents: number; subs_net_cents: number;
  posts_cents: number; posts_net_cents: number;
  messages_cents: number; messages_net_cents: number;
  streams_cents: number; streams_net_cents: number;
  tips_cents: number; tips_net_cents: number;
  other_cents: number; other_net_cents: number;
  net_missing_count: number;
  also_claimed_by: number[];
}

export interface OfTrackingFans {
  fans: OfTrackingFan[];
  counted_from: string | null;
}

export interface OfTrackingResult {
  links: OfTrackingLink[];
  username: string | null;
  url_verified: boolean;
  of_available: boolean;
  sources?: string[];
  tags?: string[];
}

export function useOfTrackingLinks(accountId: string | null) {
  return useQuery<OfTrackingResult>({
    queryKey: [OF_TRACK_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- hourly while Growth is viewed: the prewarm no longer reads it
    refetchInterval: GROWTH_VIEWED_REFRESH_MS,
    queryFn: () =>
      relay.get(`/admin/of-tracking-links?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useOfTrackingEarnings(accountId: string | null) {
  return useQuery<OfTrackingEarnings>({
    queryKey: [OF_TRACK_KEY, accountId, "earnings"],
    enabled: !!accountId,
    staleTime: 5 * 60_000,
    // eslint-disable-next-line local/no-fixed-polling -- hourly while Growth is viewed: the prewarm no longer reads it
    refetchInterval: GROWTH_VIEWED_REFRESH_MS,
    retry: false,
    queryFn: () =>
      relay.get(`/admin/of-tracking-links/earnings?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useOfTrackingFans(accountId: string | null, campaignId: number | null) {
  return useQuery<OfTrackingFans>({
    queryKey: [OF_TRACK_KEY, accountId, "fans", campaignId],
    enabled: !!accountId && campaignId != null,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: () =>
      relay.get(`/admin/of-tracking-links/${campaignId}/fans?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export type CreateOfTrackingLinkBody = { name: string } & Partial<Omit<LinkMetaBody, "kind" | "of_id">>;

export function useCreateOfTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<OfTrackingLink, Error, CreateOfTrackingLinkBody>({
    mutationFn: (body) =>
      relay.post<OfTrackingLink>("/admin/of-tracking-links", { account_id: accountId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [OF_TRACK_KEY, accountId] }),
  });
}

export function useDeleteOfTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) =>
      relay.delete(`/admin/of-tracking-links/${id}?account_id=${encodeURIComponent(accountId!)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [OF_TRACK_KEY, accountId] }),
  });
}


const PROMO_KEY = "promotions";

export interface PromoCampaign {
  id: number | null;
  of_promo_id: number | null;
  name: string;
  discount_percent: number | null;
  price_cents: number;
  subscribe_counts: number;
  subscribe_days: number;
  message: string | null;
  promo_type: string;
  status: string;
  subscriber_count: number;
  auto_reactivate: boolean;
  reactivate_count: number;
  last_reactivated_at: string | null;
  keep_blocked?: string | null;
  recreates_left?: number | null;
  preempt?: boolean;
  keep_wait?: string | null;
  keep_lines: { lead: string | null; text: string; off: boolean; until: string | null }[];
  created_at: string | null;
  source: "mirror" | "onlyfans";
  metrics?: LinkFigures;
}

export interface PromoListSetting {
  enabled: boolean;
  list_id: string | null;
  list_name: string | null;
}

const PROMO_LIST_KEY = "promo-list";

export function usePromoList(accountId: string | null) {
  return useQuery<PromoListSetting>({
    queryKey: [PROMO_LIST_KEY, accountId],
    enabled: !!accountId,
    staleTime: 60_000,
    queryFn: () => relay.get<PromoListSetting>(`/admin/promo-list?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useSavePromoList(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<PromoListSetting, Error, PromoListSetting>({
    mutationFn: (body) => relay.put<PromoListSetting>("/admin/promo-list", { account_id: accountId, ...body }),
    onSuccess: (saved) => qc.setQueryData([PROMO_LIST_KEY, accountId], saved),
  });
}

export function usePromotions(accountId: string | null) {
  return useQuery<{ campaigns: PromoCampaign[]; of_available: boolean } & Partial<MetricsState>>({
    queryKey: [PROMO_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- 15 s while the relay refreshes, else hourly while viewed
    refetchInterval: whileRefreshing,
    queryFn: () =>
      relay.get(`/admin/promotions?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export type PromoCreated = PromoCampaign & {
  auto_reactivate_refused?: string; create?: "unknown"; keep_running_taken_from?: { id: number; name: string } | null;
};

export function useCreatePromotion(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    PromoCreated, Error,
    {
      name: string; discount: number; subscribe_counts: number;
      subscribe_days: number; message?: string;
      promo_type?: string | string[];
      finish_days?: number;
      auto_reactivate?: boolean;
      recreate_limit?: number;
      preempt?: boolean;
      expect_taken_from?: number | null;
      resolve_open?: number;
    }
  >({
    mutationFn: (body) =>
      relay.post<PromoCreated>("/admin/promotions", { account_id: accountId, ...body }),
    onSuccess: () => invalidatePromos(qc, accountId),
    onError: (e) => { if (e instanceof RelayError && landed(e.body)) void invalidatePromos(qc, accountId); },
  });
}

export function useDeletePromotion(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/promotions/${id}`),
    onSettled: () => invalidatePromos(qc, accountId),
  });
}

function invalidatePromos(qc: ReturnType<typeof useQueryClient>, accountId: string | null) {
  void qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
  return qc.invalidateQueries({ queryKey: [PROMO_KEY, accountId] });
}

export function useSetPromoAutoReactivate(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { id: number; auto_reactivate: boolean; preempt: boolean }, Error,
    { id: number; auto_reactivate?: boolean; recreate_limit?: number; preempt?: boolean }
  >({
    mutationFn: ({ id, ...body }) => relay.patch(`/admin/promotions/${id}`, body),
    onSuccess: () => invalidatePromos(qc, accountId),
  });
}

export function useFinishPromotion(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, Pick<PromoCampaign, "id" | "of_promo_id" | "auto_reactivate">>({
    mutationFn: async (c) => {
      if (c.of_promo_id == null) throw new Error("This campaign is not linked to an OnlyFans promotion");
      if (c.id != null && c.auto_reactivate) await relay.patch(`/admin/promotions/${c.id}`, { auto_reactivate: false });
      return relay.post(`/api/of/v2/promotions/${c.of_promo_id}/finish`, undefined, { accountId });
    },
    onSettled: () => Promise.all([
      qc.invalidateQueries({ queryKey: [PROMO_KEY, accountId] }),
      qc.invalidateQueries({ queryKey: ["of-me", accountId] }),
    ]),
  });
}


export interface SpendBuckets {
  total_cents: number; total_net_cents: number;
  subs_cents: number; subs_net_cents: number;
  posts_cents: number; posts_net_cents: number;
  messages_cents: number; messages_net_cents: number;
  streams_cents: number; streams_net_cents: number;
  tips_cents: number; tips_net_cents: number;
  other_cents: number; other_net_cents: number;
  net_missing_count: number;
}

export interface LifetimeSpend {
  total_cents: number; subs_cents: number; posts_cents: number;
  messages_cents: number; streams_cents: number; tips_cents: number;
}

export interface LinkFan {
  fan_id: number;
  name: string;
  username: string;
  subscribe_at: string | null;
  first_seen_at: string | null;
  since: SpendBuckets | null;
  lifetime: LifetimeSpend | null;
}

export interface LinkFans {
  fans: LinkFan[];
  ledger_since: string | null;
  walked_at: string | null;
  refreshing: boolean;
}

export function useLinkFans(
  accountId: string | null, kind: "trial" | "promo", ofId: number | null,
  opts: { campaignId?: number | null; count?: number | null } = {},
) {
  const qs = new URLSearchParams({ account_id: accountId ?? "", kind, of_id: String(ofId ?? "") });
  if (opts.campaignId != null) qs.set("campaign_id", String(opts.campaignId));
  if (opts.count != null) qs.set("count", String(opts.count));
  return useQuery<LinkFans>({
    queryKey: ["link-fans", accountId, kind, ofId, opts.campaignId ?? null, opts.count ?? null],
    enabled: !!accountId && ofId != null,
    staleTime: 60_000,
    retry: false,
    // eslint-disable-next-line local/no-fixed-polling -- stops when the job ends
    refetchInterval: (q) => (q.state.data?.refreshing ? 15_000 : false),
    queryFn: () => relay.get(`/admin/link-metrics/fans?${qs}`),
  });
}

export type EditableKind = "trial" | "campaign";

export interface LinkMetaBody {
  kind: EditableKind;
  of_id: number;
  promo_cost: number | null;
  source: string | null;
  tags: string[];
  list_id?: string | null;
  list_name?: string | null;
}

export function useSaveLinkMeta(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, LinkMetaBody>({
    mutationFn: (body) => relay.put("/admin/link-meta", { account_id: accountId, ...body }),
    onSuccess: (_r, body) =>
      qc.invalidateQueries({ queryKey: [body.kind === "trial" ? TRIAL_KEY : OF_TRACK_KEY, accountId], exact: true }),
  });
}

export interface LinkMetaBatchBody {
  kind: EditableKind;
  of_ids: number[];
  promo_cost?: number | null;
  source?: string | null;
  tags?: string[];
}

export function useSaveLinkMetaBatch(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, LinkMetaBatchBody>({
    mutationFn: (body) => relay.put("/admin/link-meta/batch", { account_id: accountId, ...body }),
    onSuccess: (_r, body) =>
      qc.invalidateQueries({ queryKey: [body.kind === "trial" ? TRIAL_KEY : OF_TRACK_KEY, accountId], exact: true }),
  });
}


const SHARE_KEY = "link-shares";

export interface LinkShare {
  id: number;
  name: string;
  kind: EditableKind;
  path: string;
  of_ids: number[];
  include_earnings: boolean;
  created_at: string;
  expires_at: string;
  updated_at: string | null;
  status: "preparing" | "active" | "expired";
}

export function useLinkShares(accountId: string | null, kind: EditableKind) {
  return useQuery({
    queryKey: [SHARE_KEY, accountId, kind],
    queryFn: () => relay.get<{ shares: LinkShare[]; limit: number }>(
      `/admin/link-shares?account_id=${encodeURIComponent(accountId!)}&kind=${kind}`),
    enabled: !!accountId,
    retry: false,
  });
}

export function useCreateLinkShare(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<LinkShare, Error, { kind: EditableKind; name: string; of_ids: number[]; include_earnings: boolean }>({
    mutationFn: (body) => relay.post<LinkShare>("/admin/link-shares", { account_id: accountId, ...body }),
    onSuccess: async (_r, body) => {
      // A share's rows fill from the owner's links reads: refetch now so a new share gets rows sooner, then list the shares.
      await qc.refetchQueries({
        queryKey: body.kind === "trial" ? [TRIAL_KEY, accountId] : [OF_TRACK_KEY, accountId, "earnings"], exact: true,
      });
      await qc.invalidateQueries({ queryKey: [SHARE_KEY, accountId, body.kind] });
    },
  });
}

export function useRevokeLinkShare(accountId: string | null, kind: EditableKind) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/link-shares/${id}?account_id=${encodeURIComponent(accountId!)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [SHARE_KEY, accountId, kind] }),
  });
}


export function useOfMe(accountId: string | null) {
  return useQuery(ofMeQuery(accountId));
}

export function useBundleSettings(accountId: string | null) {
  return useQuery({
    queryKey: ["of-settings", "settings", accountId],
    queryFn: () => relay.get<BundleSettings>("/api/of/v2/users/me/settings", { accountId }),
    enabled: !!accountId,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

export function useSaveBundle(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, BundleForm & { id?: Bundle["id"] }>({
    mutationFn: ({ id, discount, duration }) =>
      id != null
        ? relay.put(`${SUB_ROUTES.bundles}/${id}`, { discount, duration }, { accountId })
        : relay.post(SUB_ROUTES.bundles, { discount, duration }, { accountId }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["of-me", accountId] }),
  });
}

export function useDeleteBundle(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, Bundle["id"]>({
    mutationFn: (id) => relay.delete(`${SUB_ROUTES.bundles}/${id}`, { accountId }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["of-me", accountId] }),
  });
}
