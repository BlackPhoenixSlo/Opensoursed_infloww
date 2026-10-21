"use client";

/**
 * useAutoFollowList — the Auto-follow list's reads and its switch (Infloww's
 * Growth → Auto-follow). Stats and records come from
 * `service/auto_follow_api.py`; the switch is the account's `auto_follow` rule,
 * flipped through `/admin/automation-rules/switch` (a rule it creates follows
 * OF's recently-expired list, money gate on).
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const STATS = "auto-follow-stats";
const RECORDS = "auto-follow-records";
const BG_CTX: RelayContext = { priority: "background" };

export interface AutoFollowStatsRow {
  account_id: string;
  on: boolean;
  total: number;
  today: number;
  yesterday: number;
  d7: number;
  d30: number;
  last_followed_at: string | null;
}

export interface AutoFollowRecord {
  fan_id: number;
  name: string | null;
  username: string | null;
  avatar_url: string | null;
  total_spend_cents: number;
  expires_at: string | null;
  followed_at: string;
  follow_count: number;
}

export type RecordSort = "followed_at" | "spend" | "expiry";

export interface RecordQuery {
  sort: RecordSort;
  order: "asc" | "desc";
  start: string | null;
  end: string | null;
  limit: number;
  offset: number;
}

function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function useAutoFollowStats() {
  return useQuery<{ rows: AutoFollowStatsRow[] }>({
    queryKey: [STATS],
    queryFn: () =>
      relay.get<{ rows: AutoFollowStatsRow[] }>(`/admin/auto-follow/stats?tz=${encodeURIComponent(browserTz())}`, BG_CTX),
    refetchOnWindowFocus: false,
  });
}

export function useAutoFollowRecords(accountId: string | null, q: RecordQuery) {
  return useQuery<{ total: number; rows: AutoFollowRecord[] }>({
    queryKey: [RECORDS, accountId, q],
    enabled: !!accountId,
    placeholderData: keepPreviousData,
    queryFn: () => {
      const p = new URLSearchParams({
        account_id: accountId!, sort: q.sort, order: q.order,
        limit: String(q.limit), offset: String(q.offset),
      });
      if (q.start) p.set("start", q.start);
      if (q.end) p.set("end", q.end);
      return relay.get<{ total: number; rows: AutoFollowRecord[] }>(`/admin/auto-follow/records?${p.toString()}`, BG_CTX);
    },
    refetchOnWindowFocus: false,
  });
}

export function useAutoFollowSwitch() {
  const qc = useQueryClient();
  return useMutation<{ action: string }, Error, { accountId: string; enable: boolean }>({
    mutationFn: ({ accountId, enable }) =>
      relay.post<{ action: string }>("/admin/automation-rules/switch",
        { account_id: accountId, kind: "auto_follow", enable }),
    onSuccess: (_r, { accountId }) => {
      qc.invalidateQueries({ queryKey: [STATS] });
      qc.invalidateQueries({ queryKey: ["automation-rules", accountId] });
    },
  });
}
