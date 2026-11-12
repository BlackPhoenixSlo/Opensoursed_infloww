"use client";

/** Settings' left tab list (docs/infloww-screens.md §3.10). Data: lib/nav.ts.
 *  md and up it is Infloww's Tab list (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md
 *  rows 3-7): 25% of the Tab area, 18.75% once the Tab area is 1200px wide, its own
 *  scroll, 64px icon rows on Infloww's colours (`--if-*`, ADR-0009). Below md it is
 *  one select naming the open tab (a phone showed 3 of 13 tabs in a strip with no hint of the rest). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { SETTINGS_TABS, visibleLinks, type NavLink } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { IfSelect } from "@/components/ui/infloww";

export default function SettingsNav() {
  const pathname = usePathname();
  const router = useRouter();
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
          "shrink-0 whitespace-nowrap flex items-center transition-colors",
          "h-[var(--if-tab-h)] px-[var(--if-row-px)] gap-[var(--if-row-px)] text-[length:var(--if-fs-lg)]",
          active
            ? "bg-[var(--if-accent-bg)] text-[var(--if-accent)]"
            : "text-[var(--if-fg-3)] hover:text-[var(--if-fg)]",
        )}
      >
        {Icon && <Icon aria-hidden strokeWidth={1.5} className="w-5 h-5 shrink-0" />}
        <span className="truncate">{t.label}</span>
      </Link>
    );
  };

  const current = tabs.find((t) => t.href === pathname)?.href ?? null;
  return (
    <>
      <IfSelect
        aria-label="Settings tab"
        className="md:hidden w-full"
        value={current}
        placeholder="Choose a tab"
        options={tabs.map((t) => ({ value: t.href, label: t.label }))}
        onChange={(href) => router.push(href)}
      />
      <nav
        data-settings="tab-list"
        className="hidden md:flex md:flex-col md:overflow-x-hidden md:overflow-y-auto no-scrollbar md:h-full md:w-1/4 @min-[1200px]:w-[18.75%] md:shrink-0 md:bg-[var(--if-list-bg)]"
      >
        {tabs.map(item)}
      </nav>
    </>
  );
}
