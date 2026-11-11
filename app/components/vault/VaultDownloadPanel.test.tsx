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
import { linksFor, STALL_MS, type StartArgs } from "./vaultDownload";
import { canRetry, summarize, unsaved } from "./vaultDownloadReducer";

const get = relay.get as unknown as ReturnType<typeof vi.fn>;
const picker = vi.fn();
const fetched: string[] = [];
let failId: number | null = null;

// A picked folder: every handle accepts writes (nothing kept); `path` names it ("root/Amy/Beach").
function dir(path = "root"): FileSystemDirectoryHandle {
  return {
    name: path.split("/").pop(), path,
    getDirectoryHandle: async (n: string) => dir(`${path}/${n}`),
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
  act(() => { void h.result.current.start(runA); });
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
    act(() => { void result.current.start(runB); });
    await waitFor(() => expect(result.current.state.picking).toBe(false));
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
    act(() => { void result.current.start(runA); });
    act(() => { void result.current.start(runB); });
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
    act(() => { void result.current.start(runB); });
    act(() => result.current.retryFailed());
    await new Promise((r) => setTimeout(r, 20));
    expect(fetched).toEqual([]);
    expect(result.current.state.phase).toBe("done");
    await act(async () => pick.reject(closed()));
    await waitFor(() => expect(result.current.state.picking).toBe(false));
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
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(n1).toBe(1));
    act(() => result.current.cancel());
    expect(canRetry(result.current.state)).toBe(true);

    act(() => result.current.retryFailed());
    await waitFor(() => expect(result.current.state.phase).toBe("running"));   // after the folder's permission check
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
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(n1).toBe(1));
    act(() => result.current.cancel());
    expect(result.current.state.phase).toBe("cancelled");

    act(() => { void result.current.start(runA); });
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
    failId = 1;   // the share sink fetches one at a time: the failure first, then the file the hold keeps unsaved
    const { result, unmount } = renderHook(() => useVaultDownload());
    expect(result.current.sink).toBe("share");
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(summarize(result.current.state)).toMatchObject({ done: 1, failed: 1 });
    expect(unsaved(result.current.state)).toBe(1);

    act(() => result.current.retryFailed());
    expect(result.current.state.phase).toBe("running");
    unmount();
  });
});

describe("useVaultDownload: the queue (folder sink)", () => {
  const ok3 = () => new Response(new Uint8Array(3), { status: 200, headers: { "content-length": "3" } });
  const selB: StartArgs = { accountId: "acc-b", creator: "Bea", mode: "selection", label: "1 selected",
                            media: [media(9)], source: "mirror" };
  /** A picked folder that records each file closed cleanly (Chrome's rules: missing without create throws). */
  function rec(written: string[], path: string): FileSystemDirectoryHandle {
    const have = new Set<string>();
    return {
      getDirectoryHandle: async (n: string) => rec(written, `${path}${n}/`),
      getFileHandle: async (n: string, o?: { create?: boolean }) => {
        if (!have.has(n) && !o?.create) throw new DOMException("missing", "NotFoundError");
        have.add(n);
        return { createWritable: async () => new WritableStream<Uint8Array>({ close: () => { written.push(`${path}${n}`); } }) };
      },
    } as unknown as FileSystemDirectoryHandle;
  }
  /** Media 1 answers when the test says; its fetch signal kept. */
  function slowA() {
    const slow = deferred<Response>();
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
      fetched.push(u);
      if (init?.signal && u.includes("media_id=1")) signals.push(init.signal);   // the open fetch
      return u.includes("media_id=1") ? slow.promise : ok3();
    }));
    return { slow, signals };
  }

  it("a download asked for while A runs is queued; it starts when A settles, into A's folder, as its own creator", async () => {
    const { slow } = slowA();
    const written: string[] = [];
    picker.mockResolvedValueOnce(rec(written, ""));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    expect(result.current.queueing).toBe(true);
    let queued: boolean | undefined;
    await act(async () => { queued = await result.current.start(selB); });
    expect(queued).toBe(true);
    expect(result.current.state.jobs.map((j) => j.creator)).toEqual(["Bea"]);
    await act(async () => slow.resolve(ok3()));
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "done", creator: "Bea", jobs: [] }));
    expect(picker).toHaveBeenCalledTimes(1);
    expect(result.current.state.finished).toMatchObject([{ creator: "Amy", total: 2, done: 2 }]);
    expect(written.filter((p) => p.endsWith(".jpg")).sort())
      .toEqual(["Amy/Unfiled/1.jpg", "Amy/Unfiled/2.jpg", "Bea/Unfiled/9.jpg"]);
  });

  it("the folder's permission lapsed: the queue pauses; Resume asks (inside the tap) and the job starts", async () => {
    const { slow } = slowA();
    const written: string[] = [];
    const perm = { q: "granted" as PermissionState };
    const requestPermission = vi.fn(async () => { perm.q = "granted"; return "granted" as PermissionState; });
    picker.mockResolvedValueOnce(Object.assign(rec(written, ""), { queryPermission: async () => perm.q, requestPermission }));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    await act(async () => { await result.current.start(selB); });
    perm.q = "prompt";
    await act(async () => slow.resolve(ok3()));
    await waitFor(() => expect(result.current.state.paused).toBe(true));
    expect(result.current.state).toMatchObject({ phase: "done", creator: "Amy" });
    act(() => result.current.resume());
    expect(requestPermission).toHaveBeenCalledTimes(1);   // called synchronously in the tap
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "done", creator: "Bea", paused: false }));
    expect(written).toContain("Bea/Unfiled/9.jpg");
    expect(picker).toHaveBeenCalledTimes(1);
  });

  it("A ends with a failure while B waits: B starts, A's failed item runs last as a retry job into the same folder", async () => {
    const slow = deferred<Response>();
    let n2 = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      fetched.push(u);
      if (u.includes("media_id=1")) return slow.promise;
      if (u.includes("media_id=2") && n2++ === 0) return new Response("", { status: 502 });
      return ok3();
    }));
    const written: string[] = [];
    picker.mockResolvedValueOnce(rec(written, ""));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    await act(async () => { await result.current.start(selB); });
    await act(async () => slow.resolve(ok3()));
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "done", jobs: [] }));
    expect(result.current.state).toMatchObject({ creator: "Amy", label: "2 selected · retry 1" });
    expect(result.current.state.finished.map((f) => [f.creator, f.failed])).toEqual([["Amy", 1], ["Bea", 0]]);
    expect(written.filter((p) => p.endsWith(".jpg")).sort())
      .toEqual(["Amy/Unfiled/1.jpg", "Amy/Unfiled/2.jpg", "Bea/Unfiled/9.jpg"]);
    expect(picker).toHaveBeenCalledTimes(1);
  });

  it("A stalls while B waits: B starts on its own and finishes, then A's stalled item runs last as a retry job", async () => {
    failId = null;
    let n1 = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      fetched.push(u);
      if (u.includes("media_id=1") && n1++ === 0) {   // 1 byte, then silence (the CDN throttled to zero)
        return new Response(new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new Uint8Array(1)); } }),
                            { status: 200, headers: { "content-length": "3" } });
      }
      return ok3();
    }));
    const written: string[] = [];
    picker.mockResolvedValueOnce(rec(written, ""));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result } = renderHook(() => useVaultDownload());
      act(() => { void result.current.start(runA); });
      await waitFor(() => expect(result.current.state.phase).toBe("running"));
      await act(async () => { await result.current.start(selB); });
      expect(result.current.state.jobs.map((j) => j.creator)).toEqual(["Bea"]);
      await act(async () => { await vi.advanceTimersByTimeAsync(STALL_MS + 100); });
      await waitFor(() => expect(result.current.state).toMatchObject({ phase: "done", jobs: [],
                                                                       label: "2 selected · retry 1" }));
      expect(result.current.state.finished.map((f) => [f.creator, f.done, f.stalled]))
        .toEqual([["Amy", 1, 1], ["Bea", 1, 0]]);
      expect(summarize(result.current.state)).toMatchObject({ total: 1, done: 1 });
      expect(written.filter((p) => p.endsWith(".jpg"))).toEqual(["Amy/Unfiled/2.jpg", "Bea/Unfiled/9.jpg", "Amy/Unfiled/1.jpg"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Retry asks for the folder's permission in the tap; refused: a retry job waits behind Resume", async () => {
    failId = 2;
    const perm = { r: "denied" as PermissionState };
    const requestPermission = vi.fn(async () => perm.r);
    const written: string[] = [];
    picker.mockResolvedValueOnce(Object.assign(rec(written, ""), { requestPermission }));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    failId = null;
    act(() => result.current.retryFailed());
    expect(requestPermission).toHaveBeenCalledTimes(1);   // synchronously, inside the tap
    await waitFor(() => expect(result.current.state.paused).toBe(true));
    expect(result.current.state.jobs.map((j) => j.label)).toEqual(["2 selected · retry 1"]);
    expect(canRetry(result.current.state)).toBe(false);
    perm.r = "granted";
    act(() => result.current.resume());
    await waitFor(() => expect(result.current.state).toMatchObject({ phase: "done", jobs: [], paused: false,
                                                                     label: "2 selected · retry 1" }));
    expect(summarize(result.current.state)).toMatchObject({ total: 1, done: 1 });
    expect(written).toContain("Amy/Unfiled/2.jpg");
  });

  it("Clear queue drops the waiting jobs; Cancel current ends only the run", async () => {
    const { slow } = slowA();
    picker.mockResolvedValueOnce(rec([], ""));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    await act(async () => { await result.current.start(selB); });
    act(() => result.current.clearQueue());
    expect(result.current.state.jobs).toEqual([]);
    act(() => result.current.cancel());
    expect(result.current.state.phase).toBe("cancelled");
    await act(async () => slow.resolve(ok3()));
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.state).toMatchObject({ phase: "cancelled", creator: "Amy" });
    expect(fetched.some((u) => u.includes("media_id=9"))).toBe(false);
  });

  it("the provider unmounting (sign-out) aborts the run and drops the queue", async () => {
    const { slow, signals } = slowA();
    picker.mockResolvedValueOnce(rec([], ""));
    const { result, unmount } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    await act(async () => { await result.current.start(selB); });
    unmount();
    expect(signals.length).toBeGreaterThan(0);
    expect(signals.every((s) => s.aborted)).toBe(true);
    slow.resolve(ok3());
    await new Promise((r) => setTimeout(r, 20));
    expect(fetched.some((u) => u.includes("media_id=9"))).toBe(false);
  });

  it("keepAccounts without the run's model (removed mid-run) cancels it and aborts its fetches", async () => {
    const { signals } = slowA();
    picker.mockResolvedValueOnce(rec([], ""));
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    act(() => result.current.keepAccounts(["acc-a", "acc-b"]));
    expect(result.current.state.phase).toBe("running");
    act(() => result.current.keepAccounts(["acc-b"]));
    expect(result.current.state.phase).toBe("cancelled");
    expect(signals.every((s) => s.aborted)).toBe(true);
  });
});

describe("Open folder: the computer's file window in the run's folder", () => {
  const openPicker = vi.fn();
  beforeEach(() => {
    openPicker.mockReset();
    (window as unknown as { showOpenFilePicker: unknown }).showOpenFilePicker = openPicker;
  });
  const startIn = () => (openPicker.mock.calls[0][0] as { startIn: { path: string } }).startIn.path;

  it.each([
    ["a selection: the creator's folder", runA, ["Amy"], "root/Amy"],
    ["a folder download: that folder", { ...runA, mode: "folder" as const, label: "folder Beach / x", folder: { id: 7, name: "Beach / x" } },
     ["Amy", "Beach _ x"], "root/Amy/Beach _ x"],
  ])("%s", async (_, run, dirs, path) => {
    picker.mockResolvedValueOnce(dir());
    failId = null;
    const { result } = renderHook(() => useVaultDownload());
    expect(result.current.state.savedAt).toBeNull();
    act(() => { void result.current.start(run); });
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(result.current.state.savedAt?.dirs).toEqual(dirs);
    expect(result.current.state.savedAt?.root.name).toBe("root");
    openPicker.mockRejectedValueOnce(closed());   // the user closes the window: not an error
    act(() => result.current.openFolder());
    await waitFor(() => expect(openPicker).toHaveBeenCalledTimes(1));
    expect(startIn()).toBe(path);
    expect(openPicker.mock.calls[0][0]).toMatchObject({ multiple: true });
    await act(async () => {});
    expect(result.current.state.note).toBe("");
  });

  it("mid-run, before any file (still listing): opens the creator's folder, made for it", async () => {
    picker.mockResolvedValueOnce(dir());
    get.mockImplementation((u: string) => (u.startsWith("/admin/vault-ai/download/info")
      ? Promise.resolve({ direct: false }) : new Promise(() => {})));   // the listing never answers
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runB); });
    await waitFor(() => expect(result.current.state.phase).toBe("listing"));
    expect(result.current.state.savedAt?.dirs).toEqual(["Bea"]);
    act(() => result.current.openFolder());
    await waitFor(() => expect(openPicker).toHaveBeenCalledTimes(1));
    expect(startIn()).toBe("root/Bea");
  });

  it("a browser without the open dialog says so", async () => {
    delete (window as unknown as { showOpenFilePicker?: unknown }).showOpenFilePicker;
    picker.mockResolvedValueOnce(dir());
    failId = null;
    const { result } = renderHook(() => useVaultDownload());
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    act(() => result.current.openFolder());
    await waitFor(() => expect(result.current.state.note).toBe("This browser can't open a folder"));
  });

  it("the share sink has no folder", async () => {
    delete (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker;
    vi.stubGlobal("navigator", { ...navigator, canShare: () => true, share: vi.fn() });
    const { result } = renderHook(() => useVaultDownload());
    expect(result.current.sink).toBe("share");
    act(() => { void result.current.start(runA); });
    await waitFor(() => expect(result.current.state.phase).not.toBe("idle"));
    expect(result.current.state.savedAt).toBeNull();
  });
});
