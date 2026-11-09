"use client";

import { useState } from "react";
import type { EmployeeSalesPoint } from "@/hooks/useStats";
import { useChartWidth } from "@/components/stats/chart";


const dateLabel = (date: string) => new Date(`${date}T12:00:00Z`).toLocaleDateString("en-US", {
  month: "short", day: "numeric", timeZone: "UTC",
});

const money = (cents: number) => (cents / 100).toLocaleString("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2,
});

/** Daily attributed sales, with zero days retained and keyboard-accessible point details. */
export function EmployeeSalesChart({ points }: { points: EmployeeSalesPoint[] }) {
  const [ref, width] = useChartWidth();
  const [active, setActive] = useState<number | null>(null);
  const left = 55, right = Math.max(left + 1, width - 8), top = 24, bottom = 315;
  const peak = Math.max(100, ...points.map((p) => p.revenue_cents));
  // A little headroom, rounded in dollars, with five equal intervals as in the reference.
  const unit = 10 ** Math.floor(Math.log10(peak / 100));
  const max = Math.ceil(peak / 100 * 1.1 / unit * 2) / 2 * unit * 100;
  const slot = (right - left) / Math.max(1, points.length);
  const x = (i: number) => left + slot * (i + 0.5);
  const y = (value: number) => bottom - value / max * (bottom - top);
  // Monotone cubic interpolation: round the curve without inventing peaks or dipping below zero.
  const slopes = points.slice(1).map((p, i) => (y(p.revenue_cents) - y(points[i].revenue_cents)) / slot);
  const tangents = points.map((_, i) => {
    if (i === 0) return slopes[0] ?? 0;
    if (i === points.length - 1) return slopes[i - 1] ?? 0;
    const before = slopes[i - 1], after = slopes[i];
    return before * after <= 0 ? 0 : 2 * before * after / (before + after);
  });
  const path = points.map((p, i) => {
    if (!i) return `M ${x(i)} ${y(p.revenue_cents)}`;
    return `C ${x(i - 1) + slot / 3} ${y(points[i - 1].revenue_cents) + tangents[i - 1] * slot / 3} ${x(i) - slot / 3} ${y(p.revenue_cents) - tangents[i] * slot / 3} ${x(i)} ${y(p.revenue_cents)}`;
  }).join(" ");
  const stride = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor((right - left) / 65))));
  const detail = (i: number) => {
    const point = points[i], previous = points[i - 1]?.revenue_cents;
    const growth = previous ? `${((point.revenue_cents - previous) / previous * 100).toFixed(2)}%` : "—";
    return `${dateLabel(point.start)}\nEarnings: ${money(point.revenue_cents)}\nGrowth: ${growth}\nFrom Messages: ${money(point.messages_cents)}\nFrom Tips: ${money(point.tips_cents)}`;
  };
  return (
    <div ref={ref} data-chart className="relative h-[350px]" onMouseLeave={() => setActive(null)}>
      <svg width="100%" height="350" viewBox={`0 0 ${width} 350`} aria-label="Daily employee sales">
        {Array.from({ length: 6 }, (_, i) => {
          const value = max * i / 5;
          return <g key={i} className="text-[12px] fill-muted">
            <text x={left - 10} y={y(value) + 4} textAnchor="end">{(value / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}</text>
            <line x1={left} x2={right} y1={y(value)} y2={y(value)} className="stroke-border-light" strokeDasharray="2 3" />
          </g>;
        })}
        <path d={`${path} L ${x(points.length - 1)} ${bottom} L ${x(0)} ${bottom} Z`} className="fill-[#aeb6c5]/[0.06] [html[data-theme=light]_&]:fill-[#3467ff]/[0.06]" />
        <path role="img" aria-label="Earnings" d={path} fill="none" stroke="#3467ff" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
        {active !== null && <line x1={x(active)} x2={x(active)} y1={y(points[active].revenue_cents)} y2={bottom} stroke="#3467ff" />}
        {points.map((point, i) => <g key={point.start}>
          <circle cx={x(i)} cy={y(point.revenue_cents)} r={active === i ? 5 : 4} fill="white" stroke="#3467ff" strokeWidth="2" />
          {i % stride === 0 && <text x={x(i)} y="341" textAnchor="middle" className="fill-muted text-[12px]">{dateLabel(point.start)}</text>}
          <rect data-testid="sales-point" x={x(i) - slot / 2} y={top - 8}
            width={slot} height={bottom - top + 16} fill="transparent"
            tabIndex={0} role="img" aria-label={detail(i)} onMouseEnter={() => setActive(i)}
            onFocus={() => setActive(i)} onBlur={() => setActive(null)}>
            <title>{detail(i)}</title>
          </rect>
        </g>)}
      </svg>
      {active !== null && <div role="tooltip" className="pointer-events-none absolute z-10 whitespace-pre-line rounded border border-border-light bg-[#303033]/95 p-3 text-[12px] leading-5 text-white shadow-lg"
        style={{ top: Math.max(12, Math.min(y(points[active].revenue_cents) - 16, bottom - 110)), left: Math.max(0, Math.min(x(active) + 12, width - 285)), maxWidth: "100%" }}>{detail(active)}</div>}
    </div>
  );
}
