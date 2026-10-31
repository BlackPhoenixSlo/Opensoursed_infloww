"use client";

/** Tracking links' Details (#82 to #84): one link's fans and their spend. */

import { ArrowLeft, Info, Search, Upload } from "lucide-react";

import { ExtraTag } from "@/components/ui/primitives";
import { HbButton, HbFilterLg } from "@/components/ui/infloww";
import {
  ACT, LEAD, Pager, TD, TH, dateOnly, downloadCsv, useReportTz, DEFAULT_PAGE_SIZE, type PageSize,
} from "@/components/growth/LinksListFrame";
import { money } from "@/components/growth/linkMetrics";
import { usePagedFilters } from "@/hooks/pagedFilters";
import { useOfTrackingFans, type OfTrackingFan, type OfTrackingLink } from "@/hooks/useGrowth";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import { SkeletonRows } from "@/components/ui/Skeleton";

/** The bundle's `LinkUserList` columns after Fan (`useLinkUserListTableConfig` @14152372): each reads its key, or the
 *  key with `Net` while "Show net earnings" is on. "Other" (a ledger kind outside the five) draws only when a fan has
 *  some, so Total always equals its row. */
const FAN_COLS: Array<{ title: string; key: "total" | "subs" | "posts" | "messages" | "streams" | "tips" | "other" }> = [
  { title: "Total", key: "total" },
  { title: "Subs", key: "subs" },
  { title: "Posts", key: "posts" },
  { title: "Messages", key: "messages" },
  { title: "Streams", key: "streams" },
  { title: "Tips", key: "tips" },
  { title: "Other", key: "other" },
];

function fanCents(f: OfTrackingFan, key: (typeof FAN_COLS)[number]["key"], net: boolean): number {
  return f[`${key}${net ? "_net" : ""}_cents` as keyof OfTrackingFan] as number;
}

export function LinkDetails({ accountId, link, net, onBack }: {
  accountId: string | null; link: OfTrackingLink; net: boolean; onBack: () => void;
}) {
  const q = useOfTrackingFans(accountId, link.id);
  const { reportTz } = useReportTz();
  const exportAllowed = useActionAllowed("export");
  const { search, page, pageSize, set, setPage } = usePagedFilters<{ search: string; pageSize: PageSize }>(
    { search: "", pageSize: DEFAULT_PAGE_SIZE },
  );

  const fans = q.data?.fans ?? [];
  const cols = FAN_COLS.filter((c) => c.key !== "other" || fans.some((f) => f.other_cents !== 0));
  const needle = search.trim().toLowerCase();
  const matched = fans.filter((f) => !needle
    || f.name.toLowerCase().includes(needle) || f.username.toLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(matched.length / pageSize));
  const current = Math.min(page, pages);
  const shown = matched.slice((current - 1) * pageSize, current * pageSize);
  const span = cols.length + 1;

  return (
    <section aria-label="Details" className="px-4 pt-4 mb-4 space-y-4">
      {/* The bundle's header: back to the list, "Details", then the link's name. */}
      <div className="flex flex-wrap items-center gap-4">
        <button type="button" onClick={onBack} className={cn(ACT, "gap-1 flex")}>
          <ArrowLeft size={14} aria-hidden /> Tracking links
        </button>
        <h2 className="text-base font-semibold">Details</h2>
        <span className="text-base text-fg-dim truncate">{link.name}</span>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <span className="relative inline-flex w-[280px] max-w-full">
          <Search size={20} aria-hidden className={LEAD} />
          <input
            className={cn(HbFilterLg, "w-full pl-10")}
            aria-label="Search fan name"
            placeholder="Search fan name"
            value={search}
            onChange={(e) => set({ search: e.target.value })}
          />
        </span>
        {/* Infloww's export-link-fans (it emails one); ours downloads the fans matched, as the table shows them. */}
        {exportAllowed && (
          <HbButton variant="secondary" icon={Upload} disabled={matched.length === 0} title={`${EXTRA_LABEL}: downloads a CSV`}
            onClick={() => downloadCsv(`tracking-link-fans-${link.id}`, [
              ["Fan", "Username", ...cols.map((c) => c.title)],
              ...matched.map((f) => [f.name, f.username, ...cols.map((c) => (fanCents(f, c.key, net) / 100).toFixed(2))]),
            ], reportTz)}>
            Export fans
          </HbButton>
        )}
        <span className="flex items-center gap-2 text-sm text-fg-dim">
          <Info size={16} aria-hidden className="shrink-0" />
          {q.data?.counted_from
            ? <>Spend from our ledger since {dateOnly(q.data.counted_from, reportTz)}</>
            : <>Spend from our ledger</>}
          ; a fan who came through several links is split between them by time.
          <ExtraTag />
        </span>
      </div>
      {q.isError && <div className="text-sm text-err">Unable to load page. Try again later</div>}
      <div className="overflow-x-auto">
        <table aria-label="Link fans" className="w-full border-collapse table-fixed">
          <thead>
            <tr>
              <th className={TH} style={{ width: 240 }}>Fan</th>
              {cols.map((c) => <th key={c.key} className={TH} style={{ width: 120 }}>{c.title}</th>)}
            </tr>
          </thead>
          <tbody>
            {q.isLoading ? (
              <SkeletonRows cols={span} rows={5} cellClassName={TD} />
            ) : shown.length === 0 ? (
              <tr><td colSpan={span} className={cn(TD, "text-center text-fg-dim")}>No data</td></tr>
            ) : (
              <>
                {shown.map((f) => (
                  <tr key={f.fan_id}>
                    <td className={TD}>
                      <div className="flex flex-col">
                        <span className="truncate text-sm">{f.name || f.username || f.fan_id}</span>
                        <span className="truncate text-[11px] text-fg-dim">
                          @{f.username || f.fan_id}
                          {f.also_claimed_by.length > 0 && " · also came through another link"}
                        </span>
                      </div>
                    </td>
                    {cols.map((c) => (
                      <td key={c.key} className={cn(TD, "tabular-nums")}>{money(fanCents(f, c.key, net))}</td>
                    ))}
                  </tr>
                ))}
                {/* The bundle's `LinkUserListSummaryRow`: each column summed. */}
                <tr className="font-medium">
                  <td className={TD}>Total:</td>
                  {cols.map((c) => (
                    <td key={c.key} className={cn(TD, "tabular-nums")}>
                      {money(shown.reduce((t, f) => t + fanCents(f, c.key, net), 0))}
                    </td>
                  ))}
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
      {shown.length > 0 && (
        <Pager
          page={current}
          total={matched.length}
          size={pageSize}
          onPage={setPage}
          onSize={(s) => set({ pageSize: s })}
        />
      )}
    </section>
  );
}
