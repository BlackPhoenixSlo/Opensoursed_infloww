/**
 * useAccounts — per-principal cache isolation (cross-tenant leak fix).
 *
 * /admin/accounts returns the FULL multi-tenant registry when called
 * UNauthenticated (the dev-curl fallback). The owner query used to cache
 * under a principal-agnostic key `["accounts"]` with a 3-day staleTime, so
 * a list fetched in an unauthed window (app boot before /auth/me resolves,
 * a brief session expiry) persisted and bled into the next owner's
 * session — surfacing another owner's models in this owner's picker, then
 * 403'ing on save ("account X is not one of yours").
 *
 * The fix keys the cache by `user.user_id` and refuses to fetch until a
 * principal is known. These tests assert both guarantees: switching
 * principals never serves the previous user's cached accounts, and a null
 * user never triggers the unauthed /admin/accounts fetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { hydrate, QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

// useUser / useChatter are driven by mutable module-level state so each test
// (and each rerender) can flip the active principal.
let mockUser: { user_id: string; username: string } | null = null;
let mockChatter: unknown = null;
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: mockUser, loading: false }),
  useOptionalUser: () => ({ user: mockUser, loading: false }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: mockChatter }),
  useOptionalChatter: () => ({ chatter: mockChatter }),
}));

import { useAccounts, useActiveAccounts, useOfManagerAccounts, useWatcherAccounts } from "@/hooks/useAccounts";
import { useCreatorFreshness } from "@/hooks/useCreatorFreshness";
import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  relayGet.mockReset();
  mockUser = null;
  mockChatter = null;
});
afterEach(() => { cleanup(); });

describe("useAccounts principal isolation", () => {
  it("does NOT fetch /admin/accounts before a principal is known", async () => {
    // No user, no chatter (app boot / login screen). Pre-fix this fired an
    // unauthed /admin/accounts → full registry → poisoned cache.
    renderHook(() => useAccounts(), { wrapper });
    await new Promise((r) => setTimeout(r, 0));
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("never serves one owner's cached accounts to the next owner", async () => {
    relayGet
      .mockResolvedValueOnce({ accounts: [{ id: "acct-a" }], active_account_id: "acct-a" })
      .mockResolvedValueOnce({ accounts: [{ id: "acct-b" }], active_account_id: "acct-b" });

    mockUser = { user_id: "owner-A", username: "owner-a" };
    const { result, rerender } = renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(result.current.data?.accounts?.[0]?.id).toBe("acct-a"));

    // Flip to a different signed-in owner on the same browser/cache.
    mockUser = { user_id: "owner-B", username: "owner-b" };
    rerender();

    // Must refetch under the new principal's key — not reuse owner-A's
    // still-fresh cache entry.
    await waitFor(() => expect(result.current.data?.accounts?.[0]?.id).toBe("acct-b"));
    expect(relayGet).toHaveBeenCalledTimes(2);
  });
});

describe("watchers", () => {
  const row = (id: string, role?: string) => ({
    account_id: id, nickname: id, color: null, owner_id: "o", owner_username: "o", is_active: true, role,
  });

  it("a chatter's granted watcher goes to `watchers` and OF Manager only, never the Creator roster", async () => {
    mockChatter = { id: "ch1" };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [row("c1"), row("w1", "watcher")] })));
    try {
      const { result } = renderHook(() => ({
        all: useAccounts().data, active: useActiveAccounts(), watchers: useWatcherAccounts(), ofm: useOfManagerAccounts(),
      }), { wrapper });
      await waitFor(() => expect(result.current.all?.accounts.length).toBe(1));
      expect(result.current.all?.accounts.map((a) => a.id)).toEqual(["c1"]);
      expect(result.current.active.map((a) => a.id)).toEqual(["c1"]);
      expect(result.current.watchers.map((a) => [a.id, a.role])).toEqual([["w1", "watcher"]]);
      expect(result.current.ofm.map((a) => a.id)).toEqual(["c1", "w1"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("an owner's watchers get a Creator's defaults; OF Manager lists those with a session after the Creators", async () => {
    relayGet.mockResolvedValueOnce({
      accounts: [{ id: "c1", has_session: true }],
      active_account_id: "c1",
      watchers: [{ id: "w1", has_session: true }, { id: "w2", has_session: false }],
    });
    mockUser = { user_id: "owner-A", username: "owner-a" };
    const { result } = renderHook(() => ({ watchers: useWatcherAccounts(), ofm: useOfManagerAccounts() }), { wrapper });
    await waitFor(() => expect(result.current.watchers.length).toBe(2));
    expect(result.current.watchers[0]).toMatchObject({ id: "w1", is_active: true, proxy_down: false, role: "watcher" });
    expect(result.current.ofm.map((a) => a.id)).toEqual(["c1", "w1"]);
  });
});

describe("freshness (the Shared refresher's snapshot on each row)", () => {
  const snap = (aid: string, seq: number, at: number | null = 4_000) => ({
    account_id: aid, boot: 1000, seq, now: 5_000, at, cycle_s: null, live: null, live_since: null, values: {},
  });
  const chatterRow = (id: string, extra: Record<string, unknown> = {}) => ({
    account_id: id, nickname: id, color: null, owner_id: "o", owner_username: "o", is_active: true, ...extra,
  });
  const store = (principal: string) => client.getQueryData(["creator-freshness", principal]) as Record<string, unknown> | undefined;

  it("owner rows keep `freshness` and seed the store from the network answer", async () => {
    relayGet.mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap("c1", 2) }, { id: "c2" }], active_account_id: "c1" });
    mockUser = { user_id: "owner-A", username: "owner-a" };
    // The reader in its own component: only the store's change re-renders it.
    const reader = renderHook(() => ({ c1: useCreatorFreshness("c1"), c2: useCreatorFreshness("c2") }), { wrapper });
    expect(reader.result.current).toEqual({ c1: null, c2: null });
    const { result } = renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(result.current.data?.accounts.length).toBe(2));
    expect(result.current.data?.accounts[0].freshness).toEqual(snap("c1", 2));
    expect(result.current.data?.accounts[1]).not.toHaveProperty("freshness");
    await waitFor(() => expect(store("owner-A")?.c1).toMatchObject({ seq: 2, at: 4_000 }));
    expect(store("owner-A")).not.toHaveProperty("c2");
    expect(reader.result.current.c1).toMatchObject({ seq: 2, at: 4_000 });
    expect(reader.result.current.c2).toBeNull();
  });

  it("chatter rows keep `freshness` through the normalization and seed the chatter's store", async () => {
    mockChatter = { chatter_id: "ch1" };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, json: async () => [chatterRow("c1", { freshness: snap("c1", 3) }), chatterRow("c2"), chatterRow("w1", { role: "watcher" })],
    })));
    try {
      const { result } = renderHook(() => useAccounts(), { wrapper });
      await waitFor(() => expect(result.current.data?.accounts.length).toBe(2));
      expect(result.current.data?.accounts.map((a) => [a.id, a.freshness?.seq])).toEqual([["c1", 3], ["c2", undefined]]);
      expect(result.current.data?.accounts[1]).not.toHaveProperty("freshness");
      await waitFor(() => expect(store("ch1")?.c1).toMatchObject({ seq: 3 }));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("never seeds from the persisted accounts copy, only from the network answer after it", async () => {
    mockUser = { user_id: "owner-A", username: "owner-a" };
    // The persisted copy, restored as the persister does (its old dataUpdatedAt kept).
    hydrate(client, {
      mutations: [],
      queries: [{
        queryKey: ["accounts", "owner-A"], queryHash: JSON.stringify(["accounts", "owner-A"]),
        state: {
          data: { accounts: [{ id: "c1", is_active: true, freshness: snap("c1", 9, 9_000) }], active_account_id: "c1", watchers: [] },
          dataUpdateCount: 3, dataUpdatedAt: Date.now() - 3_600_000, error: null, errorUpdateCount: 0, errorUpdatedAt: 0,
          fetchFailureCount: 0, fetchFailureReason: null, fetchMeta: null, isInvalidated: false, status: "success", fetchStatus: "idle",
        },
      }],
    });
    let answer!: (v: unknown) => void;
    relayGet.mockReturnValueOnce(new Promise((r) => { answer = r; }));
    const { result } = renderHook(() => useAccounts(), { wrapper });
    expect(result.current.data?.accounts[0].freshness?.seq).toBe(9);
    await new Promise((r) => setTimeout(r, 0));
    expect(store("owner-A")).toBeUndefined();
    answer({ accounts: [{ id: "c1", freshness: snap("c1", 2, 4_000) }], active_account_id: "c1" });
    await waitFor(() => expect(store("owner-A")?.c1).toMatchObject({ seq: 2, at: 4_000 }));
  });

  it("a network answer drops a held Creator whose row lost `freshness` or is absent (a switch-off evicts all)", async () => {
    relayGet
      .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap("c1", 2) }, { id: "c2", freshness: snap("c2", 2) },
        { id: "c3", freshness: snap("c3", 2) }], active_account_id: "c1" })
      .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap("c1", 3) }, { id: "c2" }], active_account_id: "c1" })
      .mockResolvedValueOnce({ accounts: [{ id: "c1" }, { id: "c2" }], active_account_id: "c1" });
    mockUser = { user_id: "owner-A", username: "owner-a" };
    const reader = renderHook(() => ({ c1: useCreatorFreshness("c1"), c2: useCreatorFreshness("c2") }), { wrapper });
    renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(Object.keys(store("owner-A") ?? {}).sort()).toEqual(["c1", "c2", "c3"]));
    await client.refetchQueries({ queryKey: ["accounts", "owner-A"] });
    await waitFor(() => expect(Object.keys(store("owner-A") ?? {})).toEqual(["c1"]));
    expect(store("owner-A")?.c1).toMatchObject({ seq: 3 });
    expect(reader.result.current.c2).toBeNull();
    await client.refetchQueries({ queryKey: ["accounts", "owner-A"] });   // Knob off + restart: no row carries it
    await waitFor(() => expect(store("owner-A")).toEqual({}));
    expect(reader.result.current).toEqual({ c1: null, c2: null });
  });

  it("an identity change clears the previous principal's store", async () => {
    relayGet
      .mockResolvedValueOnce({ accounts: [{ id: "c1", freshness: snap("c1", 2) }], active_account_id: "c1" })
      .mockResolvedValueOnce({ accounts: [{ id: "c9" }], active_account_id: "c9" });
    mockUser = { user_id: "owner-A", username: "owner-a" };
    const { rerender } = renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(store("owner-A")?.c1).toMatchObject({ seq: 2 }));
    mockUser = { user_id: "owner-B", username: "owner-b" };
    rerender();
    await waitFor(() => expect(store("owner-A")).toEqual({}));
  });

  it("Knob off (no row carries it): today's rows, no store entry", async () => {
    relayGet.mockResolvedValueOnce({ accounts: [{ id: "c1", has_session: true }], active_account_id: "c1" });
    mockUser = { user_id: "owner-A", username: "owner-a" };
    const { result } = renderHook(() => useAccounts(), { wrapper });
    await waitFor(() => expect(result.current.data?.accounts.length).toBe(1));
    expect(result.current.data?.accounts).toEqual([{ id: "c1", has_session: true, is_active: true }]);
    await new Promise((r) => setTimeout(r, 0));
    expect(client.getQueryCache().findAll({ queryKey: ["creator-freshness"] })).toEqual([]);
  });
});
