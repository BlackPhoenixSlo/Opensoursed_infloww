/**
 * The part of the Creators page's connectivity mapping (spec phase-04, Implementation Decisions, Connectivity
 * mapping; creators-manage#23, #40) that the accounts read alone settles, before any live probe. Shared by the
 * Creators table (AccountsTable `connectivity`, which adds the probe's answer) and the per-model KPI cards (which
 * read OnlyFans only for a Creator this leaves `null`), so the two never disagree on a label or its colour.
 */
import type { AccountMeta } from "@/lib/relay";

/** A connectivity verdict: the capture's label, a tooltip, and its colour. */
export interface Connectivity {
  label: string;
  title?: string;
  tone: "ok" | "err" | "muted";
  /** A flagged dead session: the Creators table adds its repair badge. */
  dead?: boolean;
}

/**
 * The verdict from the account row alone, or `null` for a live session (the relay probes it; OF may be read).
 * A flagged session OUTRANKS has_session: it pauses every automation for the account (service/account_health.py),
 * so a parked account never reads "Connected". A deactivated Creator is not probed (`_health_all_accounts`) and
 * nothing reads OF for it; its row carries the Deactivated chip, so the label is "—".
 */
export function sessionConnectivity(a: Pick<AccountMeta, "session_dead_at" | "has_session" | "is_active">): Connectivity | null {
  if (a.session_dead_at) return { label: "Disconnected", tone: "err", dead: true };
  if (!a.has_session) return { label: "Not connected", tone: "muted" };
  if (!a.is_active) return { label: "—", title: "deactivated: not probed", tone: "muted" };
  return null;
}
