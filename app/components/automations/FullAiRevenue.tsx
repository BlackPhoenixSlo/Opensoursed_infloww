"use client";

/**
 * FullAiRevenue — the Full AI page's Revenue block body: renders `revenueView` (fullAiRevenueView.ts) over
 * `useFullAiRevenue`. Shows nothing it does not get from the view: "not live yet", or since when it is live, per Arm
 * the enrolled Fans, complete 14-day windows, $ per enrolled Fan and Fans still in window, per Route offers / bought /
 * buy rate / $, and the honesty line.
 */

import { revenueView } from "@/components/automations/fullAiRevenueView";
import { IF_TABLE } from "@/components/ui/infloww";
import { useFullAiRevenue } from "@/hooks/useFullAiRevenue";
import { cn } from "@/lib/utils";

const CELL = cn(IF_TABLE.td, "whitespace-nowrap py-2 tabular-nums");
const HEAD = cn(IF_TABLE.th, IF_TABLE.thDivider);

export function FullAiRevenue({ accountId }: { accountId: string }) {
  const q = useFullAiRevenue(accountId);
  if (q.isError) return <p className="text-[12px] text-err">Couldn&apos;t read revenue.</p>;
  if (!q.data) return <p className="text-[12px] text-muted">Loading…</p>;
  const v = revenueView(q.data);
  if (!v.live) return <p className="text-[14px] text-fg-dim" data-testid="full-ai-revenue-not-live">Not live yet.</p>;
  return (
    <div className="space-y-4" data-testid="full-ai-revenue">
      <p className="text-[12px] text-muted">Live since {v.since}. Money: cleared, every kind, first 14 days per Fan.</p>
      <div className="overflow-x-auto">
        <table className={IF_TABLE.table} aria-label="Revenue per arm">
          <thead>
            <tr>
              {["Arm", "Enrolled", "Complete 14 d", "$ per Fan", "In window"].map((h) => (
                <th key={h} className={HEAD}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {v.arms.map((a) => (
              <tr key={a.arm} className={IF_TABLE.row}>
                <td className={CELL}>{a.label}</td>
                <td className={CELL}>{a.fans}</td>
                <td className={CELL}>{a.complete}</td>
                <td className={CELL}>{a.perFan}</td>
                <td className={CELL}>{a.inWindow}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {v.honesty && <p className="text-[12px] text-warn" data-testid="full-ai-revenue-honesty">{v.honesty}</p>}
      {v.delta && <p className="text-[12px] text-fg">{v.delta}</p>}
      {v.routes.length > 0 && (
        <div className="overflow-x-auto">
          <table className={IF_TABLE.table} aria-label="Offers per route">
            <thead>
              <tr>
                {["Route", "Offers", "Bought", "Buy rate", "$"].map((h) => <th key={h} className={HEAD}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {v.routes.map((r) => (
                <tr key={r.route} className={IF_TABLE.row}>
                  <td className={CELL}>{r.label}</td>
                  <td className={CELL}>{r.offers}</td>
                  <td className={CELL}>{r.bought}</td>
                  <td className={CELL}>{r.rate}</td>
                  <td className={CELL}>{r.money}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[12px] text-muted">Per-route numbers are buy rates of Full AI&apos;s own offers, not revenue proof.</p>
    </div>
  );
}
