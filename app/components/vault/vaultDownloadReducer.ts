import { type VaultSource } from "@/hooks/vaultRefresh";
import { type VaultMedia } from "@/lib/relay";

export type DlMode = "selection" | "folder" | "vault";
export type DlSource = "direct" | "relay";
export type DlStatus = "queued" | "active" | "done" | "failed" | "stalled" | "cancelled" | "drm";
export type DlFail = "failed" | "stalled" | "drm";
export type DlPhase = "idle" | "listing" | "running" | "done" | "cancelled";
export type DlSink = "folder" | "share";
export type DlLinks = "none" | "saved" | "failed";
export type DlAccess = "all" | "folders" | "unknown";

export interface DlBatch { ids: number[]; bytes: number; sealed: boolean; saved: boolean }

export interface DlItem {
  id: number;
  kind: string;
  url: string | null;
  folder: string;
  copies?: string[];
  name: string;
  status: DlStatus;
  source: DlSource | null;
  bytes: number;
  error: string | null;
}

export interface DlFolder { id: string | number; name: string }

export interface SavedAt { root: FileSystemDirectoryHandle; dirs: string[] }

export interface DlJobArgs {
  accountId: string;
  creator: string;
  mode: DlMode;
  label: string;
  media?: VaultMedia[];
  folder?: DlFolder | null;
  source: VaultSource;
  items?: DlItem[];
  retryOf?: number;
}

export interface DlJob extends DlJobArgs { qid: number }

export interface DlFinished {
  jobId: number;
  accountId: string;
  creator: string;
  title: string;
  total: number;
  done: number;
  failed: number;
  stalled: number;
  cancelled: number;
  drm: number;
}

export interface DlState {
  phase: DlPhase;
  mode: DlMode | null;
  label: string;
  accountId: string;
  creator: string;
  folder: DlFolder | null;
  savedAt: SavedAt | null;
  items: DlItem[];
  directAllowed: boolean;
  directStrikes: number;
  sink: DlSink;
  batches: DlBatch[];
  links: DlLinks;
  runError: string;
  note: string;
  picking: boolean;
  pickFor: string;
  claim: number;
  attempt: number;
  jobId: number;
  retryOf: number | null;
  seq: number;
  jobs: DlJob[];
  paused: boolean;
  finished: DlFinished[];
}

export type Action =
  | { type: "pick"; accountId: string }
  | { type: "claim"; id: number }
  | { type: "release"; id: number }
  | { type: "pickClosed"; error?: string }
  | { type: "start"; mode: DlMode; label: string; accountId: string; creator: string; sink?: DlSink;
      savedAt?: SavedAt | null; folder?: DlFolder | null; qid?: number; retryOf?: number }
  | { type: "enqueue"; job: DlJobArgs }
  | { type: "clearQueue" }
  | { type: "paused" }
  | { type: "resumed" }
  | { type: "direct"; allowed: boolean; attempt: number }
  | { type: "listed"; items: DlItem[]; attempt: number }
  | { type: "itemStart"; id: number; attempt: number }
  | { type: "itemProgress"; id: number; bytes: number; attempt: number }
  | { type: "itemDone"; id: number; source: DlSource; bytes: number; attempt: number }
  | { type: "itemFailed"; id: number; error: string; reason?: DlFail; attempt: number }
  | { type: "directStrike"; attempt: number }
  | { type: "cancel" }
  | { type: "stop" }
  | { type: "keepAccounts"; ids: readonly string[] }
  | { type: "retryFailed" }
  | { type: "retryLater" }
  | { type: "batchSaved"; index: number; attempt: number }
  | { type: "links"; ok: boolean; attempt: number }
  | { type: "runError"; error: string; attempt: number }
  | { type: "note"; text: string }
  | { type: "close"; discard?: boolean };

export const MAX_DIRECT_STRIKES = 2;
export const CONCURRENCY = 3;
export const SHARE_CONCURRENCY = 1;
export const CANCELLED = "cancelled";
export const SHARE_MAX_ITEMS = 20;
export const SHARE_BATCH_BYTES = 200 * 1024 * 1024;
export const SHARE_HELD_BYTES = 2 * SHARE_BATCH_BYTES;
export const SHARE_FILE_MAX_BYTES = SHARE_BATCH_BYTES;
export const SHARE_TOO_BIG = `Too big for a phone (over ${SHARE_FILE_MAX_BYTES / (1 << 20)} MB): download it on a computer`;
export const LIST_MAX_PAGES = 1000;
export const FINISHED_MAX = 5;
export const JOBS_MAX = 20;

const RETRYABLE: ReadonlySet<DlStatus> = new Set<DlStatus>(["failed", "stalled", "cancelled"]);

export const DOWNLOAD_OFF = "Download needs Chrome or Edge (it saves into a folder you pick)";
export const BUSY_OFF = "A download is running";
export const UNSAVED_OFF = "Save the downloaded files first";
export const SHARE_MODE_OFF = "Phone: only a selection downloads here; folders and the whole vault need desktop Chrome or Edge";
export const SHARE_COUNT_OFF = `Phone: up to ${SHARE_MAX_ITEMS} at a time`;
export const QUEUE_FULL_OFF = `The queue is full (${JOBS_MAX} waiting): let some finish or clear it first`;
export const RESTRICTED_OFF = "Your access is by folder: download a folder";

export const initialDownloadState: DlState = {
  phase: "idle", mode: null, label: "", accountId: "", creator: "", folder: null, savedAt: null, items: [],
  directAllowed: false, directStrikes: 0, sink: "folder", batches: [], links: "none", runError: "", note: "",
  picking: false, pickFor: "", claim: 0, attempt: 0, jobId: 0, retryOf: null, seq: 0, jobs: [], paused: false, finished: [],
};

export function addToBatches(bs: DlBatch[], id: number, bytes: number, budget = SHARE_BATCH_BYTES): DlBatch[] {
  let out = bs;
  let open = out.length && !out[out.length - 1].sealed ? out[out.length - 1] : null;
  if (open && open.ids.length && open.bytes + bytes > budget) {
    out = [...out.slice(0, -1), { ...open, sealed: true }];
    open = null;
  }
  const next: DlBatch = open ? { ...open, ids: [...open.ids, id], bytes: open.bytes + bytes }
    : { ids: [id], bytes, sealed: false, saved: false };
  if (next.bytes >= budget) next.sealed = true;
  return open ? [...out.slice(0, -1), next] : [...out, next];
}

export function sealBatches(bs: DlBatch[]): DlBatch[] {
  const last = bs[bs.length - 1];
  return last && !last.sealed ? [...bs.slice(0, -1), { ...last, sealed: true }] : bs;
}

export function retryJobOf(s: DlState): DlJobArgs | null {
  const items = s.items.filter((i) => RETRYABLE.has(i.status))
    .map((i) => ({ ...i, status: "queued" as const, source: null, bytes: 0, error: null }));
  if (s.sink !== "folder" || !items.length) return null;
  return { accountId: s.accountId, creator: s.creator, mode: "selection", label: `${s.label} · retry ${items.length}`,
           folder: s.folder, source: "mirror", items, retryOf: s.jobId };
}

function append(s: DlState, job: DlJobArgs): DlState {
  if (s.jobs.length >= JOBS_MAX) return s;
  const seq = s.seq + 1;
  return { ...s, seq, jobs: [...s.jobs, { ...job, qid: seq }] };
}

function settled(s: DlState): DlState {
  if (s.items.some((i) => i.status === "queued" || i.status === "active")) return s;
  const done: DlState = { ...s, phase: "done", batches: sealBatches(s.batches) };
  // A retry job's own failures never queue another retry: two jobs would re-queue each other forever.
  const retry = done.jobs.length && done.retryOf == null ? retryJobOf(done) : null;
  return retry ? append(done, retry) : done;
}

function settle(s: DlState): DlState {
  return s.phase === "running" ? settled(s) : s;
}

function patch(s: DlState, id: number, f: (i: DlItem) => DlItem): DlState {
  return { ...s, items: s.items.map((i) => (i.id === id ? f(i) : i)) };
}

function endOpen(items: DlItem[], status: "failed" | "cancelled", error: string | null): DlItem[] {
  return items.map((i) => (i.status === "queued" || i.status === "active"
    ? { ...i, status, source: null, bytes: 0, error } : i));
}

function cancelRun(s: DlState): DlState {
  if (!isBusy(s)) return s;
  return { ...s, phase: "cancelled", batches: sealBatches(s.batches), items: endOpen(s.items, "cancelled", null) };
}

type JobKey = { accountId: string; mode: DlMode | null; folder?: DlFolder | null };

function sameJob(a: JobKey, b: JobKey): boolean {
  return a.mode !== "selection" && a.accountId === b.accountId && a.mode === b.mode
    && String(a.folder?.id ?? "") === String(b.folder?.id ?? "");
}

function finishedOf(s: DlState): DlFinished {
  const sum = summarize(s);
  return { jobId: s.jobId, accountId: s.accountId, creator: s.creator, title: panelTitle(s), total: sum.total,
           done: sum.done, failed: sum.failed, stalled: sum.stalled, cancelled: sum.cancelled, drm: sum.drm };
}

export function vaultDownloadReducer(s: DlState, a: Action): DlState {
  // Late event of an older attempt (a worker cancelled before a Retry) is ignored.
  if ("attempt" in a && a.attempt !== s.attempt) return s;
  switch (a.type) {
    case "pick":
      if (holdsFiles(s)) return s;
      return { ...s, picking: true, pickFor: a.accountId, note: "" };
    case "claim":
      return s.claim || holdsFiles(s) ? s : { ...s, claim: a.id };
    case "release":
      return s.claim === a.id ? { ...s, claim: 0 } : s;
    case "pickClosed":
      return s.picking ? { ...s, picking: false, pickFor: "", note: a.error ? `Folder picker: ${a.error}` : "" } : s;
    case "start": {
      const refused = s.picking ? { ...s, picking: false, pickFor: "" } : s;
      if (isBusy(s) || unsaved(s) > 0 || (s.picking && s.pickFor !== a.accountId)) return refused;
      let jobs = s.jobs;
      if (a.qid != null) {
        if (!jobs.some((j) => j.qid === a.qid)) return refused;
        jobs = jobs.filter((j) => j.qid !== a.qid);
      }
      const finished = s.phase === "idle" ? s.finished : [...s.finished, finishedOf(s)].slice(-FINISHED_MAX);
      const seq = s.seq + 1;
      return { ...initialDownloadState, attempt: s.attempt + 1, phase: "listing", mode: a.mode, label: a.label,
               accountId: a.accountId, creator: a.creator, folder: a.folder ?? null, sink: a.sink ?? "folder",
               savedAt: a.savedAt ?? null, jobId: seq, retryOf: a.retryOf ?? null, seq, jobs, finished };
    }
    case "enqueue": {
      if (!canQueue(s)) return s;
      if ((isBusy(s) && sameJob(a.job, s)) || s.jobs.some((j) => sameJob(a.job, j))) return s;
      if (s.jobs.length >= JOBS_MAX) return s.note === QUEUE_FULL_OFF ? s : { ...s, note: QUEUE_FULL_OFF };
      return append(s, a.job);
    }
    case "clearQueue":
      return s.jobs.length || s.paused ? { ...s, jobs: [], paused: false } : s;
    case "paused":
      return s.jobs.length && !isBusy(s) && !s.paused ? { ...s, paused: true } : s;
    case "resumed":
      return s.paused ? { ...s, paused: false } : s;
    case "direct":
      return s.phase === "listing" ? { ...s, directAllowed: a.allowed } : s;
    case "listed": {
      if (s.phase !== "listing") return s;
      const seen = new Set<number>();
      const items = a.items.filter((i) => !seen.has(i.id) && (seen.add(i.id), true));
      return settle({ ...s, phase: "running", items });
    }
    case "itemStart":
      return s.phase === "running"
        ? patch(s, a.id, (i) => (i.status === "queued" ? { ...i, status: "active", bytes: 0, error: null } : i)) : s;
    case "itemProgress":
      return patch(s, a.id, (i) => (i.status === "active" ? { ...i, bytes: a.bytes } : i));
    case "itemDone": {
      if (!s.items.some((i) => i.id === a.id && i.status === "active")) return s;
      const next = patch(s, a.id, (i) => ({ ...i, status: "done", source: a.source, bytes: a.bytes, error: null }));
      return settle(s.sink === "share" ? { ...next, batches: addToBatches(s.batches, a.id, a.bytes) } : next);
    }
    case "itemFailed":
      return settle(patch(s, a.id, (i) => (i.status === "active"
        ? { ...i, status: a.reason ?? "failed", source: null, error: a.error } : i)));
    case "directStrike":
      return { ...s, directStrikes: s.directStrikes + 1 };
    case "cancel":
      return cancelRun(s);
    case "stop": {
      const next = cancelRun(s);
      return next === s && !s.jobs.length && !s.paused ? s : { ...next, jobs: [], paused: false };
    }
    case "keepAccounts": {
      const keep = new Set(a.ids);
      const jobs = s.jobs.filter((j) => keep.has(j.accountId));
      const finished = s.finished.filter((f) => keep.has(f.accountId));
      const gone = s.phase !== "idle" && !!s.accountId && !keep.has(s.accountId);
      const pickFor = s.pickFor && keep.has(s.pickFor) ? s.pickFor : "";
      if (!gone && pickFor === s.pickFor && jobs.length === s.jobs.length && finished.length === s.finished.length) {
        return s;
      }
      const next = gone
        ? { ...initialDownloadState, attempt: s.attempt, seq: s.seq, picking: s.picking, claim: s.claim } : s;
      return { ...next, pickFor, jobs, finished, paused: s.paused && jobs.length > 0 };
    }
    case "retryLater": {
      const job = canRetry(s) ? retryJobOf(s) : null;
      if (job && s.jobs.length >= JOBS_MAX) return { ...s, note: QUEUE_FULL_OFF };
      return job ? { ...append(s, job), paused: true } : s;
    }
    case "retryFailed":
      if (!canRetry(s)) return s;
      return { ...s, phase: "running", attempt: s.attempt + 1, runError: "", note: "",
               items: s.items.map((i) => (RETRYABLE.has(i.status) ? { ...i, status: "queued", bytes: 0, error: null } : i)) };
    case "batchSaved": {
      const b = s.batches[a.index];
      if (!b || !b.sealed || b.saved) return s;
      return { ...s, note: "", batches: s.batches.map((x, i) => (i === a.index ? { ...x, saved: true } : x)) };
    }
    case "links":
      if (!s.items.length) return s;
      if (s.sink === "share") return a.ok ? { ...s, links: "saved", note: "" } : s;
      return { ...s, links: a.ok ? "saved" : "failed" };
    case "runError":
      if (!isBusy(s)) return s;
      return settled({ ...s, runError: a.error, items: endOpen(s.items, "failed", a.error) });
    case "note":
      return { ...s, note: a.text };
    case "close":
      if (s.picking || isBusy(s) || (unsaved(s) > 0 && !a.discard)) return s;
      return { ...initialDownloadState, attempt: s.attempt, seq: s.seq, claim: s.claim, jobs: s.jobs, paused: s.paused };
  }
}

export function holdsFiles(s: Pick<DlState, "picking" | "phase" | "batches">): boolean {
  return s.picking || isBusy(s) || unsaved(s) > 0;
}

export function canQueue(s: Pick<DlState, "phase" | "sink" | "jobs" | "paused">): boolean {
  return s.sink === "folder" && (isBusy(s) || s.jobs.length > 0 || s.paused);
}

export function queues(sink: DlSink | null, s: Pick<DlState, "phase" | "sink" | "jobs" | "paused">): boolean {
  return sink === "folder" && canQueue(s);
}

export function dlAccess(q: { isLoading: boolean; isError: boolean; data?: { restricted?: boolean } }): DlAccess {
  if (q.isLoading || q.isError) return "unknown";
  return q.data?.restricted === true ? "folders" : "all";
}

export interface DlGate {
  reason: string;
  desktopOnly: boolean;
  queues: boolean;
}

export function downloadLabel(g: DlGate, noun: string): string {
  if (g.desktopOnly) return `Download ${noun} (desktop only)`;
  return g.queues ? `Add ${noun} to queue` : `Download ${noun}`;
}

export function downloadGate(s: DlState, sink: DlSink | null, mode: DlMode, count: number, access: DlAccess): DlGate {
  const q = queues(sink, s);
  const off = (reason: string, desktopOnly = false): DlGate => ({ reason, desktopOnly, queues: q && !reason });
  if (!sink) return off(DOWNLOAD_OFF);
  if (s.picking || (s.claim !== 0 && !q)) return off(BUSY_OFF);
  if (q && s.jobs.length >= JOBS_MAX) return off(QUEUE_FULL_OFF);
  if (sink === "share" && isBusy(s)) return off(busyOff(s));
  if (unsaved(s) > 0) return off(UNSAVED_OFF);
  if (sink === "share" && mode !== "selection") return off(SHARE_MODE_OFF, true);
  if (sink === "share" && count > SHARE_MAX_ITEMS) return off(SHARE_COUNT_OFF);
  if (mode === "vault" && access !== "all") return off(RESTRICTED_OFF);
  return off("");
}

export function busyOff(s: DlState): string {
  return `${BUSY_OFF}: ${progressText(s)}`;
}

export function progressText(s: DlState): string {
  const sum = summarize(s);
  return s.phase === "listing" ? `${s.creator} · listing` : `${s.creator} · ${sum.done}/${sum.total}`;
}

export function concurrencyFor(sink: DlSink): number {
  return sink === "share" ? SHARE_CONCURRENCY : CONCURRENCY;
}

export function maxFileBytes(sink: DlSink): number {
  return sink === "share" ? SHARE_FILE_MAX_BYTES : Infinity;
}

export function readyBatch(s: Pick<DlState, "batches">): number {
  return s.batches.findIndex((b) => b.sealed && !b.saved);
}

export function heldBytes(s: Pick<DlState, "batches">): number {
  return s.batches.reduce((n, b) => n + (b.saved ? 0 : b.bytes), 0);
}

export function canFetchMore(s: Pick<DlState, "sink" | "batches">): boolean {
  return s.sink !== "share" || heldBytes(s) < SHARE_HELD_BYTES;
}

export function batchLabel(s: Pick<DlState, "batches">, index: number): string {
  const from = s.batches.slice(0, index).reduce((n, b) => n + b.ids.length, 0) + 1;
  const to = from + (s.batches[index]?.ids.length ?? 1) - 1;
  return to > from ? `Save ${from}–${to}` : `Save ${from}`;
}

export function unsaved(s: Pick<DlState, "batches">): number {
  return s.batches.reduce((n, b) => n + (b.saved ? 0 : b.ids.length), 0);
}

export function panelTitle(s: DlState): string {
  if (!s.label) return s.jobs.length ? "Download queue" : "Download";
  const what = s.creator ? `${s.creator}: ${s.label}` : s.label;
  if (s.phase === "listing") return `Listing ${what}…`;
  if (s.phase === "running") return `Downloading ${what}`;
  if (s.phase === "cancelled") return `Cancelled: ${what}`;
  const sum = summarize(s);
  if (s.runError && sum.done === 0) return `Download failed: ${what}`;
  if (sum.total === 0) return `Nothing to download: ${what}`;
  if (sum.done === 0) return `Nothing saved: ${what}`;
  if (s.sink === "share" && unsaved(s) > 0) return `Ready to save: ${what}`;
  const verb = s.sink === "share" ? "saved" : "downloaded";
  return sum.done < sum.total ? `Partly ${verb}: ${what}` : `${verb === "saved" ? "Saved" : "Downloaded"} ${what}`;
}

export function countText(s: DlState): string {
  const sum = summarize(s);
  if (s.sink !== "share") return `${sum.done} of ${sum.total} saved`;
  const saved = s.batches.reduce((n, b) => n + (b.saved ? b.ids.length : 0), 0);
  return `${sum.done} of ${sum.total} ready${saved ? ` · ${saved} saved` : ""}`;
}

export function outcomeParts(s: Pick<DlSummary, "failed" | "stalled" | "cancelled" | "drm">): { text: string; bad: boolean }[] {
  const out: { text: string; bad: boolean }[] = [];
  if (s.stalled) out.push({ text: `${s.stalled} stalled`, bad: true });
  if (s.failed) out.push({ text: `${s.failed} failed`, bad: true });
  if (s.drm) out.push({ text: `${s.drm} DRM (no file)`, bad: false });
  if (s.cancelled) out.push({ text: `${s.cancelled} cancelled`, bad: false });
  return out;
}

export function sourceFor(s: Pick<DlState, "directAllowed" | "directStrikes">): DlSource {
  return s.directAllowed && s.directStrikes < MAX_DIRECT_STRIKES ? "direct" : "relay";
}

export function retryable(s: Pick<DlState, "items">): number {
  return s.items.filter((i) => RETRYABLE.has(i.status)).length;
}

export function canRetry(s: DlState): boolean {
  return !s.picking && !s.claim && (s.phase === "done" || s.phase === "cancelled") && retryable(s) > 0
    && !s.jobs.some((j) => j.retryOf === s.jobId);
}

export function isBusy(s: Pick<DlState, "phase">): boolean {
  return s.phase === "listing" || s.phase === "running";
}

export interface DlSummary {
  total: number; done: number; failed: number; stalled: number; cancelled: number; drm: number; active: number;
  bytes: number; direct: number; relay: number;
}

export function summarize(s: Pick<DlState, "items">): DlSummary {
  const out: DlSummary = { total: s.items.length, done: 0, failed: 0, stalled: 0, cancelled: 0, drm: 0, active: 0,
                           bytes: 0, direct: 0, relay: 0 };
  for (const i of s.items) {
    out.bytes += i.bytes;
    if (i.status === "done") {
      out.done += 1;
      if (i.source === "direct") out.direct += 1;
      else if (i.source === "relay") out.relay += 1;
    } else if (i.status === "active") out.active += 1;
    else if (i.status !== "queued") out[i.status] += 1;
  }
  return out;
}


const KIND_EXT: Record<string, string> = { photo: "jpg", video: "mp4", gif: "mp4", audio: "mp3" };
const EXT_MIME: Record<string, string> = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp", heic: "image/heic",
  mp4: "video/mp4", m4v: "video/x-m4v", mov: "video/quicktime", webm: "video/webm", mp3: "audio/mpeg",
  m4a: "audio/mp4", wav: "audio/wav",
};

export function mimeFor(name: string): string {
  const m = /\.([A-Za-z0-9]+)$/.exec(name);
  return (m && EXT_MIME[m[1].toLowerCase()]) || "application/octet-stream";
}
export const UNFILED = "Unfiled";

export function fullUrl(m: Pick<VaultMedia, "files">): string | null {
  const u = m.files?.full?.url;
  return typeof u === "string" && /^https?:\/\//.test(u) ? u : null;
}

export function fileName(id: number, url: string | null, kind: string): string {
  let path = "";
  try {
    path = url ? new URL(url).pathname : "";
  } catch {
    path = "";
  }
  const m = /\.([A-Za-z0-9]{2,5})$/.exec(path);
  return `${id}.${m ? m[1].toLowerCase() : KIND_EXT[kind] ?? "bin"}`;
}

const NAME_MAX = 80;

export function safeName(s: string): string {
  const t = s.replace(/[\u0000-\u001f<>:"/\\|?*]+/g, "_").replace(/^[\s.]+|[\s.]+$/g, "").slice(0, NAME_MAX);
  return t || "_";
}

type Named = { id: string; nickname?: string | null; name?: string | null };
const nameDir = (a: Named | null | undefined, id: string) => safeName(a?.nickname || a?.name || id);

export function creatorDir(id: string, account: Named | null | undefined, all: readonly Named[] = []): string {
  const n = nameDir(account, id);
  const same = (o: Named) => o.id !== id && nameDir(o, o.id).toLowerCase() === n.toLowerCase();
  if (!all.some(same)) return n;
  const suffix = ` (${safeName(id)})`;
  return safeName(`${n.slice(0, Math.max(1, NAME_MAX - suffix.length))}${suffix}`);
}

type ListState = { id?: number | string; type?: string; name?: string; hasMedia?: boolean };

function customFolders(m: VaultMedia): string[] {
  const ls = (m as VaultMedia & { listStates?: ListState[] }).listStates ?? [];
  const names = ls.filter((l) => l.type === "custom" && l.hasMedia !== false && l.name).map((l) => safeName(l.name!));
  return [...new Set(names)];
}

export function folderOf(m: VaultMedia, folder: string | null): string {
  if (folder) return safeName(folder);
  return customFolders(m)[0] ?? UNFILED;
}

export function toItems(media: VaultMedia[], folder: string | null): DlItem[] {
  return media.map((m) => {
    const url = fullUrl(m);
    const copies = folder ? [] : customFolders(m).slice(1);
    return { id: m.id, kind: m.type, url, folder: folderOf(m, folder), ...(copies.length ? { copies } : {}),
             name: fileName(m.id, url, m.type), status: "queued", source: null, bytes: 0, error: null };
  });
}
