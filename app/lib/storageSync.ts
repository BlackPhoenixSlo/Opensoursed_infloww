/**
 * storageSync — localStorage-backed `useSyncExternalStore` stores (the
 * `useBlurMode` pattern): the subscribe half, the raw read, and the persisted
 * value/flag factories. A custom event re-reads the store when this window
 * writes it, and `storage` when another window does.
 */

import { useSyncExternalStore } from "react";

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

/** The raw stored string for `key` — null when the key is absent, when there
 *  is no key yet (`null`, e.g. no signed-in employee), or on the server. */
export function readStorage(key: string | null): string | null {
  if (key === null || typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

/** A persisted value. `decode` maps the raw stored string (null = absent) to
 *  a value; `encode` maps a value to the string to store, or null to remove
 *  the key.
 *
 *  If a write throws (quota / private mode) the choice is still held in
 *  memory, so every same-tab reader agrees with the click; it is dropped the
 *  moment the stored value changes under it (another tab wrote). */
export function createStoredValue<T>(
  key: string,
  event: string,
  def: T,
  decode: (raw: string | null) => T,
  encode: (v: T) => string | null,
): {
  read: () => T;
  use: () => [T, (next: T) => void];
} {
  let unsaved: { value: T; raw: string | null } | null = null;

  function read(): T {
    if (typeof window === "undefined") return def;
    let raw: string | null;
    try {
      raw = readStorage(key);
    } catch {
      return unsaved ? unsaved.value : def;
    }
    if (unsaved) {
      if (unsaved.raw === raw) return unsaved.value;
      unsaved = null;
    }
    return decode(raw);
  }

  function set(next: T): void {
    let before: string | null = null;
    try {
      before = window.localStorage.getItem(key);
      const raw = encode(next);
      if (raw === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, raw);
      unsaved = null;
    } catch {
      unsaved = { value: next, raw: before };
    }
    window.dispatchEvent(new Event(event));
  }

  const subscribe = subscribeToStorage(event);
  const server = () => def;

  function useStoredValue(): [T, (next: T) => void] {
    return [useSyncExternalStore(subscribe, read, server), set];
  }

  return { read, use: useStoredValue };
}

/** A persisted on/off preference. Only the NON-default value is stored —
 *  `"0"` for a default-on flag, `"1"` for a default-off one — and choosing the
 *  default removes the key, so a missing key always reads as `def`. */
export function createStoredFlag(key: string, event: string, def: boolean) {
  const stored = def ? "0" : "1";
  return createStoredValue<boolean>(
    key,
    event,
    def,
    (raw) => (raw === stored ? !def : def),
    (v) => (v === def ? null : stored),
  );
}
