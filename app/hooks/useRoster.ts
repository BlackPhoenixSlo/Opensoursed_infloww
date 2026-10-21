"use client";

/**
 * useRoster — the owner's employee roster, shared across the settings tabs
 * (Employees / Transfer / Audit).
 *
 * Backend: GET /admin/employees. The signed-in user only ever sees their
 * own roster (employees.py filters by user_id). `include_disabled=true`
 * (the default) also returns soft-disabled rows so tables can render them
 * strikethrough; pass `includeDisabled: false` to drop them.
 *
 * All three tabs previously inlined this same query under the SAME cache
 * key (`["employees", "all"]`) but with INCONSISTENT staleTime — whichever
 * tab mounted first won. Converging on ONE hook (and one staleTime) fixes
 * that; mutations elsewhere still invalidate `["employees"]`. EmployeeContext
 * (who the session acts as) is the fourth consumer and used to inline a
 * copy of its own with `staleTime: 0` — the same divergence, one screen up.
 *
 * `rows` is the Employees: the rows with their own login (`chatter_id` set),
 * which are what Manage employees, Role Settings and Security list. Pass
 * `includeChatterMirrors: true` for every row (the owner's own row and the
 * retired name-only rows too) — the audit log needs the full set so any
 * attributed row still resolves a name.
 *
 * The endpoint 403s without a session, so the hook owns the auth coupling
 * rather than making each caller remember an `enabled` flag: it waits for
 * /auth/me and reports that window through `pending`.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { relay, RelayError, type Employee } from "@/lib/relay";

export interface EmployeesResp { employees: Employee[]; }

export interface UseRosterOptions {
  /** Include soft-disabled rows (default true). */
  includeDisabled?: boolean;
  /** Every row in `rows`, the owner's own and the name-only rows too (default false). */
  includeChatterMirrors?: boolean;
}

export function useRoster(opts: UseRosterOptions = {}) {
  const { includeDisabled = true, includeChatterMirrors = false } = opts;
  const { user, loading: userLoading } = useUser();

  const query = useQuery<EmployeesResp>({
    // The variant belongs in the key: a `false` caller sharing the `all`
    // entry would silently truncate every other consumer's roster
    // (MessagesFilters is the active-only consumer).
    queryKey: ["employees", includeDisabled ? "all" : "active"],
    queryFn: () =>
      relay.get<EmployeesResp>(
        `/admin/employees?include_disabled=${includeDisabled ? "true" : "false"}`,
      ),
    enabled: !!user,
    staleTime: 10_000,
    // Who the session acts as hangs on it, so a transient relay hiccup is worth
    // a second attempt — but a 401/403 (expired session, chatter principal)
    // never becomes a 200 by asking again.
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

  // "Still on its way", including the window before /auth/me resolves — when
  // the query is disabled and therefore NOT `isLoading` (that's isPending &&
  // isFetching). Gate load-state UI on this, never on query.isLoading:
  // testing isLoading is what once flashed a full-screen gate over every popout.
  const pending = userLoading || query.isPending;

  return { query, rows, pending };
}
