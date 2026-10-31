/**
 * eventBus Idle mode: `pause` closes the stream and holds it closed through a
 * scope change; `resume` reopens it from the last event id it saw, so the
 * relay replays what the tab missed.
 *
 * Batches: an `event: batch` frame reaches listeners as the same individual
 * events, in order, with one notify flush, and its id is the resume point.
 */
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
  private listeners = new Map<string, (m: MessageEvent) => void>();
  constructor(public url: string) { FakeEventSource.all.push(this); }
  addEventListener(type: string, fn: (m: MessageEvent) => void) { this.listeners.set(type, fn); }
  close() { this.readyState = FakeEventSource.CLOSED; }
  emit(type: string, lastEventId: string, data = "{}") {
    this.listeners.get(type)?.({ data, lastEventId } as MessageEvent);
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
    expect(live()[0].url).toBe("/events?scope=all&last_event_id=e1.41");
  });

  it("a scope change while paused waits for resume", async () => {
    const bus = await connected();
    bus.pause();
    bus.setScope("model:7");
    vi.advanceTimersByTime(50);
    expect(live()).toHaveLength(0);

    bus.resume();
    expect(live().map((e) => e.url)).toEqual(["/events?scope=model%3A7"]);
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
    vi.advanceTimersByTime(1);   // RETRY_MIN_MS
    expect(FakeEventSource.all.map((e) => e.url)).toEqual(["/events?scope=all", "/events?scope=all&last_event_id=e1.41"]);
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
    vi.advanceTimersByTime(2 * RETRY_MAX_MS);   // past any retry
    expect(FakeEventSource.all).toHaveLength(1);
  });
});

type Member = { id: string; type: string; data: Record<string, unknown> };
const dm = (n: number) => ({ api2_chat_message: { id: n }, __account_id: "7" });
const batchOf = (members: Member[]) => JSON.stringify(members);

describe("eventBus re-entrancy", () => {
  it("a listener that pauses while queued events apply leaves the bus paused, with no socket", async () => {
    // No animation frames (a hidden tab): the queue waits for the 250 ms window, so the
    // scope change's 50 ms restart is what applies it, ahead of its reopen.
    vi.stubGlobal("requestAnimationFrame", () => 1);
    const { eventBus } = await import("./events");
    // DMs 1-2 apply at once (quiet rate), 3-5 queue; the pause comes from DM 4, inside the queue's flush.
    let pausedInside: boolean | null = null;
    eventBus.on("api2_chat_message", (e) => {
      if ((e as ReturnType<typeof dm>).api2_chat_message.id === 4) {
        eventBus.pause();
        pausedInside = eventBus.isPaused(); // takes effect at once, even mid-flush
      }
    });
    eventBus.setScope("all");
    vi.advanceTimersByTime(50);
    for (let n = 1; n <= 5; n++) FakeEventSource.all[0].emit("api2_chat_message", `e1.${n}`, JSON.stringify(dm(n)));
    eventBus.setScope("model:7"); // its restart applies the queue first, then reopens
    vi.advanceTimersByTime(50);
    expect(pausedInside).toBe(true);
    expect(eventBus.isPaused()).toBe(true);
    expect(live()).toHaveLength(0);
    expect(FakeEventSource.all).toHaveLength(1); // the restart's reopen never ran
    eventBus.resume();
    expect(live().map((e) => e.url)).toEqual(["/events?scope=model%3A7&last_event_id=e1.5"]);
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
      { id: "e1.3", type: "chat_queue_update", data: { chat_queue_update: { id: 9 } } }, // nobody listens
      { id: "e1.4", type: "api2_chat_message", data: dm(2) },
    ];
    FakeEventSource.all[0].emit("batch", "e1.4", batchOf(members));
    vi.advanceTimersByTime(1_000); // 3 events: past the quiet rate, so one window
    expect(seen).toEqual([
      ["api2_chat_message", dm(1)],
      ["chat_typing", typing],
      ["api2_chat_message", dm(2)],
    ]);
    // Exactly what the same events sent one frame each deliver.
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
    expect(live()[0].url).toBe("/events?scope=all&last_event_id=e1.9");
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
    // As useQuery subscribes: each notification is scheduled through notifyManager.
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
  // Vitest's fake timers run requestAnimationFrame every 16 ms.
  const FRAME_MS = 16;
  /** A list cache like the inbox's: every DM moves its fan to the top. */
  async function inbox() {
    const { eventBus } = await import("./events");
    const { APPLY_WINDOW_MS, HOT_EVENTS_PER_S } = await import("./eventBusReducer");
    const { QueryClient, QueryObserver, notifyManager } = await import("@tanstack/react-query");
    // One scheduler call = one notify flush = one React render pass.
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

  /** The same 100 DMs applied one by one, no bus. */
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
    const spanMs = 100; // one DM per ms: ~16 per animation frame
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
    // Hidden tab: the window timer wins, three floods in a row leave no frame callback behind.
    for (let round = 1; round <= 3; round++) {
      for (let n = 1; n <= 10; n++) t.send(round * 100 + n);
      vi.advanceTimersByTime(t.APPLY_WINDOW_MS);
    }
    expect(t.order).toHaveLength(30);
    expect(frames.size).toBe(0);
    // Visible tab: the frame wins, its window timer is cleared.
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
