"use client";


import { Users } from "lucide-react";

import { NotificationBell, type OpenNotificationFan } from "@/components/NotificationBell";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const G = MP.fanList;

const BELL = { button: G.button, icon: G.buttonIcon, badge: G.notifBadge, panel: MP.ours.FanListButtons.notifPanel };

export function FanListButtons({ onlineOnly, onToggleOnline, onOpenFan, onlineListFailed = false }: {
  onlineOnly: boolean;
  onToggleOnline: () => void;
  onOpenFan: OpenNotificationFan;
  onlineListFailed?: boolean;
}) {
  return (
    <div className={cn(G.buttons, "relative flex")}>
      <button
        type="button"
        aria-pressed={onlineOnly}
        onClick={onToggleOnline}
        title={onlineListFailed ? "Online list unavailable" : onlineOnly ? "Showing only fans online now: click to show all" : "Show only fans online now"}
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
