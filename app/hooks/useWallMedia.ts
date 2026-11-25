"use client";


import { useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { perfDelivered, perfError, perfLog, perfOpId } from "@/lib/perfLog";

interface WallMediaResp {
  media_ids: number[];
  media_prices?: Record<string, number>;
  scanned_posts: number;
  new_media_count?: number;
  has_more: boolean;
  fully_backfilled?: boolean;
  mode?: "first" | "backfill" | "refresh";
  last_scan_at?: string | null;
  newest_post_published_at?: string | null;
  oldest_post_published_at?: string | null;
}

export function useWallMedia(accountId: string | null, enabled = true) {
  const qc = useQueryClient();
  const queryKey = useMemo(() => ["wall-media", accountId] as const, [accountId]);

  const q = useQuery<WallMediaResp>({
    queryKey,
    enabled: enabled && !!accountId,
    queryFn: async ({ signal }) => {
      const qs = new URLSearchParams({ account_id: accountId! });
      // force re-walks from the top: the only path that re-prices media recorded at price 0; one-shot so auto refetches stay incremental.
      if (forceRef.current) {
        qs.set("force", "true");
        forceRef.current = false;
      }
      const opId = perfOpId("wall.media");
      perfLog(opId, "wall.media", "requested", { accountId });
      try {
        const r = await relay.get<WallMediaResp>(
          `/admin/vault/wall-media?${qs.toString()}`,
          { priority: "background" },
          signal,
        );
        perfDelivered(opId, "wall.media", {
          count: r.media_ids.length,
          new: r.new_media_count ?? 0,
          mode: r.mode,
          hasMore: r.has_more,
          backfilled: r.fully_backfilled,
        });
        return r;
      } catch (err) {
        perfError(opId, "wall.media", { message: (err as Error)?.message });
        throw err;
      }
    },
    staleTime: 7 * 24 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const backfillsRef = useRef(0);
  const forceRef = useRef(false);
  // Bounds rate-budget use for accounts with thousands of posts; resumes next session.
  const MAX_AUTO_BACKFILLS = 4;
  useEffect(() => {
    if (!enabled || !accountId) return;
    if (!q.data?.has_more) return;
    if (q.isFetching) return;
    if (backfillsRef.current >= MAX_AUTO_BACKFILLS) return;
    backfillsRef.current += 1;
    const t = setTimeout(() => {
      qc.invalidateQueries({ queryKey });
    }, 1500);
    return () => clearTimeout(t);
  }, [enabled, accountId, q.data?.has_more, q.isFetching, qc, queryKey]);

  useEffect(() => {
    backfillsRef.current = 0;
  }, [accountId]);

  const set = useMemo(
    () => new Set<number>(q.data?.media_ids ?? []),
    [q.data?.media_ids],
  );

  const priceById = useMemo(() => {
    const m = new Map<number, number>();
    const raw = q.data?.media_prices;
    if (raw) {
      for (const [k, v] of Object.entries(raw)) {
        const id = Number(k);
        const cents = Number(v);
        if (Number.isFinite(id) && Number.isFinite(cents) && cents > 0) {
          m.set(id, cents);
        }
      }
    }
    return m;
  }, [q.data?.media_prices]);

  const refresh = () => {
    backfillsRef.current = 0;
    forceRef.current = true;
    return q.refetch();
  };

  return {
    set,
    priceById,
    scanned: q.data?.scanned_posts ?? 0,
    hasMore: !!q.data?.has_more,
    fullyBackfilled: !!q.data?.fully_backfilled,
    lastScanAt: q.data?.last_scan_at ?? null,
    isLoading: q.isLoading,
    isFetching: q.isFetching,
    refresh,
  };
}
