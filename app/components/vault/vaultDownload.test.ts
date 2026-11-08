// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/lib/shareToken", () => ({ resolveShareToken: () => "tok" }));

import { relay, type VaultMedia } from "@/lib/relay";

import { listAll, LIVE_PAGE_GAP_MS, runQueue } from "./vaultDownload";
import {
  initialDownloadState, toItems, vaultDownloadReducer, type Action, type DlState,
} from "./vaultDownloadReducer";

const get = relay.get as unknown as ReturnType<typeof vi.fn>;

// ── a fake directory tree: files[path] = bytes written (only on a clean close) ──
type Files = Record<string, number>;
function dir(files: Files, path: string): FileSystemDirectoryHandle {
  return {
    getDirectoryHandle: async (n: string) => dir(files, `${path}${n}/`),
    getFileHandle: async (n: string) => ({
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

async function go(ms: VaultMedia[], directAllowed: boolean, fetchImpl: (u: string) => Promise<Response>, abort?: AbortController) {
  let s: DlState = initialDownloadState;
  const seen: Action[] = [];
  const send = (a: Action) => { seen.push(a); s = vaultDownloadReducer(s, a); };
  send({ type: "start", mode: "selection", label: "x", creator: "amy", directAllowed });
  send({ type: "listed", items: toItems(ms, null) });
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");   // what real fetch does
    calls.push(u);
    return fetchImpl(u);
  }));
  const files: Files = {};
  const ac = abort ?? new AbortController();
  await runQueue({ accountId: "acc", root: dir(files, ""), send, get: () => s, signal: ac.signal });
  return { s, files, calls, seen };
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
    await runQueue({ accountId: "acc", root: dir(files, ""), send: (a) => { s = vaultDownloadReducer(s, a); },
                     get: () => s, signal: new AbortController().signal });
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
