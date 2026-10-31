/**
 * premadeRows — PremadeForm's repeating rows: the Row shape, one reducer, and
 * the pure row ⇄ payload mapping the component only calls.
 *
 *   • `rowsReducer` owns every row edit (patch, audience chips, text-variant
 *     pool, add/remove, reset). A row and a row's text pool never drop below
 *     one entry.
 *   • `rowToItem` takes the `kind` and `allModels` explicitly: in all-models
 *     mode vault ids (images, folders, previews) and custom-list ids are
 *     per-account, so they are left out.
 *   • `buildPayload` is the ONE `{posts|messages:[…]}` payload the enqueue and
 *     "Use in rule" paths send: rows with no text and no media are dropped.
 *   • `payloadToRows` / `itemToRow` are the inverse (Re-compose seeds the form).
 */

import { mergeCaptions } from "@/lib/parseCaptions";
import type { VaultMedia } from "@/lib/relay";

export type Kind = "auto_posts" | "mass_premade";

/** OF built-in audiences usable across any account (sent as `userLists`). Same
 *  pair the Mass Online composer exposes. */
export const SYSTEM_AUDIENCES: Array<{ id: string; label: string }> = [
  { id: "fans",      label: "All fans"  },
  { id: "following", label: "Following" },
];

export interface Row {
  // Text variant POOL — one is picked at random per fire. Always ≥1 entry.
  texts: string[];
  // Image POOL (pre-picked vault media) — mediaCount are sampled per fire.
  media: VaultMedia[];
  // Vault FOLDER pool — non-DRM photos from this folder join the pool at fire
  // time (backend `media_folder_id`). "" = none. Combines with `media` above.
  folderId: string;
  mediaCount: string; // images per fire (default 1)
  // Free-preview POOL (auto_posts, PAID posts only) — its picks are added to the
  // attachment set and shown FREE as the teaser (`previews` ⊆ mediaFiles). Same
  // pool shape as the image pool above. Ignored for free posts + mass_premade.
  previewMedia: VaultMedia[];
  previewFolderId: string;
  previewCount: string; // free previews per fire (default 1)
  // shared timer
  delayMinutes: string;
  // auto_posts
  hoursToLive: string;
  // PPV price in DOLLARS ("" / "0" = free; >0 = paywalled). Applies to BOTH
  // kinds — auto_posts (→ create_post) and mass_premade (→ send_mass_message);
  // a PPV post/message needs ≥1 image. Sent as `price`, stored as price_cents.
  price: string;
  // mass_premade
  onlineOnly: boolean;
  unsendAfterHours: string;
  resendAfterHours: string;
  resendCount: string;
  // mass_premade audience (Mass Online parity). `includes`/`excludes` hold a mix
  // of system-audience ids ('fans'/'following') and custom-list ids — they go to
  // OF as `user_lists` / `excluded_user_lists`. The hour/limit knobs resolve
  // server-side via audiences.resolve_mass_audience (DB-sourced fan ids).
  includes: string[];
  excludes: string[];
  excludeRepliedHours: string; // → exclude_replied_hours (fans we replied to)
  excludeInboundHours: string; // → exclude_inbound_hours (fans who messaged us)
  unreadLimit: string;         // → unread_limit (fans with unread msgs)
  recentChatHours: string;     // → recent_chat_hours (chatted-with → include)
  recentChatLimit: string;     // → recent_chat_limit (cap the recent-chat add)
}

export function blankRow(): Row {
  return {
    texts: [""],
    media: [],
    folderId: "",
    mediaCount: "",
    previewMedia: [],
    previewFolderId: "",
    previewCount: "",
    delayMinutes: "",
    hoursToLive: "",
    price: "",
    onlineOnly: true,
    unsendAfterHours: "",
    resendAfterHours: "",
    resendCount: "",
    // Default audience mirrors Mass Online: fans + following both included.
    includes: ["fans", "following"],
    excludes: [],
    excludeRepliedHours: "",
    excludeInboundHours: "",
    unreadLimit: "",
    recentChatHours: "",
    recentChatLimit: "",
  };
}

export type RowsAction =
  | { type: "patch"; i: number; patch: Partial<Row> }
  // Per-row audience toggles (mass_premade). includes/excludes mix system ids +
  // custom-list ids, mutually exclusive per id (same UX as Mass Online).
  | { type: "cycleSystem"; i: number; id: string }
  | { type: "toggleListInclude"; i: number; id: string }
  | { type: "toggleListExclude"; i: number; id: string }
  | { type: "add" }
  | { type: "remove"; i: number }
  // Text-variant pool (one row → many text variants, random one sent).
  | { type: "patchText"; i: number; ti: number; val: string }
  | { type: "addText"; i: number }
  // Imported captions: replace a lone blank variant, else append (dupes skipped).
  | { type: "addTexts"; i: number; vals: string[] }
  | { type: "removeText"; i: number; ti: number }
  | { type: "reset" };

function mapRow(rows: Row[], i: number, fn: (r: Row) => Row): Row[] {
  return rows.map((r, idx) => (idx === i ? fn(r) : r));
}

function mutAudience(r: Row, fn: (inc: Set<string>, exc: Set<string>) => void): Row {
  const inc = new Set(r.includes);
  const exc = new Set(r.excludes);
  fn(inc, exc);
  return { ...r, includes: [...inc], excludes: [...exc] };
}

export function rowsReducer(rows: Row[], a: RowsAction): Row[] {
  switch (a.type) {
    case "patch":
      return mapRow(rows, a.i, (r) => ({ ...r, ...a.patch }));
    /** System chip tri-state: off → +include → −exclude → off. */
    case "cycleSystem":
      return mapRow(rows, a.i, (r) => mutAudience(r, (inc, exc) => {
        if (inc.has(a.id)) { inc.delete(a.id); exc.add(a.id); }
        else if (exc.has(a.id)) { exc.delete(a.id); }
        else { inc.add(a.id); }
      }));
    case "toggleListInclude":
      return mapRow(rows, a.i, (r) => mutAudience(r, (inc, exc) => {
        if (inc.has(a.id)) inc.delete(a.id);
        else { inc.add(a.id); exc.delete(a.id); }
      }));
    case "toggleListExclude":
      return mapRow(rows, a.i, (r) => mutAudience(r, (inc, exc) => {
        if (exc.has(a.id)) exc.delete(a.id);
        else { exc.add(a.id); inc.delete(a.id); }
      }));
    case "add":
      return [...rows, blankRow()];
    case "remove":
      return rows.length <= 1 ? rows : rows.filter((_, idx) => idx !== a.i);
    case "patchText":
      return mapRow(rows, a.i, (r) => ({ ...r, texts: r.texts.map((t, k) => (k === a.ti ? a.val : t)) }));
    case "addText":
      return mapRow(rows, a.i, (r) => ({ ...r, texts: [...r.texts, ""] }));
    case "addTexts":
      return mapRow(rows, a.i, (r) => ({ ...r, texts: mergeCaptions(r.texts, a.vals).pool }));
    case "removeText":
      return mapRow(rows, a.i, (r) => ({
        ...r, texts: r.texts.length <= 1 ? r.texts : r.texts.filter((_, k) => k !== a.ti),
      }));
    case "reset":
      return [blankRow()];
  }
}

/** A blank/zero/garbage string → undefined; a positive number → the number.
 *  Keeps unset knobs out of the payload so the automation treats them as
 *  "not applied" (e.g. no hours_to_live = keep the post forever). */
function posNum(s: string): number | undefined {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) && n > 0 ? n : undefined;
}
function nonNegInt(s: string): number | undefined {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) && n >= 0 ? Math.floor(n) : undefined;
}

/** Resend knobs go out as a pair (count > 0 AND hours > 0) or not at all. Used
 *  by a mass row and by the Auto Posts list-level repost cycle. */
function resendPair(countStr: string, hoursStr: string): { resend_count?: number; resend_after_hours?: number } {
  const rc = nonNegInt(countStr);
  const rah = posNum(hoursStr);
  return rc && rc > 0 && rah ? { resend_count: rc, resend_after_hours: rah } : {};
}

export interface RowCtx {
  kind: Kind;
  allModels: boolean;
}

/** Build the per-item payload entry from a row, dropping unset knobs. The
 *  text/image POOLS go to the backend, which randomises per fire. */
export function rowToItem(r: Row, { kind, allModels }: RowCtx): Record<string, unknown> {
  const posts = kind === "auto_posts";
  const media = r.media.map((m) => m.id).filter((id): id is number => typeof id === "number");
  const texts = r.texts.map((t) => t.trim()).filter(Boolean);
  const item: Record<string, unknown> = {};
  // One variant → a plain `text`; many → a `texts` pool (random per fire).
  if (texts.length === 1) item.text = texts[0];
  else if (texts.length > 1) item.texts = texts;
  // Images are per-account vault ids — omit them entirely in all-models mode.
  if (!allModels) {
    const folderId = r.folderId ? Number(r.folderId) : null;
    if (media.length) item.media_files = media;        // pre-picked pool
    if (folderId) item.media_folder_id = folderId;     // whole-folder pool
    if (media.length || folderId) {
      const mc = posNum(r.mediaCount);
      if (mc) item.media_count = Math.floor(mc);       // sampled per fire (default 1)
    }
  }
  const delay = posNum(r.delayMinutes);
  if (delay) item.delay_minutes = delay;
  // PPV price (dollars) — BOTH kinds support it (auto_posts→create_post,
  // mass_premade→send_mass_message both read `price`). Only emit when >0 so a
  // free post/message drops the knob entirely (matches the backend's
  // `price or 0` default).
  const price = Number(r.price);
  if (Number.isFinite(price) && price > 0) item.price = price;
  // Free-preview pool (auto_posts + PAID only) — its picks become free teasers
  // on the paywalled post. Backend unions them into media_files so previews are
  // always a valid subset. Per-account vault ids, so off in all-models mode.
  if (posts && !allModels && Number.isFinite(price) && price > 0) {
    const pmedia = r.previewMedia
      .map((m) => m.id)
      .filter((id): id is number => typeof id === "number");
    const pfolder = r.previewFolderId ? Number(r.previewFolderId) : null;
    if (pmedia.length) item.preview_media_files = pmedia;
    if (pfolder) item.preview_media_folder_id = pfolder;
    if (pmedia.length || pfolder) {
      const pc = posNum(r.previewCount);
      if (pc) item.preview_media_count = Math.floor(pc);
    }
  }
  if (posts) {
    const htl = posNum(r.hoursToLive);
    if (htl) item.hours_to_live = htl;
  } else {
    if (r.onlineOnly) item.online_only = true;
    const uah = posNum(r.unsendAfterHours);
    if (uah) item.unsend_after_hours = uah;
    Object.assign(item, resendPair(r.resendCount, r.resendAfterHours));
    // Audience (Mass Online parity): system + custom list ids → user_lists /
    // excluded_user_lists; the hour/limit knobs resolve server-side. In
    // all-models mode custom-list ids don't map across accounts, so keep only
    // the system audiences (fans/following).
    const sysIds = new Set(SYSTEM_AUDIENCES.map((a) => a.id));
    const inc = allModels ? r.includes.filter((id) => sysIds.has(id)) : r.includes;
    const exc = allModels ? r.excludes.filter((id) => sysIds.has(id)) : r.excludes;
    if (inc.length) item.user_lists = inc;
    if (exc.length) item.excluded_user_lists = exc;
    const erh = posNum(r.excludeRepliedHours);
    if (erh) item.exclude_replied_hours = erh;
    const eih = posNum(r.excludeInboundHours);
    if (eih) item.exclude_inbound_hours = eih;
    const ul = nonNegInt(r.unreadLimit);
    if (ul && ul > 0) item.unread_limit = ul;
    const rch = posNum(r.recentChatHours);
    if (rch) item.recent_chat_hours = rch;
    const rcl = nonNegInt(r.recentChatLimit);
    if (rcl && rcl > 0) item.recent_chat_limit = rcl;
  }
  return item;
}

/** The items both send paths use. In all-models mode media is stripped, so an
 *  item is valid on text alone. */
export function rowsToItems(rows: Row[], ctx: RowCtx): Record<string, unknown>[] {
  return rows
    .map((r) => rowToItem(r, ctx))
    .filter((it) => !!it.text || Array.isArray(it.texts)
      || Array.isArray(it.media_files) || it.media_folder_id != null);
}

/** Auto Posts repost CYCLE (list-level): re-post the whole list after it finishes. */
export interface PostsCycle {
  resendCount: string;
  resendAfterHours: string;
}

export type PremadePayload = {
  posts?: Record<string, unknown>[];
  messages?: Record<string, unknown>[];
  dry_run?: boolean;
  resend_count?: number;
  resend_after_hours?: number;
};

/** The `{posts|messages:[…]}` payload both send paths use — null if no usable
 *  row. `dryRun` is the enqueue path's only (a rule stores its own dry-run
 *  knob); the cycle rides on auto_posts only, dropped when unset. */
export function buildPayload(
  rows: Row[], cycle: PostsCycle, ctx: RowCtx, dryRun?: boolean,
): PremadePayload | null {
  const items = rowsToItems(rows, ctx);
  if (items.length === 0) return null;
  const dry = dryRun === undefined ? {} : { dry_run: dryRun };
  return ctx.kind === "auto_posts"
    ? { posts: items, ...dry, ...resendPair(cycle.resendCount, cycle.resendAfterHours) }
    : { messages: items, ...dry };
}

/** Number/anything → the string an input expects ("" when unset), the inverse
 *  of posNum/nonNegInt — used to re-seed a row from a saved payload. */
export function numStr(v: unknown): string {
  return v === undefined || v === null ? "" : String(v);
}

/** Reverse of `rowToItem` — turn one saved payload entry back into an editable
 *  Row so "Re-compose" opens pre-filled instead of blank. Media re-seeds as
 *  id-only stubs (no thumbnail until re-picked, but the ids round-trip exactly). */
export function itemToRow(it: Record<string, unknown>): Row {
  const r = blankRow();
  if (typeof it.text === "string") r.texts = [it.text];
  else if (Array.isArray(it.texts) && it.texts.length) {
    r.texts = (it.texts as unknown[]).map(String);
  }
  if (Array.isArray(it.media_files)) {
    r.media = (it.media_files as unknown[])
      .filter((id): id is number => typeof id === "number")
      .map((id) => ({ id, type: "photo" }) as VaultMedia);
  }
  r.folderId = it.media_folder_id != null ? String(it.media_folder_id) : "";
  r.mediaCount = numStr(it.media_count);
  if (Array.isArray(it.preview_media_files)) {
    r.previewMedia = (it.preview_media_files as unknown[])
      .filter((id): id is number => typeof id === "number")
      .map((id) => ({ id, type: "photo" }) as VaultMedia);
  }
  r.previewFolderId = it.preview_media_folder_id != null ? String(it.preview_media_folder_id) : "";
  r.previewCount = numStr(it.preview_media_count);
  r.delayMinutes = numStr(it.delay_minutes);
  // auto_posts
  r.hoursToLive = numStr(it.hours_to_live);
  r.price = numStr(it.price);
  // mass_premade — online_only is only persisted when true, so absence = off.
  r.onlineOnly = Boolean(it.online_only);
  r.unsendAfterHours = numStr(it.unsend_after_hours);
  r.resendAfterHours = numStr(it.resend_after_hours);
  r.resendCount = numStr(it.resend_count);
  r.includes = Array.isArray(it.user_lists) ? (it.user_lists as unknown[]).map(String) : [];
  r.excludes = Array.isArray(it.excluded_user_lists)
    ? (it.excluded_user_lists as unknown[]).map(String)
    : [];
  r.excludeRepliedHours = numStr(it.exclude_replied_hours);
  r.excludeInboundHours = numStr(it.exclude_inbound_hours);
  r.unreadLimit = numStr(it.unread_limit);
  r.recentChatHours = numStr(it.recent_chat_hours);
  r.recentChatLimit = numStr(it.recent_chat_limit);
  return r;
}

/** Seed the repeating rows from a saved `{posts|messages:[…]}` payload (the
 *  inverse of buildPayload). Empty/missing → one blank row. */
export function payloadToRows(payload: Record<string, unknown> | undefined, kind: Kind): Row[] {
  const arr = kind === "auto_posts" ? payload?.posts : payload?.messages;
  if (!Array.isArray(arr) || arr.length === 0) return [blankRow()];
  return arr.map((it) => itemToRow((it ?? {}) as Record<string, unknown>));
}
