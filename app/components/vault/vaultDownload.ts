/**
 * vaultDownload — the download's I/O, no React: list what to save, pick the folder, run the queue. Every outcome
 * goes through `send` (the panel's dispatch); the state and its rules are `vaultDownloadReducer`.
 *
 * Sink `folder`: the File System Access API. `showDirectoryPicker` once, then per item `<creator>/<folder>/<id>.<ext>`
 * written by `response.body.pipeTo(fileHandle.createWritable())`: nothing is held in memory, a cancelled or short
 * file is aborted (the browser drops its temp file), never left half-written.
 * Sink `share` (phones): the same fetch, collected into a `File` (`<id>.<ext>`, its MIME by extension) kept by the
 * caller until the user's tap hands its batch to `navigator.share` (`shareFiles`).
 *
 * Source per item (docs/spec/vault-download.md, measured 2026-11-08): direct (the signed CDN url, S3 answers CORS
 * `*`) while `sourceFor` allows it; a failed direct fetch (CloudFront's 403 carries no CORS header, so it surfaces
 * as a TypeError) re-signs by media id once and retries direct; then the relay stream. A direct item that failed
 * after its re-sign is a `directStrike`.
 */

import { type VaultSource } from "@/hooks/vaultRefresh";
import { relay, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";
import { buildLinksFile, type LinksFile } from "@/components/vault/vaultLinksFile";

import {
  CONCURRENCY, canFetchMore, isBusy, mimeFor, safeName, sourceFor, toItems,
  type Action, type DlItem, type DlMode, type DlSink, type DlSource, type DlState,
} from "@/components/vault/vaultDownloadReducer";

/** The live OF listing's pacing: one 100-item page, then this long before the next (the mirror needs none). */
export const LIVE_PAGE_GAP_MS = 1500;
const MIRROR_PAGE = 500;
const LIVE_PAGE = 100;

export type Send = (a: Action) => void;

/** Where files go here: a picked folder (desktop Chrome/Edge), the share sheet (phones: files shareable), or nowhere. */
export function downloadSink(): DlSink | null {
  if (typeof window === "undefined") return null;
  if (typeof (window as { showDirectoryPicker?: unknown }).showDirectoryPicker === "function") return "folder";
  try {
    const probe = new File([""], "x.jpg", { type: "image/jpeg" });
    return navigator.canShare?.({ files: [probe] }) ? "share" : null;
  } catch {
    return null;
  }
}

/** Hand `files` to the share sheet (Save to Photos / Files). Must run inside the user's tap. "dismissed" when the user
 *  closed the sheet (AbortError): not a failure, the batch stays. */
export async function shareFiles(files: File[]): Promise<"saved" | "dismissed"> {
  try {
    await navigator.share({ files });
    return "saved";
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return "dismissed";
    throw e;
  }
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

/** Every media of a folder (`folderId`) or of the whole vault (null), paged through `source` (`vaultWholeSource`:
 *  a partial mirror would list part of it). The whole vault is soft-denied (empty) to a folder-limited chatter on
 *  both sources; the manager keeps that download off for it. */
export async function listAll(
  accountId: string, folderId: string | number | null, source: VaultSource, signal: AbortSignal,
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

/** Where one item's bytes go: `body` is counted and errors on a short read; neither then nor once `signal` has
 *  aborted may the sink keep it. */
export type Sink = (it: DlItem, body: ReadableStream<Uint8Array>, signal: AbortSignal) => Promise<void>;

/** Each item as `<creator>/<folder>/<id>.<ext>` under `root`, then a copy in each of `it.copies` (read back from disk). */
export function folderSink(root: FileSystemDirectoryHandle, creator: string): Sink {
  return async (it, body, signal) => {
    const c = await root.getDirectoryHandle(creator, { create: true });
    const f = await c.getDirectoryHandle(it.folder, { create: true });
    const fh = await f.getFileHandle(it.name, { create: true });
    await body.pipeTo(await fh.createWritable(), { signal });
    for (const name of it.copies ?? []) {
      const d = await c.getDirectoryHandle(name, { create: true });
      const ch = await d.getFileHandle(it.name, { create: true });
      await (await fh.getFile()).stream().pipeTo(await ch.createWritable(), { signal });
    }
  };
}

/** Each item as a `File` named `<id>.<ext>` with its MIME type, handed to `keep` (the share batches' store). */
export function shareSink(keep: (id: number, f: File) => void): Sink {
  return async (it, body, signal) => {
    const blob = await new Response(body).blob();
    signal.throwIfAborted();   // a cancelled / replaced run keeps nothing (the store outlives a model switch)
    keep(it.id, new File([blob], it.name, { type: mimeFor(it.name) }));
  };
}

/** The links file for the run's items now (vaultLinksFile.ts), links absolute to this page's origin. */
export function linksFor(s: DlState, now = Date.now()): LinksFile {
  return buildLinksFile(s.items, { origin: window.location.origin, accountId: s.accountId, creator: s.creator, label: s.label,
                                   direct: s.directAllowed, now, token: resolveShareToken() });
}

/** Desktop: both links files into `<root>/<creator>/` (a folder download: its `<folder>/`), before any media.
 *  A failure here never stops the download. */
export async function writeLinks(root: FileSystemDirectoryHandle, dirs: string[], f: LinksFile): Promise<void> {
  try {
    let d = root;
    for (const n of dirs) d = await d.getDirectoryHandle(n, { create: true });
    for (const [name, body] of [[f.txtName, f.txt], [f.htmlName, f.html]]) {
      const fh = await d.getFileHandle(name, { create: true });
      await new Blob([body], { type: "text/plain" }).stream().pipeTo(await fh.createWritable());   // as the media sink
    }
  } catch (e) {
    console.warn("vault download: links file not written", e);
  }
}

/** Phone: the links files as Files for their own share (txt + html; just txt if the browser won't share html). */
export function linksShareFiles(f: LinksFile): File[] {
  const txt = new File([f.txt], f.txtName, { type: "text/plain" });
  const both = [txt, new File([f.html], f.htmlName, { type: "text/html" })];
  try {
    if (navigator.canShare?.({ files: both })) return both;
    return navigator.canShare?.({ files: [txt] }) ? [txt] : [];
  } catch {
    return [];
  }
}

/** Count `r`'s body into the sink; the byte count, or throws (a short body is an error, the sink aborts). */
async function save(r: Response, it: DlItem, sink: Sink, signal: AbortSignal, progress: (n: number) => void): Promise<number> {
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
  await sink(it, r.body.pipeThrough(count, { signal }), signal);
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

/** The run's account is the state's (`start` set it): retry after a switch of model still reads the run's own. */
export interface RunDeps {
  sink: Sink;
  send: Send;
  /** The reducer's state now (the panel keeps it in a ref alongside its dispatch). */
  get: () => DlState;
  signal: AbortSignal;
}

async function one(d: RunDeps, it: DlItem): Promise<void> {
  const { send, signal } = d;
  const { accountId } = d.get();
  send({ type: "itemStart", id: it.id });
  const progress = (n: number) => send({ type: "itemProgress", id: it.id, bytes: n });
  try {
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
    const n = await save(r, it, d.sink, signal, progress);
    send({ type: "itemDone", id: it.id, source: src, bytes: n });
  } catch (e) {
    send({ type: "itemFailed", id: it.id, error: (e as Error)?.message || String(e) });   // aborted: dropped (live)
  }
}

/** `d` whose `send` drops everything once its signal aborted: the run was cancelled (the reducer's `cancel` already
 *  failed its open items) or replaced, and a late worker must not write into the run that state now holds. */
function live<T extends { send: Send; signal: AbortSignal }>(d: T): T {
  return { ...d, send: (a: Action) => { if (!d.signal.aborted) d.send(a); } };
}

/** How often a held worker (share sink, unsaved batches at SHARE_HELD_BYTES) looks again. */
const HOLD_POLL_MS = 250;

/** Download every queued item, CONCURRENCY at a time, until done or `signal` aborts. A worker waits before its next
 *  item while `canFetchMore` says no (share sink: ~2 batches unsaved). */
export async function runQueue(run: RunDeps): Promise<void> {
  const d = live(run);
  const queue = d.get().items.filter((i) => i.status === "queued");
  const room = async () => {
    while (!canFetchMore(d.get()) && !d.signal.aborted) await new Promise((r) => setTimeout(r, HOLD_POLL_MS));
  };
  const worker = async () => {
    for (;;) {
      await room();
      const it = queue.shift();
      if (!it || d.signal.aborted) return;
      await one(d, it);
    }
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
  source: VaultSource;
}

/** One whole run: the sink (folder: the picker), direct check, listing, queue. `share` is the share sink's file
 *  store; null = the folder sink. `setSink` runs the moment the `start` is accepted (the run holds the state from
 *  there). Returns false when the user closed the picker, the run was aborted first, or another run is busy: then
 *  nothing runs and the sink is left as it was. */
export async function startDownload(
  a: StartArgs, run: Omit<RunDeps, "sink">, setSink: (s: Sink) => void, share: ((id: number, f: File) => void) | null,
): Promise<boolean> {
  const d = live(run);
  let sink: Sink;
  let root: FileSystemDirectoryHandle | null = null;
  if (share) sink = shareSink(share);
  else {
    root = await pickRoot();
    if (!root) return false;
    const r = root;
    sink = folderSink(r, a.creator);   // this run's Creator, never shared state
  }
  const direct = await directAllowed(a.accountId);
  if (d.signal.aborted || isBusy(d.get())) return false;   // the reducer would refuse the `start` too
  d.send({ type: "start", mode: a.mode, label: a.label, accountId: a.accountId, creator: a.creator,
           sink: share ? "share" : "folder", directAllowed: direct });
  setSink(sink);
  let media = a.media;
  if (!media) {
    try {
      media = await listAll(a.accountId, a.folder?.id ?? null, a.source, d.signal);
    } catch (e) {
      d.send({ type: "listFailed", error: (e as Error)?.message || String(e) });   // aborted: dropped (live)
      return true;
    }
  }
  if (d.signal.aborted) return true;   // d.get() may be another run's state now
  d.send({ type: "listed", items: toItems(media, a.folder?.name ?? null) });
  if (root && d.get().items.length) {
    const s = d.get();
    await writeLinks(root, a.folder ? [s.creator, safeName(a.folder.name)] : [s.creator], linksFor(s));
  }
  await runQueue({ ...d, sink });
  return true;
}
