"use client";

import { useState } from "react";

import type { RangePreset } from "@/components/stats/DateRangePicker";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { presetRange, priorRange, toLocalIso } from "@/lib/dateRange";

/**
 * The reports' shared date range (StatsReport, SalesRecords): a preset (30d to start) or a stored custom range.
 * A preset's days are derived each render, so they follow the Agency's report time zone once the Applied settings
 * load. `fromIso`/`toIso` are those days' midnights in the report time zone (the browser's when none is saved) sent
 * as instants (docs/spec/phase-04-apply-stored-settings.md, story 18); `ready` is false until the Applied settings
 * load, so no report fires first with the browser's days.
 *
 * `fallbackTz` is the zone used when no report time zone is saved (the browser's when null): a report whose read
 * cuts its own days in UTC when none is saved passes "UTC", so its window, its days and its UTC label agree with
 * the rows (Fan reports' growth, stats.py `fan_report`). `reportTz` is the zone in effect.
 */
export function useReportRange(fallbackTz: string | null = null) {
  const [custom, setCustom] = useState<{ from: string | null; to: string | null }>({ from: null, to: null });
  const [preset, setPreset] = useState<RangePreset>("30d");
  const applied = useAppliedSettings();
  const reportTz = applied.data?.preferences?.report_tz ?? fallbackTz;
  const [from, to] = preset === "custom" ? [custom.from, custom.to] : presetRange(preset, reportTz);

  const handleRange = (f: string | null, t: string | null, p: RangePreset) => {
    if (p === "custom") setCustom({ from: f, to: t });
    setPreset(p);
  };

  const prior = priorRange(from, to);

  return {
    preset,
    from,
    to,
    fromIso: toLocalIso(from, false, reportTz),
    toIso: toLocalIso(to, true, reportTz),
    /** The window of equal length just before (`priorRange`), for the change against the previous period. */
    priorFromIso: toLocalIso(prior?.[0] ?? null, false, reportTz),
    priorToIso: toLocalIso(prior?.[1] ?? null, true, reportTz),
    reportTz,
    ready: !applied.isPending,
    handleRange,
  };
}
