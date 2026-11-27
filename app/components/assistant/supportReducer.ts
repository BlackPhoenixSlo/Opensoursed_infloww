export type SupportFrom = "me" | "support";

export interface SupportMessage {
  id: number;
  from: SupportFrom;
  text: string;
  at: string;
}

export interface SupportStatus {
  configured: boolean;
  unread: number;
}

export const NO_SUPPORT: SupportStatus = { configured: false, unread: 0 };
export const SUPPORT_POLL_MS = 60_000;
export const MAX_SUPPORT_CHARS = 4000;
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
    return [{ id: r.id, from: r.from === "support" ? "support" : "me", text: r.text, at: typeof r.at === "string" ? r.at : "" }];
  });
}

export interface SupportState {
  phase: "loading" | "ready" | "failed";
  messages: SupportMessage[];
  draft: string;
  sending: boolean;
  error: string | null;
}

export const initialSupportState: SupportState = {
  phase: "loading", messages: [], draft: "", sending: false, error: null,
};

export type SupportAction =
  | { type: "load_started" }
  | { type: "loaded"; messages: SupportMessage[] }
  | { type: "load_failed"; error: string }
  | { type: "draft"; text: string }
  | { type: "send_started" }
  | { type: "sent"; messages: SupportMessage[] }
  | { type: "send_failed"; error: string };

export function supportReducer(s: SupportState, a: SupportAction): SupportState {
  switch (a.type) {
    case "load_started":
      return s.phase === "failed" ? { ...s, phase: "loading", error: null } : s;
    case "loaded":
      return { ...s, phase: "ready", messages: a.messages, error: null };
    case "load_failed":
      return { ...s, phase: s.messages.length > 0 ? "ready" : "failed", error: a.error };
    case "draft":
      return { ...s, draft: a.text.slice(0, MAX_SUPPORT_CHARS) };
    case "send_started":
      return canSend(s) ? { ...s, sending: true, error: null } : s;
    case "sent":
      return { ...s, phase: "ready", messages: a.messages, draft: "", sending: false, error: null };
    case "send_failed":
      return { ...s, sending: false, error: a.error };
  }
}

export const canSend = (s: SupportState): boolean =>
  s.phase !== "loading" && !s.sending && s.draft.trim().length > 0;

export const buildPayload = (s: SupportState): { text: string } => ({ text: s.draft.trim() });

export function errorText(e: unknown): string {
  const detail = (e as { body?: { detail?: unknown } } | null)?.body?.detail;
  return typeof detail === "string" && detail.trim() ? detail : SUPPORT_FALLBACK_ERROR;
}
