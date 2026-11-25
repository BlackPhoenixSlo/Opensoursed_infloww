"use client";


import { ArrowDownLeft, ArrowUpRight, type LucideIcon } from "lucide-react";

import { BlankChart, ChartAxes, ChartMessage, fmtUsd, niceMax, plotFrame, useChartWidth } from "@/components/stats/chart";
import { growthOf, type Growth } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import type { Point } from "./reportsMath";
import { InfoTip } from "@/components/ui/InfoTip";


export function NotWired({ label }: { label: string }) {
  return (
    <button type="button" disabled title="not wired" aria-label={label} className="cursor-not-allowed opacity-50">
      -
    </button>
  );
}

export function ReportCard({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("report-surface rounded-xl p-4", className)} style={{ background: "var(--color-bg-elev-1)" }}>
      {children}
    </div>
  );
}

export function SectionTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center mb-4">
      <h2 id={id} className="text-xl font-medium leading-[1.2]" style={{ color: "var(--color-fg)" }}>{label}</h2>
      <InfoTip text={tip} iconClassName="h-6 w-6" className="ml-2" style={{ color: "var(--color-fg-dim)" }} />
    </div>
  );
}

export function CardTitle({ id, label, tip, className }: { id: string; label: string; tip?: string; className?: string }) {
  return (
    <div className={cn("flex items-center", className)}>
      <h3 id={id} className="text-base font-medium leading-5" style={{ color: "var(--color-fg)" }}>{label}</h3>
      {tip && (
        <InfoTip text={tip} iconClassName="h-4 w-4" className="ml-2" style={{ color: "var(--color-fg-dim)" }} />
      )}
    </div>
  );
}

export function PartialMark({ reason, className }: { reason: string; className?: string }) {
  return <span data-partial role="note" aria-label={reason} title={reason} className={cn("text-warn", className)}>*</span>;
}

export function SummaryTile({ label, Icon, rgb, total, value, growth, growthTitle, negative = false, title, partial }: {
  label: string; Icon: LucideIcon; total: boolean; value: string | null; growth: Growth; negative?: boolean; title?: string;
  partial?: string;
  growthTitle?: string;
  rgb?: string;
}) {
  const color = growth.dir === "up" ? "var(--color-ok)" : growth.dir === "down" ? "var(--color-pink)" : "var(--color-fg)";
  const Arrow = growth.dir === "up" ? ArrowUpRight : ArrowDownLeft;
  return (
    <div role="group" aria-label={label} title={title} className={cn("flex flex-col min-w-0 [overflow-wrap:anywhere]", total && "gap-0.5 col-span-2 md:col-span-1")}>
      <dt
        className={cn("flex items-center gap-1 font-medium", total ? "text-xl leading-6 tracking-[0.034px]" : "text-base leading-5 tracking-[0.032px] mb-2")}
        style={{ color: "var(--color-fg-dim)" }}
      >
        <Icon size={22} strokeWidth={1.75} aria-hidden
          style={rgb ? { color: `rgb(${rgb})`, background: `rgba(${rgb}, 0.1)` } : undefined} />
        {label}
      </dt>
      <dd
        className={cn("font-medium tabular-nums", total ? "text-[32px] leading-9 tracking-[0.128px]" : "text-[28px] leading-8 tracking-[0.098px]")}
        style={{ color: negative ? "var(--color-err)" : "var(--color-fg)" }}
      >
        {value === null ? <NotWired label={label} /> : value}
        {partial && <PartialMark reason={partial} className="ml-1 align-top text-[0.6em]" />}
      </dd>
      <dd
        className={cn("inline-flex items-center font-medium", total ? "text-xl leading-6 tracking-[0.034px] -translate-y-1" : "text-base leading-5 tracking-[0.032px]")}
        style={{ color }}
        title={growthTitle}
      >
        {growth.dir && (
          <Arrow size={total ? 24 : 20} role="img" aria-label={growth.dir === "up" ? "rising" : "falling"} />
        )}
        {growth.text}
      </dd>
    </div>
  );
}

export function StatCard({ label, tip, value, valueTitle, stat }: {
  label: string; tip?: string; value: string | null; valueTitle?: string;
  stat?: string;
}) {
  return (
    <li data-stat={stat} className="flex-1 min-w-0 md:mr-4 md:last:mr-0">
      <div
        role="group"
        aria-label={label}
        className="h-[104px] rounded-xl p-4 flex flex-col gap-3"
        style={{ background: "var(--color-bg-elev-1)", color: "var(--color-fg)" }}
      >
        <span className="flex items-center gap-1 text-base leading-5 tracking-[0.032px] font-medium">
          {label}
          {tip && <InfoTip text={tip} iconClassName="h-4 w-4" style={{ color: "var(--color-fg-dim)" }} />}
        </span>
        <span data-value={stat ? "" : undefined} title={valueTitle} className="text-[32px] leading-9 tracking-[0.128px] font-medium tabular-nums truncate">
          {value === null ? <NotWired label={label} /> : value}
        </span>
      </div>
    </li>
  );
}

export function PerfTitle({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <div className="flex items-center">
      <h3 id={id} className="text-base font-medium leading-4 mr-[9px]" style={{ color: "var(--color-fg)" }}>{label}</h3>
      <InfoTip text={tip} iconClassName="h-4 w-4" className="translate-y-px" style={{ color: "var(--color-fg-dim)" }} />
    </div>
  );
}

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



export function TrendBars({ points, message, height = 220, perf = false }: {
  points: Point[] | null; message: string; height?: number; perf?: boolean;
}) {
  const [ref, W] = useChartWidth();
  const H = height;
  const f = plotFrame(W, H);
  const n = points?.length ?? 0;
  const max = niceMax(Math.max(1, ...(points ?? []).map((p) => p.value)), 4);
  const slot = (f.R - f.L) / Math.max(1, n);
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
                <rect
                  key={i}
                  role="img"
                  aria-label={`${p.label}: ${fmtUsd(p.value)}`}
                  x={xAt(i) - bw / 2}
                  y={f.B - h}
                  width={bw}
                  height={h}
                  className="fill-accent"
                  opacity={p.partial ? 0.5 : undefined}
                  data-partial={p.partial ? "" : undefined}
                >
                  <title>{`${p.label}${p.partial ? ` (${p.partial})` : ""}\nEarnings ${fmtUsd(p.value)}\nGrowth ${g}`}</title>
                </rect>
              );
            })}
          </>
        )}
      </svg>
    </div>
  );
}

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
