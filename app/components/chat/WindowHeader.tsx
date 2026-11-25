"use client";


import Link from "next/link";
import { usePathname } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

import { IfMark } from "@/components/auth/SiteLook";
import { SwitchTrack } from "@/components/ui/SwitchTrack";
import { useSfw } from "@/hooks/useBlurMode";
import { useRailSettings } from "@/hooks/useRailSettings";
import { MP } from "@/lib/messagesPro";
import { railVisibleOn, surfaceOf, withRailOn } from "@/lib/moneyRailStorage";
import { cn } from "@/lib/utils";
import { CreatorTabs } from "./CreatorTabs";
import { AllModelsTab } from "./MessagesProExtras";

const G = MP.windowHeader;

export function goToDashboard(e: MouseEvent<HTMLAnchorElement>): void {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const main = window.opener as Window | null;
  if (!main || main.closed) return;
  try {
    main.location.assign("/");
    main.focus();
    e.preventDefault();
  } catch {
  }
}

export function RailSwitch() {
  const surface = surfaceOf(usePathname());
  const { settings, commit } = useRailSettings();
  const railOn = settings === null || railVisibleOn(settings, surface);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={railOn}
      aria-label="Buys & tips"
      data-testid="mp-notif-switch"
      disabled={settings === null}
      onClick={() => { if (settings) commit(withRailOn(settings, surface, !railOn)); }}
      title={railOn
        ? "Buys & tips notifications panel shown: click to hide it on this page"
        : "Buys & tips notifications panel hidden: click to show it on this page"}
      className={cn(
        G.sfw,
        "flex flex-col items-center text-fg-dim hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed",
      )}
    >
      <span className={G.sfwLabel}>Notif</span>
      <SwitchTrack on={railOn} />
    </button>
  );
}

export function WindowHeader({ actions, tabs = true }: {
  actions?: ReactNode;
  tabs?: boolean;
} = {}) {
  const [sfw, toggleSfw] = useSfw();
  return (
    <div role="region" aria-label="Window header" className={cn(G.bar, "flex items-end bg-[var(--inf-window,var(--color-bg))] border-[var(--inf-rule,var(--color-border))]")}>
      <Link href="/" onClick={goToDashboard} aria-label="Dashboard" title="Dashboard" className="self-center mr-3 rounded-md focus-visible:outline-2 focus-visible:outline-accent">
        <IfMark className="size-6" />
      </Link>
      {tabs && <AllModelsTab />}
      {tabs && <CreatorTabs />}
      <div className={cn(G.right, "ml-auto self-center flex items-center")}>
        {actions}
        <RailSwitch />
        <button
          type="button"
          role="switch"
          aria-checked={sfw}
          data-testid="mp-sfw-switch"
          onClick={toggleSfw}
          className={cn(G.sfw, "flex flex-col items-center text-fg-dim hover:text-fg")}
          title={sfw ? "SFW on: media blurred" : "SFW off"}
        >
          <span className={G.sfwLabel}>SFW</span>
          <SwitchTrack on={sfw} />
        </button>
      </div>
    </div>
  );
}
