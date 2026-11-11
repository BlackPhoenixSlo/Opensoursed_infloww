/**
 * vaultDownloadReducer — Vault Pro's download (a selection, one folder, the whole vault) as a pure reducer.
 *
 * The panel only dispatches; `vaultDownload.ts` runs the queue (listing, fetch, the file sink) and dispatches what
 * happened. Each item saves to `<creator>/<folder>/<mediaId>.<ext>` and records the source that delivered it:
 * `direct` (the browser fetched OF's signed CDN url itself; only when the account has no proxy, see
 * docs/spec/vault-download.md) or `relay` (`/admin/vault-ai/download`, through the account's client).
 *
 * Sink `folder` (desktop Chrome/Edge) writes each file into a picked folder. Sink `share` (phones: no folder picker,
 * but `navigator.share` takes files) is selection-only, at most SHARE_MAX_ITEMS: each fetched file joins the open
 * batch until SHARE_BATCH_BYTES, a sealed batch waits for the user's "Save" tap (the share sheet), and fetching holds
 * while unsaved batches reach SHARE_HELD_BYTES.
 */

import { type VaultMedia } from "@/lib/relay";

export type DlMode = "selection" | "folder" | "vault";
export type DlSource = "direct" | "relay";
export type DlStatus = "queued" | "active" | "done" | "failed";
export type DlPhase = "idle" | "listing" | "running" | "done" | "cancelled";
export type DlSink = "folder" | "share";

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

export interface DlState {
  phase: DlPhase;
  mode: DlMode | null;
  /** What is being downloaded ("3 selected", "folder Beach", "whole vault"); the title adds the creator. */
  label: string;
  /** The run's model (its id / its folder name): retry, re-sign and the links file use these, never the model on
   *  screen, which may have changed since the run started. */
  accountId: string;
  creator: string;
  items: DlItem[];
  /** The account has no proxy, so its urls are signed for this machine's IP and the browser may fetch them. */
  directAllowed: boolean;
  /** Items whose direct fetch failed even after a re-sign; at MAX_DIRECT_STRIKES direct is off for this run. */
  directStrikes: number;
  /** The listing failed (folder / whole vault): why. */
  error: string | null;
  sink: DlSink;
  /** Share sink only: the batches so far; the last may be open. */
  batches: DlBatch[];
  /** Share sink only: the links file was handed to a share sheet (vaultLinksFile.ts). */
  linksSaved: boolean;
}

export type Action =
  | { type: "start"; mode: DlMode; label: string; accountId: string; creator: string; directAllowed: boolean; sink?: DlSink }
  | { type: "listed"; items: DlItem[] }
  | { type: "listFailed"; error: string }
  | { type: "itemStart"; id: number }
  | { type: "itemProgress"; id: number; bytes: number }
  | { type: "itemDone"; id: number; source: DlSource; bytes: number }
  | { type: "itemFailed"; id: number; error: string }
  | { type: "directStrike" }
  | { type: "cancel" }
  | { type: "retryFailed" }
  | { type: "batchSaved"; index: number }
  | { type: "linksSaved" }
  | { type: "close" };

/** Direct fetches that fail even after a re-sign before every later item goes through the relay. */
export const MAX_DIRECT_STRIKES = 2;
/** Files fetched at once per tab. */
export const CONCURRENCY = 3;
export const CANCELLED = "cancelled";
/** Share sink: at most this many files per run (a selection). */
export const SHARE_MAX_ITEMS = 20;
/** Share sink: a batch fills to this many bytes; a bigger file is a batch of its own. Tune here. */
export const SHARE_BATCH_BYTES = 200 * 1024 * 1024;
/** Share sink: fetching holds while unsaved batches hold this many bytes (~2 batches in memory). */
export const SHARE_HELD_BYTES = 2 * SHARE_BATCH_BYTES;

export const DOWNLOAD_OFF = "Download needs Chrome or Edge (it saves into a folder you pick)";
export const BUSY_OFF = "A download is running";
export const UNSAVED_OFF = "Save the downloaded files first";
export const SHARE_MODE_OFF = "Phone: only a selection downloads here; folders and the whole vault need desktop Chrome or Edge";
export const SHARE_COUNT_OFF = `Phone: up to ${SHARE_MAX_ITEMS} at a time`;

export const initialDownloadState: DlState = {
  phase: "idle", mode: null, label: "", accountId: "", creator: "", items: [], directAllowed: false, directStrikes: 0, error: null,
  sink: "folder", batches: [], linksSaved: false,
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

function settle(s: DlState): DlState {
  if (s.phase !== "running") return s;
  if (s.items.some((i) => i.status === "queued" || i.status === "active")) return s;
  return { ...s, phase: "done", batches: sealBatches(s.batches) };
}

function patch(s: DlState, id: number, f: (i: DlItem) => DlItem): DlState {
  return { ...s, items: s.items.map((i) => (i.id === id ? f(i) : i)) };
}

export function vaultDownloadReducer(s: DlState, a: Action): DlState {
  switch (a.type) {
    case "start":
      if (isBusy(s)) return s;   // one run at a time
      return { ...initialDownloadState, phase: "listing", mode: a.mode, label: a.label, accountId: a.accountId,
               creator: a.creator, directAllowed: a.directAllowed, sink: a.sink ?? "folder" };
    case "listed": {
      if (s.phase !== "listing") return s;
      const seen = new Set<number>();
      const items = a.items.filter((i) => !seen.has(i.id) && (seen.add(i.id), true));
      return settle({ ...s, phase: "running", items });
    }
    case "listFailed":
      return s.phase === "listing" ? { ...s, phase: "done", error: a.error } : s;
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
      return settle(patch(s, a.id, (i) => (i.status === "active" || i.status === "queued"
        ? { ...i, status: "failed", source: null, error: a.error } : i)));
    case "directStrike":
      return { ...s, directStrikes: s.directStrikes + 1 };
    case "cancel":
      if (s.phase !== "listing" && s.phase !== "running") return s;
      return { ...s, phase: "cancelled", batches: sealBatches(s.batches),
               items: s.items.map((i) => (i.status === "queued" || i.status === "active"
                 ? { ...i, status: "failed", source: null, bytes: 0, error: CANCELLED } : i)) };
    case "retryFailed":
      if (!canRetry(s)) return s;
      return { ...s, phase: "running", items: s.items.map((i) => (i.status === "failed"
        ? { ...i, status: "queued", bytes: 0, error: null } : i)) };
    case "batchSaved": {
      const b = s.batches[a.index];
      if (!b || !b.sealed || b.saved) return s;
      return { ...s, batches: s.batches.map((x, i) => (i === a.index ? { ...x, saved: true } : x)) };
    }
    case "linksSaved":
      return s.sink === "share" && s.items.length ? { ...s, linksSaved: true } : s;
    case "close":
      return s.phase === "listing" || s.phase === "running" ? s : initialDownloadState;
  }
}

/** Why a download of `mode` (`count` files for a selection) can't start now, given the run `s`; "" when it can. A
 *  finished run with files not handed to the share sheet yet (phone) also holds the next one: a new run drops them. */
export function downloadOff(sink: DlSink | null, mode: DlMode, count: number, s: Pick<DlState, "phase" | "batches">): string {
  if (!sink) return DOWNLOAD_OFF;
  if (isBusy(s)) return BUSY_OFF;
  if (unsaved(s) > 0) return UNSAVED_OFF;
  if (sink === "share" && mode !== "selection") return SHARE_MODE_OFF;
  if (sink === "share" && count > SHARE_MAX_ITEMS) return SHARE_COUNT_OFF;
  return "";
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

/** Share sink: files fetched but not saved, after the fetch ended (the panel stays until they are). */
export function unsaved(s: Pick<DlState, "batches">): number {
  return s.batches.reduce((n, b) => n + (b.saved ? 0 : b.ids.length), 0);
}

/** The panel's title, "<creator>: <label>" (the run's model: another may be on screen). Share sink: "Ready" while
 *  fetched files wait for their Save tap, "Saved" once all are. */
export function panelTitle(s: DlState): string {
  if (!s.label) return "Download";
  const what = s.creator ? `${s.creator}: ${s.label}` : s.label;
  if (s.phase === "listing") return `Listing ${what}…`;
  if (s.phase === "running") return `Downloading ${what}`;
  if (s.phase === "cancelled") return `Cancelled: ${what}`;
  if (s.sink !== "share") return `Downloaded ${what}`;
  return unsaved(s) > 0 ? `Ready to save: ${what}` : `Saved ${what}`;
}

/** The count line: "3 of 4 saved" (folder), share: "5 of 5 ready" until tapped, then "… · 2 saved". */
export function countText(s: DlState): string {
  const sum = summarize(s);
  if (s.sink !== "share") return `${sum.done} of ${sum.total} saved`;
  const saved = s.batches.reduce((n, b) => n + (b.saved ? b.ids.length : 0), 0);
  return `${sum.done} of ${sum.total} ready${saved ? ` · ${saved} saved` : ""}`;
}

/** Where the next item's bytes come from. */
export function sourceFor(s: Pick<DlState, "directAllowed" | "directStrikes">): DlSource {
  return s.directAllowed && s.directStrikes < MAX_DIRECT_STRIKES ? "direct" : "relay";
}

export function canRetry(s: DlState): boolean {
  return (s.phase === "done" || s.phase === "cancelled") && s.items.some((i) => i.status === "failed");
}

export function isBusy(s: Pick<DlState, "phase">): boolean {
  return s.phase === "listing" || s.phase === "running";
}

export interface DlSummary { total: number; done: number; failed: number; active: number; bytes: number; direct: number; relay: number }

export function summarize(s: DlState): DlSummary {
  const out: DlSummary = { total: s.items.length, done: 0, failed: 0, active: 0, bytes: 0, direct: 0, relay: 0 };
  for (const i of s.items) {
    out.bytes += i.bytes;
    if (i.status === "done") {
      out.done += 1;
      if (i.source === "direct") out.direct += 1;
      else if (i.source === "relay") out.relay += 1;
    } else if (i.status === "failed") out.failed += 1;
    else if (i.status === "active") out.active += 1;
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
