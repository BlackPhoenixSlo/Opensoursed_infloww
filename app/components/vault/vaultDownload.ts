import { type VaultSource } from "@/hooks/vaultRefresh";
import { relay, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";
import { withinMs } from "@/lib/withinMs";
import { buildLinksFile, downloadPath, type LinksFile } from "@/components/vault/vaultLinksFile";

import {
  CANCELLED, LIST_MAX_PAGES, SHARE_TOO_BIG, canFetchMore, concurrencyFor, maxFileBytes, mimeFor, safeName, sourceFor,
  toItems,
  type Action, type DlFail, type DlItem, type DlJobArgs, type DlSink, type DlSource, type DlState, type SavedAt,
} from "@/components/vault/vaultDownloadReducer";

export type { SavedAt };

export const LIVE_PAGE_GAP_MS = 1500;
const MIRROR_PAGE = 500;
const LIVE_PAGE = 100;

export type Send = (a: Action) => void;

// Below the relay's 30 s low-speed abort, so an upstream stall reads as stalled too.
export const STALL_MS = 20000;
// Outlasts the relay's worst wait before its first byte (45 s slot wait plus URL refresh), else a busy relay reads as a stall.
export const HEAD_MS = 90000;
export const SETUP_MS = HEAD_MS;

export const RELAY_BUSY = "relay busy (503): Retry takes it again";

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

// Must run inside the user's tap; "dismissed" (AbortError) is not a failure.
export async function shareFiles(files: File[]): Promise<"saved" | "dismissed"> {
  try {
    await navigator.share({ files });
    return "saved";
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return "dismissed";
    throw e;
  }
}

// Chrome lapses a picked folder's permission after a while in the background.
export async function canWrite(root: FileSystemDirectoryHandle): Promise<boolean> {
  const h = root as unknown as { queryPermission?: (o: object) => Promise<PermissionState> };
  if (typeof h.queryPermission !== "function") return true;
  try {
    return (await h.queryPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

// Must run inside the user's tap (Resume, Retry).
export async function askWrite(root: FileSystemDirectoryHandle): Promise<boolean> {
  const h = root as unknown as { requestPermission?: (o: object) => Promise<PermissionState> };
  if (typeof h.requestPermission !== "function") return true;
  try {
    return (await h.requestPermission({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

export async function pickRoot(): Promise<FileSystemDirectoryHandle | null> {
  const w = window as unknown as { showDirectoryPicker: (o?: object) => Promise<FileSystemDirectoryHandle> };
  try {
    return await w.showDirectoryPicker({ id: "vault-download", mode: "readwrite" });
  } catch (e) {
    if ((e as DOMException)?.name === "AbortError") return null;
    throw e;
  }
}

// A web page can't open Finder/Explorer, so this opens Chrome's open dialog already in the run's folder.
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

export async function directAllowed(accountId: string, signal: AbortSignal): Promise<boolean> {
  try {
    const r = await withinMs(SETUP_MS, signal, (s) => relay.get<{ direct: boolean }>(
      `/admin/vault-ai/download/info?account_id=${encodeURIComponent(accountId)}`, undefined, s));
    return !!r.direct;
  } catch {
    return false;
  }
}

export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((ok, no) => {
    const gone = () => no(new DOMException("cancelled", "AbortError"));
    if (signal.aborted) return gone();
    const t = setTimeout(() => { signal.removeEventListener("abort", stop); ok(); }, ms);
    const stop = () => { clearTimeout(t); gone(); };
    signal.addEventListener("abort", stop, { once: true });
  });
}

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
    let r: VaultMediaResp;
    try {
      r = await withinMs(SETUP_MS, signal, (s) => relay.get<VaultMediaResp>(path, { accountId }, s));
    } catch (e) {
      if ((e as DOMException)?.name === "TimeoutError" && !signal.aborted) {
        throw new Error(`listing stalled: no answer for ${SETUP_MS / 1000} s`);
      }
      throw e;
    }
    const page = r.list ?? [];
    const fresh = page.filter((m) => !seen.has(m.id));
    for (const m of fresh) seen.add(m.id);
    out.push(...fresh);
    if (!r.hasMore) return out;
    if (fresh.length === 0) {
      throw new Error(page.length ? "listing incomplete: the same page came back again"
        : "listing incomplete: an empty page while more were promised");
    }
    offset += page.length;
    if (source === "live") await sleep(LIVE_PAGE_GAP_MS);
  }
}

function relayUrl(accountId: string, it: DlItem): string {
  return downloadPath(accountId, it.id, { u: it.url, token: resolveShareToken() });
}

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

export type Sink = (it: DlItem, body: ReadableStream<Uint8Array>, signal: AbortSignal, tick?: () => void)
  => Promise<File | null>;

type Owner = { by: object; made: boolean };
// A stalled attempt still winding down must not remove a file its replacement took over; the replacement inherits `made`.
const fileOwners = new WeakMap<FileSystemDirectoryHandle, Map<string, Owner>>();

export function folderSink(root: FileSystemDirectoryHandle, creator: string): Sink {
  return async (it, body, signal, tick = () => {}) => {
    const me = {};
    const owners = fileOwners.get(root) ?? new Map<string, Owner>();
    fileOwners.set(root, owners);
    const c = await root.getDirectoryHandle(creator, { create: true });
    const opened: { d: FileSystemDirectoryHandle; key: string; own: Owner }[] = [];
    const open = async (d: FileSystemDirectoryHandle, folder: string) => {
      signal.throwIfAborted();
      const key = `${creator}/${folder}/${it.name}`;
      // An attempt still on this file (stalled, winding down): its file is ours now.
      const live = owners.get(key);
      const own = { by: me, made: false };
      owners.set(key, own);
      opened.push({ d, key, own });
      try {
        const h = await d.getFileHandle(it.name);
        own.made = !!live?.made;
        return h;
      } catch {
        const h = await d.getFileHandle(it.name, { create: true });
        own.made = true;
        return h;
      }
    };
    const release = () => {
      for (const o of opened) if (owners.get(o.key) === o.own) owners.delete(o.key);
    };
    try {
      const fh = await open(await c.getDirectoryHandle(it.folder, { create: true }), it.folder);
      await body.pipeTo(await fh.createWritable(), { signal });
      for (const name of it.copies ?? []) {
        tick();
        const ch = await open(await c.getDirectoryHandle(name, { create: true }), name);
        const ticking = new TransformStream<Uint8Array, Uint8Array>({ transform(x, ctl) { tick(); ctl.enqueue(x); } });
        await (await fh.getFile()).stream().pipeThrough(ticking, { signal }).pipeTo(await ch.createWritable(), { signal });
      }
    } catch (e) {
      for (const o of opened) {
        if (!o.own.made || owners.get(o.key) !== o.own || typeof o.d.removeEntry !== "function") continue;
        await o.d.removeEntry(it.name).catch(() => {});
      }
      release();
      throw e;
    }
    release();
    return null;
  };
}

export function shareSink(): Sink {
  return async (it, body, signal) => {
    const blob = await new Response(body).blob();
    signal.throwIfAborted();
    return new File([blob], it.name, { type: mimeFor(it.name) });
  };
}

export function linksFor(s: DlState, now = Date.now()): LinksFile {
  return buildLinksFile(s.items, { origin: window.location.origin, accountId: s.accountId, creator: s.creator,
                                   label: s.label, direct: s.directAllowed, now, token: resolveShareToken() });
}

const LINKS_COPIES_MAX = 100;

const linksWritten = new WeakMap<FileSystemDirectoryHandle, Set<string>>();

export async function writeLinks(
  root: FileSystemDirectoryHandle, dirs: string[], f: LinksFile, signal: AbortSignal,
): Promise<boolean> {
  try {
    let d = root;
    for (const n of dirs) d = await d.getDirectoryHandle(n, { create: true });
    signal.throwIfAborted();
    const written = linksWritten.get(root) ?? new Set<string>();
    linksWritten.set(root, written);
    const path = (n: string) => [...dirs, n].join("/");
    const named = (n: string, k: number) => k === 1 ? n : n.replace(/(\.[^.]+)$/, `-${k}$1`);
    let k = 1;
    while (k < LINKS_COPIES_MAX && (written.has(path(named(f.txtName, k))) || written.has(path(named(f.htmlName, k))))) k++;
    const pair = [[named(f.txtName, k), f.txt], [named(f.htmlName, k), f.html]];
    // Reserved before any file opens: a later run picks the next names.
    for (const [name] of pair) written.add(path(name));
    for (const [name, body] of pair) {
      signal.throwIfAborted();
      const fh = await d.getFileHandle(name, { create: true });
      const w = (await fh.createWritable()).getWriter();
      try {
        await w.write(new TextEncoder().encode(body));
        signal.throwIfAborted();
        await w.close();
      } catch (e) {
        await w.abort(e).catch(() => {});
        throw e;
      }
    }
    return true;
  } catch (e) {
    console.warn("vault download: links file not written", e);
    return false;
  }
}

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
    if (r.ok) return r;
    // A non-2xx body left unread holds its connection.
    await r.body?.cancel();
    return null;
  } catch (e) {
    if (signal.aborted) throw e;
    // CloudFront's 403 has no CORS header: a TypeError here.
    return null;
  }
}

export interface RunDeps {
  sink: Sink;
  send: Send;
  get: () => DlState;
  signal: AbortSignal;
  keep?: (id: number, f: File) => void;
}

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

async function one(d: RunDeps, it: DlItem, attempt: number, accountId: string): Promise<void> {
  const { send } = d;
  if (statusOf(d.get(), it.id) !== "queued") return;
  // Only the worker whose own itemStart moved the item queued -> active fetches it (never two for one item).
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

const HOLD_POLL_MS = 250;

export async function runQueue(d: RunDeps): Promise<void> {
  // Fixed to this attempt: a later run may hold the state.
  const { attempt, sink, accountId } = d.get();
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

export type StartArgs = DlJobArgs & { qid?: number };

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
      d.send({ type: "pick", accountId: a.accountId });
      try {
        root = await pickRoot();
      } catch (e) {
        d.send({ type: "pickClosed", error: (e as Error)?.message || String(e) });
        return;
      }
      if (!root || d.signal.aborted) {
        d.send({ type: "pickClosed" });
        return;
      }
    }
    sink = folderSink(root, a.creator);
  }
  const savedAt = root ? { root, dirs: a.folder ? [a.creator, safeName(a.folder.name)] : [a.creator] } : null;
  const before = d.get().attempt;
  d.send({ type: "start", mode: a.mode, label: a.label, accountId: a.accountId, creator: a.creator, sink: kind,
           savedAt, folder: a.folder ?? null, ...(a.qid != null ? { qid: a.qid } : {}),
           ...(a.retryOf != null ? { retryOf: a.retryOf } : {}) });
  const attempt = d.get().attempt;
  if (attempt === before) return;
  started(sink, attempt, root);
  d.send({ type: "direct", allowed: await directAllowed(a.accountId, d.signal), attempt });
  if (a.items) {
    d.send({ type: "listed", items: a.items, attempt });
    await runQueue({ ...d, sink });
    return;
  }
  const media = a.media ?? await listAll(a.accountId, a.folder?.id ?? null, a.source, d.signal);
  d.send({ type: "listed", items: toItems(media, a.folder?.name ?? null), attempt });
  if (savedAt && d.get().attempt === attempt && d.get().items.length) {
    const ok = await withinMs(SETUP_MS, d.signal, (s) => writeLinks(savedAt.root, savedAt.dirs, linksFor(d.get()), s))
      .catch(() => false);
    if (!d.signal.aborted) d.send({ type: "links", ok, attempt });
  }
  await runQueue({ ...d, sink });
}
