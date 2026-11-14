/**
 * The pasted-logins card's state (LoginQueueCard.tsx; ultra-mode ticket 11; relay: service/login_queue.py): the paste
 * being typed, the start (POST /admin/login/remote/queue) in flight or refused with its bad lines, the open queue's id
 * (kept per browser and in `?queue=` so a reload or a notice's link resumes it), its last polled view and the emails +
 * states last seen (kept per browser too, never a password, so a queue the relay no longer has still lists what was
 * done and what was not). Pure; the card only dispatches. `canSubmit` / `buildPayload` gate Start; a 404 on the open
 * queue shows it `interrupted` (the relay restarted, or a newer paste replaced it). With no queue open (`adopt`), or
 * after a start that may have made one (`lookForQueue`: no answer, a 409, a 5xx; `startFailed.current`), the card opens
 * the owner's running queue (GET /admin/login/remote/queue); the start's error shows only when there is none. The
 * open queue is polled until it and each of its entries ended (a stopped queue's job still winds down). The paste is
 * cleared once the relay has it: it holds passwords.
 */
import { loginCount } from "@/lib/loginPaste";
import { STATE_TEXT, TERMINAL, type RemoteLoginState } from "@/components/setup/remoteLogin";

export type EntryState = "waiting" | RemoteLoginState;

export interface QueueEntry {
  email: string;
  state: EntryState;
  job_id: string | null;
  message: string;
  live_view_url: string | null;
  account_id: string | null;
}

export interface QueueView {
  id: string;
  state: "running" | "done" | "cancelled";
  entries: QueueEntry[];
}

export interface BadLine { line: number; reason: string }

/** What the browser keeps of the open queue: its id and each entry's email + state (no password ever reaches it). */
export interface Stored {
  queueId: string | null;
  seen: QueueEntry[];
}

export interface LoginQueue {
  /** The stored / linked queue id has been read (persisting before that would wipe it). */
  hydrated: boolean;
  text: string;
  queueId: string | null;
  view: QueueView | null;
  /** The open queue's entries as last seen (stored), listed until a poll lands and after a 404. */
  seen: QueueEntry[];
  badLines: BadLine[];
  starting: boolean;
  error: string | null;
  interrupted: boolean;
}

export type Action =
  | { type: "hydrate"; stored: Stored }
  | { type: "link"; queueId: string }
  | { type: "adopt"; view: QueueView }
  | { type: "edit"; text: string }
  | { type: "start" }
  | { type: "started"; view: QueueView; badLines: BadLine[] }
  /** `current`: the owner's queue read after the failure (null: none, or not looked for). */
  | { type: "startFailed"; message: string; badLines: BadLine[]; current: QueueView | null }
  | { type: "polled"; view: QueueView }
  | { type: "lost"; queueId: string }
  | { type: "reset" };

export const INITIAL: LoginQueue = {
  hydrated: false, text: "", queueId: null, view: null, seen: [], badLines: [], starting: false, error: null,
  interrupted: false,
};

/** service/remote_login_api.MAX_PASTE. */
export const MAX_PASTE = 64 * 1024;
export const POLL_MS = 1500;

const opened = (s: LoginQueue, view: QueueView): LoginQueue =>
  ({ ...s, queueId: view.id, view, seen: view.entries, interrupted: false });
/** The owner's running queue opened, none running here; null when that does not apply. */
const adopted = (s: LoginQueue, view: QueueView | null): LoginQueue | null =>
  view?.state === "running" && !isRunning(s) ? { ...opened(s, view), starting: false, error: null } : null;

export function loginQueueReducer(s: LoginQueue, a: Action): LoginQueue {
  switch (a.type) {
    case "hydrate":
      return s.hydrated ? s : { ...s, hydrated: true, queueId: a.stored.queueId, seen: a.stored.queueId ? a.stored.seen : [] };
    case "link":
      // A notice's link to another queue than the one shown: show that one.
      return !s.hydrated || a.queueId === s.queueId
        ? s : { ...s, queueId: a.queueId, view: null, seen: [], badLines: [], error: null, interrupted: false };
    case "adopt":
      // The owner's running queue, found with none running here: open it.
      return adopted(s, a.view) ?? s;
    case "edit":
      return { ...s, text: a.text.slice(0, MAX_PASTE) };
    case "start":
      return canSubmit(s) ? { ...s, starting: true, error: null, badLines: [] } : s;
    case "started":
      return { ...opened(s, a.view), starting: false, text: "", badLines: a.badLines };
    case "startFailed":
      // The start's answer lost, or a 409: a running queue found opens instead of the error.
      return adopted(s, a.current) ?? { ...s, starting: false, error: a.message, badLines: a.badLines };
    case "polled":
      return a.view.id === s.queueId && !s.interrupted ? { ...s, view: a.view, seen: a.view.entries } : s;
    case "lost":
      return a.queueId === s.queueId ? { ...s, interrupted: true } : s;
    case "reset":
      return { ...s, queueId: null, view: null, seen: [], badLines: [], error: null, interrupted: false };
  }
}

/** The open queue is still logging in (or not read yet): poll it, no new paste. */
export const isRunning = (s: LoginQueue): boolean =>
  !!s.queueId && !s.interrupted && (s.view === null || s.view.state === "running");

/** Start: hydrated, nothing in flight or running, at least one email<separator>password line. */
export const canSubmit = (s: LoginQueue): boolean =>
  s.hydrated && !s.starting && !isRunning(s) && loginCount(s.text) > 0;

export const buildPayload = (s: LoginQueue): { text: string } | null => (canSubmit(s) ? { text: s.text } : null);

/** The rows the card lists: the live view's, else the last seen ones. */
export const entriesOf = (s: LoginQueue): QueueEntry[] => s.view?.entries ?? s.seen;

/** A failed start after which the owner may have a running queue: no answer, a 409 (one runs), a 5xx (maybe taken).
 *  Another 4xx (bad paste, signed out, too big) refused it for sure. */
export const lookForQueue = (status: number | null): boolean => status === null || status === 409 || status >= 500;

/** The queue or one of its entries has not ended (a stopped queue's running job winds down after the stop). */
const stillGoing = (v: QueueView): boolean => v.state === "running" || v.entries.some((e) => !TERMINAL.has(e.state));

/** Poll the open queue: not read yet, or not ended; never once it is gone (404). */
export const isPolling = (s: LoginQueue): boolean =>
  !!s.queueId && !s.interrupted && (s.view === null || stillGoing(s.view));

/** Poll again in POLL_MS until the queue is gone (404) or a read shows it and each entry ended; a failed read keeps
 *  polling. */
export const pollEvery = (data: QueueView | undefined, lost: boolean): number | false =>
  lost || (data !== undefined && !stillGoing(data)) ? false : POLL_MS;

/** One entry's line on the card; `interrupted` marks what was still going when the queue left the relay. */
export function entryNote(e: QueueEntry, interrupted: boolean): string {
  const open = e.state !== "done" && e.state !== "error" && e.state !== "cancelled";
  if (interrupted && open) return "Not finished. Paste it again.";
  switch (e.state) {
    case "waiting": return "Waiting for its turn";
    case "done": return e.account_id ? `Logged in (account ${e.account_id})` : "Logged in";
    case "error": return `Not logged in: ${e.message || "failed"}`;
    case "cancelled": return "Cancelled";
    default: return STATE_TEXT[e.state] ?? e.message;
  }
}

/** The relay's 400 detail for a paste with no login line: {message, bad_lines}. */
export function badLinesOf(body: unknown): BadLine[] {
  const detail = (body as { detail?: { bad_lines?: unknown } } | null)?.detail;
  const lines = detail && typeof detail === "object" ? detail.bad_lines : undefined;
  return Array.isArray(lines) ? lines.filter((b): b is BadLine => typeof b?.line === "number") : [];
}

/** The browser's entry for `s`: the open queue's id + each seen entry's email and state, or null (nothing open). */
export function storedOf(s: LoginQueue): string | null {
  if (!s.queueId) return null;
  return JSON.stringify({ id: s.queueId, entries: s.seen.map((e) => ({ email: e.email, state: e.state })) });
}

/** The stored entry back; anything unreadable is nothing. */
export function parseStored(raw: string | null): Stored {
  if (!raw) return { queueId: null, seen: [] };
  let v: unknown;
  try { v = JSON.parse(raw); } catch { return { queueId: null, seen: [] }; }
  const o = v as { id?: unknown; entries?: unknown } | null;
  if (!o || typeof o !== "object" || typeof o.id !== "string" || !o.id) return { queueId: null, seen: [] };
  const seen = (Array.isArray(o.entries) ? o.entries : [])
    .filter((e): e is { email: string; state: EntryState } => typeof e?.email === "string" && typeof e?.state === "string")
    .map((e): QueueEntry => ({ email: e.email, state: e.state, job_id: null, message: "", live_view_url: null, account_id: null }));
  return { queueId: o.id, seen };
}
