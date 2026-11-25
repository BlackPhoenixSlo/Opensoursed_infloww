"use client";


import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState, IF_TABLE, IfBody, IfCard, IfRangePicker } from "@/components/ui/infloww";
import { fmtCents } from "@/lib/format";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

interface KindRow { kind: string | null; total_cents: number; count: number }

// Fansly's earnings endpoints answer the shim nothing: these are our ledger's sales from purchase notifications, not Fansly's statement.
const KIND_LABEL: Record<string, string> = {
  ppv: "Pay-per-view", tip: "Tips", subscription: "Subscriptions", rebill: "Renewals", custom: "Custom",
};

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
