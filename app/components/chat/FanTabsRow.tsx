"use client";


import Link from "next/link";
import { LayoutGrid } from "lucide-react";

import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { FanTabs } from "./FanTabs";
import { fanTabKey, type FanTab } from "./useFanTabs";

export function FanTabsRow({ openFan, onActivate, onClosed, onHome }: {
  openFan: { accountId: string; fanId: FanId } | null;
  onHome: () => void;
  onActivate: (tab: FanTab) => void;
  onClosed: (next: FanTab | null) => void;
}) {
  return (
    <div role="region" aria-label="Fan tabs" className={cn(MP.fanTabs.bar, "flex items-end bg-[var(--inf-tabs-row,var(--color-bg))] border-[var(--inf-rule,var(--color-border))]")}>
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
