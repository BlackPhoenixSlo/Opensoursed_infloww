/**
 * settlePool — `Promise.allSettled` with at most `limit` calls in flight.
 *
 * For one user action that reads OnlyFans once per Creator (a refresh, a
 * warm): 5-10 Creators share a proxy, so firing every Creator at once is a
 * burst on it. Results come back in input order, like `allSettled`; one
 * failure never stops the rest. Writes go Creator by Creator instead
 * (`runFanOut`, components/compose/fanOut.ts).
 */

/** The pool most per-Creator OnlyFans reads in one action use. */
export const CREATOR_POOL = 2;

export async function settlePool<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const out: PromiseSettledResult<R>[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      try {
        out[i] = { status: "fulfilled", value: await fn(items[i], i) };
      } catch (reason) {
        out[i] = { status: "rejected", reason };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(Math.max(1, limit), items.length) }, worker));
  return out;
}
