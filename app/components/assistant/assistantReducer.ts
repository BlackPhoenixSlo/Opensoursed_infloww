/**
 * The help bot's conversation state, as one pure reducer (AssistantProvider in
 * AssistantWidget.tsx only dispatches; storage writes and the POST stay there).
 *
 *   • `hydrate` takes the persisted open bit once, after the first client
 *     render; it leaves `turns` alone, so a turn already asked survives it,
 *     and an open hydrate clears `unread` like any open (invariant below).
 *   • Opening the dock clears `unread`: the panel on screen IS the reply read
 *     (invariant: open ⇒ !unread).
 *   • `route` records whether the /help-center page is on screen (the
 *     provider's pathname effect).
 *   • `settled` fills a turn's answer by id (concurrent turns settle in any
 *     order) and raises `unread` only when no surface shows it — the dock is
 *     closed AND the /help-center page is not on screen. Both are read here,
 *     at the same instant as the answer, never from a lagging ref.
 *   • `settledFrom` / `settledFromError` turn the POST's outcome into that
 *     action (pure, so the empty / transport sentences are table-tested).
 *   • HISTORY (GET /admin/assistant/history) loads ONCE per page load, on the
 *     first open: `history_requested` → `history_loaded` | `history_failed`
 *     (`failed` until the next open, which retries — never a retry loop
 *     while the panel stays open on a 401). It is kept apart from `turns`,
 *     and this session's asks are written server-side too, so every turn
 *     carries its server row id (`rowId`, from the ask's response) and a row
 *     already in `turns` never shows under Earlier — whichever of the load
 *     and the answer lands first. `historyFromRows` maps the rows (newest
 *     first) to oldest-first turns; `groupByDay` labels them.
 *   • The client sends no history: the server picks the previous turns that
 *     ride an ask (service/assistant_api.py `_own_turns`).
 */
import { RelayError } from "@/lib/relay";

export interface Turn {
  id: number;
  question: string;
  /** null while the POST is in flight — that's the "thinking…" row. */
  answer: string | null;
  error: string | null;
  /** The server's assistant_turns row: null in flight or when its write failed. */
  rowId: number | null;
}

/** An earlier session's turn (GET /admin/assistant/history). */
export interface EarlierTurn extends Turn {
  answer: string;
  rowId: number;
  /** ISO time (the server's `ts`). */
  ts: string;
}

/** One row of GET /admin/assistant/history (service/assistant_api.py `_turn_row`). */
export interface HistoryRow {
  id: number;
  ts: string;
  question: string;
  answer: string;
  error: string | null;
}

export type HistoryStatus = "idle" | "loading" | "loaded" | "failed";

/** The endpoint's response contract. `error` is a machine tag for the log
 *  (cap | config | provider | empty_answer | empty_question); `answer` is
 *  always a human sentence, including on every one of those. */
export interface AskResponse {
  answer: string;
  error: string | null;
  /** The turn row the server wrote (null when the write failed). */
  id: number | null;
}

export interface AssistantCore {
  /** False until the persisted open bit has been read (first client render). */
  hydrated: boolean;
  open: boolean;
  turns: Turn[];
  /** A reply settled while no surface showed it: the launcher's red dot. */
  unread: boolean;
  /** The /help-center page is on screen: it shows every reply too. */
  onHelpPage: boolean;
  /** Earlier sessions' turns, oldest first (the server returns ≤ HISTORY_LIMIT). */
  history: EarlierTurn[];
  historyStatus: HistoryStatus;
}

/** How many earlier turns the panel asks the server for. */
export const HISTORY_LIMIT = 50;

export type AssistantAction =
  | { type: "hydrate"; open: boolean }
  | { type: "toggle" }
  | { type: "asked"; id: number; question: string }
  | { type: "route"; onHelpPage: boolean }
  | { type: "settled"; id: number; answer: string; error: string | null; rowId: number | null }
  | { type: "history_requested" }
  | { type: "history_loaded"; turns: EarlierTurn[] }
  | { type: "history_failed" };

export const initialAssistantState: AssistantCore = {
  hydrated: false,
  open: false,
  turns: [],
  unread: false,
  onHelpPage: false,
  history: [],
  historyStatus: "idle",
};

/** Opening reads every reply; closing leaves `unread` as it was (false).
 *  Opening also re-arms a failed history read. */
function withOpen(state: AssistantCore, open: boolean): AssistantCore {
  const retry = open && state.historyStatus === "failed";
  return { ...state, open, unread: state.unread && !open, ...(retry ? { historyStatus: "idle" as const } : {}) };
}

export function assistantReducer(state: AssistantCore, action: AssistantAction): AssistantCore {
  switch (action.type) {
    case "hydrate":
      return { ...withOpen(state, action.open), hydrated: true };
    case "toggle":
      return withOpen(state, !state.open);
    case "asked":
      return {
        ...state,
        turns: [...state.turns, { id: action.id, question: action.question, answer: null, error: null, rowId: null }],
      };
    case "route":
      // Same page kind (every pathname change, and the mount): same object, no re-render.
      return state.onHelpPage === action.onHelpPage ? state : { ...state, onHelpPage: action.onHelpPage };
    case "settled": {
      const { id, answer, error, rowId } = action;
      const seen = state.open || state.onHelpPage;
      return {
        ...state,
        turns: state.turns.map((t) => (t.id === id ? { ...t, answer, error, rowId } : t)),
        // A history load that landed first already holds this row.
        history: state.history.filter((h) => h.rowId !== rowId),
        unread: state.unread || !seen,
      };
    }
    case "history_requested":
      return state.historyStatus === "idle" ? { ...state, historyStatus: "loading" } : state;
    case "history_loaded": {
      const mine = new Set(state.turns.map((t) => t.rowId));
      return { ...state, history: action.turns.filter((h) => !mine.has(h.rowId)), historyStatus: "loaded" };
    }
    case "history_failed":
      return { ...state, historyStatus: "failed" };
  }
}

/** The history GET's rows (newest first) as oldest-first turns. Ids go
 *  negative so they can never collide with this session's (0, 1, 2…). */
export function historyFromRows(body: { turns: HistoryRow[] }): EarlierTurn[] {
  return [...body.turns]
    .reverse()
    .map((r) => ({ id: -1 - r.id, rowId: r.id, question: r.question, answer: r.answer, error: r.error, ts: r.ts }));
}

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DAY_YEAR_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** Oldest-first turns in local-day runs: "Today", "Yesterday", "Nov 5" (a
 *  past year adds it). */
export function groupByDay(turns: EarlierTurn[], now: Date): Array<{ label: string; turns: EarlierTurn[] }> {
  const today = dayKey(now);
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  const yesterday = dayKey(y);
  const out: Array<{ key: string; label: string; turns: EarlierTurn[] }> = [];
  for (const t of turns) {
    const d = new Date(t.ts);
    const key = dayKey(d);
    if (out[out.length - 1]?.key !== key) {
      const label = key === today ? "Today"
        : key === yesterday ? "Yesterday"
        : (d.getFullYear() === now.getFullYear() ? DAY_FMT : DAY_YEAR_FMT).format(d);
      out.push({ key, label, turns: [] });
    }
    out[out.length - 1].turns.push(t);
  }
  return out.map(({ label, turns }) => ({ label, turns }));
}

type Settled = Extract<AssistantAction, { type: "settled" }>;

/** The POST's 200 as a `settled` action: a blank answer is "empty_answer"
 *  with a human sentence, never an empty bubble. */
export function settledFrom(id: number, r: AskResponse | null | undefined): Settled {
  const answer = (r?.answer || "").trim();
  return {
    type: "settled", id,
    answer: answer || "The assistant came back empty — try asking again.",
    error: answer ? (r?.error ?? null) : "empty_answer",
    rowId: r?.id ?? null,
  };
}

/** The POST threw: the request never reached a verdict — the relay is down,
 *  the share token is stale, or `assert_account_owned` said no. Every failure
 *  the endpoint itself knows about arrives as a 200 (`settledFrom`). */
export function settledFromError(id: number, e: unknown): Settled {
  const detail = e instanceof RelayError ? e.message : "";
  return {
    type: "settled", id,
    answer: `Couldn't reach the assistant${detail ? ` (${detail})` : ""} — try again in a moment.`,
    error: "transport",
    rowId: null,
  };
}
