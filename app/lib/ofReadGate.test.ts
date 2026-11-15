import { afterEach, describe, expect, it, vi } from "vitest";

import {
  armedVersion, armRead, FALLBACK_MAX_MS, FALLBACK_QUIET_MS, fallbackDeadline, gainedOf, gateOptions, isArmed, onArmed,
  readGate, REFRESH_OLDER_MS, resetReadGate, wantsRefresh,
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

  it.each([
    // [case, arm times (s after the load), when every Creator arms (s)]
    ["no arm: the 90 s deadline", [], 90],
    ["an arm at 85 s (the warm still landing): 20 s after it", [85], 105],
    ["an arm early on: the 90 s deadline", [30], 90],
    ["arms every 10 s: capped at 300 s", Array.from({ length: 40 }, (_, i) => 10 * (i + 1)), 300],
  ] as const)("fallback while the warm makes progress: %s", (_n, arms, dueS) => {
    vi.useFakeTimers();
    const t0 = Date.now();
    resetReadGate(t0);
    const off = onArmed(() => {});
    const at = (s: number) => vi.advanceTimersByTime(t0 + s * 1000 - Date.now());
    arms.forEach((s, i) => { if (s < dueS) { at(s); armRead(`warmed-${i}`); } });
    at(dueS - 0.001);
    expect(isArmed("8")).toBe(false);
    at(dueS);
    expect(isArmed("8")).toBe(true);
    off();
  });
});

describe("fallbackDeadline", () => {
  it.each([
    ["an arm at the load", 0, APP_OPEN_WARM_FALLBACK_MS],
    ["an early arm", 10_000, APP_OPEN_WARM_FALLBACK_MS],
    ["a late arm pushes it", 85_000, 85_000 + FALLBACK_QUIET_MS],
    ["never past the cap", 299_000, FALLBACK_MAX_MS],
  ])("%s", (_n, lastArm, want) => {
    expect(fallbackDeadline(1_000_000, 1_000_000 + lastArm) - 1_000_000).toBe(want);
  });
});
