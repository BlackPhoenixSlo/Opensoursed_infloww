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
 */
import { RelayError } from "@/lib/relay";

export interface Turn {
  id: number;
  question: string;
  /** null while the POST is in flight — that's the "thinking…" row. */
  answer: string | null;
  error: string | null;
}

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
}

export type AssistantAction =
  | { type: "hydrate"; open: boolean }
  | { type: "toggle" }
  | { type: "asked"; id: number; question: string }
  | { type: "route"; onHelpPage: boolean }
  | { type: "settled"; id: number; answer: string; error: string | null };

export const initialAssistantState: AssistantCore = {
  hydrated: false,
  open: false,
  turns: [],
  unread: false,
  onHelpPage: false,
};

/** Opening reads every reply; closing leaves `unread` as it was (false). */
function withOpen(state: AssistantCore, open: boolean): AssistantCore {
  return { ...state, open, unread: state.unread && !open };
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
  }
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
