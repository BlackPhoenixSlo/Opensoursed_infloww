"use client";

/**
 * Details: who claimed a free trial link or a promotion, and what each spent, as Infloww's Details fan table (Fan,
 * Total, Subs, Posts, Messages, Streams, Tips, then its summary row) with the claim date after the fan. The relay
 * reads OnlyFans' claimers list for the link (all of it, cached; `link_metrics`) and puts our ledger beside it.
 *
 * "Since claim / Lifetime":
 *   Since claim — the fan's spend in our ledger at or after the claim (OnlyFans' subscribeAt, as first read), net,
 *                 refunds and chargebacks left out. The list's Earnings, Fans who spent and Spend/Claim are this.
 *   Lifetime    — OnlyFans' own totals for the fan with this creator (net), whatever the fan came through.
 *
 * Export fans (Infloww's export-link-fans, which it emails): a CSV of this table in the mode shown.
 */

import { useState } from "react";

import { DASH, money, share } from "@/components/growth/linkMetrics";
import { downloadCsv } from "@/components/growth/LinksListFrame";
import { offerDate } from "@/components/growth/offerFormat";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useLinkFans, type LinkFan } from "@/hooks/useGrowth";
import { cn } from "@/lib/utils";

const COLS = ["total", "subs", "posts", "messages", "streams", "tips"] as const;
type ColKey = (typeof COLS)[number] | "other";
const HEAD: Record<ColKey, string> = {
  total: "Total", subs: "Subs", posts: "Posts", messages: "Messages", streams: "Streams", tips: "Tips", other: "Other",
};
const TD = "px-2 py-1 text-right tabular-nums whitespace-nowrap";

type Mode = "since" | "lifetime";

/** A fan's cell in the mode: cents, or null when the mode has no figure for the fan. */
function cell(f: LinkFan, mode: Mode, k: ColKey): number | null {
  if (mode === "since") return f.since ? f.since[`${k}_net_cents`] : null;
  return f.lifetime && k !== "other" ? f.lifetime[`${k}_cents`] : null;
}

export default function OfferClaimers({ accountId, kind, ofId, campaignId, count }: {
  accountId: string | null;
  kind: "trial" | "promo";
  ofId: number | null;
  /** A promotion campaign: its earlier re-armed OF promos fold in. */
  campaignId?: number | null;
  /** The row's claim count: the relay re-reads the link when it moved. */
  count?: number | null;
}) {
  const [mode, setMode] = useState<Mode>("since");
  const q = useLinkFans(accountId, kind, ofId, { campaignId, count });
  const exportAllowed = useActionAllowed("export");
  if (ofId == null) return <div className="text-[11px] text-fg-dim">Not linked to OnlyFans, so its claims can&apos;t be read.</div>;
  if (q.isLoading) return <div className="text-[11px] text-fg-dim">Loading claims…</div>;
  if (q.isError) return <div className="text-[11px] text-warn">OnlyFans not reachable — claims can&apos;t be read.</div>;
  const d = q.data!;
  const fans = d.fans;
  if (!fans.length) {
    return (
      <div className="text-[11px] text-fg-dim">
        {d.refreshing ? "Reading OnlyFans for this link's claims…" : "No claims yet."}
      </div>
    );
  }

  const known = fans.filter((f) => f.since);
  const spent = known.filter((f) => (f.since?.total_cents ?? 0) > 0).length;
  const earnings = known.reduce((n, f) => n + (f.since?.total_net_cents ?? 0), 0);
  const cols: ColKey[] = mode === "since" && fans.some((f) => (f.since?.other_net_cents ?? 0) !== 0)
    ? [...COLS, "other"] : [...COLS];
  const rows = fans.filter((f) => cell(f, mode, "total") != null);
  const sum = (k: ColKey) => rows.reduce((n, f) => n + (cell(f, mode, k) ?? 0), 0);
  const since = offerDate(d.ledger_since);
  const read = offerDate(d.walked_at);
  const exportFans = () => downloadCsv(`${kind === "trial" ? "free-trial" : "promotion"}-link-fans-${ofId}`, [
    ["Fan", "Username", "Claimed", ...cols.map((k) => HEAD[k])],
    ...fans.map((f) => [f.name ?? "", f.username ?? "", f.subscribe_at ?? f.first_seen_at ?? "",
      ...cols.map((k) => { const v = cell(f, mode, k); return v == null ? "" : (v / 100).toFixed(2); })]),
  ], null);

  return (
    <div className="text-[11px] text-fg-dim space-y-1">
      {known.length > 0 && (
        <div className="text-fg" data-offer-metrics>
          {kind === "promo"
            ? <>Revenue <b>{money(earnings)}</b> from {spent} fan{spent === 1 ? "" : "s"}</>
            : <>Earnings <b>{money(earnings)}</b> · Fans who spent <b>{spent}</b> · Spend/Claim <b>{share(spent, known.length)}</b></>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <div role="radiogroup" aria-label="Spend shown" className="inline-flex rounded-md border border-border p-0.5">
          {(["since", "lifetime"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={cn("h-6 px-2 rounded text-[11px]", mode === m ? "bg-bg-elev-2 text-fg font-medium" : "text-fg-dim")}
            >
              {m === "since" ? "Since claim" : "Lifetime"}
            </button>
          ))}
        </div>
        {exportAllowed && (
          <button type="button" onClick={exportFans} className="h-6 px-2 rounded-md border border-border text-[11px] text-fg">
            Export fans
          </button>
        )}
        {d.refreshing && <span>Refreshing from OnlyFans…</span>}
      </div>
      <div data-caveat>
        {mode === "since" ? (
          <>
            Net spend in our ledger since each fan claimed{since && <>, which starts {since}</>}; refunds and chargebacks
            left out. The claim date is OnlyFans&apos; subscription start as first read, so a fan who had already left
            and re-subscribed by then counts from the re-subscription.
          </>
        ) : (
          <>
            OnlyFans&apos; lifetime totals (net) per fan with this creator, through any link{read && <>, as read {read}</>}.
          </>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px]" aria-label="Claimed by">
          <thead>
            <tr className="text-fg-dim">
              <th className="px-2 py-1 text-left font-medium">Fan</th>
              <th className="px-2 py-1 text-left font-medium">Claimed</th>
              {cols.map((k) => <th key={k} className={`${TD} font-medium`}>{HEAD[k]}</th>)}
            </tr>
          </thead>
          <tbody>
            {fans.map((f) => (
              <tr key={f.fan_id} className="border-t border-border" data-fan-row>
                <td className="px-2 py-1">
                  <span className="text-fg">{f.name || `#${f.fan_id}`}</span>{f.username ? <span> @{f.username}</span> : null}
                </td>
                <td className="px-2 py-1 whitespace-nowrap">
                  {f.subscribe_at
                    ? offerDate(f.subscribe_at)
                    : <span title="OnlyFans sent no claim date: the first time we read the fan under this link">
                      {offerDate(f.first_seen_at)} (first seen)
                    </span>}
                </td>
                {cols.map((k) => {
                  const v = cell(f, mode, k);
                  return <td key={k} className={TD}>{v == null ? DASH : money(v)}</td>;
                })}
              </tr>
            ))}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr className="border-t border-border text-fg font-medium" data-fan-sum>
                <td className="px-2 py-1" colSpan={2}>Total</td>
                {cols.map((k) => <td key={k} className={TD}>{money(sum(k))}</td>)}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
