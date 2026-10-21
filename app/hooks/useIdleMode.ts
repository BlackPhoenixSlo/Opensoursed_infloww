"use client";

/**
 * useIdleMode — Infloww's Idle mode (04 M18): after IDLE_AFTER_MS with no
 * input in this window, close the SSE stream and stop every react-query poll;
 * the next input resumes both. A forgotten tab then holds no relay connection
 * and makes no OF calls.
 *
 * Polls stop through react-query's focusManager: a `refetchInterval` only
 * fires while focused (no query here sets `refetchIntervalInBackground`). On
 * resume the stream reopens from its last event id, so the relay replays what
 * was missed or sends `resync` (useAccountStateEvents refetches everything),
 * and every active query past its staleTime refetches now rather than on its
 * next tick.
 */

import { useEffect, useState } from "react";
import { focusManager, useQueryClient } from "@tanstack/react-query";

import { eventBus } from "@/lib/events";

/** Infloww's: "after 10 min with no input" (docs/infloww-screens.md §1.3). */
export const IDLE_AFTER_MS = 10 * 60_000;
export const IDLE_CHECK_MS = 15_000;
const INPUT = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"] as const;

export function useIdleMode(): boolean {
  const qc = useQueryClient();
  const [idle, setIdle] = useState(false);

  useEffect(() => {
    let lastInput = Date.now();
    let paused = false;
    const resume = () => {
      paused = false;
      focusManager.setFocused(undefined);
      eventBus.resume();
    };
    const onInput = () => {
      lastInput = Date.now();
      if (!paused) return;
      resume();
      setIdle(false);
      void qc.refetchQueries({ type: "active", stale: true });
    };
    const timer = setInterval(() => {
      if (paused || Date.now() - lastInput < IDLE_AFTER_MS) return;
      paused = true;
      eventBus.pause();
      focusManager.setFocused(false);
      setIdle(true);
    }, IDLE_CHECK_MS);
    for (const t of INPUT) window.addEventListener(t, onInput, { capture: true, passive: true });
    return () => {
      clearInterval(timer);
      for (const t of INPUT) window.removeEventListener(t, onInput, { capture: true });
      if (paused) resume();
    };
  }, [qc]);

  return idle;
}
