import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
import { isArmed, resetReadGate } from "@/lib/ofReadGate";
import { resetRosterCountsModuleState } from "./useRosterCounts";
import { COALESCE_MS, RESYNC_MIN_MS, SALES_MIN_MS, useAccountStateEvents, warmMark } from "./useAccountStateEvents";

function emit(type: string, e: Record<string, unknown> = {}) {
  act(() => { for (const fn of handlers.get(type) ?? []) fn(e, type); });
}

function mount(qc = makeTestQueryClient()) {
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

  it("refetches the Full AI Chatter read when a full_ai_chat run finishes", () => {
    const { keys } = mount();
    emit("rule_run_finished", { __account_id: "7", rule_run_finished: { kind: "full_ai_chat", status: "ok" } });
    act(() => { vi.advanceTimersByTime(COALESCE_MS); });
    expect(keys()).toEqual([["automation-rules", "7"], ["stats", "automation-runs"], ["full-ai-today", "7"]]);
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

  describe("creator_warmed", () => {
    const warmed = (aid: string, extra: Record<string, unknown> = {}) =>
      ({ __account_id: aid, creator_warmed: { account_id: aid, at: "2026-11-09T10:00:00Z", ...extra } });
    const ROSTER = ["roster-counts", "u1"];
    const qcKeep = () => new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false, staleTime: 0 } } });
    /** A query with no data and no read (an unarmed reader's entry, lib/ofReadGate `off`). */
    const empty = (qc: QueryClient, queryKey: unknown[]) => qc.getQueryCache().build(qc, { queryKey });
    /** A query whose read is in flight; `end()` lands it. */
    function inFlight(qc: QueryClient, queryKey: unknown[], data: unknown) {
      let end!: () => void;
      void qc.fetchQuery({ queryKey, queryFn: () => new Promise((r) => { end = () => r(data); }) });
      return () => act(async () => { end(); await Promise.resolve(); await Promise.resolve(); });
    }
    beforeEach(() => { resetReadGate(); resetRosterCountsModuleState(); });

    it.each([
      // [case, state, hasValue, want]
      ["a read in flight: re-read (it may predate the warm)", { fetchStatus: "fetching", dataUpdatedAt: 5, errorUpdatedAt: 0 }, true, "must"],
      ["data, the event carries the value: written", { fetchStatus: "idle", dataUpdatedAt: 5, errorUpdatedAt: 0 }, true, "write"],
      ["no data, the event carries the value: written (an unarmed count's first read)", { fetchStatus: "idle", dataUpdatedAt: 0, errorUpdatedAt: 0 }, true, "write"],
      ["data, no value: re-read unless a read ends first", { fetchStatus: "idle", dataUpdatedAt: 5, errorUpdatedAt: 0 }, false, "unless"],
      ["an error, no value: re-read unless a read ends first", { fetchStatus: "idle", dataUpdatedAt: 0, errorUpdatedAt: 5 }, false, "unless"],
      ["never read, no value: nothing (its first read is the warm's)", { fetchStatus: "idle", dataUpdatedAt: 0, errorUpdatedAt: 0 }, false, "skip"],
    ] as const)("warmMark: %s", (_n, s, hasValue, want) => {
      expect(warmMark(s, hasValue)).toBe(want);
    });

    it("writes the counts it carries; re-reads only lists read before it, gathered per window; arms at once", () => {
      const qc = qcKeep();
      qc.setQueryData(ROSTER, { counts: { 7: { unread: 0, owe_reply: 0, as_of: 100 }, 9: { unread: 4, owe_reply: 0, as_of: 100 } } });
      qc.setQueryData(["of-notif-count", "7"], 1);
      qc.setQueryData(["notif-list", "7", "tip"], { list: [] });         // read before the warm
      empty(qc, ["notif-list", "8", "tip"]);                              // unarmed: never read
      empty(qc, ["of-notif-count", "8"]);
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7", { roster: { unread: 2, owe_reply: 1, as_of: 200 }, notif_count: 5, now: Date.now() }));
      emit("creator_warmed", warmed("8", { roster: { unread: 1, owe_reply: 0, as_of: 200 }, notif_count: 3, now: Date.now() }));
      expect([isArmed("7"), isArmed("8"), isArmed("9")]).toEqual([true, true, false]);
      expect((qc.getQueryData(ROSTER) as { counts: unknown }).counts).toEqual({
        7: { unread: 2, owe_reply: 1, as_of: 200 }, 8: { unread: 1, owe_reply: 0, as_of: 200 }, 9: { unread: 4, owe_reply: 0, as_of: 100 },
      });
      expect([qc.getQueryData(["of-notif-count", "7"]), qc.getQueryData(["of-notif-count", "8"])]).toEqual([5, 3]);
      expect(keys()).toEqual([]);
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([["notif-list", "7", "tip"]]);
    });

    it("without values (an old relay, an expired entry): re-reads what it holds, not what it never read", () => {
      const qc = qcKeep();
      qc.setQueryData(ROSTER, { counts: {} });
      qc.setQueryData(["of-notif-count", "7"], 1);
      empty(qc, ["notif-list", "7", "tip"]);
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7"));
      emit("creator_warmed", warmed("7"));
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([ROSTER, ["of-notif-count", "7"]]);
    });

    it("a list read ending after it is not re-read; one in flight when it came is, even after that read ends", async () => {
      const qc = qcKeep();
      qc.setQueryData(["notif-list", "7", "tip"], { list: [] });
      const endPurchases = inFlight(qc, ["notif-list", "7", "purchases"], { list: [] });
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7"));
      // A read of the tip list starts and ends after the warm came: served the warm's entry.
      await act(async () => { await qc.fetchQuery({ queryKey: ["notif-list", "7", "tip"], queryFn: async () => ({ list: [1] }) }); });
      await endPurchases();
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([["notif-list", "7", "purchases"]]);
    });

    it("a roster read in flight when it came: written, no re-read (that read's merge keeps the newer as_of)", () => {
      const qc = qcKeep();
      qc.setQueryData(ROSTER, { counts: { 7: { unread: 0, owe_reply: 0, as_of: 100 } } });
      inFlight(qc, ROSTER, { counts: {} });
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7", { roster: { unread: 2, owe_reply: 1, as_of: 200 }, now: Date.now() }));
      expect((qc.getQueryData(ROSTER) as { counts: Record<string, unknown> }).counts[7]).toEqual({ unread: 2, owe_reply: 1, as_of: 200 });
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([]);
    });

    it("ignores a warm with no Creator", () => {
      const { keys } = mount();
      emit("creator_warmed", { creator_warmed: {} });
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([]);
    });
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
