"use client";

/**
 * MirrorFreshnessBanner — on /creators, founder only (a maintainer's task, not
 * an agency's): OF Manager's mirror is behind when OF's live build is newer than
 * the one it was captured from (OF_MIRROR_BUILD, written by scripts/of-mirror.mjs).
 * The live build is the one the relay already reads off OF's API responses
 * (live_rev.py) and /admin/rev/drift reports, the DriftBanner's read, so this
 * costs no extra OF call. Dismissible per live build, apart from DriftBanner.
 */

import { useSyncExternalStore } from "react";
import { TriangleAlert } from "lucide-react";

import { useDriftReport } from "@/components/setup/DriftBanner";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { OF_MIRROR_BUILD } from "@/lib/of-mirror-build";

const DISMISS_LS_KEY = "chatterly:mirror_behind_dismissed_for";
const DISMISS_EVENT = "chatterly:mirror-behind-dismissed";

const readDismissed = (): string | null => {
  try { return window.localStorage.getItem(DISMISS_LS_KEY); } catch { return null; }
};
const subscribeDismissed = (cb: () => void) => {
  window.addEventListener(DISMISS_EVENT, cb);
  return () => window.removeEventListener(DISMISS_EVENT, cb);
};

/** A build id's yyyymmddhhmm prefix ("202610091632-c45cc0ac3f"), or null for anything else. */
const buildTime = (rev: string | null | undefined) => rev?.match(/^(\d{12})-/)?.[1] ?? null;

export default function MirrorFreshnessBanner() {
  const dismissedFor = useSyncExternalStore(subscribeDismissed, readDismissed, () => null);

  const drift = useDriftReport(); // DriftBanner's read: one for both

  const rev = drift.data?.live_rev;
  const live = buildTime(rev);
  if (!rev || !live || live <= buildTime(OF_MIRROR_BUILD)! || dismissedFor === rev) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_LS_KEY, rev);
    } catch { /* ignore */ }
    window.dispatchEvent(new CustomEvent(DISMISS_EVENT));
  };

  // DriftBanner's look: HB's inline warning alert.
  return (
    <div role="alert" title={EXTRA_LABEL} className="rounded-lg bg-[rgba(255,161,95,.12)] px-4 py-3 text-[#ffa15f]">
      <div className="flex items-start gap-3">
        <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="flex-1 text-[14px] leading-normal">
          <div className="mb-1 font-medium">OF Manager mirror is behind OnlyFans</div>
          <p>
            The mirror is from OF build <code className="text-xs">{OF_MIRROR_BUILD}</code>; OnlyFans now
            runs <code className="text-xs">{rev}</code>. Re-run scripts/of-mirror.mjs on a fresh capture
            to pick up OF&apos;s UI changes.
          </p>
        </div>
        <button type="button" onClick={dismiss} className="shrink-0 text-[14px] text-[#ffa15f] hover:opacity-80">
          Dismiss
        </button>
      </div>
    </div>
  );
}
