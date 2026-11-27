"use client";

import { useAppliedSettings, type FeatureFlags } from "@/lib/appliedSettings";

const NO_FLAGS: FeatureFlags = { fansly_manager: false, leak_tracker: false };

// undefined until the first read answers; every flag off when no data arrived, so a dark page never shows by accident.
export function useFlags(): FeatureFlags | undefined {
  const q = useAppliedSettings();
  if (q.isPending) return undefined;
  return q.data?.flags ?? NO_FLAGS;
}
