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
 */

import Link from "next/link";
import type { MouseEvent } from "react";

import { IfMark } from "@/components/auth/SiteLook";
import { SwitchTrack } from "@/components/ui/SwitchTrack";
import { useSfw } from "@/hooks/useBlurMode";
import { MP } from "@/lib/messagesPro";
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
        {/* SFW = blur media everywhere; the same store as the app top bar's. */}
        <button
          type="button"
          role="switch"
          aria-checked={sfw}
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
