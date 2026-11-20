import type { QueryClient, QueryKey } from "@tanstack/react-query";

/** What one cache entry held at a moment: its data and when it was written. */
export type CacheMark = { data: unknown; dataUpdatedAt: number } | undefined;

export function cacheMark(qc: QueryClient, key: QueryKey): CacheMark {
  const s = qc.getQueryState(key);
  return s && { data: s.data, dataUpdatedAt: s.dataUpdatedAt };
}

/** Whether the entry was written (or dropped) since `before`. A read started at
 *  `before` that resolves after such a write is older than the cache: it must
 *  not overwrite it (a mark-read, a send, an SSE bump, a folder write). */
export function cacheMovedSince(before: CacheMark, now: CacheMark): boolean {
  return before?.dataUpdatedAt !== now?.dataUpdatedAt || before?.data !== now?.data;
}
