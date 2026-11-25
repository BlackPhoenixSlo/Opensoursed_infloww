"use client";

import { useMemo } from "react";

import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { sessionGrantedPages } from "@/lib/nav";
import type { ActionName } from "@/lib/permissionActions";

export function useGrantedPages(): Set<string> | null {
  const chatterOnly = useIsChatterOnly();
  const permissions = useAppliedSettings().data?.permissions;
  const pages = permissions?.pages;
  const optIn = permissions?.opt_in;
  return useMemo(() => sessionGrantedPages(chatterOnly, { pages, opt_in: optIn }), [chatterOnly, pages, optIn]);
}

export function useActionAllowed(action: ActionName): boolean {
  const denied = useAppliedSettings().data?.permissions?.denied_actions;
  // The Relay cannot tell which page sent a request, so any <page>#<action> denies it.
  return !denied?.some((key) => key.endsWith(`#${action}`));
}
