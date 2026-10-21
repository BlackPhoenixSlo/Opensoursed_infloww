"use client";

/**
 * IdleOverlay — what the window shows in Idle mode (`useIdleMode`): Infloww's
 * full-screen "has gone idle due to inactivity" with its Return button. Any
 * input leaves Idle mode, the button included.
 */

import { useIdleMode } from "@/hooks/useIdleMode";

export function IdleOverlay() {
  const idle = useIdleMode();
  if (!idle) return null;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="idle-title"
      className="fixed inset-0 z-[80] grid place-items-center bg-black/60 p-4">
      <div className="bg-panel border border-border rounded-lg shadow-xl p-6 max-w-sm text-center">
        <h2 id="idle-title" className="text-sm font-semibold text-fg">
          Inflowwww has gone idle due to inactivity
        </h2>
        <p className="mt-1 text-xs text-fg-dim">Live updates are paused until you return.</p>
        <button type="button" className="mt-4 h-9 px-4 rounded-md bg-accent text-white text-xs font-semibold">
          Return to Inflowwww
        </button>
      </div>
    </div>
  );
}
