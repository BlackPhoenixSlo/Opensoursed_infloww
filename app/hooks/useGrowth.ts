"use client";

/**
 * useGrowth — data layer for the Growth surfaces that mirror OnlyFans state:
 * Free-Trial links, Tracking/UTM links, and Profile-Promotion campaigns.
 *
 * All three hit owner-gated /admin/* relay routes. Trial + Promo are light
 * mirrors over OF (OF is source of truth; a local row keeps the operator's
 * name + last-seen usage). Tracking links are fully internal (public
 * /t/{slug} redirect + click analytics).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import type { BundleForm, BundleSettings } from "@/lib/ofMirrorOffers";
import { SUB_ROUTES, type Bundle } from "@/lib/ofMirrorSubscription";

import { relay } from "@/lib/relay";
import type { LinkMetaPayload } from "@/components/growth/LinkMetaFields";

// ── Free-trial links ──────────────────────────────────────────────────

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
  /** "unknown" when OF didn't return this link, so its state can't be read. */
  status: "active" | "finished" | "unknown";
  created_at: string | null;
  source: "mirror" | "onlyfans";
  /** Infloww's per-link figures, from the relay's cache (see LinkFigures). */
  metrics: LinkFigures;
  /** The Edit dialog's fields, kept by the relay (never written to OnlyFans). */
  promo_cost_cents: number | null;
  link_source: string | null;
  tags: string[];
  /** The OnlyFans list the link's claimers are added to (OnlyFans' own add-to-list), and its name when picked. */
  list_id?: string | null;
  list_name?: string | null;
  /** The create's reply only: false when OnlyFans' reply had no id, so Source, Promo cost, Tag and List weren't kept. */
  meta_saved?: boolean;
}

/**
 * A Free trial link's or promotion's figures (relay `link_metrics`): its claimers' spend in our ledger since each
 * claimed, refunds and chargebacks left out. Cents. Every value null while the link's claimers were never read (the
 * UI's "—"); `earnings_*` null too when OnlyFans sent no claim date for any claimer.
 */
export interface LinkFigures {
  earnings_cents: number | null;
  earnings_net_cents: number | null;
  /** Claimers with any spend (Spend/Claim's numerator). */
  fans_who_spent: number | null;
  /** Claimers whose spend is known: Spend/Claim's and AEPS's denominator. */
  fans_counted: number | null;
  claimers: number | null;
  /** Claimers OnlyFans sent no claim date for: their spend is unknown, not $0. */
  spend_unknown: number;
  net_missing_count: number;
}

/** The cached figures' state on a list read: when they were last checked against OnlyFans, and whether a refresh
 *  is running (the list refetches until it is done). */
export interface MetricsState {
  metrics_updated_at: string | null;
  metrics_refreshing: boolean;
}

export interface TrialLinksResult extends MetricsState {
  links: TrialLink[];
  of_available: boolean;
  /** The account's Sources and Tags in use on any link: the Edit dialog's suggestions and the filters' options. */
  sources: string[];
  tags: string[];
}

/** While the relay refreshes the cached figures, read the list again shortly. */
const whileRefreshing = (q: { state: { data?: Partial<MetricsState> } }) =>
  q.state.data?.metrics_refreshing ? 15_000 : false;

export function useTrialLinks(accountId: string | null) {
  return useQuery<TrialLinksResult>({
    queryKey: [TRIAL_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
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
      /** Offer expiration in days, 0 = none (OF's expireDays). */
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

// ── Tracking / UTM links ──────────────────────────────────────────────

const TRACK_KEY = "tracking-links";

export interface TrackingLink {
  id: number;
  account_id: string;
  name: string;
  slug: string;
  target_url: string;
  click_count: number;
  path: string;
  created_at: string | null;
}

export interface TrackingAnalytics {
  link: TrackingLink;
  total_clicks: number;
  recent: Array<{ clicked_at: string | null; referer: string | null }>;
  by_day: Array<{ day: string; clicks: number }>;
  subscribers: number | null;
  revenue_cents: number | null;
}

export function useTrackingLinks(accountId: string | null) {
  return useQuery<TrackingLink[]>({
    queryKey: [TRACK_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    queryFn: async () => {
      const r = await relay.get<{ links: TrackingLink[] }>(
        `/admin/tracking-links?account_id=${encodeURIComponent(accountId!)}`,
      );
      return r.links ?? [];
    },
  });
}

export function useCreateTrackingLink(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    TrackingLink, Error, { name: string; target_url: string; slug?: string }
  >({
    mutationFn: (body) =>
      relay.post<TrackingLink>("/admin/tracking-links", { account_id: accountId, ...body }),
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

export function useTrackingAnalytics(accountId: string | null, linkId: number | null) {
  return useQuery<TrackingAnalytics>({
    queryKey: [TRACK_KEY, "analytics", accountId, linkId],
    enabled: !!accountId && !!linkId,
    staleTime: 15_000,
    queryFn: () =>
      relay.get(
        `/admin/tracking-links/${linkId}/analytics?account_id=${encodeURIComponent(accountId!)}`,
      ),
  });
}

// ── OnlyFans-native tracking links (/campaigns) ───────────────────────
// These are OF's OWN tracking links: OF reports real clicks AND how many of
// those clicks subscribed — attribution the internal /t/ redirect can't have.
const OF_TRACK_KEY = "of-tracking-links";

export interface OfTrackingLink {
  id: number | null;
  code: number | null;
  name: string;
  url: string | null;
  /** True: the URL is built exactly as OnlyFans' own Copy-link builds it. */
  url_verified: boolean;
  clicks: number;
  subscribers: number;
  created_at: string | null;
  /** When OnlyFans ended the link (set on a deleted one). */
  end_date: string | null;
  /** Deleted on OnlyFans: Infloww's "Deactivated". The read keeps it, with its counts. */
  is_deleted: boolean;
  source: "onlyfans";
  /** Merged in client-side from the earnings read (`useOfTrackingEarnings`), gross or net as "Show net earnings"
   *  picks; absent or null while that read has no figure for the link (the UI's "—"). */
  earnings_cents?: number | null;
  fans_who_spent?: number | null;
  /** The link's claimers: the denominator of Spending CVR and AEPS. */
  fans_counted?: number | null;
  /** Net is on and some of the link's transactions have no net figure from OnlyFans yet, so net is understated. */
  earnings_partial?: boolean;
  /** The Edit dialog's fields, kept by the relay (never written to OnlyFans). */
  promo_cost_cents?: number | null;
  link_source?: string | null;
  tags?: string[];
  list_id?: string | null;
  list_name?: string | null;
  /** On a create's reply: false when OnlyFans returned no id, so the Edit fields were not stored. */
  meta_saved?: boolean;
}

/** One link's earnings: its fans' spend from our transactions ledger, from the link's creation on. */
export interface OfTrackingEarning {
  id: number;
  /** null: OnlyFans failed on this link's fan list. */
  earnings_cents: number | null;
  earnings_net_cents: number | null;
  /** Fans who spent beyond the subscription (Infloww's Spending CVR numerator). */
  fans_who_spent: number | null;
  /** The fans OnlyFans lists under this link (its claimers). */
  fans_counted: number | null;
  /** Transactions with no net figure yet: the net sum leaves them out. */
  net_missing_count: number;
}

export interface OfTrackingEarnings {
  /** false: OnlyFans was unreachable; every earnings cell is "—". */
  available: boolean;
  links: OfTrackingEarning[];
}

/** Details overlay: one fan of a link, spend in cents by kind, gross and `_net`. */
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
  /** The fan's other links: their spend is split by time between them, each row holding this link's share. */
  also_claimed_by: number[];
}

export interface OfTrackingFans {
  fans: OfTrackingFan[];
  /** When the figures can start (ISO): the later of the link's creation and our ledger's first row. */
  counted_from: string | null;
}

export interface OfTrackingResult {
  links: OfTrackingLink[];
  username: string | null;
  url_verified: boolean;
  of_available: boolean;
  /** The account's Sources and Tags in use on any link (absent while OnlyFans is unreachable). */
  sources?: string[];
  tags?: string[];
}

export function useOfTrackingLinks(accountId: string | null) {
  return useQuery<OfTrackingResult>({
    queryKey: [OF_TRACK_KEY, accountId],
    enabled: !!accountId,
    staleTime: 30_000,
    queryFn: () =>
      relay.get(`/admin/of-tracking-links?account_id=${encodeURIComponent(accountId!)}`),
  });
}

/** Per-link earnings. Slower than the list (it reads every link's fan list from OnlyFans, cached on the relay), so
 *  it is its own read: the list shows at once and the earnings columns fill in when this lands. */
export function useOfTrackingEarnings(accountId: string | null) {
  return useQuery<OfTrackingEarnings>({
    queryKey: [OF_TRACK_KEY, accountId, "earnings"],
    enabled: !!accountId,
    staleTime: 5 * 60_000,
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

/** Create on OnlyFans by name; the Edit dialog's fields ride along and are stored for the new link. */
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

// ── Profile promotion campaigns ───────────────────────────────────────

const PROMO_KEY = "promotions";

export interface PromoCampaign {
  id: number | null;
  of_promo_id: number | null;
  name: string;
  /** Percent off the subscription (OF contract). null for OF-only rows (OF
   *  doesn't echo the discount on list). */
  discount_percent: number | null;
  price_cents: number;
  subscribe_counts: number;
  subscribe_days: number;
  message: string | null;
  promo_type: string;
  status: string;
  /** People who claimed the promo (OF `claimsCount`). */
  subscriber_count: number;
  /** When on, the promo_reactivate automation re-creates this campaign each
   *  time OnlyFans marks it finished. Only mirror-backed rows can opt in. */
  auto_reactivate: boolean;
  /** How many times it has been re-armed so far. */
  reactivate_count: number;
  last_reactivated_at: string | null;
  created_at: string | null;
  source: "mirror" | "onlyfans";
  /** Revenue and its fans, over every OF promo the campaign was re-armed as. */
  metrics?: LinkFigures;
}

/** Profile promotion's "Add fans to list" (Infloww's account-level switch and list; relay `promo_list_settings`). */
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
    refetchInterval: whileRefreshing,
    queryFn: () =>
      relay.get(`/admin/promotions?account_id=${encodeURIComponent(accountId!)}`),
  });
}

export function useCreatePromotion(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    PromoCampaign, Error,
    {
      name: string; discount: number; subscribe_counts: number;
      subscribe_days: number; message?: string;
      /** "all" (new subscribers), "expired", or OF's list of both. */
      promo_type?: string | string[];
      /** Offer expiration in days, 0 = none (OF's finishDays). */
      finish_days?: number;
    }
  >({
    mutationFn: (body) =>
      relay.post<PromoCampaign>("/admin/promotions", { account_id: accountId, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [PROMO_KEY, accountId] }),
  });
}

export function useDeletePromotion(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/promotions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [PROMO_KEY, accountId] }),
  });
}

/** Toggle "keep this promo running" for one campaign. */
export function useSetPromoAutoReactivate(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<
    { id: number; auto_reactivate: boolean }, Error,
    { id: number; auto_reactivate: boolean }
  >({
    mutationFn: ({ id, auto_reactivate }) =>
      relay.patch(`/admin/promotions/${id}`, { auto_reactivate }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [PROMO_KEY, accountId] }),
  });
}

/** Deactivate (Infloww's, OF's "Stop promotion"): OF's POST /promotions/{id}/finish ends the offer, the row stays as
 *  ended. As Infloww's ("Auto-activate switch will be turned off"), a campaign set to keep running is turned off
 *  first, or the re-arm automation would re-create the offer just stopped. */
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

// ── Link figures' Details and the Edit dialog (relay link_metrics) ──

/** Spend in cents by Infloww's Details columns, gross and `_net`. */
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

/** OnlyFans' lifetime sums for the fan with this creator (net), as of the last read of the link's claimers. */
export interface LifetimeSpend {
  total_cents: number; subs_cents: number; posts_cents: number;
  messages_cents: number; streams_cents: number; tips_cents: number;
}

export interface LinkFan {
  fan_id: number;
  name: string;
  username: string;
  /** OnlyFans' subscribeAt as first read (never moved later); null when OnlyFans sent none. */
  subscribe_at: string | null;
  /** When the relay first read the fan under the link. */
  first_seen_at: string | null;
  /** Since claim: ledger spend at or after subscribe_at; null without one. */
  since: SpendBuckets | null;
  lifetime: LifetimeSpend | null;
}

export interface LinkFans {
  fans: LinkFan[];
  /** Our ledger's first row (ISO): Since claim cannot count before it. */
  ledger_since: string | null;
  walked_at: string | null;
  /** A refresh holds the account's OnlyFans reads: these are the cached fans. */
  refreshing: boolean;
}

/** Details: a free trial link's or promotion's fans. `count` is the row's claim count (the relay re-reads the link
 *  when it moved); `campaignId` folds a re-armed promotion's earlier OF promos in. */
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
    refetchInterval: (q) => (q.state.data?.refreshing ? 15_000 : false),
    queryFn: () => relay.get(`/admin/link-metrics/fans?${qs}`),
  });
}

/** Which link the Edit dialog saves: a free trial link, or a tracking link (OF's campaign). */
export type EditableKind = "trial" | "campaign";

export interface LinkMetaBody {
  kind: EditableKind;
  of_id: number;
  /** Dollars; null clears it. */
  promo_cost: number | null;
  source: string | null;
  tags: string[];
  /** An OnlyFans custom list's id: picking one adds the link's claimers to it (OnlyFans' add-to-list). */
  list_id?: string | null;
  list_name?: string | null;
}

/** The Edit dialog's save: Promo cost, Source and Tag, kept by the relay (nothing written to OnlyFans), and List,
 * which the relay applies with OnlyFans' own add-to-list in the background. */
export function useSaveLinkMeta(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, LinkMetaBody>({
    mutationFn: (body) => relay.put("/admin/link-meta", { account_id: accountId, ...body }),
    // Only the list: the tracking links' earnings read is not touched by a cost, source or tag.
    onSuccess: (_r, body) =>
      qc.invalidateQueries({ queryKey: [body.kind === "trial" ? TRIAL_KEY : OF_TRACK_KEY, accountId], exact: true }),
  });
}

/** Infloww's batch edit: each of Promo cost, Source and Tag the body carries is set on every picked link; one it
 *  leaves out stays as each link has it. List is not batch-edited. */
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

// ── Share links (a public read-only report on some links, 7 days) ─────

const SHARE_KEY = "link-shares";

export interface LinkShare {
  id: number;
  name: string;
  kind: EditableKind;
  /** `/share/<id>.<secret>`: the public page, same-origin. */
  path: string;
  of_ids: number[];
  include_earnings: boolean;
  created_at: string;
  expires_at: string;
  /** When its figures were last rebuilt from a read of the links; null until the first. */
  updated_at: string | null;
  /** "preparing": no read of the links has filled it yet. */
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
    // The new share's rows are filled by the owner's next read of the links: make it now, then list the shares.
    onSuccess: async (_r, body) => {
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

// ── Subscription bundles (the same reads and writes as OF Manager's mirror) ──

/** The page's bundles and price: users/me, as OF's own list reads them (authUser.subscriptionBundles). */
export function useOfMe(accountId: string | null) {
  return useQuery(ofMeQuery(accountId));
}

/** Add bundle's options (users/me settings' canAddSubscriberByBundle), under the mirror's own query key. */
export function useBundleSettings(accountId: string | null) {
  return useQuery({
    queryKey: ["of-settings", "settings", accountId],
    queryFn: () => relay.get<BundleSettings>("/api/of/v2/users/me/settings", { accountId }),
    enabled: !!accountId,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

/** Add (POST {discount, duration}) or, with an id, edit (PUT /{id} {discount, duration}) a bundle; then users/me again. */
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
