import { useSyncExternalStore } from "react";

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

export function readStorage(key: string | null): string | null {
  if (key === null || typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

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
