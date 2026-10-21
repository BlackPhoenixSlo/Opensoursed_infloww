/**
 * storageSync — the subscribe half of a localStorage-backed
 * `useSyncExternalStore` store (the `useBlurMode` pattern): a custom event
 * re-reads the store when this window writes it, and `storage` when another
 * window does.
 */

/** A `useSyncExternalStore` subscribe function for a store whose writers
 *  dispatch `event` on `window`. Create it once per store, at module level,
 *  so its identity is stable. */
export function subscribeToStorage(event: string): (onChange: () => void) => () => void {
  return (onChange) => {
    window.addEventListener(event, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(event, onChange);
      window.removeEventListener("storage", onChange);
    };
  };
}
