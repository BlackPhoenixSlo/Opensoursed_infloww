"use client";

import { useEffect, useState } from "react";

export function copyAge(copiedAt: string, now: number): string | null {
  const at = Date.parse(copiedAt);
  if (Number.isNaN(at)) return null;
  const min = Math.max(0, Math.floor((now - at) / 60_000));
  if (min < 1) return "under a minute old";
  if (min < 120) return `${min} min old`;
  const h = Math.floor(min / 60);
  return h < 48 ? `${h} h old` : `${Math.floor(h / 24)} days old`;
}

export function ShadowBanner({ copiedAt }: { copiedAt: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  const age = copyAge(copiedAt, now);
  const at = new Date(copiedAt);
  const clock = Number.isNaN(at.getTime()) ? null : at.toISOString().slice(11, 16);
  return (
    <div role="status" data-shadow-banner className="sticky top-0 z-50 bg-info text-white text-xs sm:text-sm">
      <div className="max-w-shell mx-auto px-3 lg:px-6 py-2 flex items-center gap-2 flex-wrap">
        <span className="font-semibold">Shadow, read-only</span>
        <span suppressHydrationWarning data-shadow-age>
          {age ? `· copy from ${clock} UTC, ${age}` : "· copy age unknown"}
        </span>
        <span className="hidden sm:inline opacity-80">· nothing here reaches OnlyFans; every send and edit is refused</span>
      </div>
    </div>
  );
}
