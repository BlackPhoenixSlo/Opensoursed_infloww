import { describe, expect, it } from "vitest";

import {
  APPLY_WINDOW_MS, CLOSED, HOT_EVENTS_PER_S, OPEN, RATE_SPAN_MS, RESTART_MS, RETRY_MIN_MS, STALE_MS,
  decide, eventsUrl, follow, initialBusState,
  type BusEffect, type BusInput, type BusState, type Decision, type EventEnvelope, type FollowUp, type Queued, type Scope,
} from "./eventBusReducer";

const CONNECTING = 0;
const T = 1_000_000;
const dm = (n: number): Queued => ["api2_chat_message", { n }];
const dms = (...ns: number[]) => ns.map(dm);

/** An input, or one built from the state it meets (a fired timer's token, the current socket's gen). */
type Make = BusInput | ((s: BusState) => BusInput);
const build = (m: Make, s: BusState): BusInput => (typeof m === "function" ? m(s) : m);
const restartFired: Make = (s) => ({ type: "RestartFired", token: s.restart! });
const retryFired: Make = (s) => ({ type: "RetryFired", token: s.retry! });
const flushFired: Make = (s) => ({ type: "Flush", token: s.flush!.token });
/** The browser gives up on the current socket. */
const giveUp: Make = (s) => ({ type: "Errored", now: T, ready: CLOSED, gen: s.gen });
const frame = (now: number, events: Queued[] = [], id = ""): BusInput => ({ type: "Frame", now, ready: OPEN, id, events });

/**
 * The shell minus its I/O: decides `inputs` in turn, performs the effects in order and hands
 * every `Then` to `follow` on the state the listeners left, with the socket's readyState then
 * (the last input's, null after a Close, CONNECTING after an Open). `listener` runs at each
 * Apply / NotifyConnected; what it returns is decided at once, nested, as a listener's call.
 * Returns the end state and the performed effects (no `Then`).
 */
function settle(start: BusState, inputs: Make[], listener: (fx: BusEffect) => Make[] = () => []): Decision {
  let state = start;
  let ready: number | null = null;
  const effects: BusEffect[] = [];
  const run = (d: Decision) => {
    state = d.state;
    for (const fx of d.effects) {
      if (fx.type === "Then") {
        run(follow(state, fx.event, ready));
        continue;
      }
      effects.push(fx);
      if (fx.type === "Close") ready = null;
      if (fx.type === "Open") ready = CONNECTING;
      if (fx.type === "Apply" || fx.type === "NotifyConnected") listener(fx).forEach(send);
    }
  };
  const send = (m: Make) => {
    const ev = build(m, state);
    if ("ready" in ev) ready = ev.ready;
    run(decide(state, ev));
  };
  inputs.forEach(send);
  return { state, effects };
}
const step = (s: BusState, ev: Make) => settle(s, [ev]);

/** The decision's follow-up (its last effect must be a `Then`). */
function thenOf(d: Decision): FollowUp {
  const last = d.effects[d.effects.length - 1];
  if (last?.type !== "Then") throw new Error(`no Then in ${JSON.stringify(d.effects)}`);
  return last.event;
}
/** A listener that makes `call` once, at the first effect `when` matches. */
function once(when: (fx: BusEffect) => boolean, call: Make[]): (fx: BusEffect) => Make[] {
  let done = false;
  return (fx) => {
    if (done || !when(fx)) return [];
    done = true;
    return call;
  };
}

/** Scope "all" set, restart fired: one socket open (not yet OPEN). */
const opened = () => settle(initialBusState, [{ type: "SetScope", scope: "all" }, restartFired]).state;
/** …and OPEN with one frame (id e1.1): connected. */
const live = () => settle(opened(), [{ type: "Opened", now: T, ready: OPEN }, frame(T, [], "e1.1")]).state;

const kinds = (fx: BusEffect[]) => fx.map((e) => e.type);
const retries = (fx: BusEffect[]) =>
  fx.flatMap((e) => (e.type === "After" && e.fire.type === "RetryFired" ? [e.ms] : []));
const opens = (fx: BusEffect[]) =>
  fx.flatMap((e) => (e.type === "Open" ? [{ scope: e.scope, lastEventId: e.lastEventId }] : []));
const applied = (fx: BusEffect[]): Queued[] => fx.flatMap((e) => (e.type === "Apply" ? e.events : []));
const errors = (fx: BusEffect[]): EventEnvelope[] => applied(fx).flatMap(([t, p]) => (t === "__error" ? [p] : []));

/** Give up, let the armed retry fire (a new socket), `n` times; the retry delays armed. */
function failNTimes(s: BusState, n: number): { s: BusState; delays: number[] } {
  const d = settle(s, Array.from({ length: n }, () => [giveUp, retryFired]).flat());
  return { s: d.state, delays: retries(d.effects) };
}

describe("backoff", () => {
  it.each<[number, number[]]>([
    [1, [5_000]],
    [2, [5_000, 10_000]],
    [4, [5_000, 10_000, 20_000, 40_000]],
    [5, [5_000, 10_000, 20_000, 40_000, 60_000]],
    [8, [5_000, 10_000, 20_000, 40_000, 60_000, 60_000, 60_000, 60_000]],
  ])("%i consecutive give-ups arm %j (doubling, capped at RETRY_MAX_MS)", (n, want) => {
    expect(failNTimes(opened(), n).delays).toEqual(want);
  });

  it.each<[string, BusInput[], number]>([
    ["Opened resets it", [{ type: "Opened", now: T, ready: OPEN }], RETRY_MIN_MS],
    ["a frame alone does not", [frame(T, [], "e1.5")], 40_000],
    ["a stale tick does not", [{ type: "StaleTick", now: T, ready: OPEN }], 40_000],
  ])("after 3 give-ups, %s", (_n, between, next) => {
    const { s } = failNTimes(opened(), 3);
    expect(retries(settle(s, [...between, giveUp]).effects)).toEqual([next]);
  });

  it.each<[string, (s: BusState) => BusInput, number[], EventEnvelope]>([
    ["CLOSED on the current socket", giveUp, [5_000], { readyState: CLOSED }],
    ["CONNECTING (the browser retries itself)",
      (s) => ({ type: "Errored", now: T, ready: CONNECTING, gen: s.gen }), [], { readyState: CONNECTING }],
    ["CLOSED on an earlier socket", (s) => ({ type: "Errored", now: T, ready: CLOSED, gen: s.gen - 1 }), [], { readyState: CLOSED }],
    ["with no socket", (s) => ({ type: "Errored", now: T, ready: null, gen: s.gen }), [], {}],
  ])("an error, %s: retries armed %j, `__error` %j", (_n, err, armed, payload) => {
    const d = step(live(), err);
    expect(retries(d.effects)).toEqual(armed);
    // Either way: freshness shut at once and `__error` reaches listeners, before any retry is armed.
    expect(d.state.lastEventAt).toBe(0);
    expect(d.effects.slice(0, 2)).toEqual([
      { type: "NotifyConnected", connected: false }, { type: "Apply", events: [["__error", payload]] }]);
  });

  it("a second give-up while a retry is armed arms nothing and keeps the delay", () => {
    const first = step(opened(), giveUp);
    const second = step(first.state, giveUp);
    expect(retries(second.effects)).toEqual([]);
    expect(second.state.retry).toBe(first.state.retry);
    expect(second.state.retryMs).toBe(10_000);
  });

  it("the retry reopens from the last event id", () => {
    const d = settle(live(), [giveUp, retryFired]);
    expect(kinds(d.effects)).toEqual(["NotifyConnected", "Apply", "After", "Close", "Open"]);
    expect(opens(d.effects)).toEqual([{ scope: "all", lastEventId: "e1.1" }]);
  });
});

describe("pause / resume", () => {
  it.each<[string, Make[]]>([
    ["RetryFired after Pause", [{ type: "Pause" }]],
    ["RetryFired after Pause then a scope change", [{ type: "Pause" }, { type: "SetScope", scope: "model:7" }, restartFired]],
  ])("%s is a no-op", (_n, before) => {
    const armed = step(live(), giveUp).state;
    const s = settle(armed, before).state;
    const d = decide(s, { type: "RetryFired", token: armed.retry! });
    expect(d.effects).toEqual([]);
    expect(d.state).toBe(s);
  });

  it("pause closes the socket and opens none; that socket's give-up after it arms nothing", () => {
    const s = live();
    const d = step(s, { type: "Pause" });
    expect(kinds(d.effects)).toEqual(["Close", "NotifyConnected"]);
    expect(retries(step(d.state, { type: "Errored", now: T, ready: CLOSED, gen: s.gen }).effects)).toEqual([]);
  });

  it.each<[string, Make[], { scope: Scope; lastEventId: string }[]]>([
    ["resume reopens from the last event id", [{ type: "Pause" }, { type: "Resume" }],
      [{ scope: "all", lastEventId: "e1.1" }]],
    ["a scope change while paused opens nothing", [{ type: "Pause" }, { type: "SetScope", scope: "model:7" }, restartFired], []],
    ["…and resume then opens the new scope, from the last event id",
      [{ type: "Pause" }, { type: "SetScope", scope: "model:7" }, restartFired, { type: "Resume" }],
      [{ scope: "model:7", lastEventId: "e1.1" }]],
    ["pause twice, resume once", [{ type: "Pause" }, { type: "Pause" }, { type: "Resume" }],
      [{ scope: "all", lastEventId: "e1.1" }]],
    ["resume while not paused is a no-op", [{ type: "Resume" }], []],
    ["a frame without an id keeps the last one", [frame(T + 1), { type: "Pause" }, { type: "Resume" }],
      [{ scope: "all", lastEventId: "e1.1" }]],
    ["a frame with an id moves it", [frame(T + 1, [], "e1.2"), { type: "Pause" }, { type: "Resume" }],
      [{ scope: "all", lastEventId: "e1.2" }]],
  ])("%s", (_n, evs, want) => {
    expect(opens(settle(live(), evs).effects)).toEqual(want);
  });

  it("resume after a give-up starts the backoff where it was (only Opened resets it)", () => {
    const { s } = failNTimes(opened(), 2);
    expect(retries(settle(s, [{ type: "Pause" }, { type: "Resume" }, giveUp]).effects)).toEqual([20_000]);
  });
});

describe("listeners that call back into the bus", () => {
  /** live() with DMs 1-5 in one frame: queued, a flush armed. */
  const queued = () => step(live(), frame(T, dms(1, 2, 3, 4, 5))).state;
  const isApplyOf = (type: string) => (fx: BusEffect) => fx.type === "Apply" && fx.events[0][0] === type;
  const isNotify = (fx: BusEffect) => fx.type === "NotifyConnected";

  it.each<[string, Make[], Make, boolean]>([
    ["Pause", [], { type: "Pause" }, false],
    ["RetryFired", [giveUp], retryFired, true],
  ])("a reconnect (%s) with a queue stops at its Apply; the teardown is a follow-up", (_n, setup, trigger, resume) => {
    const s = settle(queued(), setup).state;
    const d = decide(s, build(trigger, s));
    expect(kinds(d.effects)).toEqual(["Apply", "Then"]);
    expect(thenOf(d)).toEqual({ type: "Teardown", resume });
  });

  it("a frame that changes the connected state admits its events after the state listeners", () => {
    const d = decide(opened(), frame(T, [dm(1)]));
    expect(kinds(d.effects)).toEqual(["NotifyConnected", "Then"]);
    expect(follow(d.state, thenOf(d), OPEN).effects).toEqual([{ type: "Apply", events: [dm(1)] }]);
  });

  it.each<[string, () => BusState, Make[], (fx: BusEffect) => boolean, Make[], BusEffect["type"][], EventEnvelope[]]>([
    // [name, from, inputs, the listener runs at, what it calls, performed effects, `__error` payloads]
    ["a pause from the flush's Apply, before the restart's teardown: no socket opened",
      queued, [{ type: "SetScope", scope: "model:7" }, restartFired], isApplyOf("api2_chat_message"), [{ type: "Pause" }],
      ["After", "Apply", "Close", "NotifyConnected", "Close"], []],
    ["a pause from an `__error` listener: no retry armed",
      live, [giveUp], isApplyOf("__error"), [{ type: "Pause" }],
      ["NotifyConnected", "Apply", "Close"], [{ readyState: CLOSED }]],
    ["a pause from the error's state listener: `__error` reads the socket it left (none)",
      live, [giveUp], isNotify, [{ type: "Pause" }],
      ["NotifyConnected", "Close", "Apply"], [{}]],
    ["a resume from the pause's state listener: one socket opened, the pause's Connect superseded",
      live, [{ type: "Pause" }], isNotify, [{ type: "Resume" }],
      ["Close", "NotifyConnected", "Close", "Open"], []],
  ])("%s", (_n, from, inputs, when, call, want, wantErrors) => {
    const d = settle(from(), inputs, once(when, call));
    expect(kinds(d.effects)).toEqual(want);
    expect(errors(d.effects)).toEqual(wantErrors);
    expect(d.state.retry).toBeNull();
  });
});

describe("staleness", () => {
  const DOWN: BusEffect = { type: "NotifyConnected", connected: false };
  it.each<[string, number, number | null, boolean, BusEffect[]]>([
    ["OPEN, frame 1 ms ago", T + 1, OPEN, true, []],
    ["OPEN, frame just inside STALE_MS", T + STALE_MS - 1, OPEN, true, []],
    ["OPEN, frame exactly STALE_MS ago", T + STALE_MS, OPEN, false, [DOWN]],
    ["OPEN, frame long ago", T + 10 * STALE_MS, OPEN, false, [DOWN]],
    ["fresh frame but socket CONNECTING", T + 1, CONNECTING, false, [DOWN]],
    ["fresh frame but no socket", T + 1, null, false, [DOWN]],
  ])("StaleTick, %s: connected=%s, and it never reopens", (_n, now, ready, connected, want) => {
    const s = live();
    expect(s.reported).toBe(true);
    const d = step(s, { type: "StaleTick", now, ready });
    expect(d.effects).toEqual(want);
    expect(d.state.reported).toBe(connected);
  });

  it.each<[string, BusInput[], boolean[]]>([
    ["Opened alone does not count as fresh", [{ type: "Opened", now: T, ready: OPEN }], []],
    ["the first frame (a ping) flips connected", [{ type: "Opened", now: T, ready: OPEN }, frame(T)], [true]],
    ["stale then a frame flips back", [
      { type: "Opened", now: T, ready: OPEN }, frame(T),
      { type: "StaleTick", now: T + STALE_MS, ready: OPEN }, frame(T + STALE_MS + 1)], [true, false, true]],
    ["ticks while fresh notify nothing", [
      { type: "Opened", now: T, ready: OPEN }, frame(T),
      { type: "StaleTick", now: T + 5_000, ready: OPEN }, { type: "StaleTick", now: T + 10_000, ready: OPEN }], [true]],
  ])("NotifyConnected timing: %s", (_n, evs, want) => {
    const { effects } = settle(opened(), evs);
    expect(effects.flatMap((e) => (e.type === "NotifyConnected" ? [e.connected] : []))).toEqual(want);
  });
});

describe("adaptive apply", () => {
  const APPLY = { type: "Apply" };
  const ARM_FLUSH = { type: "After", ms: APPLY_WINDOW_MS, frame: true, fire: { type: "Flush" } };

  it.each<[string, [number, number][], object[]]>([
    // [ms after T, events in the frame] per frame -> effects of the last frame
    ["a quiet stream applies each frame at once", [[0, 1], [RATE_SPAN_MS, 1], [2 * RATE_SPAN_MS, 1]], [APPLY]],
    [`${HOT_EVENTS_PER_S} events in a span still apply at once`, [[0, 1], [10, HOT_EVENTS_PER_S - 1]], [APPLY]],
    ["one more within the span queues and arms one flush", [[0, 1], [10, HOT_EVENTS_PER_S]], [ARM_FLUSH]],
    ["a hot batch frame queues on arrival", [[0, HOT_EVENTS_PER_S + 1]], [ARM_FLUSH]],
    ["while a flush is armed a frame only queues", [[0, HOT_EVENTS_PER_S + 1], [5 * RATE_SPAN_MS, 1]], []],
    ["the rate forgets frames a full span old", [[0, HOT_EVENTS_PER_S], [RATE_SPAN_MS, 1]], [APPLY]],
    ["an empty frame (ping, unlistened batch) applies nothing", [[0, HOT_EVENTS_PER_S + 1], [10, 0]], []],
  ])("%s", (_n, frames, want) => {
    let k = 0;
    const inputs = frames.map(([dt, n]) => frame(T + dt, Array.from({ length: n }, () => dm(++k))));
    const s = settle(live(), inputs.slice(0, -1)).state;
    expect(step(s, inputs[inputs.length - 1]).effects).toMatchObject(want);
  });

  const six = dms(1, 2, 3, 4, 5, 6);
  it.each<[string, Make[], BusEffect["type"][], Queued[]]>([
    ["Flush", [flushFired], ["Apply"], six],
    ["Pause", [{ type: "Pause" }], ["Apply", "Close", "NotifyConnected"], six],
    ["RestartFired after SetScope", [{ type: "SetScope", scope: "model:7" }, restartFired],
      ["After", "Apply", "Close", "NotifyConnected", "Open"], six],
    // `__error` is a connection signal, never queued: it comes first.
    ["RetryFired", [giveUp, retryFired],
      ["NotifyConnected", "Apply", "After", "Apply", "Close", "Open"], [["__error", { readyState: CLOSED }], ...six]],
  ])("queued frames apply once, in arrival order, ahead of the next stream — via %s", (_n, trigger, want, wantApplied) => {
    const s = settle(live(), [frame(T, dms(1, 2, 3)), frame(T + 1, dms(4)), frame(T + 2, dms(5, 6))]).state;
    const d = settle(s, trigger);
    expect(kinds(d.effects)).toEqual(want);
    expect(applied(d.effects)).toEqual(wantApplied);
    expect(d.state.flush).toBeNull();
  });

  it("a flood, then Pause (applies the queue), then the flood's Flush: a no-op", () => {
    const flooded = step(live(), frame(T, dms(1, 2, 3))).state;
    const paused = step(flooded, { type: "Pause" }).state;
    const d = decide(paused, { type: "Flush", token: flooded.flush!.token });
    expect(d.effects).toEqual([]);
    expect(d.state).toBe(paused);
  });
});

describe("scope", () => {
  it.each<[string, BusState, Scope[], number[], BusEffect["type"][], { scope: Scope; lastEventId: string }[]]>([
    // [name, from, scopes set, restart delays armed, effects of the last restart, sockets it opens]
    ["first scope: one Open after the restart, no last id", initialBusState, ["all"], [RESTART_MS],
      ["Close", "Open"], [{ scope: "all", lastEventId: "" }]],
    ["new scope: Close, then Open of the new scope without the last id", live(), ["model:7"], [RESTART_MS],
      ["Close", "NotifyConnected", "Open"], [{ scope: "model:7", lastEventId: "" }]],
    ["rapid switches: only the last restart acts, on the last scope", live(), ["model:7", "model:8"], [RESTART_MS, RESTART_MS],
      ["Close", "NotifyConnected", "Open"], [{ scope: "model:8", lastEventId: "" }]],
    ["the same scope is a no-op", live(), ["all"], [], [], []],
  ])("%s", (_n, from, scopes, wantDelays, wantKinds, wantOpens) => {
    const d = settle(from, scopes.map((scope): Make => ({ type: "SetScope", scope })));
    const restarts = d.effects.flatMap((e) =>
      (e.type === "After" && e.fire.type === "RestartFired" ? [{ ms: e.ms, token: e.fire.token }] : []));
    expect(restarts.map((r) => r.ms)).toEqual(wantDelays);
    const tokens = restarts.map((r) => r.token);
    // Earlier restarts were re-armed away: firing them does nothing.
    for (const tok of tokens.slice(0, -1)) expect(step(d.state, { type: "RestartFired", token: tok }).effects).toEqual([]);
    const fired = tokens.slice(-1).flatMap((token) => step(d.state, { type: "RestartFired", token }).effects);
    expect(kinds(fired)).toEqual(wantKinds);
    expect(opens(fired)).toEqual(wantOpens);
  });

  it("a scope change cancels an armed retry", () => {
    const armed = step(live(), giveUp).state;
    const s = settle(armed, [{ type: "SetScope", scope: "model:7" }, restartFired]).state;
    expect(step(s, { type: "RetryFired", token: armed.retry! }).effects).toEqual([]);
  });
});

describe("eventsUrl", () => {
  it.each<[Scope, string | null, string, string]>([
    ["all", null, "", "/events?scope=all"],
    ["model:7", null, "", "/events?scope=model%3A7"],
    ["all", "tok", "e1.41", "/events?scope=all&t=tok&last_event_id=e1.41"],
  ])("%s token=%s id=%s", (scope, tok, id, want) => {
    expect(eventsUrl(scope, tok, id)).toBe(want);
  });
});
