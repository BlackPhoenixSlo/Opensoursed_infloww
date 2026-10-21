"use client";

/**
 * FanListButtons — the Fan List buttons (the Clone's `.big-btns`,
 * docs/spec/phase-01-window-chrome-tabs.md), in the Fan List's actions slot
 * between its header and its filters, at every width. "Online Fans" toggles
 * the page's online-only state: while on it is pressed (a 2px ring) and the
 * Fan List shows only the Fans `isFanOnline` counts as online. When the
 * Creator's online list could not be read, its tooltip says so.
 * "Notifications" is the notification bell's Messages Pro variant: the
 * scoped Creator's OnlyFans notification count and the bell's panel, whose
 * rows about a Fan go to `onOpenFan` (the page opens a Fan tab).
 * `RailSwitch` is the "Notif" switch (Compare FL11, ours; TODO.md B1), which
 * Messages Pro puts at the Fan List header's right end, after its icons: it
 * shows or hides the Buys & tips rail (`MoneyRail`, the money notifications)
 * on this page's surface, the same choice as the rail's ⚙ "Show on" ticks,
 * kept in the rail's settings (`useRailSettings`). It is disabled until those
 * are read. It sits outside the rail so it can bring the rail back.
 */

import { Users } from "lucide-react";
import { usePathname } from "next/navigation";

import { NotificationBell, type OpenNotificationFan } from "@/components/NotificationBell";
import { SwitchTrack } from "@/components/ui/SwitchTrack";
import { useRailSettings } from "@/hooks/useRailSettings";
import { MP } from "@/lib/messagesPro";
import { railVisibleOn, surfaceOf, withRailOn } from "@/lib/moneyRailStorage";
import { cn } from "@/lib/utils";

const G = MP.fanList;

/** Notifications' Geometry, handed to the shared bell (spec, Shared modules). */
const BELL = { button: G.button, icon: G.buttonIcon, badge: G.notifBadge, panel: MP.ours.FanListButtons.notifPanel };

export function FanListButtons({ onlineOnly, onToggleOnline, onOpenFan, onlineListFailed = false }: {
  onlineOnly: boolean;
  onToggleOnline: () => void;
  /** A notification row's Fan: open it in a Fan tab. */
  onOpenFan: OpenNotificationFan;
  /** The online-subscribers read failed: only the row rule applies. */
  onlineListFailed?: boolean;
}) {
  return (
    // Relative: the Notifications panel opens against the row.
    <div className={cn(G.buttons, "relative flex")}>
      <button
        type="button"
        aria-pressed={onlineOnly}
        onClick={onToggleOnline}
        title={onlineListFailed ? "Online list unavailable" : undefined}
        className={cn(
          G.button, onlineOnly && G.buttonPressed,
          "relative flex flex-1 items-center justify-center bg-accent text-white hover:bg-accent-hover ring-fg",
        )}
      >
        <Users aria-hidden className={G.buttonIcon} />
        Online Fans
      </button>
      <NotificationBell variant="messages-pro" onOpenFan={onOpenFan} classNames={BELL} />
    </div>
  );
}

/** The "Notif" switch: the Buys & tips rail on this page, labelled above its
 *  track as the Window header's SFW is. */
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
      disabled={settings === null}
      onClick={() => { if (settings) commit(withRailOn(settings, surface, !railOn)); }}
      title={railOn
        ? "Buys & tips notifications panel shown: click to hide it on this page"
        : "Buys & tips notifications panel hidden: click to show it on this page"}
      className={cn(
        MP.ours.FanListButtons.panelSwitch, MP.windowHeader.sfw,
        "shrink-0 flex flex-col items-center justify-center text-fg-dim hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed",
      )}
    >
      <span className={MP.windowHeader.sfwLabel}>Notif</span>
      <SwitchTrack on={railOn} />
    </button>
  );
}
