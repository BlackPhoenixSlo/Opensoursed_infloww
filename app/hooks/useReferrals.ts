"use client";


import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { relay, type RelayContext } from "@/lib/relay";

const BG_CTX: RelayContext = { priority: "background" };

export interface ReferralsRow { account_id: string; total_cents: number; by_day: { day: string; cents: number }[] }
export interface ReferralsResp { rows: ReferralsRow[]; unavailable: string[] }

export type ReferralsQuery = Omit<UseQueryResult<ReferralsResp>, "data"> & { data: ReferralsResp | undefined };

export function useReferrals(
  from: string | null, to: string | null, accountId?: string | null, enabled = true,
): ReferralsQuery {
  const id = accountId === "__all__" ? null : accountId ?? null;
  const q = useQuery<ReferralsResp>({
    queryKey: ["stats", "referrals", from, to, id],
    queryFn: () => {
      const qs = new URLSearchParams({ from: from!, to: to! });
      if (id) qs.set("account_id", id);
      return relay.get<ReferralsResp>(`/admin/stats/referrals?${qs.toString()}`, BG_CTX);
    },
    enabled: enabled && !!from && !!to,
    staleTime: 60_000,
  });
  return q.isError ? { ...q, data: undefined } : q;
}

export function dayIn(iso: string, timeZone: string | null): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: timeZone ?? undefined, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(iso));
}

export type ReferralsGap = "none" | "some" | "all";
export function referralsGap(q: { isError: boolean; data?: ReferralsResp }): ReferralsGap {
  if (q.isError) return "all";
  if (!q.data?.unavailable?.length) return "none";
  return (q.data.rows ?? []).length === 0 ? "all" : "some";
}

export const referralsShown = (q: { isLoading: boolean; isError: boolean; data?: ReferralsResp }): boolean =>
  !q.isLoading && referralsGap(q) !== "all";

export function referralsTotal(r: ReferralsResp | undefined): number {
  return (r?.rows ?? []).reduce((a, row) => a + row.total_cents, 0);
}

// Referral earnings are OF's payout, so net == gross; OF buckets days in its own zone, hours off the ledger's.
export function referralsAsRevenue(r: ReferralsResp | undefined) {
  const row = (cents: number) => ({ kind: "referral", total_cents: cents, net_cents: cents, count: 0 });
  const days = new Map<string, number>();
  for (const c of r?.rows ?? []) for (const d of c.by_day) days.set(d.day, (days.get(d.day) ?? 0) + d.cents);
  return {
    kind: { rows: r ? [{ day: null, ...row(referralsTotal(r)) }] : [] },
    day: { rows: [...days].map(([day, cents]) => ({ day, ...row(cents), kind: null, by_kind: [row(cents)] })) },
  };
}

export function useReferralRevenue(
  current: [string | null, string | null], prior: [string | null, string | null],
  accountId: string | null | undefined, enabled: boolean,
) {
  const now = useReferrals(current[0], current[1], accountId, enabled);
  const before = useReferrals(prior[0], prior[1], accountId, enabled);
  const rev = useMemo(() => referralsAsRevenue(now.data), [now.data]);
  const priorRev = useMemo(() => referralsAsRevenue(before.data), [before.data]);
  return { now, before, rev, priorRev };
}
