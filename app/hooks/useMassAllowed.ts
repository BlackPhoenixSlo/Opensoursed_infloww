"use client";

import { useAccountPlatform } from "@/hooks/useCan";
import { can, usePlatform } from "@/lib/platform";

export function useMassAllowed(accountId: string | null | undefined): boolean {
  const sidebar = usePlatform();
  return can(useAccountPlatform(accountId) ?? sidebar, "mass_message");
}
