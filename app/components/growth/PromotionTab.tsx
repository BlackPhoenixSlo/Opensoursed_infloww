"use client";

/**
 * PromotionTab — Growth → Profile promotion's content, laid out as Infloww's (bundle: ProfilePromotionCampaign
 * @13957700, antd's legacy set). The page (`GrowthTabPage`) draws the 48px header and the creator rail.
 *
 * "Promotion campaigns" with the primary "Create promotion" (Infloww's `CreatePromotionModal`, 520px: User type,
 * Promotion type, Offer limit, Offer expiration, Free trial duration or Discount percent, Message; the body is OF
 * Manager's own promotionBody), the tips box, "Auto-activate campaign" (`PromoReactivateCard`), "Add fans to list"
 * (`PromoListRow`, Infloww's account-level switch and list), then "Campaign insights": Show expired, the antd table
 * (Promo / Claims / Revenue / Actions) and its pager, 10 a page. OF is the source of truth; a local mirror keeps the
 * operator's name, the discount (OF does not echo it) and the Keep running switch.
 * Revenue "from N fans" (Infloww's RevenueCell) is the campaign's claimers' spend in our ledger since each claimed,
 * net, over every OF promo a re-armed campaign has been (the relay's cached read, "Updated N min ago"); Spend/Claim
 * and AEPS ride under it. Promotions carry no promo cost in Infloww, so there is no Profit or ROI.
 *
 * Ours, labelled: the Name field, Keep running per campaign, the Refresh button, Delete on an ended mirrored
 * campaign, and Subscription bundles under the table (Infloww has them in OF Manager's settings).
 */

import { Fragment, useState } from "react";
import { Info, RotateCw } from "lucide-react";

import { Badge, ExtraTag, Input, Textarea } from "@/components/ui/primitives";
import {
  EmptyState, IF_TABLE, IfButton, IfModal, IfPager, IfSelect, IfSwitch, type IfOption,
} from "@/components/ui/infloww";
import { errMsg, useIfConfirm } from "@/components/growth/_bits";
import {
  usePromotions, useCreatePromotion, useDeletePromotion, useFinishPromotion, useOfMe, useSetPromoAutoReactivate,
  type PromoCampaign,
} from "@/hooks/useGrowth";
import { NOT_WIRED, Unreachable } from "@/components/growth/LinksListFrame";
import PromoListRow from "@/components/growth/PromoListRow";
import PromoReactivateCard from "@/components/growth/PromoReactivateCard";
import SubscriptionBundles from "@/components/growth/SubscriptionBundles";
import OfferClaimers from "@/components/growth/OfferClaimers";
import { DASH, aeps, money, share, updatedAgo } from "@/components/growth/linkMetrics";
import { claimsText, discountSteps, offerDate, promoAudience, promoOffer, visibleOffers } from "@/components/growth/offerFormat";
import {
  EXPIRATIONS, PROMOTION_DEFAULTS, PROMO_DURATIONS, PROMO_LIMITS, discountDisabled, promotionBody,
  type Audience, type PromotionForm,
} from "@/lib/ofMirrorOffers";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { ofErrorMessage } from "@/lib/ofMirrorWrites";
import { cn } from "@/lib/utils";

/** Infloww's UserTypeOptions. */
const AUDIENCES: IfOption<Audience>[] = [
  { value: "new", label: "New subscribers" },
  { value: "expired", label: "Expired subscribers" },
  { value: "both", label: "Both new and expired" },
];
const MESSAGE_MAX = 500;
const PAGE_SIZE = 10;
/** The bundle's titles: 16 / 600 T1. */
const TITLE = "text-[16px] font-semibold text-fg";

/** Infloww's RevenueCell: the money over "from N fans" (the fans who spent); Spend/Claim and AEPS under it. */
function Revenue({ m }: { m: PromoCampaign["metrics"] }) {
  const rev = m?.earnings_net_cents ?? null;
  return (
    <div data-revenue title="Revenue: net spend in our ledger by the campaign's claimers since they claimed">
      <div className="tabular-nums text-fg">{rev == null ? DASH : money(rev)}</div>
      {rev != null && (
        <div className="text-[12px] text-fg-dim">from {m!.fans_who_spent} fan{m!.fans_who_spent === 1 ? "" : "s"}</div>
      )}
      <div className="text-[12px] text-fg-dim tabular-nums whitespace-nowrap" title="Share of the claimers who spent">
        Spend/Claim {share(m?.fans_who_spent, m?.fans_counted)}
      </div>
      <div className="text-[12px] text-fg-dim tabular-nums whitespace-nowrap" title="Average earnings per subscriber: Revenue divided by the claimers">
        AEPS {aeps(rev, m?.fans_counted)}
      </div>
    </div>
  );
}

/** `PromotionCampaignTips`: the info icon, then two bullets, the second with "Learn more" (Infloww's article, Not
 *  wired) in the CTA orange; on the panel colour with a 1px L1 border, radius 8. */
function Tips() {
  return (
    <div className="flex gap-3 rounded-lg border border-border bg-panel px-4 py-3 text-[14px] text-fg">
      <Info size={14} aria-hidden className="mt-[3px] shrink-0 text-fg-dim" />
      <ul className="list-disc space-y-2 pl-5">
        <li>Campaign insights are available for up to 10,000 of the most recent promotion campaigns created within the past 365 days</li>
        <li>
          Each fan&apos;s spending is always attributed to the last free trial link, tracking link or promotion campaign
          that has been clicked by the fan.{" "}
          <button type="button" disabled title={NOT_WIRED} className="text-cta disabled:cursor-not-allowed">Learn more</button>
        </li>
      </ul>
    </div>
  );
}

export default function PromotionTab({ accountId }: { accountId: string | null }) {
  const promosQ = usePromotions(accountId);
  const deleteM = useDeletePromotion(accountId);
  const finishM = useFinishPromotion(accountId);
  const reactM = useSetPromoAutoReactivate(accountId);
  const confirm = useIfConfirm();

  const [creating, setCreating] = useState(false);
  const [showExpired, setShowExpired] = useState(false);
  const [details, setDetails] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const campaigns = promosQ.data?.campaigns ?? [];
  const shown = visibleOffers(campaigns, showExpired);
  const ofAvailable = promosQ.data?.of_available ?? false;
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const rows = shown.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  async function deactivate(c: PromoCampaign) {
    if (await confirm.ask("Deactivate the campaign?",
      'The campaign will be marked as "Expired" and cannot be renewed. Keep running will be turned off.')) finishM.mutate(c);
  }
  async function remove(c: PromoCampaign) {
    if (await confirm.ask(`Delete promotion "${c.name}"?`, undefined, "Delete")) deleteM.mutate(c.id!);
  }

  return (
    <div className="space-y-6">
      <section aria-label="Promotion campaigns" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className={TITLE}>Promotion campaigns</h2>
          <IfButton variant="primary" onClick={() => setCreating(true)} disabled={!accountId}>Create promotion</IfButton>
        </div>
        <Tips />
        {!ofAvailable && !promosQ.isLoading && accountId && (
          <Unreachable text="OnlyFans not reachable — showing saved campaigns only." />
        )}
      </section>

      <PromoReactivateCard accountId={accountId} />

      <PromoListRow accountId={accountId} />

      <section aria-label="Campaign insights" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className={TITLE}>Campaign insights</h2>
          <div className="flex items-center gap-4">
            <IfSwitch aria-label="Show expired" label="Show expired" checked={showExpired}
              onChange={(on) => { setShowExpired(on); setPage(1); }} />
            {/* Ours: read OnlyFans again now. */}
            <button type="button" aria-label="Refresh" title={`${EXTRA_LABEL}: read OnlyFans again`}
              onClick={() => void promosQ.refetch()} disabled={promosQ.isFetching}
              className="grid h-7 w-7 place-items-center rounded-md border border-border text-fg-dim hover:text-accent disabled:opacity-50">
              <RotateCw size={14} aria-hidden className={promosQ.isFetching ? "animate-spin" : undefined} />
            </button>
          </div>
        </div>

        {/* antd's `Table size="middle"`. */}
        <div className="overflow-x-auto">
          <table aria-label="Campaigns" className={cn(IF_TABLE.table, "min-w-[720px]")}>
            <thead>
              <tr>
                <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Promo</th>
                <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "w-[140px]")}>Claims</th>
                <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "w-[180px]")}>Revenue</th>
                <th className={cn(IF_TABLE.th, IF_TABLE.fixedRightHead, "w-[180px] bg-bg-elev-2")}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {promosQ.isLoading ? (
                <tr className={IF_TABLE.row}>
                  <td colSpan={4} className={cn(IF_TABLE.td, "text-fg-dim")}>
                    <span className="inline-flex items-center gap-2">Loading… <ExtraTag /></span>
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr className={IF_TABLE.row}>
                  <td colSpan={4} className="pb-8 pt-10"><EmptyState kind="data" /></td>
                </tr>
              ) : rows.map((c, i) => {
                const key = c.id != null ? `m-${c.id}` : `of-${c.of_promo_id ?? i}`;
                const live = c.status === "active";
                const date = offerDate(c.created_at);
                return (
                  <Fragment key={key}>
                    <tr className={IF_TABLE.row}>
                      <td className={IF_TABLE.td}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-fg truncate">{c.name}</span>
                          {c.status === "finished" && <Badge color="muted">Expired</Badge>}
                          {live && <Badge color="ok">active</Badge>}
                          {c.source === "onlyfans" && <Badge color="muted">OnlyFans</Badge>}
                        </div>
                        <div className="text-[12px] text-fg-dim">
                          {promoOffer(c)} · {date ? `${date} | ` : ""}{promoAudience(c.promo_type)}
                        </div>
                        {/* Ours: opt this campaign into the re-arm. OnlyFans-only rows aren't mirrored, so they can't be re-created. */}
                        {c.id != null && (
                          <label className="mt-1 inline-flex items-center gap-1.5 text-[12px] text-fg-dim cursor-pointer" title={EXTRA_LABEL}>
                            <input
                              type="checkbox"
                              checked={c.auto_reactivate}
                              disabled={reactM.isPending}
                              onChange={(e) => reactM.mutate({ id: c.id!, auto_reactivate: e.target.checked })}
                              className="w-3.5 h-3.5 rounded accent-accent cursor-pointer"
                            />
                            Keep running <span className="opacity-70">— re-create it when it ends</span>
                            {c.reactivate_count > 0 && <Badge color="info">re-armed {c.reactivate_count}×</Badge>}
                          </label>
                        )}
                      </td>
                      <td className={cn(IF_TABLE.td, "tabular-nums")}>{claimsText(c.subscriber_count, c.subscribe_counts)}</td>
                      <td className={IF_TABLE.td}><Revenue m={c.metrics} /></td>
                      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "w-[180px]")}>
                        <div className="flex items-center gap-4">
                          <IfButton variant="link" onClick={() => setDetails(details === key ? null : key)}>
                            {details === key ? "Hide" : "Details"}
                          </IfButton>
                          {live && c.of_promo_id != null && (
                            <IfButton variant="link" onClick={() => void deactivate(c)} disabled={finishM.isPending}>Deactivate</IfButton>
                          )}
                          {c.id != null && !live && (
                            <IfButton variant="link" title={EXTRA_LABEL} onClick={() => void remove(c)} disabled={deleteM.isPending}>
                              Delete
                            </IfButton>
                          )}
                        </div>
                      </td>
                    </tr>
                    {/* Details spans the row, so the fan table's seven columns fit. */}
                    {details === key && (
                      <tr className={IF_TABLE.row}>
                        <td colSpan={4} className="px-4 py-3">
                          <OfferClaimers accountId={accountId} kind="promo" ofId={c.of_promo_id} campaignId={c.id}
                            count={c.subscriber_count} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* The antd pager, left, with no size changer. */}
          {shown.length > 0 ? (
            <IfPager total={shown.length} noun={shown.length === 1 ? "record" : "records"} page={current} size={PAGE_SIZE} onPage={setPage} />
          ) : <span />}
          <span className="text-[12px] text-fg-dim">
            {promosQ.data && (
              <span data-metrics-updated>Revenue {updatedAgo(promosQ.data.metrics_updated_at).replace(/^U/, "u")}
                {promosQ.data.metrics_refreshing && " · refreshing…"}</span>
            )}
            {finishM.error && <span className="ml-2 text-err">{ofErrorMessage(finishM.error) ?? finishM.error.message}</span>}
          </span>
        </div>
      </section>

      <SubscriptionBundles accountId={accountId} />

      {creating && <CreatePromotionModal accountId={accountId} onClose={() => setCreating(false)} />}
      {confirm.modal}
    </div>
  );
}

/** A number select on antd's look (`IfSelect` takes string values). */
function NumSelect({ label, value, options, onChange }: {
  label: string; value: number; options: { value: string; label: string }[]; onChange: (v: number) => void;
}) {
  return <IfSelect aria-label={label} value={String(value)} options={options} onChange={(v) => onChange(Number(v))} className="w-full" />;
}

/** A form row: the bundle's colon label, then the control. */
function Row({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={htmlFor} className="text-[14px] text-fg">{label}</label>
      {children}
    </div>
  );
}

/** `CreatePromotionModal`: 520px, the bundle's colon labels, Cancel then Create. The line over the footer says what
 *  OnlyFans will be asked to run (ours, in place of a second confirm). */
function CreatePromotionModal({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const meQ = useOfMe(accountId);
  const createM = useCreatePromotion(accountId);
  const [name, setName] = useState("");
  const [form, setForm] = useState<PromotionForm>(PROMOTION_DEFAULTS);
  const [err, setErr] = useState<string | null>(null);
  const price = Number(meQ.data?.subscribePrice ?? 0);
  // OF disables First-month discount when its smallest step would take the price under OF's minimum.
  const noDiscount = price > 0 && discountDisabled(price);
  const set = (patch: Partial<PromotionForm>) => setForm((f) => ({ ...f, ...patch }));

  const body = promotionBody(form);
  const offer = form.kind === "trial"
    ? `a FREE trial for ${form.duration} day${form.duration === 1 ? "" : "s"}`
    : `${form.percent}% off the first month`;
  const cap = form.limit ? `up to ${form.limit} claim${form.limit === 1 ? "" : "s"}` : "UNLIMITED claims";
  const ends = form.expiration ? `on offer for ${form.expiration} day${form.expiration === 1 ? "" : "s"}` : "no expiration";

  async function create() {
    setErr(null);
    if (!name.trim()) { setErr("Name is required."); return; }
    try {
      await createM.mutateAsync({
        name: name.trim(), discount: body.discount, subscribe_counts: body.subscribe_counts,
        subscribe_days: body.subscribe_days, finish_days: body.finish_days, message: body.message.trim(),
        promo_type: body.type,
      });
      onClose();
    } catch (e) { setErr(ofErrorMessage(e) ?? errMsg(e, "Create failed")); }
  }

  return (
    <IfModal
      title="Create promotion"
      width={520}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => void create()} disabled={createM.isPending || !accountId}>
            {createM.isPending ? "Creating…" : "Create"}
          </IfButton>
        </>
      )}
    >
      <div className="flex flex-col gap-5">
        <Row label="Name:" htmlFor="promo-new-name">
          <span className="flex items-center gap-2">
            <Input id="promo-new-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Summer free week" />
            <ExtraTag />
          </span>
        </Row>
        <Row label="User type:">
          <IfSelect aria-label="User type" value={form.audience} options={AUDIENCES} onChange={(audience) => set({ audience })} className="w-full" />
        </Row>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-[14px] text-fg">Promotion type:</legend>
          <div className="flex flex-wrap items-center gap-6 text-[14px]">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input type="radio" name="promo-kind" checked={form.kind === "trial"} onChange={() => set({ kind: "trial" })} className="accent-accent" />
              Free trial
            </label>
            <label className="inline-flex items-center gap-2 cursor-pointer" title={noDiscount ? "The subscription price is too low for a discount" : undefined}>
              <input type="radio" name="promo-kind" checked={form.kind === "discount"} disabled={noDiscount}
                onChange={() => set({ kind: "discount" })} className="accent-accent" />
              First-month discount
            </label>
          </div>
        </fieldset>
        <Row label="Offer limit:">
          <NumSelect label="Offer limit" value={form.limit} options={PROMO_LIMITS} onChange={(limit) => set({ limit })} />
        </Row>
        <Row label="Offer expiration:">
          <NumSelect label="Offer expiration" value={form.expiration} options={EXPIRATIONS} onChange={(expiration) => set({ expiration })} />
        </Row>
        {form.kind === "trial" ? (
          <Row label="Free trial duration:">
            <NumSelect label="Free trial duration" value={form.duration} options={PROMO_DURATIONS} onChange={(duration) => set({ duration })} />
          </Row>
        ) : (
          <Row label="Discount percent:">
            <NumSelect label="Discount percent" value={form.percent} options={discountSteps(price)} onChange={(percent) => set({ percent })} />
          </Row>
        )}
        <Row label="Message (optional):" htmlFor="promo-new-message">
          <Textarea id="promo-new-message" value={form.message} maxLength={MESSAGE_MAX} rows={3}
            onChange={(e) => set({ message: e.target.value })} placeholder="Shown with the promotion" />
          <span className="self-end text-[12px] text-fg-dim tabular-nums">{form.message.length}/{MESSAGE_MAX}</span>
        </Row>
        <p className="text-[12px] text-fg-dim">
          Creates a real OnlyFans promotion: {offer}, {promoAudience(body.type.join(",")).toLowerCase()}, {cap}, {ends}.
        </p>
        {err && <div className="text-err text-xs" role="alert">{err}</div>}
      </div>
    </IfModal>
  );
}
