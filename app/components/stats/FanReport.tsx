"use client";

/**
 * FanReport — Analytics > Fan reports, on Infloww's frame (`FansReport`, bundle @13648850, page-parity 29): the
 * legacy header (title, the report time zone's UTC offset, the icon Refresh), then the creator column beside the
 * report (`ErrorModalListLayout`, as Share for Share lays it out). The report is FanReportsCard: the filter row (the
 * range box, Shown by, Gross / Net) over New fans, Total fans, Traffic earnings and Top fans; then, under an
 * "Inflowwww extras" heading, the per-fan data table (UserDataTab, for the column's Creator; it ignores the window).
 *
 * Infloww reports one Creator at a time, the first until another is picked; there is no "All creators" row (owner
 * P2-5). Below md the column gives way to a creator select over the report. With no Creator only the range shows.
 *
 * The window is the shared report range (useReportRange): the last 30 days to start with, in the Agency's report
 * time zone, or UTC when none is saved, as the fan-report read cuts New fans' days then (not the browser's zone,
 * which would drop the growth rows past the window's UTC days); the report waits for the Applied settings and the
 * Creators. Earnings totals include pending (uncleared) sales.
 */

import { useState } from "react";

import { CreatorColumn } from "@/components/of-manager/OfManagerChrome";
import DateRangePicker from "@/components/stats/DateRangePicker";
import FanReportsCard from "@/components/stats/FanReportsCard";
import StatsRefreshButton from "@/components/stats/StatsRefreshButton";
import UserDataTab from "@/components/stats/UserDataTab";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { IfBody, IfSelect, InflowwPageHeader, type IfOption } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { useReportRange } from "@/hooks/useReportRange";

export default function FanReport() {
  const { preset, from, to, fromIso, toIso, reportTz, ready, handleRange } = useReportRange("UTC");
  const accountsQ = useAccounts();
  const accounts = useActiveAccounts();
  // null: nothing picked yet (or the pick is gone), so the first Creator.
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked && accounts.some((a) => a.id === picked) ? picked : accounts[0]?.id ?? "";

  const range = <DateRangePicker from={from} to={to} preset={preset} onChange={handleRange} timeZone={reportTz} />;
  const phoneOptions: IfOption[] = accounts.map((a) => ({
    value: a.id,
    text: a.nickname || a.id,
    label: (
      <span className="flex min-w-0 items-center gap-2">
        <span className="block h-5 w-5 shrink-0 overflow-hidden rounded-full">
          <AccountAvatarPicture account={a} letters={1} initialClassName="text-[10px] font-medium" />
        </span>
        <span className="truncate">{a.nickname || a.id}</span>
      </span>
    ),
  }));

  return (
    <div className="flex min-h-full min-w-0 flex-col">
      <InflowwPageHeader title="Fan reports" utc={reportTz} actions={<StatsRefreshButton />} />
      {/* `.h-chat` on the column (and the report's height) subtracts the 48px header too. */}
      <div className="flex min-w-0 flex-1" style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
        <CreatorColumn
          accounts={accounts}
          value={accountId}
          onChange={setPicked}
          className="md:flex border-r border-border"
        />
        {/* From md the report scrolls on its own beside the column (`.h-chat`'s height; a plain class takes no `md:`). */}
        <IfBody className="min-w-0 flex-1 space-y-4 md:h-[calc(var(--vvh)-var(--shell-top))] md:overflow-y-auto">
          {accounts.length > 0 && (
            <IfSelect aria-label="Creator" className="w-full md:hidden" searchable value={accountId}
              onChange={setPicked} options={phoneOptions} />
          )}
          {ready && !accountsQ.isPending && accountId ? (
            <FanReportsCard from={fromIso} to={toIso} fromDay={from} toDay={to} accountId={accountId}
              timeZone={reportTz} range={range} />
          ) : (
            <div className="flex flex-wrap items-center gap-3">{range}</div>
          )}
          {accountId && (
            <section aria-label="Inflowwww extras" className="space-y-3 pt-2">
              <h2 className="flex items-center gap-2 text-[16px] font-medium text-fg">Inflowwww extras <ExtraTag /></h2>
              <UserDataTab accountId={accountId} />
            </section>
          )}
        </IfBody>
      </div>
    </div>
  );
}
