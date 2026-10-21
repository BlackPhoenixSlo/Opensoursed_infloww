import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";

type Handler = (e: Record<string, unknown>, type: string) => void;
const handlers = new Map<string, Set<Handler>>();
const stateListeners = new Set<(c: boolean) => void>();
let paused = false;
vi.mock("@/lib/events", () => ({
  eventBus: {
    isPaused: () => paused,
    on(type: string, fn: Handler) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type)!.add(fn);
      return () => handlers.get(type)!.delete(fn);
    },
    onStateChange(fn: (c: boolean) => void) {
      stateListeners.add(fn);
      fn(false);
      return () => stateListeners.delete(fn);
    },
  },
}));

import { makeTestQueryClient } from "@/test-utils";
import { COALESCE_MS, RESYNC_MIN_MS, SALES_MIN_MS, useAccountStateEvents } from "./useAccountStateEvents";

function emit(type: string, e: Record<string, unknown> = {}) {
  act(() => { for (const fn of handlers.get(type) ?? []) fn(e, type); });
}

function mount() {
  const qc = makeTestQueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries").mockResolvedValue();
  renderHook(() => useAccountStateEvents(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
  const keys = () => spy.mock.calls.map(([f]) => (f as { queryKey?: unknown } | undefined)?.queryKey ?? "ALL");
  return { spy, keys };
}

describe("useAccountStateEvents", () => {
  beforeEach(() => { vi.useFakeTimers(); handlers.clear(); stateListeners.clear(); paused = false; });
  afterEach(() => { vi.useRealTimers(); });

  it("refetches everything on resync now, and once more at the window's end for later ones", () => {
    const { keys } = mount();
    emit("resync");
    expect(keys()).toEqual(["ALL"]);
    emit("resync");
    emit("resync");
    expect(keys()).toEqual(["ALL"]);
    act(() => { vi.advanceTimersByTime(RESYNC_MIN_MS - 1); });
    expect(keys()).toEqual(["ALL"]);
    act(() => { vi.advanceTimersByTime(1); });
    expect(keys()).toEqual(["ALL", "ALL"]);
    // A window with a single resync has no trailing refetch.
    act(() => { vi.advanceTimersByTime(RESYNC_MIN_MS); });
    emit("resync");
    act(() => { vi.advanceTimersByTime(2 * RESYNC_MIN_MS); });
    expect(keys()).toEqual(["ALL", "ALL", "ALL"]);
  });

  it("gathers back-to-back run and scheduled-send events into one invalidation per key", () => {
    const { keys } = mount();
    const run = { __account_id: "7", rule_run_finished: { kind: "scheduled_send", status: "ok" } };
    emit("scheduled_send_changed", { __account_id: "7", scheduled_send_changed: { job_id: 1 } });
    emit("rule_run_finished", run);
    emit("rule_run_finished", run);
    expect(keys()).toEqual([]);
    act(() => { vi.advanceTimersByTime(COALESCE_MS); });
    expect(keys()).toEqual([
      ["scheduled-sends", "7"], ["automation-rules", "7"], ["stats", "automation-runs"],
    ]);
  });

  it("refetches the reports and dashboard on a sale, then once more per window, never the Sales records list", () => {
    const { spy } = mount();
    const sale = (fan: number) => ({ __account_id: "7", transaction_recorded: { fan_id: fan, kind: "tip" } });
    emit("transaction_recorded", sale(1));
    expect(spy).toHaveBeenCalledTimes(1);
    const { predicate } = spy.mock.calls[0][0] as { predicate: (q: unknown) => boolean };
    const hit = (queryKey: unknown[]) => predicate({ queryKey });
    expect(hit(["stats", "fan-report", "2026-03-01"])).toBe(true);
    expect(hit(["dashboard", "kpis"])).toBe(true);
    expect(hit(["competitor"])).toBe(true);
    expect(hit(["stats", "sales-records", "from=2026-03-01"])).toBe(false);
    expect(hit(["fan", "7", 1])).toBe(false);

    emit("transaction_recorded", sale(2));
    emit("transaction_recorded", sale(3));
    act(() => { vi.advanceTimersByTime(SALES_MIN_MS - 1); });
    expect(spy).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("invalidates account-state queries at once", () => {
    const { keys } = mount();
    emit("proxy_switched", { __account_id: "7", proxy_switched: { proxied: true } });
    expect(keys()).toEqual([["proxies"], ["accounts"]]);
  });

  it("re-arms the SSE-relaxed polls when the stream drops, not on first connect", () => {
    const { keys } = mount();
    act(() => { for (const fn of stateListeners) fn(true); });
    expect(keys()).toEqual([]);
    act(() => { for (const fn of stateListeners) fn(false); });
    expect(keys()).toContainEqual(["scheduled-sends"]);
    expect(keys()).toContainEqual(["automation-rules"]);
  });

  it("does not re-arm them when Idle mode closed the stream", () => {
    const { keys } = mount();
    act(() => { for (const fn of stateListeners) fn(true); });
    paused = true;
    act(() => { for (const fn of stateListeners) fn(false); });
    expect(keys()).toEqual([]);
  });
});
