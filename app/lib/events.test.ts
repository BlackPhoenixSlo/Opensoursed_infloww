import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RETRY_MAX_MS, RETRY_MIN_MS } from "./eventBusReducer";

class FakeEventSource {
  static OPEN = 1;
  static CLOSED = 2;
  static all: FakeEventSource[] = [];
  readyState = FakeEventSource.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((m: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((m: MessageEvent) => void)[]>();
  constructor(public url: string) { FakeEventSource.all.push(this); }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() { this.readyState = FakeEventSource.CLOSED; }
  emit(type: string, lastEventId: string, data = "{}") {
    for (const fn of this.listeners.get(type) ?? []) fn({ data, lastEventId } as MessageEvent);
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetModules();
  FakeEventSource.all = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

async function connected() {
  const { eventBus } = await import("./events");
  eventBus.on("toasts", () => {});
  eventBus.setScope("all");
  vi.advanceTimersByTime(50);
  return eventBus;
}

const live = () => FakeEventSource.all.filter((e) => e.readyState === FakeEventSource.OPEN);

describe("eventBus pause / resume", () => {
  it("resume reopens with the last event id", async () => {
    const bus = await connected();
    FakeEventSource.all[0].emit("toasts", "e1.41");

    bus.pause();
    expect(live()).toHaveLength(0);
    expect(bus.isConnected()).toBe(false);

    bus.resume();
    expect(live()).toHaveLength(1);
    expect(live()[0].url).toBe("/events?scope=all&lease=1&last_event_id=e1.41");
  });

  it("a scope change while paused waits for resume", async () => {
    const bus = await connected();
    bus.pause();
    bus.setScope("model:7");
    vi.advanceTimersByTime(50);
    expect(live()).toHaveLength(0);

    bus.resume();
    expect(live().map((e) => e.url)).toEqual(["/events?scope=model%3A7&lease=1"]);
  });
});

describe("eventBus give-up (the shell hands `follow` the socket's readyState as it is then)", () => {
  it("socket CLOSED -> onerror -> after RETRY_MIN_MS reopens with last_event_id", async () => {
    const bus = await connected();
    const errs: unknown[] = [];
    bus.on("__error", (e) => errs.push(e));
    const es = FakeEventSource.all[0];
    es.emit("toasts", "e1.41");
    es.readyState = FakeEventSource.CLOSED;
    es.onerror!();
    expect(errs).toEqual([{ readyState: FakeEventSource.CLOSED }]);
    vi.advanceTimersByTime(RETRY_MIN_MS - 1);
    expect(FakeEventSource.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.all.map((e) => e.url)).toEqual(["/events?scope=all&lease=1", "/events?scope=all&lease=1&last_event_id=e1.41"]);
  });

  it("a state listener that pauses on the error: `__error` is {} (no socket), no retry", async () => {
    const bus = await connected();
    const es = FakeEventSource.all[0];
    es.emit("toasts", "e1.41");
    const errs: unknown[] = [];
    bus.on("__error", (e) => errs.push(e));
    bus.onStateChange((up) => { if (!up) bus.pause(); });
    es.readyState = FakeEventSource.CLOSED;
    es.onerror!();
    expect(errs).toEqual([{}]);
    expect(bus.isPaused()).toBe(true);
    vi.advanceTimersByTime(2 * RETRY_MAX_MS);
    expect(FakeEventSource.all).toHaveLength(1);
  });
});

type Member = { id: string; type: string; data: Record<string, unknown> };
const dm = (n: number) => ({ api2_chat_message: { id: n }, __account_id: "7" });
const batchOf = (members: Member[]) => JSON.stringify(members);

describe("eventBus re-entrancy", () => {
  it("a listener that pauses while queued events apply leaves the bus paused, with no socket", async () => {
    vi.stubGlobal("requestAnimationFrame", () => 1);
    const { eventBus } = await import("./events");
    let pausedInside: boolean | null = null;
    eventBus.on("api2_chat_message", (e) => {
      if ((e as ReturnType<typeof dm>).api2_chat_message.id === 4) {
        eventBus.pause();
        pausedInside = eventBus.isPaused();
      }
    });
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    for (let n = 1; n <= 5; n++) FakeEventSource.all[0].emit("api2_chat_message", `e1.${n}`, JSON.stringify(dm(n)));
    eventBus.setScope("model:7");
    vi.advanceTimersByTime(50);
    expect(pausedInside).toBe(true);
    expect(eventBus.isPaused()).toBe(true);
    expect(live()).toHaveLength(0);
    expect(FakeEventSource.all).toHaveLength(1);
    eventBus.resume();
    expect(live().map((e) => e.url)).toEqual(["/events?scope=model%3A7&lease=1&last_event_id=e1.5"]);
  });
});

describe("eventBus batch frames", () => {
  it("dispatches each member as its own event, in order, only to listeners of its type", async () => {
    const { eventBus } = await import("./events");
    const seen: [string, unknown][] = [];
    eventBus.on("api2_chat_message", (e, t) => seen.push([t, e]));
    eventBus.on("chat_typing", (e, t) => seen.push([t, e]));
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const typing = { chat_typing: { fan_id: 3 }, __account_id: "7" };
    const members: Member[] = [
      { id: "e1.1", type: "api2_chat_message", data: dm(1) },
      { id: "e1.2", type: "chat_typing", data: typing },
      { id: "e1.3", type: "chat_queue_update", data: { chat_queue_update: { id: 9 } } },
      { id: "e1.4", type: "api2_chat_message", data: dm(2) },
    ];
    FakeEventSource.all[0].emit("batch", "e1.4", batchOf(members));
    vi.advanceTimersByTime(1_000);
    expect(seen).toEqual([
      ["api2_chat_message", dm(1)],
      ["chat_typing", typing],
      ["api2_chat_message", dm(2)],
    ]);
    const single: [string, unknown][] = [];
    seen.length = 0;
    for (const m of members) FakeEventSource.all[0].emit(m.type, m.id, JSON.stringify(m.data));
    vi.advanceTimersByTime(1_000);
    single.push(...seen);
    expect(single).toEqual([
      ["api2_chat_message", dm(1)],
      ["chat_typing", typing],
      ["api2_chat_message", dm(2)],
    ]);
  });

  it("resumes from the batch frame's id (its last member's)", async () => {
    const bus = await connected();
    FakeEventSource.all[0].emit("batch", "e1.9", batchOf([
      { id: "e1.8", type: "toasts", data: { toasts: {} } },
      { id: "e1.9", type: "toasts", data: { toasts: {} } },
    ]));
    expect(bus.isConnected()).toBe(true);
    bus.pause();
    bus.resume();
    expect(live()[0].url).toBe("/events?scope=all&lease=1&last_event_id=e1.9");
  });

  it("a 50-event batch is one notify flush; 50 back-to-back single frames coalesce into one window", async () => {
    const { eventBus } = await import("./events");
    const { APPLY_WINDOW_MS } = await import("./eventBusReducer");
    const { QueryClient, QueryObserver, notifyManager } = await import("@tanstack/react-query");
    let flushes = 0;
    notifyManager.setScheduler((cb) => { flushes += 1; cb(); });
    const qc = new QueryClient();
    qc.setQueryData(["n"], 0);
    let renders = 0;
    const obs = new QueryObserver<number>(qc, { queryKey: ["n"], enabled: false });
    const off = obs.subscribe(notifyManager.batchCalls(() => { renders += 1; }));
    eventBus.on("api2_chat_message", () => qc.setQueryData<number>(["n"], (n) => (n ?? 0) + 1));
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const es = FakeEventSource.all[0];

    flushes = 0;
    es.emit("batch", "e1.50", batchOf(Array.from({ length: 50 }, (_, i) => (
      { id: `e1.${i + 1}`, type: "api2_chat_message", data: dm(i + 1) }))));
    vi.advanceTimersByTime(APPLY_WINDOW_MS);
    expect(qc.getQueryData(["n"])).toBe(50);
    expect(flushes).toBe(1);

    flushes = 0;
    for (let i = 0; i < 50; i++) es.emit("api2_chat_message", `e1.${51 + i}`, JSON.stringify(dm(51 + i)));
    vi.advanceTimersByTime(APPLY_WINDOW_MS);
    expect(qc.getQueryData(["n"])).toBe(100);
    expect(flushes).toBe(1);
    expect(renders).toBeGreaterThan(0);
    off();
    notifyManager.setScheduler((cb) => setTimeout(cb, 0));
  });

  it("ignores a malformed batch", async () => {
    const { eventBus } = await import("./events");
    const fn = vi.fn();
    eventBus.on("toasts", fn);
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    FakeEventSource.all[0].emit("batch", "e1.1", "not json");
    FakeEventSource.all[0].emit("batch", "e1.2", "{}");
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("eventBus adaptive apply", () => {
  const FRAME_MS = 16;
  async function inbox() {
    const { eventBus } = await import("./events");
    const { APPLY_WINDOW_MS, HOT_EVENTS_PER_S } = await import("./eventBusReducer");
    const { QueryClient, QueryObserver, notifyManager } = await import("@tanstack/react-query");
    let renders = 0;
    notifyManager.setScheduler((cb) => { renders += 1; cb(); });
    const qc = new QueryClient();
    qc.setQueryData<number[]>(["chats"], []);
    const obs = new QueryObserver<number[]>(qc, { queryKey: ["chats"], enabled: false });
    const off = obs.subscribe(notifyManager.batchCalls(() => {}));
    renders = 0;
    const order: number[] = [];
    eventBus.on("api2_chat_message", (e) => {
      const fan = (e as { fan: number }).fan;
      order.push((e as { n: number }).n);
      qc.setQueryData<number[]>(["chats"], (l = []) => [fan, ...l.filter((f) => f !== fan)]);
    });
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const es = FakeEventSource.all[0];
    const send = (n: number) => es.emit("api2_chat_message", `e1.${n}`, JSON.stringify({ n, fan: (n * 7) % 37 }));
    const done = () => { off(); notifyManager.setScheduler((cb) => setTimeout(cb, 0)); };
    return { qc, es, send, order, renders: () => renders, done, APPLY_WINDOW_MS, HOT_EVENTS_PER_S };
  }

  function oneByOne() {
    let l: number[] = [];
    for (let n = 1; n <= 100; n++) { const fan = (n * 7) % 37; l = [fan, ...l.filter((f) => f !== fan)]; }
    return l;
  }

  it("a quiet stream applies each event the moment it lands", async () => {
    const t = await inbox();
    for (let n = 1; n <= 5; n++) {
      t.send(n);
      expect(t.order).toHaveLength(n);
      vi.advanceTimersByTime(1_000);
    }
    expect(t.renders()).toBe(5);
    t.done();
  });

  it("a burst of 100 DMs renders at most once per frame, same final list, same order", async () => {
    const t = await inbox();
    const spanMs = 100;
    for (let n = 1; n <= 100; n++) {
      t.send(n);
      vi.advanceTimersByTime(spanMs / 100);
    }
    vi.advanceTimersByTime(FRAME_MS);
    expect(t.order).toHaveLength(100);
    expect(t.renders()).toBeLessThanOrEqual(Math.ceil(spanMs / FRAME_MS) + 1 + t.HOT_EVENTS_PER_S);
    expect(t.renders()).toBeLessThan(100);
    expect(t.qc.getQueryData(["chats"])).toEqual(oneByOne());
    expect(t.order).toEqual(Array.from({ length: 100 }, (_, i) => i + 1));
    t.done();
  });

  it("a hot DM waits at most one frame, not a fixed window", async () => {
    const t = await inbox();
    for (let n = 1; n <= 10; n++) t.send(n);
    expect(t.order.length).toBeLessThan(10);
    vi.advanceTimersByTime(FRAME_MS);
    expect(t.order).toHaveLength(10);
    t.done();
  });

  it("where frames do not run (hidden tab) the queue flushes after APPLY_WINDOW_MS", async () => {
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => {});
    try {
      const t = await inbox();
      for (let n = 1; n <= 10; n++) t.send(n);
      vi.advanceTimersByTime(t.APPLY_WINDOW_MS - 1);
      expect(t.order.length).toBeLessThan(10);
      vi.advanceTimersByTime(1);
      expect(t.order).toHaveLength(10);
      t.done();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("whichever of the flush's two timers fires first cancels the other", async () => {
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrame = 0;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { frames.set(++nextFrame, cb); return nextFrame; });
    vi.stubGlobal("cancelAnimationFrame", (h: number) => { frames.delete(h); });
    const t = await inbox();
    for (let round = 1; round <= 3; round++) {
      for (let n = 1; n <= 10; n++) t.send(round * 100 + n);
      vi.advanceTimersByTime(t.APPLY_WINDOW_MS);
    }
    expect(t.order).toHaveLength(30);
    expect(frames.size).toBe(0);
    const idle = vi.getTimerCount();
    for (let n = 1; n <= 10; n++) t.send(400 + n);
    expect(vi.getTimerCount()).toBe(idle + 1);
    const [[, cb]] = [...frames];
    cb(0);
    expect(t.order).toHaveLength(40);
    expect(vi.getTimerCount()).toBe(idle);
    t.done();
  });

  it("nothing waits longer than one window, and a scope change flushes first", async () => {
    const t = await inbox();
    for (let n = 1; n <= 10; n++) t.send(n);
    expect(t.order.length).toBeLessThanOrEqual(t.HOT_EVENTS_PER_S);
    const { eventBus } = await import("./events");
    eventBus.setScope("model:7");
    vi.advanceTimersByTime(50);
    expect(t.order).toHaveLength(10);
    t.done();
  });
});

describe("eventBus ping", () => {
  const ping = (data: unknown) => JSON.stringify(data);

  it("a ping carrying `fresh` reaches `ping` listeners once, as it came; it keeps the stream fresh", async () => {
    const { eventBus } = await import("./events");
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const seen: [string, unknown][] = [];
    eventBus.on("ping", (e, t) => seen.push([t, e]));
    const es = FakeEventSource.all[0];
    es.onopen?.();
    vi.advanceTimersByTime(40_000);
    es.emit("ping", "", ping({ ts: 1700000000.5, fresh: { a1: 9_000 } }));
    vi.advanceTimersByTime(1_000);
    expect(seen).toEqual([["ping", { ts: 1700000000.5, fresh: { a1: 9_000 } }]]);
    expect(eventBus.isConnected()).toBe(true);
  });

  it("today's ping (Knob off, no `fresh`) dispatches nothing and still keeps the stream fresh", async () => {
    const { eventBus } = await import("./events");
    const seen: unknown[] = [];
    eventBus.on("ping", (e) => seen.push(e));
    eventBus.on("*", (e) => seen.push(e));
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const es = FakeEventSource.all[0];
    es.onopen?.();
    vi.advanceTimersByTime(40_000);
    es.emit("ping", "", ping({ ts: 1700000000.5 }));
    es.emit("ping", "", "not json");
    vi.advanceTimersByTime(1_000);
    expect(seen).toEqual([]);
    expect(eventBus.isConnected()).toBe(true);
  });

  it("with no `ping` listener a `fresh` ping dispatches nothing", async () => {
    const { eventBus } = await import("./events");
    const seen: unknown[] = [];
    eventBus.on("*", (e) => seen.push(e));
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    FakeEventSource.all[0].emit("ping", "", ping({ ts: 1, fresh: { a1: 9_000 } }));
    vi.advanceTimersByTime(1_000);
    expect(seen).toEqual([]);
  });
});

describe("eventBus ping: the Relay's clock (phase-03, Which clock)", () => {
  const T = 1_800_000_000_000;
  const MIN = 60_000;
  const ping = (data: unknown) => JSON.stringify(data);

  async function open() {
    vi.setSystemTime(T);
    const { eventBus } = await import("./events");
    const ageClock = await import("./ageClock");
    eventBus.on("creator_refreshed", () => {});
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    const es = FakeEventSource.all[0];
    es.onopen?.();
    return { ageClock, es };
  }

  it("a ping sets the offset: tab clock minus the ping's `ts` (today's ping too, no `fresh`)", async () => {
    const { ageClock, es } = await open();
    expect(ageClock.relayOffset()).toBe(0);
    es.emit("ping", "", ping({ ts: (Date.now() - 5 * MIN) / 1000 }));
    expect(ageClock.relayOffset()).toBe(5 * MIN);
    es.emit("ping", "", ping({ ts: (Date.now() + 2 * MIN) / 1000, fresh: { a1: 9_000 } }));
    expect(ageClock.relayOffset()).toBe(-2 * MIN);
  });

  it("a ping with no `ts` or not JSON leaves it", async () => {
    const { ageClock, es } = await open();
    es.emit("ping", "", ping({ ts: (Date.now() - 5 * MIN) / 1000 }));
    es.emit("ping", "", ping({ fresh: {} }));
    es.emit("ping", "", "not json");
    expect(ageClock.relayOffset()).toBe(5 * MIN);
  });

  it("a replayed envelope's `now` never moves it, before or after a ping (single or batched)", async () => {
    const { ageClock, es } = await open();
    const old = { creator_refreshed: { account_id: "a", now: T - 30 * MIN }, now: T - 30 * MIN };
    es.emit("creator_refreshed", "e1.1", JSON.stringify(old));
    es.emit("batch", "e1.2", JSON.stringify([{ id: "e1.2", type: "creator_refreshed", data: old }]));
    vi.advanceTimersByTime(1_000);
    expect(ageClock.relayOffset()).toBe(0);
    es.emit("ping", "", ping({ ts: (Date.now() - 1 * MIN) / 1000 }));
    es.emit("creator_refreshed", "e1.3", JSON.stringify(old));
    vi.advanceTimersByTime(1_000);
    expect(ageClock.relayOffset()).toBe(1 * MIN);
  });
});
