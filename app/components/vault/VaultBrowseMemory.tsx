"use client";

/** Each model's grid view (folder, type, search, select mode, ticks) for the page's lifetime: VaultProPage mounts
 *  `VaultBrowseMemory` above its per-model remount, so switching model and back finds it as it was
 *  (`browseMapReducer`). With no provider (a panel rendered alone) the view is the panel's own. */

import { createContext, useCallback, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from "react";

import {
  browseFor, browseMapReducer, initialBrowseState, vaultBrowseReducer,
  type BrowseAction, type BrowseMap, type BrowseMapAction, type BrowseState,
} from "@/components/vault/vaultBrowseReducer";

const Ctx = createContext<{ map: BrowseMap; dispatch: Dispatch<BrowseMapAction> } | null>(null);

export function VaultBrowseMemory({ children }: { children: ReactNode }) {
  const [map, dispatch] = useReducer(browseMapReducer, {});
  const value = useMemo(() => ({ map, dispatch }), [map]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** `accountId`'s browse state and its dispatch: the page's memory when mounted, else local. */
export function useVaultBrowse(accountId: string): [BrowseState, (a: BrowseAction) => void] {
  const mem = useContext(Ctx);
  const [local, dispatchLocal] = useReducer(vaultBrowseReducer, initialBrowseState);
  const memDispatch = mem?.dispatch;
  const dispatch = useCallback((action: BrowseAction) => {
    if (memDispatch) memDispatch({ accountId, action });
    else dispatchLocal(action);
  }, [memDispatch, accountId]);
  return [mem ? browseFor(mem.map, accountId) : local, dispatch];
}
