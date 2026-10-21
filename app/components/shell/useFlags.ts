"use client";

import { useAppliedSettings, type FeatureFlags } from "@/lib/appliedSettings";

const NO_FLAGS: FeatureFlags = { fansly_manager: false };

/** The Agency's feature flags for the Creator in scope (roadmap 8.11):
 *  undefined until the Applied settings read first answers, every flag off on
 *  error, so a dark page never shows by accident and its gate can wait for
 *  the answer. lib/nav's `flag` filter reads it. */
export function useFlags(): FeatureFlags | undefined {
  const q = useAppliedSettings();
  if (q.isPending) return undefined;
  return q.data?.flags ?? NO_FLAGS;
}
