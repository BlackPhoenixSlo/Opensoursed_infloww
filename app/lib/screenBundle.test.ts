import { afterEach, describe, expect, it, vi } from "vitest";

import {
  bundlePath, classify, FOLLOW_DEADLINE_MS, FOLLOW_MS, followPath, KEEP_MS, onScreenRefreshed, outcome, prefetchScreen, resetScreenBundles, screenJoin, screenRead, screenSettled, setScreen, type Read, type Screen,
} from "./screenBundle";

const DASH: Screen = { kind: "dashboard", from: "2026-10-01T00:00:00Z", to: "2026-11-01T00:00:00Z" };
const INBOX: Screen = { kind: "inbox" };
const DK = "dashboard|2026-10-01T00:00:00Z|2026-11-01T00:00:00Z";
const q = (o: Record<string, string>) => new URLSearchParams(o).toString();

describe("classify", () => {
  it.each<[string, string, string | null, Screen, Partial<Read> | null]>([
    ["profile joins only", "/api/of/v2/users/me", "1", DASH, { field: "profile", starter: false, bundle: DK }],
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
    ["the bell on the Dashboard", "/api/of/v2/users/notifications/count", "1", DASH, null],
    ["the bell", "/api/of/v2/users/notifications/count", "1", INBOX,
      { field: "notificationCounts", starter: true, bundle: null }],
    ["chat page 2", "/api/of/v2/chats?limit=25&offset=25&order=recent", "1", INBOX,
      { field: "chats", starter: true, bundle: "inbox|25" }],
    ["a filtered page", "/api/of/v2/chats?limit=25&offset=0&order=recent&filter=unread", "1", INBOX, null],
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
    expect(bundlePath(DK)).toBe(`/admin/screens/dashboard?${q({ from: DASH.from!, to: DASH.to! })}`);
    expect(bundlePath("dashboard||")).toBe("/admin/screens/dashboard");
    expect(bundlePath("inbox|25")).toBe("/admin/screens/inbox?cursor=25");
    expect(followPath("inbox|25", ["1", "2"]))
      .toBe(`/admin/screens/inbox?cursor=25&accounts=1%2C2&deadline_ms=${FOLLOW_DEADLINE_MS}`);
  });
});

const r = (field: Read["field"], accountId: string | null): Read => ({ field, accountId, starter: true, bundle: null });
const LATE = { status: 504, detail: { upstream_status: "bundle_deadline" } };
const DASH_BODY = {
  settings: { s: 1 }, accounts: { accounts: [{ id: "1" }] }, perModel: { per_model: [] },
  creators: [
    { id: "1", profile: { id: 1 }, subscriberCounts: { subscribers: { all: 5 } }, newFans: { subscribers: 2 }, stale: false },
    { id: "2", profile: { id: 2 }, subscriberCounts: null, newFans: null, stale: true },
    { id: "3", profile: null, subscriberCounts: null, newFans: null, stale: false },
    { id: "4", profile: { id: 4 }, stale: false },  // a hidden Per-model card: profile only
  ],
  errors: [
    { accountId: "2", read: "subscriberCounts", ...LATE },
    { accountId: "2", read: "newFans", ...LATE },
    { accountId: "3", read: "profile", status: 403, detail: "not yours" },
    { accountId: "3", read: "subscriberCounts", status: 502, detail: { upstream_status: 500 } },
  ],
};
const INBOX_BODY = {
  accounts: { accounts: [] }, notificationCounts: { 1: { all: 3 } }, chats: { 1: { list: [], hasMore: false } },
  stale: ["2"], errors: [{ accountId: "2", read: "chats", ...LATE }, { accountId: "3", read: "chats", status: 503, detail: "x" }],
};

describe("outcome", () => {
  it.each<[string, unknown, Read, unknown]>([
    ["a value", DASH_BODY, r("subscriberCounts", "1"), { kind: "body", body: { subscribers: { all: 5 } } }],
    ["a stale Creator's finished read", DASH_BODY, r("profile", "2"), { kind: "body", body: { id: 2 } }],
    ["a late read: the follow-up's", DASH_BODY, r("subscriberCounts", "2"), { kind: "late" }],
    ["a role refusal: the route's", DASH_BODY, r("profile", "3"), { kind: "error", status: 403, detail: "not yours" }],
    ["OF's error", DASH_BODY, r("subscriberCounts", "3"), { kind: "error", status: 502, detail: { upstream_status: 500 } }],
    ["a null with no error", DASH_BODY, r("newFans", "3"), { kind: "miss" }],
    ["a field not read (hidden card)", DASH_BODY, r("subscriberCounts", "4"), { kind: "miss" }],
    ["a Creator not in the bundle", DASH_BODY, r("profile", "9"), { kind: "miss" }],
    ["per-model", DASH_BODY, r("perModel", null), { kind: "body", body: { per_model: [] } }],
    ["per-model absent", { ...DASH_BODY, perModel: null }, r("perModel", null), { kind: "miss" }],
    ["accounts", DASH_BODY, r("accounts", null), { kind: "body", body: { accounts: [{ id: "1" }] } }],
    ["a chatter's accounts (a list)", { ...DASH_BODY, accounts: [] }, r("accounts", null), { kind: "miss" }],
    ["settings", DASH_BODY, r("settings", null), { kind: "body", body: { s: 1 } }],
    ["the bell", INBOX_BODY, r("notificationCounts", "1"), { kind: "body", body: { all: 3 } }],
    ["a chat page", INBOX_BODY, r("chats", "1"), { kind: "body", body: { list: [], hasMore: false } }],
    ["a late chat page", INBOX_BODY, r("chats", "2"), { kind: "late" }],
    ["no session", INBOX_BODY, r("chats", "3"), { kind: "error", status: 503, detail: "x" }],
    ["a failed bundle", null, r("chats", "1"), { kind: "miss" }],
  ])("%s", (_n, body, read, want) => expect(outcome(body, read)).toEqual(want));
});

describe("screenJoin", () => {
  afterEach(() => { resetScreenBundles(); vi.useRealTimers(); });

  it("one bundle for a screen's burst; a joiner fired first waits a task for the starter", async () => {
    setScreen(DASH);
    const get = vi.fn(async (_p: string) => DASH_BODY);
    const profile = screenRead("/api/of/v2/users/me", "1")!;
    const counts = screenRead("/api/of/v2/subscriptions/count/all", "1")!;
    const p1 = screenJoin(profile, get);
    const p2 = screenJoin(counts, get);
    const p3 = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "2")!, get);
    expect(await p1).toEqual({ kind: "body", body: { id: 1 } });
    expect(await p2).toEqual({ kind: "body", body: { subscribers: { all: 5 } } });
    expect(await p3).toEqual({ kind: "miss" });   // late, and late again in its follow-up
    expect(get.mock.calls.map((c) => c[0])).toEqual([
      `/admin/screens/dashboard?${q({ from: DASH.from!, to: DASH.to! })}`, followPath(DK, ["2"])]);
  });

  it("screenSettled: at once with no bundle; else when the first call lands (not its follow-up); abortable", async () => {
    setScreen(DASH);
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

  it("a joiner alone never starts a bundle", async () => {
    setScreen(DASH);
    const get = vi.fn(async () => DASH_BODY);
    expect(await screenJoin(screenRead("/api/of/v2/users/me", "1")!, get)).toEqual({ kind: "miss" });
    expect(get).not.toHaveBeenCalled();
  });

  it("a landed bundle serves joins for KEEP_MS, then the next burst starts another", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    setScreen(INBOX);
    const get = vi.fn(async () => INBOX_BODY);
    const bell = screenRead("/api/of/v2/users/notifications/count", "1")!;
    await screenJoin(bell, get);
    vi.setSystemTime(Date.now() + KEEP_MS - 10);
    await screenJoin(screenRead("/api/of/v2/chats?limit=25&offset=0&order=recent", "1")!, get);
    expect(get).toHaveBeenCalledTimes(1);
    vi.setSystemTime(Date.now() + 50);
    await screenJoin(bell, get);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("a failed bundle: every read goes out per Creator", async () => {
    setScreen(INBOX);
    const get = vi.fn(async () => { throw new Error("502"); });
    expect(await screenJoin(screenRead("/api/of/v2/users/notifications/count", "1")!, get)).toEqual({ kind: "miss" });
  });

  it("an aborted joiner rejects; the bundle still serves the others", async () => {
    setScreen(INBOX);
    let land!: (b: unknown) => void;
    const get = vi.fn(() => new Promise((res) => { land = res; }));
    const ac = new AbortController();
    const a = screenJoin(screenRead("/api/of/v2/users/notifications/count", "1")!, get, ac.signal);
    const b = screenJoin(screenRead("/api/of/v2/chats?limit=25&offset=0&order=recent", "1")!, get);
    ac.abort(new DOMException("gone", "AbortError"));
    await expect(a).rejects.toThrow("gone");
    land(INBOX_BODY);
    expect(await b).toEqual({ kind: "body", body: { list: [], hasMore: false } });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("late reads share ONE follow-up naming only the late Creators, the same cursor; no per-Creator read", async () => {
    setScreen(INBOX);
    const base = { ...INBOX_BODY, stale: ["2", "4"], errors: [
      { accountId: "2", read: "chats", ...LATE }, { accountId: "4", read: "notificationCounts", ...LATE },
      { accountId: "4", read: "chats", ...LATE }] };
    const follow = { chats: { 2: { list: [{ id: 2 }] }, 4: { list: [] } }, notificationCounts: {},
      errors: [{ accountId: "4", read: "notificationCounts", ...LATE }] };
    const get = vi.fn(async (p: string) => (p.includes("accounts=") ? follow : base));
    const page = (aid: string) => screenJoin(screenRead("/api/of/v2/chats?limit=25&offset=0&order=recent", aid)!, get);
    const [two, four, bell4, one] = await Promise.all([page("2"), page("4"),
      screenJoin(screenRead("/api/of/v2/users/notifications/count", "4")!, get), page("1")]);
    expect(one).toEqual({ kind: "body", body: { list: [], hasMore: false } });
    expect(two).toEqual({ kind: "body", body: { list: [{ id: 2 }] } });
    expect(four).toEqual({ kind: "body", body: { list: [] } });
    expect(bell4).toEqual({ kind: "miss" });   // still late after the follow-up: per Creator
    expect(get.mock.calls.map((c) => c[0])).toEqual(["/admin/screens/inbox?cursor=0", followPath("inbox|0", ["2", "4"])]);
  });

  it("serve-stale: a refreshing read answers at once, ONE follow-up; a changed value names its key, whose refetch gets the follow-up's", async () => {
    setScreen(DASH);
    const stale = { ...DASH_BODY, errors: [],
      refreshing: [{ accountId: "1", read: "subscriberCounts" }, { accountId: "1", read: "profile" }] };
    const follow = { creators: [{ id: "1", profile: { id: 1 }, subscriberCounts: { subscribers: { all: 6 } } }],
      errors: [], refreshing: [] };
    const get = vi.fn(async (p: string) => (p.includes("accounts=") ? follow : stale));
    const keys: unknown[] = [];
    onScreenRefreshed((k) => keys.push(k));
    const counts = screenRead("/api/of/v2/subscriptions/count/all", "1")!;
    expect(await screenJoin(counts, get)).toEqual({ kind: "body", body: { subscribers: { all: 5 } } });
    expect(await screenJoin(screenRead("/api/of/v2/users/me", "1")!, get)).toEqual({ kind: "body", body: { id: 1 } });
    await vi.waitFor(() => expect(keys).toEqual([["of-sub-counts", "1"]]));   // the profile came back the same
    expect(await screenJoin(counts, get)).toEqual({ kind: "body", body: { subscribers: { all: 6 } } });
    expect(get.mock.calls.map((c) => c[0])).toEqual([bundlePath(DK), followPath(DK, ["1"])]);
  });

  it("serve-stale: no refreshing read joined (the cards' snapshot is fresh): no follow-up", async () => {
    setScreen(DASH);
    const get = vi.fn(async (_p: string) => ({ ...DASH_BODY, errors: [], refreshing: [{ accountId: "1", read: "subscriberCounts" }] }));
    await screenJoin(screenRead(`/admin/stats/per-model?${q({ from: DASH.from!, to: DASH.to! })}`, null)!, get);
    await new Promise((res) => setTimeout(res, FOLLOW_MS + 50));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("a failed follow-up is a miss", async () => {
    setScreen(DASH);
    const get = vi.fn(async (p: string) => { if (p.includes("accounts=")) throw new Error("502"); return DASH_BODY; });
    expect(await screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "2")!, get)).toEqual({ kind: "miss" });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("prefetchScreen: started before the screen opens, its reads (shared ones too) join it; another key: its own", async () => {
    const lands = new Map<string, (b: unknown) => void>();
    const get = vi.fn((p: string) => new Promise((r) => { lands.set(p, r); }));
    const OTHER: Screen = { kind: "dashboard", from: "2026-01-01", to: null };
    prefetchScreen(DASH, get);
    prefetchScreen(DASH, get);                       // live: not twice
    prefetchScreen(OTHER, get);                      // a wrong guess: a flight nobody on DASH joins
    expect(get.mock.calls.map((c) => c[0])).toEqual([bundlePath(DK), "/admin/screens/dashboard?from=2026-01-01"]);
    setScreen(DASH);
    const accounts = screenJoin(screenRead("/admin/accounts", null)!, get);
    const profile = screenJoin(screenRead("/api/of/v2/users/me", "1")!, get);
    const counts = screenJoin(screenRead("/api/of/v2/subscriptions/count/all", "1")!, get);
    lands.get(bundlePath(DK))!(DASH_BODY);
    expect(await profile).toEqual({ kind: "body", body: { id: 1 } });
    expect(await counts).toEqual({ kind: "body", body: { subscribers: { all: 5 } } });
    expect(await accounts).toEqual({ kind: "body", body: DASH_BODY.accounts });
    expect(get).toHaveBeenCalledTimes(2);           // they joined the prefetch: no bundle of their own
  });

  it("no open screen: nothing is a bundle read", () => {
    setScreen(null);
    expect(screenRead("/api/of/v2/users/notifications/count", "1")).toBeNull();
  });
});
