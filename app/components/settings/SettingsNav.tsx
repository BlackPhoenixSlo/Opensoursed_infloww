"use client";

/** Settings' left tab list (docs/infloww-screens.md §3.10). Data: lib/nav.ts.
 *  md and up it is Infloww's Tab list (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md
 *  rows 3-7): 25% of the Tab area, 18.75% once the Tab area is 1200px wide, its own
 *  scroll, 64px icon rows on Infloww's colours (`--if-*`, ADR-0009). Below md it
 *  stays the app's horizontal strip. */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { SETTINGS_TABS, visibleLinks, type NavLink } from "@/lib/nav";
import { cn } from "@/lib/utils";

export default function SettingsNav() {
  const pathname = usePathname();
  const { user } = useUser();
  const tabs = visibleLinks(SETTINGS_TABS, {
    chatterOnly: useIsChatterOnly(),
    grantedPages: null,
    master: user?.is_admin === true,
  });

  const item = (t: NavLink) => {
    const active = pathname === t.href;
    const Icon = t.icon;
    return (
      <Link
        key={t.href}
        href={t.href}
        data-settings="tab"
        aria-current={active ? "page" : undefined}
        className={cn(
          "shrink-0 whitespace-nowrap px-3 h-10 flex items-center rounded-lg text-sm transition-colors",
          "md:h-[var(--if-tab-h)] md:px-[var(--if-row-px)] md:gap-[var(--if-row-px)] md:rounded-none md:text-[length:var(--if-fs-lg)]",
          active
            ? "bg-bg-elev-1 text-fg md:bg-[var(--if-accent-bg)] md:text-[var(--if-accent)]"
            : "text-fg-dim hover:text-fg hover:bg-bg-elev-1/50 md:text-[var(--if-fg-3)] md:hover:text-[var(--if-fg)] md:hover:bg-transparent",
        )}
      >
        {Icon && <Icon aria-hidden strokeWidth={1.5} className="hidden md:block w-5 h-5 shrink-0" />}
        <span className="md:truncate">{t.label}</span>
      </Link>
    );
  };

  return (
    <nav
      data-settings="tab-list"
      className="flex md:flex-col gap-0.5 md:gap-0 overflow-x-auto md:overflow-x-hidden md:overflow-y-auto no-scrollbar md:h-full md:w-1/4 @min-[1200px]:w-[18.75%] md:shrink-0 md:bg-[var(--if-list-bg)]"
    >
      {tabs.map(item)}
    </nav>
  );
}
