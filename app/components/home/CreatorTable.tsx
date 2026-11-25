"use client";


import { useRef } from "react";

import { EmptyState } from "@/components/ui/infloww";
import type { PerModelRow } from "@/hooks/useStats";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { NotWired } from "./ReportsCharts";
import { UtcChip } from "./ReportsControls";
import { type ColCtx, type StatCol, type View, cellText, creatorName, readOf } from "./reportsMath";

export function CreatorTable({ creators, cols, ctx, view }: {
  creators: PerModelRow[]; cols: readonly StatCol[]; ctx: ColCtx; view: View;
}) {
  const cell = "px-[18px] h-12 whitespace-nowrap text-start";
  const line = { borderBottom: "1px solid var(--color-border)" };
  const headRef = useRef<HTMLDivElement | null>(null);
  const tableStyle: React.CSSProperties = {
    color: "var(--color-fg)", width: "100%", tableLayout: "fixed",
    minWidth: `calc(var(--creator-col) + ${cols.reduce((a, c) => a + c.width, 0)}px)`,
  };
  const colgroup = (
    <colgroup>
      <col style={{ width: "var(--creator-col)" }} />
      {cols.map((c) => <col key={c.key} style={{ width: c.width }} />)}
    </colgroup>
  );
  return (
    <>
      <div role="table" aria-label="Creator statistics" className="rounded-xl [--creator-col:180px] max-sm:[--creator-col:120px]" style={{ background: "var(--color-bg-elev-1)" }}>
        <div
          ref={headRef}
          role="rowgroup"
          className="overflow-hidden rounded-t-xl z-[2]"
          style={{ position: "sticky", top: "var(--shell-top, 3.5rem)", background: "var(--color-bg-elev-1)" }}
        >
        <table role="presentation" className="text-sm leading-[1.1429] border-collapse" style={tableStyle}>
          {colgroup}
          <thead role="presentation">
            <tr role="row" style={line}>
              <th role="columnheader" scope="col" className={cn(cell, "sticky left-0 z-[1] font-medium")} style={{ background: "var(--color-bg-elev-1)" }}>
                Creator
              </th>
              {cols.map((c) => (
                <th
                  key={c.key}
                  role="columnheader"
                  scope="col"
                  title={c.extra ? EXTRA_LABEL : undefined}
                  className={cn(cell, "font-medium")}
                >
                  {c.v ? c.title : (
                    <button type="button" disabled title="not wired" className="font-medium cursor-not-allowed opacity-60">
                      {c.title}
                    </button>
                  )}
                  {c.utc && <UtcChip />}
                </th>
              ))}
            </tr>
          </thead>
        </table>
        </div>
        <div
          role="rowgroup"
          className="overflow-x-auto"
          onScroll={(e) => { if (headRef.current) headRef.current.scrollLeft = e.currentTarget.scrollLeft; }}
        >
        <table role="presentation" className="text-sm leading-[1.1429] border-collapse" style={tableStyle}>
          {colgroup}
          <tbody role="presentation">
            {view !== "ready" ? (
              <tr role="row">
                <td role="cell" colSpan={cols.length + 1}>
                  {view === "empty" ? (
                    <EmptyState className="py-24" textClassName="text-base text-fg-dim" />
                  ) : (
                    <div
                      title={EXTRA_LABEL}
                      className="flex flex-col items-center justify-center py-24 text-base"
                      style={{ color: "var(--color-fg-dim)" }}
                    >
                      {view === "loading" ? "Loading…" : "Creator statistics unavailable"}
                    </div>
                  )}
                </td>
              </tr>
            ) : creators.map((m) => (
              <tr key={m.account_id} role="row" style={line}>
                <td role="cell" className={cn(cell, "sticky left-0 z-[1]")} style={{ background: "var(--color-bg-elev-1)" }}>
                  {creatorName(m)}
                </td>
                {cols.map((c) => (
                  <td key={c.key} role="cell" className={cell}>
                    {c.v && !readOf(c, ctx)
                      ? <NotWired label={`${creatorName(m)} ${c.title}`} />
                      : cellText(c, m, ctx)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
      {view === "ready" && creators.length > 20 && (
        <p className="py-8 text-center text-base" style={{ color: "color-mix(in srgb, var(--color-fg) 38%, transparent)" }}>
          You have reached the end of the page
        </p>
      )}
    </>
  );
}
