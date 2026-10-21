/**
 * eventBus Idle mode: `pause` closes the stream and holds it closed through a
 * scope change; `resume` reopens it from the last event id it saw, so the
 * relay replays what the tab missed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  emit(type: string, lastEventId: string) {
    this.listeners.get(type)?.({ data: "{}", lastEventId } as MessageEvent);
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
