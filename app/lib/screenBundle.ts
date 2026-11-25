import { useEffect, useRef } from "react";

import { bundlePath, screenKey, withQuery, type ChatLack, type Screen } from "@/lib/screenKey";

export const SEED_PAGE = 30;
export const ATTRIBUTION_LIMIT = 200;

export const CHATS_PAGE = 25;
// A write does not expire a landed bundle: a chat open fires its own writes while its bundle lands and later reads must still join it.
export const KEEP_MS = 2_000;
export const FOLLOW_MS = 250;
export const FOLLOW_DEADLINE_MS = 15_000;
const TIMEOUT_MARGIN_MS = 6_000;
export const BUNDLE_TIMEOUT_MS = 2_000 + TIMEOUT_MARGIN_MS;
export const FOLLOW_TIMEOUT_MS = FOLLOW_DEADLINE_MS + TIMEOUT_MARGIN_MS;

export type BundleGet = (path: string, timeoutMs: number) => Promise<unknown>;

type Field =
  | "profile" | "subscriberCounts" | "newFans" | "perModel" | "accounts" | "settings"
  | "notificationCounts" | "chats"
  | "seed" | "fan" | "attribution" | "fanHistory" | "scheduledSends" | ChatLack;

export type Read = {
  field: Field;
  accountId: string | null;
  since?: number;
} & (
  | { starter: true; bundle: Screen }
  | { starter: false; bundle: Screen | null }
);

export type Outcome =
  | { kind: "body"; body: unknown; refreshing?: true }
  | { kind: "error"; status: number; detail: unknown }
  | { kind: "late" }
  | { kind: "miss" };

const MISS: Outcome = { kind: "miss" };
const LATE: Outcome = { kind: "late" };

function exactly(params: URLSearchParams, want: Record<string, string | null>): boolean {
  const keys = Object.keys(want).filter((k) => want[k] != null);
  const got = [...params.keys()];
  return got.length === keys.length && new Set(got).size === got.length && keys.every((k) => params.get(k) === want[k]);
}

export function classify(url: string, accountId: string | null, screen: Screen): Read | null {
  const q = url.indexOf("?");
  const path = q < 0 ? url : url.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : url.slice(q + 1));
  const bare = [...params.keys()].length === 0;
  const own = (field: Field, starter: boolean, bundle: Screen): Read | null =>
    accountId ? { field, accountId, starter, bundle } : null;
  const shared = (field: Field, starter: boolean, bundle: Screen): Read | null =>
    accountId ? null : { field, accountId: null, starter, bundle };
  if (screen.kind === "chat") return classifyChat(path, params, bare, accountId, screen);
  if (screen.kind === "dashboard") {
    const { from, to } = screen;
    if (path === "/api/of/v2/users/me" && exactly(params, { max_age: params.get("max_age") })) {
      return own("profile", false, screen);
    }
    if (path === "/api/of/v2/subscriptions/count/all" && bare) return own("subscriberCounts", true, screen);
    if (path === "/api/of/v2/subscriptions/subscribers/chart" && exactly(params, { start: from, end: to })) {
      return own("newFans", true, screen);
    }
    if (path === "/admin/stats/per-model" && exactly(params, { from, to })) return shared("perModel", true, screen);
    if (path === "/admin/accounts" && bare) return shared("accounts", false, screen);
    if (path === "/admin/settings/applied" && bare) return shared("settings", false, screen);
    return null;
  }
  if (path === "/api/of/v2/users/notifications/count" && bare && accountId) {
    return { field: "notificationCounts", accountId, starter: false, bundle: null };
  }
  if (path === "/api/of/v2/chats") {
    const offset = Number(params.get("offset"));
    if (Number.isInteger(offset) && offset >= 0 && exactly(params, {
      limit: String(CHATS_PAGE), offset: String(offset), order: "recent",
    })) return own("chats", true, { kind: "inbox", cursor: offset });
  }
  if (path === "/admin/accounts" && bare) return shared("accounts", false, { kind: "inbox", cursor: 0 });
  return null;
}

function classifyChat(
  path: string, params: URLSearchParams, bare: boolean, accountId: string | null,
  screen: Extract<Screen, { kind: "chat" }>,
): Read | null {
  const { accountId: a, fanId: f } = screen;
  const read = (field: Field, since?: number): Read => ({
    field, accountId, starter: false, bundle: screen, ...(since != null ? { since } : {}),
  });
  const thread = `/admin/messages/${encodeURIComponent(a)}/${f}`;
  if (accountId === a) {
    return path === "/api/of/v2/scheduled-sends" && exactly(params, { fan_id: f }) ? read("scheduledSends") : null;
  }
  if (accountId) return null;
  if (path === thread && exactly(params, { limit: String(SEED_PAGE) })) return read("seed");
  if (path === `${thread}/attribution`) {
    if (bare) return read("attribution");
    const since = Number(params.get("since_id"));
    return Number.isSafeInteger(since) && since > 0 && exactly(params, { since_id: String(since) })
      ? read("attribution", since) : null;
  }
  if (path === `/admin/fans/${a}/${f}` && bare) return read("fan");
  if (path === "/admin/vault/fan-history" && exactly(params, { account_id: a, fan_id: f })) return read("fanHistory");
  const own = exactly(params, { account_id: a });
  if (path === "/admin/saved-replies" && own && screen.lacks.includes("savedReplies")) return read("savedReplies");
  if (path === "/admin/sensitive-words" && own && screen.lacks.includes("sensitiveWords")) return read("sensitiveWords");
  return null;
}

type AttributionBody = { by_msg_id?: Record<string, unknown> };

export function attributionSince(bare: unknown, since: number): AttributionBody | null {
  const rows = (bare as AttributionBody | null)?.by_msg_id;
  if (!rows || typeof rows !== "object" || Object.keys(rows).length >= ATTRIBUTION_LIMIT) return null;
  const floor = BigInt(since);
  const out: Record<string, unknown> = {};
  for (const [id, v] of Object.entries(rows)) if (/^\d+$/.test(id) && BigInt(id) >= floor) out[id] = v;
  return { by_msg_id: out };
}

type Answer = { accountId: string | null; read: string } & (
  | { body: unknown; refreshing?: true }
  | { status: number; detail: unknown }
);

function answers(body: unknown): Answer[] {
  const a = (body as { answers?: unknown } | null)?.answers;
  return Array.isArray(a) ? (a as Answer[]) : [];
}

function answerOf(body: unknown, read: Read): Answer | undefined {
  return answers(body).find((a) => a.accountId === read.accountId && a.read === read.field);
}

function late(a: Answer): boolean {
  return "status" in a && a.status === 504
    && (a.detail as { upstream_status?: unknown } | null)?.upstream_status === "bundle_deadline";
}

export function outcome(body: unknown, read: Read): Outcome {
  const a = answerOf(body, read);
  if (!a) return MISS;
  if ("status" in a) return late(a) ? LATE : { kind: "error", status: a.status, detail: a.detail };
  if (a.body == null) return MISS;
  if (read.field === "attribution" && read.since != null) {
    const derived = attributionSince(a.body, read.since);
    return derived ? { kind: "body", body: derived } : MISS;
  }
  return a.refreshing ? { kind: "body", body: a.body, refreshing: true } : { kind: "body", body: a.body };
}


const open = new Map<string, Screen>();
type Flight = {
  screen: Screen; key: string; done: number | null; p: Promise<unknown>; follow: Promise<unknown> | null;
  fresh?: unknown; freshAt?: number;
};
const flights = new Map<string, Flight>();
const bypass = new Set<string>();
const readId = (r: Read) => `${r.field}|${r.accountId ?? ""}`;

export function useScreen(s: Screen | null): void {
  const key = s ? screenKey(s) : null;
  const ref = useRef(s);
  ref.current = s;
  if (s && key && typeof window !== "undefined") { open.delete(key); open.set(key, s); }
  useEffect(() => {
    if (!ref.current || !key) return;
    open.set(key, ref.current);
    return () => { open.delete(key); };
  }, [key]);
}

function live(key: string, now: number): Flight | null {
  const f = flights.get(key);
  if (!f) return null;
  const at = f.freshAt ?? f.done;
  if (at != null && now - at > KEEP_MS) { flights.delete(key); return null; }
  return f;
}

function find(read: Read, now: number): Flight | null {
  if (read.bundle) return live(screenKey(read.bundle), now);
  for (const [k, f] of [...flights]) if (f.screen.kind === "inbox" && live(k, now)) return f;
  return null;
}

export function abortable<T>(p: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return p;
  signal.throwIfAborted();
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    p.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

function start(screen: Screen, get: BundleGet): Flight {
  const now = Date.now();
  for (const k of [...flights.keys()]) live(k, now);
  const flight: Flight = { screen, key: screenKey(screen), done: null, p: Promise.resolve(null), follow: null };
  flight.p = get(bundlePath(screen), BUNDLE_TIMEOUT_MS).catch(() => null).finally(() => { flight.done = Date.now(); });
  flights.set(flight.key, flight);
  return flight;
}

export function prefetchScreen(s: Screen, get: BundleGet): Promise<unknown> {
  return (live(screenKey(s), Date.now()) ?? start(s, get)).p;
}

export function screenRead(url: string, accountId: string | null): Read | null {
  for (const s of [...open.values()].reverse()) {
    const r = classify(url, accountId, s);
    if (r) return r;
  }
  return null;
}

export async function screenJoin(read: Read, get: BundleGet, signal?: AbortSignal | null): Promise<Outcome> {
  if (bypass.delete(readId(read))) return MISS;
  let f = find(read, Date.now());
  if (!f && !read.starter) {
    await new Promise((r) => setTimeout(r, 0));
    f = find(read, Date.now());
  }
  if (!f) {
    if (!read.starter) return MISS;
    f = start(read.bundle, get);
  }
  const body = await abortable(f.p, signal);
  const fresh = f.freshAt != null ? outcome(f.fresh, read) : MISS;
  if (fresh.kind === "body" || fresh.kind === "error") return fresh;
  const o = outcome(body, read);
  if (o.kind === "body" && o.refreshing) void refreshed(f, get, read, o.body);
  if (o.kind !== "late") return o;
  // No follow-up for chat: the relay kept the read running, its route answers.
  if (f.screen.kind === "chat") return MISS;
  const again = outcome(await abortable(followUp(f, get), signal), read);
  return again.kind === "late" ? MISS : again;
}

const listeners = new Set<(key: readonly unknown[]) => void>();

export function onScreenRefreshed(cb: (key: readonly unknown[]) => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

function refreshKey(read: Read): readonly unknown[] | null {
  const k = (REFRESH_KEYS as Partial<Record<Field, string>>)[read.field];
  return k && read.accountId ? [k, read.accountId] : null;
}
export const REFRESH_KEYS = {
  profile: "of-profile", subscriberCounts: "of-sub-counts", newFans: "of-new-fans",
} as const satisfies Partial<Record<Field, string>>;

async function refreshed(f: Flight, get: BundleGet, read: Read, was: unknown): Promise<void> {
  const now = outcome(await followUp(f, get), read);
  const key = refreshKey(read);
  if (!key) return;
  if (now.kind === "body" || now.kind === "error") {
    if (now.kind === "error" || JSON.stringify(now.body) !== JSON.stringify(was)) for (const cb of listeners) cb(key);
    return;
  }
  if (flights.get(f.key) === f) flights.delete(f.key);
  bypass.add(readId(read));
  for (const cb of listeners) cb(key);
}

export function followPath(s: Screen, ids: string[]): string {
  return withQuery(bundlePath(s), { accounts: ids.join(","), deadline_ms: String(FOLLOW_DEADLINE_MS) });
}

function followUp(f: Flight, get: BundleGet): Promise<unknown> {
  f.follow ??= f.p.then(async (body) => {
    const due = answers(body).filter((a) => a.accountId && (late(a) || ("body" in a && a.refreshing)));
    const ids = [...new Set(due.map((a) => String(a.accountId)))];
    if (!ids.length) return null;
    if (due.some(late)) await new Promise((r) => setTimeout(r, FOLLOW_MS));
    const fresh = await get(followPath(f.screen, ids), FOLLOW_TIMEOUT_MS).catch(() => null);
    if (fresh) { f.fresh = fresh; f.freshAt = Date.now(); }
    return fresh;
  });
  return f.follow;
}

export async function screenSettled(signal?: AbortSignal | null): Promise<void> {
  const busy = [...flights.values()].filter((f) => f.done == null).map((f) => f.p);
  if (busy.length) await abortable(Promise.all(busy), signal);
}

export function forgetScreenBundles(): void {
  flights.clear();
  bypass.clear();
}

export function screenBundleKeys(): string[] {
  return [...flights.keys()];
}

export function resetScreenBundles(): void {
  forgetScreenBundles();
  listeners.clear();
  open.clear();
}
