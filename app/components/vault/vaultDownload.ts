/**
 * vaultDownload — the download's I/O, no React: list what to save, pick the folder, run the queue. Every outcome
 * goes through `send` (the provider's dispatch); the state and its rules are `vaultDownloadReducer`.
 *
 * Sink `folder`: the File System Access API. `showDirectoryPicker` once (a queued job reuses that folder), then per
 * item `<creator>/<folder>/<id>.<ext>` written by `response.body.pipeTo(fileHandle.createWritable())`: nothing is held
 * in memory, a cancelled or short file is aborted (the browser drops its temp file), never left half-written.
 * Sink `share` (phones): the same fetch, one file at a time, collected into a `File` (`<id>.<ext>`, its MIME by
 * extension; over SHARE_FILE_MAX_BYTES it fails instead) kept by the caller (`keep`, only once the reducer accepted
 * the item) until the user's tap hands its batch to `navigator.share` (`shareFiles`).
 *
 * Source per item (docs/spec/vault-download.md, measured 2026-11-08): direct (the signed CDN url, S3 answers CORS
 * `*`) while `sourceFor` allows it; a failed direct fetch (CloudFront's 403 carries no CORS header, so it surfaces
 * as a TypeError) re-signs by media id once and retries direct; then the relay stream. A direct item that failed
 * after its re-sign is a `directStrike`.
 *
 * Stall watchdog: each item fetches under its own AbortController chained to the run's signal; no response headers
 * for HEAD_MS, or no bytes for STALL_MS after them, aborts it and the item ends `stalled` (the worker goes on). The
 * folder sink's swap file is dropped on that abort and the empty file `getFileHandle` made is removed, so nothing
 * half-written is left (and a retry rewrites the file anyway: the runner never skips one already on disk).
 */

import { type VaultSource } from "@/hooks/vaultRefresh";
import { relay, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";
import { buildLinksFile, downloadPath, type LinksFile } from "@/components/vault/vaultLinksFile";

import {
  CANCELLED, LIST_MAX_PAGES, SHARE_TOO_BIG, canFetchMore, concurrencyFor, maxFileBytes, mimeFor, safeName, sourceFor,
  toItems,
  type Action, type DlFail, type DlItem, type DlJobArgs, type DlSink, type DlSource, type DlState, type SavedAt,
} from "@/components/vault/vaultDownloadReducer";

export type { SavedAt };

/** The live OF listing's pacing: one 100-item page, then this long before the next (the mirror needs none). */
export const LIVE_PAGE_GAP_MS = 1500;
const MIRROR_PAGE = 500;
const LIVE_PAGE = 100;

export type Send = (a: Action) => void;

/** No bytes for this long ends an item `stalled`. Below the relay's own 30 s low-speed abort (curl_cffi stream:
 *  LOW_SPEED_TIME = its timeout), so a stall upstream of the relay reads as stalled too; healthy reads are
 *  sub-second apart (spec, measured 2026-11-08). */
export const STALL_MS = 20000;
/** No response headers for this long ends an item `stalled` (the relay's own upstream timeout is 30 s). */
export const HEAD_MS = 60000;

/** The relay's slot wait ran out (503 download_busy): the item fails, the card's Retry takes it again. */
export const RELAY_BUSY = "relay busy (503): Retry takes it again";

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

/** May the run write into `root` without asking (Chrome lapses a picked folder's permission, e.g. after a while in
 *  the background)? A browser without `queryPermission` never lapses it. */
export async function canWrite(root: FileSystemDirectoryHandle): Promise<boolean> {
  const h = root as unknown as { queryPermission?: (o: object) => Promise<PermissionState> };
  if (typeof h.queryPermission !== "function") return true;
  try {
    return (await h.queryPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

/** Ask for `root`'s write permission again; must run inside the user's tap (Resume, Retry). */
export async function askWrite(root: FileSystemDirectoryHandle): Promise<boolean> {
  const h = root as unknown as { requestPermission?: (o: object) => Promise<PermissionState> };
  if (typeof h.requestPermission !== "function") return true;
  try {
    return (await h.requestPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
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

/** "Open folder": a web page can't open Finder / Explorer or a file:// link, so this opens the computer's own file
 *  window (Chrome's open dialog, `showOpenFilePicker`) already in the run's folder (`startIn`: its handle). Made if
 *  not there yet (mid-run, before the first file). Whatever is picked there is ignored; closing it is not an error. */
export async function showSavedFolder(at: SavedAt): Promise<void> {
  let d = at.root;
  for (const n of at.dirs) d = await d.getDirectoryHandle(n, { create: true });
  const w = window as unknown as { showOpenFilePicker?: (o?: object) => Promise<unknown> };
  if (typeof w.showOpenFilePicker !== "function") throw new Error("This browser can't open a folder");
  try {
    await w.showOpenFilePicker({ startIn: d, multiple: true });
  } catch (e) {
    if ((e as DOMException)?.name !== "AbortError") throw e;
  }
}

/** May the browser fetch this account's CDN urls itself (no proxy)? A failure reads as no: the relay always works.
 *  `signal`: the run's (a cancel ends the wait). */
export async function directAllowed(accountId: string, signal?: AbortSignal): Promise<boolean> {
  try {
    const r = await relay.get<{ direct: boolean }>(
      `/admin/vault-ai/download/info?account_id=${encodeURIComponent(accountId)}`, undefined, signal);
    return !!r.direct;
  } catch {
    return false;
  }
}

/** `ms`, or an AbortError as soon as `signal` aborts (a Cancel never waits out a page gap). */
export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((ok, no) => {
    const gone = () => no(new DOMException("cancelled", "AbortError"));
    if (signal.aborted) return gone();
    const t = setTimeout(() => { signal.removeEventListener("abort", stop); ok(); }, ms);
    const stop = () => { clearTimeout(t); gone(); };
    signal.addEventListener("abort", stop, { once: true });
  });
}

/** Every media of a folder (`folderId`) or of the whole vault (null), paged through `source` (`vaultWholeSource`:
 *  a partial mirror would list part of it). The whole vault is soft-denied (empty) to a folder-limited chatter on
 *  both sources; the manager keeps that download off for it. A page with nothing new while `hasMore` (a stuck
 *  cursor), or more than LIST_MAX_PAGES pages, throws "listing incomplete": never a partial list read as the whole. */
export async function listAll(
  accountId: string, folderId: string | number | null, source: VaultSource, signal: AbortSignal,
  sleep: (ms: number) => Promise<void> = (ms) => abortableSleep(ms, signal),
): Promise<VaultMedia[]> {
  const out: VaultMedia[] = [];
  const seen = new Set<number>();
  for (let offset = 0, pages = 0; ; pages += 1) {
    if (pages >= LIST_MAX_PAGES) throw new Error(`listing incomplete: more than ${LIST_MAX_PAGES} pages`);
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
    const fresh = page.filter((m) => !seen.has(m.id));
    for (const m of fresh) seen.add(m.id);
    out.push(...fresh);
    if (!r.hasMore) return out;
    if (page.length > 0 && fresh.length === 0) throw new Error("listing incomplete: the same page came back again");
    if (page.length === 0) return out;
    offset += page.length;
    if (source === "live") await sleep(LIVE_PAGE_GAP_MS);
  }
}

function relayUrl(accountId: string, it: DlItem): string {
  return downloadPath(accountId, it.id, { u: it.url, token: resolveShareToken() });
}

/** A fresh url for `it`, or null; throws once `signal` (the item's: its HEAD_MS limit, the run's cancel) aborted. */
async function resign(accountId: string, it: DlItem, signal: AbortSignal): Promise<string | null> {
  const p = new URLSearchParams({ account_id: accountId, media_id: String(it.id) });
  if (it.url) p.set("u", it.url);
  try {
    return (await relay.get<{ url: string }>(`/admin/vault-ai/download/resign?${p}`, undefined, signal)).url ?? null;
  } catch (e) {
    if (signal.aborted) throw e;
    return null;
  }
}

/** Where one item's bytes go: `body` is counted and errors on a short read; neither then nor once `signal` has
 *  aborted may the sink keep it. The share sink resolves the File (the runner hands it to `keep` once the reducer
 *  accepted the item); the folder sink null. `tick`: the sink is still moving bytes after the body (the watchdog). */
export type Sink = (it: DlItem, body: ReadableStream<Uint8Array>, signal: AbortSignal, tick?: () => void)
  => Promise<File | null>;

/** Each item as `<creator>/<folder>/<id>.<ext>` under `root`, then a copy in each of `it.copies` (read back from disk,
 *  each chunk a `tick`). `creator`: the run's own, fixed at its start (never shared state: another run may hold that
 *  by then). Any failure removes every file this attempt created (`getFileHandle` makes it, empty, at once); a file
 *  that was there before is left. */
export function folderSink(root: FileSystemDirectoryHandle, creator: string): Sink {
  return async (it, body, signal, tick = () => {}) => {
    const c = await root.getDirectoryHandle(creator, { create: true });
    const made: FileSystemDirectoryHandle[] = [];
    const open = async (d: FileSystemDirectoryHandle) => {
      try {
        return await d.getFileHandle(it.name);
      } catch {
        const h = await d.getFileHandle(it.name, { create: true });
        made.push(d);
        return h;
      }
    };
    try {
      const fh = await open(await c.getDirectoryHandle(it.folder, { create: true }));
      await body.pipeTo(await fh.createWritable(), { signal });
      for (const name of it.copies ?? []) {
        tick();
        const ch = await open(await c.getDirectoryHandle(name, { create: true }));
        const ticking = new TransformStream<Uint8Array, Uint8Array>({ transform(x, ctl) { tick(); ctl.enqueue(x); } });
        await (await fh.getFile()).stream().pipeThrough(ticking, { signal }).pipeTo(await ch.createWritable(), { signal });
      }
    } catch (e) {
      for (const d of made) {
        if (typeof d.removeEntry === "function") await d.removeEntry(it.name).catch(() => {});
      }
      throw e;
    }
    return null;
  };
}

/** Each item as a `File` named `<id>.<ext>` with its MIME type (the share batches' store keeps it). */
export function shareSink(): Sink {
  return async (it, body, signal) => {
    const blob = await new Response(body).blob();
    signal.throwIfAborted();   // a cancelled / replaced run keeps nothing (the store outlives a Creator switch)
    return new File([blob], it.name, { type: mimeFor(it.name) });
  };
}

/** The links file for the run's items now (vaultLinksFile.ts), links absolute to this page's origin. */
export function linksFor(s: DlState, now = Date.now()): LinksFile {
  return buildLinksFile(s.items, { origin: window.location.origin, accountId: s.accountId, creator: s.creator,
                                   label: s.label, direct: s.directAllowed, now, token: resolveShareToken() });
}

/** Desktop: both links files into `<root>/<creator>/` (a folder download: its `<folder>/`), before any media.
 *  A failure here never stops the download; false tells the card not to point at the file. */
export async function writeLinks(root: FileSystemDirectoryHandle, dirs: string[], f: LinksFile): Promise<boolean> {
  try {
    let d = root;
    for (const n of dirs) d = await d.getDirectoryHandle(n, { create: true });
    for (const [name, body] of [[f.txtName, f.txt], [f.htmlName, f.html]]) {
      const fh = await d.getFileHandle(name, { create: true });
      await new Blob([body], { type: "text/plain" }).stream().pipeTo(await fh.createWritable());   // as the media sink
    }
    return true;
  } catch (e) {
    console.warn("vault download: links file not written", e);
    return false;
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

/** Count `r`'s body into the sink; the byte count and the sink's File, or throws (a short body or one over `max` is an
 *  error, the sink aborts). `chunk` runs on every read (the stall watchdog); `stall` rejects when it fires (a hung
 *  write can keep `pipeTo` open). */
async function save(
  r: Response, it: DlItem, sink: Sink, signal: AbortSignal, progress: (n: number) => void, chunk: () => void,
  stall: Promise<never>, max: number,
): Promise<{ n: number; file: File | null }> {
  if (!r.body) throw new Error("empty body");
  const want = Number(r.headers.get("content-length") || 0);
  if (want > max) {
    await r.body.cancel();
    throw new Error(SHARE_TOO_BIG);
  }
  let n = 0;
  let last = 0;
  const count = new TransformStream<Uint8Array, Uint8Array>({
    transform(c, ctl) {
      chunk();
      n += c.byteLength;
      if (n > max) {
        ctl.error(new Error(SHARE_TOO_BIG));
        return;
      }
      if (n - last >= 1 << 20) {
        last = n;
        progress(n);
      }
      ctl.enqueue(c);
    },
    flush() {
      if (want && n !== want) throw new Error(`short body: ${n} of ${want} bytes`);
    },
  });
  const file = await Promise.race([sink(it, r.body.pipeThrough(count, { signal }), signal, chunk), stall]);
  return { n, file };
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

/** The run's account is the state's (`start` set it): Retry after a Creator switch still reads the run's own. */
export interface RunDeps {
  sink: Sink;
  send: Send;
  /** The reducer's state now (the provider keeps it in a ref alongside its dispatch). */
  get: () => DlState;
  signal: AbortSignal;
  /** Share sink: the store of fetched files until their batch is saved. */
  keep?: (id: number, f: File) => void;
}

/** One item's AbortController, chained to the run's `signal`: `kick(ms)` (re)arms its timer; when that fires the
 *  item aborts, `stalled` turns true and `stall` rejects. `end()` disarms and unchains. */
function watchdog(signal: AbortSignal) {
  const ac = new AbortController();
  const onRun = () => ac.abort(signal.reason);
  if (signal.aborted) onRun();
  else signal.addEventListener("abort", onRun, { once: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  let fire: (e: Error) => void = () => {};
  const stall = new Promise<never>((_, no) => { fire = no; });
  stall.catch(() => {});
  const w = {
    signal: ac.signal,
    stall,
    stalled: false,
    kick(ms: number) {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const e = new DOMException(`no data for ${ms / 1000} s`, "TimeoutError");
        w.stalled = true;
        ac.abort(e);
        fire(e);
      }, ms);
    },
    end() {
      clearTimeout(timer);
      signal.removeEventListener("abort", onRun);
    },
  };
  return w;
}

const statusOf = (s: DlState, id: number) => s.items.find((i) => i.id === id)?.status;

/** One item of `attempt` (of the run on `accountId`). Every event carries the attempt, so a worker of a cancelled
 *  attempt can't touch a retry or the next queued run; and the worker stops when its itemStart was not accepted (the
 *  item is no longer this attempt's to fetch). */
async function one(d: RunDeps, it: DlItem, attempt: number, accountId: string): Promise<void> {
  const { send } = d;
  // Only the worker whose own itemStart moved the item queued -> active fetches it (never two for one item).
  if (statusOf(d.get(), it.id) !== "queued") return;
  send({ type: "itemStart", id: it.id, attempt });
  if (statusOf(d.get(), it.id) !== "active") return;
  const w = watchdog(d.signal);
  const signal = w.signal;
  const progress = (n: number) => { if (!w.stalled) send({ type: "itemProgress", id: it.id, bytes: n, attempt }); };
  try {
    let src: DlSource = sourceFor(d.get());
    let r: Response | null = null;
    if (src === "direct" && it.url) {
      w.kick(HEAD_MS);
      r = await directFetch(it.url, signal);
      if (!r) {
        w.kick(HEAD_MS);
        const fresh = await resign(accountId, it, signal);
        w.kick(HEAD_MS);
        r = fresh ? await directFetch(fresh, signal) : null;
        if (!r) send({ type: "directStrike", attempt });
      }
    }
    if (!r) {
      src = "relay";
      w.kick(HEAD_MS);
      r = await fetch(relayUrl(accountId, it), { signal, credentials: "include", cache: "no-store" });
      if (!r.ok) {
        const drm = r.status === 422;
        const why = drm ? "no downloadable file (DRM-protected video)"
          : r.status === 503 ? RELAY_BUSY : `relay ${r.status}`;
        await r.body?.cancel();
        send({ type: "itemFailed", id: it.id, reason: drm ? "drm" : "failed", error: why, attempt });
        return;
      }
    }
    w.kick(STALL_MS);
    const { n, file } = await save(r, it, d.sink, signal, progress, () => w.kick(STALL_MS), w.stall,
                                   maxFileBytes(d.get().sink));
    send({ type: "itemDone", id: it.id, source: src, bytes: n, attempt });
    // Kept only when the reducer took it (a batch now names it): a late file of a cancelled attempt is dropped here.
    if (file && d.get().attempt === attempt && statusOf(d.get(), it.id) === "done") d.keep?.(it.id, file);
  } catch (e) {
    const reason: DlFail = w.stalled ? "stalled" : "failed";
    const error = w.stalled ? `stalled: no data for ${STALL_MS / 1000} s`
      : d.signal.aborted ? CANCELLED : (e as Error)?.message || String(e);
    send({ type: "itemFailed", id: it.id, reason, error, attempt });
  } finally {
    w.end();
  }
}

/** How often a held worker (share sink, unsaved batches at SHARE_HELD_BYTES) looks again. */
const HOLD_POLL_MS = 250;

/** Download every queued item of the current attempt, `concurrencyFor(sink)` at a time, until done or `signal` aborts.
 *  A worker waits before its next item while `canFetchMore` says no (share sink: ~2 batches unsaved). */
export async function runQueue(d: RunDeps): Promise<void> {
  const { attempt, sink, accountId } = d.get();   // this attempt's, fixed: a later run may hold the state
  const queue = d.get().items.filter((i) => i.status === "queued");
  const room = async () => {
    while (!canFetchMore(d.get()) && !d.signal.aborted) await new Promise((r) => setTimeout(r, HOLD_POLL_MS));
  };
  const worker = async () => {
    for (;;) {
      await room();
      const it = queue.shift();
      if (!it || d.signal.aborted) return;
      await one(d, it, attempt, accountId);
    }
  };
  await Promise.all(Array.from({ length: concurrencyFor(sink) }, worker));
}

/** A job to start; `qid`: it is the queue's head (`jobs`), which its `start` drops it from. */
export type StartArgs = DlJobArgs & { qid?: number };

/** One whole run into `kind` (the browser's `downloadSink()`): the sink (folder: `root` when the queue reuses its
 *  folder, else the picker, `pick` / `pickClosed`; a picker that throws is `pickClosed` with its error), `start`,
 *  direct check, listing (a retry job's items are not listed again), links file, queue.
 *  `started` gets the Sink, the attempt `start` actually made and the folder (Retry reuses the Sink, also after a
 *  Cancel while the workers still wind down; the caller pins its failure handler to the attempt). The share sink
 *  dispatches `start` before any await, so a second tap finds the run already going. A refused `start` (another run
 *  holds files, the queued job is gone) ends here. Any throw after `start` (listing included) is the run's failure:
 *  the caller aborts it and sends `runError` for that attempt. */
export async function startDownload(
  a: StartArgs, d: Omit<RunDeps, "sink">, kind: DlSink,
  started: (s: Sink, attempt: number, root: FileSystemDirectoryHandle | null) => void,
  given: FileSystemDirectoryHandle | null = null,
): Promise<void> {
  let sink: Sink;
  let root: FileSystemDirectoryHandle | null = given;
  if (kind === "share") sink = shareSink();
  else {
    if (!root) {
      d.send({ type: "pick" });
      try {
        root = await pickRoot();
      } catch (e) {
        d.send({ type: "pickClosed", error: (e as Error)?.message || String(e) });
        return;
      }
      if (!root) {
        d.send({ type: "pickClosed" });
        return;
      }
    }
    sink = folderSink(root, a.creator);   // this run's Creator, never shared state
  }
  // Where a folder run saves (its links files too): the card's "Saved in" / Open folder, from `start` on (#445).
  const savedAt = root ? { root, dirs: a.folder ? [a.creator, safeName(a.folder.name)] : [a.creator] } : null;
  const before = d.get().attempt;
  d.send({ type: "start", mode: a.mode, label: a.label, accountId: a.accountId, creator: a.creator, sink: kind,
           savedAt, folder: a.folder ?? null, ...(a.qid != null ? { qid: a.qid } : {}) });
  const attempt = d.get().attempt;
  if (attempt === before) return;   // refused: another run holds files, or the queued job is gone
  started(sink, attempt, root);
  d.send({ type: "direct", allowed: await directAllowed(a.accountId, d.signal), attempt });
  if (a.items) {   // a retry job: those items again, same paths; its links file was written by the first run
    d.send({ type: "listed", items: a.items, attempt });
    await runQueue({ ...d, sink });
    return;
  }
  const media = a.media ?? await listAll(a.accountId, a.folder?.id ?? null, a.source, d.signal);
  d.send({ type: "listed", items: toItems(media, a.folder?.name ?? null), attempt });
  if (savedAt && d.get().attempt === attempt && d.get().items.length) {
    const ok = await writeLinks(savedAt.root, savedAt.dirs, linksFor(d.get()));
    d.send({ type: "links", ok, attempt });
  }
  await runQueue({ ...d, sink });
}
