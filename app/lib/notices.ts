"use client";

/**
 * One-line app notices ("Clock in successful") for the toast stack
 * (`NotificationToaster`'s `ToastStack`, which subscribes here), so code
 * outside that module can toast without importing it: it already imports
 * `lib/shifts`, which would make the import a cycle.
 */

export interface Notice {
  /** Dedup key: a second notice with the same id while the first shows is dropped. */
  id: string;
  text: string;
  /** The card's small label, as an OF toast's type ("Time tracking"). */
  label: string;
}

const listeners = new Set<(n: Notice) => void>();

export function pushNotice(n: Notice): void {
  for (const fn of listeners) fn(n);
}

/** Subscribe; returns the unsubscribe. */
export function onNotice(fn: (n: Notice) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
