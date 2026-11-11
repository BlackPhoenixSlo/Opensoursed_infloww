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
 *     already in `turns` never shows twice — whichever of the load and the
 *     answer lands first. `historyFromRows` maps the rows (newest first) to
 *     oldest-first turns; `threadsOf` + `groupByDay` list their threads.
 *   • The client sends no history: the server picks the previous turns that
 *     ride an ask (service/assistant_api.py `_context_turns`) — the earlier
 *     turns of the ask's THREAD.
 *   • THREADS. A conversation is a `thread` id, sent on every ask and stored
 *     on the row. `active` is the thread on screen; null is the home screen
 *     (a new chat: the provider names it on its first ask and `asked` carries
 *     it, so asks fired before the first answer share it). Earlier threads are
 *     listed (`threadsOf`), never dumped inline. The server owns the ids of
 *     rows from before threads (`legacy-<first id>`, db/assistant_threads.py),
 *     so every row arrives with one.
 *   • FOCUS — who the next ask is about: an account id, or null = General
 *     (manual only). It follows the app's model switcher (`scope`), and a
 *     manual `pick` holds until the next switcher change. Once the thread on
 *     screen has started, focus is LOCKED to it (the server's context is per
 *     thread AND account): a switcher change is only remembered (`held`, the
 *     widget offers it), a pick of another focus starts a new chat, and
 *     `new_chat` adopts a held switch. Opening a thread takes its focus.
 *   • ROSTER — the OWNED accounts (every one, a dropped session or a
 *     deactivated Creator included: the server's reach) and whether General is
 *     on offer (a signed-in user only: the server 401s a chatter's account-less ask). The stored
 *     focus stays RAW — the app's / the pick's value — and is resolved on read
 *     (`resolveFocus`): an owned account or offered General as is, else the
 *     first account. So a roster landing late (or empty for a moment) never
 *     loses the app's model. Comparisons (`scope`'s hold, `pick`, `new_chat`)
 *     are on resolved values. A started thread's focus is the account its
 *     asks went out with (`asked` locks it); one the roster no longer has is
 *     never silently retargeted: it becomes a new chat. Before the roster
 *     loads the unresolved focus goes out (the server's assert_account_owned gates
 *     it), except General for a non-user, which waits (`sendFocusOf` →
 *     undefined).
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
  /** The conversation it belongs to. */
  thread: string;
  /** The account it was asked about; null = General. */
  accountId: Focus;
  /** ISO time it was asked (the server's `ts` for an earlier one). */
  ts: string;
}

/** Who the help bot answers about: an account id, or null = General. */
export type Focus = string | null;

/** An earlier session's turn (GET /admin/assistant/history). */
export interface EarlierTurn extends Turn {
  answer: string;
  rowId: number;
}

/** One row of GET /admin/assistant/history (service/assistant_api.py `_turn_row`). */
export interface HistoryRow {
  id: number;
  ts: string;
  question: string;
  answer: string;
  error: string | null;
  account_id: string | null;
  /** Always set by a current server (rows from before threads are backfilled). */
  thread_id: string | null;
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
  /** The thread on screen; null = home (a new chat, not asked yet). */
  active: string | null;
  focus: Focus;
  /** The app switcher's focus as last seen; undefined before the first `scope`. */
  appFocus: Focus | undefined;
  /** The switcher moved off `focus` while a started thread locked it. */
  held: boolean;
  roster: Roster;
}

/** Who the widget may focus: the owned account ids (null while they load)
 *  and whether the asker is a signed-in user (General is theirs). */
export interface Roster {
  ids: string[] | null;
  isUser: boolean;
}

/** How many earlier turns the panel asks the server for: all it keeps
 *  (assistant_api MAX_TURNS_KEPT), so no thread is cut off the list. */
export const HISTORY_LIMIT = 500;

export type AssistantAction =
  | { type: "hydrate"; open: boolean }
  | { type: "toggle" }
  /** `thread`: the open one, or the new one this first ask names (the provider's, made once).
   *  `accountId`: the focus the ask went out with (sendFocusOf). */
  | { type: "asked"; id: number; question: string; ts: string; thread: string; accountId: Focus }
  | { type: "route"; onHelpPage: boolean }
  | { type: "settled"; id: number; answer: string; error: string | null; rowId: number | null }
  | { type: "history_requested" }
  | { type: "history_loaded"; turns: EarlierTurn[] }
  | { type: "history_failed" }
  /** The app's model switcher: a model, or null = all models (→ General). */
  | { type: "scope"; focus: Focus }
  | { type: "pick"; focus: Focus }
  | { type: "new_chat" }
  | { type: "open_thread"; thread: string; focus: Focus }
  /** The owned accounts (null while loading) and whether the asker is a user. */
  | { type: "roster"; ids: string[] | null; isUser: boolean };

export const initialAssistantState: AssistantCore = {
  hydrated: false,
  open: false,
  turns: [],
  unread: false,
  onHelpPage: false,
  history: [],
  historyStatus: "idle",
  active: null,
  focus: null,
  appFocus: undefined,
  held: false,
  roster: { ids: null, isUser: false },
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
      // The thread is about the account the ask went out with: lock it.
      return {
        ...state,
        active: action.thread,
        focus: action.accountId,
        turns: [...state.turns, {
          id: action.id, question: action.question, answer: null, error: null, rowId: null,
          thread: action.thread, accountId: action.accountId, ts: action.ts,
        }],
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
    case "scope": {
      // Change-only: a re-sent switcher value must not undo a manual pick.
      if (state.appFocus !== undefined && action.focus === state.appFocus) return state;
      if (state.active === null) return { ...state, appFocus: action.focus, focus: action.focus, held: false };
      return { ...state, appFocus: action.focus, held: comparable(action.focus, state.roster) !== comparable(state.focus, state.roster) };
    }
    case "pick": {
      if (state.active === null) {
        return action.focus === state.focus && !state.held ? state : { ...state, focus: action.focus, held: false };
      }
      if (comparable(action.focus, state.roster) === comparable(state.focus, state.roster)) {
        return state.held ? { ...state, held: false } : state;
      }
      // A started thread is about its focus: another one is a new chat.
      return { ...state, focus: action.focus, held: false, active: null };
    }
    case "new_chat": {
      if (state.active === null) return state;
      // Back to the app's model (raw) unless a manual pick differs from it.
      const app = state.appFocus;
      const follow = app !== undefined
        && (state.held || comparable(app, state.roster) === comparable(state.focus, state.roster));
      return { ...state, active: null, held: false, focus: follow ? app : state.focus };
    }
    case "open_thread":
      return guardThread({ ...state, active: action.thread, focus: action.focus, held: false });
    case "roster": {
      const roster: Roster = { ids: action.ids, isUser: action.isUser };
      if (sameRoster(state.roster, roster)) return state;
      // The focus is never rewritten here (resolved on read).
      const s = guardThread({ ...state, roster });
      // A hold the new roster resolves away is no offer any more (never raised here).
      return s.held && !heldOf(s) ? { ...s, held: false } : s;
    }
  }
}

const sameRoster = (a: Roster, b: Roster) => a.isUser === b.isUser
  && (a.ids === b.ids || (a.ids !== null && b.ids !== null
    && a.ids.length === b.ids.length && a.ids.every((id, i) => id === b.ids![i])));

/** General is on offer to a signed-in user only (the server 401s a chatter's
 *  account-less ask). */
export const canGeneralOf = (r: Roster): boolean => r.isUser;

/** The server would answer about it: an owned account (any, while the roster
 *  loads — assert_account_owned gates), or General where it is on offer. */
export function focusValid(focus: Focus, r: Roster): boolean {
  if (focus === null) return canGeneralOf(r);
  return r.ids === null || r.ids.includes(focus);
}

/** The focus an ask goes out with: a valid one as is; else the first account,
 *  else General where on offer; undefined (send disabled) for a chatter with
 *  General while the roster loads, or with no account at all. */
export function resolveFocus(focus: Focus, r: Roster): Focus | undefined {
  if (focusValid(focus, r)) return focus;
  if (r.ids === null) return undefined;
  return r.ids[0] ?? (r.isUser ? null : undefined);
}

/** A focus as compared: resolved once the roster is known, raw before. */
function comparable(focus: Focus, r: Roster): Focus {
  const resolved = resolveFocus(focus, r);
  return resolved === undefined ? focus : resolved;
}

/** The switcher's focus, resolved, differs from a started thread's. */
const heldOf = (s: AssistantCore): boolean =>
  s.active !== null && s.appFocus !== undefined && comparable(s.appFocus, s.roster) !== comparable(s.focus, s.roster);

/** A started thread is about its focus: one the roster lacks is an explicit
 *  new chat on the app's model, never a silent switch of the thread's model. */
function guardThread(s: AssistantCore): AssistantCore {
  if (s.active === null || s.roster.ids === null || focusValid(s.focus, s.roster)) return s;
  return { ...s, active: null, held: false, focus: s.appFocus !== undefined ? s.appFocus : s.focus };
}

/** The focus the next ask goes out with (undefined: it cannot go yet). */
export const sendFocusOf = (s: AssistantCore): Focus | undefined => resolveFocus(s.focus, s.roster);

/** The app switcher's focus as the widget would resolve it (the "<model> in app" offer). */
export const appFocusOf = (s: AssistantCore): Focus =>
  s.appFocus === undefined ? null : comparable(s.appFocus, s.roster);

/** The history GET's rows (newest first) as oldest-first turns. Ids go
 *  negative so they can never collide with this session's (0, 1, 2…). The
 *  server gives every row a thread; `legacy-<id>` only guards a NULL from a
 *  server older than that. */
export function historyFromRows(body: { turns: HistoryRow[] }): EarlierTurn[] {
  return [...body.turns].reverse().map((r) => ({
    id: -1 - r.id, rowId: r.id, question: r.question, answer: r.answer, error: r.error,
    ts: r.ts, thread: r.thread_id ?? `legacy-${r.id}`, accountId: r.account_id,
  }));
}

/** One conversation in the "Earlier conversations" list. */
export interface ThreadSummary {
  id: string;
  focus: Focus;
  /** Its first question. */
  title: string;
  count: number;
  /** ISO time of its newest turn. */
  last: string;
}

/** Every thread with a turn, newest activity first. `history` is
 *  oldest-first and this session's `turns` come after it. */
export function threadsOf(history: Turn[], turns: Turn[]): ThreadSummary[] {
  const by = new Map<string, ThreadSummary>();
  for (const t of [...history, ...turns]) {
    const s = by.get(t.thread);
    if (s) {
      s.count += 1;
      if (t.ts > s.last) s.last = t.ts;
    } else {
      by.set(t.thread, { id: t.thread, focus: t.accountId, title: t.question, count: 1, last: t.ts });
    }
  }
  return [...by.values()].sort((a, b) => Date.parse(b.last) - Date.parse(a.last));
}

/** The thread's turns, in order (earlier sessions' first). */
export const turnsOf = (thread: string | null, history: Turn[], turns: Turn[]): Turn[] =>
  thread === null ? [] : [...history, ...turns].filter((t) => t.thread === thread);

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DAY_YEAR_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** Newest-first threads in local-day sections by their last turn: "Today",
 *  "Yesterday", "Nov 5" (a past year adds it). */
export function groupByDay(threads: ThreadSummary[], now: Date): Array<{ label: string; threads: ThreadSummary[] }> {
  const today = dayKey(now);
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  const yesterday = dayKey(y);
  const out: Array<{ key: string; label: string; threads: ThreadSummary[] }> = [];
  for (const t of threads) {
    const d = new Date(t.last);
    const key = dayKey(d);
    if (out[out.length - 1]?.key !== key) {
      const label = key === today ? "Today"
        : key === yesterday ? "Yesterday"
        : (d.getFullYear() === now.getFullYear() ? DAY_FMT : DAY_YEAR_FMT).format(d);
      out.push({ key, label, threads: [] });
    }
    out[out.length - 1].threads.push(t);
  }
  return out.map(({ label, threads }) => ({ label, threads }));
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
