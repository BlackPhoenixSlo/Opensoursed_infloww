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
 * The "Notif" switch is the Window header's (`WindowHeader` `RailSwitch`).
 */

import { Users } from "lucide-react";

import { NotificationBell, type OpenNotificationFan } from "@/components/NotificationBell";
import { MP } from "@/lib/messagesPro";
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
