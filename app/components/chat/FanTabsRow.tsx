"use client";

/**
 * FanTabsRow — the row under the Window header that holds the Fan tabs (the
 * Clone's `.hometabs`). It keeps its height while empty, so the panes do not
 * move when the first Fan tab opens (docs/spec/phase-01-window-chrome-tabs.md,
 * story 32). Home is its first item, a folder tab over the Fan List, as in
 * Infloww (2026-10-18 capture): it goes to Messages Pro's own inbox root, the
 * Fan List with no Thread open, never to the app's dashboard. The Fan tabs
 * strip follows it; the tab
 * of the conversation open in the Thread is the active one, clicking a tab
 * hands it to `onActivate`, and ✕ hands the tab to open next (or null) to
 * `onClosed`.
 */

import Link from "next/link";
import { LayoutGrid } from "lucide-react";

import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { FanTabs } from "./FanTabs";
import { fanTabKey, type FanTab } from "./useFanTabs";

/** `openFan`: the Fan open in the Thread (null with none), for the active tab. */
export function FanTabsRow({ openFan, onActivate, onClosed, onHome }: {
  openFan: { accountId: string; fanId: FanId } | null;
  /** Home: empty the Thread. */
  onHome: () => void;
  onActivate: (tab: FanTab) => void;
  onClosed: (next: FanTab | null) => void;
}) {
  return (
    <div role="region" aria-label="Fan tabs" className={cn(MP.fanTabs.bar, "flex items-end bg-[var(--inf-tabs-row,var(--color-bg))] border-[var(--inf-rule,var(--color-border))]")}>
      {/* On the index route the link is this page, so `onHome` empties the
       *  Thread; from a Deep link the link itself lands on the index. */}
      <Link href="/messages-pro" onClick={onHome} className={cn(MP.windowHeader.home, "shrink-0 flex items-center justify-center bg-[var(--inf-pane,var(--color-panel))] text-fg")}>
        <LayoutGrid aria-hidden className={cn(MP.windowHeader.homeIcon, "text-fg-dim")} />
        Home
      </Link>
      <FanTabs
        activeKey={openFan ? fanTabKey(openFan.accountId, openFan.fanId) : null}
        onActivate={onActivate}
        onClosed={onClosed}
      />
    </div>
  );
}
