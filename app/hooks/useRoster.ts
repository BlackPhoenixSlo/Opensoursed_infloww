"use client";


import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { relay, RelayError, type Employee } from "@/lib/relay";

export interface EmployeesResp { employees: Employee[]; }

export interface UseRosterOptions {
  includeDisabled?: boolean;
  includeChatterMirrors?: boolean;
}

export function useRoster(opts: UseRosterOptions = {}) {
  const { includeDisabled = true, includeChatterMirrors = false } = opts;
  const { user, loading: userLoading } = useUser();

  const query = useQuery<EmployeesResp>({
    // Variant in the key: a `false` caller sharing the `all` entry would truncate every other consumer's roster.
    queryKey: ["employees", includeDisabled ? "all" : "active"],
    queryFn: () =>
      relay.get<EmployeesResp>(
        `/admin/employees?include_disabled=${includeDisabled ? "true" : "false"}`,
      ),
    enabled: !!user,
    staleTime: 10_000,
    retry: (failureCount, err) => {
      if (failureCount >= 2) return false;
      const status = err instanceof RelayError ? err.status : 0;
      return status === 0 || status >= 500;
    },
    retryDelay: (attempt) => Math.min(800 * 2 ** attempt, 3000),
  });

  const rows = useMemo(() => {
    const all = query.data?.employees ?? [];
    if (includeChatterMirrors) return all;
    return all.filter((e) => !!e.chatter_id);
  }, [query.data?.employees, includeChatterMirrors]);

  // Gate load UI on this, not query.isLoading: a disabled query is not loading, and that once flashed a full-screen gate over popouts.
  const pending = userLoading || query.isPending;

  return { query, rows, pending };
}
