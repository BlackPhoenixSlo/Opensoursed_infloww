"use client";

import { useCallback, useEffect, useRef } from "react";

import { LG } from "@/hooks/useIsDesktop";


export const CHAT_ENTRY = "__mpChat";

// Live matchMedia, not useIsDesktop: that reads false during hydration, and a desktop deep link must not get an entry.
const narrow = () => !window.matchMedia(LG).matches;
const marked = () => (window.history.state as Record<string, unknown> | null)?.[CHAT_ENTRY] === true;

// Code replacing the URL must keep the mark (replaceState with this).
export function keepChatEntry(): Record<string, true> | null {
  return marked() ? { [CHAT_ENTRY]: true } : null;
}

const unmarked = (): Record<string, unknown> => {
  const s = { ...(window.history.state as Record<string, unknown> | null) };
  delete s[CHAT_ENTRY];
  return s;
};

export function useChatBackEntry(enabled: boolean, open: boolean, close: () => void): () => void {
  const openRef = useRef(open);
  const closeRef = useRef(close);
  useEffect(() => { openRef.current = open; closeRef.current = close; });
  const popping = useRef(false);
  const popOnce = useCallback(() => {
    if (popping.current) return;
    popping.current = true;
    window.history.back();
  }, []);

  useEffect(() => {
    if (!enabled || !narrow() || popping.current) return;
    if (open && !marked()) window.history.pushState({ [CHAT_ENTRY]: true }, "");
    else if (!open && marked()) popOnce();
  }, [enabled, open, popOnce]);

  useEffect(() => {
    if (!enabled || !narrow()) return;
    const onPop = () => {
      popping.current = false;
      if (marked()) {
        if (!openRef.current) window.history.replaceState(unmarked(), "");
      } else if (openRef.current) {
        closeRef.current();
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [enabled]);

  return useCallback(() => {
    if (enabled && narrow() && marked()) popOnce();
    else close();
  }, [enabled, close, popOnce]);
}
