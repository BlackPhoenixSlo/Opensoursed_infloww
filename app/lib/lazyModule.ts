import { useEffect, useReducer } from "react";

/**
 * A module kept out of the first load, fetched the first time a component wants it, without Suspense:
 * `next/dynamic` (React.lazy) suspends on its first render even with the chunk in, and React then holds the empty
 * fallback ~300 ms (its Suspense reveal throttle, measured: PlatformGate's note). `useLazyModule` gives `undefined`
 * until the module lands, re-renders its caller then, and gives it on the first render of every caller after.
 * A failed load is left unhandled on purpose (the root layout's stale-chunk script reloads the page on it); the
 * next wanting render tries again.
 */
export interface LazyModule<T> {
  preload: () => Promise<T>;
  readonly current: T | undefined;
}

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
