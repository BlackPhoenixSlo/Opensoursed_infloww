"use client";

/**
 * useReferrals — `GET /admin/stats/referrals?from&to[&account_id]`, each Creator's referral earnings over whole
 * days (roadmap 1.12): the Dashboard's Referrals tile and Creator reports' Referrals channel.
 *
 * No transaction carries referral earnings, so the Relay reads OnlyFans' Statements › Referrals chart, one read per
 * Creator, cached five minutes. OnlyFans buckets those days in its own time zone, not the report zone, so a day's
 * referrals can sit a few hours off the ledger's days. A Creator whose read failed is in `unavailable`. Referral
 * earnings are what OnlyFans pays the Creator, so gross and net are the same figure.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { relay, type RelayContext } from "@/lib/relay";

const BG_CTX: RelayContext = { priority: "background" };

export interface ReferralsRow { account_id: string; total_cents: number; by_day: { day: string; cents: number }[] }
export interface ReferralsResp { rows: ReferralsRow[]; unavailable: string[] }

/** `from`/`to` are YYYY-MM-DD; `accountId` one id or several comma-separated, omitted (or "__all__") for every
 *  Creator. Nothing is read until both dates are known and `enabled`. */
export function useReferrals(from: string | null, to: string | null, accountId?: string | null, enabled = true) {
  const id = accountId === "__all__" ? null : accountId ?? null;
  return useQuery<ReferralsResp>({
    queryKey: ["stats", "referrals", from, to, id],
    queryFn: () => {
      const qs = new URLSearchParams({ from: from!, to: to! });
      if (id) qs.set("account_id", id);
      return relay.get<ReferralsResp>(`/admin/stats/referrals?${qs.toString()}`, BG_CTX);
    },
    enabled: enabled && !!from && !!to,
    staleTime: 60_000,
  });
}

/** Instant `iso`'s YYYY-MM-DD in `timeZone` (the browser's when null): a window's edge as the read's whole day. */
export function dayIn(iso: string, timeZone: string | null): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: timeZone ?? undefined, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(iso));
}

/** The sum over every Creator, in cents. */
export function referralsTotal(r: ReferralsResp | undefined): number {
  return (r?.rows ?? []).reduce((a, row) => a + row.total_cents, 0);
}

/** The referrals as the revenue read's rows, kind `referral` with net equal to gross: `kind` as `group_by=kind`
 *  answers, `day` as `group_by=day&by_kind=true` does, so the reports' channel sums take them as one more kind. */
export function referralsAsRevenue(r: ReferralsResp | undefined) {
  const row = (cents: number) => ({ kind: "referral", total_cents: cents, net_cents: cents, count: 0 });
  const days = new Map<string, number>();
  for (const c of r?.rows ?? []) for (const d of c.by_day) days.set(d.day, (days.get(d.day) ?? 0) + d.cents);
  return {
    kind: { rows: r ? [{ day: null, ...row(referralsTotal(r)) }] : [] },
    day: { rows: [...days].map(([day, cents]) => ({ day, ...row(cents), kind: null, by_kind: [row(cents)] })) },
  };
}

/** A window's referrals and the window's before it (`current`/`prior`, each `[from, to]` YYYY-MM-DD), each read
 *  and as `referralsAsRevenue`'s rows. Until a read answers its rows are empty, so a sum over them is the ledger's
 *  alone and takes the referrals in when they land. */
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
