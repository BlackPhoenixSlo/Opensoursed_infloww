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
 * Who starts a bundle: a read only the screen's burst makes (fan counts, new fans, per-model; the bell, a chat page),
 * never a shared one (users/me, the accounts list, Applied settings), which only joins one already going; or a
 * document load of the screen's route (`prefetchScreen`, lib/screenEntry.ts), with the auth probe. A screen
 * whose keys are all fresh (the saved snapshot) fires no read, so no bundle. A bundle's answers serve joins for
 * KEEP_MS after it lands (cards that mount a moment later), never longer: a refetch after a write reads its route.
 */
import { useEffect, useRef } from "react";

export type Screen =
  | { kind: "dashboard"; from: string | null; to: string | null }
  | { kind: "inbox" };

/** The bundle's per-Creator chat page (service/screens_api.py CHATS_PAGE, useChatList PAGE_SIZE). */
export const CHATS_PAGE = 25;
/** How long a landed bundle still serves joins. */
export const KEEP_MS = 2_000;
/** The follow-up for a bundle's late Creators: this long after it landed, and its own (long) deadline. */
export const FOLLOW_MS = 250;
export const FOLLOW_DEADLINE_MS = 15_000;

type Field =
  | "profile" | "subscriberCounts" | "newFans" | "perModel" | "accounts" | "settings"
  | "notificationCounts" | "chats";

export interface Read {
  field: Field;
  accountId: string | null;
  /** May start a bundle (else only joins one). */
  starter: boolean;
  /** The bundle this read belongs to (an inbox read but the chat page: any inbox bundle; null). */
  bundle: string | null;
}

export type Outcome =
  | { kind: "body"; body: unknown }
  | { kind: "error"; status: number; detail: unknown }
  /** Past the bundle's deadline (its follow-up has it). */
  | { kind: "late" }
  | { kind: "miss" };

const MISS: Outcome = { kind: "miss" };
const LATE: Outcome = { kind: "late" };

export function screenKey(s: Screen): string {
  return s.kind === "dashboard" ? `dashboard|${s.from ?? ""}|${s.to ?? ""}` : "inbox|0";
}

/** The bundle's URL for `key` (`dashboard|from|to`, `inbox|cursor`). */
export function bundlePath(key: string): string {
  const [kind, a, b] = key.split("|");
  const qs = new URLSearchParams();
  if (kind === "dashboard") {
    if (a) qs.set("from", a);
    if (b) qs.set("to", b);
  } else {
    qs.set("cursor", a);
  }
  const s = qs.toString();
  return `/admin/screens/${kind}${s ? `?${s}` : ""}`;
}

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
  const own = (field: Field, starter: boolean, bundle: string | null): Read | null =>
    accountId ? { field, accountId, starter, bundle } : null;
  const shared = (field: Field, bundle: string): Read | null =>
    accountId ? null : { field, accountId: null, starter: false, bundle };
  if (screen.kind === "dashboard") {
    const key = screenKey(screen);
    const { from, to } = screen;
    if (path === "/api/of/v2/users/me" && bare) return own("profile", false, key);
    if (path === "/api/of/v2/subscriptions/count/all" && bare) return own("subscriberCounts", true, key);
    if (path === "/api/of/v2/subscriptions/subscribers/chart" && exactly(params, { start: from, end: to })) {
      return own("newFans", true, key);
    }
    if (path === "/admin/stats/per-model" && exactly(params, { from, to })) {
      return accountId ? null : { field: "perModel", accountId: null, starter: true, bundle: key };
    }
    if (path === "/admin/accounts" && bare) return shared("accounts", key);
    if (path === "/admin/settings/applied" && bare) return shared("settings", key);
    return null;
  }
  if (path === "/api/of/v2/users/notifications/count" && bare) return own("notificationCounts", true, null);
  if (path === "/api/of/v2/chats") {
    const offset = Number(params.get("offset"));
    if (Number.isInteger(offset) && offset >= 0 && exactly(params, {
      limit: String(CHATS_PAGE), offset: String(offset), order: "recent",
    })) return own("chats", true, `inbox|${offset}`);
  }
  if (path === "/admin/accounts" && bare) return shared("accounts", "inbox|0");
  return null;
}

type Body = Record<string, unknown>;
type BundleError = { accountId?: string | null; read?: string; status?: number; detail?: unknown };

function late(e: BundleError): boolean {
  return e.status === 504 && (e.detail as Body | null)?.upstream_status === "bundle_deadline";
}

/** `read`'s answer in a bundle `body`: the route's body, its error, or a miss (go out per Creator). */
export function outcome(body: unknown, read: Read): Outcome {
  if (!body || typeof body !== "object") return MISS;
  const b = body as Body;
  const errors = (Array.isArray(b.errors) ? b.errors : []) as BundleError[];
  const err = errors.find((e) => (e.accountId ?? null) === read.accountId && e.read === read.field);
  if (err) {
    if (late(err)) return LATE;
    return typeof err.status === "number" ? { kind: "error", status: err.status, detail: err.detail } : MISS;
  }
  switch (read.field) {
    case "accounts":  // a chatter's is /chatter/me/accounts' list: not this route's body
      return b.accounts && typeof b.accounts === "object" && !Array.isArray(b.accounts)
        ? { kind: "body", body: b.accounts } : MISS;
    case "settings":
    case "perModel":
      return b[read.field] != null ? { kind: "body", body: b[read.field] } : MISS;
    case "notificationCounts":
    case "chats": {
      const m = b[read.field] as Body | undefined;
      return m && read.accountId && read.accountId in m ? { kind: "body", body: m[read.accountId] } : MISS;
    }
    default: {
      const rows = (Array.isArray(b.creators) ? b.creators : []) as Body[];
      const row = rows.find((r) => r.id === read.accountId);
      // A field the bundle did not read (a hidden card), or a null with no error: not an answer.
      return row && row[read.field] != null ? { kind: "body", body: row[read.field] } : MISS;
    }
  }
}

// ── runtime: the open screen and its bundles in flight ──────────────────────

let current: Screen | null = null;
type Flight = { key: string; done: number | null; p: Promise<unknown>; follow: Promise<unknown> | null };
const flights = new Map<string, Flight>();

/** The open screen's bundles may serve its reads (null: none). */
export function setScreen(s: Screen | null): void {
  current = s;
}

/** Mark `s` open while the calling component is mounted (set during render: this commit's reads see it). */
export function useScreen(s: Screen | null): void {
  const key = s ? screenKey(s) : null;
  const ref = useRef(s);
  ref.current = s;
  if (s && typeof window !== "undefined") current = s;
  useEffect(() => {
    if (!ref.current) return;
    current = ref.current;
    return () => { if (current && screenKey(current) === key) current = null; };
  }, [key]);
}

function live(key: string, now: number): Flight | null {
  const f = flights.get(key);
  if (!f) return null;
  if (f.done != null && now - f.done > KEEP_MS) { flights.delete(key); return null; }
  return f;
}

function find(read: Read, now: number): Flight | null {
  if (read.bundle) return live(read.bundle, now);
  for (const k of [...flights.keys()].filter((k) => k.startsWith("inbox|"))) {
    const f = live(k, now);
    if (f) return f;
  }
  return null;
}

function abortable<T>(p: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return p;
  signal.throwIfAborted();
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    p.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

function start(key: string, get: (path: string) => Promise<unknown>): Flight {
  const flight: Flight = { key, done: null, p: Promise.resolve(null), follow: null };
  flight.p = get(bundlePath(key)).catch(() => null).finally(() => { flight.done = Date.now(); });
  flights.set(key, flight);
  return flight;
}

/** Start `s`'s bundle now unless one is live: a document load starts it with the auth probe (lib/screenEntry.ts),
 *  not three round trips later when the screen's first starter mounts; the screen's reads join it as any flight. A
 *  guess another screen's key never joins (a miss: that screen starts its own). */
export function prefetchScreen(s: Screen, get: (path: string) => Promise<unknown>): void {
  const key = screenKey(s);
  if (!live(key, Date.now())) start(key, get);
}

/** The read `url` for `accountId` would be, if the open screen's bundle covers it (sync: no await for the rest). */
export function screenRead(url: string, accountId: string | null): Read | null {
  return current ? classify(url, accountId, current) : null;
}

/** `read`'s answer from its screen's bundle: joins one in flight (or landed < KEEP_MS ago), else a starter starts one
 *  with `get` (the bundle's own relay GET, user priority), else a miss. A failed bundle is a miss for every read; a
 *  late read takes the flight's one follow-up (still late or failed there: a miss). */
export async function screenJoin(
  read: Read, get: (path: string) => Promise<unknown>, signal?: AbortSignal | null,
): Promise<Outcome> {
  let f = find(read, Date.now());
  if (!f && !read.starter) {
    // This commit's starters fire in the same task: let them start it.
    await new Promise((r) => setTimeout(r, 0));
    f = find(read, Date.now());
  }
  if (!f) {
    if (!read.starter) return MISS;
    f = start(read.bundle ?? "inbox|0", get);
  }
  const o = outcome(await abortable(f.p, signal), read);
  if (o.kind !== "late") return o;
  const again = outcome(await abortable(followUp(f, get), signal), read);
  return again.kind === "late" ? MISS : again;
}

/** The URL of `key`'s follow-up for its late Creators `ids`. */
export function followPath(key: string, ids: string[]): string {
  const p = bundlePath(key);
  const qs = new URLSearchParams({ accounts: ids.join(","), deadline_ms: String(FOLLOW_DEADLINE_MS) });
  return `${p}${p.includes("?") ? "&" : "?"}${qs.toString()}`;
}

/** `f`'s one follow-up: every Creator its body answered late, FOLLOW_MS after it landed. */
function followUp(f: Flight, get: (path: string) => Promise<unknown>): Promise<unknown> {
  f.follow ??= f.p.then(async (body) => {
    const errors = ((body as Body | null)?.errors ?? []) as BundleError[];
    const ids = [...new Set(errors.filter((e) => late(e) && e.accountId).map((e) => String(e.accountId)))];
    if (!ids.length) return null;
    await new Promise((r) => setTimeout(r, FOLLOW_MS));
    return get(followPath(f.key, ids)).catch(() => null);
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

/** Tests only: forget every bundle and the open screen. */
export function resetScreenBundles(): void {
  flights.clear();
  current = null;
}
