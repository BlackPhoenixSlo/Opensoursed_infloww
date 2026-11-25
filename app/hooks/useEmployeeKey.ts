"use client";


import { useChatter, useOptionalChatter } from "@/contexts/ChatterContext";
import { useEmployee } from "@/contexts/EmployeeContext";
import { useOptionalUser, useUser } from "@/contexts/UserContext";

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

  // null until resolved: a store writes nothing under null, so sign-in state is never saved under "anon".
  if (!hydrated || userLoading || chatterLoading) return null;
  if (current !== null) return String(current.id);
  return principalId;
}
