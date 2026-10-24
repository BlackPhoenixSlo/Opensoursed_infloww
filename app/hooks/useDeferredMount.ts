"use client";

/**
 * useDeferredMount — returns false on first render, true after a small
 * idle delay. Used to gate non-critical "decoration" queries (spend
 * chips, last-purchase, chat folders, badge counters) so they don't
 * compete with the chat list fetch for upstream OF bandwidth and the
 * relay's thread pool on cold load.
 *
 * Pattern at call site:
 *
 *     const ready = useDeferredMount();
 *     useQuery({ ..., enabled: ready && hasInputs });
 *
 * Default 600ms is long enough for the primary /chats fetch to land
 * and the first paint to settle, short enough that the chip "pop-in"
 * still feels live to the user. After the timer fires once, `ready`
 * stays true for the life of the component — so subsequent re-renders
 * (pagination, scope switch) fire decoration queries immediately.
 */

import { useEffect, useState } from "react";

import { onIdle } from "@/lib/idle";

export function useDeferredMount(ms = 600): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready) return;
    // Idle, so we yield to any already-in-flight work; after `ms` at the latest.
    return onIdle(() => setReady(true), ms);
  }, [ms, ready]);
  return ready;
}
