"use client";

/**
 * TrialLinksTab — Growth → Free trial links, Infloww's Tracking links frame in its FREETRIAL variant
 * (`LinksListFrame`, bundle `LINK_LIST_VIEW_TYPE.FREETRIAL`): the attribution tip, the filters (Creator, "Search free
 * trial link name", Source, Tag, Date created), the two switches, "Create free trial link" and Export, the update
 * row, then the table: Free trial links, Date created, Claim ("3 / ∞"), and Infloww's free trial figures
 * (`FREE_TRIAL_LINK_CUSTOM_METRIC_OPTIONS`, with its tooltips): Spend/Claim, Promo cost, Earnings, Fans who spent,
 * Profit, AEPS and ROI. Infloww's free trial table has no CPC or CPS. Infloww's Dashboard tab is left out (owner:
 * YAGNI until asked). The third tab, "Share links" (`ShareLinksPanel`, owner-only), makes public read-only reports
 * on picked links. The row checkboxes pick links for Batch edit (`LinkBatchEditDialog`: Source, Promo cost, Tag).
 *
 * Mint / label / delete OnlyFans free-trial links and read their redemptions. Create is the bundle's editor pop-up:
 * Infloww's and OF's fields (Link name, Offer limit, Offer expiration, Free trial duration; the body is OF Manager's
 * own trialBody), then Source, Promo cost, Tag and List (`LinkMetaFields`, shared with Edit); List is OnlyFans' own
 * add-to-list on the link's claimers (`POST /lists/{id}/users/trial/{id}/claims`, confirmed live 2026-10-19). A new
 * link's List takes its fans from the first claim on. When OnlyFans' create reply carries no link id, the link is
 * made but the four fields can't be kept, and the pop-up says so.
 *
 * Earnings is the link's claimers' spend in our ledger since each claimed (the relay's cached read, "Updated N min
 * ago", refreshed past an hour); Promo cost, Source and Tag are kept by the relay. OF is the source of truth; a local
 * mirror keeps the operator's name so the list renders even when a live OF fetch is unavailable.
 *
 * Row actions: Details (who claimed, `OfferClaimers`, opened under the row, with its Export fans), Edit (`LinkEditDialog`) and the dots
 * menu's Delete: the OnlyFans delete, ours and labelled (the bundle's menu has Deactivate). "Show deactivated
 * links" is Not wired: the relay keeps no deleted free trial links to show.
 */

import { useState } from "react";
import { RotateCw } from "lucide-react";

import { Badge, ExtraTag, Input } from "@/components/ui/primitives";
import { HbButton, HbModal, HB_TABLE } from "@/components/ui/infloww";
import { CopyButton, SelectInput, errMsg } from "@/components/growth/_bits";
import { useTrialLinks, useCreateTrialLink, useDeleteTrialLink, type TrialLink } from "@/hooks/useGrowth";
import { useGrowthCreator } from "@/hooks/useAccounts";
import { useUser } from "@/contexts/UserContext";
import LinkEditDialog, { LinkBatchEditDialog } from "@/components/growth/LinkEditDialog";
import ShareLinksPanel from "@/components/growth/ShareLinksPanel";
import LinkMetaFields, { FieldLabel, META_LOST, useLinkMetaFields } from "@/components/growth/LinkMetaFields";
import LinksListFrame, {
  FrameTabs, GrowthHbFrame, RowActions, Switch, Unreachable, dateOnly, downloadCsv, useFrameFilters, useSessionGone,
  type FrameCol,
} from "@/components/growth/LinksListFrame";
import { createdDay } from "@/components/growth/frameDates";
import OfferClaimers from "@/components/growth/OfferClaimers";
import { DASH, TRIAL_TIPS, aeps, money, profit, roi, share, updatedAgo } from "@/components/growth/linkMetrics";
import { claimsText } from "@/components/growth/offerFormat";
import { fmtPrice } from "@/lib/format";
import { EXPIRATIONS, TRIAL_DEFAULTS, TRIAL_DURATIONS, TRIAL_LIMITS, trialBody, type TrialForm } from "@/lib/ofMirrorOffers";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { ofErrorMessage } from "@/lib/ofMirrorWrites";
import { cn } from "@/lib/utils";

/** Infloww's free trial figures for one row, in its column order (after Date created and Claim); `null` gives the
 *  heads (every value "—"). `net` picks the net or gross earnings, as "Show net earnings". */
export function trialFigures(l: TrialLink | null, net: boolean): Array<{ title: string; tip?: string; value: string }> {
  const m = l?.metrics;
  const earnings = m ? (net ? m.earnings_net_cents : m.earnings_cents) : null;
  const cost = l?.promo_cost_cents ?? null;
  return [
    { title: "Spend/Claim", tip: TRIAL_TIPS.spendClaim, value: share(m?.fans_who_spent, m?.fans_counted) },
    { title: "Promo cost", tip: TRIAL_TIPS.promoCost, value: cost ? fmtPrice(cost) : DASH },
    { title: "Earnings", tip: TRIAL_TIPS.earnings, value: earnings == null ? DASH : money(earnings) },
    { title: "Fans who spent", value: m?.fans_who_spent == null ? DASH : String(m.fans_who_spent) },
    { title: "Profit", tip: TRIAL_TIPS.profit, value: profit(earnings, cost) },
    { title: "AEPS", tip: TRIAL_TIPS.aeps, value: aeps(earnings, m?.fans_counted) },
    { title: "ROI", tip: TRIAL_TIPS.roi, value: roi(earnings, cost) },
  ];
}

/** The figures' widths, as the Tracking links columns of the same names. */
const FIGURE_WIDTH: Record<string, number> = {
  "Spend/Claim": 112, "Promo cost": 139, Earnings: 128, "Fans who spent": 92, Profit: 139, AEPS: 112, ROI: 139,
};

/** The columns the Edit dialog fills, drawn once some link has a value (as Tracking links' `visibleCols`). */
const META_COLS: Array<FrameCol<TrialLink> & { has: (l: TrialLink) => boolean }> = [
  { title: "Source", width: 120, has: (l) => !!l.link_source, cell: (l) => l.link_source || DASH },
  { title: "Tag", width: 180, has: (l) => !!l.tags?.length, cell: (l) => (l.tags?.length ? l.tags.join(", ") : DASH) },
  {
    title: "List", width: 180, has: (l) => !!(l.list_name || l.list_id),
    cell: (l) => l.list_name || (l.list_id ? `List ${l.list_id}` : DASH),
  },
];

const keyOf = (l: TrialLink, i = 0) => (l.id != null ? `m-${l.id}` : `of-${l.of_trial_id ?? i}`);

/** Ours under the name: the trial's length, clicks and expiry (the bundle's row has only the name and Copy link). */
function trialMeta(l: TrialLink): string {
  const parts = [`${l.subscribe_days}-day trial`];
  if (l.clicks_count != null) parts.push(`${l.clicks_count} click${l.clicks_count === 1 ? "" : "s"}`);
  if (l.expired_at) parts.push(`expire${new Date(l.expired_at) < new Date() ? "d" : "s"} ${new Date(l.expired_at).toLocaleDateString()}`);
  return parts.join(" · ");
}

type TabKey = "list" | "share";
const TABS: Array<{ key: TabKey; label: string }> = [{ key: "list", label: "Links list" }, { key: "share", label: "Share links" }];

export default function TrialLinksTab({ accountId, onAccountChange, accountsLoading = false }: {
  accountId: string | null;
  /** The Creators list is still loading (no Creator picked yet): placeholder rows, not "No data". */
  accountsLoading?: boolean;
  /** The creator filter picks the Creator every read and write below is for. */
  onAccountChange: (id: string) => void;
}) {
  const linksQ = useTrialLinks(accountId);
  const deleteM = useDeleteTrialLink(accountId);
  const filters = useFrameFilters({});
  const { reportTz } = filters;
  const sessionGone = useSessionGone(accountId);

  const owner = !!useUser().user;
  const [tab, setTab] = useState<TabKey>("list");
  const [creating, setCreating] = useState(false);
  const [details, setDetails] = useState<string | null>(null);
  const [editing, setEditing] = useState<TrialLink | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [batch, setBatch] = useState(false);
  // Infloww's "Show net earnings", on by default.
  const [net, setNet] = useState(true);

  const all = linksQ.data?.links ?? [];
  const links = all.filter(filters.keep);
  const ofAvailable = linksQ.data?.of_available ?? false;
  const sources = linksQ.data?.sources ?? [];
  const tagOptions = linksQ.data?.tags ?? [];
  // The picks still in the list (a filter or another Creator leaves the rest out).
  const pickedRows = links.filter((l) => l.of_trial_id != null && picked.includes(keyOf(l)));
  const shown = owner ? tab : "list";

  const columns: Array<FrameCol<TrialLink>> = [
    { title: "Date created", width: 104, cell: (l) => dateOnly(l.created_at, reportTz) },
    { title: "Claim", width: 80, cell: (l) => claimsText(l.claim_counts, l.subscribe_counts) },
    ...trialFigures(null, net).map((h, i) => ({
      title: h.title, tip: h.tip, width: FIGURE_WIDTH[h.title] ?? 112, cell: (l: TrialLink) => trialFigures(l, net)[i].value,
    })),
    ...META_COLS.filter((c) => all.some(c.has)),
  ];

  function exportCsv() {
    const head = ["Free trial links", "Link", ...columns.map((c) => c.title)];
    downloadCsv("free-trial-links", [head, ...links.map((l) => [
      l.name, l.url ?? "", createdDay(l, reportTz) ?? "", claimsText(l.claim_counts, l.subscribe_counts),
      ...trialFigures(l, net).map((f) => (f.value === DASH ? "" : f.value)),
      ...META_COLS.filter((c) => all.some(c.has)).map((c) => String(c.cell(l)).replace(DASH, "")),
    ])], reportTz);
  }

  return (
    <div>
      <FrameTabs tabs={owner ? TABS : TABS.slice(0, 1)} value={shown} onChange={setTab} label="Free trial links" idPrefix="ftl" />
      <div role="tabpanel" id={`ftl-panel-${shown}`} aria-labelledby={`ftl-tab-${shown}`}>
        {shown === "share" ? (
          <ShareLinksPanel accountId={accountId} onAccountChange={onAccountChange} kind="trial"
            links={all.filter((l) => l.of_trial_id != null).map((l) => ({ ofId: l.of_trial_id!, name: l.name }))} />
        ) : <LinksListFrame<TrialLink>
          variant="FREETRIAL"
          accountId={accountId}
          onAccountChange={onAccountChange}
          filters={filters}
          sources={sources}
          tags={tagOptions}
          switches={(
            <>
              <Switch label="Show deactivated links" on={false} />
              <Switch label="Show net earnings" on={net} onChange={setNet} />
            </>
          )}
          onCreate={() => setCreating(true)}
          onExport={exportCsv}
          exportTitle={`${EXTRA_LABEL}: downloads a CSV of the filtered links; Infloww emails its export`}
          update={linksQ.data ? (
            <>
              <span className="flex items-center gap-2 text-sm text-fg-dim">
                <span data-metrics-updated
                  title="Earnings and Fans who spent: the claimers OnlyFans lists under each link, with their spend in our ledger since they claimed. Read again when over an hour old.">
                  {updatedAgo(linksQ.data.metrics_updated_at)}
                  {linksQ.data.metrics_refreshing && " · refreshing…"}
                </span>
                <ExtraTag />
              </span>
              {/* Ours: read OnlyFans again now. */}
              <button type="button" aria-label="Refresh" title={`${EXTRA_LABEL}: read OnlyFans again`}
                onClick={() => void linksQ.refetch()} disabled={linksQ.isFetching}
                className={cn(HB_TABLE.iconButton, "disabled:opacity-50")}>
                <RotateCw size={14} aria-hidden className={linksQ.isFetching ? "animate-spin" : undefined} />
              </button>
            </>
          ) : null}
          notice={linksQ.data && !ofAvailable && !sessionGone
            ? <Unreachable text="OnlyFans not reachable — showing saved links only." /> : null}
          loading={linksQ.isLoading || (!accountId && accountsLoading)}
          columns={columns}
          rows={links}
          rowKey={(l) => keyOf(l)}
          rowName={(l) => l.name}
          nameCell={(l) => (
            <div className="flex flex-col items-start gap-0.5 w-full">
              <span className="w-full truncate text-sm" title={l.name}>{l.name || "(unnamed)"}</span>
              <span className="flex items-center gap-2 w-full min-w-0">
                {/* A spent link keeps showing in OF's list: say so, or a dead link reads exactly like a live one. */}
                {l.status === "finished" ? <Badge color="muted">spent</Badge>
                  : l.url && <CopyButton text={l.url} label="Copy link" doneLabel="Link copied" holdMs={5000} />}
                <span className="truncate text-[11px] text-fg-dim" title={EXTRA_LABEL}>{trialMeta(l)}</span>
              </span>
            </div>
          )}
          actions={(l) => (
            <RowActions
              name={l.name}
              onDetails={() => setDetails(details === keyOf(l) ? null : keyOf(l))}
              detailsOpen={details === keyOf(l)}
              onEdit={l.of_trial_id != null ? () => setEditing(l) : undefined}
              action={{
                label: "Delete",
                extra: true,
                confirmTitle: `Delete free trial link, ${l.name}?`,
                confirmBody: "The link is deleted on OnlyFans and can no longer be claimed. This action cannot be undone.",
                failText: "Unable to delete free trial link. Try again later",
                run: l.id != null ? () => deleteM.mutateAsync(l.id!) : undefined,
              }}
            />
          )}
          expanded={(l) => details === keyOf(l)
            ? <OfferClaimers accountId={accountId} kind="trial" ofId={l.of_trial_id} count={l.claim_counts} />
            : null}
          selection={{
            selected: pickedRows.map((l) => keyOf(l)), onChange: setPicked, canSelect: (l) => l.of_trial_id != null, onBatchEdit: () => setBatch(true),
          }}
        />}
      </div>
      {batch && (
        <LinkBatchEditDialog
          accountId={accountId}
          kind="trial"
          ofIds={pickedRows.map((l) => l.of_trial_id!)}
          sources={sources}
          tags={tagOptions}
          onClose={(saved) => { setBatch(false); if (saved) setPicked([]); }}
        />
      )}
      {creating && (
        <CreateTrialModal accountId={accountId} sources={sources} tags={tagOptions} onClose={() => setCreating(false)} />
      )}
      {editing?.of_trial_id != null && (
        <LinkEditDialog
          accountId={accountId}
          link={{ kind: "trial", ofId: editing.of_trial_id, name: editing.name, promo_cost_cents: editing.promo_cost_cents,
            link_source: editing.link_source, tags: editing.tags, list_id: editing.list_id, list_name: editing.list_name }}
          sources={sources}
          tags={tagOptions}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

/** "Create free trial link": the bundle's editor pop-up (480px, Cancel then Save): OnlyFans' fields, then Source,
 *  Promo cost, Tag and List. It closes once OnlyFans made the link; a reply that lost the four fields says so in
 *  place of the form, so a second Save can't mint a duplicate. */
function CreateTrialModal({ accountId, sources, tags, onClose }: {
  accountId: string | null;
  sources: string[];
  tags: string[];
  onClose: () => void;
}) {
  const createM = useCreateTrialLink(accountId);
  const f = useLinkMetaFields();
  const [form, setForm] = useState<TrialForm>(TRIAL_DEFAULTS);
  const [err, setErr] = useState<string | null>(null);
  const [lost, setLost] = useState(false);
  const set = (patch: Partial<TrialForm>) => setForm((x) => ({ ...x, ...patch }));

  async function save() {
    setErr(null);
    const body = trialBody(form);
    if (!body.name.trim()) { setErr("This is a required field"); return; }
    if (f.costBad) return;
    try {
      const out = await createM.mutateAsync({ ...body, name: body.name.trim(), ...(f.filled() ? f.payload() : {}) });
      if (out?.meta_saved === false) { setLost(true); return; }
      onClose();
    } catch (e) { setErr(ofErrorMessage(e) ?? errMsg(e, "Create failed")); }
  }

  return (
    <HbModal
      title="Create free trial link"
      width={480}
      onClose={onClose}
      footer={lost ? (
        <HbButton onClick={onClose}>Close</HbButton>
      ) : (
        <>
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton onClick={() => void save()} disabled={createM.isPending || !accountId || f.costBad}>Save</HbButton>
        </>
      )}
    >
      {lost ? (
        <div role="alert" className="text-sm text-fg">{META_LOST}</div>
      ) : (
        <form className="flex flex-col gap-6 text-fg" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="flex flex-col gap-2">
            <FieldLabel htmlFor="trial-new-name" text="Link name" />
            <Input id="trial-new-name" className="h-9" maxLength={100} autoFocus value={form.name}
              onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Twitter 7-day" />
            {err && <div className="text-err text-xs" role="alert">{err}</div>}
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-base">Offer limit</span>
            <SelectInput ariaLabel="Offer limit" value={form.limit} options={TRIAL_LIMITS} onChange={(limit) => set({ limit })} />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-base">Offer expiration</span>
            <SelectInput ariaLabel="Offer expiration" value={form.expiration} options={EXPIRATIONS} onChange={(expiration) => set({ expiration })} />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-base">Free trial duration</span>
            <SelectInput ariaLabel="Free trial duration" value={form.duration} options={TRIAL_DURATIONS} onChange={(duration) => set({ duration })} />
          </div>
          <LinkMetaFields f={f} id="trial-new" accountId={accountId} sources={sources} tags={tags} />
        </form>
      )}
    </HbModal>
  );
}

/** /growth/free-trial-links: this tab in the Growth HB frame. */
export function TrialLinksPage() {
  const { accountId, setAccountId, loading } = useGrowthCreator();
  return (
    <GrowthHbFrame title="Free trial links">
      <TrialLinksTab accountId={accountId} onAccountChange={setAccountId} accountsLoading={loading} />
    </GrowthHbFrame>
  );
}
