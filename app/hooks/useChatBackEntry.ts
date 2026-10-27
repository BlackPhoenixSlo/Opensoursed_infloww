"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Below lg Messages Pro shows the Fan List or one Thread, swapped by React state
 * with the URL unchanged. Without a history entry for the open Thread, the
 * platform's back (iOS edge swipe, Android back gesture or button, the browser's
 * Back) would leave Messages Pro instead of returning to the Fan List.
 *
 * So while `enabled` (below lg), the open Thread and the current history entry
 * agree: a Thread opening pushes a same-URL entry marked `CHAT_ENTRY`; a back
 * onto an unmarked entry closes the Thread (`close`); a Thread closed in-app
 * (its Back, ✕ on the last Fan tab) pops the marked entry, so the next back
 * leaves Messages Pro as usual. A marked entry found with no Thread open on
 * mount (a reload, a back from a later page) is popped the same way: the entry
 * before it is always Messages Pro's own, so that only ever moves back. One
 * reached by a traversal while Messages Pro is up (the browser's Forward after
 * a back) is never popped, which would undo the traversal and trap every entry
 * after it: it loses its mark in place. The returned `back` is the Thread's Back
 * (its button, a swipe right): on a marked entry it goes back in history and the
 * popstate closes the Thread, so an in-app back and the platform's are one path
 * and never both navigate. One back at a time: history.back() is async, so an
 * effect run again before its popstate (Strict Mode's remount, a re-render)
 * must not send a second one past Messages Pro. No URL changes, so Next's router only
 * restores the same tree. Code replacing the URL must keep the mark
 * (`keepChatEntry`).
 */

export const CHAT_ENTRY = "__mpChat";

/** Live, not `useIsDesktop`'s value: that reads false during hydration, and a
 *  desktop Deep link must not get an entry from that first commit. */
const narrow = () => !window.matchMedia("(min-width: 1024px)").matches;
const marked = () => (window.history.state as Record<string, unknown> | null)?.[CHAT_ENTRY] === true;

/** State for a `history.replaceState` that keeps the current entry's mark. */
export function keepChatEntry(): Record<string, true> | null {
  return marked() ? { [CHAT_ENTRY]: true } : null;
}

/** The current entry's state without the mark (Next's own keys kept). */
const unmarked = (): Record<string, unknown> => {
  const s = { ...(window.history.state as Record<string, unknown> | null) };
  delete s[CHAT_ENTRY];
  return s;
};

export function useChatBackEntry(enabled: boolean, open: boolean, close: () => void): () => void {
  const openRef = useRef(open);
  const closeRef = useRef(close);
  useEffect(() => { openRef.current = open; closeRef.current = close; });
  // A back sent and its popstate not yet in.
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
