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

import { useContext, useMemo } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { useOutsideClose } from "@/components/ui/Menu";
import { useAccounts } from "@/hooks/useAccounts";
import { useRosterCounts, type RosterCount } from "@/hooks/useRosterCounts";
import { rosterUnreadText } from "@/lib/format";
import {
  DEFAULT_PLATFORM, AllPlatformsContext, PLATFORMS, PLATFORM_NAME, accountPlatform, isPlatform, platformRow, setPlatform, usePlatform,
  type Platform,
} from "@/lib/platform";
import type { AccountMeta } from "@/lib/relay";
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
      {platformRow(platform).logo.map(({ d, fill }) => <path key={d} d={d} fill={fill} />)}
    </svg>
  );
}

function creatorPlatformName(account: Pick<AccountMeta, "platform">): string | null {
  const platform = accountPlatform(account);
  return platform === DEFAULT_PLATFORM ? null : PLATFORM_NAME[platform];
}

const noPlatformName = () => null;

export function useCreatorPlatformName(): (account: Pick<AccountMeta, "platform">) => string | null {
  return useContext(AllPlatformsContext) ? creatorPlatformName : noPlatformName;
}

export function CreatorPlatformBadge({ account, always = false }: { account: Pick<AccountMeta, "platform">; always?: boolean }) {
  const scopedName = useCreatorPlatformName();
  const name = (always ? creatorPlatformName : scopedName)(account);
  if (!name) return null;
  const platform = accountPlatform(account);
  return (
    <>
      {isPlatform(platform) && <PlatformLogo platform={platform} className="h-3.5 w-3.5" />}
      <span className="sr-only">{` ${name}`}</span>
    </>
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

export interface PlatformUnread { count: number }

/** Unread per platform: the roster's unread summed over that platform's accounts with a session. */
export function platformUnread(
  accounts: readonly Pick<AccountMeta, "id" | "platform" | "has_session">[] | undefined,
  counts: Record<string, RosterCount>,
): Record<Platform, PlatformUnread> {
  const out = Object.fromEntries(PLATFORMS.map((p) => [p.key, { count: 0 }])) as Record<Platform, PlatformUnread>;
  for (const a of accounts ?? []) {
    const c = counts[a.id];
    const p = accountPlatform(a);
    if (!a.has_session || !c || !isPlatform(p)) continue;
    out[p].count += c.unread;
  }
  return out;
}

export function usePlatformUnread(): Record<Platform, PlatformUnread> {
  const accounts = useAccounts().data?.accounts;
  const counts = useRosterCounts();
  return useMemo(() => platformUnread(accounts, counts), [accounts, counts]);
}

export default function PlatformSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const platform = usePlatform();
  const unread = usePlatformUnread();
  const { open, setOpen, ref } = useOutsideClose();
  const anyUnread = PLATFORMS.some(({ key }) => unread[key].count > 0);
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
          {PLATFORMS.map(({ key: p }) => (
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
              {unread[p].count > 0 && (
                <span
                  aria-label={`${unread[p].count} unread`}
                  className="min-w-5 h-5 px-1.5 rounded-full bg-pink text-white text-[12px] leading-5 text-center"
                >
                  {rosterUnreadText(unread[p].count)}
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
