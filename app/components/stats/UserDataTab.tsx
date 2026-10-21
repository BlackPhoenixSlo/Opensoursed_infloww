"use client";

/**
 * UserDataTab — the per-fan profile data gen_info builds, read live from our
 * DB so the team can check it in-app. Search, and scan the columns:
 * name / nickname / spend / msgs / short bio / Q1-3 / Tease1-3 / note-on-OF.
 * The Creator is the page's (Fan reports' creator column).
 *
 * Source: GET /admin/stats/per-fan-data (usePerFanData) → service/fan_data.py
 * build_fan_data.
 */

import { useMemo, useState } from "react";

import { Card, Input } from "@/components/ui/primitives";
import { usePerFanData, type FanDataRow } from "@/hooks/useStats";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

function fmtSpend(n: number): string {
  return n > 0 ? `$${n.toFixed(2)}` : "—";
}
function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toISOString().slice(0, 10);
}

export default function UserDataTab({ accountId }: {
  /** The page's Creator. */
  accountId: string;
}) {
  const [q, setQ] = useState("");
  const dataQ = usePerFanData(accountId);
  const rows = useMemo(() => dataQ.data?.rows ?? [], [dataQ.data]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      [r.fan_name, r.nickname, r.short_bio, r.q1, r.q2, r.q3, String(r.fan_id)]
        .some((v) => (v || "").toLowerCase().includes(needle)),
    );
  }, [rows, q]);

  return (
    <Card className="p-4 space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-3">
        {/* Fan data: an Inflowwww extra (ADR-0003; docs/infloww-screens.md "Fan reports") */}
        <div className="min-w-0" title={EXTRA_LABEL}>
          <h2 className="text-sm font-medium text-fg">User data</h2>
          <p className="text-xs text-fg-dim">
            Per-fan profiles built by gen_info, read live from our DB. Sorted by
            spend.
          </p>
        </div>
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-2 w-full sm:w-auto">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name / nickname / bio…"
            className="w-full sm:w-56 text-base sm:text-sm"
          />
        </div>
      </header>

      <div className="text-xs text-fg-dim">
        {dataQ.isLoading
          ? "Loading…"
          : dataQ.isError
            ? "Failed to load."
            : `${filtered.length}${filtered.length !== rows.length ? ` of ${rows.length}` : ""} fans`}
      </div>

      <div className="overflow-x-auto border border-border rounded-lg">
        <table className="w-full text-xs">
          <thead className="bg-bg-elev-1 text-fg-dim">
            <tr className="text-left">
              <Th>Fan</Th>
              <Th>Nickname</Th>
              <Th>Lang</Th>
              <Th className="text-right">Spend</Th>
              <Th className="text-right">Msgs</Th>
              <Th>Short bio</Th>
              <Th>Rich note</Th>
              <Th>Q1 / Q2 / Q3</Th>
              <Th>Tease 1 / 2 / 3</Th>
              <Th>Note on OF</Th>
              <Th>Updated</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <Row key={`${r.account_id}:${r.fan_id}`} r={r} />
            ))}
            {!dataQ.isLoading && filtered.length === 0 && (
              <tr>
                <td colSpan={11} className="px-3 py-6 text-center text-fg-dim">
                  No profiled fans yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`px-3 py-2 font-medium whitespace-nowrap ${className}`}>{children}</th>;
}

function Stack({ items }: { items: string[] }) {
  const real = items.filter(Boolean);
  if (real.length === 0) return <span className="text-fg-dim">—</span>;
  return (
    <ul className="space-y-0.5">
      {real.map((t, i) => (
        <li key={i} className="text-fg-dim">• {t}</li>
      ))}
    </ul>
  );
}

function Row({ r }: { r: FanDataRow }) {
  return (
    <tr className="border-t border-border align-top hover:bg-bg-elev-1/40">
      <td className="px-3 py-2 whitespace-nowrap">
        <div className="text-fg">{r.fan_name || r.fan_id}</div>
        <div className="text-[10px] text-fg-dim font-mono">{r.fan_id}</div>
      </td>
      <td className="px-3 py-2 whitespace-nowrap">{r.nickname || <span className="text-fg-dim">—</span>}</td>
      <td className="px-3 py-2 whitespace-nowrap uppercase font-mono text-[10px]">
        {r.language ? r.language : <span className="text-fg-dim">—</span>}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap font-medium">{fmtSpend(r.total_spend)}</td>
      <td className="px-3 py-2 text-right whitespace-nowrap">{r.message_count || "—"}</td>
      <td className="px-3 py-2 max-w-[260px]"><span className="text-fg-dim">{r.short_bio || "—"}</span></td>
      <td className="px-3 py-2 max-w-[300px]">
        <span className="text-fg-dim whitespace-pre-line line-clamp-4">{r.bullet_points || "—"}</span>
      </td>
      <td className="px-3 py-2 max-w-[260px]"><Stack items={[r.q1, r.q2, r.q3]} /></td>
      <td className="px-3 py-2 max-w-[260px]"><Stack items={[r.tease1, r.tease2, r.tease3]} /></td>
      <td className="px-3 py-2 whitespace-nowrap">
        <span className={r.note_on_of === "added" ? "text-ok" : "text-fg-dim"}>{r.note_on_of}</span>
      </td>
      <td className="px-3 py-2 whitespace-nowrap text-fg-dim">{fmtDate(r.last_updated)}</td>
    </tr>
  );
}
