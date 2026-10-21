"use client";

/**
 * PlatformSwitcher — Infloww's platform selector at the top of the sidebar
 * (`SelectPlatform`, index.9f50f370.js @11125100).
 *
 * The trigger is the platform's logo and name with a chevron, and a red dot
 * when any platform has unread messages; the 60px rail draws the logo and the
 * dot only. It opens a list of the platforms, each with a check on the active
 * one, its logo, its name and a pink chip (`HBChip signal:"stop"`) counting
 * its unread, "99+" past 99. Infloww always lists OnlyFans and Fansly, then mym
 * and Fanvue behind feature flags (@11128150) an agency with them sees. We have
 * no mym or Fanvue yet, so they follow as disabled rows with a "Coming soon"
 * chip in place of the count: nothing to pick, no backend.
 *
 * Infloww's OnlyFans count is the unread messages summed over its creators
 * (`useOnlyfansNotification`, @11123200), Fansly's the Fansly store's unread
 * count. Ours sums the roster's unread (conversations with unread messages,
 * useRosterCounts) over each platform's accounts with a session.
 *
 * Picking a platform (`changePlatform`, @11121052) saves it; PlatformSync
 * then drops a scope on a creator of the other platform and leaves a page only
 * the other platform shows, as it does for a switch from another window.
 */

import { useMemo } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { useOutsideClose } from "@/components/ui/Menu";
import { useAccounts } from "@/hooks/useAccounts";
import { useRosterCounts } from "@/hooks/useRosterCounts";
import { PLATFORMS, PLATFORM_NAME, accountPlatform, setPlatform, usePlatform, type Platform } from "@/lib/platform";
import { cn } from "@/lib/utils";

/** Each platform's brand mark, 20px: Infloww's OnlyfansColor and
 *  FanslyColor (index.9f50f370.js), paths verbatim. */
export function PlatformLogo({ platform, className }: { platform: Platform; className?: string }) {
  return (
    <svg
      aria-hidden
      data-testid={`platform-logo-${platform}`}
      viewBox="0 0 24 24"
      fill="none"
      className={cn("w-5 h-5 shrink-0", className)}
    >
      {platform === "onlyfans" ? (
        <>
          <path
            d="M8 4c-4.416 0-8 3.584-8 8s3.584 8 8 8 8-3.584 8-8-3.584-8-8-8zm0 10.4A2.397 2.397 0 015.6 12c0-1.328 1.072-2.4 2.4-2.4 1.328 0 2.4 1.072 2.4 2.4 0 1.328-1.072 2.4-2.4 2.4z"
            fill="#00AEEF"
          />
          <path
            d="M16.992 10c2.033.585 4.432 0 4.432 0-.696 3.04-2.904 4.944-6.088 5.176A7.983 7.983 0 018 20l2.4-7.628C12.867 4.532 14.132 4 19.983 4H24c-.672 2.96-2.988 5.221-7.008 6z"
            fill="#008CCF"
          />
        </>
      ) : (
        <path
          d="M5.787 2c-1.388.06-2.798.506-3.84 1.468C.744 4.537.176 6.158 0 7.733v.501a5.644 5.644 0 001.571 3.619c2.81 2.896 5.647 5.762 8.483 8.63.533.532 1.026 1.124 1.677 1.517h.484c.717-.251 1.158-.918 1.698-1.415 2.087-2.164 4.266-4.238 6.303-6.45l-6.113-6.234c.69-.703 1.372-1.414 2.074-2.103.57-.574 1.366-.906 2.173-.839 1.64.022 2.998 1.727 2.697 3.364-.177 1.422-1.494 2.195-2.317 3.219l2.066 2c.688-.574 1.332-1.279 1.917-1.96 1.634-1.956 1.716-5.031.223-7.093-.978-1.448-2.631-2.347-4.342-2.489h-.848c-1.266.145-2.514.633-3.456 1.521-2.835 2.809-5.609 5.68-8.446 8.486-.658-.658-1.31-1.32-1.965-1.981-.693-.701-1.061-1.74-.858-2.727.278-1.465 1.763-2.566 3.225-2.32 1.41.153 2.166 1.527 3.182 2.353L11.47 5.36C10.2 3.713 8.486 2.123 6.318 2h-.531zm6.272 9.21c1.38.015 2.705 1.127 2.848 2.556.274 1.774-1.391 3.52-3.15 3.277-1.715-.062-2.968-1.97-2.54-3.617.248-1.086 1.168-1.966 2.25-2.152.196-.045.394-.066.592-.064zm-.031 1.02c-.492 0-.963.199-1.31.552a1.899 1.899 0 00-.543 1.332c0 .5.195.978.542 1.332.348.353.82.551 1.31.551.493 0 .964-.198 1.312-.551a1.899 1.899 0 00.361-2.144.783.783 0 01-.757.087.79.79 0 01-.428-.435.815.815 0 01-.06-.308.814.814 0 01.08-.344 1.827 1.827 0 00-.507-.072z"
          fill="#2699F7"
        />
      )}
    </svg>
  );
}

/** Infloww's two flagged platforms, listed disabled. Their marks are drawn after
 *  Infloww's rows (mym's white wordmark, Fanvue's green tile), not its paths. */
const COMING_SOON = [
  {
    name: "mym",
    logo: (
      <svg aria-hidden data-testid="platform-logo-mym" viewBox="0 0 24 24" className="w-6 h-6 shrink-0">
        <text x="12" y="15" textAnchor="middle" fontSize="9" fontWeight="700" fill="currentColor">mym</text>
      </svg>
    ),
  },
  {
    name: "Fanvue",
    logo: (
      <svg aria-hidden data-testid="platform-logo-fanvue" viewBox="0 0 24 24" className="w-6 h-6 shrink-0">
        <rect x="2" y="2" width="20" height="20" rx="4" fill="#6CE57A" />
        <path d="M7 17.5c1.6-5 4.6-8.3 10-9.5-2.4 1.4-3.9 2.9-4.7 4.5H16c-1.5 1.1-3.4 1.7-5.4 1.8L9.2 17.5z" fill="#fff" />
      </svg>
    ),
  },
] as const;

/** HBChip's count: "99+" past 99. */
export const unreadLabel = (n: number) => (n > 99 ? "99+" : String(n));

/** Unread per platform: the roster's unread summed over that platform's accounts with a session. */
export function usePlatformUnread(): Record<Platform, number> {
  const accounts = useAccounts().data?.accounts;
  const counts = useRosterCounts();
  return useMemo(() => {
    const out: Record<Platform, number> = { onlyfans: 0, fansly: 0 };
    for (const a of accounts ?? []) if (a.has_session) out[accountPlatform(a)] += counts[a.id]?.unread ?? 0;
    return out;
  }, [accounts, counts]);
}

export default function PlatformSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const platform = usePlatform();
  const unread = usePlatformUnread();
  const { open, setOpen, ref } = useOutsideClose();
  const anyUnread = PLATFORMS.some((p) => unread[p] > 0);
  const name = PLATFORM_NAME[platform];

  const pick = (p: Platform) => {
    setOpen(false);
    setPlatform(p);
  };

  const Chevron = open ? ChevronUp : ChevronDown;
  return (
    <div ref={ref} className={cn("relative shrink-0 mb-6", collapsed ? "w-12" : "w-full")}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={collapsed ? `Platform: ${name}` : undefined}
        title={collapsed ? name : undefined}
        className={cn(
          "relative flex items-center gap-3 h-12 rounded-xl bg-nav-surface hover:bg-nav-hover transition-colors",
          collapsed ? "w-12 justify-center" : "w-full px-4",
        )}
      >
        <PlatformLogo platform={platform} />
        {!collapsed && (
          <>
            <span className="flex-1 text-left text-[16px] font-medium text-nav-fg-active">{name}</span>
            {anyUnread && <span data-testid="platform-unread-dot" aria-hidden className="w-2 h-2 rounded-full bg-pink" />}
            <Chevron aria-hidden className="w-5 h-5 text-nav-fg" />
          </>
        )}
        {collapsed && anyUnread && (
          <span data-testid="platform-unread-dot" aria-hidden className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-pink" />
        )}
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Platform"
          className={cn(
            "absolute z-50 flex flex-col gap-1 p-2 rounded-lg border border-nav-surface bg-chrome shadow-lg",
            collapsed ? "left-full top-0 ml-2 w-56" : "left-0 right-0 top-full mt-2",
          )}
        >
          {PLATFORMS.map((p) => (
            <button
              key={p}
              type="button"
              role="menuitemradio"
              aria-checked={p === platform}
              onClick={() => pick(p)}
              className={cn(
                "flex items-center gap-3 h-10 px-2 rounded-lg text-[14px] font-medium transition-colors",
                p === platform ? "bg-nav-hover text-nav-fg-active" : "text-nav-fg hover:bg-nav-hover",
              )}
            >
              <Check aria-hidden className={cn("w-4 h-4 shrink-0", p !== platform && "invisible")} />
              <PlatformLogo platform={p} className="w-6 h-6" />
              <span className="flex-1 text-left">{PLATFORM_NAME[p]}</span>
              {unread[p] > 0 && (
                <span
                  aria-label={`${unread[p]} unread`}
                  className="min-w-5 h-5 px-1.5 rounded-full bg-pink text-white text-[12px] leading-5 text-center"
                >
                  {unreadLabel(unread[p])}
                </span>
              )}
            </button>
          ))}
          {COMING_SOON.map((p) => (
            <button
              key={p.name}
              type="button"
              role="menuitem"
              disabled
              aria-disabled
              title={`${p.name} is coming soon`}
              className="flex items-center gap-3 h-10 px-2 rounded-lg text-[14px] font-medium text-nav-fg opacity-50 cursor-not-allowed"
            >
              <Check aria-hidden className="w-4 h-4 shrink-0 invisible" />
              {p.logo}
              <span className="flex-1 text-left">{p.name}</span>
              <span className="h-5 px-1.5 rounded-full bg-nav-surface text-[12px] leading-5 whitespace-nowrap">Coming soon</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
