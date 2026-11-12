import type { InvalidateOptions, InvalidateQueryFilters, Query, QueryClient } from "@tanstack/react-query";

export const vaultReadOwners = new WeakMap<Query, symbol>();

/** Every invalidation intent supersedes matching vault sidecars, even when the
 * query is already stale and TanStack emits no second invalidate event. Keep
 * TanStack's filters/refetch policy: revoking ownership adds no network reads. */
export function invalidateVaultQueries(
  qc: QueryClient, filters?: InvalidateQueryFilters, options?: InvalidateOptions,
): Promise<void> {
  for (const query of qc.getQueryCache().findAll(filters)) vaultReadOwners.delete(query);
  return qc.invalidateQueries(filters, options);
}
