"use client";

/**
 * EmployeeContext — who the session acts as, from the session alone.
 *
 * There is no "Who's chatting?" pick any more: an Owner session is the owner
 * (the Agency's Owner row, `kind: "owner"` on /admin/employees — the relay
 * credits every owner send, flag and unsend to it without a header), and an
 * Employee signs in with their own login (the relay resolves their row from
 * the chatter session; the roster is owner-only, so `current` stays null
 * there).
 *
 * `current.id` still rides as `X-Employee-Id` on writes so an owner's
 * optimistic "Sent by …" label and the per-Employee browser storage
 * (useEmployeeKey) read the same row the relay records.
 *
 * `roster` is every row, owner, logins and the retired name-only rows
 * included — attribution flows (orphan tips, audit) resolve a name for any
 * id the history carries.
 */

import { createContext, useContext, useMemo } from "react";

import { useOptionalUser } from "@/contexts/UserContext";
import { useRoster } from "@/hooks/useRoster";
import type { Employee } from "@/lib/relay";

/** Stable identity for the "no roster yet" case so `current`'s memo and
 *  every consumer's deps don't churn on each render. */
const EMPTY_ROSTER: Employee[] = [];

interface EmployeeContextValue {
  /** The row this session acts as: the owner's own row for an Owner session,
   *  null for an Employee login (the relay resolves theirs) and until the
   *  roster lands. */
  current: Employee | null;
  /** Full roster, disabled rows included. */
  roster: Employee[];
  /** True once `current` is final: the roster has settled for an owner, at
   *  once otherwise. Per-Employee storage waits on it. */
  hydrated: boolean;
}

const EmployeeContext = createContext<EmployeeContextValue | null>(null);

export function EmployeeProvider({ children }: { children: React.ReactNode }) {
  const user = useOptionalUser()?.user ?? null;
  const { query, pending } = useRoster({ includeChatterMirrors: true });
  const roster = query.data?.employees ?? EMPTY_ROSTER;
  const userId = user?.user_id ?? null;

  const current = useMemo(() => {
    if (!userId) return null;
    return roster.find((e) => e.kind === "owner" && e.user_id === userId) ?? null;
  }, [roster, userId]);

  const hydrated = !userId || !pending;

  return (
    <EmployeeContext.Provider value={{ current, roster, hydrated }}>
      {children}
    </EmployeeContext.Provider>
  );
}

export function useEmployee(): EmployeeContextValue {
  const ctx = useContext(EmployeeContext);
  if (!ctx) throw new Error("useEmployee must be used inside <EmployeeProvider>");
  return ctx;
}
