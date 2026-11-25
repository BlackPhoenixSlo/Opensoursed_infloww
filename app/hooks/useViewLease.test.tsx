import { StrictMode } from "react";
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { holdLease, onLeaseHolds } from "@/lib/viewLease";
import { useOnScreenLease, useViewLease } from "./useViewLease";

function watch() {
  const seen: Record<string, string[]> = {};
  const off = onLeaseHolds((key, ids) => { seen[key] = ids; });
  const of = (label: string) => [...new Set(Object.entries(seen)
    .filter(([k]) => k.startsWith(`${label}#`)).flatMap(([, ids]) => ids))].sort();
  return { seen, of, off };
}

describe("holdLease: one hold per key", () => {
  it.each<[string, (h: typeof holdLease) => void, Record<string, string[]>]>([
    ["a hold leases its Creators, sorted, once each", (h) => { h("t-a", ["B", "A", "B"]); }, { "t-a": ["A", "B"] }],
    ["a second hold on a key replaces the first", (h) => { h("t-b", ["A"]); h("t-b", ["B"]); }, { "t-b": ["B"] }],
    ["the release drops the hold", (h) => { const r = h("t-c", ["A"]); r(); }, { "t-c": [] }],
    ["a replaced hold's release is a no-op", (h) => { const r = h("t-d", ["A"]); h("t-d", ["B"]); r(); },
      { "t-d": ["B"] }],
    ["keys are held apart", (h) => { h("t-e", ["A"]); const r = h("t-f", ["A"]); r(); }, { "t-e": ["A"], "t-f": [] }],
  ])("%s", (_name, act_, want) => {
    const w = watch();
    act_(holdLease);
    w.off();
    expect(Object.fromEntries(Object.keys(want).map((k) => [k, w.seen[k]]))).toEqual(want);
  });

  it("a late subscriber is told every live hold at once", () => {
    const r = holdLease("t-late", ["Z"]);
    const w = watch();
    expect(w.seen["t-late"]).toEqual(["Z"]);
    w.off();
    r();
  });
});

describe("useViewLease", () => {
  it("holds while mounted, follows its ids, releases on [] and on unmount", () => {
    const w = watch();
    const { rerender, unmount } = renderHook(({ ids }) => useViewLease(ids, "u-chat"), { initialProps: { ids: ["A"] } });
    expect(w.of("u-chat")).toEqual(["A"]);
    rerender({ ids: ["B"] });
    expect(w.of("u-chat")).toEqual(["B"]);
    rerender({ ids: [] });
    expect(w.of("u-chat")).toEqual([]);
    rerender({ ids: ["C"] });
    expect(w.of("u-chat")).toEqual(["C"]);
    unmount();
    expect(w.of("u-chat")).toEqual([]);
    w.off();
  });

  it("two mounts (two open chats) hold apart: one unmounting keeps the other's", () => {
    const w = watch();
    const a = renderHook(() => useViewLease(["A"], "u-two"));
    const b = renderHook(() => useViewLease(["A", "B"], "u-two"));
    expect(w.of("u-two")).toEqual(["A", "B"]);
    b.unmount();
    expect(w.of("u-two")).toEqual(["A"]);
    a.unmount();
    expect(w.of("u-two")).toEqual([]);
    w.off();
  });
});

class FakeIO implements IntersectionObserver {
  static all: FakeIO[] = [];
  readonly root = null;
  readonly rootMargin = "0px";
  readonly scrollMargin = "0px";
  readonly thresholds: readonly number[] = [0];
  observed = new Set<Element>();
  observeCalls = 0;
  constructor(private cb: IntersectionObserverCallback) { FakeIO.all.push(this); }
  observe(el: Element) { this.observed.add(el); this.observeCalls++; }
  unobserve(el: Element) { this.observed.delete(el); }
  disconnect() { this.observed.clear(); }
  takeRecords(): IntersectionObserverEntry[] { return []; }
  fire(shown: Element[], ratio = 1) {
    const entries = [...this.observed].map((target): IntersectionObserverEntry => {
      const box = target.getBoundingClientRect();
      const on = shown.includes(target);
      return { target, time: 0, isIntersecting: on, intersectionRatio: on ? ratio : 0, boundingClientRect: box,
        intersectionRect: box, rootBounds: null };
    });
    this.cb(entries, this);
  }
}

function Strip({ ids }: { ids: string[] }) {
  const track = useOnScreenLease("u-strip");
  return <div>{ids.map((id) => <span key={id} data-id={id} ref={track(id)} />)}</div>;
}

describe("useOnScreenLease: the visible-row sources", () => {
  beforeEach(() => { FakeIO.all = []; vi.stubGlobal("IntersectionObserver", FakeIO); });
  afterEach(() => vi.unstubAllGlobals());

  it("leases the rows on screen, follows a scroll, and releases on unmount", () => {
    const w = watch();
    const { container, unmount } = render(<Strip ids={["A", "B", "C", "D"]} />);
    const el = (id: string) => container.querySelector(`[data-id="${id}"]`)!;
    const io = FakeIO.all[0];
    expect(io.observed.size).toBe(4);
    expect(w.of("u-strip")).toEqual([]);
    act(() => io.fire([el("A"), el("B")]));
    expect(w.of("u-strip")).toEqual(["A", "B"]);
    act(() => io.fire([el("C"), el("D")]));
    expect(w.of("u-strip")).toEqual(["C", "D"]);
    act(() => io.fire([el("C")], 0));
    expect(w.of("u-strip")).toEqual([]);
    act(() => io.fire([el("D")]));
    unmount();
    expect(w.of("u-strip")).toEqual([]);
    w.off();
  });

  it("a re-render (StrictMode too) keeps every row observed once: no loss-then-gain flap", () => {
    const w = watch();
    const tell: string[][] = [];
    const off = onLeaseHolds((key, ids) => { if (key.startsWith("u-strip#")) tell.push(ids); });
    const { container, rerender, unmount } = render(<StrictMode><Strip ids={["A", "B"]} /></StrictMode>);
    const io = FakeIO.all.at(-1)!;
    act(() => io.fire([container.querySelector('[data-id="A"]')!, container.querySelector('[data-id="B"]')!]));
    const calls = io.observeCalls;
    const told = tell.length;
    rerender(<StrictMode><Strip ids={["A", "B"]} /></StrictMode>);
    rerender(<StrictMode><Strip ids={["A", "B"]} /></StrictMode>);
    expect(io.observeCalls).toBe(calls);
    expect(tell.length).toBe(told);
    expect(w.of("u-strip")).toEqual(["A", "B"]);
    unmount();
    off();
    w.off();
  });

  it("a row that unmounts while on screen leaves the lease, and a row back under its key is tracked again", () => {
    const w = watch();
    const { container, rerender, unmount } = render(<Strip ids={["A", "B"]} />);
    const io = FakeIO.all[0];
    act(() => io.fire([container.querySelector('[data-id="A"]')!, container.querySelector('[data-id="B"]')!]));
    expect(w.of("u-strip")).toEqual(["A", "B"]);
    rerender(<Strip ids={["B"]} />);
    expect(w.of("u-strip")).toEqual(["B"]);
    expect(io.observed.size).toBe(1);
    rerender(<Strip ids={["A", "B"]} />);
    act(() => io.fire([container.querySelector('[data-id="A"]')!, container.querySelector('[data-id="B"]')!]));
    expect(w.of("u-strip")).toEqual(["A", "B"]);
    unmount();
    w.off();
  });

  it("several rows of one Creator (the rail) count once and stay while any is shown", () => {
    function Rail() {
      const track = useOnScreenLease("u-rail");
      return <div>{["r1", "r2", "r3"].map((k) => <span key={k} data-k={k} ref={track(k === "r3" ? "B" : "A", k)} />)}</div>;
    }
    const w = watch();
    const { container, unmount } = render(<Rail />);
    const el = (k: string) => container.querySelector(`[data-k="${k}"]`)!;
    act(() => FakeIO.all[0].fire([el("r1"), el("r2"), el("r3")]));
    expect(w.of("u-rail")).toEqual(["A", "B"]);
    act(() => FakeIO.all[0].fire([el("r2")]));
    expect(w.of("u-rail")).toEqual(["A"]);
    unmount();
    w.off();
  });

  it("without IntersectionObserver (an old browser, jsdom) nothing is leased", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const w = watch();
    const { unmount } = render(<Strip ids={["A"]} />);
    expect(w.of("u-strip")).toEqual([]);
    unmount();
    w.off();
  });
});
