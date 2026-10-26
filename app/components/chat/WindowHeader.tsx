"use client";

/**
 * WindowHeader — Messages Pro's own top row (the Clone's `.topstrip`,
 * docs/spec/phase-01-window-chrome-tabs.md): SFW at the right. Home sits in
 * the Fan tabs row under it, as in Infloww (`FanTabsRow`).
 * It is there from lg up, in Messages Pro's own window (ADR-0002), so its
 * SFW is the only one. All Models comes first, before the Creator tabs
 * strip, with the Legacy flag off and on, so the scope can always go back to
 * every Creator; there is no "+" Extras overflow (TODO.md B2;
 * `MessagesProExtras`). The Creator tabs and "+ Add a Creator"
 * (`CreatorTabs`) follow it. Our Inflowwww mark sits before All Models
 * as the way back to the Dashboard (`goToDashboard`): this window has no
 * sidebar, and in the desktop app no address bar.
 * The right-hand group ends with SFW, the far right; before it the "Notif"
 * switch (`RailSwitch`).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { MouseEvent } from "react";

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

/** The Dashboard in the window that opened this one (the app's main window), brought to the front. With no such
 *  window (a tab, or its opener closed) the link goes there in this window, as does a modified click its own way. */
export function goToDashboard(e: MouseEvent<HTMLAnchorElement>): void {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const main = window.opener as Window | null;
  if (!main || main.closed) return;
  try {
    main.location.assign("/");
    main.focus();
    e.preventDefault();
  } catch {
    /* another origin's window: the link goes there here */
  }
}

/** The "Notif" switch (Compare FL11, ours; TODO.md B1): shows or hides the
 *  Buys & tips rail (`MoneyRail`, the money notifications) on this page's
 *  surface, the same choice as the rail's ⚙ "Show on" ticks, kept in the
 *  rail's settings (`useRailSettings`). Disabled until those are read. It sits
 *  outside the rail so it can bring the rail back. Labelled above its track
 *  as SFW is; desktop only, as the rail is in Messages Pro. */
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

export function WindowHeader() {
  const [sfw, toggleSfw] = useSfw();
  return (
    <div role="region" aria-label="Window header" className={cn(G.bar, "flex items-end bg-[var(--inf-window,var(--color-bg))] border-[var(--inf-rule,var(--color-border))]")}>
      <Link href="/" onClick={goToDashboard} aria-label="Dashboard" title="Dashboard" className="self-center mr-3 rounded-md focus-visible:outline-2 focus-visible:outline-accent">
        <IfMark className="size-6" />
      </Link>
      <AllModelsTab />
      <CreatorTabs />
      <div className={cn(G.right, "ml-auto self-center flex items-center")}>
        <RailSwitch />
        {/* SFW = blur media everywhere; the same store as the app top bar's. */}
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
