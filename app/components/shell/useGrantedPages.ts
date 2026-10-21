"use client";

import { useMemo } from "react";

import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { sessionGrantedPages } from "@/lib/nav";
import type { ActionName } from "@/lib/permissionActions";

/** The pages this session may open, from the Applied settings read; null for
 *  every page. A chatter-only session gets only the My Automations pages the
 *  read's `opt_in` lists, none while it loads or fails
 *  (`sessionGrantedPages`; the Relay refuses a denied route either way). */
export function useGrantedPages(): Set<string> | null {
  const chatterOnly = useIsChatterOnly();
  const permissions = useAppliedSettings().data?.permissions;
  const pages = permissions?.pages;
  const optIn = permissions?.opt_in;
  return useMemo(() => sessionGrantedPages(chatterOnly, { pages, opt_in: optIn }), [chatterOnly, pages, optIn]);
}

/** Whether this session may perform Function permission `action` (lib/permissionActions.ts): false once the
 *  Applied settings read lists any `<page>#<action>` in `denied_actions`, the Relay's own rule (it cannot tell
 *  which page sent a request). Hides the action's control; the Relay refuses the request either way. */
export function useActionAllowed(action: ActionName): boolean {
  const denied = useAppliedSettings().data?.permissions?.denied_actions;
  return !denied?.some((key) => key.endsWith(`#${action}`));
}
