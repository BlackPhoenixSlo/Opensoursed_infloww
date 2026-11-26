import { loginCount } from "@/lib/loginPaste";
import { stateText, TERMINAL, type RemoteLoginState } from "@/components/setup/remoteLogin";
import { DEFAULT_PLATFORM, PLATFORM_NAME } from "@/lib/platform";

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

export interface Stored {
  queueId: string | null;
  seen: QueueEntry[];
}

export interface LoginQueue {
  hydrated: boolean;
  text: string;
  queueId: string | null;
  view: QueueView | null;
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
  | { type: "startFailed"; message: string; badLines: BadLine[]; current: QueueView | null }
  | { type: "polled"; view: QueueView }
  | { type: "lost"; queueId: string }
  | { type: "reset" };

export const INITIAL: LoginQueue = {
  hydrated: false, text: "", queueId: null, view: null, seen: [], badLines: [], starting: false, error: null,
  interrupted: false,
};

export const MAX_PASTE = 64 * 1024;
export const POLL_MS = 1500;

const opened = (s: LoginQueue, view: QueueView): LoginQueue =>
  ({ ...s, queueId: view.id, view, seen: view.entries, interrupted: false });
const adopted = (s: LoginQueue, view: QueueView | null): LoginQueue | null =>
  view?.state === "running" && !isRunning(s) ? { ...opened(s, view), starting: false, error: null } : null;

export function loginQueueReducer(s: LoginQueue, a: Action): LoginQueue {
  switch (a.type) {
    case "hydrate":
      return s.hydrated ? s : { ...s, hydrated: true, queueId: a.stored.queueId, seen: a.stored.queueId ? a.stored.seen : [] };
    case "link":
      return !s.hydrated || a.queueId === s.queueId
        ? s : { ...s, queueId: a.queueId, view: null, seen: [], badLines: [], error: null, interrupted: false };
    case "adopt":
      return adopted(s, a.view) ?? s;
    case "edit":
      return { ...s, text: a.text.slice(0, MAX_PASTE) };
    case "start":
      return canSubmit(s) ? { ...s, starting: true, error: null, badLines: [] } : s;
    case "started":
      return { ...opened(s, a.view), starting: false, text: "", badLines: a.badLines };
    case "startFailed":
      return adopted(s, a.current) ?? { ...s, starting: false, error: a.message, badLines: a.badLines };
    case "polled":
      return a.view.id === s.queueId && !s.interrupted ? { ...s, view: a.view, seen: a.view.entries } : s;
    case "lost":
      return a.queueId === s.queueId ? { ...s, interrupted: true } : s;
    case "reset":
      return { ...s, queueId: null, view: null, seen: [], badLines: [], error: null, interrupted: false };
  }
}

export const isRunning = (s: LoginQueue): boolean =>
  !!s.queueId && !s.interrupted && (s.view === null || s.view.state === "running");

export const canSubmit = (s: LoginQueue): boolean =>
  s.hydrated && !s.starting && !isRunning(s) && loginCount(s.text) > 0;

export const buildPayload = (s: LoginQueue): { text: string } | null => (canSubmit(s) ? { text: s.text } : null);

export const entriesOf = (s: LoginQueue): QueueEntry[] => s.view?.entries ?? s.seen;

export const lookForQueue = (status: number | null): boolean => status === null || status === 409 || status >= 500;

const stillGoing = (v: QueueView): boolean => v.state === "running" || v.entries.some((e) => !TERMINAL.has(e.state));

export const isPolling = (s: LoginQueue): boolean =>
  !!s.queueId && !s.interrupted && (s.view === null || stillGoing(s.view));

export const pollEvery = (data: QueueView | undefined, lost: boolean): number | false =>
  lost || (data !== undefined && !stillGoing(data)) ? false : POLL_MS;

export const QUEUE_SITE = PLATFORM_NAME[DEFAULT_PLATFORM];
const QUEUE_STATE_TEXT = stateText(QUEUE_SITE);

export function entryNote(e: QueueEntry, interrupted: boolean): string {
  const open = e.state !== "done" && e.state !== "error" && e.state !== "cancelled";
  if (interrupted && open) return "Not finished. Paste it again.";
  switch (e.state) {
    case "waiting": return "Waiting for its turn";
    case "done": return e.account_id ? `Logged in (account ${e.account_id})` : "Logged in";
    case "error": return `Not logged in: ${e.message || "failed"}`;
    case "cancelled": return "Cancelled";
    default: return QUEUE_STATE_TEXT[e.state] ?? e.message;
  }
}

export function badLinesOf(body: unknown): BadLine[] {
  const detail = (body as { detail?: { bad_lines?: unknown } } | null)?.detail;
  const lines = detail && typeof detail === "object" ? detail.bad_lines : undefined;
  return Array.isArray(lines) ? lines.filter((b): b is BadLine => typeof b?.line === "number") : [];
}

export function storedOf(s: LoginQueue): string | null {
  if (!s.queueId) return null;
  return JSON.stringify({ id: s.queueId, entries: s.seen.map((e) => ({ email: e.email, state: e.state })) });
}

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
