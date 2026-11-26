"use client";

import { useSyncExternalStore } from "react";

import { eventBus } from "@/lib/events";
import { cn } from "@/lib/utils";

export function useLiveBlocked(): boolean {
  return useSyncExternalStore(eventBus.onBlocked, eventBus.liveBlocked, () => false);
}

export function LiveH2Banner({ className }: { className?: string }) {
  if (!useLiveBlocked()) return null;
  return (
    <div
      role="status"
      data-live-h2
      className={cn("mx-3 mb-2 h-10 px-3 rounded-lg bg-[rgba(255,161,95,.14)] flex items-center text-sm text-warn", className)}
    >
      <span className="flex-1 min-w-0 truncate">
        Live updates need HTTP/2<span className="hidden sm:inline">. Chats still load, but new messages show up more slowly.</span>
      </span>
    </div>
  );
}
