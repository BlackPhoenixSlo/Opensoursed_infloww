"use client";


import { createContext, useCallback, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from "react";

import {
  browseFor, browseMapReducer, type BrowseAction, type BrowseMap, type BrowseMapAction, type BrowseState,
} from "@/components/vault/vaultBrowseReducer";

const Ctx = createContext<{ map: BrowseMap; dispatch: Dispatch<BrowseMapAction> } | null>(null);

export function VaultBrowseMemory({ children }: { children: ReactNode }) {
  const [map, dispatch] = useReducer(browseMapReducer, {});
  const value = useMemo(() => ({ map, dispatch }), [map]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useVaultBrowse(accountId: string): [BrowseState, (a: BrowseAction) => void] {
  const mem = useContext(Ctx);
  if (!mem) throw new Error("useVaultBrowse: no VaultBrowseMemory above this component");
  const memDispatch = mem.dispatch;
  const dispatch = useCallback((action: BrowseAction) => memDispatch({ accountId, action }), [memDispatch, accountId]);
  return [browseFor(mem.map, accountId), dispatch];
}
