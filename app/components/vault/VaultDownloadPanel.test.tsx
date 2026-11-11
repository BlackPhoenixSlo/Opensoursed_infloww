/**
 * useVaultDownload across a switch of model: the page's one download (VaultDownloadProvider) outlives the per-model
 * remount, so a start for model B must never take over model A's run (its account, its sink, its retry) unless B's
 * own `start` was accepted. The queue (vaultDownload.ts) and the reducer are the real ones; the relay's reads, the
 * network and the folder picker are stubs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/lib/shareToken", () => ({ resolveShareToken: () => null }));
// `hold.on`: a share run counts every fetched file as huge, so any unsaved file holds the workers in room() (as
// >= SHARE_HELD_BYTES unsaved would) without the test allocating 400 MB.
const hold = vi.hoisted(() => ({ on: false }));
vi.mock("@/components/vault/vaultDownloadReducer", async (orig) => {
  const m = await orig<typeof import("./vaultDownloadReducer")>();
  return { ...m, canFetchMore: (s: Parameters<typeof m.canFetchMore>[0]) =>
    m.canFetchMore(s) && !(hold.on && s.sink === "share" && m.heldBytes(s) > 0) };
});

import { relay, type VaultMedia } from "@/lib/relay";

import { useVaultDownload } from "./VaultDownloadPanel";
import { linksFor, type StartArgs } from "./vaultDownload";
import { canRetry, summarize, unsaved } from "./vaultDownloadReducer";

const get = relay.get as unknown as ReturnType<typeof vi.fn>;
const picker = vi.fn();
const fetched: string[] = [];
let failId: number | null = null;

// A picked folder: every handle accepts writes (nothing kept).
function dir(): FileSystemDirectoryHandle {
  return {
    getDirectoryHandle: async () => dir(),
    getFileHandle: async () => ({ createWritable: async () => new WritableStream<Uint8Array>() }),
  } as unknown as FileSystemDirectoryHandle;
}
const media = (id: number) =>
  ({ id, type: "photo", files: { full: { url: `https://cdn2.onlyfans.com/files/a/${id}.jpg` } }, listStates: [] }) as unknown as VaultMedia;
const runA: StartArgs = { accountId: "acc-a", creator: "Amy", mode: "selection", label: "2 selected",
                          media: [media(1), media(2)], source: "mirror" };
const runB: StartArgs = { accountId: "acc-b", creator: "Bea", mode: "vault", label: "whole vault", source: "mirror" };
const deferred = <T,>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
const closed = () => new DOMException("closed", "AbortError");

beforeEach(() => {
  hold.on = false;
  fetched.length = 0;
  failId = 2;
  picker.mockReset();
  (window as unknown as { showDirectoryPicker: unknown }).showDirectoryPicker = picker;
  get.mockReset().mockImplementation(async (u: string) => (u.startsWith("/admin/vault-ai/download/info") ? { direct: false } : {}));
  vi.spyOn(console, "warn").mockImplementation(() => {});   // writeLinks: jsdom's Blob has no stream()
  vi.stubGlobal("fetch", vi.fn(async (u: string) => {
    fetched.push(u);
    return u.includes(`media_id=${failId}`) ? new Response("", { status: 502 })
      : new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } });
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A's selection run through the relay (no proxy check: direct off), media 2 failing. */
async function aDoneWithAFailure() {
  picker.mockResolvedValueOnce(dir());
  const h = renderHook(() => useVaultDownload());
  act(() => h.result.current.start(runA));
  await waitFor(() => expect(h.result.current.state.phase).toBe("done"));
  expect(summarize(h.result.current.state)).toMatchObject({ done: 1, failed: 1 });
  fetched.length = 0;
  failId = null;
  return h;
}

describe("useVaultDownload: one run, its own model", () => {
  it("a picker closed for B leaves A's run: Retry failed still downloads as A", async () => {
    const { result } = await aDoneWithAFailure();
    picker.mockRejectedValueOnce(closed());
    act(() => result.current.start(runB));
    await waitFor(() => expect(result.current.picking).toBe(false));
    expect(result.current.state).toMatchObject({ phase: "done", creator: "Amy" });
    expect(canRetry(result.current.state)).toBe(true);

    act(() => result.current.retryFailed());
    await waitFor(() => expect(summarize(result.current.state)).toMatchObject({ done: 2, failed: 0 }));
    expect(fetched).toHaveLength(1);
    const u = new URL(fetched[0], "http://x");
    expect(u.pathname).toBe("/admin/vault-ai/download");
    expect(u.searchParams.get("account_id")).toBe("acc-a");
    expect(u.searchParams.get("media_id")).toBe("2");
    expect(result.current.state.accountId).toBe("acc-a");
  });

  it("the card title and the links file name the run's creator once", async () => {
    const { result } = await aDoneWithAFailure();
    expect(result.current.state.label).toBe("2 selected");
    const lf = linksFor(result.current.state);
    expect(lf.txt.split("\n")[0]).toMatch(/^# Amy: 2 selected \(2 files\), made /);
    expect(lf.html).toContain("<title>Amy: 2 selected</title>");
    expect(lf.rows.every((r) => new URL(r.app).searchParams.get("account_id") === "acc-a")).toBe(true);
  });

  it("a second start while the first's picker is open is ignored", async () => {
    const pick = deferred<FileSystemDirectoryHandle>();
    picker.mockReturnValueOnce(pick.promise);
    failId = null;
    const { result } = renderHook(() => useVaultDownload());
    act(() => result.current.start(runA));
    act(() => result.current.start(runB));
    expect(picker).toHaveBeenCalledTimes(1);
    await act(async () => pick.resolve(dir()));
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(result.current.state).toMatchObject({ accountId: "acc-a", creator: "Amy" });
    expect(fetched.every((u) => u.includes("account_id=acc-a"))).toBe(true);
    expect(fetched).toHaveLength(2);
  });

  it("Retry failed while another start's picker is open does nothing (no second queue)", async () => {
    const { result } = await aDoneWithAFailure();
    const pick = deferred<FileSystemDirectoryHandle>();
    picker.mockReturnValueOnce(pick.promise);
    act(() => result.current.start(runB));
    act(() => result.current.retryFailed());
    await new Promise((r) => setTimeout(r, 20));
    expect(fetched).toEqual([]);
    expect(result.current.state.phase).toBe("done");
    await act(async () => pick.reject(closed()));
    await waitFor(() => expect(result.current.picking).toBe(false));
    expect(result.current.state).toMatchObject({ phase: "done", accountId: "acc-a" });
  });

  it("Cancel then Retry failed runs while the cancelled queue still winds down; its late worker can't touch the retry", async () => {
    failId = null;
    const late = [deferred<Response>(), deferred<Response>()];   // media 1: the cancelled run's fetch, then the retry's
    let n1 = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      fetched.push(u);
      if (u.includes("media_id=1")) return late[n1++].promise;   // ignores the abort: a slow server
      return new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } });
    }));
    picker.mockResolvedValueOnce(dir());
    const { result, unmount } = renderHook(() => useVaultDownload());
    act(() => result.current.start(runA));
    await waitFor(() => expect(n1).toBe(1));
    act(() => result.current.cancel());
    expect(canRetry(result.current.state)).toBe(true);

    act(() => result.current.retryFailed());
    expect(result.current.state.phase).toBe("running");
    await waitFor(() => expect(n1).toBe(2));
    // the cancelled run's fetch answers now: its worker's failure must not land on the retry's active media 1
    await act(async () => late[0].resolve(new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } })));
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.state.items.find((i) => i.id === 1)?.status).toBe("active");
    await act(async () => late[1].resolve(new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } })));
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(summarize(result.current.state)).toMatchObject({ done: 2, failed: 0 });
    unmount();
  });

  it("Cancel then a new start runs while the cancelled queue still winds down", async () => {
    failId = null;
    const slow = deferred<Response>();
    let n1 = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      fetched.push(u);
      if (u.includes("media_id=1") && n1++ === 0) return slow.promise;
      return new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } });
    }));
    picker.mockResolvedValueOnce(dir()).mockResolvedValueOnce(dir());
    const { result } = renderHook(() => useVaultDownload());
    act(() => result.current.start(runA));
    await waitFor(() => expect(n1).toBe(1));
    act(() => result.current.cancel());
    expect(result.current.state.phase).toBe("cancelled");

    act(() => result.current.start(runA));
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(summarize(result.current.state)).toMatchObject({ done: 2, failed: 0 });
    expect(picker).toHaveBeenCalledTimes(2);
    await act(async () => slow.resolve(new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } })));
    await new Promise((r) => setTimeout(r, 20));
    expect(summarize(result.current.state)).toMatchObject({ done: 2, failed: 0 });
  });

  it("phone: a run done with a failed file and unsaved files held (workers idle) still lets Retry failed run", async () => {
    delete (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker;
    vi.stubGlobal("navigator", { ...navigator, canShare: () => true });
    hold.on = true;
    const { result, unmount } = renderHook(() => useVaultDownload());
    expect(result.current.sink).toBe("share");
    act(() => result.current.start(runA));
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(summarize(result.current.state)).toMatchObject({ done: 1, failed: 1 });
    expect(unsaved(result.current.state)).toBe(1);

    act(() => result.current.retryFailed());
    expect(result.current.state.phase).toBe("running");
    unmount();
  });
});
