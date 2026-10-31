"use client";

/** Creator reports' primitives and charts: the Not wired marker, cards and titles, the summary tile and stat card,
 *  the sparkline, the trend bars and the donut. */

import { ArrowDownLeft, ArrowUpRight, Info as InfoCircle, type LucideIcon } from "lucide-react";

import { BlankChart, ChartAxes, ChartMessage, fmtUsd, niceMax, plotFrame, useChartWidth } from "@/components/stats/chart";
import { growthOf, type Growth } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import type { Point } from "./reportsMath";

/* ───────── primitives ───────── */

/** The house Not wired marker, read as "-" (#58, #147). */
export function NotWired({ label }: { label: string }) {
  return (
    <button type="button" disabled title="not wired" aria-label={label} className="cursor-not-allowed opacity-50">
      -
    </button>
  );
}

/** #44: a report card, 16px padding and 12px radius by default, on our raised surface (ADR-0001 colours). */
export function ReportCard({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("rounded-xl p-4", className)} style={{ background: "var(--color-bg-elev-1)" }}>
      {children}
    </div>
  );
}

/** #46 to #48: a section title, 20px weight 500, 16px below, a 24px info icon 8px to its right. */
export function SectionTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center mb-4">
      <h2 id={id} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>{label}</h2>
      <span title={tip} className="ml-2 inline-flex" style={{ color: "var(--color-fg-dim)" }}>
        <InfoCircle size={24} aria-hidden />
      </span>
    </div>
  );
}

/** #63, #64: a card title, 16px weight 500, a 16px info icon 8px to its right when it has a tooltip. */
export function CardTitle({ id, label, tip, className }: { id: string; label: string; tip?: string; className?: string }) {
  return (
    <div className={cn("flex items-center", className)}>
      <h3 id={id} className="text-base font-medium leading-5" style={{ color: "var(--color-fg)" }}>{label}</h3>
      {tip && (
        <span title={tip} className="ml-2 inline-flex" style={{ color: "var(--color-fg-dim)" }}>
          <InfoCircle size={16} aria-hidden />
        </span>
      )}
    </div>
  );
}

/** #55 to #60: a summary tile, its title (with a 20px icon 4px away), value and growth. The total tile is larger.
 *  A `null` value is Not wired. */
export function SummaryTile({ label, Icon, total, value, growth }: {
  label: string; Icon: LucideIcon; total: boolean; value: string | null; growth: Growth;
}) {
  // #59: rising and falling on our ok and pink tokens (ADR-0001 colours).
  const color = growth.dir === "up" ? "var(--color-ok)" : growth.dir === "down" ? "var(--color-pink)" : "var(--color-fg)";
  const Arrow = growth.dir === "up" ? ArrowUpRight : ArrowDownLeft;
  return (
    // The capture has no phone layout: below md the total tile spans both columns and long values wrap.
    <div role="group" aria-label={label} className={cn("flex flex-col min-w-0 [overflow-wrap:anywhere]", total && "gap-0.5 col-span-2 md:col-span-1")}>
      <dt
        // #51, #53: Text$5's tracking, heading4's 0.034px or body1's 0.032px on the title and growth, heading1's
        // 0.128px or heading2's 0.098px on the value.
        className={cn("flex items-center gap-1 font-medium", total ? "text-xl leading-6 tracking-[0.034px]" : "text-base leading-5 tracking-[0.032px] mb-2")}
        style={{ color: "var(--color-fg-dim)" }}
      >
        <Icon size={20} aria-hidden />
        {label}
      </dt>
      <dd
        className={cn("font-medium tabular-nums", total ? "text-[32px] leading-9 tracking-[0.128px]" : "text-[28px] leading-8 tracking-[0.098px]")}
        style={{ color: "var(--color-fg)" }}
      >
        {value === null ? <NotWired label={label} /> : value}
      </dd>
      <dd
        className={cn("inline-flex items-center font-medium", total ? "text-xl leading-6 tracking-[0.034px] -translate-y-1" : "text-base leading-5 tracking-[0.032px]")}
        style={{ color }}
      >
        {growth.dir && (
          <Arrow size={total ? 24 : 20} role="img" aria-label={growth.dir === "up" ? "rising" : "falling"} />
        )}
        {growth.text}
      </dd>
    </div>
  );
}

/** #102 to #104: a Creator statistics card, 104px high, its label (16px weight 500, a 16px info icon 4px away) 12px
 *  over its value (32px weight 500). A `null` value is Not wired. */
export function StatCard({ label, tip, value }: { label: string; tip: string; value: string | null }) {
  return (
    <li className="flex-1 min-w-0 md:mr-4 md:last:mr-0">
      <div
        role="group"
        aria-label={label}
        className="h-[104px] rounded-xl p-4 flex flex-col gap-3"
        style={{ background: "var(--color-bg-elev-1)", color: "var(--color-fg)" }}
      >
        {/* #53, #103: body1's 0.032px tracking on the label, heading1's 0.128px on the value. */}
        <span className="flex items-center gap-1 text-base leading-5 tracking-[0.032px] font-medium">
          {label}
          <span title={tip} className="inline-flex" style={{ color: "var(--color-fg-dim)" }}>
            <InfoCircle size={16} aria-hidden />
          </span>
        </span>
        <span className="text-[32px] leading-9 tracking-[0.128px] font-medium tabular-nums truncate">
          {value === null ? <NotWired label={label} /> : value}
        </span>
      </div>
    </li>
  );
}

/** #159, #160: a Creator performance block title, 16px weight 500 on 16px, its info icon 9px away and 1px down. */
export function PerfTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center">
      <h3 id={id} className="text-base font-medium leading-4 mr-[9px]" style={{ color: "var(--color-fg)" }}>{label}</h3>
      <span title={tip} className="inline-flex translate-y-px" style={{ color: "var(--color-fg-dim)" }}>
        <InfoCircle size={16} aria-hidden />
      </span>
    </div>
  );
}

/** #164, #166: a growth row's 140px by 25px sparkline of the channel's days. */
export function Sparkline({ values, color }: { values: number[]; color: string }) {
  const W = 140, H = 25;
  const max = Math.max(1, ...values);
  const x = (i: number) => (values.length <= 1 ? W / 2 : (i / (values.length - 1)) * W);
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0" aria-hidden>
      <path
        d={values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${(H - 1 - (v / max) * (H - 2)).toFixed(2)}`).join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
      />
    </svg>
  );
}


/* ───────── charts ───────── */

/** #83: a bar with only its top corners rounded, 2px below 24px wide, 4px below 60px, else 8px, never more than half
 *  its width or its height. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(w < 24 ? 2 : w < 60 ? 4 : 8, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** #67, #82, #83: Earnings trends, a 220px bar chart, each bar's tooltip its Earnings and its Growth over the bucket
 *  before. `perf` is Creator performance's Earnings (#161, #162): 336px high, 25px bars (never wider than their slot),
 *  the x labels 16px off the axis. `null` points draw the blank chart with `message`. */
export function TrendBars({ points, message, height = 220, perf = false }: {
  points: Point[] | null; message: string; height?: number; perf?: boolean;
}) {
  const [ref, W] = useChartWidth();
  const H = height;
  const f = plotFrame(W, H);
  const n = points?.length ?? 0;
  const max = niceMax(Math.max(1, ...(points ?? []).map((p) => p.value)), 4);
  const slot = (f.R - f.L) / Math.max(1, n);
  // Each bar 80% of its slot, whole pixels above 1px, at most 96px; Creator performance's 25px (`barWidth:25`).
  const raw = slot * 0.8;
  const bw = perf ? Math.min(25, slot) : Math.min(96, raw > 1 ? Math.floor(raw) : raw);
  const xAt = (i: number) => f.L + slot * (i + 0.5);
  return (
    <div ref={ref} className="relative">
      <ChartMessage message={points ? "" : message} title={EXTRA_LABEL} />
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block">
        {!points ? <BlankChart W={W} H={H} /> : (
          <>
            <ChartAxes W={W} H={H} max={max} labels={points.map((p) => p.label)} xAt={xAt} labelGap={perf ? 16 : undefined} />
            {points.map((p, i) => {
              const h = (p.value / max) * (f.B - f.T);
              const growth = growthOf(p.value, i > 0 ? points[i - 1].value : null);
              const g = (growth.dir === "down" ? "-" : "") + growth.text;
              return (
                <path
                  key={i}
                  role="img"
                  aria-label={`${p.label}: ${fmtUsd(p.value)}`}
                  d={barPath(xAt(i) - bw / 2, f.B - h, bw, h)}
                  className="fill-accent"
                >
                  <title>{`${p.label}\nEarnings ${fmtUsd(p.value)}\nGrowth ${g}`}</title>
                </path>
              );
            })}
          </>
        )}
      </svg>
    </div>
  );
}

/** #78, #84: Earnings breakdown, a 200px donut (inner radius 55, outer 85); an empty ring with nothing to show.
 *  `perf` is Creator performance's (#164): 180px high and 35px down, its ring 69% to 80% of the half height
 *  (`radius:["80%","69%"]`), 62.1px to 72px. */
export function Donut({ slices, perf = false }: { slices: { color: string; cents: number }[] | null; perf?: boolean }) {
  const H = perf ? 180 : 200;
  const [inner, outer] = perf ? [0.69 * 90, 0.8 * 90] : [55, 85];
  const cx = 172, cy = H / 2, r = (inner + outer) / 2, sw = outer - inner, C = 2 * Math.PI * r;
  const sum = (slices ?? []).reduce((a, s) => a + s.cents, 0);
  let at = 0;
  return (
    <svg
      viewBox={`0 0 344 ${H}`}
      className={cn("block w-full", perf ? "h-[180px] mt-[35px]" : "h-[200px] my-2")}
      role="img"
      aria-label={sum > 0 ? "Earnings breakdown chart" : "No earnings"}
    >
      <circle cx={cx} cy={cy} r={r} fill="none" strokeWidth={sw} style={{ stroke: "color-mix(in srgb, var(--color-fg) 24%, transparent)" }} />
      {sum > 0 && slices!.map((s, i) => {
        const len = (C * s.cents) / sum;
        const offset = -at;
        at += len;
        return len > 0 ? (
          <circle
            key={i}
            cx={cx} cy={cy} r={r} fill="none" stroke={s.color} strokeWidth={sw}
            strokeDasharray={`${len.toFixed(2)} ${(C - len).toFixed(2)}`}
            strokeDashoffset={offset.toFixed(2)}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        ) : null;
      })}
    </svg>
  );
}
