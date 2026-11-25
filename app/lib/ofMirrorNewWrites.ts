"use client";


import { useQuery } from "@tanstack/react-query";
import { relay } from "@/lib/relay";

export const OFM_WRITES_PATH = "/api/of/ofm-writes";
export const OFM_WRITES_KEY = "ofm-writes";

export async function switchOn(get: () => Promise<Record<string, unknown> | null | undefined>, field: string): Promise<boolean> {
  try {
    return (await get())?.[field] === true;
  } catch {
    return false;
  }
}

export function relaySwitchQuery(key: string, path: string, field: string, accountId?: string | null) {
  return {
    queryKey: accountId === undefined ? [key] : [key, accountId],
    queryFn: () => switchOn(() => relay.get<Record<string, unknown>>(path, accountId ? { accountId } : undefined), field),
    // A per-Creator probe is asked again each minute, so an open tab drops the controls within a minute of the owner's force-off.
    refetchInterval: accountId === undefined ? (false as const) : 60 * 1000,
  };
}

export function useRelaySwitch(key: string, path: string, field: string, enabled: boolean, accountId?: string | null): boolean {
  return (
    useQuery({
      ...relaySwitchQuery(key, path, field, accountId),
      enabled: enabled && accountId !== null,
      staleTime: 60 * 1000,
      retry: false,
    }).data === true
  );
}

export const useOfmNewWrites = (enabled: boolean, accountId: string | null): boolean =>
  useRelaySwitch(OFM_WRITES_KEY, OFM_WRITES_PATH, "on", enabled, accountId);
