"use client";


import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";

import { relay, type LiveRev } from "@/lib/relay";
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

const buildTime = (rev: string | null | undefined) => rev?.match(/^(\d{12})-/)?.[1] ?? null;

export default function MirrorFreshnessBanner() {
  const dismissedFor = useSyncExternalStore(subscribeDismissed, readDismissed, () => null);

  const liveRev = useQuery<LiveRev>({
    queryKey: ["live-rev"],
    queryFn: () => relay.get<LiveRev>("/admin/rev/live"),
    // eslint-disable-next-line local/no-fixed-polling -- detects a deploy; relay restart kills SSE anyway
    refetchInterval: 15 * 60_000,
    staleTime: 60_000,
  });

  const rev = liveRev.data?.live_rev;
  const live = buildTime(rev);
  if (!rev || !live || live <= buildTime(OF_MIRROR_BUILD)! || dismissedFor === rev) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_LS_KEY, rev);
    } catch { }
    window.dispatchEvent(new CustomEvent(DISMISS_EVENT));
  };

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
