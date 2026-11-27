// A step whose send was interrupted is never auto-resent (at-most-once); the user retries or marks it sent.
export type UnconfirmedKind = "funnel" | "followup";
export type UnconfirmedState = "UNCONFIRMED" | "IN_FLIGHT";

export interface UnconfirmedRow {
  kind: UnconfirmedKind;
  fan_id: string;
  mass_run_id: number | null;
  step: number;
  step_label: string;
  since: string;
  last_error: string | null;
  state: UnconfirmedState;
  // A hint, not proof: the first untagged outbound message to this fan since the mark.
  hint?: { message_id: string; at: string; text: string } | null;
  retry_allowed?: boolean;
}

export interface OpRow {
  kind: string;
  op_id: string;
  updated_at: string;
  fan_id: string;
  since: string;
  state: "UNCONFIRMED";
  retry_allowed: false;
  link: "chat" | "queue";
}

export type ListedRow = UnconfirmedRow | OpRow;
export type Outcome = "was_sent" | "not_sent";
export type Op = "retry" | "dismiss" | Outcome;

export type UnconfirmedView = ListedRow & {
  key: string;
  pending: Op | null;
  error: string | null;
};

export const isOpRow = (r: ListedRow): r is OpRow => "op_id" in r;
export const showsRetry = (r: ListedRow): boolean => !isOpRow(r) && r.retry_allowed !== false;

export interface RowOverlay {
  pending: Op | null;
  error: string | null;
}

export type Overlay = Record<string, RowOverlay>;

export interface RetryResult {
  status: number;
  message?: string;
}

export type Action =
  | { type: "start"; key: string; op: Op }
  | { type: "done"; key: string; op: Op; result: RetryResult };

export const initialOverlay: Overlay = {};

export function rowKey(r: Pick<UnconfirmedRow, "kind" | "fan_id" | "mass_run_id"> | OpRow): string {
  return "op_id" in r ? `op:${r.op_id}:${r.updated_at}` : `${r.kind}:${r.fan_id}:${r.mass_run_id ?? ""}`;
}

export type RetryOutcome = "drop" | "error";

export function retryOutcome(status: number): RetryOutcome {
  return (status >= 200 && status < 300) || status === 404 ? "drop" : "error";
}

export function canAct(r: UnconfirmedView): boolean {
  return r.state === "UNCONFIRMED" && !r.pending;
}

export function buildRetryPayload(r: UnconfirmedRow): { kind: UnconfirmedKind; fan_id: string; mass_run_id?: number; since: string } {
  return r.mass_run_id == null
    ? { kind: r.kind, fan_id: r.fan_id, since: r.since }
    : { kind: r.kind, fan_id: r.fan_id, mass_run_id: r.mass_run_id, since: r.since };
}

export function buildDismissPayload(r: UnconfirmedRow): ReturnType<typeof buildRetryPayload> & { hint_message_id?: string } {
  const base = buildRetryPayload(r);
  return r.hint ? { ...base, hint_message_id: r.hint.message_id } : base;
}

export function buildResolvePayload(r: OpRow, outcome: Outcome): { op_id: string; updated_at: string; outcome: Outcome } {
  return { op_id: r.op_id, updated_at: r.updated_at, outcome };
}

export function resolveQuestion(r: OpRow, outcome: Outcome): string {
  const what = r.link === "queue" ? "this queued send" : `this send to fan ${r.fan_id}`;
  return outcome === "was_sent"
    ? `Mark ${what} as sent?\n\nOnly do this if you checked and it went out.`
    : `Mark ${what} as not sent?\n\nThis releases the hold and allows the same send to be tried again.`;
}

export function dismissQuestion(r: UnconfirmedRow): string {
  return `Mark ${r.step_label} to fan ${r.fan_id} as sent?\n\n`
    + "It will be treated as sent: the funnel moves on and this step is not sent again. "
    + "Only do this if you checked the chat and the fan got it.";
}

export interface UnconfirmedRequest {
  path: "retry" | "dismiss" | "resolve";
  body: object;
  confirm: { question: string; label: string } | null;
}

export function buildRequest(r: ListedRow, op: Op): UnconfirmedRequest | null {
  if (isOpRow(r)) {
    if (op !== "was_sent" && op !== "not_sent") return null;
    return { path: "resolve", body: buildResolvePayload(r, op),
      confirm: { question: resolveQuestion(r, op), label: op === "was_sent" ? "Was sent" : "Not sent" } };
  }
  if (op === "retry") return showsRetry(r) ? { path: "retry", body: buildRetryPayload(r), confirm: null } : null;
  if (op === "dismiss") {
    return { path: "dismiss", body: buildDismissPayload(r), confirm: { question: dismissQuestion(r), label: "It went through" } };
  }
  return null;
}

export function hintLine(r: UnconfirmedRow, time: (iso: string) => string): string | null {
  if (!r.hint) return null;
  const text = r.hint.text.length >= 60 ? `${r.hint.text}…` : r.hint.text;
  return `Sent to this fan at ${time(r.hint.at)}: ${text || "(no text)"}`;
}

export function viewRows(rows: ListedRow[] | undefined, o: Overlay): UnconfirmedView[] {
  return (rows ?? []).map((r) => {
    const key = rowKey(r);
    return { ...r, key, pending: o[key]?.pending ?? null, error: o[key]?.error ?? null };
  });
}

export function settleRows(rows: ListedRow[] | undefined, key: string, out: RetryOutcome): ListedRow[] | undefined {
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
      const failed = a.op === "retry" ? "Retry failed" : a.op === "not_sent" ? "Couldn't mark it as not sent" : "Couldn't mark it as sent";
      return { ...o, [a.key]: { pending: null, error: a.result.message || `${failed} (HTTP ${a.result.status})` } };
    }
  }
}
