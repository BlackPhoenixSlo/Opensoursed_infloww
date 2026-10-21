"use client";

/**
 * Fansly Manager > Earning Statistics: the purchases our ledger recorded for this Fansly creator, by kind, over a date
 * range (default the last 30 days), from `GET /admin/stats/revenue?account_id&from&to&group_by=kind`. Fansly's own
 * earnings endpoints answer the shim nothing, so this is not Fansly's statement: it is the sales service/fansly_revenue
 * wrote from Fansly's purchase notifications, labelled as such. Fansly's wallet balance is not shown: its unit is
 * unverified.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState, IF_TABLE, IfBody, IfCard, IfRangePicker } from "@/components/ui/infloww";
import { fmtCents } from "@/lib/format";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

interface KindRow { kind: string | null; total_cents: number; count: number }

const KIND_LABEL: Record<string, string> = {
  ppv: "Pay-per-view", tip: "Tips", subscription: "Subscriptions", rebill: "Renewals", custom: "Custom",
};

/** A local `yyyy-mm-dd`, `days` before today. */
function dayOffset(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function FanslyEarnings({ accountId }: { accountId: string }) {
  const [range, setRange] = useState(() => ({ from: dayOffset(29), to: dayOffset(0) }));
  const ready = !!range.from && !!range.to;
  const q = useQuery<{ rows: KindRow[] }>({
    queryKey: ["fansly-manager", "earnings", accountId, range.from, range.to],
    queryFn: () => {
      const qs = new URLSearchParams({ account_id: accountId, from: range.from, to: range.to, group_by: "kind" });
      return relay.get(`/admin/stats/revenue?${qs.toString()}`);
    },
    enabled: ready,
    staleTime: 30_000,
  });
  const rows = q.data?.rows ?? [];
  const total = rows.reduce((s, r) => s + (r.total_cents ?? 0), 0);
  const count = rows.reduce((s, r) => s + (r.count ?? 0), 0);

  return (
    <IfBody>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12px] text-muted">
          Purchases recorded by us from Fansly&apos;s purchase notifications, not Fansly&apos;s own statement.
        </p>
        <IfRangePicker from={range.from} to={range.to} onChange={setRange} />
      </div>
      {q.isError ? (
        <EmptyState kind="error" text="Could not load earnings." onRetry={() => void q.refetch()} className="mt-16" />
      ) : !ready ? (
        <EmptyState text="Pick a date range" className="mt-16" />
      ) : q.isPending ? (
        <p className="mt-16 text-center text-[14px] text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-4">
          <IfCard title="Purchases recorded by us">
            <p className="mt-3 text-[28px] font-semibold tabular-nums text-fg" data-testid="fansly-earnings-total">{fmtCents(total)}</p>
            <p className="text-[12px] text-muted">{count} {count === 1 ? "purchase" : "purchases"}</p>
          </IfCard>
          {rows.length === 0 ? (
            <EmptyState text="No purchases in this range" className="mt-8" />
          ) : (
            <table className={IF_TABLE.table}>
              <thead>
                <tr>
                  <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Kind</th>
                  <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Purchases</th>
                  <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "text-right")}>Gross</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.kind ?? "other"} className={IF_TABLE.row}>
                    <td className={IF_TABLE.td}>{(r.kind && KIND_LABEL[r.kind]) || r.kind || "Other"}</td>
                    <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{r.count}</td>
                    <td className={cn(IF_TABLE.td, "text-right tabular-nums")}>{fmtCents(r.total_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </IfBody>
  );
}
