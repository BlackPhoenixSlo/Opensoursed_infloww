/**
 * unconfirmedSendsReducer — pure state for the Auto Funnel "May not have sent" list
 * (UnconfirmedSends.tsx, data via hooks/useUnconfirmedSends).
 *
 * A funnel / follow-up step whose send was interrupted is marked and never
 * auto-resent (at-most-once); the relay lists it on
 * GET /admin/unconfirmed-sends and the user retries it. Per row:
 *   • UNCONFIRMED → "May not have sent" + Retry; IN_FLIGHT → "Sending", no Retry.
 *   • Retry is per row and non-blocking (`pending` on that row only).
 *   • Retry 200 (`retried` / `already_sent`) or 404 (gone) → drop + refetch;
 *     409 → the row is IN_FLIGHT ("Sending") + refetch; any other error → row error
 *     text, Retry enabled again.
 * The rows are react-query's (the server truth); this holds only each row's
 * local Retry overlay (`pending` / `error`), and `settleRows` is a Retry's
 * answer applied to the cached rows until the refetch.
 */

export type UnconfirmedKind = "funnel" | "followup";
export type UnconfirmedState = "UNCONFIRMED" | "IN_FLIGHT";

/** One row of GET /admin/unconfirmed-sends. */
export interface UnconfirmedRow {
  kind: UnconfirmedKind;
  fan_id: string;
  mass_run_id: number | null;
  step: number;
  step_label: string;
  since: string;
  last_error: string | null;
  state: UnconfirmedState;
}

export interface UnconfirmedView extends UnconfirmedRow {
  key: string;
  pending: boolean;
  error: string | null;
}

export interface RowOverlay {
  pending: boolean;
  error: string | null;
}

/** rowKey → that row's local Retry state. */
export type Overlay = Record<string, RowOverlay>;

/** What a Retry POST came back with: an HTTP status (200 for a body) + error text. */
export interface RetryResult {
  status: number;
  message?: string;
}

export type Action =
  | { type: "retryStart"; key: string }
  | { type: "retryDone"; key: string; result: RetryResult };

export const initialOverlay: Overlay = {};

export function rowKey(r: Pick<UnconfirmedRow, "kind" | "fan_id" | "mass_run_id">): string {
  return `${r.kind}:${r.fan_id}:${r.mass_run_id ?? ""}`;
}

export type RetryOutcome = "drop" | "sending" | "error";

export function retryOutcome(status: number): RetryOutcome {
  if ((status >= 200 && status < 300) || status === 404) return "drop";
  if (status === 409) return "sending";
  return "error";
}

/** Retry is shown for UNCONFIRMED rows and enabled unless one is in flight. */
export function canRetry(r: UnconfirmedView): boolean {
  return r.state === "UNCONFIRMED" && !r.pending;
}

/** The POST body for a row's Retry (`mass_run_id` only when set). */
export function buildRetryPayload(r: UnconfirmedRow): { kind: UnconfirmedKind; fan_id: string; mass_run_id?: number } {
  return r.mass_run_id == null
    ? { kind: r.kind, fan_id: r.fan_id }
    : { kind: r.kind, fan_id: r.fan_id, mass_run_id: r.mass_run_id };
}

/** The rendered rows: the fetched rows with their overlay. */
export function viewRows(rows: UnconfirmedRow[] | undefined, o: Overlay): UnconfirmedView[] {
  return (rows ?? []).map((r) => {
    const key = rowKey(r);
    return { ...r, key, pending: o[key]?.pending ?? false, error: o[key]?.error ?? null };
  });
}

/** A Retry's answer on the fetched rows: drop → gone; 409 → "Sending"; error → as is. */
export function settleRows(rows: UnconfirmedRow[] | undefined, key: string, out: RetryOutcome): UnconfirmedRow[] | undefined {
  if (!rows || out === "error") return rows;
  if (out === "drop") return rows.filter((r) => rowKey(r) !== key);
  return rows.map((r) => (rowKey(r) === key ? { ...r, state: "IN_FLIGHT" } : r));
}

function without(o: Overlay, key: string): Overlay {
  if (!(key in o)) return o;
  const { [key]: _gone, ...rest } = o;
  return rest;
}

export function unconfirmedSendsReducer(o: Overlay, a: Action): Overlay {
  switch (a.type) {
    case "retryStart":
      return o[a.key]?.pending ? o : { ...o, [a.key]: { pending: true, error: null } };
    case "retryDone":
      if (retryOutcome(a.result.status) !== "error") return without(o, a.key);
      return { ...o, [a.key]: { pending: false, error: a.result.message || `Retry failed (HTTP ${a.result.status})` } };
  }
}
