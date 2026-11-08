import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BUNDLE_TIMEOUT_MS, classify, FOLLOW_DEADLINE_MS, FOLLOW_MS, FOLLOW_TIMEOUT_MS, followPath,
  forgetScreenBundles, KEEP_MS,
  onScreenRefreshed, outcome, prefetchScreen, resetScreenBundles, screenBundleKeys, screenJoin, screenRead, screenSettled,
  useScreen, type Read,
} from "./screenBundle";
import { bundlePath, type Screen } from "./screenKey";

const DASH: Screen = { kind: "dashboard", from: "2026-10-01T00:00:00Z", to: "2026-11-01T00:00:00Z" };
const INBOX: Screen = { kind: "inbox", cursor: 0 };
const q = (o: Record<string, string>) => new URLSearchParams(o).toString();
const openScreen = (s: Screen | null) => renderHook(() => useScreen(s));
const PAGE0 = "/api/of/v2/chats?limit=25&offset=0&order=recent";
const BELL = "/api/of/v2/users/notifications/count";

describe("classify", () => {
  it.each<[string, string, string | null, Screen, Partial<Read> | null]>([
    ["profile joins only", "/api/of/v2/users/me", "1", DASH, { field: "profile", starter: false, bundle: DASH }],
    ["fan counts start", "/api/of/v2/subscriptions/count/all", "1", DASH, { field: "subscriberCounts", starter: true }],
    ["new fans, the screen's window", `/api/of/v2/subscriptions/subscribers/chart?${q({ start: DASH.from!, end: DASH.to! })}`,
      "1", DASH, { field: "newFans", starter: true }],
    ["new fans, another window", `/api/of/v2/subscriptions/subscribers/chart?${q({ start: "2026-09-01", end: DASH.to! })}`,
      "1", DASH, null],
    ["new fans, by=", `/api/of/v2/subscriptions/subscribers/chart?${q({ start: DASH.from!, end: DASH.to!, by: "x" })}`,
      "1", DASH, null],
    ["per-model", `/admin/stats/per-model?${q({ from: DASH.from!, to: DASH.to! })}`, null, DASH,
      { field: "perModel", starter: true }],
    ["per-model with engagement", `/admin/stats/per-model?${q({ from: DASH.from!, to: DASH.to!, engagement: "true" })}`,
      null, DASH, null],
    ["accounts list joins only", "/admin/accounts", null, DASH, { field: "accounts", starter: false }],
    ["Applied settings for a Creator: not the bundle's", "/admin/settings/applied", "1", DASH, null],
    ["Applied settings unscoped", "/admin/settings/applied", null, DASH, { field: "settings", starter: false }],
    ["a refresh", "/api/of/v2/subscriptions/count/all?refresh=1", "1", DASH, null],
    ["a share token", "/api/of/v2/users/me?t=abc", "1", DASH, null],
    ["users/me with no Creator", "/api/of/v2/users/me", null, DASH, null],
    ["the bell on the Dashboard", BELL, "1", DASH, null],
    ["the bell joins only (it polls)", BELL, "1", INBOX, { field: "notificationCounts", starter: false, bundle: null }],
    ["chat page 2", "/api/of/v2/chats?limit=25&offset=25&order=recent", "1", INBOX,
      { field: "chats", starter: true, bundle: { kind: "inbox", cursor: 25 } }],
    ["a filtered page", `${PAGE0}&filter=unread`, "1", INBOX, null],
    ["oldest first", "/api/of/v2/chats?limit=25&offset=0&order=old", "1", INBOX, null],
    ["another page size", "/api/of/v2/chats?limit=50&offset=0&order=recent", "1", INBOX, null],
    ["fan counts in Messages Pro", "/api/of/v2/subscriptions/count/all", "1", INBOX, null],
    ["the money rail's feed: its own route", "/api/of/v2/users/notifications?limit=20&offset=0&type=purchases", "1", INBOX, null],
    ["last purchases: its own route", "/api/of/v2/payouts/transactions?limit=50&offset=0", "1", INBOX, null],
  ])("%s", (_n, url, aid, screen, want) => {
    const got = classify(url, aid, screen);
    if (want === null) expect(got).toBeNull();
    else expect(got).toMatchObject({ accountId: aid, ...want });
  });

  it("bundle paths", () => {
    expect(bundlePath(DASH)).toBe(`/admin/screens/dashboard?${q({ from: DASH.from!, to: DASH.to! })}`);
    expect(bundlePath({ kind: "dashboard", from: null, to: null })).toBe("/admin/screens/dashboard");
    expect(bundlePath({ kind: "inbox", cursor: 25 })).toBe("/admin/screens/inbox?cursor=25");
    expect(followPath({ kind: "inbox", cursor: 25 }, ["1", "2"]))
      .toBe(`/admin/screens/inbox?cursor=25&accounts=1%2C2&deadline_ms=${FOLLOW_DEADLINE_MS}`);
  });
});

const r = (field: Read["field"], accountId: string | null): Read => ({ field, accountId, starter: false, bundle: null });
const LATE = { status: 504, detail: { upstream_status: "bundle_deadline" } };
const ok = (accountId: string | null, read: string, body: unknown, more: object = {}) => ({ accountId, read, body, ...more });
const err = (accountId: string | null, read: string, e: { status: number; detail: unknown }) => ({ accountId, read, ...e });
const DASH_BODY = {
  answers: [
    ok(null, "settings", { s: 1 }), ok(null, "accounts", { accounts: [{ id: "1" }] }), ok(null, "perModel", { per_model: [] }),
    ok("1", "profile", { id: 1 }), ok("1", "subscriberCounts", { subscribers: { all: 5 } }), ok("1", "newFans", { subscribers: 2 }),
    ok("2", "profile", { id: 2 }), err("2", "subscriberCounts", LATE), err("2", "newFans", LATE),
    err("3", "profile", { status: 403, detail: "not yours" }),
    err("3", "subscriberCounts", { status: 502, detail: { upstream_status: 500 } }), ok("3", "newFans", null),
    ok("4", "profile", { id: 4 }),   // a hidden Per-model card: profile only
  ],
  asOf: 1,
};
const INBOX_BODY = {
  answers: [
    ok(null, "accounts", { accounts: [] }), ok("1", "notificationCounts", { all: 3 }),
    ok("1", "chats", { list: [], hasMore: false }), err("2", "chats", LATE), err("3", "chats", { status: 503, detail: "x" }),
  ],
  asOf: 1,
};

describe("outcome", () => {
  it.each<[string, unknown, Read, unknown]>([
    ["a value", DASH_BODY, r("subscriberCounts", "1"), { kind: "body", body: { subscribers: { all: 5 } } }],
    ["another Creator's finished read", DASH_BODY, r("profile", "2"), { kind: "body", body: { id: 2 } }],
    ["a late read: the follow-up's", DASH_BODY, r("subscriberCounts", "2"), { kind: "late" }],
    ["a role refusal: the route's", DASH_BODY, r("profile", "3"), { kind: "error", status: 403, detail: "not yours" }],
    ["OF's error", DASH_BODY, r("subscriberCounts", "3"), { kind: "error", status: 502, detail: { upstream_status: 500 } }],
    ["a null with no error", DASH_BODY, r("newFans", "3"), { kind: "miss" }],
    ["a field not read (hidden card)", DASH_BODY, r("subscriberCounts", "4"), { kind: "miss" }],
    ["a Creator not in the bundle", DASH_BODY, r("profile", "9"), { kind: "miss" }],
    ["per-model", DASH_BODY, r("perModel", null), { kind: "body", body: { per_model: [] } }],
    ["per-model absent", { answers: DASH_BODY.answers.filter((a) => a.read !== "perModel") }, r("perModel", null),
      { kind: "miss" }],
    ["accounts", DASH_BODY, r("accounts", null), { kind: "body", body: { accounts: [{ id: "1" }] } }],
    ["settings", DASH_BODY, r("settings", null), { kind: "body", body: { s: 1 } }],
    ["the bell", INBOX_BODY, r("notificationCounts", "1"), { kind: "body", body: { all: 3 } }],
    ["a chat page", INBOX_BODY, r("chats", "1"), { kind: "body", body: { list: [], hasMore: false } }],
    ["a late chat page", INBOX_BODY, r("chats", "2"), { kind: "late" }],
    ["no session", INBOX_BODY, r("chats", "3"), { kind: "error", status: 503, detail: "x" }],
    ["the relay's last value (its follow-up has the new one)",
      { answers: [ok("1", "profile", { id: 1 }, { refreshing: true })] }, r("profile", "1"),
      { kind: "body", body: { id: 1 }, refreshing: true }],
    ["a failed bundle", null, r("chats", "1"), { kind: "miss" }],
    ["not an envelope", { chats: { 1: {} } }, r("chats", "1"), { kind: "miss" }],
  ])("%s", (_n, body, read, want) => expect(outcome(body, read)).toEqual(want));
});

describe("screenJoin", () => {
  afterEach(() => { cleanup(); resetScreenBundles(); vi.useRealTimers(); });

  it("one bundle for a screen's burst; a joiner fired first waits a task for the starter", async () => {
    openScreen(DASH);
    const get = vi.fn(async (_p: string, _t: number) => DASH_BODY);
    const p1 = screenJoin(screenRead("/api/of/v2/users/me", "1")!, get);
    const p2 = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "1")!, get);
    const p3 = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "2")!, get);
    expect(await p1).toEqual({ kind: "body", body: { id: 1 } });
    expect(await p2).toEqual({ kind: "body", body: { subscribers: { all: 5 } } });
    expect(await p3).toEqual({ kind: "miss" });   // late, and late again in its follow-up
    expect(get.mock.calls).toEqual([[bundlePath(DASH), BUNDLE_TIMEOUT_MS], [followPath(DASH, ["2"]), FOLLOW_TIMEOUT_MS]]);
  });

  it("screenSettled: at once with no bundle; else when the first call lands (not its follow-up); abortable", async () => {
    openScreen(DASH);
    await screenSettled();
    let land!: (b: unknown) => void;
    const get = vi.fn((p: string) => p.includes("accounts=") ? new Promise(() => {}) : new Promise((r) => { land = r; }));
    const late = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "2")!, get);
    let settled = false;
    const s = screenSettled().then(() => { settled = true; });
    const ac = new AbortController();
    const aborted = screenSettled(ac.signal);
    ac.abort(new Error("gone"));
    await expect(aborted).rejects.toThrow("gone");
    await new Promise((r) => setTimeout(r, 0));
    expect(settled).toBe(false);
    land(DASH_BODY);
    await s;
    await new Promise((r) => setTimeout(r, FOLLOW_MS + 20));
    expect(get).toHaveBeenCalledTimes(2);            // the follow-up for Creator 2 still in flight
    await screenSettled();                           // ...and it does not hold background reads
    void late;
  });

  it("a joiner alone never starts a bundle (the bell neither)", async () => {
    openScreen(DASH);
    const get = vi.fn(async () => DASH_BODY);
    expect(await screenJoin(screenRead("/api/of/v2/users/me", "1")!, get)).toEqual({ kind: "miss" });
    cleanup();
    openScreen(INBOX);
    expect(await screenJoin(screenRead(BELL, "1")!, get)).toEqual({ kind: "miss" });
    expect(get).not.toHaveBeenCalled();
  });

  it("a landed bundle serves joins for KEEP_MS, then the next burst starts another", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    openScreen(INBOX);
    const get = vi.fn(async () => INBOX_BODY);
    const page = screenRead(PAGE0, "1")!;
    await screenJoin(page, get);
    vi.setSystemTime(Date.now() + KEEP_MS - 10);
    expect(await screenJoin(screenRead(BELL, "1")!, get)).toEqual({ kind: "body", body: { all: 3 } });
    expect(get).toHaveBeenCalledTimes(1);
    vi.setSystemTime(Date.now() + 50);
    await screenJoin(page, get);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("start sweeps every landed bundle past KEEP_MS (a long-lived tab holds none)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const get = vi.fn(async (p: string) => (p.includes("inbox") ? INBOX_BODY : DASH_BODY));
    const CHAT: Screen = { kind: "chat", accountId: "1", fanId: "5", lacks: [] };
    await prefetchScreen(DASH, get);
    await prefetchScreen(CHAT, get);
    expect(screenBundleKeys()).toHaveLength(2);
    vi.setSystemTime(Date.now() + KEEP_MS + 1);
    await prefetchScreen(INBOX, get);
    expect(screenBundleKeys()).toEqual(["inbox|0"]);
  });

  it("a failed bundle: every read goes out per Creator", async () => {
    openScreen(INBOX);
    const get = vi.fn(async () => { throw new Error("502"); });
    expect(await screenJoin(screenRead(PAGE0, "1")!, get)).toEqual({ kind: "miss" });
  });

  it("a bundle past its timeout (the get rejects): a miss for every read, joiners too", async () => {
    openScreen(INBOX);
    const get = vi.fn((_p: string, t: number) => new Promise((_res, rej) => setTimeout(() => rej(new DOMException("t", "TimeoutError")), t / 1000)));
    const [page, bell] = await Promise.all([screenJoin(screenRead(PAGE0, "1")!, get), screenJoin(screenRead(BELL, "1")!, get)]);
    expect([page, bell]).toEqual([{ kind: "miss" }, { kind: "miss" }]);
    expect(get.mock.calls).toEqual([[bundlePath(INBOX), BUNDLE_TIMEOUT_MS]]);
    await screenSettled();                           // and it holds no background read
  });

  it("an aborted joiner rejects; the bundle still serves the others", async () => {
    openScreen(INBOX);
    let land!: (b: unknown) => void;
    const get = vi.fn(() => new Promise((res) => { land = res; }));
    const ac = new AbortController();
    const b = screenJoin(screenRead(PAGE0, "1")!, get);
    const a = screenJoin(screenRead(BELL, "1")!, get, ac.signal);
    ac.abort(new DOMException("gone", "AbortError"));
    await expect(a).rejects.toThrow("gone");
    land(INBOX_BODY);
    expect(await b).toEqual({ kind: "body", body: { list: [], hasMore: false } });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("late reads share ONE follow-up naming only the late Creators, the same cursor; no per-Creator read", async () => {
    openScreen(INBOX);
    const base = { answers: [
      ok("1", "chats", { list: [], hasMore: false }), err("2", "chats", LATE),
      err("4", "notificationCounts", LATE), err("4", "chats", LATE)] };
    const follow = { answers: [ok("2", "chats", { list: [{ id: 2 }] }), err("4", "notificationCounts", LATE), ok("4", "chats", { list: [] })] };
    const get = vi.fn(async (p: string) => (p.includes("accounts=") ? follow : base));
    const page = (aid: string) => screenJoin(screenRead(PAGE0, aid)!, get);
    const [two, four, bell4, one] = await Promise.all([page("2"), page("4"), screenJoin(screenRead(BELL, "4")!, get), page("1")]);
    expect(one).toEqual({ kind: "body", body: { list: [], hasMore: false } });
    expect(two).toEqual({ kind: "body", body: { list: [{ id: 2 }] } });
    expect(four).toEqual({ kind: "body", body: { list: [] } });
    expect(bell4).toEqual({ kind: "miss" });   // still late after the follow-up: per Creator
    expect(get.mock.calls.map((c) => c[0])).toEqual([bundlePath(INBOX), followPath(INBOX, ["2", "4"])]);
  });

  it("serve-stale: a refreshing read answers at once, ONE follow-up; a changed value names its key, whose refetch gets the follow-up's", async () => {
    openScreen(DASH);
    const stale = { answers: [
      ok("1", "profile", { id: 1 }, { refreshing: true }), ok("1", "subscriberCounts", { subscribers: { all: 5 } }, { refreshing: true })] };
    const follow = { answers: [ok("1", "profile", { id: 1 }), ok("1", "subscriberCounts", { subscribers: { all: 6 } })] };
    const get = vi.fn(async (p: string) => (p.includes("accounts=") ? follow : stale));
    const keys: unknown[] = [];
    onScreenRefreshed((k) => keys.push(k));
    const counts = screenRead("/api/of/v2/subscriptions/count/all", "1")!;
    expect(await screenJoin(counts, get)).toEqual({ kind: "body", body: { subscribers: { all: 5 } }, refreshing: true });
    expect(await screenJoin(screenRead("/api/of/v2/users/me", "1")!, get)).toEqual({ kind: "body", body: { id: 1 }, refreshing: true });
    await vi.waitFor(() => expect(keys).toEqual([["of-sub-counts", "1"]]));   // the profile came back the same
    expect(await screenJoin(counts, get)).toEqual({ kind: "body", body: { subscribers: { all: 6 } } });
    expect(get.mock.calls.map((c) => c[0])).toEqual([bundlePath(DASH), followPath(DASH, ["1"])]);
  });

  it("serve-stale, the follow-up fails: the key is named, the flight dropped, the refetch reads its route", async () => {
    openScreen(DASH);
    const stale = { answers: [ok("1", "subscriberCounts", { subscribers: { all: 5 } }, { refreshing: true })] };
    const get = vi.fn(async (p: string) => { if (p.includes("accounts=")) throw new Error("timeout"); return stale; });
    const keys: unknown[] = [];
    onScreenRefreshed((k) => keys.push(k));
    const counts = screenRead("/api/of/v2/subscriptions/count/all", "1")!;
    expect(await screenJoin(counts, get)).toEqual({ kind: "body", body: { subscribers: { all: 5 } }, refreshing: true });
    await vi.waitFor(() => expect(keys).toEqual([["of-sub-counts", "1"]]));
    expect(screenBundleKeys()).toEqual([]);
    expect(await screenJoin(counts, get)).toEqual({ kind: "miss" });   // the invalidated refetch: per Creator
    expect(get).toHaveBeenCalledTimes(2);
    await screenJoin(counts, get);                                      // once: the next burst bundles again
    expect(get.mock.calls[2][0]).toBe(bundlePath(DASH));
  });

  it("serve-stale: no refreshing read joined (the cards' snapshot is fresh): no follow-up", async () => {
    openScreen(DASH);
    const get = vi.fn(async (_p: string) => ({ answers: [
      ok(null, "perModel", { per_model: [] }), ok("1", "subscriberCounts", { subscribers: { all: 5 } }, { refreshing: true })] }));
    await screenJoin(screenRead(`/admin/stats/per-model?${q({ from: DASH.from!, to: DASH.to! })}`, null)!, get);
    await new Promise((res) => setTimeout(res, FOLLOW_MS + 50));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("a failed follow-up is a miss", async () => {
    openScreen(DASH);
    const get = vi.fn(async (p: string) => { if (p.includes("accounts=")) throw new Error("502"); return DASH_BODY; });
    expect(await screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "2")!, get)).toEqual({ kind: "miss" });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("forgetScreenBundles (an identity switch): no read joins a bundle from before, in flight or landed", async () => {
    openScreen(DASH);
    const lands: ((b: unknown) => void)[] = [];
    const get = vi.fn(() => new Promise((res) => { lands.push(res); }));
    const counts = screenRead("/api/of/v2/subscriptions/count/all", "1")!;
    const before = screenJoin(counts, get);
    await Promise.resolve();
    forgetScreenBundles();
    const profile = screenJoin(screenRead("/api/of/v2/users/me", "1")!, get);   // a joiner: B's flight is gone
    const after = screenJoin(counts, get);                                       // a starter: a new bundle
    expect(get).toHaveBeenCalledTimes(2);
    lands[0]({ answers: [ok("1", "subscriberCounts", "B's"), ok("1", "profile", "B's")] });
    lands[1]({ answers: [ok("1", "subscriberCounts", "A's"), ok("1", "profile", "A's")] });
    expect(await before).toEqual({ kind: "body", body: "B's" });   // its own caller, already asked
    expect(await after).toEqual({ kind: "body", body: "A's" });
    expect(await profile).toEqual({ kind: "body", body: "A's" });
    forgetScreenBundles();
    expect(await screenJoin(screenRead("/api/of/v2/users/me", "1")!, get)).toEqual({ kind: "miss" });   // landed: gone too
  });

  it("prefetchScreen: started before the screen opens, its reads (shared ones too) join it; another key: its own", async () => {
    const lands = new Map<string, (b: unknown) => void>();
    const get = vi.fn((p: string) => new Promise((r) => { lands.set(p, r); }));
    const OTHER: Screen = { kind: "dashboard", from: "2026-01-01", to: null };
    prefetchScreen(DASH, get);
    prefetchScreen(DASH, get);                       // live: not twice
    prefetchScreen(OTHER, get);                      // a wrong guess: a flight nobody on DASH joins
    expect(get.mock.calls.map((c) => c[0])).toEqual([bundlePath(DASH), "/admin/screens/dashboard?from=2026-01-01"]);
    openScreen(DASH);
    const accounts = screenJoin(screenRead("/admin/accounts", null)!, get);
    const profile = screenJoin(screenRead("/api/of/v2/users/me", "1")!, get);
    const counts = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "1")!, get);
    lands.get(bundlePath(DASH))!(DASH_BODY);
    expect(await profile).toEqual({ kind: "body", body: { id: 1 } });
    expect(await counts).toEqual({ kind: "body", body: { subscribers: { all: 5 } } });
    expect(await accounts).toEqual({ kind: "body", body: { accounts: [{ id: "1" }] } });
    expect(get).toHaveBeenCalledTimes(2);           // they joined the prefetch: no bundle of their own
  });

  it("no open screen: nothing is a bundle read; an unmounted screen closes", () => {
    expect(screenRead(BELL, "1")).toBeNull();
    const h = openScreen(INBOX);
    expect(screenRead(BELL, "1")).not.toBeNull();
    h.unmount();
    expect(screenRead(BELL, "1")).toBeNull();
    openScreen(null);
    expect(screenRead(BELL, "1")).toBeNull();
  });
});
