import { useEffect, useReducer } from "react";

export interface LazyModule<T> {
  preload: () => Promise<T>;
  readonly current: T | undefined;
}

// Not next/dynamic: React.lazy suspends on first render and holds the fallback ~300 ms (measured). A failed load is left unhandled: the root layout's stale-chunk script reloads the page.
export function lazyModule<T>(load: () => Promise<T>): LazyModule<T> {
  let mod: T | undefined;
  let pending: Promise<T> | undefined;
  return {
    preload: () => (pending ??= load().then(
      (m) => (mod = m),
      (e: unknown) => { pending = undefined; throw e; },
    )),
    get current() { return mod; },
  };
}

export function useLazyModule<T>(m: LazyModule<T>, want = true): T | undefined {
  const [, landed] = useReducer((n: number) => n + 1, 0);
  const mod = m.current;
  useEffect(() => {
    if (want && mod === undefined) void m.preload().then(landed);
  }, [m, mod, want]);
  return mod;
}
