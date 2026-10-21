/**
 * useRevalidate: the vault reads the Relay serves from its day-long cache (the folder list, a vault dialog's first 24)
 * show the cached answer at once, then read once more past the cache (refresh=1) per page open, and show that.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { mirrorQuery, useRevalidate, VAULT_LISTS } from "./ofMirrorData";
import { relay } from "./relay";

/** OF's own vault responses, captured through the Relay and scrubbed. */
const fixture = (name: string) => JSON.parse(readFileSync(resolve(__dirname, `__fixtures__/of/vault-${name}.json`), "utf8"));
/** The Relay's cached folder list, and OF's answer now (a folder renamed since, the sort changed). */
const CACHED = fixture("lists");
const FRESH = { ...CACHED, sort: "name", list: CACHED.list.map((l: { name: string }, i: number) => (i === 0 ? { ...l, name: "Renamed" } : l)) };
const DIALOG = "/api/of/v2/vault/media?limit=24";
const MEDIA = fixture("media-all");

let client: QueryClient;
let get: MockInstance;
const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
/** The read as useOfData makes it: mirrorQuery, then useRevalidate on the same path. */
const useRead = (path: string | null) => {
  const r = useQuery(mirrorQuery("1", path, true));
  useRevalidate("1", path, r);
  return r;
};
const refreshes = () => get.mock.calls.filter((c) => (c[3] as { refresh?: boolean } | undefined)?.refresh);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  get = vi.spyOn(relay, "get").mockImplementation(async (path: string, _ctx?: unknown, _s?: unknown, opts?: { refresh?: boolean }) =>
    path === VAULT_LISTS ? (opts?.refresh ? FRESH : CACHED) : MEDIA,
  );
});
afterEach(() => {
  cleanup();
  get.mockRestore();
});

describe("useRevalidate", () => {
  it("the folder list: the cached answer first, then exactly one refresh=1 read, whose answer replaces it", async () => {
    const { result, rerender } = renderHook(() => useRead(VAULT_LISTS), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(get.mock.calls[0]).toEqual([VAULT_LISTS, { accountId: "1" }]); // the cached read goes first
    await waitFor(() => expect(result.current.data).toEqual(FRESH));
    expect(get.mock.calls[1]).toEqual([VAULT_LISTS, { accountId: "1" }, undefined, { refresh: true }]);
    for (let i = 0; i < 5; i++) rerender();
    await new Promise((r) => setTimeout(r, 20));
    expect(get).toHaveBeenCalledTimes(2); // not per render
  });

  it("each open rechecks once more; a failed recheck keeps the cached answer", async () => {
    const first = renderHook(() => useRead(VAULT_LISTS), { wrapper });
    await waitFor(() => expect(refreshes()).toHaveLength(1));
    first.unmount();
    get.mockImplementation(async (_p: string, _c?: unknown, _s?: unknown, opts?: { refresh?: boolean }) => {
      if (opts?.refresh) throw new Error("OF is down");
      return CACHED;
    });
    client.setQueryData(mirrorQuery("1", VAULT_LISTS, true).queryKey, CACHED);
    const again = renderHook(() => useRead(VAULT_LISTS), { wrapper });
    await waitFor(() => expect(refreshes()).toHaveLength(2));
    await new Promise((r) => setTimeout(r, 20));
    expect(again.result.current.data).toEqual(CACHED);
  });

  it("a vault dialog's first 24: cached, then one recheck; none for no path or before the cached answer", async () => {
    const { result } = renderHook(() => useRead(DIALOG), { wrapper });
    await waitFor(() => expect(refreshes()).toEqual([[DIALOG, { accountId: "1" }, undefined, { refresh: true }]]));
    expect(get.mock.calls[0]).toEqual([DIALOG, { accountId: "1" }]);
    expect(result.current.data).toEqual(MEDIA);
    renderHook(() => useRead(null), { wrapper });
    get.mockImplementation(() => new Promise(() => {})); // the cached read never answers
    renderHook(() => useRead(`${DIALOG}&type=video`), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(refreshes()).toHaveLength(1);
  });
});
