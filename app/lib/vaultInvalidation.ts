import type { InvalidateOptions, InvalidateQueryFilters, Query, QueryClient } from "@tanstack/react-query";

export const vaultReadOwners = new WeakMap<Query, symbol>();

export function invalidateVaultQueries(
  qc: QueryClient, filters?: InvalidateQueryFilters, options?: InvalidateOptions,
): Promise<void> {
  for (const query of qc.getQueryCache().findAll(filters)) vaultReadOwners.delete(query);
  return qc.invalidateQueries(filters, options);
}
