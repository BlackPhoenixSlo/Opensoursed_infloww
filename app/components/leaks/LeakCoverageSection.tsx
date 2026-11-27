"use client";

import { cn } from "@/lib/utils";

import { FRESHNESS, laneRows, type LaneState, type LeakLane } from "./leakCoverage";

const TONE: Record<LaneState, string> = {
  ok: "bg-ok/10 text-ok",
  waiting: "bg-warn/10 text-warn",
  reduced: "bg-warn/10 text-warn",
  failed: "bg-err/10 text-err",
  never: "border border-border text-muted",
  paused: "border border-border text-muted",
};

export function LeakCoverageSection({ lanes }: { lanes: LeakLane[] }) {
  const rows = laneRows(lanes, new Date());
  return (
    <section aria-label="Coverage" className="mt-4">
      <h3 className="text-[14px] font-medium text-fg">Coverage</h3>
      <ul aria-label="Lanes" className="divide-y divide-border">
        {rows.map((r) => (
          <li key={r.lane} data-lane={r.lane} className="flex min-w-0 flex-col gap-1 py-2 text-[14px]">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-fg">{r.label}</span>
              <span data-lane-state={r.tone} className={cn("rounded-full px-2 py-0.5 text-[12px] font-medium", TONE[r.tone])}>
                {r.chip}
              </span>
              {r.lastOk && <span className="text-[13px] text-muted">{r.lastOk}</span>}
              {r.next && <span className="text-[13px] text-muted">{r.next}</span>}
            </div>
            {r.note && <span className="text-[13px] text-muted">{r.note}</span>}
            {r.skipped.length > 0 && <span className="break-words text-[13px] text-muted">Skipped: {r.skipped.join(", ")}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[13px] text-muted">{FRESHNESS}</p>
    </section>
  );
}
