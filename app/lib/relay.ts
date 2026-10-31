/**
 * relay.ts — typed fetch wrapper around the Python relay.
 *
 * Auto-injects:
 *   • `X-Employee-Id` from EmployeeContext (so every mutation gets audited)
 *   • `X-Account-Id` from ScopeContext when scope is a single model
 *   • `?t=<share token>` query param on every URL (relay's share-link gate)
 *
 * Returns parsed JSON for 2xx, throws `RelayError` for 4xx/5xx with the
 * upstream body attached. Callers (and React Query) get clean rejection
 * paths instead of having to inspect `.ok` themselves.
 */

import { resolveShareToken } from "@/lib/shareToken";
import type { GiphyResponse } from "./relayTypes";
export type * from "./relayTypes";
export { SALARY_FREQUENCIES, toChoice } from "./relayTypes";

const RELAY_BASE = ""; // Next rewrites front the relay; same-origin.

export class RelayError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message?: string) {
    super(message || `relay ${status}`);
    this.status = status;
    this.body = body;
  }
}

/** The relay's typed answer when an AI feature's API key is missing, empty or
 *  rejected (`llm_client.key_error_payload`, served as a 424). The relay owns
 *  every sentence here; the app shows them, it does not re-compose them. */
export interface ApiKeyErrorPayload {
  error: "api_key_missing" | "api_key_invalid" | "api_key_no_credit";
  feature: string;
  provider: string;
  fix_url: string;
  /** What is wrong — safe for anyone who can see the account. */
  message: string;
  /** What the OWNER does about it (names Settings › AI keys). */
  fix: string;
}

/** The window event every `ApiKeyError` raises — `ApiKeyToaster` listens. */
export const API_KEY_ERROR_EVENT = "infloww:api-key-error";

export function isApiKeyErrorPayload(v: unknown): v is ApiKeyErrorPayload {
  if (!v || typeof v !== "object") return false;
  const e = (v as Record<string, unknown>).error;
  return typeof e === "string" && e.startsWith("api_key_") &&
    typeof (v as Record<string, unknown>).message === "string";
}

/** Show a key error to the user (the toaster). Also what a background sweep's
 *  `key_error` snapshot is handed to, so both look the same. */
export function announceApiKeyError(payload: ApiKeyErrorPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ApiKeyErrorPayload>(API_KEY_ERROR_EVENT, { detail: payload }));
}

/** A relay call refused because an AI key is missing/empty/wrong. Its
 *  `message` is the relay's sentence, so an inline error that prints
 *  `e.message` reads right too. */
export class ApiKeyError extends RelayError {
  payload: ApiKeyErrorPayload;
  constructor(status: number, body: unknown, payload: ApiKeyErrorPayload) {
    super(status, body, payload.message);
    this.payload = payload;
  }
}

export interface RelayContext {
  shareToken?: string | null;
  employeeId?: number | null;
  accountId?: string | null;
  /** Sent as `X-Priority`. The relay reserves slots in its per-account
   *  upstream concurrency pool for "user" callers — anything tagged
   *  "background" (chat-list enrichment, periodic refresh, prefetch)
   *  may queue behind user-initiated work. Default: "user". */
  priority?: "user" | "background";
}


function buildUrl(path: string, ctx?: RelayContext, opts?: { refresh?: boolean }): string {
  const url = new URL(path, RELAY_BASE || window.location.origin);
  const tok = ctx?.shareToken ?? resolveShareToken();
  if (tok && !url.searchParams.has("t")) url.searchParams.set("t", tok);
  // Stage C backend caches honour `?refresh=1` as a per-request bypass.
  // Refresh-affordances on the frontend (Refresh Inbox, settings refresh,
  // etc.) pass `{ refresh: true }` to force the next call past the cache.
  if (opts?.refresh && !url.searchParams.has("refresh")) {
    url.searchParams.set("refresh", "1");
  }
  return url.pathname + url.search;
}

function buildHeaders(init?: RequestInit, ctx?: RelayContext): Headers {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (ctx?.employeeId != null) headers.set("X-Employee-Id", String(ctx.employeeId));
  if (ctx?.accountId) headers.set("X-Account-Id", String(ctx.accountId));
  if (ctx?.priority === "background") headers.set("X-Priority", "background");
  // Only set content-type for JSON bodies. For FormData the browser
  // needs to set Content-Type itself so it can include the multipart
  // boundary — overriding here would corrupt the upload.
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function parseResponse<T>(r: Response): Promise<T> {
  const text = await r.text();
  let body: unknown = text;
  if (text) {
    try { body = JSON.parse(text); } catch { /* keep as text */ }
  }
  if (!r.ok) {
    const rawDetail =
      (typeof body === "object" && body && "detail" in body && (body as Record<string, unknown>).detail) ||
      text || `HTTP ${r.status}`;
    if (isApiKeyErrorPayload(rawDetail)) {
      announceApiKeyError(rawDetail);
      throw new ApiKeyError(r.status, body, rawDetail);
    }
    // FastAPI returns `detail` as an object/array for upstream proxy
    // errors (`{upstream_status, upstream_body}`) and validation errors
    // (list of {loc, msg, type}). `String(obj)` yields "[object Object]"
    // which surfaces as an unreadable error chip — flatten to JSON instead.
    let detail: string;
    if (typeof rawDetail === "string") detail = rawDetail;
    else if (rawDetail && typeof rawDetail === "object") {
      const d = rawDetail as Record<string, unknown>;
      if (typeof d.upstream_status === "number" && typeof d.upstream_body === "string") {
        detail = `upstream ${d.upstream_status}: ${String(d.upstream_body).slice(0, 200)}`;
      } else if (typeof d.error === "string" && typeof d.message === "string") {
        // A typed refusal (`{error, message}`, e.g. the clock's): its sentence.
        detail = d.message;
      } else if (Array.isArray(rawDetail)) {
        detail = rawDetail.map((e) => {
          if (e && typeof e === "object" && "msg" in (e as Record<string, unknown>)) {
            return String((e as Record<string, unknown>).msg);
          }
          return JSON.stringify(e);
        }).join("; ");
      } else {
        try { detail = JSON.stringify(rawDetail); } catch { detail = `HTTP ${r.status}`; }
      }
    } else {
      detail = `HTTP ${r.status}`;
    }
    throw new RelayError(r.status, body, detail);
  }
  return body as T;
}

/**
 * Turn one of the error strings built above into a line an operator can act on.
 *
 * It lives HERE, next to the code that formats `upstream <status>: <body>`,
 * because the two have to agree on that shape — a humaniser parked in one
 * component drifts the moment this formatter changes, and every other error
 * surface keeps printing the raw blob.
 *
 * What the operator actually sees today is the upstream body verbatim:
 * `upstream 404: {"error":{"code":0,"message":"User not found"}}` — which reads
 * like a crash and buries the only fact that matters. The permanent case is
 * separated from the transient ones on purpose: "retry" is the right instinct
 * for a timeout and a waste of time on a 404.
 */
export function describeLoadError(
  error: { message?: string } | null | undefined,
  /** What a 404 means HERE. The generic default is deliberate: only the caller
   *  knows whether the missing thing is a fan, a thread or a vault list, and
   *  "this fan's account no longer exists" is simply false on a list query. */
  notFound = "OnlyFans no longer has this.",
): string {
  const raw = error?.message || "";
  if (/User not found/i.test(raw) || /upstream 404/.test(raw)) return notFound;
  if (/proxy_unreachable|network/i.test(raw)) return "Can't reach OnlyFans right now.";
  if (/timeout/i.test(raw)) return "OnlyFans timed out.";
  if (/upstream 401|upstream 403/.test(raw)) return "This account's OnlyFans session expired.";
  return `Couldn't refresh: ${raw || "unknown error"}`;
}

/**
 * Core fetch wrapper. Most callers use the verb helpers (get/post/patch/delete)
 * but `request()` is here for the long tail of mixed verbs / streaming bodies.
 *
 * `opts.refresh=true` appends `?refresh=1` so Stage C backend caches bypass.
 */
export async function request<T = unknown>(
  path: string,
  init?: RequestInit,
  ctx?: RelayContext,
  opts?: { refresh?: boolean },
): Promise<T> {
  const url = buildUrl(path, ctx, opts);
  const headers = buildHeaders(init, ctx);
  // A Creator-scoped call (`X-Account-Id`) shares its URL with every other
  // Creator's call, so the browser HTTP cache cannot tell them apart — and
  // Chrome holds a per-URL cache lock: N parallel GETs of the same URL run one
  // after another, each waiting for the previous one's headers. The shell's
  // per-Creator `users/me` (one per Creator) and Messages Pro's per-Creator
  // chats/notifications reads paid one round trip per Creator for it —
  // measured 20 calls = 4.2 s serial vs 0.29 s with `no-store` in Chromium
  // (Safari/WebKit runs them in parallel either way). `no-store` skips the
  // cache, so the lock is never taken. Unscoped calls keep the browser's
  // default. A caller's own `init.cache` wins.
  const cache = headers.has("X-Account-Id") ? "no-store" : undefined;
  const r = await fetch(url, { cache, ...init, headers, credentials: "same-origin" });
  return parseResponse<T>(r);
}


/** A GET answered with a file (a payout invoice), or a POST of JSON `body` (the reports' Excel export): its bytes
 *  and name. Errors as `RelayError`; a JSON answer (no file) is an error too, as the caller cannot save it. */
export async function relayFile(path: string, ctx?: RelayContext, body?: unknown): Promise<{ blob: Blob; name: string | null }> {
  const init: RequestInit = body === undefined ? {} : { method: "POST", body: JSON.stringify(body) };
  const r = await fetch(buildUrl(path, ctx), {
    ...init, headers: buildHeaders({ ...init, headers: { Accept: "*/*" } }, ctx), credentials: "same-origin",
  });
  if (!r.ok) return parseResponse<never>(r);
  if (/json/i.test(r.headers.get("content-type") ?? "")) throw new RelayError(r.status, await r.text(), "no file in the answer");
  const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? null;
  return { blob: await r.blob(), name: name && decodeURIComponent(name) };
}

export const relay = {
  /** `opts.refresh=true` appends `?refresh=1` to bust Stage C backend
   *  caches (list_chats / init / notifications_count / my_settings /
   *  get_messages_tail / tagged_friend_users). Use for Refresh-inbox
   *  buttons and similar user-driven "force fresh" affordances. */
  get<T = unknown>(
    path: string,
    ctx?: RelayContext,
    signal?: AbortSignal,
    opts?: { refresh?: boolean },
  ): Promise<T> {
    return request<T>(path, { method: "GET", signal }, ctx, opts);
  },
  /** Multipart POST — caller hands us the File; we wrap it in FormData
   *  and skip the default JSON Content-Type so the browser can set the
   *  multipart boundary. */
  uploadFile<T = unknown>(
    path: string, file: File, fieldName = "file", ctx?: RelayContext, signal?: AbortSignal,
  ): Promise<T> {
    const form = new FormData();
    form.append(fieldName, file, file.name);
    return request<T>(path, { method: "POST", body: form, signal }, ctx);
  },
  /** Multipart POST of a FormData the caller assembled — several files, or
   *  files mixed with text fields. `uploadFile` covers the single-file case;
   *  this is for routes like the vault import that take both. */
  uploadForm<T = unknown>(path: string, form: FormData, ctx?: RelayContext): Promise<T> {
    return request<T>(path, { method: "POST", body: form }, ctx);
  },
  post<T = unknown>(path: string, body?: unknown, ctx?: RelayContext): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: body == null ? undefined : JSON.stringify(body),
    }, ctx);
  },
  patch<T = unknown>(path: string, body?: unknown, ctx?: RelayContext): Promise<T> {
    return request<T>(path, {
      method: "PATCH",
      body: body == null ? undefined : JSON.stringify(body),
    }, ctx);
  },
  put<T = unknown>(path: string, body?: unknown, ctx?: RelayContext): Promise<T> {
    return request<T>(path, {
      method: "PUT",
      body: body == null ? undefined : JSON.stringify(body),
    }, ctx);
  },
  delete<T = unknown>(path: string, ctx?: RelayContext, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "DELETE",
      body: body == null ? undefined : JSON.stringify(body),
    }, ctx);
  },
};

export function gifTrending(
  limit = 20, offset = 0, ctx?: RelayContext, signal?: AbortSignal,
): Promise<GiphyResponse> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return relay.get<GiphyResponse>(`/api/of/v2/giphy/proxy/gifs/trending?${qs}`, ctx, signal);
}

export function gifSearch(
  q: string, limit = 20, offset = 0, ctx?: RelayContext, signal?: AbortSignal,
): Promise<GiphyResponse> {
  const qs = new URLSearchParams({ q, limit: String(limit), offset: String(offset) });
  return relay.get<GiphyResponse>(`/api/of/v2/giphy/proxy/gifs/search?${qs}`, ctx, signal);
}
