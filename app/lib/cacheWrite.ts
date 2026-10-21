import type { QueryClient, QueryKey } from "@tanstack/react-query";

/** Write a query's data without it counting as a read: a live message, the
 *  local seed, a rename. react-query's `setQueryData` dates the data now and
 *  drops a pending invalidation; this keeps the read time (0 when nothing was
 *  ever read) and re-marks the invalidation, so the next mount or poll still
 *  reads what the write didn't.
 *
 *  Limit: react-query makes a manual write the revert point of a fetch in
 *  flight, but the re-mark is a separate dispatch it doesn't capture. A fetch
 *  cancelled with revert after this write restores the data without the mark
 *  (no public API sets both at once); its date stays, so the query still
 *  goes stale on time. */
export function patchQueryData<T>(
  qc: QueryClient,
  queryKey: QueryKey,
  updater: (prev: T | undefined) => T | undefined,
): void {
  const state = qc.getQueryState(queryKey);
  qc.setQueryData<T>(queryKey, updater, { updatedAt: state?.dataUpdatedAt ?? 0 });
  if (state?.isInvalidated) void qc.invalidateQueries({ queryKey, exact: true, refetchType: "none" });
}
