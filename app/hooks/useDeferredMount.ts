"use client";


import { useEffect, useState } from "react";

import { onIdle } from "@/lib/idle";

export function useDeferredMount(ms = 600): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready) return;
    return onIdle(() => setReady(true), ms);
  }, [ms, ready]);
  return ready;
}
