import type { QueryClient, QueryKey } from "@tanstack/react-query";

export function patchQueryData<T>(
  qc: QueryClient,
  queryKey: QueryKey,
  updater: (prev: T | undefined) => T | undefined,
): void {
  const state = qc.getQueryState(queryKey);
  // A write is not a read: keep the read time and re-mark the invalidation so the next mount or poll still refetches.
  qc.setQueryData<T>(queryKey, updater, { updatedAt: state?.dataUpdatedAt ?? 0 });
  if (state?.isInvalidated) void qc.invalidateQueries({ queryKey, exact: true, refetchType: "none" });
}
