// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/lib/shareToken", () => ({ resolveShareToken: () => "tok" }));

import { relay, type VaultMedia } from "@/lib/relay";

import {
  HEAD_MS, RELAY_BUSY, STALL_MS, abortableSleep, folderSink, listAll, LIVE_PAGE_GAP_MS, runQueue, shareFiles, shareSink,
  startDownload, writeLinks,
} from "./vaultDownload";
import {
  CANCELLED, LIST_MAX_PAGES, SHARE_BATCH_BYTES, SHARE_FILE_MAX_BYTES, SHARE_TOO_BIG, canRetry, initialDownloadState, readyBatch, toItems,
  vaultDownloadReducer, type Action, type DlSink, type DlState,
} from "./vaultDownloadReducer";

const get = relay.get as unknown as ReturnType<typeof vi.fn>;

// ── a fake directory tree, Chrome's rules: getFileHandle(create) makes the file (0 bytes) at once, without create a
// missing one throws; files[path] = bytes, written only on a clean close (an abort keeps what was there) ──
type Files = Record<string, number>;
/** `write(path)`: runs before each chunk written to that file (a slow / failing disk). */
type DirOpts = { write?: (path: string) => Promise<void> };
function dir(files: Files, path: string, o: DirOpts = {}): FileSystemDirectoryHandle {
  return {
    getDirectoryHandle: async (n: string) => dir(files, `${path}${n}/`, o),
    removeEntry: async (n: string) => { delete files[`${path}${n}`]; },
    getFileHandle: async (n: string, f?: { create?: boolean }) => {
      if (!(`${path}${n}` in files)) {
        if (!f?.create) throw new DOMException("missing", "NotFoundError");
        files[`${path}${n}`] = 0;
      }
      return fileHandle(files, path, n, o);
    },
  } as unknown as FileSystemDirectoryHandle;
}
function fileHandle(files: Files, path: string, n: string, o: DirOpts = {}) {
  return {
    // read back in 64 KiB chunks, as Chrome's File.stream() does (node's gives one)
    getFile: async () => Object.assign(new File([new Uint8Array(files[`${path}${n}`] ?? 0)], n), {
      stream: () => {
        let left = files[`${path}${n}`] ?? 0;
        return new ReadableStream<Uint8Array>({ pull(c) {
          if (left <= 0) return c.close();
          const k = Math.min(left, 1 << 16);
          left -= k;
          c.enqueue(new Uint8Array(k));
        } });
      },
    }),
    createWritable: async () => {
      let n2 = 0;
      return new WritableStream<Uint8Array>({
        write: async (c) => { await o.write?.(`${path}${n}`); n2 += c.byteLength; },
        close: () => { files[`${path}${n}`] = n2; },
      });
    },
  };
}

const body = (n: number, declared = n) =>
  new Response(new Uint8Array(n), { status: 200, headers: { "content-length": String(declared) } });
const cdn = (id: number, sig = "old") => `https://cdn2.onlyfans.com/files/a/${id}.jpg?Signature=${sig}`;
const media = (id: number, type = "photo", url: string | null = cdn(id)) =>
  ({ id, type, files: { full: { url } }, listStates: [] }) as unknown as VaultMedia;

async function go(ms: VaultMedia[], directAllowed: boolean, fetchImpl: (u: string) => Promise<Response>,
  abort?: AbortController, sink: DlSink = "folder") {
  let s: DlState = initialDownloadState;
  const seen: Action[] = [];
  const send = (a: Action) => { seen.push(a); s = vaultDownloadReducer(s, a); };
  send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", sink });
  send({ type: "direct", allowed: directAllowed, attempt: 1 });
  send({ type: "listed", items: toItems(ms, null), attempt: 1 });
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");   // what real fetch does
    calls.push(u);
    return fetchImpl(u);
  }));
  const files: Files = {};
  const kept = new Map<number, File>();
  const ac = abort ?? new AbortController();
  await runQueue({ send, get: () => s, signal: ac.signal, keep: (id, f) => kept.set(id, f),
                   sink: sink === "share" ? shareSink() : folderSink(dir(files, ""), "amy") });
  return { s, files, calls, seen, kept };
}

beforeEach(() => {
  get.mockReset();
  vi.unstubAllGlobals();
});

describe("source chain", () => {
  it("direct ok: one CDN fetch, no relay, file written under creator/folder", async () => {
    const { s, files, calls } = await go([media(1)], true, async () => body(10));
    expect(calls).toEqual([cdn(1)]);
    expect(files).toEqual({ "amy/Unfiled/1.jpg": 10 });
    expect(s.items[0]).toMatchObject({ status: "done", source: "direct", bytes: 10 });
    expect(s.phase).toBe("done");
  });

  it("direct fails, re-sign, direct again ok", async () => {
    get.mockResolvedValue({ url: cdn(1, "new") });
    const { s, calls } = await go([media(1)], true, async (u) => {
      if (u.includes("old")) throw new TypeError("Failed to fetch");
      return body(4);
    });
    expect(calls).toEqual([cdn(1), cdn(1, "new")]);
    expect(get.mock.calls[0][0]).toContain("/admin/vault-ai/download/resign?account_id=acc&media_id=1");
    expect(s.items[0]).toMatchObject({ status: "done", source: "direct" });
    expect(s.directStrikes).toBe(0);
  });

  it("direct fails twice: a strike, then the relay with u and the share token", async () => {
    get.mockResolvedValue({ url: cdn(1, "new") });
    const { s, calls } = await go([media(1)], true, async (u) => {
      if (u.startsWith("https://")) return new Response("no", { status: 403 });
      return body(6);
    });
    expect(calls).toHaveLength(3);
    const relayUrl = new URL(calls[2], "http://x");
    expect(relayUrl.pathname).toBe("/admin/vault-ai/download");
    expect(Object.fromEntries(relayUrl.searchParams)).toEqual({ account_id: "acc", media_id: "1", u: cdn(1), t: "tok" });
    expect(s.directStrikes).toBe(1);
    expect(s.items[0]).toMatchObject({ status: "done", source: "relay", bytes: 6 });
  });

  it("after MAX strikes direct is off for the rest of the run", async () => {
    get.mockResolvedValue({ url: null });
    const ms = [1, 2, 3, 4, 5, 6].map((i) => media(i));
    const { s, calls } = await go(ms, true, async (u) => {
      if (u.startsWith("https://")) throw new TypeError("Failed to fetch");
      return body(1);
    });
    expect(s.items.every((i) => i.status === "done" && i.source === "relay")).toBe(true);
    // 3 workers start direct before any strike lands; nothing after the 2nd strike goes direct
    expect(calls.filter((u) => u.startsWith("https://")).length).toBeLessThanOrEqual(3);
    expect(s.directStrikes).toBeGreaterThanOrEqual(2);
  });

  it("proxied account: relay only, the browser never touches the CDN", async () => {
    const { s, calls } = await go([media(1), media(2, "video")], false, async () => body(3));
    expect(calls.every((u) => u.startsWith("/admin/vault-ai/download?"))).toBe(true);
    expect(get).not.toHaveBeenCalled();
    expect(summarize2(s)).toEqual(["relay", "relay"]);
  });

  // #1/#18: the relay's slot wait ran out (503 download_busy): a failed item Retry takes again.
  it("relay busy (503): a failed item that Retry requeues", async () => {
    const { s, calls } = await go([media(1)], false, async () => new Response("{}", { status: 503 }));
    expect(calls).toHaveLength(1);
    expect(s.items[0]).toMatchObject({ status: "failed", error: RELAY_BUSY });
    expect(canRetry(s)).toBe(true);
    expect(vaultDownloadReducer(s, { type: "retryFailed" }).items[0].status).toBe("queued");
  });

  it("DRM-only video (no url) goes straight to the relay; 422 is a drm item (not failed) with a reason", async () => {
    const { s, calls } = await go([media(7, "video", null)], true,
      async () => new Response("{}", { status: 422 }));
    expect(calls).toHaveLength(1);
    expect(s.items[0]).toMatchObject({ status: "drm", error: "no downloadable file (DRM-protected video)" });
  });
});

const summarize2 = (s: DlState) => s.items.map((i) => i.source);

describe("integrity", () => {
  it("a short body fails the item and leaves no file", async () => {
    const { s, files } = await go([media(1)], false, async () => body(5, 9));
    expect(s.items[0]).toMatchObject({ status: "failed" });
    expect(s.items[0].error).toContain("short body");
    expect(files).toEqual({});
  });

  it("relay 502 is a failed item; retry-failed then succeeds", async () => {
    let fail = true;
    const r = await go([media(1), media(2)], false, async (u) => (fail && u.includes("media_id=2")
      ? new Response("", { status: 502 }) : body(2)));
    expect(r.s.items.map((i) => i.status)).toEqual(["done", "failed"]);
    fail = false;
    let s = vaultDownloadReducer(r.s, { type: "retryFailed" });
    const files: Files = {};
    await runQueue({ sink: folderSink(dir(files, ""), "amy"),
                     send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s, signal: new AbortController().signal });
    expect(s.items.map((i) => i.status)).toEqual(["done", "done"]);
    expect(Object.keys(files)).toEqual(["amy/Unfiled/2.jpg"]);
  });

  it("cancel stops the queue: nothing after the abort is fetched", async () => {
    const ac = new AbortController();
    let n = 0;
    const ms = Array.from({ length: 20 }, (_, i) => media(i + 1));
    const { s, calls, files } = await go(ms, false, async () => {
      n += 1;
      if (n === 4) ac.abort();
      return body(1);
    }, ac);
    expect(calls.length).toBe(4);
    expect(s.items.find((i) => i.id === 4)).toMatchObject({ status: "failed", error: "cancelled" });
    expect(s.items.filter((i) => i.status === "queued").length).toBeGreaterThanOrEqual(14);
    expect(Object.keys(files).length).toBeLessThanOrEqual(3);
  });
});

describe("item signal", () => {
  it("a re-sign that never answers is cut at HEAD_MS: stalled, no strike counted", async () => {
    vi.useFakeTimers();
    try {
      get.mockImplementation((_p: string, _c: unknown, signal?: AbortSignal) => new Promise((_, no) => {
        signal?.addEventListener("abort", () => no(signal.reason));
      }));
      const p = go([media(1)], true, async (u) => (u.startsWith("https://") ? new Response("", { status: 403 }) : body(4)));
      await vi.advanceTimersByTimeAsync(HEAD_MS + 100);
      const { s, seen } = await p;
      expect(s.items[0].status).toBe("stalled");
      expect(seen.some((a) => a.type === "directStrike")).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("attempts + links (#5, #9)", () => {
  it("a worker of an attempt that was cancelled and retried fetches nothing and changes nothing", async () => {
    let s: DlState = initialDownloadState;
    const send = (a: Action) => { s = vaultDownloadReducer(s, a); };
    send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy" });
    send({ type: "listed", items: toItems([media(1), media(2)], null), attempt: 1 });
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => { fetched.push(u); return body(1); }));
    const old = runQueue({ send, get: () => s, signal: new AbortController().signal,
                           sink: folderSink(dir({}, ""), "amy") });
    // Before the old workers' first item: Cancel, then Retry failed (attempt 2) — its own queue is not run here.
    send({ type: "cancel" });
    send({ type: "retryFailed" });
    await old;
    expect(fetched).toEqual([]);
    expect(s.items.map((i) => i.status)).toEqual(["queued", "queued"]);
  });

  // #428: the page's one download; B's start while A's run holds the state takes nothing over.
  it("a start the reducer refuses (another run holds the state) runs nothing and reports no sink", async () => {
    get.mockResolvedValue({ direct: true });
    let s = vaultDownloadReducer(initialDownloadState,
      { type: "start", mode: "vault", label: "whole vault", accountId: "acc-a", creator: "amy" });
    s = vaultDownloadReducer(s, { type: "listed", items: toItems([media(1), media(2)], null), attempt: 1 });
    const held = s;
    const fetchSpy = vi.fn(async () => body(1));
    vi.stubGlobal("fetch", fetchSpy);
    const started = vi.fn();
    await startDownload(
      { accountId: "acc-b", mode: "selection", label: "1 selected", creator: "bea", media: [media(9)], source: "mirror" },
      { send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s, signal: new AbortController().signal },
      "share", started);
    expect(s).toBe(held);                      // A's run untouched, still A's
    expect(fetchSpy).not.toHaveBeenCalled();   // no second queue over A's items
    expect(started).not.toHaveBeenCalled();
  });

  it("writeLinks: false when the folder refuses the file", async () => {
    const refusing = { getDirectoryHandle: async () => { throw new DOMException("no", "NotAllowedError"); } } as unknown as
      FileSystemDirectoryHandle;
    const f = { txtName: "a.txt", htmlName: "a.html", txt: "t", html: "h", validUntil: null, rows: [] };
    await expect(writeLinks(refusing, ["amy"], f)).resolves.toBe(false);
    const files: Files = {};
    await expect(writeLinks(dir(files, ""), ["amy"], f)).resolves.toBe(true);
    expect(files).toEqual({ "amy/a.txt": 1, "amy/a.html": 1 });
  });

  it("a queued job: no picker (the queue's folder), its own creator's path; gone from the queue: nothing runs", async () => {
    get.mockResolvedValue({ direct: false });
    vi.stubGlobal("fetch", vi.fn(async () => body(3)));
    vi.stubGlobal("window", { showDirectoryPicker: vi.fn(), location: { origin: "http://x" } });
    let s = vaultDownloadReducer(initialDownloadState,
      { type: "start", mode: "vault", label: "whole vault", accountId: "acc-a", creator: "amy" });
    s = vaultDownloadReducer(s, { type: "listed", items: [], attempt: 1 });
    s = vaultDownloadReducer(s, { type: "start", mode: "vault", label: "whole vault", accountId: "acc-a", creator: "amy" });
    s = vaultDownloadReducer(s, { type: "enqueue", job: { accountId: "acc-b", creator: "bea", mode: "selection",
                                                         label: "1 selected", media: [media(9)], source: "mirror" } });
    s = vaultDownloadReducer(s, { type: "listed", items: [], attempt: 2 });   // amy's run done (empty); bea's job waits
    const files: Files = {};
    const root = dir(files, "");
    const run = { send: (a: Action) => { s = vaultDownloadReducer(s, a); }, get: () => s,
                  signal: new AbortController().signal };
    const job = s.jobs[0];
    const started = vi.fn();
    await startDownload(job, run, "folder", started, root);
    expect((window as unknown as { showDirectoryPicker: ReturnType<typeof vi.fn> }).showDirectoryPicker).not.toHaveBeenCalled();
    expect(started).toHaveBeenCalledWith(expect.any(Function), 3, root);
    expect(s).toMatchObject({ phase: "done", creator: "bea", jobs: [] });
    expect(files["bea/Unfiled/9.jpg"]).toBe(3);
    // the same qid again (no longer queued): refused before anything runs
    const again = vi.fn();
    await startDownload(job, run, "folder", again, root);
    expect(again).not.toHaveBeenCalled();
  });
});

describe("stall watchdog", () => {
  const stuck = () => new Response(new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new Uint8Array(3)); } }),
    { status: 200, headers: { "content-length": "9" } });

  it("no bytes for STALL_MS: the item ends stalled, its empty file removed, the worker goes on", async () => {
    vi.useFakeTimers();
    try {
      const p = go([media(1), media(2)], false, async (u) => (u.includes("media_id=1") ? stuck() : body(4)));
      await vi.advanceTimersByTimeAsync(STALL_MS + 100);
      const { s, files } = await p;
      expect(s.items.map((i) => i.status)).toEqual(["stalled", "done"]);
      expect(s.items[0].error).toBe(`stalled: no data for ${STALL_MS / 1000} s`);
      expect(files).toEqual({ "amy/Unfiled/2.jpg": 4 });   // no partial / empty 1.jpg a retry could mistake
    } finally {
      vi.useRealTimers();
    }
  });

  it("a slow but steady body (a chunk just under STALL_MS apart) is not a stall", async () => {
    vi.useFakeTimers();
    try {
      const slow = () => new Response(new ReadableStream<Uint8Array>({
        async pull(c) {
          await new Promise((r) => setTimeout(r, STALL_MS - 1000));
          c.enqueue(new Uint8Array(3));
          if (++sent === 3) c.close();
        },
      }), { status: 200, headers: { "content-length": "9" } });
      let sent = 0;
      const p = go([media(1)], false, async () => slow());
      await vi.advanceTimersByTimeAsync(4 * STALL_MS);
      const { s, files } = await p;
      expect(s.items[0]).toMatchObject({ status: "done", bytes: 9 });
      expect(files).toEqual({ "amy/Unfiled/1.jpg": 9 });
    } finally {
      vi.useRealTimers();
    }
  });

  it("no response headers for HEAD_MS: stalled", async () => {
    vi.useFakeTimers();
    try {
      let s = vaultDownloadReducer(initialDownloadState,
        { type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy" });
      s = vaultDownloadReducer(s, { type: "listed", items: toItems([media(1)], null), attempt: 1 });
      vi.stubGlobal("fetch", vi.fn((_u: string, init?: RequestInit) => new Promise((_, no) => {
        init?.signal?.addEventListener("abort", () => no(init.signal!.reason));
      })));
      const p = runQueue({ send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s,
                           signal: new AbortController().signal, sink: folderSink(dir({}, ""), "amy") });
      await vi.advanceTimersByTimeAsync(HEAD_MS + 100);
      await p;
      expect(s.items[0].status).toBe("stalled");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a write that hangs (pipeTo never settles) still ends stalled", async () => {
    vi.useFakeTimers();
    try {
      let s = vaultDownloadReducer(initialDownloadState,
        { type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy" });
      s = vaultDownloadReducer(s, { type: "listed", items: toItems([media(1)], null), attempt: 1 });
      vi.stubGlobal("fetch", vi.fn(async () => stuck()));
      const p = runQueue({ send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s,
                           signal: new AbortController().signal, sink: () => new Promise<File | null>(() => {}) });
      await vi.advanceTimersByTimeAsync(STALL_MS + 100);
      await p;
      expect(s.items[0].status).toBe("stalled");
    } finally {
      vi.useRealTimers();
    }
  });

  it("the run's cancel still wins: no stalled after an abort", async () => {
    vi.useFakeTimers();
    try {
      const ac = new AbortController();
      const p = go([media(1)], false, async () => stuck(), ac);
      await vi.advanceTimersByTimeAsync(1000);
      ac.abort();
      await vi.advanceTimersByTimeAsync(STALL_MS + 100);
      const { seen } = await p;
      // the run's abort is CANCELLED, never `stalled` (the panel's `cancel` / `stop` then mark open items cancelled)
      expect(seen.filter((a) => a.type === "itemFailed").map((a) => a.type === "itemFailed" && [a.reason, a.error]))
        .toEqual([["failed", CANCELLED]]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("listAll", () => {
  it("pages the mirror by 500 until hasMore is false, no pacing", async () => {
    get.mockResolvedValueOnce({ list: [media(1), media(2)], hasMore: true })
       .mockResolvedValueOnce({ list: [media(3)], hasMore: false });
    const sleep = vi.fn(async () => {});
    const out = await listAll("acc", 12, "mirror", new AbortController().signal, sleep);
    expect(out.map((m) => m.id)).toEqual([1, 2, 3]);
    expect(get.mock.calls.map((c) => c[0])).toEqual([
      "/admin/vault-ai/items?account_id=acc&limit=500&offset=0&of_folder_id=12",
      "/admin/vault-ai/items?account_id=acc&limit=500&offset=2&of_folder_id=12",
    ]);
    expect(sleep).not.toHaveBeenCalled();
  });
  it("pages live OF by 100 with a gap between pages", async () => {
    get.mockResolvedValueOnce({ list: [media(1)], hasMore: true })
       .mockResolvedValueOnce({ list: [media(2)], hasMore: true })
       .mockResolvedValueOnce({ list: [], hasMore: true });
    const sleep = vi.fn(async () => {});
    const out = await listAll("acc", null, "live", new AbortController().signal, sleep);
    expect(out.map((m) => m.id)).toEqual([1, 2]);
    expect(get.mock.calls[0][0]).toBe("/api/of/v2/vault/media?limit=100&offset=0");
    expect(get.mock.calls[0][1]).toEqual({ accountId: "acc" });
    expect(sleep.mock.calls).toEqual([[LIVE_PAGE_GAP_MS], [LIVE_PAGE_GAP_MS]]);
  });
  // #8: a stuck cursor or an endless hasMore is "listing incomplete", never a partial list read as the whole.
  it("the same page again while hasMore: listing incomplete", async () => {
    get.mockResolvedValue({ list: [media(1), media(2)], hasMore: true });
    await expect(listAll("acc", 12, "mirror", new AbortController().signal, async () => {}))
      .rejects.toThrow(/listing incomplete/);
    expect(get).toHaveBeenCalledTimes(2);
  });
  it("more than LIST_MAX_PAGES pages: listing incomplete", async () => {
    let n = 0;
    get.mockImplementation(async () => ({ list: [media((n += 1))], hasMore: true }));
    await expect(listAll("acc", 12, "mirror", new AbortController().signal, async () => {}))
      .rejects.toThrow(/listing incomplete/);
    expect(get).toHaveBeenCalledTimes(LIST_MAX_PAGES);
  });
  // #31: a Cancel during the live page gap rejects at once, not after the gap.
  it("abortableSleep: resolves after ms, rejects at once on abort", async () => {
    await expect(abortableSleep(1, new AbortController().signal)).resolves.toBeUndefined();
    const gone = new AbortController();
    gone.abort();
    await expect(abortableSleep(60_000, gone.signal)).rejects.toMatchObject({ name: "AbortError" });
    const ac = new AbortController();
    const p = abortableSleep(60_000, ac.signal);
    ac.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });
  it("live listing: a Cancel in the page gap ends it without waiting the gap out", async () => {
    get.mockResolvedValue({ list: [media(1)], hasMore: true });
    const ac = new AbortController();
    const t0 = Date.now();
    const p = listAll("acc", null, "live", ac.signal);   // the default sleep
    await new Promise((r) => setTimeout(r, 5));
    ac.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
    expect(Date.now() - t0).toBeLessThan(LIVE_PAGE_GAP_MS);
    expect(get).toHaveBeenCalledTimes(1);
  });
});

describe("startDownload (#28, #33, #34)", () => {
  const harness = () => {
    let s: DlState = initialDownloadState;
    const send = (a: Action) => { s = vaultDownloadReducer(s, a); };
    return { send, get: () => s, signal: new AbortController().signal, keep: () => {} };
  };
  const args = (media?: VaultMedia[]) =>
    ({ accountId: "acc", mode: "folder" as const, label: "folder A", creator: "amy", media, source: "mirror" as const });

  it("phone double tap: the second start is refused before any await; each item fetched once", async () => {
    get.mockResolvedValue({ direct: false });
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => { fetched.push(u); return body(1); }));
    const d = harness();
    const started: number[] = [];
    const a = startDownload(args([media(1), media(2)]), d, "share", (_k, n) => started.push(n));
    const b = startDownload(args([media(1), media(2)]), d, "share", (_k, n) => started.push(n));
    await Promise.all([a, b]);
    expect(started).toEqual([1]);
    expect(fetched).toHaveLength(2);
    expect(d.get().items.map((i) => i.status)).toEqual(["done", "done"]);
  });
  it("two queues of one attempt (Retry over a winding-down run) fetch each item once", async () => {
    const d = harness();
    d.send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", sink: "share" });
    d.send({ type: "listed", items: toItems([media(1), media(2), media(3)], null), attempt: 1 });
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => { fetched.push(u); return body(1); }));
    await Promise.all([runQueue({ ...d, sink: shareSink() }), runQueue({ ...d, sink: shareSink() })]);
    expect(fetched).toHaveLength(3);
  });
  it("a listing error throws to the caller after start, with the attempt it started", async () => {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/vault-ai/download/info")) return { direct: false };
      throw new Error("relay 500");
    });
    const d = harness();
    let attempt = 0;
    await expect(startDownload(args(), d, "share", (_k, n) => { attempt = n; })).rejects.toThrow("relay 500");
    expect([attempt, d.get().phase]).toEqual([1, "listing"]);
  });
});

describe("share sink (phones)", () => {
  const typed = (id: number, ext: string) => media(id, ext === "mp4" ? "video" : "photo",
    `https://cdn2.onlyfans.com/files/a/${id}.${ext}?Signature=old`);
  const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

  it("keeps nothing when the run is aborted by the time the body is read", async () => {
    const ac = new AbortController();
    ac.abort();
    const it1 = { id: 7, kind: "photo", url: null, folder: "f", name: "7.jpg", status: "active" as const,
                  source: null, bytes: 0, error: null };
    await expect(shareSink()(it1, body(5).body!, ac.signal)).rejects.toThrow();
  });

  it("same source chain, each file kept as <id>.<ext> with its MIME, one batch at the end", async () => {
    const { s, kept, files } = await go([typed(1, "jpg"), typed(2, "png"), typed(3, "mp4"), typed(4, "gif")], true,
      async () => body(5), undefined, "share");
    expect(files).toEqual({});
    expect([...kept.values()].map((f) => [f.name, f.type, f.size]).sort()).toEqual([
      ["1.jpg", "image/jpeg", 5], ["2.png", "image/png", 5], ["3.mp4", "video/mp4", 5], ["4.gif", "image/gif", 5]]);
    expect(s.items.every((i) => i.status === "done" && i.source === "direct")).toBe(true);
    expect(s.batches).toHaveLength(1);
    expect(s.batches[0]).toMatchObject({ bytes: 20, sealed: true, saved: false });
    expect(s.batches[0].ids.slice().sort()).toEqual([1, 2, 3, 4]);
  });

  it("DRM 422 fails and joins no batch; a short body keeps no file", async () => {
    const { s, kept } = await go([media(7, "video", null), media(8)], false,
      async (u) => (u.includes("media_id=7") ? new Response("{}", { status: 422 }) : body(3, 9)), undefined, "share");
    expect(kept.size).toBe(0);
    expect(s.items.map((i) => i.status)).toEqual(["drm", "failed"]);
    expect(s.batches).toEqual([]);
  });

  it("holds fetching while ~2 batches are unsaved, resumes after each save", async () => {
    let s: DlState = initialDownloadState;
    // every file reported as a whole batch's bytes: each is a batch of its own
    const send = (a: Action) => {
      s = vaultDownloadReducer(s, a.type === "itemDone" ? { ...a, bytes: SHARE_BATCH_BYTES } : a);
    };
    send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", sink: "share" });
    send({ type: "listed", items: toItems([1, 2, 3, 4, 5, 6].map((i) => media(i)), null), attempt: 1 });
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => { fetched.push(u); return body(4); }));
    const run = runQueue({ send, get: () => s, signal: new AbortController().signal,
                           sink: shareSink() });
    await tick(50);
    const held = fetched.length;
    expect(held).toBeLessThan(6);
    await tick(600);
    expect(fetched.length).toBe(held);   // nothing more until a save
    while (s.phase !== "done" || readyBatch(s) >= 0) {
      if (readyBatch(s) >= 0) send({ type: "batchSaved", index: readyBatch(s), attempt: s.attempt });
      await tick(300);
    }
    await run;
    expect(fetched.length).toBe(6);
    expect(s.items.every((i) => i.status === "done")).toBe(true);
    expect(s.batches.map((b) => b.ids.length)).toEqual([1, 1, 1, 1, 1, 1]);
  });

  // #7: a file the phone would have to hold whole is refused, by its Content-Length or by the counted bytes.
  it.each<[string, () => Response]>([
    ["declared too big", () => new Response(new Uint8Array(4), { status: 200,
      headers: { "content-length": String(SHARE_FILE_MAX_BYTES + 1) } })],
    ["no length, too many bytes", () => {
      const mb = new Uint8Array(1 << 20);
      let sent = 0;
      return new Response(new ReadableStream<Uint8Array>({
        pull(c) {
          if (sent > SHARE_FILE_MAX_BYTES) c.close();
          else { sent += mb.byteLength; c.enqueue(mb); }
        },
      }), { status: 200 });
    }],
  ])("too big for a phone: %s → failed, nothing kept", async (_n, res) => {
    const { s, kept } = await go([typed(1, "mp4")], false, async () => res(), undefined, "share");
    expect(s.items[0]).toMatchObject({ status: "failed", error: SHARE_TOO_BIG });
    expect(kept.size).toBe(0);
    expect(s.batches).toEqual([]);
  });

  it("a file finished after its item was cancelled is not kept (#6)", async () => {
    let s: DlState = initialDownloadState;
    const send = (a: Action) => { s = vaultDownloadReducer(s, a); };
    send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", sink: "share" });
    send({ type: "listed", items: toItems([media(1)], null), attempt: 1 });
    // The Cancel lands in the reducer while the body is still read; the fetch itself is not aborted.
    vi.stubGlobal("fetch", vi.fn(async () => { send({ type: "cancel" }); return body(3); }));
    const kept = new Map<number, File>();
    await runQueue({ send, get: () => s, signal: new AbortController().signal,
                     keep: (id, f) => kept.set(id, f), sink: shareSink() });
    expect(s.items[0]).toMatchObject({ status: "cancelled", error: null });
    expect(kept.size).toBe(0);
  });

  it("shareFiles: AbortError is dismissed (not a failure), other errors throw", async () => {
    const f = [new File(["x"], "1.jpg", { type: "image/jpeg" })];
    vi.stubGlobal("navigator", { share: vi.fn(async () => undefined) });
    await expect(shareFiles(f)).resolves.toBe("saved");
    vi.stubGlobal("navigator", { share: vi.fn(async () => { throw new DOMException("x", "AbortError"); }) });
    await expect(shareFiles(f)).resolves.toBe("dismissed");
    vi.stubGlobal("navigator", { share: vi.fn(async () => { throw new DOMException("x", "NotAllowedError"); }) });
    await expect(shareFiles(f)).rejects.toThrow();
  });
});

describe("folder sink copies", () => {
  const inTwo = (id: number) =>
    ({ ...media(id), listStates: [{ type: "custom", name: "A" }, { type: "custom", name: "B" }] }) as unknown as VaultMedia;
  async function goDir(ms: VaultMedia[], o: DirOpts, fetchImpl: (u: string) => Promise<Response>) {
    let s = vaultDownloadReducer(initialDownloadState,
      { type: "start", mode: "vault", label: "whole vault", accountId: "acc", creator: "amy" });
    s = vaultDownloadReducer(s, { type: "listed", items: toItems(ms, null), attempt: 1 });
    vi.stubGlobal("fetch", vi.fn(async (u: string) => fetchImpl(u)));
    const files: Files = {};
    await runQueue({ send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s,
                     signal: new AbortController().signal, sink: folderSink(dir(files, "", o), "amy") });
    return { s, files };
  }

  it("a slow copy (each chunk just under STALL_MS, all of it far over) is not a stall", async () => {
    vi.useFakeTimers();
    try {
      const big = 300_000;   // several File.stream() chunks
      const p = goDir([inTwo(1)], { write: async (path) => {
        if (path === "amy/B/1.jpg") await new Promise((r) => setTimeout(r, STALL_MS - 1000));
      } }, async () => body(big));
      await vi.advanceTimersByTimeAsync(20 * STALL_MS);
      const { s, files } = await p;
      expect(s.items[0]).toMatchObject({ status: "done", bytes: big });
      expect(files).toEqual({ "amy/A/1.jpg": big, "amy/B/1.jpg": big });
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed copy fails the item and leaves no file this attempt created (a file there before stays)", async () => {
    const { s, files } = await goDir([inTwo(1)], { write: async (path) => {
      if (path === "amy/B/1.jpg") throw new Error("disk full");
    } }, async () => body(10));
    expect(s.items[0]).toMatchObject({ status: "failed", error: "disk full" });
    expect(files).toEqual({});
  });

  it("whole vault: an item in 2 custom folders is written once per folder, fetched once", async () => {
    const m = { ...media(1), listStates: [{ type: "custom", name: "A" }, { type: "custom", name: "B" }] } as unknown as VaultMedia;
    const { files, calls } = await go([m], true, async () => body(10));
    expect(calls).toHaveLength(1);
    expect(files).toEqual({ "amy/A/1.jpg": 10, "amy/B/1.jpg": 10 });
  });
});

