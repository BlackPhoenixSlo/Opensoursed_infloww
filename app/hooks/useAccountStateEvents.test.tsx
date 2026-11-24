import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
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

// useAccounts' principal, for the resync row (null: usePrincipalId's "anon", as every other row has it).
let mockUser: { user_id: string; username: string } | null = null;
vi.mock("@/contexts/UserContext", async (orig) => ({
  ...(await orig<object>()),
  useUser: () => ({ user: mockUser, loading: false }),
  useOptionalUser: () => (mockUser ? { user: mockUser, loading: false } : null),
}));
vi.mock("@/contexts/ChatterContext", async (orig) => ({
  ...(await orig<object>()),
  useChatter: () => ({ chatter: null }),
  useOptionalChatter: () => null,
}));

import { makeTestQueryClient } from "@/test-utils";
import { useAccounts } from "@/hooks/useAccounts";
import { relay } from "@/lib/relay";
import { isArmed, resetReadGate } from "@/lib/ofReadGate";
import { resetRosterCountsModuleState } from "./useRosterCounts";
import {
  COALESCE_MS, RESYNC_MIN_MS, SALES_MIN_MS, flipCachedReadState, useAccountStateEvents, warmMark,
} from "./useAccountStateEvents";

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

  it("session_dead refetches the owner's and the chatter's own accounts lists (the Disconnected mark in either scope)", () => {
    const { keys } = mount();
    emit("session_dead", { __account_id: "7", session_dead: { reason: "401" } });
    expect(keys()).toEqual([["accounts"], ["chatter", "self", "accounts"], ["app-errors", "recent"]]);
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

    it("writes the notif count it carries, not its roster; re-reads only lists read before it, gathered per window; arms at once", () => {
      const qc = qcKeep();
      const counts = { counts: { 7: { unread: 0, owe_reply: 0 }, 9: { unread: 4, owe_reply: 0 } } };
      qc.setQueryData(ROSTER, counts);
      qc.setQueryData(["of-notif-count", "7"], 1);
      qc.setQueryData(["notif-list", "7", "tip"], { list: [] });         // read before the warm
      empty(qc, ["notif-list", "8", "tip"]);                              // unarmed: never read
      empty(qc, ["of-notif-count", "8"]);
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7", { roster: { unread: 2, owe_reply: 1, as_of: 200 }, notif_count: 5, now: Date.now() }));
      emit("creator_warmed", warmed("8", { roster: { unread: 1, owe_reply: 0, as_of: 200 }, notif_count: 3, now: Date.now() }));
      expect([isArmed("7"), isArmed("8"), isArmed("9")]).toEqual([true, true, false]);
      expect(qc.getQueryData(ROSTER)).toBe(counts);
      expect([qc.getQueryData(["of-notif-count", "7"]), qc.getQueryData(["of-notif-count", "8"])]).toEqual([5, 3]);
      expect(keys()).toEqual([]);
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([["notif-list", "7", "tip"]]);
    });

    it("without values (an old relay, an expired entry): re-reads what it holds, not what it never read; never roster-counts", () => {
      const qc = qcKeep();
      qc.setQueryData(ROSTER, { counts: {} });
      qc.setQueryData(["of-notif-count", "7"], 1);
      empty(qc, ["notif-list", "7", "tip"]);
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7"));
      emit("creator_warmed", warmed("7"));
      act(() => { vi.advanceTimersByTime(COALESCE_MS); });
      expect(keys()).toEqual([["of-notif-count", "7"]]);
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

    it("a roster read in flight when it came: untouched, no re-read; the read's answer stands", async () => {
      const qc = qcKeep();
      qc.setQueryData(ROSTER, { counts: { 7: { unread: 0, owe_reply: 0 } } });
      const end = inFlight(qc, ROSTER, { counts: { 7: { unread: 5, owe_reply: 0 } } });
      const { keys } = mount(qc);
      emit("creator_warmed", warmed("7", { roster: { unread: 2, owe_reply: 1, as_of: 200 }, now: Date.now() }));
      expect((qc.getQueryData(ROSTER) as { counts: Record<string, unknown> }).counts[7]).toEqual({ unread: 0, owe_reply: 0 });
      await end();
      expect((qc.getQueryData(ROSTER) as { counts: Record<string, unknown> }).counts[7]).toEqual({ unread: 5, owe_reply: 0 });
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

  describe("creator_refreshed", () => {
    // No principal provider mounted: usePrincipalId's "anon".
    const STORE = ["creator-freshness", "anon"];
    const snap = (seq: number, at: number) => ({
      account_id: "7", boot: 1000, seq, now: 5_000, at, cycle_s: 600, live: "up", live_since: null, values: {},
    });
    const refreshed = (seq: number, at: number) => ({ __account_id: "7", creator_refreshed: snap(seq, at) });
    beforeEach(() => { resetReadGate(); });

    it("dispatches `refreshed` into the store; arms no read, invalidates no money list", () => {
      const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false, staleTime: 0 } } });
      qc.setQueryData(["notif-list", "7", "tip"], { list: [] });
      const { keys } = mount(qc);
      emit("creator_refreshed", refreshed(2, 4_000));
      expect((qc.getQueryData(STORE) as Record<string, unknown>)["7"]).toMatchObject({ seq: 2, at: 4_000 });
      emit("creator_refreshed", refreshed(1, 3_000));  // older (a replay): the newer stays
      expect((qc.getQueryData(STORE) as Record<string, unknown>)["7"]).toMatchObject({ seq: 2, at: 4_000 });
      act(() => { vi.advanceTimersByTime(COALESCE_MS * 2); });
      expect(isArmed("7")).toBe(false);
      expect(keys()).toEqual([]);
      expect(qc.getQueryState(["notif-list", "7", "tip"])?.isInvalidated).toBe(false);
    });

    it("a malformed body writes no store entry", () => {
      const qc = makeTestQueryClient();
      mount(qc);
      emit("creator_refreshed", { __account_id: "7", creator_refreshed: { account_id: "7" } });
      expect(qc.getQueryData(STORE)).toBeUndefined();
    });

    it("a ping's `fresh` dispatches `confirmed`: `at` forward only, never a slot's `at`, nothing armed or read", () => {
      const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false, staleTime: 0 } } });
      const { keys } = mount(qc);
      const slot = { unread_total: { n: 4, at: 4_500 } };
      emit("creator_refreshed", { __account_id: "7", creator_refreshed: { ...snap(2, 4_000), values: slot } });
      emit("ping", { ts: 9.9, fresh: { "7": 9_000, "8": 9_000 } });
      const held = () => (qc.getQueryData(STORE) as Record<string, Record<string, unknown>>);
      expect(held()["7"]).toMatchObject({ seq: 2, at: 9_000, now: 9_900, values: slot });
      expect(held()).not.toHaveProperty("8");  // no snapshot to move
      emit("ping", { ts: 10.9, fresh: { "7": 8_000 } });
      expect(held()["7"]).toMatchObject({ at: 9_000, now: 9_900 });
      expect(isArmed("7")).toBe(false);
      expect(keys()).toEqual([]);
    });

    it("a ping with no store held writes no entry", () => {
      const qc = makeTestQueryClient();
      mount(qc);
      emit("ping", { ts: 9.9, fresh: { "7": 9_000 } });
      expect(qc.getQueryData(STORE)).toBeUndefined();
    });

    it("a missed `creator_refreshed` replayed on reconnect is applied, `at` kept at the max", () => {
      const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false, staleTime: 0 } } });
      mount(qc);
      emit("creator_refreshed", refreshed(2, 4_000));
      emit("ping", { ts: 9.9, fresh: { "7": 9_000 } });
      // The stream dropped; its reconnect replays the change it missed (seq 3, read before the ping's `at`).
      emit("creator_refreshed", { __account_id: "7", creator_refreshed: { ...snap(3, 6_000), live: "down" } });
      expect((qc.getQueryData(STORE) as Record<string, unknown>)["7"]).toMatchObject({ seq: 3, live: "down", at: 9_000 });
    });
  });

  describe("resync (the rings could not replay what the tab missed)", () => {
    const snap = (seq: number, at: number) => ({
      account_id: "c1", boot: 1000, seq, now: 5_000, at, cycle_s: 600, live: "up", live_since: null, values: {},
    });
    afterEach(() => { mockUser = null; vi.restoreAllMocks(); });

    it("refetches the accounts lists and reseeds the store from the new answer", async () => {
      vi.useRealTimers();
      mockUser = { user_id: "owner-A", username: "owner-a" };
      const get = vi.spyOn(relay, "get")
        .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap(1, 4_000) }], active_account_id: "c1" })
        .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap(4, 6_000) }], active_account_id: "c1" });
      const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
      renderHook(() => { useAccountStateEvents(); useAccounts(); }, {
        wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
      });
      const held = () => (qc.getQueryData(["creator-freshness", "owner-A"]) as Record<string, unknown> | undefined)?.c1;
      await waitFor(() => expect(held()).toMatchObject({ seq: 1, at: 4_000 }));
      emit("resync");
      await waitFor(() => expect(held()).toMatchObject({ seq: 4, at: 6_000 }));
      expect(get.mock.calls.map(([path]) => path)).toEqual(["/admin/accounts", "/admin/accounts"]);
    });
  });

  describe("ping `badge` (a Badge version the tab missed)", () => {
    const snap = (seq: number, v: number) => ({
      account_id: "c1", boot: 1000, seq, now: 5_000, at: 4_000, cycle_s: 600, live: "up", live_since: null,
      values: { unread_total: { n: 2, at: 4_000, v, grey: null } },
    });
    afterEach(() => { mockUser = null; vi.restoreAllMocks(); });

    it("one behind ping refetches the accounts answer once (its seed catches up); an equal ping none", async () => {
      vi.useRealTimers();
      mockUser = { user_id: "owner-A", username: "owner-a" };
      const get = vi.spyOn(relay, "get")
        .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap(1, 3) }], active_account_id: "c1" })
        .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap(2, 4) }], active_account_id: "c1" });
      const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
      renderHook(() => { useAccountStateEvents(); useAccounts(); }, {
        wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
      });
      const held = () => (qc.getQueryData(["creator-freshness", "owner-A"]) as Record<string, Record<string, unknown>> | undefined)?.c1;
      const calls = () => get.mock.calls.filter(([path]) => path === "/admin/accounts").length;
      await waitFor(() => expect(held()).toMatchObject({ seq: 1 }));
      emit("ping", { ts: 9.9, fresh: {}, badge: { c1: 3 } });
      await new Promise((r) => setTimeout(r, 20));
      expect(calls()).toBe(1);
      emit("ping", { ts: 29.9, fresh: {}, badge: { c1: 4 } });
      await waitFor(() => expect(held()).toMatchObject({ seq: 2 }));
      emit("ping", { ts: 49.9, fresh: {}, badge: { c1: 4 } });
      await new Promise((r) => setTimeout(r, 20));
      expect(calls()).toBe(2);
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

  it("does not re-arm them when Idle mode closed the stream, nor on its reopen", () => {
    const { keys } = mount();
    act(() => { for (const fn of stateListeners) fn(true); });
    paused = true;
    act(() => { for (const fn of stateListeners) fn(false); });
    paused = false;
    act(() => { for (const fn of stateListeners) fn(true); });
    expect(keys()).toEqual([]);
  });

  it("refetches roster-counts once on the drop and once more on the reconnect, nothing else on the reconnect", () => {
    const { keys } = mount();
    const roster = () => keys().filter((k) => JSON.stringify(k) === '["roster-counts"]').length;
    act(() => { for (const fn of stateListeners) fn(true); });
    act(() => { for (const fn of stateListeners) fn(false); });
    expect(roster()).toBe(1);
    const atDrop = keys().length;
    act(() => { for (const fn of stateListeners) fn(true); });
    expect(keys().slice(atDrop)).toEqual([["roster-counts"]]);
    act(() => { for (const fn of stateListeners) fn(false); });
    act(() => { for (const fn of stateListeners) fn(true); });
    expect(roster()).toBe(4);
  });

  it("chat_read_changed flips the fan's row in every cached list holding the Creator, All Models included; no read", () => {
    const qc = makeTestQueryClient();
    const row = (aid: string, fid: number, unread: boolean) =>
      ({ __accountId: aid, withUser: { id: fid }, hasUnread: unread, unreadMessagesCount: unread ? 1 : 0 });
    const lists = {
      model: ["chats", "model", "a1", null, null, null, 25],
      unread: ["chats", "model", "a1", "unread", null, null, 25],
      all: ["chats", "all", "a1,a2", null, null, null, 25],
      other: ["chats", "model", "a2", null, null, null, 25],
    };
    const seed = { pages: [{ rows: [row("a1", 7, true), row("a1", 8, true)], hasMore: false }], pageParams: [0] };
    for (const k of [lists.model, lists.unread]) qc.setQueryData(k, seed);
    qc.setQueryData(lists.all, { pages: [{ rows: [row("a2", 7, true), row("a1", 7, true)], hasMore: false }], pageParams: [0] });
    qc.setQueryData(lists.other, { pages: [{ rows: [row("a2", 7, true)], hasMore: false }], pageParams: [0] });
    const before = Object.fromEntries(Object.entries(lists).map(([n, k]) => [n, qc.getQueryData(k)]));
    const { spy } = mount(qc);
    const unreadOf = (k: unknown[]) => (qc.getQueryData(k) as typeof seed).pages[0].rows
      .map((c) => `${c.__accountId}:${c.withUser.id}:${c.hasUnread ? 1 : 0}`);

    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 9, unread: 0, at: 1 } });
    for (const [n, k] of Object.entries(lists)) expect(qc.getQueryData(k)).toBe(before[n]);  // unknown fan: no-op

    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 0, at: 1 } });
    expect(unreadOf(lists.model)).toEqual(["a1:7:0", "a1:8:1"]);
    expect(unreadOf(lists.unread)).toEqual(["a1:8:1"]);  // the Unread list (none on screen) drops it
    expect(unreadOf(lists.all)).toEqual(["a2:7:1", "a1:7:0"]);
    expect(qc.getQueryData(lists.other)).toBe(before.other);

    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: "all", unread: 0, at: 2 } });
    expect(unreadOf(lists.model)).toEqual(["a1:7:0", "a1:8:0"]);
    expect(unreadOf(lists.unread)).toEqual([]);
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 8, unread: 1, at: 3 } });
    expect(unreadOf(lists.unread)).toEqual(["a1:8:1"]);  // copied in from a cached list
    expect(unreadOf(lists.model)).toEqual(["a1:7:0", "a1:8:1"]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("chat_restrict_changed writes the fan's restrict flags into every cached list and his OF user; no OF read", () => {
    const qc = makeTestQueryClient();
    const restricted = {
      __accountId: "a1", withUser: { id: 7, isRestricted: true, badgeExcluded: true },
      canSendMessage: false, canNotSendReason: "muted",
    };
    const model = ["chats", "model", "a1", null, null, null, 25];
    const all = ["chats", "all", "a1,a2", null, null, null, 25];
    const other = ["chats", "model", "a2", null, null, null, 25];
    for (const k of [model, all]) qc.setQueryData(k, { pages: [{ rows: [restricted], hasMore: false }], pageParams: [0] });
    qc.setQueryData(other, { pages: [{ rows: [{ ...restricted, __accountId: "a2" }], hasMore: false }], pageParams: [0] });
    const otherBefore = qc.getQueryData(other);
    qc.setQueryData(["of-user", "a1", 7, "full"], { id: 7, isRestricted: true });
    const { keys } = mount(qc);
    const rowOf = (k: unknown[]) => (qc.getQueryData(k) as { pages: { rows: typeof restricted[] }[] }).pages[0].rows[0];

    emit("chat_restrict_changed", { __account_id: "a1", chat_restrict_changed: { fan_id: 7, restricted: false } });
    for (const k of [model, all]) {
      expect(rowOf(k)).toEqual({ __accountId: "a1", withUser: { id: 7 }, canSendMessage: true, canNotSendReason: null });
    }
    expect(qc.getQueryData(other)).toBe(otherBefore);
    expect(qc.getQueryData(["of-user", "a1", 7, "full"])).toEqual({ id: 7, isRestricted: false });
    expect(keys()).toEqual([["automation-restrict", "a1"]]);

    emit("chat_restrict_changed", { __account_id: "a1", chat_restrict_changed: { fan_id: "7", restricted: true } });
    expect(rowOf(model)).toEqual(restricted);
    expect(qc.getQueryData(["of-user", "a1", 7, "full"])).toEqual({ id: 7, isRestricted: true });
  });

  it("chat_read_changed older than a list's read (a replay after reconnect) leaves that list alone", () => {
    const qc = makeTestQueryClient();
    const row = (fid: number, unread: boolean) =>
      ({ __accountId: "a1", withUser: { id: fid }, hasUnread: unread, unreadMessagesCount: unread ? 1 : 0 });
    const key = ["chats", "model", "a1", null, null, null, 25];
    qc.setQueryData(key, { pages: [{ rows: [row(7, true)], hasMore: false, askedAt: 5_000 }], pageParams: [0] });
    const before = qc.getQueryData(key);
    mount(qc);
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 0, at: 4_999 } });
    expect(qc.getQueryData(key)).toBe(before);
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 0, at: 5_001 } });
    expect((qc.getQueryData(key) as { pages: { rows: { hasUnread: boolean }[] }[] }).pages[0].rows[0].hasUnread).toBe(false);
  });

  it("flips order by their Relay stamp per fan, not by arrival; a mark-all leaves a fan flipped after it (W30-mu #44)", () => {
    const qc = makeTestQueryClient();
    const row = (fid: number, unread: boolean) =>
      ({ __accountId: "a1", withUser: { id: fid }, hasUnread: unread, unreadMessagesCount: unread ? 1 : 0 });
    const key = ["chats", "model", "a1", null, null, null, 25];
    qc.setQueryData(key, { pages: [{ rows: [row(7, false), row(8, false), row(9, true)], hasMore: false, askedAt: 1 }],
      pageParams: [0] });
    mount(qc);
    const unreadOf = () => (qc.getQueryData(key) as { pages: { rows: ReturnType<typeof row>[] }[] }).pages[0].rows
      .map((c) => `${c.withUser.id}:${c.hasUnread ? 1 : 0}`);
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 1, at: 200 } });
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 0, at: 100 } });
    expect(unreadOf()).toEqual(["7:1", "8:0", "9:1"]);            // the older read, arriving late, changes nothing
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 8, unread: 1, at: 300 } });
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: "all", unread: 0, at: 250 } });
    expect(unreadOf()).toEqual(["7:0", "8:1", "9:0"]);            // all read but fan 8, marked unread after it
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 9, unread: 1, at: 240 } });
    expect(unreadOf()).toEqual(["7:0", "8:1", "9:0"]);            // older than the mark-all
  });

  it("this tab's own flip records no stamp: a newer remote flip the Relay stamped before the tab's clock applies (W30-mu #50)", () => {
    const qc = makeTestQueryClient();
    const key = ["chats", "model", "a1", null, null, null, 25];
    qc.setQueryData(key, { pages: [{ rows: [{ __accountId: "a1", withUser: { id: 7 }, hasUnread: false,
      unreadMessagesCount: 0 }], hasMore: false, askedAt: 1 }], pageParams: [0] });
    mount(qc);
    const unread = () => (qc.getQueryData(key) as { pages: { rows: { hasUnread: boolean }[] }[] }).pages[0].rows[0]
      .hasUnread;
    flipCachedReadState(qc, "a1", { fanId: 7, unread: true, at: 500 }, { own: true });   // stamped after the answer
    expect(unread()).toBe(true);
    emit("chat_read_changed", { __account_id: "a1", chat_read_changed: { fan_id: 7, unread: 0, at: 400 } });
    expect(unread()).toBe(false);
  });
});
