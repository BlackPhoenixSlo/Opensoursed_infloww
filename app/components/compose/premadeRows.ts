/**
 * premadeRows — PremadeForm's repeating rows: the Row shape, one reducer, and
 * the pure row ⇄ payload mapping the component only calls.
 *
 *   • `rowsReducer` is the form's one state and owns every row edit (patch,
 *     audience chips, reset). One rule = one post / message, its only clock the
 *     rule's "Run every": no add/remove, no delay, no resend (an older list or
 *     timer is edited in Raw JSON, readyMadeContent `isLegacy`).
 *   • `rowToItem` takes the `kind` explicitly.
 *   • `buildPayload` is the ONE `{posts|messages:[…]}` payload "Use in rule"
 *     stores: rows with no text and no media are dropped.
 *   • `payloadToRows` / `itemToRow` are the inverse (Re-compose seeds the form).
 */

import { SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import type { VaultMedia } from "@/lib/relay";

export type Kind = "auto_posts" | "mass_premade";

/** Each kind's payload list: `{posts:[…]}` | `{messages:[…]}`. */
export const LIST_KEY: Record<Kind, "posts" | "messages"> = { auto_posts: "posts", mass_premade: "messages" };

/** The kind's own list in `payload` (`posts` | `messages`); not an array → `[]`. */
export function listItems(payload: Record<string, unknown> | undefined, kind: Kind): unknown[] {
  const arr = payload?.[LIST_KEY[kind]];
  return Array.isArray(arr) ? arr : [];
}

const SYSTEM_IDS = new Set(SYSTEM_AUDIENCES.map((a) => a.id));

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
  // auto_posts
  hoursToLive: string;
  // PPV price in DOLLARS ("" / "0" = free; >0 = paywalled). Applies to BOTH
  // kinds — auto_posts (→ create_post) and mass_premade (→ send_mass_message);
  // a PPV post/message needs ≥1 image. Sent as `price`, stored as price_cents.
  price: string;
  // mass_premade
  onlineOnly: boolean;
  unsendAfterHours: string;
  // mass_premade audience (Mass Online parity). `includes` holds a mix of
  // system-audience ids ('fans'/'following') and custom-list ids, `excludes`
  // custom-list ids only (OF drops a built-in name in `excludedLists`,
  // fanLists.tsx) — they go to OF as `user_lists` / `excluded_user_lists`. The hour/limit knobs resolve
  // server-side via audiences.resolve_mass_audience (DB-sourced fan ids).
  includes: string[];
  excludes: string[];
  excludeLastChatHours: string; // → exclude_last_chat_hours (we OR they messaged; "Skip fans chatted with")
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
    hoursToLive: "",
    price: "",
    onlineOnly: true,
    unsendAfterHours: "",
    // Default audience mirrors Mass Online: fans + following both included.
    includes: ["fans", "following"],
    excludes: [],
    // A new Auto Mass doesn't interrupt live chats (a saved one re-seeds its own value, itemToRow).
    excludeLastChatHours: "1",
    excludeRepliedHours: "",
    excludeInboundHours: "",
    unreadLimit: "",
    recentChatHours: "",
    recentChatLimit: "",
  };
}

export type RowsAction =
  | { type: "patch"; i: number; patch: Partial<Row> }
  // Per-row audience toggles (mass_premade), the same UX as Mass Online: a system
  // chip is include-only (toggleListInclude; OF drops a built-in name in
  // `excludedLists`); a custom list is included or excluded, never both.
  | { type: "toggleListInclude"; i: number; id: string }
  | { type: "toggleListExclude"; i: number; id: string }
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

export interface RowCtx {
  kind: Kind;
}

/** Build the per-item payload entry from a row, dropping unset knobs. The
 *  text/image POOLS go to the backend, which randomises per fire. */
export function rowToItem(r: Row, { kind }: RowCtx): Record<string, unknown> {
  const posts = kind === "auto_posts";
  const media = r.media.map((m) => m.id).filter((id): id is number => typeof id === "number");
  const texts = r.texts.map((t) => t.trim()).filter(Boolean);
  const item: Record<string, unknown> = {};
  // One variant → a plain `text`; many → a `texts` pool (random per fire).
  if (texts.length === 1) item.text = texts[0];
  else if (texts.length > 1) item.texts = texts;
  const folderId = r.folderId ? Number(r.folderId) : null;
  if (media.length) item.media_files = media;        // pre-picked pool
  if (folderId) item.media_folder_id = folderId;     // whole-folder pool
  if (media.length || folderId) {
    const mc = posNum(r.mediaCount);
    if (mc) item.media_count = Math.floor(mc);       // sampled per fire (default 1)
  }
  // PPV price (dollars) — BOTH kinds support it (auto_posts→create_post,
  // mass_premade→send_mass_message both read `price`). Only emit when >0 so a
  // free post/message drops the knob entirely (matches the backend's
  // `price or 0` default).
  const price = Number(r.price);
  if (Number.isFinite(price) && price > 0) item.price = price;
  // Free-preview pool (auto_posts + PAID only) — its picks become free teasers
  // on the paywalled post. Backend unions them into media_files so previews are
  // always a valid subset.
  if (posts && Number.isFinite(price) && price > 0) {
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
    // Audience (Mass Online parity): system + custom list ids → user_lists /
    // excluded_user_lists; the hour/limit knobs resolve server-side.
    if (r.includes.length) item.user_lists = r.includes;
    if (r.excludes.length) item.excluded_user_lists = r.excludes;
    const elc = posNum(r.excludeLastChatHours);
    if (elc) item.exclude_last_chat_hours = elc;
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

/** The payload's items: a row needs text or media. */
export function rowsToItems(rows: Row[], ctx: RowCtx): Record<string, unknown>[] {
  return rows
    .map((r) => rowToItem(r, ctx))
    .filter((it) => !!it.text || Array.isArray(it.texts)
      || Array.isArray(it.media_files) || it.media_folder_id != null);
}

export type PremadePayload = {
  posts?: Record<string, unknown>[];
  messages?: Record<string, unknown>[];
};

/** The `{posts|messages:[one]}` payload — null if no usable row. A rule stores its own dry-run knob. */
export function buildPayload(rows: Row[], ctx: RowCtx): PremadePayload | null {
  const items = rowsToItems(rows, ctx);
  return items.length === 0 ? null : { [LIST_KEY[ctx.kind]]: items };
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
  // auto_posts
  r.hoursToLive = numStr(it.hours_to_live);
  r.price = numStr(it.price);
  // mass_premade — online_only is only persisted when true, so absence = off.
  r.onlineOnly = Boolean(it.online_only);
  r.unsendAfterHours = numStr(it.unsend_after_hours);
  r.includes = Array.isArray(it.user_lists) ? (it.user_lists as unknown[]).map(String) : [];
  // A built-in name saved in `excluded_user_lists` (the old tri-state chip) excluded nobody (OF drops it): not carried.
  r.excludes = Array.isArray(it.excluded_user_lists)
    ? (it.excluded_user_lists as unknown[]).map(String).filter((id) => !SYSTEM_IDS.has(id))
    : [];
  r.excludeLastChatHours = numStr(it.exclude_last_chat_hours);
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
  const arr = listItems(payload, kind);
  if (arr.length === 0) return [blankRow()];
  return arr.map((it) => itemToRow((it ?? {}) as Record<string, unknown>));
}

/** "Skip fans chatted with in last" chips (hours; "" = Off). A saved value off
 *  the presets gets its own chip so the form shows what the rule does. */
export const LAST_CHAT_PRESETS = ["", "1", "3", "8", "24"];

export function lastChatChips(hours: string): { value: string; options: { value: string; label: string }[] } {
  const n = posNum(hours);
  const value = n ? String(n) : "";
  const vals = LAST_CHAT_PRESETS.includes(value) ? LAST_CHAT_PRESETS
    : [...LAST_CHAT_PRESETS, value].sort((a, b) => Number(a) - Number(b));
  return { value, options: vals.map((v) => ({ value: v, label: v ? `${v}h` : "Off" })) };
}

/** A mass row uses an advanced "More settings" knob (opens that disclosure on edit). */
export function hasMoreAudience(r: Row): boolean {
  return [r.excludeRepliedHours, r.excludeInboundHours, r.recentChatHours, r.recentChatLimit, r.unreadLimit]
    .some((v) => v.trim() !== "");
}
