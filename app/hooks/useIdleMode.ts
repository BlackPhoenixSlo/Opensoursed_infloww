"use client";


import { useEffect, useState } from "react";
import { focusManager, useQueryClient } from "@tanstack/react-query";

import { eventBus } from "@/lib/events";
import { onUserInput } from "@/lib/idle";

export const IDLE_AFTER_MS = 10 * 60_000;
export const IDLE_CHECK_MS = 15_000;

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
    const unlisten = onUserInput(onInput);
    return () => {
      clearInterval(timer);
      unlisten();
      if (paused) resume();
    };
  }, [qc]);

  return idle;
}
