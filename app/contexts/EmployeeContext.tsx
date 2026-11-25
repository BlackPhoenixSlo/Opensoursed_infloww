"use client";


import { createContext, useContext, useMemo } from "react";

import { useOptionalUser } from "@/contexts/UserContext";
import { useRoster } from "@/hooks/useRoster";
import type { Employee } from "@/lib/relay";

const EMPTY_ROSTER: Employee[] = [];

interface EmployeeContextValue {
  current: Employee | null;
  roster: Employee[];
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
