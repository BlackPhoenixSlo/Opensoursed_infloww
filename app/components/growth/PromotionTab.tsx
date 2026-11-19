"use client";

/**
 * PromotionTab — Growth → Profile promotion's content, laid out as Infloww's (bundle: ProfilePromotionCampaign
 * @13957700, antd's legacy set). The page (`GrowthRailFrame`) draws the 48px header and the creator rail.
 *
 * "Promotion campaigns" with the primary "Create promotion" (Infloww's `CreatePromotionModal`, 520px: User type,
 * Promotion type, Offer limit, Offer expiration, Free trial duration or Discount percent, Message; the body is OF
 * Manager's own promotionBody), the tips box, then "Campaign insights": Show expired, the antd table (Promo / Claims /
 * Revenue / Actions) and its pager, 10 a page; then the settings rows, "Auto-activate campaign" (`PromoReactivateCard`,
 * a read-only status: the per-campaign Keep running tick is the one switch; in Create promotion it is on by default
 * for a discount and off for a Free trial, which needs a Re-create limit when ticked, and names the campaign it
 * takes Keep running from; under it, on the dialog and a kept row, the second tick Re-create at 90% filled, ticked by
 * default and off under an Offer limit of 10)
 * and "Add fans to list" (`PromoListRow`, Infloww's account-level switch and list). Infloww puts the two rows above
 * Campaign insights; ours lead with the campaigns, the page's reason (UI flow audit C33). OF is the source of truth; a local mirror keeps the
 * operator's name, the discount (OF does not echo it) and the Keep running switch.
 * Revenue "from N fans" (Infloww's RevenueCell) is the campaign's claimers' spend in our ledger since each claimed,
 * net, over every OF promo a re-armed campaign has been (the relay's cached read, "Updated N min ago"); Spend/Claim
 * and AEPS ride under it. Promotions carry no promo cost in Infloww, so there is no Profit or ROI.
 *
 * Ours, labelled: the Name field, Keep running per campaign, the Refresh button, Delete on an ended mirrored
 * campaign, and Subscription bundles under the table (Infloww has them in OF Manager's settings).
 */

import { Fragment, useEffect, useReducer, useState } from "react";
import { Info, RotateCw } from "lucide-react";

import { Badge, ExtraTag } from "@/components/ui/primitives";
import { SkeletonRows } from "@/components/ui/Skeleton";
import {
  EmptyState, IF_TABLE, IfButton, IfInput, IfLabel, IfModal, IfPager, IfSelect, IfSwitch, IfTextArea, type IfOption,
} from "@/components/ui/infloww";
import { errMsg, useIfConfirm } from "@/components/growth/_bits";
import {
  usePromotions, useCreatePromotion, useDeletePromotion, useFinishPromotion, useOfMe, useSetPromoAutoReactivate,
  type PromoCampaign, type PromoCreated,
} from "@/hooks/useGrowth";
import { NOT_WIRED, Unreachable } from "@/components/growth/LinksListFrame";
import { usePagedFilters } from "@/hooks/pagedFilters";
import PromoListRow from "@/components/growth/PromoListRow";
import PromoReactivateCard from "@/components/growth/PromoReactivateCard";
import SubscriptionBundles from "@/components/growth/SubscriptionBundles";
import OfferClaimers from "@/components/growth/OfferClaimers";
import { DASH, aeps, money, share, updatedAgo } from "@/components/growth/linkMetrics";
import { claimsText, discountSteps, offerDate, promoAudience, promoOffer, visibleOffers } from "@/components/growth/offerFormat";
import {
  EXPIRATIONS, PROMO_DURATIONS, PROMO_LIMITS, discountDisabled, promotionBody,
  type Audience, type PromotionForm,
} from "@/lib/ofMirrorOffers";
import {
  INITIAL_CREATE, RECREATE_MAX, RECREATE_MIN, blockReason, buildPayload, createPromotionReducer, keepRunningOn, movedTo,
  preemptUsable, takeoverNotice, type TakenFrom,
} from "@/components/growth/createPromotionForm";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { ofErrorMessage, unresolvedId } from "@/lib/ofMirrorWrites";
import { RelayError } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { GrowthRailFrame } from "@/components/growth/GrowthFrame";
import { useGrowthCreator } from "@/hooks/useAccounts";

/** Infloww's UserTypeOptions. */
const AUDIENCES: IfOption<Audience>[] = [
  { value: "new", label: "New subscribers" },
  { value: "expired", label: "Expired subscribers" },
  { value: "both", label: "Both new and expired" },
];
const MESSAGE_MAX = 500;
/** A Free trial's Re-create limit choices (the relay's 1-10). */
const RECREATE_LIMITS = Array.from({ length: RECREATE_MAX - RECREATE_MIN + 1 }, (_, i) => {
  const n = RECREATE_MIN + i;
  return { value: String(n), label: `${n} re-create${n === 1 ? "" : "s"}` };
});
/** A Free trial campaign (OF's 100% off for its duration). */
const isTrial = (c: PromoCampaign) => c.discount_percent === 100;
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

/** `creatorsLoading`: the Creators read is still out, so no Creator is picked yet (placeholder rows, not the empty state). */
export default function PromotionTab({ accountId, creatorsLoading = false }: { accountId: string | null; creatorsLoading?: boolean }) {
  const promosQ = usePromotions(accountId);
  const deleteM = useDeletePromotion(accountId);
  const finishM = useFinishPromotion(accountId);
  const reactM = useSetPromoAutoReactivate(accountId);
  const confirm = useIfConfirm();

  const [creating, setCreating] = useState(false);
  const [details, setDetails] = useState<string | null>(null);
  /** The create just made: why it could not keep running (it still went through), or the campaign it took Keep
   *  running from. */
  const [created, setCreated] = useState<PromoCreated | null>(null);
  /** The Free trial row being ticked: it asks for its Re-create limit first. */
  const [retick, setRetick] = useState<PromoCampaign | null>(null);
  const { showExpired, page, set, setPage } = usePagedFilters({ showExpired: false });

  const campaigns = promosQ.data?.campaigns ?? [];
  const shown = visibleOffers(campaigns, showExpired);
  const ofAvailable = promosQ.data?.of_available ?? false;
  const kept = campaigns.find((c) => c.auto_reactivate && c.id != null) ?? null;
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
        {/* OF answered without the new promo: nothing proves it exists yet, so never "Created". */}
        {created?.create === "unknown" && (
          <div role="status" className="break-words text-[14px] text-warn">
            Sent, but OnlyFans hasn&apos;t confirmed it. It shows here once OnlyFans lists it; tick Keep running then.
          </div>
        )}
        {created?.create !== "unknown" && created?.auto_reactivate_refused && (
          <div role="status" className="text-[14px] text-warn">Created, but Keep running is off: {created.auto_reactivate_refused}.</div>
        )}
        {created?.keep_running_taken_from && (
          <div role="status" className="break-words text-[14px] text-fg-dim">
            Created. Took Keep running from “{created.keep_running_taken_from.name}”.
          </div>
        )}
        {!ofAvailable && !promosQ.isLoading && accountId && (
          <Unreachable text="OnlyFans not reachable — showing saved campaigns only." />
        )}
      </section>

      <section aria-label="Campaign insights" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className={TITLE}>Campaign insights</h2>
          <div className="flex items-center gap-4">
            <IfSwitch aria-label="Show expired" label="Show expired" checked={showExpired}
              onChange={(on) => set({ showExpired: on })} />
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
              {promosQ.isLoading || (!accountId && creatorsLoading) ? (
                <SkeletonRows cols={4} rows={4} cellClassName={IF_TABLE.td} />
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
                              onChange={(e) => (e.target.checked && isTrial(c)
                                ? setRetick(c) : reactM.mutate({ id: c.id!, auto_reactivate: e.target.checked }))}
                              className="w-3.5 h-3.5 rounded accent-accent cursor-pointer"
                            />
                            Keep running <span className="opacity-70">— re-create it when it ends</span>
                            {c.reactivate_count > 0 && <Badge color="info">re-armed {c.reactivate_count}×</Badge>}
                            {c.auto_reactivate && c.recreates_left != null && (
                              <Badge color="muted">{c.recreates_left} re-create{c.recreates_left === 1 ? "" : "s"} left</Badge>
                            )}
                          </label>
                        )}
                        {c.id != null && c.auto_reactivate && (
                          <PreemptTick className="max-w-[146px] text-[12px] text-fg-dim md:max-w-none" checked={!!c.preempt}
                            usable={preemptUsable(c.subscribe_counts)} disabled={reactM.isPending}
                            onChange={(on) => reactM.mutate({ id: c.id!, preempt: on })} />
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

      {/* The settings rows after the campaigns they act on (Infloww has them above Campaign insights). */}
      <PromoReactivateCard accountId={accountId} />

      <PromoListRow accountId={accountId} />

      <SubscriptionBundles accountId={accountId} />

      {creating && (
        <CreatePromotionModal accountId={accountId} kept={kept && { id: kept.id!, name: kept.name }}
          onClose={() => setCreating(false)} onCreated={setCreated} />
      )}
      {retick && <TrialRetickModal accountId={accountId} campaign={retick} onClose={() => setRetick(null)} />}
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

/** A form row: the label (antd's vertical form: no colon), then the control. */
function Row({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <IfLabel htmlFor={htmlFor} className="mb-0">{label}</IfLabel>
      {children}
    </div>
  );
}

/** A Free trial's Re-create limit: full width, so it fits a 390 px phone. */
function RecreateLimit({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <Row label="Re-create limit">
      <NumSelect label="Re-create limit" value={value} options={RECREATE_LIMITS} onChange={onChange} />
      <span className="text-[12px] text-fg-dim">Re-creates the free trial at most this many times, then Keep running turns off.</span>
    </Row>
  );
}

/** Re-create at 90% filled, the second tick under Keep running: its own line, indented 24 px, a 44 px tap row on a
 *  phone. Under an Offer limit of 10 (or none) it can never act, so it shows off, disabled, and says why. */
function PreemptTick({ checked, usable, disabled = false, onChange, className }: {
  checked: boolean; usable: boolean; disabled?: boolean; onChange: (on: boolean) => void; className: string;
}) {
  return (
    <div className={className}>
      <label title={EXTRA_LABEL}
        className={cn("flex min-h-11 items-center gap-2 pl-6 md:min-h-0", usable ? "cursor-pointer" : "cursor-not-allowed opacity-60")}>
        <input type="checkbox" checked={usable && checked} disabled={disabled || !usable}
          onChange={(e) => onChange(e.target.checked)} className="w-3.5 h-3.5 shrink-0 rounded accent-accent cursor-pointer" />
        Re-create at 90% filled
      </label>
      {!usable && <span className="block break-words pl-6 text-[12px] text-fg-dim">Needs an Offer limit of 10 or more</span>}
    </div>
  );
}

/** Ticking Keep running on a Free trial row: its Re-create limit first (the relay refuses the tick without one). */
function TrialRetickModal({ accountId, campaign, onClose }: {
  accountId: string | null; campaign: PromoCampaign; onClose: () => void;
}) {
  const reactM = useSetPromoAutoReactivate(accountId);
  const [limit, setLimit] = useState(3);
  async function tick() {
    try {
      await reactM.mutateAsync({ id: campaign.id!, auto_reactivate: true, recreate_limit: limit });
      onClose();
    } catch { /* reactM.error shows the relay's line */ }
  }
  return (
    <IfModal
      title="Keep running"
      width={420}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => void tick()} disabled={reactM.isPending}>Keep running</IfButton>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <p className="break-words text-[14px] text-fg">Keep “{campaign.name}” running: a free trial needs a Re-create limit.</p>
        <RecreateLimit value={limit} onChange={setLimit} />
        {reactM.error && (
          <div className="text-err text-[12px]" role="alert">{ofErrorMessage(reactM.error) ?? reactM.error.message}</div>
        )}
      </div>
    </IfModal>
  );
}

/** `CreatePromotionModal`: 520px, label over control, Cancel then Create. The line over the footer says what
 *  OnlyFans will be asked to run (ours, in place of a second confirm). `kept`: the campaign keeping running now. */
function CreatePromotionModal({ accountId, kept, onClose, onCreated }: {
  accountId: string | null; kept: TakenFrom | null; onClose: () => void; onCreated: (out: PromoCreated | null) => void;
}) {
  const meQ = useOfMe(accountId);
  const createM = useCreatePromotion(accountId);
  const [state, dispatch] = useReducer(createPromotionReducer, INITIAL_CREATE);
  const { name, form, preempt, recreateLimit, takenFrom, err, unresolved } = state;
  const keepOn = keepRunningOn(state);
  const takeover = keepOn ? takeoverNotice(takenFrom?.name) : null;
  // The line shown is what the create sends (expect_taken_from): follow the campaigns read as it lands.
  const keptId = kept?.id ?? null;
  const keptName = kept?.name ?? "";
  useEffect(() => {
    dispatch({ type: "takenFromLoaded", kept: keptId === null ? null : { id: keptId, name: keptName } });
  }, [keptId, keptName]);
  const price = Number(meQ.data?.subscribePrice ?? 0);
  // OF disables First-month discount when its smallest step would take the price under OF's minimum.
  const noDiscount = price > 0 && discountDisabled(price);
  const set = (patch: Partial<PromotionForm>) => dispatch({ type: "edit", patch });

  const body = promotionBody(form);
  const offer = form.kind === "trial"
    ? `a FREE trial for ${form.duration} day${form.duration === 1 ? "" : "s"}`
    : `${form.percent}% off the first month`;
  const cap = form.limit ? `up to ${form.limit} claim${form.limit === 1 ? "" : "s"}` : "UNLIMITED claims";
  const ends = form.expiration ? `on offer for ${form.expiration} day${form.expiration === 1 ? "" : "s"}` : "no expiration";

  /** `resolve`: "It did not go through — create anyway" clears the earlier create the relay could not settle. */
  async function create(resolve = false) {
    const payload = buildPayload(state, resolve);
    dispatch({ type: "clear" });
    const why = blockReason(state);
    if (why) { dispatch({ type: "failed", err: why }); return; }
    try {
      onCreated((await createM.mutateAsync(payload)) ?? null);
      onClose();
    } catch (e) {
      const said = ofErrorMessage(e) ?? errMsg(e, "Create failed");
      const id = e instanceof RelayError ? unresolvedId(e.body) : null;
      // Keep running moved meanwhile: show where it is now, so the next Create sends that.
      const moved = e instanceof RelayError ? movedTo(e.body) : undefined;
      if (moved) dispatch({ type: "takenFromLoaded", kept: moved.kept });
      dispatch(id === null ? { type: "failed", err: said } : { type: "unresolved", id, err: said });
    }
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
        <Row label="Name" htmlFor="promo-new-name">
          <span className="flex items-center gap-2">
            <IfInput id="promo-new-name" className="flex-1" value={name} onChange={(e) => dispatch({ type: "name", value: e.target.value })} placeholder="e.g. Summer free week" />
            <ExtraTag />
          </span>
        </Row>
        <Row label="User type">
          <IfSelect aria-label="User type" value={form.audience} options={AUDIENCES} onChange={(audience) => set({ audience })} className="w-full" />
        </Row>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-[14px] text-fg">Promotion type</legend>
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
        <Row label="Offer limit">
          <NumSelect label="Offer limit" value={form.limit} options={PROMO_LIMITS} onChange={(limit) => set({ limit })} />
        </Row>
        <Row label="Offer expiration">
          <NumSelect label="Offer expiration" value={form.expiration} options={EXPIRATIONS} onChange={(expiration) => set({ expiration })} />
        </Row>
        {form.kind === "trial" ? (
          <Row label="Free trial duration">
            <NumSelect label="Free trial duration" value={form.duration} options={PROMO_DURATIONS} onChange={(duration) => set({ duration })} />
          </Row>
        ) : (
          <Row label="Discount percent">
            <NumSelect label="Discount percent" value={form.percent} options={discountSteps(price)} onChange={(percent) => set({ percent })} />
          </Row>
        )}
        <Row label="Message" htmlFor="promo-new-message">
          <IfTextArea id="promo-new-message" value={form.message} maxLength={MESSAGE_MAX} rows={3}
            onChange={(e) => set({ message: e.target.value })} placeholder="Shown with the promotion" />
          <span className="self-end text-[12px] text-fg-dim tabular-nums">{form.message.length}/{MESSAGE_MAX}</span>
        </Row>
        {/* Ours: on by default for a discount, off for a Free trial; the new campaign takes Keep running from any other. */}
        <label className="inline-flex items-center gap-2 text-[14px] text-fg cursor-pointer" title={EXTRA_LABEL}>
          <input type="checkbox" checked={keepOn} onChange={(e) => dispatch({ type: "keepRunning", on: e.target.checked })}
            className="w-3.5 h-3.5 rounded accent-accent cursor-pointer" />
          Keep running <span className="text-fg-dim">— re-create it when it ends</span>
        </label>
        {keepOn && (
          <PreemptTick className="-mt-3 text-[14px] text-fg" checked={preempt} usable={preemptUsable(form.limit)}
            onChange={(on) => dispatch({ type: "preempt", on })} />
        )}
        {keepOn && form.kind === "trial" && (
          <RecreateLimit value={recreateLimit} onChange={(value) => dispatch({ type: "recreateLimit", value })} />
        )}
        {takeover && <p data-takeover className="break-words text-[14px] text-warn">{takeover}</p>}
        <p className="text-[12px] text-fg-dim">
          Creates a real OnlyFans promotion: {offer}, {promoAudience(body.type.join(",")).toLowerCase()}, {cap}, {ends}.
        </p>
        {err && <div className="text-err text-[12px]" role="alert">{err}</div>}
        {unresolved !== null && (
          <IfButton className="w-full whitespace-normal h-auto py-2" onClick={() => void create(true)} disabled={createM.isPending}>
            It did not go through — create anyway
          </IfButton>
        )}
      </div>
    </IfModal>
  );
}

/** /growth/profile-promotion: this tab in the Growth rail frame. */
export function PromotionPage() {
  const creator = useGrowthCreator();
  return (
    <GrowthRailFrame title="Profile promotion" creator={creator}>
      <PromotionTab accountId={creator.accountId} creatorsLoading={creator.loading} />
    </GrowthRailFrame>
  );
}
