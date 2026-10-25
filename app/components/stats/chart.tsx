"use client";

/**
 * chart — the reports' shared SVG chart parts and granularity rule (Employee reports' charts, Creator reports').
 *
 *   granAllowed   Infloww's `getDisableStatus` over a range's calendar days; the relay's `stats._bucket_allowed`.
 *   granShown     the granularity picked, or the first allowed one when the range rules it out.
 *   niceMax, useChartWidth, plotFrame, ChartAxes, ChartMessage, BlankChart, fmtUsd   the axis, sizing, wording
 *                 and money parts.
 *   LineChart     2px lines, one per series, with a hover column per x that names every line's value there.
 */

import { type ReactNode, useEffect, useRef, useState } from "react";
import { fmtCents } from "@/lib/format";

/** A "Shown by" granularity. */
export type Gran = "hour" | "day" | "week" | "month";

/** #29 (`getDisableStatus`) over the range's calendar days: up to 2 Hour or Day, under 14 Day, 14 to 31 Day or Week,
 *  32 to 62 Week, 63 to 365 Week or Month, over 365 Month. A report with no hourly read rules Hour out itself. */
export function granAllowed(g: Gran, days: number): boolean {
  if (g === "hour") return days <= 2;
  if (days < 14) return g === "day";
  if (days <= 31) return g === "day" || g === "week";
  if (days <= 62) return g === "week";
  if (days <= 365) return g === "week" || g === "month";
  return g === "month";
}

/** The bucket shown: the one picked, or (`autoChangeLegendBy`) the first allowed one when the range rules it out. */
export function granShown(g: Gran, days: number): Gran {
  if (granAllowed(g, days)) return g;
  return (["day", "week", "month"] as const).find((p) => granAllowed(p, days)) ?? "day";
}

/** The calendar days of a report range sent as instants, from a midnight to the end of a day in any zone
 *  (useReportRange): its length in whole days, a millisecond added for the last day's end and a daylight-saving hour
 *  either way rounded off; the relay's `stats._range_days`. */
export function rangeDays(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso) - Date.parse(fromIso) + 1) / 86_400_000);
}

/** A rounded-up axis maximum of `gridLines` even steps (1, 2 or 5 × 10ⁿ). */
export function niceMax(maxValue: number, gridLines: number): number {
  if (maxValue <= 0) return gridLines;
  const raw = maxValue / gridLines;
  const exp = Math.floor(Math.log10(raw));
  const base = Math.pow(10, exp);
  const m = raw / base;
  const stepMult = m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10;
  const step = stepMult * base;
  return step * gridLines;
}

/** The width a chart is drawn at, so its pixel values (#80, #83) stay pixels; a fallback until it is measured. */
export function useChartWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width || 900] as const;
}

/** The plot box: room for the 14px y labels on the left (up to "$800,000", 8px off the plot; 56 clipped the "$" of
 *  "$80,000") and the x ticks and labels below. */
export function plotFrame(W: number, H: number) {
  return { L: 72, R: W - 8, T: 8, B: H - 30 };
}

/** Cents as the house `fmtCents` prints money, whole dollars with commas as on the dashboard ("$1,235", "$8"), a
 *  loss as "-$12": a report figure's, a point's and a tooltip's money. */
export function fmtUsd(cents: number): string {
  return fmtCents(cents);
}

/** Cents as whole dollars, "$930" / "$1,235": a report's earnings total (as the dashboard's earnings overview prints
 *  them) and the axes' default. */
export const fmtDollars = (cents: number) => fmtCents(cents); // a loss "-$12", never "$-12" or "$-0"
export const axisDollars = fmtDollars;

/** #79, #80: horizontal 1px grid lines and 14px tick text, x tick lines 4px long with the labels 8px under them, no
 *  axis lines (our border and dim tokens, ADR-0001 colours). `fmt` writes a y tick (whole dollars of cents by
 *  default). */
export function ChartAxes({ W, H, max, labels, xAt, labelGap = 4 + 8, fmt = axisDollars }: {
  W: number; H: number; max: number; labels: string[]; xAt: (i: number) => number;
  /** The x labels' distance off the axis, the tick and 8px by default. */
  labelGap?: number;
  fmt?: (value: number) => string;
}) {
  const f = plotFrame(W, H);
  const ticks = 4;
  const stride = Math.max(1, Math.ceil(labels.length / Math.max(1, Math.floor((f.R - f.L) / 64))));
  return (
    <g fontSize={14} style={{ fill: "var(--color-fg-dim)" }}>
      {Array.from({ length: ticks + 1 }).map((_, i) => {
        const g = (max / ticks) * i;
        const y = f.B - (g / max) * (f.B - f.T);
        return (
          <g key={i}>
            <line x1={f.L} y1={y} x2={f.R} y2={y} strokeWidth={1} style={{ stroke: "var(--color-border)" }} />
            <text x={f.L - 8} y={y + 5} textAnchor="end">{fmt(g)}</text>
          </g>
        );
      })}
      {labels.map((l, i) => (i % stride !== 0 ? null : (
        <g key={i}>
          <line x1={xAt(i)} y1={f.B} x2={xAt(i)} y2={f.B + 4} strokeWidth={1} style={{ stroke: "var(--color-border)" }} />
          <text x={xAt(i)} y={f.B + labelGap + 11} textAnchor="middle">{l}</text>
        </g>
      )))}
    </g>
  );
}

/** A chart with nothing to draw: the zero line. */
export function BlankChart({ W, H }: { W: number; H: number }) {
  const f = plotFrame(W, H);
  return <line x1={f.L} y1={f.B} x2={f.R} y2={f.B} strokeWidth={1} style={{ stroke: "var(--color-border)" }} />;
}

/** A loading or failed chart's wording, centred over it; `title` labels it (Creator reports mark theirs ours). */
export function ChartMessage({ message, title }: { message: string; title?: string }) {
  if (!message) return null;
  return (
    <p title={title} className="absolute inset-0 flex items-center justify-center text-sm" style={{ color: "var(--color-fg-dim)" }}>
      {message}
    </p>
  );
}

export type ChartLine = { name: string; color: string; values: number[] };

/** 2px lines, one per series over `labels`, a legend under them unless `legend` is off. Each x has a full-height
 *  hover column whose tooltip names every line's value there (`valueFmt`), however many points. `null` lines draw the
 *  blank chart with `message` (titled `messageTitle`). */
export function LineChart({
  labels, lines, message, messageTitle, height = 250, fmt, valueFmt = String, empty, legend = true,
}: {
  labels: string[]; lines: ChartLine[] | null; message: string; messageTitle?: string; height?: number;
  /** The y ticks (ChartAxes' `fmt`). */
  fmt?: (value: number) => string;
  valueFmt?: (value: number) => string;
  /** Laid over the axes when there are no lines to draw (an empty comparison); absolutely placed by the caller. */
  empty?: ReactNode;
  legend?: boolean;
}) {
  const [ref, W] = useChartWidth();
  const H = height;
  const f = plotFrame(W, H);
  const n = labels.length;
  // The default ticks are whole dollars of cents: a floor of $1 a grid step keeps them distinct (an empty range read
  // "$0" five times on a 1-cent axis).
  const max = niceMax(Math.max(fmt ? 1 : 4 * 100, ...(lines ?? []).flatMap((l) => l.values)), 4);
  const xAt = (i: number) => (n <= 1 ? (f.L + f.R) / 2 : f.L + (i / (n - 1)) * (f.R - f.L));
  const yAt = (v: number) => f.B - (v / max) * (f.B - f.T);
  const slot = (f.R - f.L) / Math.max(1, n - 1);
  return (
    <div ref={ref} className="relative">
      {lines && lines.length === 0 && empty}
      <ChartMessage message={lines ? "" : message} title={messageTitle} />
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block">
        {!lines ? <BlankChart W={W} H={H} /> : (
          <>
            <ChartAxes W={W} H={H} max={max} labels={labels} xAt={xAt} fmt={fmt} />
            {lines.map((l, k) => (
              <path
                key={k}
                role="img"
                aria-label={l.name}
                d={l.values.map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(2)},${yAt(v).toFixed(2)}`).join(" ")}
                fill="none"
                stroke={l.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {labels.map((label, i) => (
              <rect key={i} data-testid="chart-hover" x={xAt(i) - slot / 2} y={f.T} width={Math.max(slot, 1)}
                height={f.B - f.T} fill="transparent">
                <title>{[label, ...lines.map((l) => `${l.name}: ${valueFmt(l.values[i] ?? 0)}`)].join("\n")}</title>
              </rect>
            ))}
          </>
        )}
      </svg>
      {legend && lines && lines.length > 0 && (
        <ul className="flex flex-wrap justify-center gap-4 mt-1 text-xs" style={{ color: "var(--color-fg-dim)" }}>
          {lines.map((l, k) => (
            <li key={k} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: l.color }} />{l.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
