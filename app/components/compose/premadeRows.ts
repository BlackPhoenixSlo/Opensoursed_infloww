import { DEFAULT_BROADCAST_LISTS, SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import { fmtPrice } from "@/lib/format";
import type { VaultMedia } from "@/lib/relay";
import { LIST_KEY, listItems, ppvPrice, type Kind } from "./payloadRules";

export const SYSTEM_IDS: ReadonlySet<string> = new Set(SYSTEM_AUDIENCES.map((a) => a.id));

export interface Row {
  texts: string[];
  media: VaultMedia[];
  folderId: string;
  mediaCount: string;
  previewMedia: VaultMedia[];
  previewFolderId: string;
  previewCount: string;
  hoursToLive: string;
  price: string;
  onlineOnly: boolean;
  unsendAfterHours: string;
  includes: string[];
  excludes: string[];
  excludeLastChatHours: string;
  excludeRepliedHours: string;
  excludeInboundHours: string;
  unreadLimit: string;
  recentChatHours: string;
  recentChatLimit: string;
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
    // System audiences are include-only: OF drops a built-in name in `excludedLists`.
    includes: [...DEFAULT_BROADCAST_LISTS],
    excludes: [],
    excludeLastChatHours: "1",
    excludeRepliedHours: "",
    excludeInboundHours: "",
    unreadLimit: "",
    recentChatHours: "",
    recentChatLimit: "",
  };
}

export type RowAction =
  | { type: "patch"; patch: Partial<Row> }
  | { type: "toggleListInclude"; id: string }
  | { type: "toggleListExclude"; id: string };

function mutAudience(r: Row, fn: (inc: Set<string>, exc: Set<string>) => void): Row {
  const inc = new Set(r.includes);
  const exc = new Set(r.excludes);
  fn(inc, exc);
  return { ...r, includes: [...inc], excludes: [...exc] };
}

export function rowReducer(r: Row, a: RowAction): Row {
  switch (a.type) {
    case "patch":
      return { ...r, ...a.patch };
    case "toggleListInclude":
      return mutAudience(r, (inc, exc) => {
        if (inc.has(a.id)) inc.delete(a.id);
        else { inc.add(a.id); exc.delete(a.id); }
      });
    case "toggleListExclude":
      return mutAudience(r, (inc, exc) => {
        if (exc.has(a.id)) exc.delete(a.id);
        else { exc.add(a.id); inc.delete(a.id); }
      });
  }
}

export function posNum(s: string): number | undefined {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) && n > 0 ? n : undefined;
}
function nonNegInt(s: string): number | undefined {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) && n >= 0 ? Math.floor(n) : undefined;
}
function nonNeg(s: string): number | undefined {
  const n = Number(s);
  return s.trim() !== "" && Number.isFinite(n) && n >= 0 ? n : undefined;
}

export function priceLabel(v: unknown): string {
  const p = ppvPrice(v);
  return p > 0 ? fmtPrice(Math.round(p * 100)) : "Free";
}

export function customIncludes(r: Row): string[] {
  return r.includes.filter((id) => !SYSTEM_IDS.has(id));
}

export function rowToItem(r: Row, kind: Kind): Record<string, unknown> {
  const posts = kind === "auto_posts";
  const media = r.media.map((m) => m.id).filter((id): id is number => typeof id === "number");
  const texts = r.texts.map((t) => t.trim()).filter(Boolean);
  const item: Record<string, unknown> = {};
  if (texts.length === 1) item.text = texts[0];
  else if (texts.length > 1) item.texts = texts;
  const folderId = r.folderId ? Number(r.folderId) : null;
  if (media.length) item.media_files = media;
  if (folderId) item.media_folder_id = folderId;
  if (media.length || folderId) {
    const mc = posNum(r.mediaCount);
    if (mc) item.media_count = Math.floor(mc);
  }
  const price = Number(r.price);
  if (Number.isFinite(price) && price > 0) item.price = price;
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
    if (r.includes.length) item.user_lists = r.includes;
    if (r.excludes.length) item.excluded_user_lists = r.excludes;
    const elc = posNum(r.excludeLastChatHours);
    if (elc) item.exclude_last_chat_hours = elc;
    // Default-on guards (absent = 6h / 2h server-side): an explicit 0 turns them off, so 0 is sent.
    const erh = nonNeg(r.excludeRepliedHours);
    if (erh !== undefined) item.exclude_replied_hours = erh;
    const eih = nonNeg(r.excludeInboundHours);
    if (eih !== undefined) item.exclude_inbound_hours = eih;
    const ul = nonNegInt(r.unreadLimit);
    if (ul && ul > 0) item.unread_limit = ul;
    const rch = posNum(r.recentChatHours);
    if (rch) item.recent_chat_hours = rch;
    const rcl = nonNegInt(r.recentChatLimit);
    if (rcl && rcl > 0) item.recent_chat_limit = rcl;
  }
  return item;
}

export type PremadePayload = {
  posts?: Record<string, unknown>[];
  messages?: Record<string, unknown>[];
};

export function buildPayload(r: Row, kind: Kind): PremadePayload {
  return { [LIST_KEY[kind]]: [rowToItem(r, kind)] };
}

export function numStr(v: unknown): string {
  return v === undefined || v === null ? "" : String(v);
}

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
  r.hoursToLive = numStr(it.hours_to_live);
  r.price = numStr(it.price);
  r.onlineOnly = Boolean(it.online_only);
  r.unsendAfterHours = numStr(it.unsend_after_hours);
  r.includes = Array.isArray(it.user_lists) ? (it.user_lists as unknown[]).map(String) : [];
  // A built-in name in `excluded_user_lists` excluded nobody (OF drops it): not carried.
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

export function payloadToRow(payload: Record<string, unknown> | undefined, kind: Kind): Row {
  const first = listItems(payload, kind)[0];
  if (first === undefined) return blankRow();
  return itemToRow((first && typeof first === "object" ? first : {}) as Record<string, unknown>);
}

export const LAST_CHAT_PRESETS = ["", "1", "3", "8", "24"];

export function lastChatChips(hours: string): { value: string; options: { value: string; label: string }[] } {
  const n = posNum(hours);
  const value = n ? String(n) : "";
  const vals = LAST_CHAT_PRESETS.includes(value) ? LAST_CHAT_PRESETS
    : [...LAST_CHAT_PRESETS, value].sort((a, b) => Number(a) - Number(b));
  return { value, options: vals.map((v) => ({ value: v, label: v ? `${v}h` : "Off" })) };
}

export function hasMoreAudience(r: Row): boolean {
  return [r.excludeRepliedHours, r.excludeInboundHours, r.recentChatHours, r.recentChatLimit, r.unreadLimit]
    .some((v) => v.trim() !== "");
}
