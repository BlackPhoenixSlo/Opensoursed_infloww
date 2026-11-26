export type Scope = "all" | `model:${string}`;

export interface EventEnvelope {
  __account_id?: string;
  __account_name?: string;
  __account_color?: string;
  [key: string]: unknown;
}

// 2.25x the 20 s backend heartbeat: two missed pings absorb hiccups; tighter is jittery, looser delays offline-poll
export const STALE_MS = 45_000;
export const RETRY_MIN_MS = 5_000;
export const RETRY_MAX_MS = 60_000;
export const RESTART_MS = 50;
// A quiet inbox (<=2 ev/s) applies instantly; hot applies per frame, or after 250 ms where frames don't run (hidden tab), inside the 2 s SSE-lag budget
export const HOT_EVENTS_PER_S = envNum(process.env.NEXT_PUBLIC_SSE_HOT_EVPS, 2);
export const APPLY_WINDOW_MS = envNum(process.env.NEXT_PUBLIC_SSE_APPLY_WINDOW_MS, 250);
export const RATE_SPAN_MS = 1_000;

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
  gen: number;
  lastEventId: string;
  lastEventAt: number;
  reported: boolean;
  retryMs: number;
  retry: number | null;
  restart: number | null;
  flush: { token: number; events: Queued[] } | null;
  nextToken: number;
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
  | { type: "Errored"; now: number; ready: number | null; gen: number }
  | { type: "Frame"; now: number; ready: number | null; id: string; events: Queued[] }
  | { type: "RetryFired"; token: number }
  | { type: "StaleTick"; now: number; ready: number | null }
  | { type: "Flush"; token: number };

export type FollowUp =
  | { type: "Teardown"; resume: boolean }
  | { type: "Connect"; resume: boolean; gen: number }
  | { type: "Admit"; now: number; events: Queued[] }
  | { type: "ReportError"; gen: number }
  | { type: "MaybeRetry"; gen: number };

export type BusEffect =
  | { type: "Open"; scope: Scope; lastEventId: string; gen: number }
  | { type: "Close" }
  | { type: "After"; ms: number; fire: BusInput; frame?: true }
  | { type: "Apply"; events: Queued[] }
  | { type: "NotifyConnected"; connected: boolean }
  | { type: "Then"; event: FollowUp };

export interface Decision {
  state: BusState;
  effects: BusEffect[];
}

export function isConnected(s: BusState, ready: number | null, now: number): boolean {
  return ready === OPEN && now - s.lastEventAt < STALE_MS;
}

export function eventsUrl(scope: Scope, token: string | null, lastEventId: string, cell?: string): string {
    // lease=1: this app renews its own View lease; the relay leases all Creators for an unmarked (legacy) stream
  const qs = new URLSearchParams({ scope, lease: "1" });
  if (token) qs.set("t", token);
  if (lastEventId) qs.set("last_event_id", lastEventId);
  if (cell) qs.set("cell", cell);
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
        // deliberately no freshness bump: a reopened socket over a hung pump stays "disconnected"
    case "Opened":
      return notify({ ...state, retryMs: RETRY_MIN_MS }, ev.ready, ev.now);
    case "Errored":
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

export function follow(state: BusState, ev: FollowUp, ready: number | null): Decision {
  switch (ev.type) {
    case "Teardown": {
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
