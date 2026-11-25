"use client";


import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { fmtCents } from "@/lib/format";

export type Gran = "hour" | "day" | "week" | "month";

export function granAllowed(g: Gran, days: number): boolean {
  if (g === "hour") return days <= 2;
  if (days < 14) return g === "day";
  if (days <= 31) return g === "day" || g === "week";
  if (days <= 62) return g === "week";
  if (days <= 365) return g === "week" || g === "month";
  return g === "month";
}

export function granShown(g: Gran, days: number): Gran {
  if (granAllowed(g, days)) return g;
  return (["day", "week", "month"] as const).find((p) => granAllowed(p, days)) ?? "day";
}

export function rangeDays(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso) - Date.parse(fromIso) + 1) / 86_400_000);
}

export function niceMax(maxValue: number, gridLines: number): number {
  if (maxValue <= 0) return gridLines;
  const raw = maxValue / gridLines;
  const exp = Math.floor(Math.log10(raw));
  const base = Math.pow(10, exp);
  const m = raw / base;
  // 1, 2 or 5 alone left up to 2.5x headroom ($800,697 drew a $2M axis)
  const ladder = exp >= 0 ? [1, 2, 3, 4, 5, 6, 8, 10] : [1, 2, 5, 10];
  const step = (ladder.find((k) => m <= k) ?? 10) * base;
  return step * gridLines;
}

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

export function plotFrame(W: number, H: number) {
  return { L: 72, R: W - 8, T: 8, B: H - 30 };
}

export const fmtUsd = fmtCents;

export const fmtDollars = (cents: number) => fmtCents(cents);
export const axisDollars = fmtDollars;

export function xLabelPos(label: string, x: number, W: number): { x: number; textAnchor: "middle" | "end" } {
  return x + label.length * 4 > W ? { x: W, textAnchor: "end" } : { x, textAnchor: "middle" };
}

export function ChartAxes({ W, H, max, labels, xAt, labelGap = 4 + 8, fmt = axisDollars }: {
  W: number; H: number; max: number; labels: string[]; xAt: (i: number) => number;
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
          <text {...xLabelPos(l, xAt(i), W)} y={f.B + labelGap + 11}>{l}</text>
        </g>
      )))}
    </g>
  );
}

export function BlankChart({ W, H }: { W: number; H: number }) {
  const f = plotFrame(W, H);
  return <line x1={f.L} y1={f.B} x2={f.R} y2={f.B} strokeWidth={1} style={{ stroke: "var(--color-border)" }} />;
}

export function ChartMessage({ message, title }: { message: string; title?: string }) {
  if (!message) return null;
  return (
    <p title={title} className="absolute inset-0 flex items-center justify-center text-sm" style={{ color: "var(--color-fg-dim)" }}>
      {message}
    </p>
  );
}

export type ChartLine = { name: string; color: string; values: number[] };

export function linePaths(values: number[], at: (i: number) => string, partial?: readonly (string | undefined)[]) {
  if (!partial?.some(Boolean)) return { solid: values.map((_, i) => `${i === 0 ? "M" : "L"}${at(i)}`).join(" "), dashed: "" };
  const solid: string[] = [], dashed: string[] = [];
  if (values.length === 1) solid.push(`M${at(0)}`);
  for (let i = 1; i < values.length; i++) {
    const out = partial[i] || partial[i - 1] ? dashed : solid;
    out.push(`M${at(i - 1)} L${at(i)}`);
  }
  return { solid: solid.join(" "), dashed: dashed.join(" ") };
}

export function LineChart({
  labels, lines, message, messageTitle, height = 250, fmt, valueFmt = String, empty, legend = true, partial,
}: {
  labels: string[]; lines: ChartLine[] | null; message: string; messageTitle?: string; height?: number;
  partial?: readonly (string | undefined)[];
  fmt?: (value: number) => string;
  valueFmt?: (value: number) => string;
  empty?: ReactNode;
  legend?: boolean;
}) {
  const [ref, W] = useChartWidth();
  const H = height;
  const f = plotFrame(W, H);
  const n = labels.length;
  // $1 floor per grid step keeps default ticks distinct (an empty range read "$0" five times)
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
            {lines.map((l, k) => {
              const d = linePaths(l.values, (i) => `${xAt(i).toFixed(2)},${yAt(l.values[i]).toFixed(2)}`, partial);
              return (
                <Fragment key={k}>
                  <path role="img" aria-label={l.name} d={d.solid} fill="none" stroke={l.color} strokeWidth={2}
                    strokeLinejoin="round" strokeLinecap="round" />
                  {d.dashed && (
                    <path data-partial d={d.dashed} fill="none" stroke={l.color} strokeWidth={2} strokeDasharray="4 4"
                      aria-hidden />
                  )}
                </Fragment>
              );
            })}
            {labels.map((label, i) => (
              <rect key={i} data-testid="chart-hover" x={xAt(i) - slot / 2} y={f.T} width={Math.max(slot, 1)}
                height={f.B - f.T} fill="transparent">
                <title>{[partial?.[i] ? `${label} (${partial[i]})` : label,
                  ...lines.map((l) => `${l.name}: ${valueFmt(l.values[i] ?? 0)}`)].join("\n")}</title>
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
