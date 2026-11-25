"use client";


import { useQuery } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";

export const ROUTES = ["chat", "sext", "sell_now", "tease", "make_right", "ai_dare", "no_send"] as const;
export type Route = (typeof ROUTES)[number];

export const ROUTE_LABEL: Record<Route, string> = {
  chat: "Chat", sext: "Sext", sell_now: "Sell now", tease: "Tease",
  make_right: "Make right", ai_dare: "AI dare", no_send: "No send",
};

export interface FullAiRow {
  id: number;
  created_at: string;
  fan_id: string;
  fan_name: string | null;
  route: Route;
  heat: number;
  row: string;
  jev_ms: number | null;
  jev_failed: boolean;
  test?: boolean;
  live?: boolean;
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
