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
 *     while the panel stays open on a 401). It is kept apart
 *     from `turns`: this session's asks are written server-side too, so a
 *     reload on every open would show them twice. `historyFromRows` maps the
 *     rows (newest first) to oldest-first turns; `groupByDay` labels them;
 *     `historyForAsk` is the last 3 answered turns the POST carries so a bare
 *     "yes" can take up the last answer's offer.
 */
import { RelayError } from "@/lib/relay";

export interface Turn {
  id: number;
  question: string;
  /** null while the POST is in flight — that's the "thinking…" row. */
  answer: string | null;
  error: string | null;
  /** ISO time, on history turns only (the server's `ts`). */
  ts?: string | null;
}

/** One row of GET /admin/assistant/history (service/assistant_api.py `_turn_row`). */
export interface HistoryRow {
  id: number;
  ts: string | null;
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
  /** Earlier sessions' turns, oldest first (max HISTORY_LIMIT). */
  history: Turn[];
  historyStatus: HistoryStatus;
}

/** How many earlier turns the panel loads and shows. */
export const HISTORY_LIMIT = 50;
/** How many previous turns ride each ask (the server keeps the newest 3 too). */
export const ASK_HISTORY_TURNS = 3;

export type AssistantAction =
  | { type: "hydrate"; open: boolean }
  | { type: "toggle" }
  | { type: "asked"; id: number; question: string }
  | { type: "route"; onHelpPage: boolean }
  | { type: "settled"; id: number; answer: string; error: string | null }
  | { type: "history_requested" }
  | { type: "history_loaded"; turns: Turn[] }
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
        turns: [...state.turns, { id: action.id, question: action.question, answer: null, error: null }],
      };
    case "route":
      // Same page kind (every pathname change, and the mount): same object, no re-render.
      return state.onHelpPage === action.onHelpPage ? state : { ...state, onHelpPage: action.onHelpPage };
    case "settled": {
      const { id, answer, error } = action;
      const seen = state.open || state.onHelpPage;
      return {
        ...state,
        turns: state.turns.map((t) => (t.id === id ? { ...t, answer, error } : t)),
        unread: state.unread || !seen,
      };
    }
    case "history_requested":
      return state.historyStatus === "idle" ? { ...state, historyStatus: "loading" } : state;
    case "history_loaded":
      return { ...state, history: action.turns.slice(-HISTORY_LIMIT), historyStatus: "loaded" };
    case "history_failed":
      return { ...state, historyStatus: "failed" };
  }
}

/** The history GET's rows (newest first) as oldest-first turns. Ids go
 *  negative so they can never collide with this session's (0, 1, 2…). A body
 *  without `turns` (an older server) is no history, not a crash. */
export function historyFromRows(body: { turns?: HistoryRow[] } | null | undefined): Turn[] {
  const rows = Array.isArray(body?.turns) ? body.turns : [];
  return rows
    .slice(0, HISTORY_LIMIT)
    .reverse()
    .map((r) => ({ id: -1 - r.id, question: r.question, answer: r.answer ?? "", error: r.error ?? null, ts: r.ts }));
}

/** The last answered turns, oldest first, as the ask's `history`. An error
 *  answer (cap, transport) is not context worth sending. */
export function historyForAsk(state: Pick<AssistantCore, "history" | "turns">): Array<{ question: string; answer: string }> {
  return [...state.history, ...state.turns]
    .filter((t) => t.answer !== null && !t.error)
    .slice(-ASK_HISTORY_TURNS)
    .map((t) => ({ question: t.question, answer: t.answer as string }));
}

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DAY_YEAR_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** Oldest-first turns in local-day runs: "Today", "Yesterday", "Nov 5" (a
 *  past year adds it). A turn without a parseable `ts` joins the run before it. */
export function groupByDay(turns: Turn[], now: Date): Array<{ label: string; turns: Turn[] }> {
  const today = dayKey(now);
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  const yesterday = dayKey(y);
  const out: Array<{ key: string; label: string; turns: Turn[] }> = [];
  for (const t of turns) {
    const parsed = t.ts ? new Date(t.ts) : null;
    const d = parsed && !Number.isNaN(parsed.getTime()) ? parsed : null;
    const key = d ? dayKey(d) : out[out.length - 1]?.key ?? "?";
    if (out[out.length - 1]?.key !== key) {
      const label = !d ? "Earlier"
        : key === today ? "Today"
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
  };
}
