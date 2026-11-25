"use client";

import { useState } from "react";

import type { RangePreset } from "@/components/stats/DateRangePicker";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { presetRange, priorRange, toLocalIso } from "@/lib/dateRange";

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
    priorFromIso: toLocalIso(prior?.[0] ?? null, false, reportTz),
    priorToIso: toLocalIso(prior?.[1] ?? null, true, reportTz),
    reportTz,
    ready: !applied.isPending,
    handleRange,
  };
}
