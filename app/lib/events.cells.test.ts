import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CellMap } from "./cellInbox";

const MAP: CellMap = {
  actor: "admin:1", grant_gen: 1, placement_gen: 2, cells: ["s01", "s02"], control: "c0",
  accounts: [
    { platform: "onlyfans", account_id: "10", cell: "s01" },
    { platform: "onlyfans", account_id: "20", cell: "s02" },
  ],
};
const grey = vi.fn();
vi.mock("./cellFlag", () => ({ cellMode: () => true }));
vi.mock("./cellMap", () => ({
  currentCellMap: () => MAP, loadCellMap: () => Promise.resolve(MAP), onCellMap: () => () => {},
  setStreamGrey: (ids: ReadonlySet<string>) => grey([...ids]),
}));

class FakeEventSource {
  static all: FakeEventSource[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((m: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((m: MessageEvent) => void)[]>();
  constructor(public url: string) { FakeEventSource.all.push(this); }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() { this.readyState = 2; }
  emit(type: string, lastEventId: string, data = "{}") {
    for (const fn of this.listeners.get(type) ?? []) fn({ data, lastEventId } as MessageEvent);
  }
}

const open = () => FakeEventSource.all.filter((e) => e.readyState === 1);
const of = (cell: string) => open().find((e) => e.url.includes(`cell=${cell}`))!;

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetModules();
  FakeEventSource.all = [];
  grey.mockClear();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

async function started() {
  const { eventBus } = await import("./events");
  eventBus.on("toasts", () => {});
  eventBus.setScope("all");
  vi.advanceTimersByTime(50);
  return eventBus;
}

describe("one stream per Cell", () => {
  it("opens control + each data Cell, routed by ?cell=", async () => {
    await started();
    expect(open().map((e) => e.url)).toEqual([
      "/events?scope=all&lease=1&cell=c0",
      "/events?scope=all&lease=1&cell=s01",
      "/events?scope=all&lease=1&cell=s02",
    ]);
  });

  it("a stalled Cell greys only its Creators; others stay live", async () => {
    const bus = await started();
    for (const c of ["c0", "s01", "s02"]) of(c).emit("toasts", `${c}.1`);
    expect(bus.isConnected()).toBe(true);
    const s01 = vi.fn();
    const s02 = vi.fn();
    const drops = vi.fn();
    bus.onStateChange(s01, "10");
    bus.onStateChange(s02, "20");
    bus.onStreamState(drops);
    s01.mockClear();
    s02.mockClear();

    for (let t = 0; t < 50_000; t += 5_000) {
      of("c0").emit("toasts", "");
      of("s01").emit("toasts", "");
      vi.advanceTimersByTime(5_000);
    }
    expect(bus.isConnected("10")).toBe(true);
    expect(bus.isConnected("20")).toBe(false);
    expect(bus.isConnected()).toBe(false);
    expect(s01).not.toHaveBeenCalled();
    expect(s02).toHaveBeenCalledWith(false);
    expect(drops).toHaveBeenCalledWith({ connected: false, accounts: ["20"] });
    expect(grey).toHaveBeenLastCalledWith(["20"]);
  });

  it("each stream reconnects from its own cursor", async () => {
    const bus = await started();
    of("s01").emit("toasts", "e1.7");
    of("s02").emit("toasts", "e9.3");
    bus.pause();
    bus.resume();
    expect(of("s01").url).toBe("/events?scope=all&lease=1&last_event_id=e1.7&cell=s01");
    expect(of("s02").url).toBe("/events?scope=all&lease=1&last_event_id=e9.3&cell=s02");
  });

  it("model scope keeps only that Creator's Cell plus control", async () => {
    const bus = await started();
    bus.setScope("model:20");
    vi.advanceTimersByTime(50);
    expect(open().map((e) => e.url)).toEqual([
      "/events?scope=all&lease=1&cell=c0",
      "/events?scope=model%3A20&lease=1&cell=s02",
    ]);
  });

  it("events from every Cell reach the same listeners", async () => {
    const bus = await started();
    const got: string[] = [];
    bus.on("api2_chat_message", (e) => got.push(String(e.cell)));
    of("s01").emit("api2_chat_message", "a.1", '{"cell":"s01"}');
    of("s02").emit("api2_chat_message", "b.1", '{"cell":"s02"}');
    of("s01").emit("api2_chat_message", "a.2", '{"cell":"s01"}');
    expect(got).toEqual(["s01", "s02", "s01"]);
  });

  it("HTTP/1.1 opens no streams and raises the banner", async () => {
    vi.stubGlobal("performance", {
      getEntriesByType: (t: string) => (t === "resource" ? [{ name: "http://x/auth/cells", nextHopProtocol: "http/1.1" }] : []),
    });
    const bus = await started();
    expect(open()).toEqual([]);
    expect(bus.liveBlocked()).toBe(true);
    expect(bus.isConnected("10")).toBe(false);
  });
});
