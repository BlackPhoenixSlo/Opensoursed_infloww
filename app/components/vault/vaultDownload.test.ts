// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/lib/shareToken", () => ({ resolveShareToken: () => "tok" }));

import { relay, type VaultMedia } from "@/lib/relay";

import { folderSink, listAll, LIVE_PAGE_GAP_MS, runQueue, shareFiles, shareSink, startDownload } from "./vaultDownload";
import {
  SHARE_BATCH_BYTES, initialDownloadState, readyBatch, toItems, vaultDownloadReducer, type Action, type DlSink,
  type DlState,
} from "./vaultDownloadReducer";

const get = relay.get as unknown as ReturnType<typeof vi.fn>;

// ── a fake directory tree: files[path] = bytes written (only on a clean close) ──
type Files = Record<string, number>;
function dir(files: Files, path: string): FileSystemDirectoryHandle {
  return {
    getDirectoryHandle: async (n: string) => dir(files, `${path}${n}/`),
    getFileHandle: async (n: string) => ({
      getFile: async () => new File([new Uint8Array(files[`${path}${n}`] ?? 0)], n),
      createWritable: async () => {
        let n2 = 0;
        return new WritableStream<Uint8Array>({
          write: (c) => { n2 += c.byteLength; },
          close: () => { files[`${path}${n}`] = n2; },
        });
      },
    }),
  } as unknown as FileSystemDirectoryHandle;
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
  send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", directAllowed, sink });
  send({ type: "listed", items: toItems(ms, null) });
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");   // what real fetch does
    calls.push(u);
    return fetchImpl(u);
  }));
  const files: Files = {};
  const kept = new Map<number, File>();
  const ac = abort ?? new AbortController();
  await runQueue({ send, get: () => s, signal: ac.signal,
                   sink: sink === "share" ? shareSink((id, f) => kept.set(id, f))
                     : folderSink(dir(files, ""), "amy") });
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

  it("DRM-only video (no url) goes straight to the relay; 422 is a failed item with a reason", async () => {
    const { s, calls } = await go([media(7, "video", null)], true,
      async () => new Response("{}", { status: 422 }));
    expect(calls).toHaveLength(1);
    expect(s.items[0]).toMatchObject({ status: "failed", error: "no downloadable file (DRM-protected video)" });
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
    const { s, calls, files, seen } = await go(ms, false, async () => {
      n += 1;
      if (n === 4) ac.abort();
      return body(1);
    }, ac);
    expect(calls.length).toBe(4);
    // after the abort the runner sends nothing (it may be another run's state by then): the `cancel` action that
    // goes with the abort fails what is open
    expect(seen.filter((a) => "id" in a && a.id === 4).map((a) => a.type)).toEqual(["itemStart"]);
    expect(vaultDownloadReducer(s, { type: "cancel" }).items.find((i) => i.id === 4))
      .toMatchObject({ status: "failed", error: "cancelled" });
    expect(s.items.filter((i) => i.status === "queued").length).toBeGreaterThanOrEqual(14);
    expect(Object.keys(files).length).toBeLessThanOrEqual(3);
  });
});

describe("startDownload", () => {
  it("a start the reducer refuses (another run holds the state) runs nothing and keeps that run's sink", async () => {
    get.mockResolvedValue({ direct: true });
    let s = vaultDownloadReducer(initialDownloadState,
      { type: "start", mode: "vault", label: "whole vault", accountId: "acc-a", creator: "amy", directAllowed: true });
    s = vaultDownloadReducer(s, { type: "listed", items: toItems([media(1), media(2)], null) });
    const held = s;
    const fetchSpy = vi.fn(async () => body(1));
    vi.stubGlobal("fetch", fetchSpy);
    const setSink = vi.fn();
    const ok = await startDownload(
      { accountId: "acc-b", mode: "selection", label: "1 selected", creator: "bea", media: [media(9)], source: "mirror" },
      { send: (a) => { s = vaultDownloadReducer(s, a); }, get: () => s, signal: new AbortController().signal },
      setSink, () => {});
    expect(ok).toBe(false);
    expect(s).toBe(held);                 // A's run untouched, still A's
    expect(fetchSpy).not.toHaveBeenCalled();   // no second queue over A's items
    expect(setSink).not.toHaveBeenCalled();
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
});

describe("share sink (phones)", () => {
  const typed = (id: number, ext: string) => media(id, ext === "mp4" ? "video" : "photo",
    `https://cdn2.onlyfans.com/files/a/${id}.${ext}?Signature=old`);
  const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

  it("keeps nothing when the run is aborted by the time the body is read", async () => {
    const kept: number[] = [];
    const ac = new AbortController();
    ac.abort();
    const it1 = { id: 7, kind: "photo", url: null, folder: "f", name: "7.jpg", status: "active" as const,
                  source: null, bytes: 0, error: null };
    await expect(shareSink((id) => kept.push(id))(it1, body(5).body!, ac.signal)).rejects.toThrow();
    expect(kept).toEqual([]);
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
    expect(s.items.map((i) => i.status)).toEqual(["failed", "failed"]);
    expect(s.batches).toEqual([]);
  });

  it("holds fetching while ~2 batches are unsaved, resumes after each save", async () => {
    let s: DlState = initialDownloadState;
    // every file reported as a whole batch's bytes: each is a batch of its own
    const send = (a: Action) => {
      s = vaultDownloadReducer(s, a.type === "itemDone" ? { ...a, bytes: SHARE_BATCH_BYTES } : a);
    };
    send({ type: "start", mode: "selection", label: "x", accountId: "acc", creator: "amy", directAllowed: false, sink: "share" });
    send({ type: "listed", items: toItems([1, 2, 3, 4, 5, 6].map((i) => media(i)), null) });
    const fetched: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string) => { fetched.push(u); return body(4); }));
    const run = runQueue({ send, get: () => s, signal: new AbortController().signal,
                           sink: shareSink(() => {}) });
    await tick(50);
    const held = fetched.length;
    expect(held).toBeLessThan(6);
    await tick(600);
    expect(fetched.length).toBe(held);   // nothing more until a save
    while (s.phase !== "done" || readyBatch(s) >= 0) {
      if (readyBatch(s) >= 0) send({ type: "batchSaved", index: readyBatch(s) });
      await tick(300);
    }
    await run;
    expect(fetched.length).toBe(6);
    expect(s.items.every((i) => i.status === "done")).toBe(true);
    expect(s.batches.map((b) => b.ids.length)).toEqual([1, 1, 1, 1, 1, 1]);
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
  it("whole vault: an item in 2 custom folders is written once per folder, fetched once", async () => {
    const m = { ...media(1), listStates: [{ type: "custom", name: "A" }, { type: "custom", name: "B" }] } as unknown as VaultMedia;
    const { files, calls } = await go([m], true, async () => body(10));
    expect(calls).toHaveLength(1);
    expect(files).toEqual({ "amy/A/1.jpg": 10, "amy/B/1.jpg": 10 });
  });
});

