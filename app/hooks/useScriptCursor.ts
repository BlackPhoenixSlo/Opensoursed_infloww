"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { type FanId } from "@/lib/fanId";

export interface ScriptCursor {
  scriptId: string;
  step: number;
}

/** Per-chat cursor for template scripts. Stored in localStorage so the
 *  next-step suggestion survives reloads. Sticky — only cleared when the
 *  user explicitly dismisses the bubble (✕) or when no successor template
 *  exists (handled in render). */
export function useScriptCursor(
  accountId: string | null,
  fanId: FanId | null,
): [ScriptCursor | null, (next: ScriptCursor | null) => void] {
  const storageKey = useMemo(
    () => (accountId && fanId != null ? `chatterly:scriptCursor:${accountId}:${fanId}` : null),
    [accountId, fanId],
  );
  const [cursor, setCursor] = useState<ScriptCursor | null>(null);
  useEffect(() => {
    if (!storageKey || typeof window === "undefined") {
      setCursor(null);
      return;
    }
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) {
        setCursor(null);
        return;
      }
      const parsed = JSON.parse(raw) as ScriptCursor;
      if (parsed && typeof parsed.scriptId === "string" && typeof parsed.step === "number") {
        setCursor(parsed);
      } else {
        setCursor(null);
      }
    } catch {
      setCursor(null);
    }
  }, [storageKey]);
  const save = useCallback(
    (next: ScriptCursor | null) => {
      setCursor(next);
      if (!storageKey || typeof window === "undefined") return;
      try {
        if (next) window.localStorage.setItem(storageKey, JSON.stringify(next));
        else window.localStorage.removeItem(storageKey);
      } catch {
        /* quota / private mode — UI still works for the current session */
      }
    },
    [storageKey],
  );
  return [cursor, save];
}
