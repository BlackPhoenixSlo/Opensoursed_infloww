/**
 * The user doing something, and the browser doing nothing: the two signals
 * idle-time work waits on (useIdleMode, useDeferredMount, the unread-thread
 * warm).
 */

/** What counts as the user doing something in this window. */
export const USER_INPUT_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"] as const;

/** Calls `onInput` on each of `events` anywhere in this window, in the capture
 *  phase so it is heard before any handler acts on it. Returns the unsubscribe. */
export function onUserInput(
  onInput: () => void,
  events: readonly string[] = USER_INPUT_EVENTS,
): () => void {
  const opts = { capture: true, passive: true } as const;
  for (const e of events) window.addEventListener(e, onInput, opts);
  return () => {
    for (const e of events) window.removeEventListener(e, onInput, opts);
  };
}

/** Calls `cb` once the browser is idle, or after `timeout` ms at the latest;
 *  without requestIdleCallback (Safari), after `timeout`. Returns the cancel. */
export function onIdle(cb: () => void, timeout: number): () => void {
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(() => cb(), { timeout });
    return () => cancelIdleCallback(id);
  }
  const t = setTimeout(cb, timeout);
  return () => clearTimeout(t);
}
