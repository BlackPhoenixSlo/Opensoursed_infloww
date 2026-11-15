import { afterEach, describe, expect, it, vi } from "vitest";

import {
  armedVersion, armRead, gainedOf, gateOptions, isArmed, onArmed, readGate, REFRESH_OLDER_MS, resetReadGate, wantsRefresh,
} from "./ofReadGate";
import { APP_OPEN_WARM_FALLBACK_MS, type TabLease } from "./viewLease";

const lease = (leased: string[], selected: string | null = null): TabLease => ({ leased: new Set(leased), selected });

describe("readGate", () => {
  it.each([
    [true, true, "live"],
    [true, false, "live"],
    [false, true, "once"],
    [false, false, "off"],
  ] as const)("leased=%s armed=%s → %s", (leased, armed, want) => {
    expect(readGate({ leased, armed })).toBe(want);
  });
});

describe("gateOptions", () => {
  it.each([
    ["off", { enabled: false }],
    // eslint-disable-next-line local/no-fixed-polling -- the expected options: no poll at all
    ["once", { staleTime: Infinity, refetchInterval: false, refetchOnWindowFocus: false }],
    ["live", {}],
  ] as const)("%s", (gate, want) => {
    expect(gateOptions(gate)).toEqual(want);
  });
});

describe("gainedOf", () => {
  it.each([
    ["nothing changed", lease(["1"], "1"), lease(["1"], "1"), []],
    ["a new hold", lease(["1"]), lease(["1", "2"]), ["2"]],
    ["a dropped hold", lease(["1", "2"]), lease(["1"]), []],
    ["a selection of a leased Creator", lease(["1", "2"], "1"), lease(["1", "2"], "2"), ["2"]],
    ["a new selection, counted once", lease([]), lease(["3"], "3"), ["3"]],
    ["a cleared selection", lease(["1"], "1"), lease([], null), []],
  ])("%s", (_name, prev, next, want) => {
    expect(gainedOf(prev, next)).toEqual(want);
  });
});

describe("wantsRefresh", () => {
  it.each([
    [0, 1_000_000, true],
    [1_000_000 - REFRESH_OLDER_MS, 1_000_000, false],
    [1_000_000 - REFRESH_OLDER_MS - 1, 1_000_000, true],
    [1_000_000, 1_000_000, false],
  ])("updated %s, now %s → %s", (at, now, want) => {
    expect(wantsRefresh(at, now)).toBe(want);
  });
});

describe("armed store", () => {
  afterEach(() => { vi.useRealTimers(); resetReadGate(); });

  it("arms one Creator for the load, once", () => {
    resetReadGate();
    const v = armedVersion();
    armRead("7");
    armRead("7");
    armRead(undefined);
    expect([isArmed("7"), isArmed("8")]).toEqual([true, false]);
    expect(armedVersion()).toBe(v + 1);
  });

  it("arms every Creator at the fallback deadline, counted from the load, and tells subscribers", () => {
    vi.useFakeTimers();
    resetReadGate(Date.now() - 30_000);
    const fn = vi.fn();
    const off = onArmed(fn);
    vi.advanceTimersByTime(APP_OPEN_WARM_FALLBACK_MS - 30_000 - 1);
    expect(isArmed("8")).toBe(false);
    vi.advanceTimersByTime(1);
    expect(isArmed("8")).toBe(true);
    expect(fn).toHaveBeenCalledTimes(1);
    off();
  });
});
