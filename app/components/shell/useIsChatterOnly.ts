"use client";

import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { isChatterOnly } from "@/lib/session";

export function useIsChatterOnly(): boolean {
  const { user } = useUser();
  const { chatter } = useChatter();
  return isChatterOnly(user, chatter);
}
