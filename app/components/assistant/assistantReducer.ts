import { RelayError } from "@/lib/relay";

export interface Turn {
  id: number;
  question: string;
  answer: string | null;
  error: string | null;
  rowId: number | null;
  thread: string;
  accountId: Focus;
  ts: string;
  fromDo?: true;
  about?: string;
}

export type Focus = string | null;

export interface EarlierTurn extends Turn {
  answer: string;
  rowId: number;
}

export interface HistoryRow {
  id: number;
  ts: string;
  question: string;
  answer: string;
  error: string | null;
  account_id: string | null;
  thread_id: string | null;
}

export type HistoryStatus = "idle" | "loading" | "loaded" | "failed";

export interface AskResponse {
  answer: string;
  error: string | null;
  id: number | null;
  about?: string | null;
}

export interface AssistantCore {
  hydrated: boolean;
  open: boolean;
  turns: Turn[];
  unread: boolean;
  onHelpPage: boolean;
  history: EarlierTurn[];
  historyStatus: HistoryStatus;
  active: string | null;
  focus: Focus;
  appFocus: Focus | undefined;
  held: boolean;
  roster: Roster;
  principal: Principal | undefined;
}

export type Principal = string | null;

export interface Roster {
  ids: string[] | null;
  isUser: boolean;
}

export const HISTORY_LIMIT = 500;

export type AssistantAction =
  | { type: "hydrate"; open: boolean }
  | { type: "toggle" }
  | { type: "asked"; id: number; question: string; ts: string; thread: string; accountId: Focus; fromDo?: boolean }
  | { type: "route"; onHelpPage: boolean }
  | { type: "settled"; id: number; answer: string; error: string | null; rowId: number | null; about?: string }
  | { type: "history_requested" }
  | { type: "history_loaded"; turns: EarlierTurn[]; principal: Principal | undefined }
  | { type: "history_failed" }
  | { type: "scope"; focus: Focus }
  | { type: "pick"; focus: Focus }
  | { type: "new_chat" }
  | { type: "open_thread"; thread: string; focus: Focus }
  | { type: "roster"; ids: string[] | null; isUser: boolean }
  | { type: "principal"; id: Principal };

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
  principal: undefined,
};

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
        active: action.thread,
        focus: action.accountId,
        turns: [...state.turns, {
          id: action.id, question: action.question, answer: null, error: null, rowId: null,
          thread: action.thread, accountId: action.accountId, ts: action.ts,
          ...(action.fromDo ? { fromDo: true as const } : {}),
        }],
      };
    case "route":
      return state.onHelpPage === action.onHelpPage ? state : { ...state, onHelpPage: action.onHelpPage };
    case "settled": {
      const { id, answer, error, rowId, about } = action;
      if (!state.turns.some((t) => t.id === id)) return state;
      const seen = state.open || state.onHelpPage;
      return {
        ...state,
        turns: state.turns.map((t) => (t.id === id ? { ...t, answer, error, rowId, ...(about ? { about } : {}) } : t)),
        history: state.history.filter((h) => h.rowId !== rowId),
        unread: state.unread || !seen,
      };
    }
    case "history_requested":
      return state.historyStatus === "idle" ? { ...state, historyStatus: "loading" } : state;
    case "history_loaded": {
      if (action.principal !== state.principal) return state;
      const mine = new Set(state.turns.map((t) => t.rowId));
      return { ...state, history: action.turns.filter((h) => !mine.has(h.rowId)), historyStatus: "loaded" };
    }
    case "history_failed":
      return { ...state, historyStatus: "failed" };
    case "scope": {
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
      return { ...state, focus: action.focus, held: false, active: null };
    }
    case "new_chat": {
      if (state.active === null) return state;
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
      const s = guardThread({ ...state, roster });
      return s.held && !heldOf(s) ? { ...s, held: false } : s;
    }
    case "principal": {
      if (state.principal === action.id) return state;
      if (state.principal === undefined) return { ...state, principal: action.id };
      return {
        ...initialAssistantState, hydrated: state.hydrated, open: state.open, onHelpPage: state.onHelpPage,
        appFocus: state.appFocus, focus: state.appFocus ?? null, roster: state.roster, principal: action.id,
      };
    }
  }
}

const sameRoster = (a: Roster, b: Roster) => a.isUser === b.isUser
  && (a.ids === b.ids || (a.ids !== null && b.ids !== null
    && a.ids.length === b.ids.length && a.ids.every((id, i) => id === b.ids![i])));

export const canGeneralOf = (r: Roster): boolean => r.isUser;

export function focusValid(focus: Focus, r: Roster): boolean {
  if (focus === null) return canGeneralOf(r);
  return r.ids === null || r.ids.includes(focus);
}

export function resolveFocus(focus: Focus, r: Roster): Focus | undefined {
  if (focusValid(focus, r)) return focus;
  if (r.ids === null) return undefined;
  return r.ids[0] ?? (r.isUser ? null : undefined);
}

function comparable(focus: Focus, r: Roster): Focus {
  const resolved = resolveFocus(focus, r);
  return resolved === undefined ? focus : resolved;
}

const heldOf = (s: AssistantCore): boolean =>
  s.active !== null && s.appFocus !== undefined && comparable(s.appFocus, s.roster) !== comparable(s.focus, s.roster);

function guardThread(s: AssistantCore): AssistantCore {
  if (s.active === null || s.roster.ids === null || focusValid(s.focus, s.roster)) return s;
  return { ...s, active: null, held: false, focus: s.appFocus !== undefined ? s.appFocus : s.focus };
}

export const sendFocusOf = (s: AssistantCore): Focus | undefined => resolveFocus(s.focus, s.roster);

export const appFocusOf = (s: AssistantCore): Focus =>
  s.appFocus === undefined ? null : comparable(s.appFocus, s.roster);

export function historyFromRows(body: { turns: HistoryRow[] }): EarlierTurn[] {
  return [...body.turns].reverse().map((r) => ({
    // Ids go negative so they never collide with this session's (0, 1, 2…).
    id: -1 - r.id, rowId: r.id, question: r.question, answer: r.answer, error: r.error,
    ts: r.ts, thread: r.thread_id ?? `legacy-${r.id}`, accountId: r.account_id,
  }));
}

export interface ThreadSummary {
  id: string;
  focus: Focus;
  title: string;
  count: number;
  last: string;
}

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

export const turnsOf = (thread: string | null, history: Turn[], turns: Turn[]): Turn[] =>
  thread === null ? [] : [...history, ...turns].filter((t) => t.thread === thread);

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DAY_YEAR_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

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

export const cardFocus = (t: Pick<Turn, "about" | "accountId">): Focus => t.about ?? t.accountId;

type Settled = Extract<AssistantAction, { type: "settled" }>;

export function settledFrom(id: number, r: AskResponse | null | undefined): Settled {
  const answer = (r?.answer || "").trim();
  return {
    type: "settled", id,
    answer: answer || "The assistant came back empty — try asking again.",
    error: answer ? (r?.error ?? null) : "empty_answer",
    rowId: r?.id ?? null,
    ...(typeof r?.about === "string" && r.about ? { about: r.about } : {}),
  };
}

export function settledFromError(id: number, e: unknown): Settled {
  const detail = e instanceof RelayError ? e.message : "";
  return {
    type: "settled", id,
    answer: `Couldn't reach the assistant${detail ? ` (${detail})` : ""} — try again in a moment.`,
    error: "transport",
    rowId: null,
  };
}
