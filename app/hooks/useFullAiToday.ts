"use client";

/**
 * useFullAiToday — one Creator's Shadow and Test chat Decision rows of today (GET /admin/full-ai/today,
 * service/full_ai_api.py): counts per Route, Jev failures, and the 50 newest rows. A finished `full_ai_chat` run
 * (`rule_run_finished`, useAccountStateEvents) or a Test chat Turn (useFullAiTestChat) refetches it; the poll is the
 * safety net, 30 s while SSE is down.
 */

import { useQuery } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";

/** The Routes in the Route table's order (service/automations/full_ai_decide.py `Route`). */
export const ROUTES = ["chat", "sext", "sell_now", "tease", "make_right", "ai_dare", "no_send"] as const;
export type Route = (typeof ROUTES)[number];

export interface FullAiRow {
  id: number;
  created_at: string;
  fan_id: string;
  fan_name: string | null;
  route: Route;
  heat: number;
  /** The Route table row that matched. */
  row: string;
  jev_ms: number | null;
  jev_failed: boolean;
  /** A Test chat Turn (no Fan: the page shows "Test chat"). */
  test?: boolean;
}

export interface FullAiToday {
  since: string;
  counts: Record<Route, number>;
  jev_failed: number;
  rows: FullAiRow[];
}

export const fullAiTodayKey = (accountId: string) => ["full-ai-today", accountId] as const;

export function useFullAiToday(accountId: string) {
  return useQuery<FullAiToday>({
    queryKey: fullAiTodayKey(accountId),
    queryFn: () => relay.get<FullAiToday>(
      `/admin/full-ai/today?account_id=${encodeURIComponent(accountId)}`,
      { accountId, priority: "background" },
    ),
    staleTime: 15_000,
    refetchInterval: ssePoll(5 * 60_000, 30_000),
    refetchOnWindowFocus: true,
  });
}
