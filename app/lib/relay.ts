import type { ListCaller } from "@/hooks/chatListLoadMore";
import { cellMode } from "@/lib/cellFlag";
import { resolveShareToken } from "@/lib/shareToken";
import { admissible, initialSchedule, scheduleReducer, type Action as ScheduleAction } from "@/lib/relaySchedule";
import { takeInline } from "@/lib/inlineBoot";
import {
  abortable, prefetchScreen, screenJoin, screenRead, screenSettled,
} from "@/lib/screenBundle";
import { withQuery, type Screen } from "@/lib/screenKey";
import { accountOf, routeOf } from "@/lib/cellRoute";
import { fetchRenewing } from "@/lib/actorRenew";
import type { GiphyResponse } from "./relayTypes";
export type * from "./relayTypes";
export { SALARY_FREQUENCIES, toChoice } from "./relayTypes";

const RELAY_BASE = "";

export class RelayError extends Error {
  status: number;
  body: unknown;
  upstreamStatus: number | undefined;
  constructor(status: number, body: unknown, message?: string) {
    super(message || `relay ${status}`);
    this.status = status;
    this.body = body;
    const upstream = (body as { detail?: { upstream_status?: unknown } } | null)?.detail?.upstream_status;
    this.upstreamStatus = typeof upstream === "number" ? upstream : undefined;
  }
}

export function ackedFanIds(err: unknown): (number | string)[] {
  const body = err instanceof RelayError
    ? (err.body as { detail?: { upstream_body?: { acked_fan_ids?: unknown } } } | null) : null;
  const ids = body?.detail?.upstream_body?.acked_fan_ids;
  return Array.isArray(ids) ? ids.filter((f): f is number | string => typeof f === "number" || typeof f === "string") : [];
}

export interface ApiKeyErrorPayload {
  error: "api_key_missing" | "api_key_invalid" | "api_key_no_credit";
  feature: string;
  provider: string;
  fix_url: string;
  message: string;
  fix: string;
}

export const API_KEY_ERROR_EVENT = "infloww:api-key-error";

export function isApiKeyErrorPayload(v: unknown): v is ApiKeyErrorPayload {
  if (!v || typeof v !== "object") return false;
  const e = (v as Record<string, unknown>).error;
  return typeof e === "string" && e.startsWith("api_key_") &&
    typeof (v as Record<string, unknown>).message === "string";
}

export function announceApiKeyError(payload: ApiKeyErrorPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ApiKeyErrorPayload>(API_KEY_ERROR_EVENT, { detail: payload }));
}

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
  cellAccountId?: string | null;
  cellId?: string | null;
  priority?: "user" | "background";
  unqueued?: boolean;
  maxAge?: number;
  caller?: ListCaller;
  intent?: "explicit";
  opId?: string;
  opPart?: number;
}


function buildUrl(path: string, ctx?: RelayContext, opts?: { refresh?: boolean }): string {
  const url = new URL(path, RELAY_BASE || window.location.origin);
  const tok = ctx?.shareToken ?? resolveShareToken();
  if (tok && !url.searchParams.has("t")) url.searchParams.set("t", tok);
  if (opts?.refresh && !url.searchParams.has("refresh")) {
    url.searchParams.set("refresh", "1");
  }
  if (ctx?.maxAge && !url.searchParams.has("max_age")) url.searchParams.set("max_age", String(ctx.maxAge));
  return url.pathname + url.search;
}

function buildHeaders(cells: boolean, init?: RequestInit, ctx?: RelayContext): Headers {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (ctx?.employeeId != null) headers.set("X-Employee-Id", String(ctx.employeeId));
  if (ctx?.accountId) headers.set("X-Account-Id", String(ctx.accountId));
  if (cells && ctx?.cellAccountId && !ctx.accountId) headers.set("X-Account-Id", ctx.cellAccountId);
  if (ctx?.cellId) headers.set("X-Cell-Id", ctx.cellId);
  if (ctx?.priority === "background") headers.set("X-Priority", "background");
  if (ctx?.caller) headers.set("X-List-Caller", ctx.caller);
  if (ctx?.intent) headers.set("X-List-Intent", ctx.intent);
  if (ctx?.opId) headers.set("X-Op-Id", ctx.opId);
  if (ctx?.opId && ctx.opPart) headers.set("X-Op-Part", String(ctx.opPart));
  // FormData: the browser must set Content-Type itself for the multipart boundary.
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function parseResponse<T>(r: Response): Promise<T> {
  const text = await r.text();
  let body: unknown = text;
  if (text) {
    try { body = JSON.parse(text); } catch { }
  }
  if (!r.ok) {
    const rawDetail =
      (typeof body === "object" && body && "detail" in body && (body as Record<string, unknown>).detail) ||
      text || `HTTP ${r.status}`;
    if (isApiKeyErrorPayload(rawDetail)) {
      announceApiKeyError(rawDetail);
      throw new ApiKeyError(r.status, body, rawDetail);
    }
    let detail: string;
    if (typeof rawDetail === "string") detail = rawDetail;
    else if (rawDetail && typeof rawDetail === "object") {
      const d = rawDetail as Record<string, unknown>;
      if (typeof d.upstream_status === "number" && typeof d.upstream_body === "string") {
        detail = `upstream ${d.upstream_status}: ${String(d.upstream_body).slice(0, 200)}`;
      } else if (typeof d.error === "string" && typeof d.message === "string") {
        detail = d.message;
      } else if (Array.isArray(rawDetail)) {
        // FastAPI `detail` can be an object/array: String(obj) gives "[object Object]", so flatten to JSON.
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

export function describeLoadError(
  error: { message?: string } | null | undefined,
  notFound = "OnlyFans no longer has this.",
): string {
  const raw = error?.message || "";
  if (isRateLimited(error)) return "OnlyFans is busy. Try again shortly.";
  if (/User not found/i.test(raw) || /upstream 404/.test(raw)) return notFound;
  if (/proxy_unreachable|network/i.test(raw)) return "Can't reach OnlyFans right now.";
  if (/timeout/i.test(raw)) return "OnlyFans timed out.";
  if (/upstream 401|upstream 403/.test(raw)) return "This account's OnlyFans session expired.";
  const said = /^upstream \S+: \{.*?"message":"([^"]+)"/.exec(raw)?.[1];
  return `Couldn't refresh: ${said || raw || "unknown error"}`;
}

export function isRateLimited(error: unknown): boolean {
  return error instanceof RelayError && (error.status === 429 || error.upstreamStatus === 429);
}

export function isDeepRefused(error: unknown): boolean {
  return error instanceof RelayError && error.status === 428;
}

export function chatListRetry(failures: number, error: unknown): boolean {
  return failures < 1 && !isDeepRefused(error) && !isRateLimited(error);
}

export const STALE_CELL_GEN_EVENT = "infloww:stale-cell-gen";

const cellGens = new Map<string, string>();
const fenced = new Map<string, RelayError>();

export function resetCellGens(): void {
  cellGens.clear();
  fenced.clear();
}

function routed(url: string, headers: Headers, method: string, cells: boolean): string | null {
  const account = accountOf(url, headers);
  if (cells && routeOf(url, headers, method) === null) {
    throw new RelayError(400, { detail: { error: "account_required", path: url } },
      `account_required: ${method} ${url.split("?")[0]} names no Creator or Cell`);
  }
  const write = method !== "GET" && method !== "HEAD";
  const fence = cells && account && write ? fenced.get(account) : undefined;
  if (fence) throw fence;
  const gen = account && write ? cellGens.get(account) : undefined;
  if (gen && !headers.has("X-Cell-Gen")) headers.set("X-Cell-Gen", gen);
  return account;
}

export function nextGen(known: string | undefined, header: string | null, phase: "ok" | "stale"): string | undefined {
  return phase === "stale" ? header || undefined : known ?? (header || undefined);
}

function learnCellGen(account: string | null, r: Response, cells: boolean, phase: "ok" | "stale" = "ok"): void {
  if (!account) return;
  const header = r.headers.get("X-Cell-Gen");
  const gen = nextGen(cells ? cellGens.get(account) : undefined, header, phase);
  if (gen) cellGens.set(account, gen);
  else if (phase === "stale") cellGens.delete(account);
}

async function cellAware<T>(url: string, account: string | null, r: Response, cells: boolean, readFence?: RelayError): Promise<T> {
  if (!cells) learnCellGen(account, r, cells);
  try {
    const value = await parseResponse<T>(r);
    if (cells) learnCellGen(account, r, cells);
    if (account && readFence && fenced.get(account) === readFence) fenced.delete(account);
    return value;
  } catch (e) {
    if (!(e instanceof RelayError)) throw e;
    const d = e.body as { detail?: { error?: unknown } } | null;
    const error = d?.detail?.error;
    const stale = e.status === 409 && error === "stale_cell_gen";
    const reason = stale ? "stale" : e.status === 409 && error === "not_owner" ? "not_owner"
      : e.status === 401 && error === "actor_stale" && !url.startsWith("/auth/") ? "actor_stale" : null;
    if (cells && stale && account) {
      fenced.set(account, e);
      learnCellGen(account, r, cells, "stale");
    }
    if (typeof window !== "undefined" && ((cells && reason) || (stale && account))) {
      window.dispatchEvent(new CustomEvent(STALE_CELL_GEN_EVENT, {
        detail: cells ? { accountId: account, reason } : { accountId: account },
      }));
    }
    throw e;
  }
}

let schedule = initialSchedule;
let nextJobId = 1;
const admitted = new Map<number, () => void>();

function dispatchSchedule(a: ScheduleAction): void {
  schedule = scheduleReducer(schedule, a);
  const ids = admissible(schedule);
  if (!ids.length) return;
  schedule = scheduleReducer(schedule, { type: "start", ids });
  for (const id of ids) { admitted.get(id)?.(); admitted.delete(id); }
}

function admitBackground(accountId: string | null, signal: AbortSignal | null | undefined, screen: boolean): Promise<() => void> {
  signal?.throwIfAborted();
  const id = nextJobId++;
  const release = () => dispatchSchedule({ type: "done", id });
  return new Promise((resolve, reject) => {
    const onAbort = () => { admitted.delete(id); release(); reject(signal!.reason); };
    admitted.set(id, () => { signal?.removeEventListener("abort", onAbort); resolve(release); });
    signal?.addEventListener("abort", onAbort, { once: true });
    dispatchSchedule({ type: "enqueue", job: { id, accountId, screen } });
  });
}

export function setRelayFocus(accountId: string | null): void {
  dispatchSchedule({ type: "focus", accountId });
}

export function relayFocus(): string | null {
  return schedule.focus;
}

type NetInfo = EventTarget & { effectiveType?: string; saveData?: boolean };
if (typeof navigator !== "undefined") {
  const conn = (navigator as Navigator & { connection?: NetInfo }).connection;
  if (conn) {
    const read = () => dispatchSchedule({ type: "net", effectiveType: conn.effectiveType, saveData: conn.saveData });
    read();
    conn.addEventListener?.("change", read);
  }
}

const FETCH_PRIORITY = (() => {
  let read = false;
  try {
    // Chromium reads `priority` from the init but has no Request.prototype.priority: probe the read.
    new Request("data:,", { get priority() { read = true; return "low"; } } as RequestInit);
  } catch { }
  return read;
})();

export async function request<T = unknown>(
  path: string,
  init?: RequestInit,
  ctx?: RelayContext,
  opts?: { refresh?: boolean },
): Promise<T> {
  const url = buildUrl(path, ctx, opts);
  const cells = cellMode();
  const headers = buildHeaders(cells, init, ctx);
  const method = (init?.method ?? "GET").toUpperCase();
  const account = routed(url, headers, method, cells);
  const readFence = cells && account && method === "GET" ? fenced.get(account) : undefined;
  // Creator-scoped calls share a URL, and Chrome's per-URL cache lock serialises parallel GETs (measured 20 calls: 4.2 s vs 0.29 s); no-store skips the lock.
  const scoped = headers.has("X-Account-Id");
  const cache = scoped ? "no-store" : undefined;
  const local = method === "GET" && !headers.has("X-Employee-Id");
  const read = local && ctx?.intent !== "explicit" && !cells ? screenRead(url, ctx?.accountId ?? null) : null;
  if (read) {
    const o = await screenJoin(read, (p, ms) => bundleGet(p, ms, ctx?.caller), init?.signal);
    if (o.kind === "body") return o.body as T;
    if (o.kind === "error") {
      return parseResponse<T>(new Response(JSON.stringify({ detail: o.detail }), { status: o.status }));
    }
  }
  const inline = local && !scoped ? takeInline(url) : null;
  const answered = inline && await abortable(inline, init?.signal);
  if (answered) return parseResponse<T>(answered);
  const background = ctx?.priority === "background";
  const bgRead = background && !ctx?.unqueued && url.startsWith("/api/of/") && method === "GET";
  if (bgRead) await screenSettled(init?.signal);
  const release = bgRead ? await admitBackground(ctx?.accountId ?? null, init?.signal, read != null) : null;
  try {
    const priority = FETCH_PRIORITY ? { priority: background ? "low" : "high" } as RequestInit : undefined;
    const send = cells ? fetchRenewing : fetch;
    return await cellAware<T>(url, account, await send(url, { cache, ...priority, ...init, headers, credentials: "same-origin" }), cells, readFence);
  } finally {
    release?.();
  }
}

function bundleGet(p: string, timeoutMs: number, caller?: ListCaller): Promise<unknown> {
  const f = relayFocus();
  return request(
    f ? withQuery(p, { focus: f }) : p, { method: "GET", signal: AbortSignal.timeout(timeoutMs) }, { caller },
  ).then(
    (body) => { dispatchSchedule({ type: "reserve", on: false }); return body; },
    (e: unknown) => { dispatchSchedule({ type: "reserve", on: true }); throw e; },
  );
}

export function prefetchScreenBundle(s: Screen): Promise<unknown> {
  if (cellMode() && s.kind !== "chat") return Promise.resolve(null);
  return prefetchScreen(s, bundleGet);
}

export async function relayFile(path: string, ctx?: RelayContext, body?: unknown): Promise<{ blob: Blob; name: string | null }> {
  const init: RequestInit = body === undefined ? {} : { method: "POST", body: JSON.stringify(body) };
  const url = buildUrl(path, ctx);
  const cells = cellMode();
  const headers = buildHeaders(cells, { ...init, headers: { Accept: "*/*" } }, ctx);
  const account = routed(url, headers, init.method ?? "GET", cells);
  const send = cells ? fetchRenewing : fetch;
  const r = await send(url, { ...init, headers, credentials: "same-origin" });
  if (!r.ok) return cellAware<never>(url, account, r, cells);
  learnCellGen(account, r, cells);
  if (/json/i.test(r.headers.get("content-type") ?? "")) throw new RelayError(r.status, await r.text(), "no file in the answer");
  const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? null;
  return { blob: await r.blob(), name: name && decodeURIComponent(name) };
}

export const relay = {
  get<T = unknown>(
    path: string,
    ctx?: RelayContext,
    signal?: AbortSignal,
    opts?: { refresh?: boolean },
  ): Promise<T> {
    return request<T>(path, { method: "GET", signal }, ctx, opts);
  },
  uploadFile<T = unknown>(
    path: string, file: File, fieldName = "file", ctx?: RelayContext, signal?: AbortSignal,
  ): Promise<T> {
    const form = new FormData();
    form.append(fieldName, file, file.name);
    return request<T>(path, { method: "POST", body: form, signal }, ctx);
  },
  uploadForm<T = unknown>(path: string, form: FormData, ctx?: RelayContext): Promise<T> {
    return request<T>(path, { method: "POST", body: form }, ctx);
  },
  post<T = unknown>(path: string, body?: unknown, ctx?: RelayContext, signal?: AbortSignal): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: body == null ? undefined : JSON.stringify(body),
      signal,
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
