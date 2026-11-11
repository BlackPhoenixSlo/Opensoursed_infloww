/**
 * vaultDownloadReducer — Vault Pro's download (a selection, one folder, the whole vault) as a pure reducer.
 *
 * The provider only dispatches; `vaultDownload.ts` runs the queue (listing, fetch, the file sink) and dispatches what
 * happened. Each item saves to `<creator>/<folder>/<mediaId>.<ext>` and records the source that delivered it:
 * `direct` (the browser fetched OF's signed CDN url itself; only when the account has no proxy, see
 * docs/spec/vault-download.md) or `relay` (`/admin/vault-ai/download`, through the account's client).
 *
 * One run at a time, app-wide (the provider sits above the routes). Folder sink: a download asked for while a run is
 * busy (or jobs wait) is a queued job (`jobs`, `enqueue`); the provider starts the next one when the run settles,
 * into the same picked folder. Each item ends `done` or without a file: `failed`, `stalled` (no bytes for STALL_MS),
 * `cancelled` (all three retryable) or `drm` (a DRM-only video: no file exists, never retried, never "failed").
 *
 * Sink `folder` (desktop Chrome/Edge) writes each file into a picked folder. Sink `share` (phones: no folder picker,
 * but `navigator.share` takes files) is selection-only, at most SHARE_MAX_ITEMS, never queues: each fetched file joins
 * the open batch until SHARE_BATCH_BYTES, a sealed batch waits for the user's "Save" tap (the share sheet), and
 * fetching holds while unsaved batches reach SHARE_HELD_BYTES.
 */

import { type VaultSource } from "@/hooks/vaultRefresh";
import { type VaultMedia } from "@/lib/relay";

export type DlMode = "selection" | "folder" | "vault";
export type DlSource = "direct" | "relay";
/** `failed` / `stalled` / `cancelled` are retryable; `drm` (a DRM-only video: no full file) is not. */
export type DlStatus = "queued" | "active" | "done" | "failed" | "stalled" | "cancelled" | "drm";
/** Why the runner ended an item without a file (`cancelled` is the reducer's own, from `cancel`). */
export type DlFail = "failed" | "stalled" | "drm";
export type DlPhase = "idle" | "listing" | "running" | "done" | "cancelled";
export type DlSink = "folder" | "share";
/** The links file: not written yet, written (desktop) / handed to a share sheet (phone), or the desktop write failed. */
export type DlLinks = "none" | "saved" | "failed";
/** What the caller may download: everything, only its folders (a folder-limited chatter), or not known yet. */
export type DlAccess = "all" | "folders" | "unknown";

/** Share sink: files handed to one share sheet, in fetch-completion order. `sealed`: no more files join it. */
export interface DlBatch { ids: number[]; bytes: number; sealed: boolean; saved: boolean }

export interface DlItem {
  id: number;
  kind: string;
  /** The full-quality CDN url the listing carried; null for a DRM-only video (only the relay can say why). */
  url: string | null;
  folder: string;
  /** More folders the item is in (no forced folder): the folder sink writes a copy into each. */
  copies?: string[];
  name: string;
  status: DlStatus;
  source: DlSource | null;
  bytes: number;
  error: string | null;
}

/** The folder a run saves under (folder mode, or a selection made inside it). */
export interface DlFolder { id: string | number; name: string }

/** Where a folder run saves (#445): the picked folder and the path under it (`<creator>`, a folder download's
 *  `<folder>`), where its links files go too. */
export interface SavedAt { root: FileSystemDirectoryHandle; dirs: string[] }

/** One download: the model it is for (never the one on screen later), what, and how to list it. */
export interface DlJobArgs {
  accountId: string;
  creator: string;
  mode: DlMode;
  label: string;
  /** selection: the ticked tiles; else listed when the job starts. */
  media?: VaultMedia[];
  folder?: DlFolder | null;
  source: VaultSource;
  /** A retry job: these items again (same paths, not listed); `retryOf`: the run they came from. */
  items?: DlItem[];
  retryOf?: number;
}

/** A queued download (folder sink only); `qid` names it until it starts. */
export interface DlJob extends DlJobArgs { qid: number }

/** A run a later one replaced on the card, kept as one line. */
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
  /** What is being downloaded ("3 selected", "folder Beach", "whole vault"); the title adds the creator. */
  label: string;
  /** The run's model (its id / its folder name), set by its `start`: retry, re-sign and the links file use these,
   *  never the model on screen, which may have changed since (the app's one download outlives a Creator switch). */
  accountId: string;
  creator: string;
  /** The folder this run saves under (folder mode, or a selection made in it); null: each item's own folder. */
  folder: DlFolder | null;
  /** Folder sink: where this run saves, set by its `start` (null before it, and for the share sink): the card's
   *  "Saved in" line and Open folder. */
  savedAt: SavedAt | null;
  items: DlItem[];
  /** The account has no proxy, so its urls are signed for this machine's IP and the browser may fetch them
   *  (`direct`, read after `start`; false until then: the relay always works). */
  directAllowed: boolean;
  /** Items whose direct fetch failed even after a re-sign; at MAX_DIRECT_STRIKES direct is off for this run. */
  directStrikes: number;
  sink: DlSink;
  /** Share sink only: the batches so far; the last may be open. */
  batches: DlBatch[];
  links: DlLinks;
  /** Why the run itself threw (it ended there; not a per-item failure); "" when none. */
  runError: string;
  /** A message only (the picker, a share sheet or the folder's permission failed): never changes the phase or the
   *  items; "" when none. */
  note: string;
  /** The folder picker is open for a next run (folder sink). The run below stays as it was (a finished run keeps its
   *  card and its Retry) until that next run's `start`; a closed picker leaves it untouched. */
  picking: boolean;
  /** This run's attempt (start / Retry failed bump it). Item events carry the attempt they belong to; an older
   *  attempt's late event (a worker cancelled before a Retry) is ignored. Never reset, so a new run is never confused
   *  with a cancelled one either. */
  attempt: number;
  /** This run's number (0: none yet). Runs and queued jobs (`qid`) count on `seq`. */
  jobId: number;
  seq: number;
  /** Folder sink: downloads waiting for this run, in order. */
  jobs: DlJob[];
  /** The next job waits for the folder's write permission again (the user's Resume tap re-asks). */
  paused: boolean;
  /** Earlier runs this card replaced, oldest first, at most FINISHED_MAX. */
  finished: DlFinished[];
}

export type Action =
  | { type: "pick" }
  /** The picker closed (`error`: it threw instead of a plain close). */
  | { type: "pickClosed"; error?: string }
  /** Dispatched before the runner's first await (after its picker), so a second tap already finds the run.
   *  `qid`: the queue's head, which it drops from `jobs`. */
  | { type: "start"; mode: DlMode; label: string; accountId: string; creator: string; sink?: DlSink;
      savedAt?: SavedAt | null; folder?: DlFolder | null; qid?: number }
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
  /** Cancel the run and drop the queue (the provider unmounting: sign-out). */
  | { type: "stop" }
  /** Only these accounts still exist: drop the others' queued jobs, cancel a run of theirs. */
  | { type: "keepAccounts"; ids: readonly string[] }
  | { type: "retryFailed" }
  /** Retry, but the folder's permission was refused: the retry waits as a queued job behind Resume. */
  | { type: "retryLater" }
  /** A share sheet resolved for batch `index` of run `attempt` (a late one of an older run changes nothing). */
  | { type: "batchSaved"; index: number; attempt: number }
  | { type: "links"; ok: boolean; attempt: number }
  /** Terminal, the one failure channel of a run (`attempt`): the listing or the run threw; it ends, nothing stays
   *  queued or active. */
  | { type: "runError"; error: string; attempt: number }
  | { type: "note"; text: string }
  | { type: "close"; discard?: boolean };

/** Direct fetches that fail even after a re-sign before every later item goes through the relay. */
export const MAX_DIRECT_STRIKES = 2;
/** Files fetched at once per tab (folder sink: each streams to disk). */
export const CONCURRENCY = 3;
/** Share sink: one file at a time, so in memory sit at most SHARE_HELD_BYTES of unsaved batches + one file. */
export const SHARE_CONCURRENCY = 1;
/** The error a worker cancelled with its run carries (its late event is dropped either way). */
export const CANCELLED = "cancelled";
/** Share sink: at most this many files per run (a selection). */
export const SHARE_MAX_ITEMS = 20;
/** Share sink: a batch fills to this many bytes; a bigger file is a batch of its own. Tune here. */
export const SHARE_BATCH_BYTES = 200 * 1024 * 1024;
/** Share sink: fetching holds while unsaved batches hold this many bytes (~2 batches in memory). */
export const SHARE_HELD_BYTES = 2 * SHARE_BATCH_BYTES;
/** Share sink: a file bigger than this fails instead of being held in the phone's memory. */
export const SHARE_FILE_MAX_BYTES = SHARE_BATCH_BYTES;
export const SHARE_TOO_BIG = `Too big for a phone (over ${SHARE_FILE_MAX_BYTES / (1 << 20)} MB): download it on a computer`;
/** Folder / whole-vault listing: at most this many pages (500k mirror rows, 100k live), then "listing incomplete". */
export const LIST_MAX_PAGES = 1000;
/** Lines of earlier runs the card keeps. */
export const FINISHED_MAX = 5;

const RETRYABLE: ReadonlySet<DlStatus> = new Set<DlStatus>(["failed", "stalled", "cancelled"]);

export const DOWNLOAD_OFF = "Download needs Chrome or Edge (it saves into a folder you pick)";
export const BUSY_OFF = "A download is running";
/** Phone: a finished run whose fetched files wait for their Save tap holds the next one (a new run would drop them). */
export const UNSAVED_OFF = "Save the downloaded files first";
export const SHARE_MODE_OFF = "Phone: only a selection downloads here; folders and the whole vault need desktop Chrome or Edge";
export const SHARE_COUNT_OFF = `Phone: up to ${SHARE_MAX_ITEMS} at a time`;
/** The relay soft-denies "All" to a folder-limited chatter on both sources, so its whole-vault download would read
 *  "Nothing to download". Also while its folder access is unread (loading / failed): never a false empty. */
export const RESTRICTED_OFF = "Your access is by folder: download a folder";

export const initialDownloadState: DlState = {
  phase: "idle", mode: null, label: "", accountId: "", creator: "", folder: null, savedAt: null, items: [],
  directAllowed: false, directStrikes: 0, sink: "folder", batches: [], links: "none", runError: "", note: "",
  picking: false, attempt: 0, jobId: 0, seq: 0, jobs: [], paused: false, finished: [],
};

/** Share sink: add a fetched file to the open batch. A file that would push a non-empty batch past `budget` seals it
 *  and opens the next; a batch at or over `budget` seals at once (so a file >= budget is a batch of its own). */
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

/** Seal the open batch (nothing more is coming). */
export function sealBatches(bs: DlBatch[]): DlBatch[] {
  const last = bs[bs.length - 1];
  return last && !last.sealed ? [...bs.slice(0, -1), { ...last, sealed: true }] : bs;
}

/** The run's retryable items as a job (folder sink), or null: Retry for a run a queued job is about to replace. */
export function retryJobOf(s: DlState): DlJobArgs | null {
  const items = s.items.filter((i) => RETRYABLE.has(i.status))
    .map((i) => ({ ...i, status: "queued" as const, source: null, bytes: 0, error: null }));
  if (s.sink !== "folder" || !items.length) return null;
  return { accountId: s.accountId, creator: s.creator, mode: "selection", label: `${s.label} · retry ${items.length}`,
           folder: s.folder, source: "mirror", items, retryOf: s.jobId };
}

/** Append `job` to the queue (no dedupe: a retry job is never another's duplicate). */
function append(s: DlState, job: DlJobArgs): DlState {
  const seq = s.seq + 1;
  return { ...s, seq, jobs: [...s.jobs, { ...job, qid: seq }] };
}

/** The run ended: the open batch seals; with jobs waiting (the next one replaces this card at once) its retryable
 *  items join the queue's end as a retry job, so they keep a Retry. The one way to `done`, and never while an item is
 *  still queued / active: every item has its outcome (done / failed / stalled / cancelled / drm) first. */
function settled(s: DlState): DlState {
  if (s.items.some((i) => i.status === "queued" || i.status === "active")) return s;
  const done: DlState = { ...s, phase: "done", batches: sealBatches(s.batches) };
  const retry = done.jobs.length ? retryJobOf(done) : null;
  return retry ? append(done, retry) : done;
}

function settle(s: DlState): DlState {
  return s.phase === "running" ? settled(s) : s;
}

function patch(s: DlState, id: number, f: (i: DlItem) => DlItem): DlState {
  return { ...s, items: s.items.map((i) => (i.id === id ? f(i) : i)) };
}

/** Queued / active items end as `status` with `error` (a run that threw: failed; a cancel: cancelled). */
function endOpen(items: DlItem[], status: "failed" | "cancelled", error: string | null): DlItem[] {
  return items.map((i) => (i.status === "queued" || i.status === "active"
    ? { ...i, status, source: null, bytes: 0, error } : i));
}

function cancelRun(s: DlState): DlState {
  if (!isBusy(s)) return s;
  return { ...s, phase: "cancelled", batches: sealBatches(s.batches), items: endOpen(s.items, "cancelled", null) };
}

type JobKey = { accountId: string; mode: DlMode | null; folder?: DlFolder | null };

/** The same folder / whole vault of the same model (two selections are never the same job). */
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
  if ("attempt" in a && a.attempt !== s.attempt) return s;   // a late event of an older attempt
  switch (a.type) {
    case "pick":
      if (holdsFiles(s)) return s;
      return { ...s, picking: true, note: "" };
    case "pickClosed":
      // The run below (a finished one, its Retry) stays as it was; the note names the picker, not that run (#41).
      return s.picking ? { ...s, picking: false, note: a.error ? `Folder picker: ${a.error}` : "" } : s;
    case "start": {
      // One run at a time; unsaved phone files are never dropped by a new run. After `pick` (its own picker) too. A
      // refused start still ends its picker (the runner returns without `pickClosed`, #40).
      const refused = s.picking ? { ...s, picking: false } : s;
      if (isBusy(s) || unsaved(s) > 0) return refused;
      let jobs = s.jobs;
      if (a.qid != null) {       // the queue's head; gone (Clear queue meanwhile): nothing starts
        if (!jobs.some((j) => j.qid === a.qid)) return refused;
        jobs = jobs.filter((j) => j.qid !== a.qid);
      }
      const finished = s.phase === "idle" ? s.finished : [...s.finished, finishedOf(s)].slice(-FINISHED_MAX);
      const seq = s.seq + 1;
      return { ...initialDownloadState, attempt: s.attempt + 1, phase: "listing", mode: a.mode, label: a.label,
               accountId: a.accountId, creator: a.creator, folder: a.folder ?? null, sink: a.sink ?? "folder",
               savedAt: a.savedAt ?? null, jobId: seq, seq, jobs, finished };
    }
    case "enqueue": {
      if (!canQueue(s)) return s;
      if ((isBusy(s) && sameJob(a.job, s)) || s.jobs.some((j) => sameJob(a.job, j))) return s;   // asked twice
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
      // Only from `active`: the runner always starts an item first, and a queued item is a requeued one (Retry).
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
      const gone = isBusy(s) && !keep.has(s.accountId);
      // a finished run of a removed model: its card (and Retry) goes
      const stale = !isBusy(s) && s.phase !== "idle" && !!s.accountId && !keep.has(s.accountId);
      if (!gone && !stale && jobs.length === s.jobs.length) return s;
      if (stale) {
        return { ...initialDownloadState, attempt: s.attempt, seq: s.seq, finished: s.finished, jobs,
                 paused: s.paused && jobs.length > 0 };
      }
      const next = gone ? cancelRun(s) : s;
      return { ...next, jobs, paused: next.paused && jobs.length > 0 };
    }
    case "retryLater": {
      const job = canRetry(s) ? retryJobOf(s) : null;
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
      // Desktop: the write's outcome. Phone: only a share that resolved (`ok`); a dismissed sheet changes nothing.
      if (!s.items.length) return s;
      if (s.sink === "share") return a.ok ? { ...s, links: "saved", note: "" } : s;
      return { ...s, links: a.ok ? "saved" : "failed" };
    case "runError":
      // Only a listing / running attempt ends here (`attempt` checked above); after a Cancel it changes nothing.
      if (!isBusy(s)) return s;
      return settled({ ...s, runError: a.error, items: endOpen(s.items, "failed", a.error) });
    case "note":
      return { ...s, note: a.text };
    case "close":
      // Unsaved phone files go only on an explicit discard. A queue waiting on Resume stays (Clear queue drops it).
      if (s.picking || isBusy(s) || (unsaved(s) > 0 && !a.discard)) return s;
      return { ...initialDownloadState, attempt: s.attempt, seq: s.seq, jobs: s.jobs, paused: s.paused };
  }
}

/** The download can't take a next run now: a picker is open for one, the run is listing / running, or (phone)
 *  fetched files wait for their Save tap. The one rule for `pick`, the hook's start and file store and the close X.
 *  (A folder-sink Download press while busy queues instead: `queues`.) */
export function holdsFiles(s: Pick<DlState, "picking" | "phase" | "batches">): boolean {
  return s.picking || isBusy(s) || unsaved(s) > 0;
}

/** Folder sink: a download asked for now joins the queue (a run is busy, or jobs wait) instead of starting. */
export function canQueue(s: Pick<DlState, "phase" | "sink" | "jobs" | "paused">): boolean {
  return s.sink === "folder" && (isBusy(s) || s.jobs.length > 0 || s.paused);
}

/** In this browser (`sink`), does a Download press queue rather than start? Never on the share sink. */
export function queues(sink: DlSink | null, s: Pick<DlState, "phase" | "sink" | "jobs" | "paused">): boolean {
  return sink === "folder" && canQueue(s);
}

/** A folder-access read (`useChatterFolderAccess`) as what the caller may download. An owner's query is disabled
 *  (not loading, no data): everything. */
export function dlAccess(q: { isLoading: boolean; isError: boolean; data?: { restricted?: boolean } }): DlAccess {
  if (q.isLoading || q.isError) return "unknown";
  return q.data?.restricted === true ? "folders" : "all";
}

export interface DlGate {
  /** Why it can't start or queue now; "" when it can. Shown as the control's title / beside it. */
  reason: string;
  /** Off only because this is a phone (folder / whole vault): the rail says "(desktop only)". */
  desktopOnly: boolean;
}

/** The one rule for every Download control (selection bar, rail folder item, page header): may a download of `mode`
 *  (`count` files for a selection) start or queue in this browser (`sink`), with this run state and the caller's
 *  access? The run may be another Creator's (the app's one download). Folder sink: a busy run never stops it (it
 *  queues); an open picker does. Share sink: a busy run does (its name and progress), and so do files not handed to
 *  the share sheet yet (a new run would drop them). */
export function downloadGate(s: DlState, sink: DlSink | null, mode: DlMode, count: number, access: DlAccess): DlGate {
  const off = (reason: string, desktopOnly = false): DlGate => ({ reason, desktopOnly });
  if (!sink) return off(DOWNLOAD_OFF);
  if (s.picking) return off(BUSY_OFF);
  if (sink === "share" && isBusy(s)) return off(busyOff(s));
  if (unsaved(s) > 0) return off(UNSAVED_OFF);
  if (sink === "share" && mode !== "selection") return off(SHARE_MODE_OFF, true);
  if (sink === "share" && count > SHARE_MAX_ITEMS) return off(SHARE_COUNT_OFF);
  if (mode === "vault" && access !== "all") return off(RESTRICTED_OFF);
  return off("");
}

/** "A download is running: Ava · 12/40" (which run, how far). */
export function busyOff(s: DlState): string {
  return `${BUSY_OFF}: ${progressText(s)}`;
}

/** "Ava · 12/40" ("Ava · listing" before its items are known). */
export function progressText(s: DlState): string {
  const sum = summarize(s);
  return s.phase === "listing" ? `${s.creator} · listing` : `${s.creator} · ${sum.done}/${sum.total}`;
}

/** Files fetched at once for this sink. */
export function concurrencyFor(sink: DlSink): number {
  return sink === "share" ? SHARE_CONCURRENCY : CONCURRENCY;
}

/** The biggest file this sink takes (the share sink holds each file in memory). */
export function maxFileBytes(sink: DlSink): number {
  return sink === "share" ? SHARE_FILE_MAX_BYTES : Infinity;
}

/** Share sink: the first sealed batch not saved yet (the one whose Save button shows), or -1. */
export function readyBatch(s: Pick<DlState, "batches">): number {
  return s.batches.findIndex((b) => b.sealed && !b.saved);
}

/** Share sink: bytes fetched and not handed to a share sheet yet. */
export function heldBytes(s: Pick<DlState, "batches">): number {
  return s.batches.reduce((n, b) => n + (b.saved ? 0 : b.bytes), 0);
}

/** May the runner start fetching another file? Always for the folder sink (it streams to disk). */
export function canFetchMore(s: Pick<DlState, "sink" | "batches">): boolean {
  return s.sink !== "share" || heldBytes(s) < SHARE_HELD_BYTES;
}

/** Share sink: "Save 1–8" for batch `index` (positions across batches), "Save 9" for a single file. */
export function batchLabel(s: Pick<DlState, "batches">, index: number): string {
  const from = s.batches.slice(0, index).reduce((n, b) => n + b.ids.length, 0) + 1;
  const to = from + (s.batches[index]?.ids.length ?? 1) - 1;
  return to > from ? `Save ${from}–${to}` : `Save ${from}`;
}

/** Share sink: fetched files not handed to a share sheet yet (sealed or not). While any are, the panel stays and no
 *  new run starts (`holdsFiles`). */
export function unsaved(s: Pick<DlState, "batches">): number {
  return s.batches.reduce((n, b) => n + (b.saved ? 0 : b.ids.length), 0);
}

/** The panel's title, "<creator>: <label>" (the run's model: another may be on screen), from what actually
 *  happened: "Download failed" (listing or the run failed), "Nothing to download" / "Nothing saved" (no file came),
 *  "Partly …" (some item has no file: failed, stalled, cancelled or DRM). Share sink: "Ready to save" while fetched
 *  files wait for their Save tap, "Saved" only once every fetched file went to a share sheet. */
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

/** The count line: "3 of 4 saved" (folder), share: "5 of 5 ready" until tapped, then "… · 2 saved". */
export function countText(s: DlState): string {
  const sum = summarize(s);
  if (s.sink !== "share") return `${sum.done} of ${sum.total} saved`;
  const saved = s.batches.reduce((n, b) => n + (b.saved ? b.ids.length : 0), 0);
  return `${sum.done} of ${sum.total} ready${saved ? ` · ${saved} saved` : ""}`;
}

/** The items with no file, by why ("2 stalled", "1 failed", "1 DRM (no file)", "3 cancelled"; none: empty).
 *  `bad`: a fault (red); DRM and cancelled are not. */
export function outcomeParts(s: Pick<DlSummary, "failed" | "stalled" | "cancelled" | "drm">): { text: string; bad: boolean }[] {
  const out: { text: string; bad: boolean }[] = [];
  if (s.stalled) out.push({ text: `${s.stalled} stalled`, bad: true });
  if (s.failed) out.push({ text: `${s.failed} failed`, bad: true });
  if (s.drm) out.push({ text: `${s.drm} DRM (no file)`, bad: false });
  if (s.cancelled) out.push({ text: `${s.cancelled} cancelled`, bad: false });
  return out;
}

/** Where the next item's bytes come from. */
export function sourceFor(s: Pick<DlState, "directAllowed" | "directStrikes">): DlSource {
  return s.directAllowed && s.directStrikes < MAX_DIRECT_STRIKES ? "direct" : "relay";
}

/** Items Retry would fetch again (failed, stalled, cancelled; never DRM). */
export function retryable(s: Pick<DlState, "items">): number {
  return s.items.filter((i) => RETRYABLE.has(i.status)).length;
}

/** Retry is offered: the run ended with retryable items, no picker is open for a next run, and no retry job of it
 *  waits already. */
export function canRetry(s: DlState): boolean {
  return !s.picking && (s.phase === "done" || s.phase === "cancelled") && retryable(s) > 0
    && !s.jobs.some((j) => j.retryOf === s.jobId);
}

/** The run is listing or downloading. */
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

// ── Items from OF media dicts ────────────────────────────────────────

const KIND_EXT: Record<string, string> = { photo: "jpg", video: "mp4", gif: "mp4", audio: "mp3" };
const EXT_MIME: Record<string, string> = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp", heic: "image/heic",
  mp4: "video/mp4", m4v: "video/x-m4v", mov: "video/quicktime", webm: "video/webm", mp3: "audio/mpeg",
  m4a: "audio/mp4", wav: "audio/wav",
};

/** The MIME type for a file name's extension (iOS offers "Save Image/Video" only for a proper image/video type). */
export function mimeFor(name: string): string {
  const m = /\.([A-Za-z0-9]+)$/.exec(name);
  return (m && EXT_MIME[m[1].toLowerCase()]) || "application/octet-stream";
}
export const UNFILED = "Unfiled";

/** The full-quality file: `files.full.url` (photo jpg, video / gif source mp4, audio mp3). Same rule as the relay's
 *  `vault_download_api.full_url`. */
export function fullUrl(m: Pick<VaultMedia, "files">): string | null {
  const u = m.files?.full?.url;
  return typeof u === "string" && /^https?:\/\//.test(u) ? u : null;
}

/** `<mediaId>.<ext>`: the extension off the url's path, else by kind. Same rule as the relay's `file_name`. */
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

/** A folder or creator name as one path segment: no separators, control chars or reserved names, at most 80 chars. */
export function safeName(s: string): string {
  const t = s.replace(/[\u0000-\u001f<>:"/\\|?*]+/g, "_").replace(/^[\s.]+|[\s.]+$/g, "").slice(0, 80);
  return t || "_";
}

type ListState = { id?: number | string; type?: string; name?: string; hasMedia?: boolean };

/** The item's custom OF folders (`listStates`, the rule the mirror's `of_folder_ids` uses), as path segments. */
function customFolders(m: VaultMedia): string[] {
  const ls = (m as VaultMedia & { listStates?: ListState[] }).listStates ?? [];
  const names = ls.filter((l) => l.type === "custom" && l.hasMedia !== false && l.name).map((l) => safeName(l.name!));
  return [...new Set(names)];
}

/** The item's folder in the path: `folder` when one is being downloaded (or the selection was made in it), else its
 *  first custom OF folder, else UNFILED. */
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
