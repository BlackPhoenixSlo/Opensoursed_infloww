import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InfiniteQueryObserver, QueryClient, QueryObserver } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { relay, type VaultListsResp, type VaultMediaResp } from "@/lib/relay";
import { fetchAllVaultLists, revalidateVaultLists, revalidateVaultMediaFirstPage, vaultListsKey, vaultMediaQuery } from "./useVaultMedia";

import { reloadBrokenThumbs } from "./vaultRefresh";
import { invalidateVaultGrid } from "./useVaultCache";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";

const opts = { accountId: "rewarm" };
const query = vaultMediaQuery(opts);
const first: VaultMediaResp = {
  list: [{ id: 1, type: "photo", files: { full: { url: "https://cdn.example/expired" } } }], hasMore: true,
};
const fresh: VaultMediaResp = {
  list: [{ id: 1, type: "photo", files: { full: { url: "https://cdn.example/renewed" } }, canView: true }],
  hasMore: true,
};
const later: VaultMediaResp = { list: [{ id: 25, type: "photo" }], hasMore: true };
const last: VaultMediaResp = { list: [{ id: 49, type: "photo" }], hasMore: false };
const get = vi.mocked(relay.get);
let qc: QueryClient;
let unsub: (() => void) | undefined;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } } });
  qc.setQueryData(query.queryKey, { pages: [first, later], pageParams: [0, 24] });
  get.mockReset();
  get.mockResolvedValue(fresh);
});
afterEach(() => { unsub?.(); unsub = undefined; qc.clear(); });

function startNextPage() {
  const next = deferred<VaultMediaResp>();
  get.mockImplementation((url) => String(url).includes("revalidate=1") ? Promise.resolve(fresh) : next.promise);
  const observer = new InfiniteQueryObserver(qc, { ...query, staleTime: Infinity });
  unsub = observer.subscribe(() => {});
  const fetching = observer.fetchNextPage();
  return { next, fetching };
}

function expectRenewed(pages: VaultMediaResp[], pageParams: number[]) {
  expect(qc.getQueryData(query.queryKey)).toEqual({ pages: [fresh, ...pages], pageParams });
}

describe("picker first-page revalidation", () => {
  it("same IDs replace signed URLs and metadata, preserving the user's later pages", async () => {
    await revalidateVaultMediaFirstPage(qc, opts);
    expectRenewed([later], [0, 24]);
    expect(get).toHaveBeenCalledOnce();
    expect(get.mock.calls[0][0]).toContain("offset=0&type=all&sort=desc&revalidate=1");
  });

  it.each(["same IDs", "changed IDs"])("a newer refetch wins over a delayed open response with %s", async (membership) => {
    const response = deferred<VaultMediaResp>();
    const newer = {
      ...fresh,
      list: [{ ...fresh.list![0], files: { full: { url: "https://cdn.example/newer-refresh" } } }],
    };
    get.mockImplementation((url) => {
      const params = new URL(String(url), "https://relay.example").searchParams;
      return params.has("revalidate") ? response.promise : Promise.resolve(params.get("offset") === "0" ? newer : later);
    });
    const observer = new InfiniteQueryObserver(qc, { ...query, staleTime: Infinity });
    unsub = observer.subscribe(() => {});
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    await observer.refetch();
    const refetched = qc.getQueryData(query.queryKey);
    expect(refetched?.pages[0]).toEqual(newer);
    response.resolve(membership === "same IDs" ? fresh : { list: [{ id: 99, type: "photo" }], hasMore: false });
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(refetched);
    expect(get).toHaveBeenCalledTimes(3); // open + both refetched pages
  });

  it("allows pagination-only appends during the open's network read", async () => {
    const response = deferred<VaultMediaResp>();
    get.mockImplementation((url) => String(url).includes("revalidate=1") ? response.promise : Promise.resolve(last));
    const observer = new InfiniteQueryObserver(qc, { ...query, staleTime: Infinity });
    unsub = observer.subscribe(() => {});
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    await observer.fetchNextPage();
    response.resolve(fresh);
    await refreshing;
    expectRenewed([later, last], [0, 24, 48]);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("does not overwrite a recreated query even when it reuses the same head", async () => {
    const response = deferred<VaultMediaResp>();
    get.mockReturnValue(response.promise);
    const old = qc.getQueryData(query.queryKey);
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    qc.removeQueries({ queryKey: query.queryKey, exact: true });
    qc.setQueryData(query.queryKey, old);
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(old);
  });

  it.each(["before", "after"])("keeps an in-flight next page that lands %s revalidation", async (order) => {
    const { next, fetching } = startNextPage();
    if (order === "before") { next.resolve(last); await fetching; }
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    // Let revalidation receive page 1 while page 3 still holds its old page-1 snapshot.
    await Promise.resolve();
    await Promise.resolve();
    if (order === "after") { next.resolve(last); await fetching; }
    await refreshing;
    expectRenewed([later, last], [0, 24, 48]);
    expect(get).toHaveBeenCalledTimes(2); // exactly page 3 + page 1, no restart
  });

  it("still renews page 1 when the in-flight next page fails", async () => {
    const { next, fetching } = startNextPage();
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    await Promise.resolve();
    next.reject(new Error("next page failed"));
    await fetching;
    await refreshing;
    expectRenewed([later], [0, 24]);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it.each(["ids", "hasMore"])("changed %s resets offsets and cancels an obsolete next page", async (change) => {
    const { next, fetching } = startNextPage();
    const changed = change === "ids" ? { ...fresh, list: [{ id: 2, type: "photo" as const }] } : { ...fresh, hasMore: false };
    get.mockResolvedValue(changed);
    await revalidateVaultMediaFirstPage(qc, opts);
    next.resolve(last);
    await fetching;
    expect(qc.getQueryData(query.queryKey)).toEqual({ pages: [changed], pageParams: [0] });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("a failed revalidation keeps every cached page", async () => {
    const old = qc.getQueryData(query.queryKey);
    get.mockRejectedValue(new Error("offline"));
    await expect(revalidateVaultMediaFirstPage(qc, opts)).rejects.toThrow("offline");
    expect(qc.getQueryData(query.queryKey)).toBe(old);
  });

  it("does not recreate a cache removed during the network read", async () => {
    const response = deferred<VaultMediaResp>();
    get.mockReturnValue(response.promise);
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    qc.removeQueries({ queryKey: query.queryKey, exact: true });
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBeUndefined();
  });

  it.each(["removed", "replaced", "recreated"])("keeps cache %s while waiting for in-flight paging", async (change) => {
    const { next, fetching } = startNextPage();
    const refreshing = revalidateVaultMediaFirstPage(qc, opts);
    await Promise.resolve();
    await Promise.resolve();
    await qc.cancelQueries({ queryKey: query.queryKey, exact: true });
    const replacement = change === "recreated" ? qc.getQueryData(query.queryKey)
      : { pages: [{ list: [{ id: 99, type: "photo" as const }], hasMore: false }], pageParams: [0] };
    if (change === "recreated") qc.removeQueries({ queryKey: query.queryKey, exact: true });
    if (change === "removed") qc.removeQueries({ queryKey: query.queryKey, exact: true });
    else qc.setQueryData(query.queryKey, replacement);
    next.resolve(last);
    await fetching;
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toEqual(change === "removed" ? undefined : replacement);
  });
});

it("keeps an inactive query stale after repeated mutation invalidation during thumbnail reload", async () => {
  const response = deferred<VaultMediaResp>();
  const requested = deferred<void>();
  get.mockImplementation((url) => {
    const params = new URL(String(url), "https://relay.example").searchParams;
    if (params.get("offset") === "0") { requested.resolve(); return response.promise; }
    return Promise.resolve(later);
  });
  const observer = new InfiniteQueryObserver(qc, { ...query, staleTime: Infinity });
  unsub = observer.subscribe(() => {});
  const before = qc.getQueryData(query.queryKey);
  const refreshing = reloadBrokenThumbs(qc, opts.accountId, "live");
  await requested.promise;
  expect(qc.getQueryState(query.queryKey)?.isInvalidated).toBe(true);
  unsub();
  unsub = undefined;
  expect(qc.getQueryCache().find({ queryKey: query.queryKey })?.isActive()).toBe(false);
  await invalidateVaultGrid(qc, opts.accountId);
  expect(get).toHaveBeenCalledOnce(); // Inactive mutation invalidation starts no refetch.
  expect(qc.getQueryState(query.queryKey)?.isInvalidated).toBe(true);
  response.resolve(fresh); // Read began before the mutation.
  await refreshing;
  expect(qc.getQueryState(query.queryKey)?.isInvalidated).toBe(true);
  expect(qc.getQueryData(query.queryKey)).toBe(before);
});

// Real observers exercise fetch start/completion, including structural sharing.
// No clock advancement: two refreshes in the same millisecond must still order.
describe.each(["open", "thumbnails"] as const)("%s refresh ownership", (reader) => {
  const refresh = () => reader === "open"
    ? revalidateVaultMediaFirstPage(qc, opts)
    : reloadBrokenThumbs(qc, opts.accountId, "live");

  function setup() {
    const response = deferred<VaultMediaResp>();
    const requested = deferred<void>();
    get.mockImplementation((url) => {
      const params = new URL(String(url), "https://relay.example").searchParams;
      if (params.has("revalidate")) {
        if (params.get("offset") === "0") { requested.resolve(); return response.promise; }
        return Promise.resolve(later);
      }
      return Promise.resolve(params.get("offset") === "0" ? first : later);
    });
    const observer = new InfiniteQueryObserver(qc, { ...query, staleTime: Infinity });
    unsub = observer.subscribe(() => {});
    return { response, requested: requested.promise, observer };
  }

  it.each(["grid", "resync"])("keeps inactive, already-invalidated media stale after %s", async (intent) => {
    const { response, requested } = setup();
    await invalidateVaultQueries(qc, { queryKey: query.queryKey, refetchType: "none" });
    const before = qc.getQueryData(query.queryKey);
    const refreshing = refresh();
    await requested;
    unsub!(); unsub = undefined;
    if (intent === "grid") await invalidateVaultGrid(qc, opts.accountId);
    else await invalidateVaultQueries(qc);
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryState(query.queryKey)?.isInvalidated).toBe(true);
    expect(qc.getQueryData(query.queryKey)).toBe(before);
    expect(get).toHaveBeenCalledOnce();
  });

  it("an unrelated model's invalidation does not discard a valid response", async () => {
    const { response, requested } = setup();
    const refreshing = refresh();
    await requested;
    await invalidateVaultGrid(qc, "another-model");
    response.resolve(fresh);
    await refreshing;
    expectRenewed([later], [0, 24]);
    expect(get).toHaveBeenCalledTimes(reader === "open" ? 1 : 2);
  });

  it.each(["same IDs", "changed IDs"])("preserves a newer in-flight refetch against %s", async (membership) => {
    const older = membership === "same IDs" ? fresh : { list: [{ id: 99, type: "photo" as const }], hasMore: false };
    const { response, requested, observer } = setup();
    const refreshing = refresh();
    await requested;
    const newer = deferred<VaultMediaResp>();
    let signal: AbortSignal | undefined;
    get.mockImplementation((url, _ctx, abort) => {
      const params = new URL(String(url), "https://relay.example").searchParams;
      if (params.has("revalidate")) return Promise.resolve(later);
      if (params.get("offset") === "0") { signal = abort; return newer.promise; }
      return Promise.resolve(later);
    });
    const fetching = observer.refetch();
    response.resolve(older);
    // Do not await the old sidecar: an incorrect implementation can wait for the newer fetch.
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    expect(signal?.aborted).toBe(false);
    expect(qc.getQueryState(query.queryKey)?.fetchStatus).toBe("fetching");
    newer.resolve(fresh);
    await fetching;
    await refreshing;
    expectRenewed([later], [0, 24]);
  });

  it.each(["identical", "new payload"])("preserves a completed newer refetch with %s data", async (payload) => {
    const { response, requested, observer } = setup();
    const before = qc.getQueryData(query.queryKey);
    const refreshing = refresh();
    await requested;
    if (payload === "new payload") get.mockResolvedValue({ ...fresh, hasMore: false });
    await observer.refetch();
    const refetched = qc.getQueryData(query.queryKey);
    if (payload === "identical") expect(refetched).toBe(before); // TanStack structural sharing
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(refetched);
  });

  it.each(["removed", "recreated", "manual identical write", "reset"])("rejects a response after cache %s", async (change) => {
    const { response, requested } = setup();
    const refreshing = refresh();
    await requested;
    const before = qc.getQueryData(query.queryKey);
    // Reset the active Query directly to avoid starting a replacement request.
    if (change === "reset") qc.getQueryCache().find({ queryKey: query.queryKey })!.reset();
    else {
      if (change !== "manual identical write") qc.removeQueries({ queryKey: query.queryKey, exact: true });
      if (change !== "removed") qc.setQueryData(query.queryKey, before);
    }
    const replacement = qc.getQueryData(query.queryKey);
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(replacement);
  });

  it.each(["before", "during"])("preserves pagination landing %s the sidecar reply", async (order) => {
    const { response, requested, observer } = setup();
    const refreshing = refresh();
    await requested;
    const next = deferred<VaultMediaResp>();
    get.mockImplementation((url) => String(url).includes("revalidate=1") ? Promise.resolve(later) : next.promise);
    const fetching = observer.fetchNextPage();
    if (order === "before") { next.resolve(last); await fetching; }
    response.resolve(fresh);
    await Promise.resolve(); await Promise.resolve();
    if (order === "during") { next.resolve(last); await fetching; }
    await refreshing;
    expectRenewed([later, last], [0, 24, 48]);
    expect(get).toHaveBeenCalledTimes(reader === "open" ? 2 : 3);
  });

  it("a refetch started while waiting for pagination owns the result", async () => {
    const { response, requested, observer } = setup();
    const refreshing = refresh();
    await requested;
    const next = deferred<VaultMediaResp>();
    get.mockImplementation((url) => String(url).includes("revalidate=1") ? Promise.resolve(later) : next.promise);
    const paging = observer.fetchNextPage();
    response.resolve(fresh);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    get.mockImplementation((url) => Promise.resolve(String(url).includes("offset=0") ? first : later));
    await observer.refetch();
    const newer = qc.getQueryData(query.queryKey);
    next.resolve(last);
    await paging;
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(newer);
  });

  it.each(["in flight", "completed"])("changed membership drops obsolete pagination (%s)", async (state) => {
    const { response, requested, observer } = setup();
    const refreshing = refresh();
    await requested;
    const next = deferred<VaultMediaResp>();
    get.mockImplementation((url) => String(url).includes("revalidate=1") ? Promise.resolve(later) : next.promise);
    const paging = observer.fetchNextPage();
    if (state === "completed") { next.resolve(last); await paging; }
    const changed = { list: [{ id: 99, type: "photo" as const }], hasMore: false };
    response.resolve(changed);
    await refreshing;
    next.resolve(last);
    await paging;
    expect(qc.getQueryData(query.queryKey)).toEqual({ pages: [changed], pageParams: [0] });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("a newer sidecar owns the cache even if it returns identical data", async () => {
    const { response, requested } = setup();
    const refreshing = refresh();
    await requested;
    get.mockImplementation((url) => Promise.resolve(String(url).includes("offset=0") ? first : later));
    await revalidateVaultMediaFirstPage(qc, opts);
    const newer = qc.getQueryData(query.queryKey);
    response.resolve(fresh);
    await refreshing;
    expect(qc.getQueryData(query.queryKey)).toBe(newer);
  });
});

describe("folder refresh ownership", () => {
  const key = vaultListsKey(opts.accountId);
  const old: VaultListsResp = { list: [{ id: 1, name: "Old folder", type: "custom", hasMedia: true }], hasMore: false };
  const newer: VaultListsResp = { list: [...old.list!, { id: 2, name: "New folder", type: "custom", hasMedia: true }], hasMore: false };
  function setup() {
    qc.setQueryData(key, old);
    const response = deferred<VaultListsResp>();
    get.mockImplementation((url) => String(url).includes("revalidate=1") ? response.promise : Promise.resolve(newer));
    const observer = new QueryObserver(qc, {
      queryKey: key, queryFn: () => fetchAllVaultLists(opts), staleTime: Infinity,
    });
    unsub = observer.subscribe(() => {});
    return { response, observer };
  }

  it.each(["grid", "folder", "resync"])("keeps inactive, already-invalidated folders stale after %s", async (intent) => {
    const { response } = setup();
    await invalidateVaultQueries(qc, { queryKey: key, refetchType: "none" });
    const before = qc.getQueryData(key);
    const refreshing = revalidateVaultLists(qc, opts.accountId);
    unsub!(); unsub = undefined;
    if (intent === "grid") await invalidateVaultGrid(qc, opts.accountId);
    else await invalidateVaultQueries(qc, intent === "folder" ? { queryKey: key } : undefined, { cancelRefetch: false });
    response.resolve(newer);
    await refreshing;
    expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
    expect(qc.getQueryData(key)).toBe(before);
    expect(get).toHaveBeenCalledOnce();
  });

  it.each(["in flight", "completed", "identical"])("active invalidation %s wins over older open", async (state) => {
    const { response } = setup();
    const refreshing = revalidateVaultLists(qc, opts.accountId);
    const pending = deferred<VaultListsResp>();
    get.mockReturnValue(state === "in flight" ? pending.promise : Promise.resolve(state === "identical" ? old : newer));
    const invalidating = qc.invalidateQueries({ queryKey: key });
    if (state !== "in flight") await invalidating;
    const expected = qc.getQueryData(key);
    response.resolve({ list: [], hasMore: false });
    await refreshing;
    expect(qc.getQueryData(key)).toBe(expected);
    if (state === "in flight") { pending.resolve(newer); await invalidating; expect(qc.getQueryData(key)).toEqual(newer); }
  });

  it.each(["recreated", "removed", "manual identical write"])("does not overwrite %s folder cache", async (change) => {
    const { response } = setup();
    const refreshing = revalidateVaultLists(qc, opts.accountId);
    if (change !== "manual identical write") qc.removeQueries({ queryKey: key, exact: true });
    if (change !== "removed") qc.setQueryData(key, old);
    const expected = qc.getQueryData(key);
    response.resolve(newer);
    await refreshing;
    expect(qc.getQueryData(key)).toBe(expected);
  });

  it("populates a missing folder cache and releases its listener after success/failure", async () => {
    const cache = qc.getQueryCache();
    const subscribe = cache.subscribe.bind(cache);
    const cleanup = vi.fn();
    vi.spyOn(cache, "subscribe").mockImplementation((listener) => {
      const stop = subscribe(listener);
      return () => { cleanup(); stop(); };
    });
    get.mockResolvedValue(newer);
    await revalidateVaultLists(qc, opts.accountId);
    expect(qc.getQueryData(key)).toEqual(newer);
    expect(cleanup).toHaveBeenCalledTimes(1);
    get.mockRejectedValue(new Error("offline"));
    await expect(revalidateVaultLists(qc, opts.accountId)).rejects.toThrow("offline");
    expect(cleanup).toHaveBeenCalledTimes(2);
  });
});
