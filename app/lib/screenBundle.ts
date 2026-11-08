/**
 * One relay call per screen (service/screens_api.py): the Dashboard's Per-model cards and Messages Pro's All Models
 * list paid one round trip per Creator per read (users/me, fan counts, new fans; the bell and the chat page). Here
 * those reads JOIN their screen's bundle instead of going out one by one.
 *
 * No hook changes, one source of truth for keys: every per-Creator hook keeps its own query key, queryFn and
 * transform. `relay.request` asks `screenJoin` first; a GET the open screen's bundle covers gets that read's body
 * (the route's own body, service parity-tested) or its error (replayed through `parseResponse`, so a hook sees the
 * per-Creator route's RelayError). A read the bundle answered late (`bundle_deadline`: the relay kept it running, so
 * it lands in the relay's cache) waits for ONE follow-up bundle per flight, FOLLOW_MS later, naming only the late
 * Creators (`accounts=`, `deadline_ms=FOLLOW_DEADLINE_MS`, the same cursor): the card keeps its saved value meanwhile
 * (React Query keeps data while refetching), and no per-Creator fan-out fires. Only a read the bundle cannot answer at
 * all (a Creator not in it, the bundle failed, still late after the follow-up) goes out as before: per Creator, a
 * background one through the scheduler (lib/relaySchedule.ts, the focused Creator first).
 *
 * Who starts a bundle: a read only the screen's burst makes (fan counts, new fans, per-model; a chat page), never a
 * shared one (users/me, the accounts list, Applied settings) nor the bell (it polls), which only join one already
 * going; or a document load of the screen's route (`prefetchScreen`, lib/screenEntry.ts), with the auth probe. A screen
 * whose keys are all fresh (the saved snapshot) fires no read, so no bundle. A bundle's answers serve joins for
 * KEEP_MS after it lands (or after its follow-up; cards that mount a moment later), never longer, including right after
 * a write: a write does not expire it (a chat open fires its own writes, mark-read and the vault backfill, while its
 * bundle is in flight or just landed, and its later reads such as attribution must still join it), so a refetch within
 * KEEP_MS of a landing reads from before the write; reads after that go to their route. An identity switch forgets
 * every one (`forgetScreenBundles`: another principal's answers).
 *
 * A bundle's call has BUNDLE_TIMEOUT_MS (its follow-up FOLLOW_TIMEOUT_MS), its deadline plus a generous margin: past
 * it, it hung (a miss for every read); a slow answer within it still answers (no per-Creator fan-out beside it).
 *
 * Serve-stale: a read the relay answered from its last value (`refreshing`, re-read there behind the answer) resolves
 * at once and takes the same one follow-up as a late one; when the follow-up's value differs, `onScreenRefreshed`
 * names that hook's key (`refreshKey`), the app invalidates it, and the refetch joins the follow-up's body. A
 * follow-up with no value for it (failed, timed out, still late): the flight is dropped, the key named too, and that
 * read's refetch goes to its route (`bypass`), so a stale value never stands as fresh.
 */
import { useEffect, useRef } from "react";

import { bundlePath, screenKey, withQuery, type ChatLack, type Screen } from "@/lib/screenKey";

/** The chat bundle's DB seed page (service/chat_screen_api.py SEED_PAGE; useChatMessagesLocal's default limit). */
export const SEED_PAGE = 30;
/** The attribution route's limit: a bare answer with fewer rows holds every outbound row of the thread. */
export const ATTRIBUTION_LIMIT = 200;

/** The bundle's per-Creator chat page (service/screens_api.py CHATS_PAGE; useChatList's PAGE_SIZE). */
export const CHATS_PAGE = 25;
/** How long a landed bundle still serves joins. */
export const KEEP_MS = 2_000;
/** The follow-up for a bundle's late Creators: this long after it landed, and its own (long) deadline. */
export const FOLLOW_MS = 250;
export const FOLLOW_DEADLINE_MS = 15_000;
/** A bundle's call past its deadline (service/screens_api.py DEADLINE_MS, 2 s; the follow-up's FOLLOW_DEADLINE_MS) plus
 *  this failed: a hang, not a slow answer (the relay's queue before the deadline, a slow link's download after it). */
const TIMEOUT_MARGIN_MS = 6_000;
export const BUNDLE_TIMEOUT_MS = 2_000 + TIMEOUT_MARGIN_MS;
export const FOLLOW_TIMEOUT_MS = FOLLOW_DEADLINE_MS + TIMEOUT_MARGIN_MS;

/** A bundle's relay GET of `path`, failed past `timeoutMs`. */
export type BundleGet = (path: string, timeoutMs: number) => Promise<unknown>;

type Field =
  | "profile" | "subscriberCounts" | "newFans" | "perModel" | "accounts" | "settings"
  | "notificationCounts" | "chats"
  | "seed" | "fan" | "attribution" | "fanHistory" | "scheduledSends" | ChatLack;

export type Read = {
  field: Field;
  accountId: string | null;
  /** An attribution read's `since_id`: answered from the bundle's bare attribution (`attributionSince`). */
  since?: number;
} & (
  /** `starter`: may start its bundle (else only joins one). `bundle`: the one it belongs to; null: any inbox bundle
   *  (the bell, which only joins). */
  | { starter: true; bundle: Screen }
  | { starter: false; bundle: Screen | null }
);

export type Outcome =
  /** `refreshing`: the relay's last value, re-read there behind the answer (its follow-up has the new one). */
  | { kind: "body"; body: unknown; refreshing?: true }
  | { kind: "error"; status: number; detail: unknown }
  /** Past the bundle's deadline (its follow-up has it). */
  | { kind: "late" }
  | { kind: "miss" };

const MISS: Outcome = { kind: "miss" };
const LATE: Outcome = { kind: "late" };

/** `params` hold exactly `want`'s entries (a null value: absent). */
function exactly(params: URLSearchParams, want: Record<string, string | null>): boolean {
  const keys = Object.keys(want).filter((k) => want[k] != null);
  const got = [...params.keys()];
  return got.length === keys.length && new Set(got).size === got.length && keys.every((k) => params.get(k) === want[k]);
}

/** Which of `screen`'s bundle reads `url` (relay.ts' buildUrl: path + query) is, for `accountId`; null: none. */
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
    if (path === "/api/of/v2/users/me" && bare) return own("profile", false, screen);
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

/** A thread's reads the chat bundle answers (each hook's exact URL; `accountId` its X-Account-Id). */
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

/** The attribution route's `since_id` answer from its bare one: the rows at or past `since` (ids as text, Fansly
 *  snowflakes compared as BigInt). Exact only while the bare answer is below the route's limit (it then holds every
 *  outbound row); else null (read the route). */
export function attributionSince(bare: unknown, since: number): AttributionBody | null {
  const rows = (bare as AttributionBody | null)?.by_msg_id;
  if (!rows || typeof rows !== "object" || Object.keys(rows).length >= ATTRIBUTION_LIMIT) return null;
  const floor = BigInt(since);
  const out: Record<string, unknown> = {};
  for (const [id, v] of Object.entries(rows)) if (/^\d+$/.test(id) && BigInt(id) >= floor) out[id] = v;
  return { by_msg_id: out };
}

/** One read's answer in a bundle (service/screens_api.py `run_screen`): its route's body, or its error. */
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

/** `read`'s answer in a bundle `body`: the route's body, its error, late, or a miss (go out per Creator). */
export function outcome(body: unknown, read: Read): Outcome {
  const a = answerOf(body, read);
  if (!a) return MISS;
  if ("status" in a) return late(a) ? LATE : { kind: "error", status: a.status, detail: a.detail };
  if (a.body == null) return MISS;   // no value and no error: not an answer
  if (read.field === "attribution" && read.since != null) {
    const derived = attributionSince(a.body, read.since);
    return derived ? { kind: "body", body: derived } : MISS;
  }
  return a.refreshing ? { kind: "body", body: a.body, refreshing: true } : { kind: "body", body: a.body };
}

// ── runtime: the open screen and its bundles in flight ──────────────────────

/** The open screens by key (Messages Pro's list and its open thread at once). */
const open = new Map<string, Screen>();
type Flight = {
  screen: Screen; key: string; done: number | null; p: Promise<unknown>; follow: Promise<unknown> | null;
  /** The follow-up's body once it landed (it answers before `p`), and when. */
  fresh?: unknown; freshAt?: number;
};
const flights = new Map<string, Flight>();
/** Reads whose stale value the follow-up never replaced: their next read goes to the route (once). */
const bypass = new Set<string>();
const readId = (r: Read) => `${r.field}|${r.accountId ?? ""}`;

/** Mark `s` open while the calling component is mounted (set during render: this commit's reads see it). */
export function useScreen(s: Screen | null): void {
  const key = s ? screenKey(s) : null;
  const ref = useRef(s);
  ref.current = s;
  if (s && key && typeof window !== "undefined") { open.delete(key); open.set(key, s); }  // newest rendered first
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

/** `p`, or a rejection with `signal`'s reason once it aborts (`p` itself runs on). */
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
  for (const k of [...flights.keys()]) live(k, now);   // landed ones past KEEP_MS: gone (a long-lived tab)
  const flight: Flight = { screen, key: screenKey(screen), done: null, p: Promise.resolve(null), follow: null };
  flight.p = get(bundlePath(screen), BUNDLE_TIMEOUT_MS).catch(() => null).finally(() => { flight.done = Date.now(); });
  flights.set(flight.key, flight);
  return flight;
}

/** Start `s`'s bundle now unless one is live: a document load starts it with the auth probe (lib/screenEntry.ts),
 *  not three round trips later when the screen's first starter mounts; the screen's reads join it as any flight. A
 *  guess another screen's key never joins (a miss: that screen starts its own). */
export function prefetchScreen(s: Screen, get: BundleGet): Promise<unknown> {
  return (live(screenKey(s), Date.now()) ?? start(s, get)).p;
}

/** The read `url` for `accountId` would be, if the open screen's bundle covers it (sync: no await for the rest). */
export function screenRead(url: string, accountId: string | null): Read | null {
  for (const s of [...open.values()].reverse()) {
    const r = classify(url, accountId, s);
    if (r) return r;
  }
  return null;
}

/** `read`'s answer from its screen's bundle: joins one in flight (or landed < KEEP_MS ago), else a starter starts one
 *  with `get` (the bundle's own relay GET, user priority), else a miss. A failed bundle is a miss for every read; a
 *  late read takes the flight's one follow-up (still late or failed there: a miss). */
export async function screenJoin(read: Read, get: BundleGet, signal?: AbortSignal | null): Promise<Outcome> {
  if (bypass.delete(readId(read))) return MISS;
  let f = find(read, Date.now());
  if (!f && !read.starter) {
    // This commit's starters fire in the same task: let them start it.
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
  if (f.screen.kind === "chat") return MISS;  // no follow-up: the relay kept the read running, its route answers
  const again = outcome(await abortable(followUp(f, get), signal), read);
  return again.kind === "late" ? MISS : again;
}

const listeners = new Set<(key: readonly unknown[]) => void>();

/** `cb` gets the query key of every read a follow-up answered with another value than the stale one it saw, or
 *  with none (that read then goes to its route). */
export function onScreenRefreshed(cb: (key: readonly unknown[]) => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

/** The hook key holding `read`'s value (hooks/useStats.ts: useAccountProfile, useOfSubscriberCounts, useOfNewFans:
 *  the reads the relay serves stale, service/screens_api.py STALE_READS); null: none. */
function refreshKey(read: Read): readonly unknown[] | null {
  const k = (REFRESH_KEYS as Partial<Record<Field, string>>)[read.field];
  return k && read.accountId ? [k, read.accountId] : null;
}
/** Those hooks' query key heads (hooks/useStats.ts reads them from here). */
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
  // No new value: the stale one must not stand. This flight serves no more joins; the read's refetch reads its route.
  if (flights.get(f.key) === f) flights.delete(f.key);
  bypass.add(readId(read));
  for (const cb of listeners) cb(key);
}

/** The URL of `s`'s follow-up for its late Creators `ids`. */
export function followPath(s: Screen, ids: string[]): string {
  return withQuery(bundlePath(s), { accounts: ids.join(","), deadline_ms: String(FOLLOW_DEADLINE_MS) });
}

/** `f`'s one follow-up: every Creator its body answered late (FOLLOW_MS after it landed) or from the relay's last
 *  value (at once: its re-read is already running there). Its body then answers the flight's joins first, for KEEP_MS. */
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

/** Resolves once no bundle's first call is in flight (follow-ups don't count). A background OnlyFans read waits
 *  here: the bundle's reads for the other Creators are background on the relay too (2 slots a Creator), so the rail's
 *  feeds sent alongside took those slots and the screen's own rows landed a round later (clicks-first mp-first). */
export async function screenSettled(signal?: AbortSignal | null): Promise<void> {
  const busy = [...flights.values()].filter((f) => f.done == null).map((f) => f.p);
  if (busy.length) await abortable(Promise.all(busy), signal);
}

/** Forget every bundle, in flight or landed, and every `bypass`: an identity switch (another principal's answers). */
export function forgetScreenBundles(): void {
  flights.clear();
  bypass.clear();
}

/** Tests only: the bundles held (in flight or landed). */
export function screenBundleKeys(): string[] {
  return [...flights.keys()];
}

/** Tests only: forget every bundle, listener and open screen. */
export function resetScreenBundles(): void {
  forgetScreenBundles();
  listeners.clear();
  open.clear();
}
