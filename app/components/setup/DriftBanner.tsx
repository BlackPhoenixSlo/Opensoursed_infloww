"use client";

/**
 * DriftBanner — shown on /creators, below the creator table's footer, when at
 * least one account's stored x-of-rev no longer matches the live OF build
 * hash. Infloww has no such banner, so it is titled as an Inflowwww extra.
 *
 * Mirrors the existing /ui/ drift banner but as a React component:
 *   • Polls /admin/rev/drift every 5 minutes (per the plan).
 *   • Dismissible per-rev — dismissing on rev A doesn't suppress the
 *     warning when rev B ships and a new drift appears.
 *   • Lists which accounts are stale with their nicknames so you know
 *     exactly which model needs re-capture.
 */

import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";

import { ssePoll } from "@/lib/events";
import { relay, type DriftReport } from "@/lib/relay";
import { TriangleAlert } from "lucide-react";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

const DISMISS_LS_KEY = "chatterly:drift_dismissed_for";

/** The /admin/rev/drift read, shared with MirrorFreshnessBanner. */
export function useDriftReport() {
  return useQuery<DriftReport>({
    queryKey: ["drift"],
    queryFn: () => relay.get<DriftReport>("/admin/rev/drift"),
    refetchInterval: ssePoll(15 * 60_000, 5 * 60_000), // SSE: session_dead invalidates
    staleTime: 60_000,
  });
}

export default function DriftBanner() {
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);

  // Hydrate dismissal state from localStorage. Effect so SSR is happy.
  useEffect(() => {
    try {
      setDismissedFor(window.localStorage.getItem(DISMISS_LS_KEY));
    } catch { /* ignore */ }
  }, []);

  const drift = useDriftReport();

  if (!drift.data?.any_drift) return null;
  if (drift.data.live_rev && dismissedFor === drift.data.live_rev) return null;

  const stale = drift.data.accounts.filter((a) => a.drift);
  const labels = stale.map((a) => a.nickname || a.account_id).join(", ");

  const dismiss = () => {
    if (drift.data?.live_rev) {
      try {
        window.localStorage.setItem(DISMISS_LS_KEY, drift.data.live_rev);
      } catch { /* ignore */ }
      setDismissedFor(drift.data.live_rev);
    }
  };

  // HB's inline warning alert (page-parity 02): #ffa15f on its 12% tint, 8px corners, no border.
  return (
    <div role="alert" title={EXTRA_LABEL} className="rounded-lg bg-[rgba(255,161,95,.12)] px-4 py-3 text-[#ffa15f]">
      <div className="flex items-start gap-3">
        <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="flex-1 text-[14px] leading-normal">
          <div className="mb-1 font-medium">Session stale — re-capture required</div>
          <p>
            OnlyFans shipped a new frontend (rev <code className="text-xs">{drift.data.live_rev}</code>).
            Stale: <strong>{labels}</strong>. Sign in again via the Login Capture
            extension and paste the fresh cURL below.
          </p>
        </div>
        <button type="button" onClick={dismiss} className="shrink-0 text-[14px] text-[#ffa15f] hover:opacity-80">
          Dismiss
        </button>
      </div>
    </div>
  );
}
