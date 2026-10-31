/**
 * The EventBus's rules (lib/events.ts is the I/O shell) as pure transitions:
 * `decide(state, input)` for what the shell observed, `follow(state, followUp,
 * ready)` for the rest of a decision; each returns `{ state, effects }`. The
 * shell turns EventSource callbacks, idle mode and timers into inputs and
 * performs the effects in the order given.
 *
 *   • Scope: `SetScope` (a new scope only) arms a 50 ms restart, so a rapid
 *     model-switcher click reopens once; `RestartFired` reopens WITHOUT the last
 *     event id (a fresh stream). While paused a scope change only records the
 *     scope and `Resume` reopens it from the last event id (ids are relay-global
 *     `<epoch>.<seq>`, service/events.py, so the relay replays across scopes).
 *   • Idle mode: `Pause` tears the stream down and keeps it down; `Resume`
 *     reopens from the last event id, so the relay replays what the tab missed
 *     (or sends `resync`).
 *   • Backoff: when the browser gives up on the current socket (an error with
 *     readyState CLOSED, a non-200) and no retry is armed, a retry is armed
 *     after `retryMs`, which then doubles up to RETRY_MAX_MS; `Opened` resets it
 *     to RETRY_MIN_MS. The retry reopens from the last event id.
 *   • Every reopen first applies the queued events (they came before anything
 *     from the next stream), cancels an armed retry, closes the socket and
 *     forces the freshness window shut.
 *   • Connected = socket OPEN and a frame (pings too) within STALE_MS; socket
 *     OPEN alone is not enough (a hung upstream pump). `NotifyConnected` only on
 *     a change; `StaleTick` re-checks it on a timer.
 *   • Adaptive apply: each frame's events (batch members counted) apply at once
 *     while the arrival rate over the last RATE_SPAN_MS is <= HOT_EVENTS_PER_S
 *     and no flush is armed; else they queue (arrival order) for one `Flush`:
 *     the next animation frame, or APPLY_WINDOW_MS where frames do not run (a
 *     hidden tab). A flood costs at most one list update per painted frame; the
 *     relay already batches a hot stream into 100-250 ms frames, so a longer
 *     window only adds latency (a fixed 250 ms one was ~260 ms of every DM's
 *     time to screen).
 *
 * Listeners may call back into the bus (a listener that pauses). The shell runs
 * such a call at once, as a nested `decide`, so nothing is ever decided past an
 * effect that runs listeners (`Apply`, `NotifyConnected`): what follows one is a
 * `Then`, a follow-up the shell hands to `follow` right after it, on the state
 * the listeners left and with the socket's readyState as it is then. A pause
 * from inside a reconnect's flush therefore opens no socket, and `__error`
 * carries the readyState its state listeners left.
 *
 * Timers are tokens: an `After` effect carries the input to send, whose token
 * only acts while armed. A disarmed timer that still fires is a no-op (what
 * clearTimeout was). Sockets are generations: each `Open` gets `gen`, every
 * teardown moves `gen` on, so only the current socket's give-up arms a retry
 * and only the latest teardown's `Connect` opens one.
 *
 * The socket's readyState is the browser's: inputs that read it carry it
 * (`ready`, the current socket's, null = none); `follow` gets it from the shell.
 */

export type Scope = "all" | `model:${string}`;

export interface EventEnvelope {
  __account_id?: string;
  __account_name?: string;
  __account_color?: string;
  [key: string]: unknown;
}

// 2.25× the 20 s backend heartbeat: two missed pings absorb network/GC
// hiccups before isConnected degrades. Tighter than this is jittery;
// looser delays the offline-poll kick-in.
export const STALE_MS = 45_000;
// Our own reopen after the browser gives up: 5 s, doubling to 60 s.
export const RETRY_MIN_MS = 5_000;
export const RETRY_MAX_MS = 60_000;
// Scope-switch debounce.
export const RESTART_MS = 50;
// Adaptive apply (header). Knobs: NEXT_PUBLIC_SSE_HOT_EVPS,
// NEXT_PUBLIC_SSE_APPLY_WINDOW_MS. A quiet inbox (≤ 2 ev/s) stays instant;
// a hot one applies on the next frame, or after 250 ms where frames do not
// run (hidden tab), well inside the 2 s SSE-lag budget.
export const HOT_EVENTS_PER_S = envNum(process.env.NEXT_PUBLIC_SSE_HOT_EVPS, 2);
export const APPLY_WINDOW_MS = envNum(process.env.NEXT_PUBLIC_SSE_APPLY_WINDOW_MS, 250);
export const RATE_SPAN_MS = 1_000;

// EventSource.readyState values (the spec's; also where EventSource is absent).
export const OPEN = 1;
export const CLOSED = 2;

function envNum(v: string | undefined, fallback: number): number {
  const n = Number(v);
  return v != null && v !== "" && Number.isFinite(n) && n >= 0 ? n : fallback;
}

export type Queued = [string, EventEnvelope];

export interface BusState {
  scope: Scope | null;
  paused: boolean;
  /** The current socket's generation (the next one's while there is none). */
  gen: number;
  /** The browser's last-seen event id, the resume point. */
  lastEventId: string;
  /** Last frame (any, pings too); 0 = freshness window shut. */
  lastEventAt: number;
  /** Last value sent as NotifyConnected. */
  reported: boolean;
  retryMs: number;
  /** Armed timers' tokens (null = none armed). */
  retry: number | null;
  restart: number | null;
  /** The armed flush and the events waiting for it, in arrival order. */
  flush: { token: number; events: Queued[] } | null;
  nextToken: number;
  /** [arrivedAt, count] over the last RATE_SPAN_MS. */
  arrivals: [number, number][];
}

export const initialBusState: BusState = {
  scope: null, paused: false, gen: 1, lastEventId: "", lastEventAt: 0, reported: false,
  retryMs: RETRY_MIN_MS, retry: null, restart: null, flush: null, nextToken: 1, arrivals: [],
};

export type BusInput =
  | { type: "SetScope"; scope: Scope }
  | { type: "RestartFired"; token: number }
  | { type: "Pause" }
  | { type: "Resume" }
  | { type: "Opened"; now: number; ready: number | null }
  /** `gen`: the erroring socket's; `ready`: the current socket's readyState. */
  | { type: "Errored"; now: number; ready: number | null; gen: number }
  /** Any frame, pings included: `id` its lastEventId ("" = none), `events` what it carries for listeners. */
  | { type: "Frame"; now: number; ready: number | null; id: string; events: Queued[] }
  | { type: "RetryFired"; token: number }
  | { type: "StaleTick"; now: number; ready: number | null }
  | { type: "Flush"; token: number };

/** The rest of a decision (`Then`), decided by `follow` after the listeners before it ran. */
export type FollowUp =
  | { type: "Teardown"; resume: boolean }
  /** `gen`: the teardown's; a later teardown (a nested pause/resume) supersedes it. */
  | { type: "Connect"; resume: boolean; gen: number }
  | { type: "Admit"; now: number; events: Queued[] }
  /** `gen`: the erroring socket's. */
  | { type: "ReportError"; gen: number }
  | { type: "MaybeRetry"; gen: number };

export type BusEffect =
  /** `lastEventId`: the resume point ("" = none). */
  | { type: "Open"; scope: Scope; lastEventId: string; gen: number }
  | { type: "Close" }
  /** Send `fire` after `ms`; with `frame`, also on the next animation frame (the first to fire cancels the other). */
  | { type: "After"; ms: number; fire: BusInput; frame?: true }
  /** Emit to listeners: one event as is, several inside one notify batch. */
  | { type: "Apply"; events: Queued[] }
  | { type: "NotifyConnected"; connected: boolean }
  /** Hand `event` to `follow` now, after the effects before it ran. */
  | { type: "Then"; event: FollowUp };

export interface Decision {
  state: BusState;
  effects: BusEffect[];
}

/** OPEN socket and a frame within STALE_MS. */
export function isConnected(s: BusState, ready: number | null, now: number): boolean {
  return ready === OPEN && now - s.lastEventAt < STALE_MS;
}

/** The stream's URL. `token` is the share token, `lastEventId` the resume point ("" = none). */
export function eventsUrl(scope: Scope, token: string | null, lastEventId: string): string {
  const qs = new URLSearchParams({ scope });
  if (token) qs.set("t", token);
  if (lastEventId) qs.set("last_event_id", lastEventId);
  return `/events?${qs.toString()}`;
}

export function decide(state: BusState, ev: BusInput): Decision {
  switch (ev.type) {
    case "SetScope": {
      if (state.scope === ev.scope) return none(state);
      const token = state.nextToken;
      return {
        state: { ...state, scope: ev.scope, restart: token, nextToken: token + 1 },
        effects: [{ type: "After", ms: RESTART_MS, fire: { type: "RestartFired", token } }],
      };
    }
    case "RestartFired":
      if (state.restart !== ev.token) return none(state);
      return reconnect({ ...state, restart: null }, false);
    case "Pause":
      if (state.paused) return none(state);
      return reconnect({ ...state, paused: true }, false);
    case "Resume":
      if (!state.paused) return none(state);
      return reconnect({ ...state, paused: false }, true);
    case "RetryFired":
      if (state.retry !== ev.token) return none(state);
      return reconnect(state, true);
    case "Opened":
      // Deliberately no freshness bump: a reopened socket over a hung pump stays "disconnected".
      return notify({ ...state, retryMs: RETRY_MIN_MS }, ev.ready, ev.now);
    case "Errored":
      // Freshness shut at once, even while the browser retries underneath; listeners get `__error`.
      return then(notify({ ...state, lastEventAt: 0 }, ev.ready, ev.now), { type: "ReportError", gen: ev.gen });
    case "Frame":
      return then(
        notify({ ...state, lastEventId: ev.id || state.lastEventId, lastEventAt: ev.now }, ev.ready, ev.now),
        { type: "Admit", now: ev.now, events: ev.events });
    case "StaleTick":
      return notify(state, ev.ready, ev.now);
    case "Flush":
      if (state.flush?.token !== ev.token) return none(state);
      return flushPending(state);
  }
}

/** `ready`: the current socket's readyState now (null = none). */
export function follow(state: BusState, ev: FollowUp, ready: number | null): Decision {
  switch (ev.type) {
    case "Teardown": {
      // Freshness shut: "disconnected" until the first frame on the new socket.
      const gen = state.gen + 1;
      const d = report({ ...state, gen, lastEventAt: 0 }, false);
      return then({ state: d.state, effects: [{ type: "Close" }, ...d.effects] }, { type: "Connect", resume: ev.resume, gen });
    }
    case "Connect":
      if (state.gen !== ev.gen || !state.scope || state.paused) return none(state);
      return {
        state,
        effects: [{ type: "Open", scope: state.scope, lastEventId: ev.resume ? state.lastEventId : "", gen: state.gen }],
      };
    case "Admit":
      return admit(state, ev.events, ev.now);
    case "ReportError":
      return then(
        { state, effects: [{ type: "Apply", events: [["__error", ready === null ? {} : { readyState: ready }]] }] },
        { type: "MaybeRetry", gen: ev.gen });
    case "MaybeRetry": {
      // CLOSED on the current socket: the browser will not retry (a non-200 answer).
      if (ev.gen !== state.gen || ready !== CLOSED || state.retry !== null) return none(state);
      const token = state.nextToken;
      return {
        state: { ...state, retry: token, nextToken: token + 1, retryMs: Math.min(state.retryMs * 2, RETRY_MAX_MS) },
        effects: [{ type: "After", ms: state.retryMs, fire: { type: "RetryFired", token } }],
      };
    }
  }
}

function none(state: BusState): Decision {
  return { state, effects: [] };
}

function then(d: Decision, event: FollowUp): Decision {
  return { state: d.state, effects: [...d.effects, { type: "Then", event }] };
}

/** Tear down + reopen (unless paused or scopeless). `resume`: from the last event id.
 *  Events already received apply first, before anything from the next stream. */
function reconnect(state: BusState, resume: boolean): Decision {
  return then(flushPending({ ...state, retry: null }), { type: "Teardown", resume });
}

function notify(s: BusState, ready: number | null, now: number): Decision {
  return report(s, isConnected(s, ready, now));
}

function report(s: BusState, connected: boolean): Decision {
  if (connected === s.reported) return none(s);
  return { state: { ...s, reported: connected }, effects: [{ type: "NotifyConnected", connected }] };
}

/** Apply now while the stream is quiet; above HOT_EVENTS_PER_S (or while a
 *  flush is armed, so order holds) queue for the armed flush. */
function admit(s: BusState, events: Queued[], now: number): Decision {
  if (!events.length) return none(s);
  const arrivals = [...s.arrivals, [now, events.length] as [number, number]];
  let drop = 0;
  while (drop < arrivals.length && now - arrivals[drop][0] >= RATE_SPAN_MS) drop++;
  const recent = arrivals.slice(drop);
  if (s.flush !== null) {
    return { state: { ...s, arrivals: recent, flush: { ...s.flush, events: [...s.flush.events, ...events] } }, effects: [] };
  }
  let rate = 0;
  for (const [, n] of recent) rate += n;
  if (rate <= HOT_EVENTS_PER_S) return { state: { ...s, arrivals: recent }, effects: [{ type: "Apply", events }] };
  const token = s.nextToken;
  return {
    state: { ...s, arrivals: recent, flush: { token, events }, nextToken: token + 1 },
    effects: [{ type: "After", ms: APPLY_WINDOW_MS, fire: { type: "Flush", token }, frame: true }],
  };
}

function flushPending(s: BusState): Decision {
  if (s.flush === null) return none(s);
  return { state: { ...s, flush: null }, effects: [{ type: "Apply", events: s.flush.events }] };
}
