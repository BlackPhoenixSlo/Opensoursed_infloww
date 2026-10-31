/**
 * customsPaneReducer — the expanded-row pane of CustomsTab's Section, plus the
 * pure helpers that read it (`rowKey`, `briefPhase`, `canCopy`, `handoffText`).
 *
 *   • ONE row open at a time: `pane` is `null` (nothing open) or the open
 *     row's `{ key, fan, seq, at, ctx, brief, order, copied }`. `open` replaces it
 *     with a fresh in-flight pane (ctx, brief and order all `null`) under a new
 *     `seq` — the caller's counter, never reused; `close` sets it back to `null`.
 *     `at` = the row's `tipped_at` it was opened at, so the pane can say when
 *     the row has moved on since (he tipped again) and was read at the old tip.
 *   • Every reply (`ctx`, `brief`, `order`), the brief retry and the copy
 *     result carry the `seq` of the open they were asked for, and are DROPPED
 *     unless a pane is open under that seq. Open A then B quickly and A's late
 *     replies used to land in B's pane — and "Copy handoff" then copied A's
 *     brief under B's username. A row KEY could not tell apart two opens of
 *     the same row (close + reopen, or Pull), so the guard is the seq.
 *   • A failed thread / order lookup is stored IN that field as `{ error }`
 *     (as a failed brief is `{ ok: false }`), never as an empty result:
 *     "nothing found" and "could not look" are different answers.
 *   • `pulls` is a row button state keyed by row, not pane data, so it is not
 *     gated on the seq: `"running"` while the row's pull runs (Pull A then
 *     Pull B keeps both spinners), `{ error }` once it failed, absent otherwise.
 *   • `copied` lives in the pane, so open / close drop it and a copy that
 *     settles after its pane was replaced (even by a reopen of the same row)
 *     is dropped too. `n` = the caller's copy counter, so an older copy's
 *     expiry timer cannot clear a newer copy's note.
 *   • `cleared` = a Sent / Dismiss POST on fan `fan` (`fanKey`) succeeded: the
 *     backend settles the FAN, so every row of his leaves the queue, and the
 *     open pane closes if it is any of his rows — `pane.fan`, carried from the
 *     open, never parsed back out of the row key (its late replies then land
 *     nowhere). Another fan's pane and every Pull spinner are untouched — a
 *     Pull on his row still runs to its `pullDone`; whether it may reopen is
 *     `mayReopen` below, not this reducer.
 *
 * Pull's reopen rule (`ReopenLedger`, `pullTicket`, `mayReopen`) lives here too,
 * so it is one pure, tabled rule rather than refs and a compound condition in
 * the component. A Pull takes a ticket when it starts; its ok rescrape reopens
 * the row only if the ticket is still good when it answers:
 *   • any open or Hide since (`paneMoved`: another row, this row reopened or
 *     hidden) revokes EVERY Pull's ticket — reopening would replace or undo
 *     what the operator chose and pay for a brief nobody asked for;
 *   • a Sent / Dismiss click on a fan (`cleared`, at the click, before its
 *     POST) revokes only THAT fan's tickets — he is being settled; another
 *     fan's Pull still reopens its row. While the POST runs, Read and Pull are
 *     off on every row of his, so no Pull of his can start in between. The
 *     close a successful clear makes is the reducer's `cleared`, not a
 *     `paneMoved`.
 */

import { fmtCents } from "@/lib/format";

/** The recording brief. Amounts come from the DB, never from the model —
 *  see `/admin/customs/brief`. */
export interface Brief {
  ok: boolean;
  reason?: string;
  paid_cents?: number;
  order_count?: number;
  /** false = the model could not see him ask for anything in this excerpt.
   *  Rendered as a warning, never as a work order. */
  found_request?: boolean;
  /** The concrete work order — what to make, how long, what to wear, what to
   *  say, what to call him. This IS the handoff. */
  summary?: string;
  /** His own lines that are the request, verbatim — the receipt. */
  his_words?: string[];
  call_him?: string | null;
}

/** ONE line of the order span. Named rather than inline because both the pane
 *  and the clipboard render it, through `speaker` / `orderLine` below. */
export interface OrderMsg {
  message_id: number;
  from_fan: boolean;
  is_tip: boolean;
  text: string;
  at: string | null;
}

/** The order's own span — see `/admin/customs/order`. NOT a window around the
 *  tip: on a layaway custom the ask is months behind the money. */
export interface OrderLines {
  lines: OrderMsg[];
  count: number;
  opened_at?: string | null;
  /** true = the span was too long to print whole, so only the lines mentioning
   *  the order survived. Said out loud, because the operator is otherwise
   *  reading an edit without being told it is one. */
  truncated?: boolean;
  /** The backend's own word on an empty span ("no order talk found…"). */
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

/** A lookup that failed, stored in the field its answer would have filled. */
export interface Failed {
  error: string;
}

export function isFailed(x: unknown): x is Failed {
  return typeof x === "object" && x !== null && "error" in x;
}

/** A lookup field's answer, or `null` while it is in flight or once it failed. */
export function loaded<T extends object>(x: T | Failed | null): T | null {
  return x === null || isFailed(x) ? null : x;
}

/** The row fields the pane's helpers read — CustomsTab's `CustomRow` extends it. */
export interface PaneRow {
  /** true = tagged Custom and owed (one row per fan). false = a qualifying tip
   *  nobody watched: a "Worth a look" REVIEW row (one per ORDER), which may
   *  equally have been plain generosity. */
  marked: boolean;
  account_id: string;
  account_name: string;
  fan_id: number;
  display_name: string;
  /** The OnlyFans @handle, kept SEPARATE from `display_name` (which falls back
   *  to it) because the handoff has to carry the exact string the operator
   *  pastes into OF search — a display name finds nothing there. */
  of_username?: string | null;
  tip_cents: number | null;
  tipped_at: string | null;
}

/** The open row's pane. `null` in `ctx` / `brief` / `order` = that request is
 *  still in flight. */
export interface Pane {
  key: string;
  /** The open row's fan (`fanKey`) — what `cleared` matches. */
  fan: string;
  seq: number;
  /** The row's `tipped_at` when this pane was opened (brief and thread read at it). */
  at: string | null;
  ctx: ContextMsg[] | Failed | null;
  brief: Brief | null;
  order: OrderLines | Failed | null;
  /** The last copy from this pane, `null` = none yet. */
  copied: { n: number; ok: boolean } | null;
}

export interface CustomsPaneState {
  pane: Pane | null;
  /** Per row key: its pull running, or how the last one failed. */
  pulls: Readonly<Record<string, "running" | Failed>>;
}

export type CustomsPaneAction =
  /** `seq` is new on every open (the caller's counter, never reused). */
  | { type: "open"; key: string; fan: string; seq: number; at: string | null }
  | { type: "close" }
  | { type: "ctx"; seq: number; ctx: ContextMsg[] | Failed }
  | { type: "brief"; seq: number; brief: Brief }
  | { type: "briefRetry"; seq: number }
  | { type: "order"; seq: number; order: OrderLines | Failed }
  | { type: "pullStart"; key: string }
  /** `error` set = the pull failed; it is shown on that row. */
  | { type: "pullDone"; key: string; error?: string }
  | { type: "copyDone"; seq: number; n: number; ok: boolean }
  | { type: "copyExpired"; n: number }
  /** Sent / Dismiss on fan `fan` (`fanKey`) succeeded. */
  | { type: "cleared"; fan: string };

export const initialCustomsPane: CustomsPaneState = {
  pane: null,
  pulls: {},
};

export function customsPaneReducer(
  s: CustomsPaneState,
  a: CustomsPaneAction,
): CustomsPaneState {
  /** Apply `patch` to the pane only if it is the open `seq`'s. */
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
      return { ...s, pulls: a.error === undefined ? rest : { ...rest, [a.key]: { error: a.error } } };
    }
    case "copyDone":
      return onPane(a.seq, { copied: { n: a.n, ok: a.ok } });
    case "copyExpired":
      return s.pane?.copied?.n === a.n ? { ...s, pane: { ...s.pane, copied: null } } : s;
    case "cleared":
      return s.pane?.fan === a.fan ? { ...s, pane: null } : s;
  }
}

/** The fan's identity, `account:fan` — what Sent / Dismiss settles. */
export function fanKey(r: Pick<PaneRow, "account_id" | "fan_id">): string {
  return `${r.account_id}:${r.fan_id}`;
}

/** What Pull's reopen rule reads. Held in a ref by the Section (an async Pull
 *  needs the value as of its answer, not as of its render). */
export interface ReopenLedger {
  /** The pane counter, bumped on every open and every Hide, not a `cleared`
   *  close; an open's replies carry its value (the reducer's `seq`). Never
   *  reused. */
  seq: number;
  /** Per fan (`fanKey`), bumped on every Sent / Dismiss click on him. */
  clears: Readonly<Record<string, number>>;
}

export type ReopenEvent =
  /** A pane opened or hidden (Read, Hide, read again, a Pull's own reopen). */
  | { type: "paneMoved" }
  /** Sent / Dismiss on fan `fan`. */
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

/** A Pull's right to reopen its row, taken when the Pull starts. */
export interface PullTicket {
  seq: number;
  fan: string;
  clears: number;
}

export function pullTicket(ledger: ReopenLedger, fan: string): PullTicket {
  return { seq: ledger.seq, fan, clears: ledger.clears[fan] || 0 };
}

/** May this Pull's ok rescrape reopen its row now? One condition per rule of
 *  the header's "Pull's reopen rule". */
export function mayReopen(ledger: ReopenLedger, ticket: PullTicket): boolean {
  const paneMoved = ledger.seq !== ticket.seq;
  const clearsNow = ledger.clears[ticket.fan] || 0;
  const fanCleared = clearsNow !== ticket.clears;
  return !paneMoved && !fanCleared;
}

/** The row's identity — the fan plus, where a fan can have several rows, the
 *  order. An OWED row is one per fan (`customs_api.list_customs` folds every
 *  order into it), so it is `account:fan` alone: its `tipped_at` is the newest
 *  tip and moves when he tips again, which would close the open pane on
 *  Refresh. "Worth a look" emits one row per ORDER (`_unmarked`), so one fan
 *  can have two; each order's anchor tip time (`tipped_at`) tells them apart. */
export function rowKey(r: Pick<PaneRow, "marked" | "account_id" | "fan_id" | "tipped_at">): string {
  const fan = fanKey(r);
  return r.marked ? fan : `${fan}:${r.tipped_at ?? ""}`;
}

/** The brief's four visible states. `null` = in flight. */
export function briefPhase(brief: Brief | null): "loading" | "failed" | "not-found" | "ready" {
  if (brief === null) return "loading";
  if (!brief.ok) return "failed";
  return brief.found_request === false ? "not-found" : "ready";
}

/** The handoff is copyable once both of its inputs — the brief and the order
 *  span — have SETTLED (answered or failed). Before that it would copy the
 *  fallback text and the UI would say "Copied" over a request it never had. */
export function canCopy(pane: Pane): boolean {
  return pane.brief !== null && pane.order !== null;
}

/** WHO SAID IT, for ONE order line — the single source for the pane and the
 *  clipboard, so the two cannot drift apart. */
export function speaker(m: OrderMsg): string {
  return m.is_tip ? "💸" : m.from_fan ? "HIM" : "US";
}

/** ONE order line as the clipboard carries it: speaker, date, text — padded
 *  to the pane's column widths so a pasted handoff reads as the same three
 *  columns the operator was just looking at. */
export function orderLine(m: OrderMsg): string {
  return `${speaker(m).padStart(4, " ")} ${(m.at || "").slice(0, 10)}  ${m.text}`;
}

/** THE HANDOFF, in the operator's own words (2026-09-05):
 *
 *      -username
 *      -account
 *      -copy and paste the request
 *
 *  ...where the request is *"scrape those 100 messages over the tips before
 *  and after and generate CONCRETE SUMMARY OF WHAT WE NEED TO DO"*. So the
 *  body is the model's work order from `/admin/customs/brief` (100 messages
 *  each side of the tip, plus the order's own lines from the whole thread),
 *  followed by his exact words as the receipt.
 *
 *  When the brief failed or found no request, the raw order lines stand in;
 *  when the order lookup failed too, it says so rather than "none found".
 *  Only called once `canCopy(pane)`.
 *
 *  The username is `of_username`, NOT `display_name`. `display_name` falls back
 *  to the handle, so on many rows they render identically and the difference is
 *  invisible right up until the row where it matters and OF search finds
 *  nothing. */
export function handoffText(
  r: PaneRow,
  pane: Pick<Pane, "brief" | "order">,
): string {
  const { brief, order } = pane;
  const username = (r.of_username || "").trim();
  const lines = [
    `-username: ${username ? `@${username}` : `(not stored — fan #${r.fan_id}, "${r.display_name}")`}`,
    `-account: ${r.account_name}`,
  ];
  // The total, from the DB. One number, nothing derived from it.
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
