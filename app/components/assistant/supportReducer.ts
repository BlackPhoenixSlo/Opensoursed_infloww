export type SupportFrom = "me" | "support";

export interface SupportPhoto {
  id: number;
  w: number;
  h: number;
}

export interface SupportMessage {
  id: number;
  from: SupportFrom;
  text: string;
  at: string;
  photos: SupportPhoto[];
}

export interface PendingPhoto {
  key: string;
  blob: Blob;
  url: string;
}

export interface SupportStatus {
  configured: boolean;
  unread: number;
}

export const NO_SUPPORT: SupportStatus = { configured: false, unread: 0 };
export const SUPPORT_POLL_MS = 60_000;
export const SUPPORT_THREAD_POLL_MS = 4_000;
export const MAX_SUPPORT_PHOTOS = 4;
export const SUPPORT_PHOTO_SIDE = 2048;
export const MAX_SUPPORT_CHARS = 4000;
export const MAX_SUPPORT_MESSAGES = 500;
export const SUPPORT_FALLBACK_ERROR = "Couldn't reach Support — try again soon.";

export function supportStatusOf(body: unknown): SupportStatus {
  if (!body || typeof body !== "object") return NO_SUPPORT;
  const b = body as { configured?: unknown; unread?: unknown };
  if (b.configured !== true) return NO_SUPPORT;
  const n = typeof b.unread === "number" && Number.isFinite(b.unread) && b.unread > 0 ? Math.floor(b.unread) : 0;
  return { configured: true, unread: n };
}

export function messagesOf(body: unknown): SupportMessage[] {
  const rows = body && typeof body === "object" ? (body as { messages?: unknown }).messages : undefined;
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((m) => {
    if (!m || typeof m !== "object") return [];
    const r = m as Record<string, unknown>;
    if (typeof r.id !== "number" || typeof r.text !== "string") return [];
    return [{ id: r.id, from: r.from === "support" ? "support" : "me", text: r.text, at: typeof r.at === "string" ? r.at : "",
      photos: photosOf(r.photos) }];
  });
}

function photosOf(rows: unknown): SupportPhoto[] {
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((p) => {
    if (!p || typeof p !== "object") return [];
    const r = p as Record<string, unknown>;
    if (typeof r.id !== "number" || !Number.isFinite(r.id)) return [];
    return [{ id: r.id, w: typeof r.w === "number" ? r.w : 0, h: typeof r.h === "number" ? r.h : 0 }];
  });
}

const same = (a: SupportMessage, b: SupportMessage) =>
  a.text === b.text && a.from === b.from && a.at === b.at
  && a.photos.length === b.photos.length && a.photos.every((p, i) => p.id === b.photos[i].id);

export function mergeMessages(cur: SupportMessage[], next: SupportMessage[]): SupportMessage[] {
  const byId = new Map(cur.map((m) => [m.id, m]));
  for (const m of next) {
    const o = byId.get(m.id);
    if (!o || !same(o, m)) byId.set(m.id, m);
  }
  const out = [...byId.values()].sort((a, b) => a.id - b.id).slice(-MAX_SUPPORT_MESSAGES);
  return out.length === cur.length && out.every((m, i) => m === cur[i]) ? cur : out;
}

export interface SupportState {
  phase: "loading" | "ready" | "failed";
  messages: SupportMessage[];
  photos: PendingPhoto[];
  sending: boolean;
  error: string | null;
}

export const initialSupportState: SupportState = {
  phase: "loading", messages: [], photos: [], sending: false, error: null,
};

export const TOO_MANY_PHOTOS = `Up to ${MAX_SUPPORT_PHOTOS} photos per message.`;

export type SupportAction =
  | { type: "load_started" }
  | { type: "loaded"; messages: SupportMessage[] }
  | { type: "load_failed"; error: string }
  | { type: "polled"; messages: SupportMessage[] }
  | { type: "photos_added"; photos: PendingPhoto[]; requested: number }
  | { type: "photo_removed"; key: string }
  | { type: "photo_failed"; error: string }
  | { type: "send_started" }
  | { type: "sent"; messages: SupportMessage[]; keys: string[] }
  | { type: "send_failed"; error: string };

export function supportReducer(s: SupportState, a: SupportAction): SupportState {
  switch (a.type) {
    case "load_started":
      return s.phase === "failed" ? { ...s, phase: "loading", error: null } : s;
    case "loaded":
      return { ...s, phase: "ready", messages: mergeMessages(s.messages, a.messages), error: null };
    case "polled": {
      const messages = mergeMessages(s.messages, a.messages);
      return messages === s.messages ? s : { ...s, messages };
    }
    case "load_failed":
      return { ...s, phase: s.messages.length > 0 ? "ready" : "failed", error: a.error };
    case "photos_added": {
      const room = photoRoom(s);
      const photos = a.photos.slice(0, room);
      const error = Math.max(a.requested, a.photos.length) > room ? TOO_MANY_PHOTOS : s.error;
      return photos.length === 0 && error === s.error ? s : { ...s, photos: [...s.photos, ...photos], error };
    }
    case "photo_removed":
      return { ...s, photos: s.photos.filter((p) => p.key !== a.key) };
    case "photo_failed":
      return { ...s, error: a.error };
    case "send_started":
      return s.phase !== "loading" && !s.sending ? { ...s, sending: true, error: null } : s;
    case "sent": {
      const keep = new Set(a.keys);
      return {
        ...s, phase: "ready", messages: mergeMessages(s.messages, a.messages), sending: false, error: null,
        photos: s.photos.filter((p) => !keep.has(p.key)),
      };
    }
    case "send_failed":
      return { ...s, sending: false, error: a.error };
  }
}

export function appendDraft(draft: string, add: string): string {
  const extra = add.trim();
  if (!extra) return draft;
  return (draft.trim() ? `${draft.replace(/\s+$/, "")}\n${extra}` : extra).slice(0, MAX_SUPPORT_CHARS);
}

export interface SupportEntry {
  open: boolean;
  draft: string;
}

export const initialSupportEntry: SupportEntry = { open: false, draft: "" };

export type SupportEntryAction =
  | { type: "open" }
  | { type: "close" }
  | { type: "contact"; question: string }
  | { type: "draft"; text: string }
  | { type: "sent"; text: string };

export function supportEntryReducer(s: SupportEntry, a: SupportEntryAction): SupportEntry {
  switch (a.type) {
    case "open":
      return s.open ? s : { ...s, open: true };
    case "close":
      return s.open ? { ...s, open: false } : s;
    case "contact":
      return { open: true, draft: appendDraft(s.draft, a.question) };
    case "draft":
      return s.draft === a.text ? s : { ...s, draft: a.text.slice(0, MAX_SUPPORT_CHARS) };
    case "sent":
      return s.draft.trim() === a.text ? { ...s, draft: "" } : s;
  }
}

export const photoRoom = (s: SupportState): number => Math.max(0, MAX_SUPPORT_PHOTOS - s.photos.length);

export const canSend = (s: SupportState, draft: string): boolean =>
  s.phase !== "loading" && !s.sending && (draft.trim().length > 0 || s.photos.length > 0);

export interface SupportPayload {
  text: string;
  photos: PendingPhoto[];
}

export const buildPayload = (s: SupportState, draft: string): SupportPayload => ({ text: draft.trim(), photos: s.photos });

export function droppedPhotos(before: PendingPhoto[], after: PendingPhoto[]): PendingPhoto[] {
  const kept = new Set(after.map((p) => p.key));
  return before.filter((p) => !kept.has(p.key));
}

export function errorText(e: unknown): string {
  const detail = (e as { body?: { detail?: unknown } } | null)?.body?.detail;
  return typeof detail === "string" && detail.trim() ? detail : SUPPORT_FALLBACK_ERROR;
}
