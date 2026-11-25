import { fmtCents } from "@/lib/format";

export interface Brief {
  ok: boolean;
  reason?: string;
  paid_cents?: number;
  order_count?: number;
  found_request?: boolean;
  summary?: string;
  his_words?: string[];
  call_him?: string | null;
}

export interface OrderMsg {
  message_id: number;
  from_fan: boolean;
  is_tip: boolean;
  text: string;
  at: string | null;
}

// The order's own span, not a window around the tip: on a layaway custom the ask is months behind the money.
export interface OrderLines {
  lines: OrderMsg[];
  count: number;
  opened_at?: string | null;
  truncated?: boolean;
  reason?: string;
}

export interface ContextMsg {
  message_id: number;
  from_fan: boolean;
  text: string;
  at: string | null;
  is_tip: boolean;
  price_cents: number;
}

export interface Failed {
  error: string;
}

export function isFailed(x: unknown): x is Failed {
  return typeof x === "object" && x !== null && "error" in x;
}

export function loaded<T extends object>(x: T | Failed | null): T | null {
  return x === null || isFailed(x) ? null : x;
}

export interface PaneRow {
  marked: boolean;
  account_id: string;
  account_name: string;
  fan_id: number;
  display_name: string;
  of_username?: string | null;
  tip_cents: number | null;
  tipped_at: string | null;
}

export interface Pane {
  key: string;
  fan: string;
  seq: number;
  at: string | null;
  ctx: ContextMsg[] | Failed | null;
  brief: Brief | null;
  order: OrderLines | Failed | null;
  copied: { n: number; ok: boolean } | null;
}

export type PullNotice = "partial" | "pending";

export interface CustomsPaneState {
  pane: Pane | null;
  pulls: Readonly<Record<string, "running" | PullNotice | Failed>>;
}

export type CustomsPaneAction =
  | { type: "open"; key: string; fan: string; seq: number; at: string | null }
  | { type: "close" }
  | { type: "ctx"; seq: number; ctx: ContextMsg[] | Failed }
  | { type: "brief"; seq: number; brief: Brief }
  | { type: "briefRetry"; seq: number }
  | { type: "order"; seq: number; order: OrderLines | Failed }
  | { type: "pullStart"; key: string }
  | { type: "pullDone"; key: string; error?: string; notice?: PullNotice }
  | { type: "copyDone"; seq: number; n: number; ok: boolean }
  | { type: "copyExpired"; n: number }
  | { type: "cleared"; fan: string };

export const initialCustomsPane: CustomsPaneState = {
  pane: null,
  pulls: {},
};

export function customsPaneReducer(
  s: CustomsPaneState,
  a: CustomsPaneAction,
): CustomsPaneState {
  // Replies carry the open's seq and are dropped unless that pane is open: a late reply from A must not land in B.
  const onPane = (seq: number, patch: Partial<Pane>): CustomsPaneState =>
    s.pane !== null && s.pane.seq === seq ? { ...s, pane: { ...s.pane, ...patch } } : s;
  switch (a.type) {
    case "open":
      return {
        ...s,
        pane: { key: a.key, fan: a.fan, seq: a.seq, at: a.at, ctx: null, brief: null, order: null, copied: null },
      };
    case "close":
      return s.pane === null ? s : { ...s, pane: null };
    case "ctx":
      return onPane(a.seq, { ctx: a.ctx });
    case "brief":
      return onPane(a.seq, { brief: a.brief });
    case "briefRetry":
      return onPane(a.seq, { brief: null });
    case "order":
      return onPane(a.seq, { order: a.order });
    case "pullStart":
      return { ...s, pulls: { ...s.pulls, [a.key]: "running" } };
    case "pullDone": {
      const { [a.key]: _done, ...rest } = s.pulls;
      const result = a.error === undefined ? a.notice : { error: a.error };
      return { ...s, pulls: result === undefined ? rest : { ...rest, [a.key]: result } };
    }
    case "copyDone":
      return onPane(a.seq, { copied: { n: a.n, ok: a.ok } });
    case "copyExpired":
      return s.pane?.copied?.n === a.n ? { ...s, pane: { ...s.pane, copied: null } } : s;
    case "cleared":
      return s.pane?.fan === a.fan ? { ...s, pane: null } : s;
  }
}

export function fanKey(r: Pick<PaneRow, "account_id" | "fan_id">): string {
  return `${r.account_id}:${r.fan_id}`;
}

export interface ReopenLedger {
  seq: number;
  clears: Readonly<Record<string, number>>;
}

export type ReopenEvent =
  | { type: "paneMoved" }
  | { type: "cleared"; fan: string };

export const initialReopenLedger: ReopenLedger = { seq: 0, clears: {} };

export function reopenLedger(ledger: ReopenLedger, e: ReopenEvent): ReopenLedger {
  switch (e.type) {
    case "paneMoved":
      return { ...ledger, seq: ledger.seq + 1 };
    case "cleared":
      return { ...ledger, clears: { ...ledger.clears, [e.fan]: (ledger.clears[e.fan] || 0) + 1 } };
  }
}

export interface PullTicket {
  seq: number;
  fan: string;
  clears: number;
}

export function pullTicket(ledger: ReopenLedger, fan: string): PullTicket {
  return { seq: ledger.seq, fan, clears: ledger.clears[fan] || 0 };
}

export function mayReopen(ledger: ReopenLedger, ticket: PullTicket): boolean {
  const paneMoved = ledger.seq !== ticket.seq;
  const clearsNow = ledger.clears[ticket.fan] || 0;
  const fanCleared = clearsNow !== ticket.clears;
  return !paneMoved && !fanCleared;
}

// An owed row is one per fan, keyed without tipped_at (it moves on a new tip and would close the pane on Refresh); review rows are per order.
export function rowKey(r: Pick<PaneRow, "marked" | "account_id" | "fan_id" | "tipped_at">): string {
  const fan = fanKey(r);
  return r.marked ? fan : `${fan}:${r.tipped_at ?? ""}`;
}

export function briefPhase(brief: Brief | null): "loading" | "failed" | "not-found" | "ready" {
  if (brief === null) return "loading";
  if (!brief.ok) return "failed";
  return brief.found_request === false ? "not-found" : "ready";
}

export function canCopy(pane: Pane): boolean {
  return pane.brief !== null && pane.order !== null;
}

export function speaker(m: OrderMsg): string {
  return m.is_tip ? "💸" : m.from_fan ? "HIM" : "US";
}

export function orderLine(m: OrderMsg): string {
  return `${speaker(m).padStart(4, " ")} ${(m.at || "").slice(0, 10)}  ${m.text}`;
}

export function handoffText(
  r: PaneRow,
  pane: Pick<Pane, "brief" | "order">,
): string {
  const { brief, order } = pane;
  // of_username, not display_name: OF search finds nothing on a display name.
  const username = (r.of_username || "").trim();
  const lines = [
    `-username: ${username ? `@${username}` : `(not stored — fan #${r.fan_id}, "${r.display_name}")`}`,
    `-account: ${r.account_name}`,
  ];
  if (r.tip_cents != null) {
    lines.push(`-total: ${fmtCents(r.tip_cents)}`);
  }
  if (brief?.call_him) lines.push(`-call him: ${brief.call_him}`);
  lines.push("-request:");

  if (brief?.ok && brief.found_request !== false && brief.summary) {
    lines.push(`  ${brief.summary}`);
    if ((brief.his_words || []).length > 0) {
      lines.push("  His words:");
      for (const w of brief.his_words || []) lines.push(`  "${w}"`);
    }
    return lines.join("\n");
  }

  if (isFailed(order)) {
    lines.push(`  (order lookup failed: ${order.error} — open it in OnlyFans)`);
    return lines.join("\n");
  }
  const got = order?.lines || [];
  if (got.length === 0) {
    lines.push("  (no order talk found in this thread — open it in OnlyFans)");
  } else {
    for (const m of got) lines.push(orderLine(m));
  }
  return lines.join("\n");
}
