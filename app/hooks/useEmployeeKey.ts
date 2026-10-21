"use client";

/**
 * useEmployeeKey — the key that per-Employee browser storage is filed under
 * (docs/spec/phase-01-window-chrome-tabs.md, Contracts: `employeeKey`). The
 * Creator tabs store uses it, and the Fan tabs store is meant to reuse it, so
 * the rule lives here once:
 * - the session's own Employee row (`useEmployee().current`: the owner's
 *   row for an Owner session);
 * - else the signed-in principal (`usePrincipalId`, the rule the roster
 *   counts cache key uses too): the user id, then the chatter id, else
 *   "anon".
 * It is `null` until the Employee and the principal have resolved (the
 * owner's roster still loading, or a principal still loading). A store
 * reads and writes nothing under `null`, so state seen during sign-in is
 * never saved under "anon". An Employee login has no roster, so their key
 * is their chatter id.
 */

import { useChatter, useOptionalChatter } from "@/contexts/ChatterContext";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useOptionalUser, useUser } from "@/contexts/UserContext";

/** The signed-in principal's id: the user id, then the chatter id, else
 *  "anon". */
export function usePrincipalId(): string {
  const user = useOptionalUser()?.user;
  const chatter = useOptionalChatter()?.chatter;
  return user?.user_id ?? chatter?.chatter_id ?? "anon";
}

export function useEmployeeKey(): string | null {
  const { current, hydrated } = useEmployee();
  const { loading: userLoading } = useUser();
  const { loading: chatterLoading } = useChatter();
  const principalId = usePrincipalId();

  if (!hydrated || userLoading || chatterLoading) return null;
  if (current !== null) return String(current.id);
  return principalId;
}
