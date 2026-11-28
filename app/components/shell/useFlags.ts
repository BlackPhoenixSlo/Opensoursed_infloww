"use client";

import { useAppliedSettings, type FeatureFlags } from "@/lib/appliedSettings";

const NO_FLAGS: FeatureFlags = { fansly_manager: true, leak_tracker: false };

export function useFlags(): FeatureFlags | undefined {
  const q = useAppliedSettings();
  if (q.isPending) return undefined;
  const flags = q.data?.flags ?? NO_FLAGS;
  // Public builds ship without app/public/fansly-mirror (never public), so their Fansly Manager would be iframe 404s.
  if (flags.fansly_manager && process.env.NEXT_PUBLIC_FANSLY_MIRROR_ABSENT === "1") return { ...flags, fansly_manager: false };
  return flags;
}
