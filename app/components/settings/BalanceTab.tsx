"use client";

/**
 * Your Balance (docs/spec/settings-tabs/phase-05-billing-balance-about.md): the selected Creator's Referral
 * balance (Infloww's 360px centred amount block for the first figure, a row of the other three under it) and
 * its referral payouts as the Transaction history, read from the Relay's existing routes with `X-Account-Id`
 * as the OF mirror does (ofMirrorData.ts). The Creator is picked in the panel header (the top bar has no model
 * filter): the one in scope when it opens, else the first session-backed Creator. Both queries are keyed by
 * the account id and enabled only when one is set, so with no Creator nothing is sent and a switch never
 * shows the previous Creator's figures. A missing or non-numeric amount shows "—", never 0.
 * The Panel stores nothing (ADR-0008).
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { fmtCents, fmtPrice } from "@/lib/format";
import { relay } from "@/lib/relay";
import type { Payout } from "@/lib/ofMirrorFeeds";
import { LoadError, SettingsPanel, SettingsTable, TABLE_CELL, TABLE_ROW } from "@/components/settings/SettingsPanel";
import { EmptyState, IfCreatorSelect } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

const BALANCE = "/api/of/v2/payments/referrals/balance";
const PAYOUTS = "/api/of/v2/payouts/requests/referral?limit=10";
/** Card label → the balance key it shows (the spec's card map). */
const CARDS = [
  ["Total earnings", "referralEarnings"],
  ["Available to withdraw", "availableEarnings"],
  ["Pending earnings", "pendingEarnings"],
  ["Withdrawn", "withdrawnEarnings"],
] as const;
const COLUMNS = ["Date", "Amount", "Status"];

/** A payout state's colour, Infloww's history statuses: pending #3467ff, success #2ad4ac, failure #ff7c71,
 *  complete #666. The cell still shows OF's raw state; an unknown one stays T1. */
const STATE_COLOUR: Record<string, string> = {
  new: "text-[#3467ff]",
  pending: "text-[#3467ff]",
  approved: "text-[#2ad4ac]",
  rejected: "text-[#ff7c71]",
  done: "text-[#666666]",
};

/** A dollar balance in whole dollars, as on the dashboard; anything that is not a finite number is "—". */
function usd(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? fmtCents(Math.round(v * 100)) : "—";
}

/** One payout: its real cents, never rounded ("$123.45", "$100"). */
function payoutUsd(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? fmtPrice(Math.round(v * 100)) : "—";
}

function day(iso: string | undefined): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : "—";
}

const [FIRST, ...REST] = CARDS;
/** A figure's label: 14 / 500 T2. */
const LABEL = "text-[length:var(--if-fs)] font-[var(--if-fw-title)] text-[var(--if-fg-2)]";

export default function BalanceTab() {
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked ?? scoped ?? accounts[0]?.id ?? null;
  const picker = accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />;
  const q = <T,>(path: string) => ({
    queryKey: ["settings-balance", accountId, path],
    queryFn: () => relay.get<T>(path, { accountId }),
    enabled: !!accountId,
    staleTime: 60_000,
    retry: false,
  });
  const balance = useQuery(q<Record<string, unknown>>(BALANCE));
  const payouts = useQuery(q<{ list?: Payout[] }>(PAYOUTS));

  if (!accountId) {
    return (
      <SettingsPanel title="Your Balance" actions={picker}>
        <EmptyState kind="data" text="Select a creator to see its balance" className="h-[260px]" />
      </SettingsPanel>
    );
  }

  // Only an array is a payout list: a 200 without one reads as "—", like a failure, never "No payouts".
  const rows = Array.isArray(payouts.data?.list) ? payouts.data.list : null;
  return (
    <SettingsPanel title="Your Balance" actions={picker}>
      <section className="mb-[var(--if-section-gap)]">
        <dl className="text-center">
          {/* Infloww's amount block: 360px on B-nav, centred, 20px margins. */}
          <div className="mx-auto w-[360px] max-w-full py-5 bg-[var(--if-bg)]">
            <dt className={LABEL}>{FIRST[0]}</dt>
            <dd className="mt-5 text-[32px] font-semibold text-[var(--if-fg-0)]">{usd(balance.data?.[FIRST[1]])}</dd>
          </div>
          {/* Ours: OF's referral balance has three more figures, a row under the block. */}
          <div className="mx-auto max-w-[760px] grid grid-cols-1 gap-4 sm:grid-cols-3">
            {REST.map(([label, key]) => (
              <div key={key}>
                <dt className={LABEL}>{label}</dt>
                <dd className="mt-2 text-[20px] font-semibold text-[var(--if-fg-0)]">{usd(balance.data?.[key])}</dd>
              </div>
            ))}
          </div>
        </dl>
        <LoadError error={balance.error} />
      </section>
      <section>
        <h3 className="mb-4 text-[length:var(--if-fs-lg)] font-semibold text-[var(--if-fg)]">Transaction history</h3>
        <LoadError error={payouts.error} />
        <SettingsTable columns={COLUMNS}>
          {rows?.length ? (
            rows.map((p, i) => (
              <tr key={i} className={TABLE_ROW}>
                <td className={TABLE_CELL}>{day(p.createdAt)}</td>
                <td className={TABLE_CELL}>{payoutUsd(p.amount)}</td>
                <td className={cn(TABLE_CELL, p.state && STATE_COLOUR[p.state])}>{p.state ?? "—"}</td>
              </tr>
            ))
          ) : (
            <tr className={TABLE_ROW}>
              <td colSpan={COLUMNS.length} className={cn(TABLE_CELL, "text-[var(--if-fg-3)]")}>
                {rows ? <EmptyState kind="data" size="sm" text="No payouts" className="h-[260px]" /> : "—"}
              </td>
            </tr>
          )}
        </SettingsTable>
      </section>
    </SettingsPanel>
  );
}
