/**
 * vaultDownloadReducer — Vault Pro's download (a selection, one folder, the whole vault) as a pure reducer.
 *
 * The panel only dispatches; `vaultDownload.ts` runs the queue (listing, fetch, the file sink) and dispatches what
 * happened. Each item saves to `<creator>/<folder>/<mediaId>.<ext>` and records the source that delivered it:
 * `direct` (the browser fetched OF's signed CDN url itself; only when the account has no proxy, see
 * docs/spec/vault-download.md) or `relay` (`/admin/vault-ai/download`, through the account's client).
 */

import { type VaultMedia } from "@/lib/relay";

export type DlMode = "selection" | "folder" | "vault";
export type DlSource = "direct" | "relay";
export type DlStatus = "queued" | "active" | "done" | "failed";
export type DlPhase = "idle" | "listing" | "running" | "done" | "cancelled";

export interface DlItem {
  id: number;
  kind: string;
  /** The full-quality CDN url the listing carried; null for a DRM-only video (only the relay can say why). */
  url: string | null;
  folder: string;
  name: string;
  status: DlStatus;
  source: DlSource | null;
  bytes: number;
  error: string | null;
}

export interface DlState {
  phase: DlPhase;
  mode: DlMode | null;
  /** What is being downloaded, for the panel's title ("3 selected", "Folder Beach", "Whole vault"). */
  label: string;
  creator: string;
  items: DlItem[];
  /** The account has no proxy, so its urls are signed for this machine's IP and the browser may fetch them. */
  directAllowed: boolean;
  /** Items whose direct fetch failed even after a re-sign; at MAX_DIRECT_STRIKES direct is off for this run. */
  directStrikes: number;
  /** The listing failed (folder / whole vault): why. */
  error: string | null;
}

export type Action =
  | { type: "start"; mode: DlMode; label: string; creator: string; directAllowed: boolean }
  | { type: "listed"; items: DlItem[] }
  | { type: "listFailed"; error: string }
  | { type: "itemStart"; id: number }
  | { type: "itemProgress"; id: number; bytes: number }
  | { type: "itemDone"; id: number; source: DlSource; bytes: number }
  | { type: "itemFailed"; id: number; error: string }
  | { type: "directStrike" }
  | { type: "cancel" }
  | { type: "retryFailed" }
  | { type: "close" };

/** Direct fetches that fail even after a re-sign before every later item goes through the relay. */
export const MAX_DIRECT_STRIKES = 2;
/** Files fetched at once per tab. */
export const CONCURRENCY = 3;
export const CANCELLED = "cancelled";

export const initialDownloadState: DlState = {
  phase: "idle", mode: null, label: "", creator: "", items: [], directAllowed: false, directStrikes: 0, error: null,
};

function settle(s: DlState): DlState {
  if (s.phase !== "running") return s;
  return s.items.some((i) => i.status === "queued" || i.status === "active") ? s : { ...s, phase: "done" };
}

function patch(s: DlState, id: number, f: (i: DlItem) => DlItem): DlState {
  return { ...s, items: s.items.map((i) => (i.id === id ? f(i) : i)) };
}

export function vaultDownloadReducer(s: DlState, a: Action): DlState {
  switch (a.type) {
    case "start":
      if (s.phase === "listing" || s.phase === "running") return s;   // one run at a time
      return { ...initialDownloadState, phase: "listing", mode: a.mode, label: a.label, creator: a.creator,
               directAllowed: a.directAllowed };
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
    case "itemDone":
      return settle(patch(s, a.id, (i) => (i.status === "active"
        ? { ...i, status: "done", source: a.source, bytes: a.bytes, error: null } : i)));
    case "itemFailed":
      return settle(patch(s, a.id, (i) => (i.status === "active" || i.status === "queued"
        ? { ...i, status: "failed", source: null, error: a.error } : i)));
    case "directStrike":
      return { ...s, directStrikes: s.directStrikes + 1 };
    case "cancel":
      if (s.phase !== "listing" && s.phase !== "running") return s;
      return { ...s, phase: "cancelled", items: s.items.map((i) => (i.status === "queued" || i.status === "active"
        ? { ...i, status: "failed", source: null, bytes: 0, error: CANCELLED } : i)) };
    case "retryFailed":
      if (!canRetry(s)) return s;
      return { ...s, phase: "running", items: s.items.map((i) => (i.status === "failed"
        ? { ...i, status: "queued", bytes: 0, error: null } : i)) };
    case "close":
      return s.phase === "listing" || s.phase === "running" ? s : initialDownloadState;
  }
}

/** Where the next item's bytes come from. */
export function sourceFor(s: Pick<DlState, "directAllowed" | "directStrikes">): DlSource {
  return s.directAllowed && s.directStrikes < MAX_DIRECT_STRIKES ? "direct" : "relay";
}

export function canRetry(s: DlState): boolean {
  return (s.phase === "done" || s.phase === "cancelled") && s.items.some((i) => i.status === "failed");
}

export function isBusy(s: DlState): boolean {
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

/** The item's folder in the path: `folder` when a folder is being downloaded, else its first custom OF folder
 *  (`listStates`, the rule the mirror's `of_folder_ids` uses), else UNFILED. */
export function folderOf(m: VaultMedia, folder: string | null): string {
  if (folder) return safeName(folder);
  const ls = (m as VaultMedia & { listStates?: ListState[] }).listStates ?? [];
  const first = ls.find((l) => l.type === "custom" && l.hasMedia !== false && l.name);
  return safeName(first?.name ?? UNFILED);
}

export function toItems(media: VaultMedia[], folder: string | null): DlItem[] {
  return media.map((m) => {
    const url = fullUrl(m);
    return { id: m.id, kind: m.type, url, folder: folderOf(m, folder), name: fileName(m.id, url, m.type),
             status: "queued", source: null, bytes: 0, error: null };
  });
}
