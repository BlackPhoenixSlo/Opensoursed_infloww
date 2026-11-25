"use client";


import { useState } from "react";
import { Info } from "lucide-react";

import { Badge, ExtraTag } from "@/components/ui/primitives";
import { CopyButton } from "@/components/ui/CopyButton";
import LinkEditDialog, { LinkBatchEditDialog } from "@/components/growth/LinkEditDialog";
import LinksListFrame, {
  RowActions, Switch, Unreachable, dateOnly, downloadCsv, readTime, useFrameFilters, useSessionGone,
} from "@/components/growth/LinksListFrame";
import { createdDay } from "@/components/growth/frameDates";
import { PARTIAL, TIPS, costPer, count, cvr, money, per, profitCents, roi, share } from "@/components/growth/linkMetrics";
import { CreateLinkModal } from "@/components/growth/CreateLinkModal";
import { LinkDetails } from "@/components/growth/TrackingLinkDetails";
import { useOfTrackingLinks, useOfTrackingEarnings, useDeleteOfTrackingLink, type OfTrackingLink } from "@/hooks/useGrowth";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { fmtPrice } from "@/lib/format";

type Col = {
  title: string;
  width: number;
  tip?: string;
  core?: boolean;
  net?: boolean;
  cell?: (l: OfTrackingLink, tz: string | null) => string | null;
  hint?: (l: OfTrackingLink) => string | undefined;
  csv?: (l: OfTrackingLink, tz: string | null) => string;
};

const PARTIAL_HINT = "Partial: some transactions have no net figure from OnlyFans yet, so net is understated";

export function useLinks(accountId: string | null, net: boolean) {
  const q = useOfTrackingLinks(accountId);
  const e = useOfTrackingEarnings(accountId);
  const byId = new Map((e.data?.available ? e.data.links : []).map((x) => [x.id, x]));
  const links: OfTrackingLink[] = (q.data?.links ?? []).map((l) => {
    const x = l.id != null ? byId.get(l.id) : undefined;
    return x
      ? {
        ...l,
        earnings_cents: net ? x.earnings_net_cents : x.earnings_cents,
        fans_who_spent: x.fans_who_spent,
        fans_counted: x.fans_counted,
        earnings_partial: net && x.net_missing_count > 0,
      }
      : l;
  });
  return { q, links };
}

const METRIC_COLS: Col[] = [
  {
    title: "Date created", width: 121, core: true,
    cell: (l, tz) => dateOnly(l.created_at, tz), csv: (l, tz) => createdDay(l, tz) ?? "",
  },
  { title: "Clicks", width: 100, core: true, cell: (l) => count(l.clicks), csv: (l) => String(l.clicks) },
  { title: "Subs", width: 100, core: true, cell: (l) => count(l.subscribers), csv: (l) => String(l.subscribers) },
  { title: "Subscription CVR", width: 179, tip: TIPS.cvr, core: true, cell: cvr },
  {
    title: "Promo cost", width: 139, tip: TIPS.promoCost,
    cell: (l) => (l.promo_cost_cents ? fmtPrice(l.promo_cost_cents) : null),
    csv: (l) => (l.promo_cost_cents ? (l.promo_cost_cents / 100).toFixed(2) : ""),
  },
  {
    title: "Earnings", width: 139, tip: TIPS.earnings, net: true,
    cell: (l) => (l.earnings_cents == null ? null : money(l.earnings_cents) + (l.earnings_partial ? PARTIAL : "")),
    hint: (l) => (l.earnings_partial ? PARTIAL_HINT : undefined),
    csv: (l) => (l.earnings_cents == null ? "" : (l.earnings_cents / 100).toFixed(2)),
  },
  {
    title: "Fans who spent", width: 185,
    cell: (l) => (l.fans_who_spent == null ? null : count(l.fans_who_spent)),
    csv: (l) => (l.fans_who_spent == null ? "" : String(l.fans_who_spent)),
  },
  {
    title: "Spending CVR", width: 159, tip: TIPS.spendingCvr,
    cell: (l) => (l.fans_who_spent == null ? null : share(l.fans_who_spent, l.fans_counted)),
  },
  {
    title: "Profit", width: 139, tip: TIPS.profit, net: true,
    cell: (l) => { const p = profitCents(l.earnings_cents, l.promo_cost_cents); return p == null ? null : money(p); },
  },
  { title: "CPC", width: 123, tip: TIPS.cpc, cell: (l) => (l.promo_cost_cents ? costPer(l.promo_cost_cents, l.clicks) : null) },
  { title: "EPC", width: 123, tip: TIPS.epc, net: true, cell: (l) => per(l.earnings_cents, l.clicks) },
  { title: "CPS", width: 123, tip: TIPS.cps, cell: (l) => (l.promo_cost_cents ? costPer(l.promo_cost_cents, l.subscribers) : null) },
  { title: "AEPS", width: 123, tip: TIPS.aeps, net: true, cell: (l) => per(l.earnings_cents, l.fans_counted) },
  {
    title: "ROI", width: 139, tip: TIPS.roi, net: true,
    cell: (l) => (profitCents(l.earnings_cents, l.promo_cost_cents) == null ? null : roi(l.earnings_cents, l.promo_cost_cents)),
  },
  { title: "Source", width: 120, cell: (l) => l.link_source || null },
  { title: "Tag", width: 180, cell: (l) => (l.tags?.length ? l.tags.join(", ") : null) },
  { title: "List", width: 180, cell: (l) => l.list_name || (l.list_id ? `List ${l.list_id}` : null) },
  { title: "Last updated", width: 151 },
];

function visibleCols(links: OfTrackingLink[], tz: string | null): Col[] {
  return METRIC_COLS.filter((c) => c.cell && (c.core || links.some((l) => c.cell!(l, tz) !== null)));
}

export function hasNetCols(links: OfTrackingLink[], tz: string | null): boolean {
  return visibleCols(links, tz).some((c) => c.net);
}


function exportCsv(rows: OfTrackingLink[], cols: Col[], tz: string | null) {
  const withStatus = rows.some((l) => l.is_deleted);
  const head = ["Tracking link", "Link", ...cols.map((c) => c.title), ...(withStatus ? ["Status"] : [])];
  downloadCsv("tracking-links", [head, ...rows.map((l) => [
    l.name,
    l.url ?? "",
    ...cols.map((c) => (c.csv ? c.csv(l, tz) : c.cell?.(l, tz) ?? "")),
    ...(withStatus ? [l.is_deleted ? "Deactivated" : "Active"] : []),
  ])], tz);
}

export type TabProps = { accountId: string | null; onAccountChange: (id: string) => void; net: boolean; onNet: (on: boolean) => void };

export function LinksList({ accountId, onAccountChange, net, onNet, accountsLoading = false }: TabProps & { accountsLoading?: boolean }) {
  const { q, links } = useLinks(accountId, net);
  const deleteM = useDeleteOfTrackingLink(accountId);
  const filters = useFrameFilters({ showDeactivated: false });
  const { reportTz } = filters;

  const [creating, setCreating] = useState(false);
  const [details, setDetails] = useState<OfTrackingLink | null>(null);
  const [editing, setEditing] = useState<OfTrackingLink | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [batch, setBatch] = useState(false);
  const sessionGone = useSessionGone(accountId);

  const ofAvailable = q.data?.of_available ?? false;
  const matched = links.filter((l) => (!l.is_deleted || filters.showDeactivated) && filters.keep(l));
  const cols = visibleCols(links, reportTz);
  const rowKey = (l: OfTrackingLink) => String(l.id ?? l.code);
  const pickedRows = matched.filter((l) => l.id != null && picked.includes(rowKey(l)));

  if (details) {
    return <LinkDetails accountId={accountId} link={details} net={net} onBack={() => setDetails(null)} />;
  }

  return (
    <div>
      <LinksListFrame<OfTrackingLink>
        variant="TRACKING"
        accountId={accountId}
        onAccountChange={onAccountChange}
        filters={filters}
        sources={q.data?.sources ?? []}
        tags={q.data?.tags ?? []}
        switches={(
          <>
            <Switch
              label="Show deactivated links"
              on={filters.showDeactivated}
              onChange={(showDeactivated) => filters.set({ showDeactivated })}
            />
            {hasNetCols(links, reportTz) && <Switch label="Show net earnings" on={net} onChange={onNet} />}
          </>
        )}
        onCreate={() => setCreating(true)}
        onExport={() => exportCsv(matched, cols, reportTz)}
        exportTitle={`${EXTRA_LABEL}: downloads a CSV of the filtered links and the columns shown; Infloww emails its export`}
        update={q.dataUpdatedAt > 0 ? (
          <span className="flex items-center gap-2 text-sm text-fg-dim">
            <Info size={16} aria-hidden className="shrink-0" />
            <span>Last read from OnlyFans at {readTime(q.dataUpdatedAt, reportTz)}</span>
            <ExtraTag />
          </span>
        ) : null}
        notice={!q.isLoading && !ofAvailable && !sessionGone ? <Unreachable /> : null}
        loading={q.isLoading || (!accountId && accountsLoading)}
        columns={cols.map((c) => ({
          title: c.title, width: c.width, tip: c.tip, hint: c.hint, cell: (l: OfTrackingLink) => c.cell?.(l, reportTz) ?? "—",
        }))}
        rows={matched}
        phoneMetrics={["Clicks", "Subs", "Earnings", "Subscription CVR"]}
        rowKey={rowKey}
        selection={{
          selected: pickedRows.map(rowKey), onChange: setPicked, canSelect: (l) => l.id != null,
          onBatchEdit: () => setBatch(true),
        }}
        rowName={(l) => l.name}
        nameCell={(l) => (
          <div className="flex flex-col items-start gap-0.5 w-full">
            <span className="w-full truncate text-sm" title={l.name}>{l.name}</span>
            <span className="flex items-center gap-2 w-full min-w-0">
              {l.is_deleted ? (
                <Badge color="err">Deactivated</Badge>
              ) : (
                <>
                  {l.url && <CopyButton text={l.url} label="Copy link" doneLabel="Link copied" holdMs={5000} />}
                  <span className="truncate text-[11px] text-fg-dim" title={EXTRA_LABEL}>
                    {l.url ? l.url.replace(/^https:\/\/onlyfans\.com/, "") : "(url unavailable)"}
                  </span>
                </>
              )}
            </span>
          </div>
        )}
        actions={(l) => (
          <RowActions
            name={l.name}
            onDetails={l.id != null ? () => setDetails(l) : undefined}
            onEdit={l.id != null ? () => setEditing(l) : undefined}
            action={{
              label: "Deactivate",
              confirmTitle: `Deactivate link, ${l.name}?`,
              confirmBody: "Data from the tracking link is no longer tracked when the link is deactivated. This action is permanent and cannot be undone.",
              failText: "Unable to deactivate tracking link. Try again later",
              run: l.id != null && !l.is_deleted ? () => deleteM.mutateAsync(l.id!) : undefined,
            }}
          />
        )}
      />
      {editing?.id != null && (
        <LinkEditDialog
          accountId={accountId}
          link={{ kind: "campaign", ofId: editing.id, name: editing.name, promo_cost_cents: editing.promo_cost_cents,
            link_source: editing.link_source, tags: editing.tags, list_id: editing.list_id, list_name: editing.list_name }}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={() => setEditing(null)}
        />
      )}
      {batch && (
        <LinkBatchEditDialog
          accountId={accountId}
          kind="campaign"
          ofIds={pickedRows.map((l) => l.id!)}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={(saved) => { setBatch(false); if (saved) setPicked([]); }}
        />
      )}
      {creating && (
        <CreateLinkModal
          accountId={accountId}
          taken={links.filter((l) => !l.is_deleted).map((l) => l.name)}
          sources={q.data?.sources ?? []}
          tags={q.data?.tags ?? []}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  );
}
