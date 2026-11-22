/**
 * unconfirmedSendsReducer — pure state for the Auto Funnel "May not have sent" list
 * (UnconfirmedSends.tsx, data via hooks/useUnconfirmedSends).
 *
 * A funnel / follow-up step whose send was interrupted is marked and never
 * auto-resent (at-most-once); the relay lists it on
 * GET /admin/unconfirmed-sends and the user retries it, or tells it the step
 * went through (POST …/dismiss: saved as sent, never resent). Per row:
 *   • UNCONFIRMED → "May not have sent" + Retry + "It went through";
 *     IN_FLIGHT → "Sending", neither.
 *   • Each op is per row and non-blocking (`pending` names the op on that row only;
 *     both buttons wait for it).
 *   • Retry 200 (`retried` / `already_sent`) or 404 (gone) → drop + refetch.
 *   • It went through 200 (`dismissed` / `already_sent`) or 404 (gone) → drop +
 *     refetch.
 *   • Either op's error → row error text, the row stays, both enabled again; a 409
 *     (still sending, the row changed since it was listed, a step it can't save)
 *     also refetches, so the row shows the server's state now.
 *   • Both bodies carry the listed row's `since`: the server refuses (409) an op on
 *     a newer attempt than the one the user saw.
 * The rows are react-query's (the server truth); this holds only each row's
 * local overlay (`pending` / `error`), and `settleRows` is an op's answer
 * applied to the cached rows until the refetch.
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
  /** The first untagged outbound message to this fan since the mark (local DB): a hint, not proof. */
  hint?: { message_id: string; at: string; text: string } | null;
}

/** A row's two ops: resend it, or save it as sent ("It went through"). */
export type Op = "retry" | "dismiss";

export interface UnconfirmedView extends UnconfirmedRow {
  key: string;
  pending: Op | null;
  error: string | null;
}

export interface RowOverlay {
  pending: Op | null;
  error: string | null;
}

/** rowKey → that row's local op state. */
export type Overlay = Record<string, RowOverlay>;

/** What an op's POST came back with: an HTTP status (200 for a body) + error text. */
export interface RetryResult {
  status: number;
  message?: string;
}

export type Action =
  | { type: "start"; key: string; op: Op }
  | { type: "done"; key: string; op: Op; result: RetryResult };

export const initialOverlay: Overlay = {};

export function rowKey(r: Pick<UnconfirmedRow, "kind" | "fan_id" | "mass_run_id">): string {
  return `${r.kind}:${r.fan_id}:${r.mass_run_id ?? ""}`;
}

export type RetryOutcome = "drop" | "error";

export function retryOutcome(status: number): RetryOutcome {
  return (status >= 200 && status < 300) || status === 404 ? "drop" : "error";
}

/** Retry and It went through are shown for UNCONFIRMED rows, enabled unless either is in flight. */
export function canAct(r: UnconfirmedView): boolean {
  return r.state === "UNCONFIRMED" && !r.pending;
}

/** The POST body for a row's Retry (`mass_run_id` only when set; `since`: a newer attempt on the row is refused). */
export function buildRetryPayload(r: UnconfirmedRow): { kind: UnconfirmedKind; fan_id: string; mass_run_id?: number; since: string } {
  return r.mass_run_id == null
    ? { kind: r.kind, fan_id: r.fan_id, since: r.since }
    : { kind: r.kind, fan_id: r.fan_id, mass_run_id: r.mass_run_id, since: r.since };
}

/** The POST body for a row's It went through: Retry's + the hint the user saw (it gets the step's tags). */
export function buildDismissPayload(r: UnconfirmedRow): ReturnType<typeof buildRetryPayload> & { hint_message_id?: string } {
  const base = buildRetryPayload(r);
  return r.hint ? { ...base, hint_message_id: r.hint.message_id } : base;
}

/** The confirm before It went through. */
export function dismissQuestion(r: UnconfirmedRow): string {
  return `Mark ${r.step_label} to fan ${r.fan_id} as sent?\n\n`
    + "It will be treated as sent: the funnel moves on and this step is not sent again. "
    + "Only do this if you checked the chat and the fan got it.";
}

/** "Sent to this fan at 14:02: …" under a row, or null without a hint. */
export function hintLine(r: UnconfirmedRow, time: (iso: string) => string): string | null {
  if (!r.hint) return null;
  const text = r.hint.text.length >= 60 ? `${r.hint.text}…` : r.hint.text;
  return `Sent to this fan at ${time(r.hint.at)}: ${text || "(no text)"}`;
}

/** The rendered rows: the fetched rows with their overlay. */
export function viewRows(rows: UnconfirmedRow[] | undefined, o: Overlay): UnconfirmedView[] {
  return (rows ?? []).map((r) => {
    const key = rowKey(r);
    return { ...r, key, pending: o[key]?.pending ?? null, error: o[key]?.error ?? null };
  });
}

/** An op's answer on the fetched rows: drop → gone; error → as is. */
export function settleRows(rows: UnconfirmedRow[] | undefined, key: string, out: RetryOutcome): UnconfirmedRow[] | undefined {
  if (!rows || out === "error") return rows;
  return rows.filter((r) => rowKey(r) !== key);
}

function without(o: Overlay, key: string): Overlay {
  if (!(key in o)) return o;
  const { [key]: _gone, ...rest } = o;
  return rest;
}

export function unconfirmedSendsReducer(o: Overlay, a: Action): Overlay {
  switch (a.type) {
    case "start":
      return o[a.key]?.pending ? o : { ...o, [a.key]: { pending: a.op, error: null } };
    case "done": {
      if (retryOutcome(a.result.status) !== "error") return without(o, a.key);
      const failed = a.op === "retry" ? "Retry failed" : "Couldn't mark it as sent";
      return { ...o, [a.key]: { pending: null, error: a.result.message || `${failed} (HTTP ${a.result.status})` } };
    }
  }
}
