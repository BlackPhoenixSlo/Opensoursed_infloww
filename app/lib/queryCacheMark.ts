import type { QueryClient, QueryKey } from "@tanstack/react-query";

export type CacheMark = { data: unknown; dataUpdatedAt: number } | undefined;

export function cacheMark(qc: QueryClient, key: QueryKey): CacheMark {
  const s = qc.getQueryState(key);
  return s && { data: s.data, dataUpdatedAt: s.dataUpdatedAt };
}

// A read started before a write (mark-read, send, SSE bump) that resolves after it must not overwrite the cache.
export function cacheMovedSince(before: CacheMark, now: CacheMark): boolean {
  return before?.dataUpdatedAt !== now?.dataUpdatedAt || before?.data !== now?.data;
}
