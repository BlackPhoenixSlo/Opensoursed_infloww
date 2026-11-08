/**
 * vaultDownload — the download's I/O, no React: list what to save, pick the folder, run the queue. Every outcome
 * goes through `send` (the panel's dispatch); the state and its rules are `vaultDownloadReducer`.
 *
 * Sink: the File System Access API. `showDirectoryPicker` once, then per item `<creator>/<folder>/<id>.<ext>`
 * written by `response.body.pipeTo(fileHandle.createWritable())`: nothing is held in memory, a cancelled or short
 * file is aborted (the browser drops its temp file), never left half-written.
 *
 * Source per item (docs/spec/vault-download.md, measured 2026-11-08): direct (the signed CDN url, S3 answers CORS
 * `*`) while `sourceFor` allows it; a failed direct fetch (CloudFront's 403 carries no CORS header, so it surfaces
 * as a TypeError) re-signs by media id once and retries direct; then the relay stream. A direct item that failed
 * after its re-sign is a `directStrike`.
 */

import { relay, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";

import {
  CANCELLED, CONCURRENCY, sourceFor, toItems,
  type Action, type DlItem, type DlMode, type DlSource, type DlState,
} from "@/components/vault/vaultDownloadReducer";

/** The live OF listing's pacing: one 100-item page, then this long before the next (the mirror needs none). */
export const LIVE_PAGE_GAP_MS = 1500;
const MIRROR_PAGE = 500;
const LIVE_PAGE = 100;

export type Send = (a: Action) => void;

export function downloadSupported(): boolean {
  return typeof window !== "undefined" && typeof (window as { showDirectoryPicker?: unknown }).showDirectoryPicker === "function";
}

/** The folder picker. Null when the user closed it. */
export async function pickRoot(): Promise<FileSystemDirectoryHandle | null> {
  const w = window as unknown as { showDirectoryPicker: (o?: object) => Promise<FileSystemDirectoryHandle> };
  try {
    return await w.showDirectoryPicker({ id: "vault-download", mode: "readwrite" });
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return null;
    throw e;
  }
}

/** May the browser fetch this account's CDN urls itself (no proxy)? A failure reads as no: the relay always works. */
export async function directAllowed(accountId: string): Promise<boolean> {
  try {
    const r = await relay.get<{ direct: boolean }>(
      `/admin/vault-ai/download/info?account_id=${encodeURIComponent(accountId)}`);
    return !!r.direct;
  } catch {
    return false;
  }
}

/** Every media of a folder (`folderId`) or of the whole vault (null), paged through the source the grid reads. */
export async function listAll(
  accountId: string, folderId: string | number | null, source: "mirror" | "live", signal: AbortSignal,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<VaultMedia[]> {
  const out: VaultMedia[] = [];
  for (let offset = 0; ; ) {
    if (signal.aborted) throw new DOMException("cancelled", "AbortError");
    const p = new URLSearchParams();
    let path: string;
    if (source === "mirror") {
      p.set("account_id", accountId);
      p.set("limit", String(MIRROR_PAGE));
      p.set("offset", String(offset));
      if (folderId != null) p.set("of_folder_id", String(folderId));
      path = `/admin/vault-ai/items?${p}`;
    } else {
      p.set("limit", String(LIVE_PAGE));
      p.set("offset", String(offset));
      if (folderId != null) p.set("list_id", String(folderId));
      path = `/api/of/v2/vault/media?${p}`;
    }
    const r = await relay.get<VaultMediaResp>(path, { accountId }, signal);
    const page = r.list ?? [];
    out.push(...page);
    if (!r.hasMore || page.length === 0) return out;
    offset += page.length;
    if (source === "live") await sleep(LIVE_PAGE_GAP_MS);
  }
}

function relayUrl(accountId: string, it: DlItem): string {
  const p = new URLSearchParams({ account_id: accountId, media_id: String(it.id) });
  if (it.url) p.set("u", it.url);
  const tok = resolveShareToken();
  if (tok) p.set("t", tok);
  return `/admin/vault-ai/download?${p}`;
}

async function resign(accountId: string, it: DlItem): Promise<string | null> {
  const p = new URLSearchParams({ account_id: accountId, media_id: String(it.id) });
  if (it.url) p.set("u", it.url);
  try {
    return (await relay.get<{ url: string }>(`/admin/vault-ai/download/resign?${p}`)).url ?? null;
  } catch {
    return null;
  }
}

async function fileFor(root: FileSystemDirectoryHandle, creator: string, it: DlItem): Promise<FileSystemFileHandle> {
  const c = await root.getDirectoryHandle(creator, { create: true });
  const f = await c.getDirectoryHandle(it.folder, { create: true });
  return f.getFileHandle(it.name, { create: true });
}

/** Stream `r`'s body into the file; the byte count, or throws (a short body is an error, the file is aborted). */
async function save(r: Response, fh: FileSystemFileHandle, signal: AbortSignal, progress: (n: number) => void): Promise<number> {
  if (!r.body) throw new Error("empty body");
  const want = Number(r.headers.get("content-length") || 0);
  let n = 0;
  let last = 0;
  const count = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, ctl) {
      n += chunk.byteLength;
      if (n - last >= 1 << 20) {
        last = n;
        progress(n);
      }
      ctl.enqueue(chunk);
    },
    flush() {
      if (want && n !== want) throw new Error(`short body: ${n} of ${want} bytes`);
    },
  });
  const w = await fh.createWritable();
  await r.body.pipeThrough(count).pipeTo(w, { signal });
  return n;
}

async function directFetch(url: string, signal: AbortSignal): Promise<Response | null> {
  try {
    const r = await fetch(url, { signal, credentials: "omit", cache: "no-store" });
    return r.ok ? r : null;
  } catch (e) {
    if (signal.aborted) throw e;
    return null;   // CloudFront's 403 has no CORS header: a TypeError here
  }
}

export interface RunDeps {
  accountId: string;
  root: FileSystemDirectoryHandle;
  send: Send;
  /** The reducer's state now (the panel keeps it in a ref alongside its dispatch). */
  get: () => DlState;
  signal: AbortSignal;
}

async function one(d: RunDeps, it: DlItem): Promise<void> {
  const { accountId, send, signal } = d;
  send({ type: "itemStart", id: it.id });
  const progress = (n: number) => send({ type: "itemProgress", id: it.id, bytes: n });
  try {
    const fh = await fileFor(d.root, d.get().creator, it);
    let src: DlSource = sourceFor(d.get());
    let r: Response | null = null;
    if (src === "direct" && it.url) {
      r = await directFetch(it.url, signal);
      if (!r) {
        const fresh = await resign(accountId, it);
        r = fresh ? await directFetch(fresh, signal) : null;
        if (!r) send({ type: "directStrike" });
      }
    }
    if (!r) {
      src = "relay";
      r = await fetch(relayUrl(accountId, it), { signal, credentials: "include", cache: "no-store" });
      if (!r.ok) {
        const why = r.status === 422 ? "no downloadable file (DRM-protected video)" : `relay ${r.status}`;
        await r.body?.cancel();
        send({ type: "itemFailed", id: it.id, error: why });
        return;
      }
    }
    const n = await save(r, fh, signal, progress);
    send({ type: "itemDone", id: it.id, source: src, bytes: n });
  } catch (e) {
    send({ type: "itemFailed", id: it.id, error: signal.aborted ? CANCELLED : (e as Error)?.message || String(e) });
  }
}

/** Download every queued item, CONCURRENCY at a time, until done or `signal` aborts. */
export async function runQueue(d: RunDeps): Promise<void> {
  const queue = d.get().items.filter((i) => i.status === "queued");
  const worker = async () => {
    for (let it = queue.shift(); it && !d.signal.aborted; it = queue.shift()) await one(d, it);
  };
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
}

export interface StartArgs {
  accountId: string;
  mode: DlMode;
  label: string;
  creator: string;
  /** selection: the ticked tiles; else listed here. */
  media?: VaultMedia[];
  folder?: { id: string | number; name: string } | null;
  source: "mirror" | "live";
}

/** One whole run: picker, direct check, listing, queue. Returns false when the user closed the picker. */
export async function startDownload(
  a: StartArgs, d: Omit<RunDeps, "root">, setRoot: (r: FileSystemDirectoryHandle) => void,
): Promise<boolean> {
  const root = await pickRoot();
  if (!root) return false;
  setRoot(root);
  d.send({ type: "start", mode: a.mode, label: a.label, creator: a.creator, directAllowed: await directAllowed(a.accountId) });
  let media = a.media;
  if (!media) {
    try {
      media = await listAll(a.accountId, a.folder?.id ?? null, a.source, d.signal);
    } catch (e) {
      d.send({ type: "listFailed", error: d.signal.aborted ? CANCELLED : (e as Error)?.message || String(e) });
      return true;
    }
  }
  d.send({ type: "listed", items: toItems(media, a.folder?.name ?? null) });
  await runQueue({ ...d, root });
  return true;
}
