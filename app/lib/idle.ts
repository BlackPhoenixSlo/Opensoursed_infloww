export const USER_INPUT_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"] as const;

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

export function onIdle(cb: () => void, timeout: number): () => void {
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(() => cb(), { timeout });
    return () => cancelIdleCallback(id);
  }
  const t = setTimeout(cb, timeout);
  return () => clearTimeout(t);
}
