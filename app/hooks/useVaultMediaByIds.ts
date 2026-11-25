"use client";


import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";

import { relay, type VaultMedia } from "@/lib/relay";

const MAX_IN_FLIGHT = 6;
// Client brake only: useQueries has no concurrency limit and Next rewrites /api/of/* server-side; the server cap is the safety boundary.
let inFlight = 0;
const waiting: Array<() => void> = [];

function release(): void {
  // Hand the slot over instead of decrementing, or a caller arriving in between would see a free slot already spoken for.
  const next = waiting.shift();
  if (next) next();
  else inFlight -= 1;
}

async function withSlot<T>(run: () => Promise<T>): Promise<T> {
  if (inFlight >= MAX_IN_FLIGHT) {
    await new Promise<void>((resolve) => waiting.push(resolve));
  } else {
    inFlight += 1;
  }
  try {
    return await run();
  } finally {
    release();
  }
}

export function useVaultMediaByIds(
  accountId: string | null,
  ids: number[],
): Record<number, VaultMedia> {
  const uniqueIds = useMemo(
    () => Array.from(new Set(ids.filter((n) => typeof n === "number" && n > 0))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [accountId, ids.join(",")],
  );

  const queries = useQueries({
    queries: uniqueIds.map((id) => ({
      queryKey: ["vault-media-by-id", accountId, id] as const,
      enabled: !!accountId,
      queryFn: () =>
        withSlot(() =>
          relay.get<VaultMedia>(`/api/of/v2/vault/media/${id}`, { accountId: accountId ?? undefined }),
        ),
      // Vault items rarely change; mirror useVaultMedia.
      staleTime: 3 * 24 * 60 * 60_000,
      gcTime: 3 * 24 * 60 * 60_000,
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: false,
    })),
  });

  const updatedKey = queries.map((q) => q.dataUpdatedAt).join("|");
  return useMemo(() => {
    const out: Record<number, VaultMedia> = {};
    queries.forEach((q, i) => {
      const id = uniqueIds[i];
      const m = q.data;
      if (id && m && typeof m.id === "number") out[id] = m;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updatedKey, uniqueIds]);
}
