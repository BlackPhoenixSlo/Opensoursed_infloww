"use client";

/**
 * Creator reports › Creator performance's lower blocks, outside CompetitorReports.tsx so its diff stays small
 * (docs/infloww-layouts/analytics-creator-reports.md):
 *   • Chargebacks (#170, #171): a smooth 5px #3467FF line of the reversed money over a #EFF4FF area, 350px high,
 *     from the revenue read's `status=reversed` days.
 *   • Earnings heatmap (#168, #169): the window's sales by weekday and hour in the report zone, the revenue read's
 *     `group_by=hour_of_week`, 500px high, #EFF4FF to #3467FF, hours "12 AM" to "11 PM", each cell's tooltip
 *     "Total sales". The bundle charts each date by hour; we fold the window into one week, rows from the Agency's
 *     week start.
 */

import { useId } from "react";

import { BlankChart, ChartAxes, ChartMessage, fmtUsd, niceMax, plotFrame, useChartWidth } from "@/components/stats/chart";
import { useWeekStart } from "@/lib/appliedSettings";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

/** A bucket's label and its money in cents. */
export interface ChartPoint { label: string; value: number }

const BLUE = "#3467FF";
const PALE = "#EFF4FF";

/** A smooth path through the points (Catmull-Rom as cubic Béziers), the bundle's `smooth:true`. */
function smoothPath(pts: [number, number][]): string {
  if (!pts.length) return "";
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [p0, p1, p2, p3] = [pts[i - 1] ?? pts[i], pts[i], pts[i + 1], pts[i + 2] ?? pts[i + 1]];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

/** A slot of the week: ISO weekday (1 = Monday), hour 0-23, its money in cents. */
export interface HeatCell { weekday: number; hour: number; value: number }

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** The bundle's `hours`: "12 AM", "1 AM" … "11 PM". */
const HOURS = Array.from({ length: 24 }, (_, h) => `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`);

/** #169: the share `t` (0-1) of the way from #EFF4FF to #3467FF. */
function heatColor(t: number): string {
  const [a, b] = [[0xef, 0xf4, 0xff], [0x34, 0x67, 0xff]];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}

/** #168, #169: Earnings heatmap. `null` cells draw the empty grid with `message`. */
export function EarningsHeatmap({ cells, message }: { cells: HeatCell[] | null; message: string }) {
  const [ref, W] = useChartWidth();
  const weekStart = useWeekStart();
  const scaleId = `heat-${useId().replace(/[^\w-]/g, "")}`;
  const H = 500;
  const [L, R, T, B] = [48, W - 8, 8, H - 64];
  const days = weekStart === "sunday" ? [7, 1, 2, 3, 4, 5, 6] : [1, 2, 3, 4, 5, 6, 7];
  const at = new Map((cells ?? []).map((c) => [`${c.weekday} ${c.hour}`, c.value]));
  const max = Math.max(0, ...at.values());
  const [cw, ch] = [(R - L) / 24, (B - T) / 7];
  const stride = Math.max(1, Math.ceil(24 / Math.max(1, Math.floor((R - L) / 44))));
  return (
    <div ref={ref} className="relative">
      <ChartMessage message={cells ? "" : message} title={EXTRA_LABEL} />
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block" role="img" aria-label="Earnings heatmap chart">
        <g fontSize={12} style={{ fill: "var(--color-fg-dim)" }}>
          {days.map((d, row) => (
            <text key={d} x={L - 8} y={T + row * ch + ch / 2 + 4} textAnchor="end">{DAY_NAMES[d - 1]}</text>
          ))}
          {HOURS.map((h, i) => (i % stride ? null : (
            <text key={h} x={L + i * cw + cw / 2} y={B + 18} textAnchor="middle">{h}</text>
          )))}
        </g>
        {days.map((d, row) => HOURS.map((h, i) => {
          const v = at.get(`${d} ${i}`) ?? 0;
          const name = `${DAY_NAMES[d - 1]} ${h}`;
          const box = { x: L + i * cw + 1, y: T + row * ch + 1, width: Math.max(0, cw - 2), height: Math.max(0, ch - 2) };
          // With no read yet (or no Creator) the bare grid, no figures.
          if (!cells) return <rect key={name} {...box} fill={PALE} />;
          return (
            <rect key={name} {...box} fill={heatColor(max ? v / max : 0)} role="img" aria-label={`${name}: ${fmtUsd(v)}`}>
              <title>{`${name}\nTotal sales ${fmtUsd(v)}`}</title>
            </rect>
          );
        }))}
        {/* The visual map: the scale's two ends under the grid. */}
        {cells && (
          <>
            <defs>
              <linearGradient id={scaleId}>
                <stop offset="0" stopColor={PALE} />
                <stop offset="1" stopColor={BLUE} />
              </linearGradient>
            </defs>
            <g fontSize={12} style={{ fill: "var(--color-fg-dim)" }}>
              <text x={(L + R) / 2 - 108} y={H - 12} textAnchor="end">{fmtUsd(0)}</text>
              <rect x={(L + R) / 2 - 100} y={H - 24} width={200} height={14} rx={2} fill={`url(#${scaleId})`} />
              <text x={(L + R) / 2 + 108} y={H - 12}>{fmtUsd(max)}</text>
            </g>
          </>
        )}
      </svg>
    </div>
  );
}

/** #170, #171: Chargebacks, on the reports' axes. `null` points draw the blank chart with `message`. */
export function ChargebacksChart({ points, message }: { points: ChartPoint[] | null; message: string }) {
  const [ref, W] = useChartWidth();
  const H = 350;
  const f = plotFrame(W, H);
  const n = points?.length ?? 0;
  const max = niceMax(Math.max(1, ...(points ?? []).map((p) => p.value)), 4);
  const xAt = (i: number) => (n <= 1 ? (f.L + f.R) / 2 : f.L + (i / (n - 1)) * (f.R - f.L));
  const yAt = (v: number) => f.B - (v / max) * (f.B - f.T);
  const xy: [number, number][] = (points ?? []).map((p, i) => [xAt(i), yAt(p.value)]);
  const line = smoothPath(xy);
  return (
    <div ref={ref} className="relative">
      <ChartMessage message={points ? "" : message} title={EXTRA_LABEL} />
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block" role="img" aria-label="Chargebacks chart">
        {!points ? <BlankChart W={W} H={H} /> : (
          <>
            <ChartAxes W={W} H={H} max={max} labels={points.map((p) => p.label)} xAt={xAt} />
            {n > 0 && <path d={`${line} L${xy[n - 1][0].toFixed(2)},${f.B} L${xy[0][0].toFixed(2)},${f.B} Z`} fill={PALE} />}
            {n > 0 && <path d={line} fill="none" stroke={BLUE} strokeWidth={5} strokeLinejoin="round" strokeLinecap="round" />}
            {points.map((p, i) => (
              <circle key={i} cx={xAt(i)} cy={yAt(p.value)} r={6} fill="transparent" role="img" aria-label={`${p.label}: ${fmtUsd(p.value)}`}>
                <title>{`${p.label}\nChargebacks ${fmtUsd(p.value)}`}</title>
              </circle>
            ))}
          </>
        )}
      </svg>
    </div>
  );
}
