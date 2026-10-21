"use client";

/**
 * ShareReport — the public page behind a share link (`/share/<id>.<secret>`, `ShareLinksPanel`): no sign-in, no app
 * shell (AuthGate renders it bare). It reads `/share/<key>/data` (the relay's public route, outside every gate) once
 * and draws the links the owner picked: name, date created, OnlyFans' counts and, with "Include earnings", net
 * Earnings, Fans who spent and Spend share. Never a fan. Unknown link: "not found"; revoked or past 7 days: expired.
 */

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { DASH, money, share } from "@/components/growth/linkMetrics";
import { cn } from "@/lib/utils";

type Row = {
  name: string;
  created_at: string | null;
  claims?: number | null;
  clicks?: number | null;
  subscribers?: number | null;
  earnings_cents?: number | null;
  fans_who_spent?: number | null;
  fans_counted?: number | null;
};

type Report = {
  name: string;
  kind: "trial" | "campaign";
  include_earnings: boolean;
  updated_at: string | null;
  expires_at: string;
  /** False: no read of the links has filled it yet. */
  ready: boolean;
  links: Row[];
};

class Gone extends Error {
  constructor(readonly status: number) { super(String(status)); }
}

async function load(key: string): Promise<Report> {
  const r = await fetch(`/share/${encodeURIComponent(key)}/data`, { credentials: "omit", cache: "no-store" });
  if (!r.ok) throw new Gone(r.status);
  return r.json();
}

const TH = "px-3 py-2 text-left font-medium text-fg-dim whitespace-nowrap";
const TD = "px-3 py-2 border-t border-border whitespace-nowrap tabular-nums";
const count = (n: number | null | undefined) => (n == null ? DASH : n.toLocaleString());
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : DASH);

export default function ShareReport() {
  const key = (usePathname() ?? "").split("/")[2] ?? "";
  const q = useQuery({ queryKey: ["share-report", key], queryFn: () => load(key), enabled: !!key, retry: false });

  if (q.isLoading) return <Shell><p className="text-fg-dim">Loading…</p></Shell>;
  if (q.isError || !q.data) {
    const expired = q.error instanceof Gone && q.error.status === 410;
    return (
      <Shell>
        <h1 className="text-lg font-semibold">{expired ? "This share link has expired" : "Share link not found"}</h1>
        <p className="mt-2 text-sm text-fg-dim">
          {expired ? "Ask whoever sent it for a new one." : "Check the address, or ask whoever sent it for a new one."}
        </p>
      </Shell>
    );
  }
  const d = q.data;
  const trial = d.kind === "trial";
  if (!d.ready) {
    return (
      <Shell>
        <h1 className="text-lg font-semibold">{d.name}</h1>
        <p className="mt-2 text-sm text-fg-dim">This report is being prepared. Check back in a few minutes.</p>
      </Shell>
    );
  }
  return (
    <Shell>
      <h1 className="text-lg font-semibold">{d.name}</h1>
      <p className="mt-1 text-sm text-fg-dim">
        {trial ? "Free trial links" : "Tracking links"} · Updated {day(d.updated_at)} · Expires {day(d.expires_at)}
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm" aria-label="Links">
          <thead>
            <tr>
              <th className={TH}>{trial ? "Free trial link" : "Tracking link"}</th>
              <th className={TH}>Date created</th>
              {trial ? <th className={TH}>Claims</th> : <th className={TH}>Clicks</th>}
              {trial ? <th className={TH}>Clicks</th> : <th className={TH}>Subscribers</th>}
              {d.include_earnings && (
                <>
                  <th className={TH}>Earnings</th>
                  <th className={TH}>Fans who spent</th>
                  <th className={TH}>{trial ? "Spend/Claim" : "Spending CVR"}</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {d.links.map((l, i) => (
              <tr key={i}>
                <td className={cn(TD, "max-w-[280px] truncate")} title={l.name}>{l.name || "(unnamed)"}</td>
                <td className={TD}>{day(l.created_at)}</td>
                <td className={TD}>{count(trial ? l.claims : l.clicks)}</td>
                <td className={TD}>{count(trial ? l.clicks : l.subscribers)}</td>
                {d.include_earnings && (
                  <>
                    <td className={TD}>{l.earnings_cents == null ? DASH : money(l.earnings_cents)}</td>
                    <td className={TD}>{count(l.fans_who_spent)}</td>
                    <td className={TD}>{share(l.fans_who_spent, l.fans_counted)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.include_earnings && (
        <p className="mt-3 text-xs text-fg-dim">Earnings are net, from the fans who came through each link.</p>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="min-h-screen bg-bg text-fg p-6 md:p-10"><div className="mx-auto max-w-5xl">{children}</div></main>;
}
