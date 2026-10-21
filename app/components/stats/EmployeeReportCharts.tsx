"use client";

/**
 * EmployeeReportCharts — Employee reports' charts (roadmap W5 5.10; Infloww's Overview and Employee performance tabs,
 * 05-analytics M3, M4), from ONE read of `GET /admin/stats/chatting-stats?bucket=` over the report's range: the summed
 * series and each Employee's. The page's tab bar (EmployeeReport, page-parity ticket 27) owns the tabs and the
 * "Shown by" select; this module draws each tab's body from `useEmployeeCharts`.
 *
 *   Overview              "Employee sales" (every Employee in scope summed), "Employee comparison" (up to three
 *                         Employees' sales lines) and "Sales ranking" (Chatting statistics' Sales, top 10, then
 *                         "MORE>>"; Descending / Ascending).
 *   Employee performance  one Employee: "Sales" and "Message statistics" (direct messages and PPVs sent, PPVs
 *                         unlocked, fans chatted).
 *
 * "Shown by" offers the granularities the range's calendar days allow (`granAllowed`). Sales follow the Sales
 * Settings rules and count pending sales; the Employees offered are those with a Chatting statistics row in the range
 * (a "self" Data scope gets only its own). An answer without `series` or `by_employee` draws empty charts rather than
 * throwing (the route walk's catch-all `{}`).
 */

import { Info } from "lucide-react";
import { useMemo, useState } from "react";

import { type Gran, LineChart, granAllowed } from "@/components/stats/chart";
import { EmptyState, IfSelect } from "@/components/ui/infloww";
import {
  type ChattingSeriesFigures, type ChattingSeriesResp, type ChattingStatsRow, useChattingSeries, useChattingStats,
} from "@/hooks/useStats";
import { fmtCents, fmtInt } from "@/lib/format";
import { cn } from "@/lib/utils";

// Infloww's comparison colours; the fourth for Message statistics' fourth line.
const COLORS = ["#3467FF", "#2AD4AC", "#FFA15F", "#ac72d2"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const GRANS: { value: Gran; label: string }[] = [
  { value: "hour", label: "Shown by hour" }, { value: "day", label: "Shown by day" },
  { value: "week", label: "Shown by week" }, { value: "month", label: "Shown by month" },
];
const MESSAGE_LINES: { key: keyof ChattingSeriesFigures; name: string }[] = [
  { key: "direct_messages_sent", name: "Direct messages sent" },
  { key: "direct_ppvs_sent", name: "Direct PPVs sent" },
  { key: "ppvs_unlocked", name: "PPVs unlocked" },
  { key: "fans_chatted", name: "Fans chatted" },
];
const ZERO: ChattingSeriesFigures = {
  sales_cents: 0, direct_messages_sent: 0, direct_ppvs_sent: 0, ppvs_unlocked: 0, fans_chatted: 0,
};

/** A point's x label from its "YYYY-MM-DDTHH:MM" start (report-zone wall time, so no Date parsing). */
export function bucketLabel(start: string, bucket: Gran): string {
  const [y, m, d, h] = [start.slice(0, 4), Number(start.slice(5, 7)), Number(start.slice(8, 10)), Number(start.slice(11, 13))];
  if (bucket === "month") return `${MONTHS[m - 1]} ${y}`;
  const day = `${MONTHS[m - 1]} ${d}`;
  return bucket === "hour" ? `${day} ${h % 12 || 12} ${h < 12 ? "AM" : "PM"}` : day;
}

const name = (r: ChattingStatsRow) => r.display_name ?? `Employee #${r.employee_id}`;

/** One Employee's points, zeros when the read has none for it (no sales or sends in the range). */
function pointsOf(data: ChattingSeriesResp, id: number): ChattingSeriesFigures[] {
  return data.by_employee?.[String(id)] ?? (data.series ?? []).map(() => ZERO);
}

/** The tab bar's "Shown by" select: the granularities the range's `days` allow, the rest disabled. */
export function ShownBySelect({ days, value, onChange }: { days: number; value: Gran; onChange: (g: Gran) => void }) {
  return (
    <IfSelect<Gran> aria-label="Shown by" className="w-[140px]" value={value} onChange={onChange}
      options={GRANS.map((g) => ({ ...g, disabled: !granAllowed(g.value, days) }))} />
  );
}

/** What both tabs draw from: the Chatting statistics rows (the Employees offered) and the series read. */
export type ChartProps = {
  data: ChattingSeriesResp | null; error: boolean; bucket: Gran; rows: ChattingStatsRow[];
  /** Reads the series again (the error state's Retry). */
  onRetry?: () => void;
};

/** The two reads behind the charts, shared by both tabs (react-query keys them, so a tab switch reads nothing). */
export function useEmployeeCharts(from: string | null, to: string | null, bucket: Gran, chatterOnly = false): ChartProps {
  const stats = useChattingStats(from, to, chatterOnly);
  const rows = useMemo(() => stats.data?.employees ?? [], [stats.data]);
  const series = useChattingSeries(from, to, bucket, chatterOnly);
  const { refetch } = series;
  return { data: series.data ?? null, error: series.isError, bucket, rows, onRetry: () => { void refetch(); } };
}

const LOADING = "Loading…";
const labelsOf = (data: ChattingSeriesResp | null, bucket: Gran) =>
  (data?.series ?? []).map((p) => bucketLabel(p.start, bucket));

/** Infloww's `Empty$1` with Retry in place of a tab's charts when the series read fails. */
function ChartsError({ onRetry }: { onRetry?: () => void }) {
  return <EmptyState kind="error" text="Failed to load" onRetry={onRetry} className="py-16" />;
}

/** The Overview tab's charts: Employee sales, then Employee comparison beside Sales ranking. */
export function EmployeeOverviewCharts({ data, error, bucket, rows, onRetry }: ChartProps) {
  const [slots, setSlots] = useState<(number | null)[]>([null, null, null]);
  if (error) return <ChartsError onRetry={onRetry} />;
  const names = new Map(rows.map((r) => [r.employee_id, name(r)]));
  const labels = labelsOf(data, bucket);
  const compared = data && slots.flatMap((id, i) => (id == null ? [] : [{
    name: names.get(id) ?? `Employee #${id}`, color: COLORS[i], values: pointsOf(data, id).map((p) => p.sales_cents),
  }]));

  return (
    <>
      <Section title="Employee sales" tip="Sales of every employee, according to your sales settings">
        <LineChart labels={labels} message={LOADING} valueFmt={fmtCents}
          lines={data ? [{ name: "Employee sales", color: COLORS[0], values: (data.series ?? []).map((p) => p.sales_cents) }] : null} />
      </Section>
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <Section title="Employee comparison" tip="Compare sales and performance of up to three employees">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {slots.map((id, i) => (
              <span key={i} className="flex items-center gap-2">
                {i > 0 && <span className="text-fg-dim">-</span>}
                <IfSelect<string> aria-label={`Employee ${i + 1}`} className="w-[140px]" placeholder="Select" searchable
                  value={id == null ? null : String(id)}
                  onChange={(v) => setSlots((s) => s.map((x, j) => (j === i ? (v ? Number(v) : null) : x)))}
                  options={[{ value: "", label: "None" }, ...rows.map((r) => ({
                    value: String(r.employee_id), label: name(r), text: name(r),
                    disabled: slots.some((x, j) => j !== i && x === r.employee_id),
                  }))]} />
              </span>
            ))}
          </div>
          <LineChart labels={labels} message={LOADING} valueFmt={fmtCents} lines={compared}
            empty={(
              <p className="absolute inset-0 flex items-center justify-center text-sm text-fg-dim">
                Select up to three employees to compare
              </p>
            )} />
        </Section>
        <SalesRanking rows={rows} />
      </div>
    </>
  );
}

const axisCount = (n: number) => String(Math.round(n));

function SalesRanking({ rows }: { rows: ChattingStatsRow[] }) {
  const [desc, setDesc] = useState(true);
  const [more, setMore] = useState(false);
  const sorted = [...rows].sort((a, b) => (desc ? b.sales_cents - a.sales_cents : a.sales_cents - b.sales_cents));
  return (
    <section aria-label="Sales ranking">
      <header className="flex items-center justify-between mb-4">
        <h3 className="text-[16px] font-medium text-fg">Sales ranking</h3>
        <button type="button" className="text-xs text-fg-dim hover:text-fg" onClick={() => setDesc((d) => !d)}>
          {desc ? "Descending ↓" : "Ascending ↑"}
        </button>
      </header>
      {sorted.length === 0 ? <EmptyState size="sm" /> : (
        <ol className="space-y-2">
          {sorted.slice(0, more ? undefined : 10).map((r, i) => (
            <li key={r.employee_id} className="flex items-center gap-3 text-sm">
              <span className={cn("h-5 w-5 shrink-0 rounded-full text-[11px] flex items-center justify-center",
                i < 3 ? "bg-[#2AD4AC] text-white" : "bg-bg-elev-2 text-fg-dim")}>{i + 1}</span>
              <span className="flex-1 truncate text-fg">{name(r)}</span>
              <span className="tabular-nums text-accent">{fmtCents(r.sales_cents)}</span>
            </li>
          ))}
        </ol>
      )}
      {sorted.length > 10 && !more && (
        <button type="button" className="mt-2 text-xs text-accent hover:underline" onClick={() => setMore(true)}>MORE&gt;&gt;</button>
      )}
    </section>
  );
}

/** The Employee performance tab: the picked Employee (the top seller until one is picked), its Sales and Message
 *  statistics. The Employee select sits at the body's right, as Infloww's does, with the name as a tag at the left. */
export function EmployeePerformance({ data, error, bucket, rows, onRetry }: ChartProps) {
  const [picked, setPicked] = useState<number | null>(null);
  if (error) return <ChartsError onRetry={onRetry} />;
  const top = rows.reduce<ChattingStatsRow | null>((t, r) => (!t || r.sales_cents > t.sales_cents ? r : t), null);
  const id = picked != null && rows.some((r) => r.employee_id === picked) ? picked : top?.employee_id ?? null;
  if (id == null) return <EmptyState text="No chatting in this window." className="py-16" />;
  const points = data ? pointsOf(data, id) : null;
  const labels = labelsOf(data, bucket);
  const current = rows.find((r) => r.employee_id === id);
  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex h-8 items-center rounded-[4px] bg-accent px-4 text-[14px] text-white">
          {current ? name(current) : `Employee #${id}`}
        </span>
        <IfSelect<string> aria-label="Employee" className="w-[200px]" searchable value={String(id)}
          onChange={(v) => setPicked(Number(v))}
          options={rows.map((r) => ({ value: String(r.employee_id), label: name(r), text: name(r) }))} />
      </div>
      <Section title="Sales" tip="Sales generated by the employee, according to your sales settings">
        <LineChart labels={labels} message={LOADING} valueFmt={fmtCents}
          lines={points ? [{ name: "Employee sales", color: COLORS[0], values: points.map((p) => p.sales_cents) }] : null} />
      </Section>
      <Section title="Message statistics" tip="Does not include mass messages or automated messages">
        <LineChart labels={labels} message={LOADING} fmt={axisCount} valueFmt={fmtInt}
          lines={points ? MESSAGE_LINES.map((l, i) => ({ name: l.name, color: COLORS[i],
            values: points.map((p) => p[l.key]) })) : null} />
      </Section>
    </>
  );
}

/** A chart section on the page colour, as Infloww's: the title 16px / 500 in element-emphasis-00 (#ffffff dark, the
 *  live capture) with its (i) tip 8px after it. */
function Section({ title, tip, children }: { title: string; tip: string; children: React.ReactNode }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-3 flex items-center gap-2 text-[16px] font-medium text-nav-fg-active">
        {title}
        <span role="img" aria-label={tip} title={tip} className="cursor-help text-fg-dim">
          <Info className="h-3.5 w-3.5" aria-hidden />
        </span>
      </h3>
      {children}
    </section>
  );
}
