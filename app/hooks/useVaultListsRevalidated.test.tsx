import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { useVaultLists, useVaultListsRevalidated, vaultListsKey } from "@/hooks/useVaultMedia";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const AID = "acct-1";
const OLD = { type: "custom", id: 1, name: "Old", hasMedia: true, photosCount: 2 };
const NEW = { type: "custom", id: 2, name: "New", hasMedia: true, photosCount: 4 };

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);
const urls = () => relayGet.mock.calls.map((c) => String(c[0]));
const names = (d: { list: { name: string }[] } | undefined) => (d?.list ?? []).map((l) => l.name);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  relayGet.mockReset();
  relayGet.mockImplementation((url: string) =>
    Promise.resolve({ list: url.includes("revalidate=1") ? [OLD, NEW] : [OLD], hasMore: false }));
});
afterEach(cleanup);

describe("useVaultListsRevalidated", () => {
  it("a fresh cached copy without the new folder: one revalidate read on open brings it in", async () => {
    client.setQueryData(vaultListsKey(AID), { list: [OLD], hasMore: false });
    const { result, rerender } = renderHook(() => useVaultListsRevalidated(AID), { wrapper });
    await waitFor(() => expect(names(result.current.data)).toEqual(["Old", "New"]));
    rerender();
    expect(urls()).toHaveLength(1);
    expect(urls()[0]).toContain("revalidate=1");
  });

  it("a cold cache: the plain read paints, then one revalidate read", async () => {
    const { result } = renderHook(() => useVaultListsRevalidated(AID), { wrapper });
    await waitFor(() => expect(names(result.current.data)).toEqual(["Old", "New"]));
    expect(urls()).toHaveLength(2);
    expect(urls()[0]).not.toContain("revalidate=1");
    expect(urls()[1]).toContain("revalidate=1");
  });

  it("a failed revalidate keeps the painted list", async () => {
    client.setQueryData(vaultListsKey(AID), { list: [OLD], hasMore: false });
    relayGet.mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useVaultListsRevalidated(AID), { wrapper });
    await waitFor(() => expect(relayGet).toHaveBeenCalledTimes(1));
    expect(names(result.current.data)).toEqual(["Old"]);
  });
});


it.each([false, true])("manual refresh retries with cache bypass (persistent failure: %s)", async (persistent) => {
  client.setDefaultOptions({ mutations: { retryDelay: 0 } });
  client.setQueryData(vaultListsKey(AID), { list: [OLD], hasMore: false });
  relayGet.mockImplementation((url: string) => Promise.resolve({
    list: url.includes("refresh=1") ? [NEW] : [OLD], hasMore: false,
  }));
  let rejectFirst!: (error: Error) => void;
  relayGet.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }));
  if (persistent) relayGet.mockRejectedValueOnce(new Error("502"));

  const { result } = renderHook(() => useVaultLists(AID), { wrapper });
  act(() => result.current.refresh());
  await waitFor(() => {
    expect(result.current.isRefreshing).toBe(true);
    expect(urls()).toHaveLength(1);
  });
  const second = renderHook(() => useVaultLists(AID), { wrapper });
  act(() => rejectFirst(new Error("502")));
  await waitFor(() => expect(result.current.isRefreshing).toBe(false));
  expect(urls()).toHaveLength(2);
  expect(urls().every((url) => url.includes("refresh=1"))).toBe(true);
  await waitFor(() => {
    expect(result.current.refreshFailed).toBe(persistent);
    expect(names(second.result.current.data)).toEqual(persistent ? ["Old"] : ["New"]);
  });
});
