/**
 * useOFUser — the full profile on its own key (`["of-user", aid, fid, "full"]`),
 * apart from the name key the chat list, notifications and name lookups write:
 * a name write never refreshes the full read's freshness, a slim name lookup
 * can't answer for it, a money invalidation reaches the full key alone (and is
 * read on the next open), and a reader moving to a Fan with only a name reads
 * his full profile.
 */
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider, useQuery, type QueryClient } from "@tanstack/react-query";

const { relayGet, relayPatch } = vi.hoisted(() => ({ relayGet: vi.fn(), relayPatch: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: { get: relayGet, patch: relayPatch, post: vi.fn() },
}));

import { useFan } from "@/hooks/useFan";
import { OF_USER_STALE_MS, ofUserNameQuery, useOFUser } from "@/hooks/useOFUser";
import { makeTestQueryClient } from "@/test-utils";

const NAME = (f: number) => ["of-user", "a", f];
const FULL = (f: number) => ["of-user", "a", f, "full"];

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const paths = () => relayGet.mock.calls.map(([p]) => p as string);

beforeEach(() => {
  client = makeTestQueryClient();
  // Seeds stand for a cache read earlier: kept with no reader mounted.
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, gcTime: Infinity } });
  relayGet.mockReset();
  relayPatch.mockReset();
});
afterEach(() => { cleanup(); });

describe("useOFUser", () => {
  it("a Fan with only a name is read in full, and the read reaches the name key", async () => {
    client.setQueryData(NAME(1), { id: 1, name: "Named", customNickname: "Team nick" });
    relayGet.mockResolvedValue({ id: 1, name: "Named", lastSeen: "2026-10-20T10:00:00Z", subscribedOnData: { totalSumm: 9 } });
    const { result } = renderHook(() => useOFUser("a", 1), { wrapper });
    await waitFor(() => expect(result.current.data?.subscribedOnData).toEqual({ totalSumm: 9 }));
    expect(paths()).toEqual(["/api/of/v2/users/1"]);
    expect(client.getQueryData(NAME(1))).toMatchObject({ customNickname: "Team nick", lastSeen: "2026-10-20T10:00:00Z" });
    // Only the name fields: the money block stays on the full key.
    expect(client.getQueryData(NAME(1))).not.toHaveProperty("subscribedOnData");
  });

  it("a full read leaves the avatar thumbnail on the name key, as the name lookup does", async () => {
    relayGet.mockResolvedValue({ id: 1, avatar: "https://cdn/full.jpg", avatarThumbs: { c50: "https://cdn/50.jpg", c144: "https://cdn/144.jpg" } });
    const { result } = renderHook(() => useOFUser("a", 1), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(client.getQueryData(NAME(1))).toMatchObject({ avatar: "https://cdn/50.jpg" });
  });

  it("a name lookup on the name key keeps the presence the full read left there", async () => {
    client.setQueryData(NAME(1), { id: 1, name: "Old", lastSeen: "2026-10-20T10:00:00Z" });
    relayGet.mockResolvedValue({ 1: { name: "New", username: "new" } });
    await client.fetchQuery({ ...ofUserNameQuery("a", 1), staleTime: 0 });
    expect(client.getQueryData(NAME(1))).toMatchObject({ name: "New", lastSeen: "2026-10-20T10:00:00Z" });
  });

  it("a reader switched to a Fan with only a name reads his full profile", async () => {
    client.setQueryData(FULL(1), { id: 1 });
    client.setQueryData(NAME(2), { id: 2, name: "Slim" });
    relayGet.mockResolvedValue({ id: 2 });
    const { rerender } = renderHook(({ f }) => useOFUser("a", f), { wrapper, initialProps: { f: 1 } });
    await act(async () => {});
    expect(paths()).toEqual([]);
    rerender({ f: 2 });   // a FanDrawer not keyed by Fan, moving on
    await act(async () => {});
    expect(paths()).toEqual(["/api/of/v2/users/2"]);
  });

  it("name writes (chat list, notifications) leave the full read's age alone", async () => {
    const readAt = Date.now() - OF_USER_STALE_MS - 1_000;
    client.setQueryData(FULL(1), { id: 1, subscribedOnData: { totalSumm: 5 } }, { updatedAt: readAt });
    for (let i = 0; i < 3; i++) client.setQueryData(NAME(1), (p: object | undefined) => ({ ...p, name: `n${i}` }));
    expect(client.getQueryState(FULL(1))?.dataUpdatedAt).toBe(readAt);
    const { result } = renderHook(() => useOFUser("a", 1), { wrapper });
    expect(result.current.isStale).toBe(true);
  });

  it("an invalidation (a discount set) re-reads the full profile, and not the name lookup sharing the Fan", async () => {
    client.setQueryData(FULL(1), { id: 1, subscribedOnData: { discountPercent: null } });
    client.setQueryData(NAME(1), { id: 1, name: "Named" });
    relayGet.mockImplementation((p: string) => Promise.resolve(p.startsWith("/api/of/v2/users/list")
      ? { 1: { name: "Named" } }
      : { id: 1, subscribedOnData: { discountPercent: 15 } }));
    const { result } = renderHook(() => {
      // The Deep link's own /users/list lookup on the name key, as MessagesPro mounts it.
      useQuery(ofUserNameQuery("a", 1));
      return useOFUser("a", 1);
    }, { wrapper });
    await act(async () => {});
    relayGet.mockClear();
    // DiscountSubmenu's invalidation.
    await act(async () => { await client.invalidateQueries({ queryKey: FULL(1), exact: true }); });
    await waitFor(() => expect(result.current.data?.subscribedOnData).toEqual({ discountPercent: 15 }));
    expect(paths()).toEqual(["/api/of/v2/users/1"]);
  });

  it("an invalidation with no reader mounted (a tip, the drawer closed) is read on the next open; otherwise an open reads nothing", async () => {
    client.setQueryData(FULL(1), { id: 1, subscribedOnData: { totalSumm: 5 } });
    relayGet.mockResolvedValue({ id: 1, subscribedOnData: { totalSumm: 25 } });
    const first = renderHook(() => useOFUser("a", 1), { wrapper });
    await act(async () => {});
    first.unmount();
    expect(paths()).toEqual([]);

    await act(async () => { await client.invalidateQueries({ queryKey: FULL(1), exact: true }); });
    const { result } = renderHook(() => useOFUser("a", 1), { wrapper });
    await waitFor(() => expect(result.current.data?.subscribedOnData).toEqual({ totalSumm: 25 }));
    expect(paths()).toEqual(["/api/of/v2/users/1"]);
  });

  it("a nickname save renames the cached full profile without refreshing its age", async () => {
    const readAt = Date.now() - 60_000;
    client.setQueryData(FULL(1), { id: 1, displayName: "Old", subscribedOnData: { totalSumm: 5 } }, { updatedAt: readAt });
    relayPatch.mockResolvedValue({ custom_nickname: "New" });
    const { result } = renderHook(() => useFan("a", 1), { wrapper });
    await act(async () => { await result.current.update.mutateAsync({ custom_nickname: "New" }); });
    expect(client.getQueryData(FULL(1))).toMatchObject({ displayName: "New", subscribedOnData: { totalSumm: 5 } });
    expect(client.getQueryState(FULL(1))?.dataUpdatedAt).toBe(readAt);
  });

  it("a nickname save keeps a pending invalidation of the full profile pending", async () => {
    client.setQueryData(FULL(1), { id: 1, displayName: "Old" });
    await client.invalidateQueries({ queryKey: FULL(1), exact: true, refetchType: "none" });
    relayPatch.mockResolvedValue({ custom_nickname: "New" });
    const { result } = renderHook(() => useFan("a", 1), { wrapper });
    await act(async () => { await result.current.update.mutateAsync({ custom_nickname: "New" }); });
    expect(client.getQueryData(FULL(1))).toMatchObject({ displayName: "New" });
    expect(client.getQueryState(FULL(1))?.isInvalidated).toBe(true);
  });
});
