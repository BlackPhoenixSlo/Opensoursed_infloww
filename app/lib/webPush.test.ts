/**
 * lib/webPush over fakes of the browser (serviceWorker.ready, PushManager,
 * Notification) and the relay (fetch, through the real lib/relay): the tap's
 * subscribe-first order (an unprimed tap fails at once and primes), key
 * rotation (found by the prime, dropped in the tap), the tap's PUT queued
 * behind a DELETE, the debounced lazy sync, the row's DELETE (the browser's
 * subscription kept), the forced re-PUT and a revoked session, logout's local
 * reset, the relay's 503 reason, the SW's messages and the push-notice ack,
 * and never in the shell.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { openNotification } = vi.hoisted(() => ({ openNotification: vi.fn() }));
vi.mock("@/lib/notificationLink", () => ({ openNotification }));

import { DEFAULT_NOTIF_SETTINGS, type NotifSettings } from "@/lib/notifSettings";
import {
  KEY_CHANGED,
  NOT_READY,
  SYNC_DEBOUNCE_MS,
  forgetPush,
  isPushLive,
  listenNotificationClicks,
  listenPushNotices,
  primePush,
  pushId,
  pushSupported,
  resetPushForTests,
  subscribePush,
  syncPush,
  testPush,
  unsubscribePush,
  usePushState,
  why,
} from "@/lib/webPush";
import { renderHook } from "@testing-library/react";

const keyBytes = (seed: number) => Uint8Array.from({ length: 65 }, (_, i) => (i * 7 + seed) % 256);
const b64url = (b: Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const KEY = keyBytes(1);
const OLD = keyBytes(2);

function fakeSub(k: Uint8Array, endpoint = "https://fcm.googleapis.com/fcm/send/abc") {
  return {
    endpoint,
    options: { applicationServerKey: k.slice().buffer },
    toJSON: () => ({ endpoint, keys: { p256dh: "P256", auth: "AUTH" } }),
    unsubscribe: vi.fn(async () => true),
  };
}

let pm: { subscribe: ReturnType<typeof vi.fn>; getSubscription: ReturnType<typeof vi.fn> };
let reg: { pushManager: typeof pm; showNotification: ReturnType<typeof vi.fn> };
let swListeners: Set<(e: MessageEvent) => void>;
let calls: { method: string; path: string; body: unknown }[];
let routes: Record<string, () => Response>;
const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });

const settings: NotifSettings = DEFAULT_NOTIF_SETTINGS; // message + purchases + tip + subscribed, osPing on
const off: NotifSettings = { ...DEFAULT_NOTIF_SETTINGS, osPing: false };

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "production");
  resetPushForTests();
  openNotification.mockClear();
  pm = { subscribe: vi.fn(async () => fakeSub(KEY)), getSubscription: vi.fn(async () => null) };
  reg = { pushManager: pm, showNotification: vi.fn(async () => undefined) };
  swListeners = new Set();
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      ready: Promise.resolve(reg),
      addEventListener: (_t: string, fn: (e: MessageEvent) => void) => swListeners.add(fn),
      removeEventListener: (_t: string, fn: (e: MessageEvent) => void) => swListeners.delete(fn),
      startMessages: vi.fn(),
    },
  });
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("Notification", { permission: "granted" });
  calls = [];
  routes = {
    "GET /push/key": json({ key: b64url(KEY) }),
    "PUT /push/subscription": json({ id: "sub-1" }),
    "DELETE /push/subscription": json({ ok: true }),
    "POST /push/test": json({ status: 201 }),
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = new URL(url, "http://app.test").pathname;
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return (routes[`${method} ${path}`] ?? json({ detail: "no route" }, 500))();
  }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  delete (window as { fasttShell?: unknown }).fasttShell;
});

const putBody = {
  endpoint: "https://fcm.googleapis.com/fcm/send/abc",
  keys: { p256dh: "P256", auth: "AUTH" },
  types: ["message", "purchases", "tip", "subscribed"],
  platforms: { onlyfans: true, fansly: true },
};

describe("subscribePush (a tap)", () => {
  it("with the key primed, calls pushManager.subscribe at once — inside the gesture — then PUTs", async () => {
    await primePush();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /push/key"]);
    const p = subscribePush(settings);
    expect(pm.subscribe).toHaveBeenCalledTimes(1); // synchronously: no await before it
    expect(pm.subscribe.mock.calls[0][0]).toMatchObject({ userVisibleOnly: true });
    expect(new Uint8Array(pm.subscribe.mock.calls[0][0].applicationServerKey)).toEqual(KEY);
    await expect(p).resolves.toBe("sub-1");
    expect(calls.at(-1)).toEqual({ method: "PUT", path: "/push/subscription", body: putBody });
    expect(isPushLive()).toBe(true);
    expect(pushId()).toBe("sub-1");
  });

  it("not primed yet: fails at once (no network, no await in the tap), primes, and the next tap subscribes", async () => {
    const err = await subscribePush(settings).catch((e) => e);
    expect(err.message).toBe(NOT_READY);
    expect(pm.subscribe).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /push/key"]));
    await primePush(); // the re-prime the tap started, settled
    const p = subscribePush(settings);
    expect(pm.subscribe).toHaveBeenCalledTimes(1);
    await expect(p).resolves.toBe("sub-1");
  });

  it("the relay's key changed (the prime saw it): the tap drops the old one and subscribes in the same tick", async () => {
    const old = fakeSub(OLD, "https://fcm.googleapis.com/fcm/send/old");
    pm.getSubscription.mockResolvedValue(old);
    await primePush();
    const p = subscribePush(settings);
    expect(old.unsubscribe).toHaveBeenCalledTimes(1);
    expect(pm.subscribe).toHaveBeenCalledTimes(1); // no await between the two
    await expect(p).resolves.toBe("sub-1");
    expect(calls.at(-1)?.body).toMatchObject({ endpoint: "https://fcm.googleapis.com/fcm/send/abc" });
  });

  it("the relay's key changed and the browser refused the same-tick subscribe: tap again, which subscribes", async () => {
    const old = fakeSub(OLD, "https://fcm.googleapis.com/fcm/send/old");
    pm.getSubscription.mockResolvedValue(old);
    pm.subscribe.mockRejectedValueOnce(new DOMException("key mismatch", "InvalidStateError"));
    await primePush();
    const err = await subscribePush(settings).catch((e) => e);
    expect(err.message).toBe(KEY_CHANGED);
    expect(old.unsubscribe).toHaveBeenCalledTimes(1);
    const p = subscribePush(settings);
    expect(pm.subscribe).toHaveBeenCalledTimes(2);
    await expect(p).resolves.toBe("sub-1");
    expect(old.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("an unprimed tap after a prime that failed without a relay reason: \"try again\", not the raw error", async () => {
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { ...navigator.serviceWorker, ready: Promise.reject(new Error("boom")) } });
    routes["GET /push/key"] = () => { throw new TypeError("Failed to fetch"); };
    await primePush();
    const err = await subscribePush(settings).catch((e) => e);
    expect(err.message).toBe(NOT_READY);
  });

  it("the old subscription's unsubscribe failed and the subscribe too: the real error, the stale one kept for the next tap", async () => {
    const old = fakeSub(OLD, "https://fcm.googleapis.com/fcm/send/old");
    old.unsubscribe.mockResolvedValue(false);
    pm.getSubscription.mockResolvedValue(old);
    const refused = new DOMException("key mismatch", "InvalidStateError");
    pm.subscribe.mockRejectedValueOnce(refused);
    await primePush();
    expect(await subscribePush(settings).catch((e) => e)).toBe(refused);
    old.unsubscribe.mockResolvedValue(true);
    await expect(subscribePush(settings)).resolves.toBe("sub-1");
    expect(old.unsubscribe).toHaveBeenCalledTimes(2); // still known stale: dropped again in the next tap
  });

  it("logout while the tap's PUT is in flight: its answer does not revive the id (in-page pings stay on)", async () => {
    await primePush();
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const fetchMock = vi.mocked(fetch);
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "PUT") await gate;
      return real(url as string, init);
    });
    const p = subscribePush(settings);
    await new Promise((r) => setTimeout(r, 10));
    forgetPush();
    release();
    await p;
    expect(isPushLive()).toBe(false);
    expect(pushId()).toBeNull();
  });

  it("the tap's PUT waits behind a DELETE already queued (one at a time, in call order)", async () => {
    pm.getSubscription.mockResolvedValue(fakeSub(KEY));
    await primePush();
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const fetchMock = vi.mocked(fetch);
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "DELETE") { await gate; return new Response(JSON.stringify({ ok: true })); }
      return real(url as string, init);
    });
    const del = unsubscribePush();
    const sub = subscribePush(settings);
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method === "PUT")).toEqual([]);
    release();
    await del;
    await expect(sub).resolves.toBe("sub-1");
    expect(isPushLive()).toBe(true);
  });

  it("logout while a tap's PUT waits behind a DELETE: the PUT is dropped, never sent, no id, no failure shown", async () => {
    pm.getSubscription.mockResolvedValue(fakeSub(KEY));
    await primePush();
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const fetchMock = vi.mocked(fetch);
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "DELETE") { await gate; return new Response(JSON.stringify({ ok: true })); }
      return real(url as string, init);
    });
    const del = unsubscribePush();
    const sub = subscribePush(settings);
    const dropped = expect(sub).rejects.toThrow();
    await new Promise((r) => setTimeout(r, 10));
    forgetPush();
    release();
    await del;
    await dropped;
    await settle();
    expect(calls.filter((c) => c.method === "PUT")).toEqual([]);
    expect(pushId()).toBeNull();
    const { result } = renderHook(() => usePushState());
    expect(result.current).toEqual({ id: null, failed: null });
  });

  it("GET /push/key 503 {reason}: the prime and the tap fail with the relay's reason, and it is the failure shown", async () => {
    routes["GET /push/key"] = json({ reason: "push disabled: no VAPID subject" }, 503);
    await primePush();
    const err = await subscribePush(settings).catch((e) => e);
    expect(why(err)).toBe("push disabled: no VAPID subject");
    const { result } = renderHook(() => usePushState());
    expect(result.current).toEqual({ id: null, failed: "push disabled: no VAPID subject" });
    expect(pm.subscribe).not.toHaveBeenCalled();
  });
});

/** Real macrotask turns (only setTimeout is faked): the queued fetches settle. */
async function settle() {
  for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
}

/** `syncPush`, its debounce run out, and its queued work settled. */
async function sync(s: NotifSettings, opts?: { force?: boolean }) {
  syncPush(s, opts);
  await vi.advanceTimersByTimeAsync(SYNC_DEBOUNCE_MS);
  await settle();
}

describe("syncPush (no gesture)", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }); });

  it("is debounced: three settings changes in a second are one PUT, with the last", async () => {
    const latest: NotifSettings = { ...settings, toast: { ...settings.toast, favorited: true } };
    syncPush(settings);
    await vi.advanceTimersByTimeAsync(SYNC_DEBOUNCE_MS / 2);
    syncPush(settings);
    await sync(latest);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(calls.at(-1)?.body).toMatchObject({ types: ["message", "purchases", "tip", "subscribed", "favorited"] });

    // The same prefs again: left alone. Forced (tab return, SSE reconnect): PUT again.
    await sync(latest);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    await sync(latest, { force: true });
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2);
  });

  it("a revoked session (PUT 401/404) is not live, so the page pings itself again", async () => {
    await sync(settings);
    expect(isPushLive()).toBe(true);
    routes["PUT /push/subscription"] = json({ detail: "not signed in" }, 401);
    await sync(settings, { force: true });
    expect(isPushLive()).toBe(false);
  });

  it("logout: no longer live at once, no network, and a pending sync is dropped", async () => {
    await sync(settings);
    expect(isPushLive()).toBe(true);
    const before = calls.length;
    syncPush(settings, { force: true });
    forgetPush();
    expect(isPushLive()).toBe(false);
    await vi.advanceTimersByTimeAsync(SYNC_DEBOUNCE_MS);
    await settle();
    expect(calls.length).toBe(before);
  });

  it("an old-key subscription is NOT unsubscribed without a gesture: not live, the hint shows", async () => {
    const old = fakeSub(OLD);
    pm.getSubscription.mockResolvedValue(old);
    await sync(settings);
    expect(old.unsubscribe).not.toHaveBeenCalled();
    expect(pm.subscribe).not.toHaveBeenCalled();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    expect(isPushLive()).toBe(false);
    const { result } = renderHook(() => usePushState());
    expect(result.current.failed).toMatch(/key changed/);
  });

  it("OS ping off: DELETEs the relay's row once; the browser's subscription stays", async () => {
    const sub = fakeSub(KEY);
    pm.getSubscription.mockResolvedValue(sub);
    await sync(settings);
    expect(isPushLive()).toBe(true);

    for (let i = 0; i < 2; i++) await sync(off);
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([
      { method: "DELETE", path: "/push/subscription", body: { endpoint: sub.endpoint } },
    ]);
    expect(sub.unsubscribe).not.toHaveBeenCalled();
    expect(isPushLive()).toBe(false);
  });

  it("permission not granted: nothing is subscribed or sent", async () => {
    vi.stubGlobal("Notification", { permission: "default" });
    await sync(settings);
    expect(pm.subscribe).not.toHaveBeenCalled();
    expect(calls).toEqual([]);
  });
});

describe("testPush", () => {
  it("asks the relay to push this subscription in N s; refused while not live", async () => {
    await expect(testPush(8)).rejects.toThrow(/push is off/);
    await primePush();
    await subscribePush(settings);
    await expect(testPush(8)).resolves.toEqual({ status: 201 });
    expect(calls.at(-1)).toEqual({ method: "POST", path: "/push/test", body: { id: "sub-1", delay_s: 8 } });
  });
});

describe("never in the desktop app", () => {
  it("the shell notifies natively: unsupported, and nothing reaches the relay", async () => {
    (window as { fasttShell?: unknown }).fasttShell = { notify: vi.fn() };
    expect(pushSupported()).toBe(false);
    syncPush(settings);
    await unsubscribePush();
    await primePush();
    await expect(subscribePush(settings)).rejects.toThrow(/not supported/);
    expect(calls).toEqual([]);
    expect(pm.subscribe).not.toHaveBeenCalled();
  });
});

describe("the service worker's messages", () => {
  const port = () => ({ postMessage: vi.fn() });
  const send = (data: unknown, ports: unknown[] = []) =>
    swListeners.forEach((fn) => fn(new MessageEvent("message", { data, ports: ports as MessagePort[] })));

  it("listenNotificationClicks: a click opens its link; an off-site one and anything else are ignored", () => {
    const off = listenNotificationClicks();
    send({ type: "open-notification", href: "/messages-pro/a/5?fanTab=Jim" });
    send({ type: "open-notification", href: "https://evil.example/" });
    send({ type: "push-notice", payload: { tag: "a:m1" } });
    send("junk");
    expect(openNotification.mock.calls).toEqual([["/messages-pro/a/5?fanTab=Jim"]]);
    off();
    expect(swListeners.size).toBe(0);
  });

  it.each([
    // [label, onNotice, the answer on the port]
    ["taken: acked", () => true, true],
    ["not taken (out of scope): nacked, the worker shows it", () => false, false],
    ["onNotice throws: nacked", () => { throw new Error("boom"); }, false],
  ])("listenPushNotices: %s", (_l, impl, answer) => {
    const onNotice = vi.fn(impl);
    const off = listenPushNotices(onNotice);
    const p = port();
    try { send({ type: "push-notice", payload: { tag: "a:m1" } }, [p]); } catch { /* the throw case */ }
    send({ type: "open-notification", href: "/x" });
    expect(onNotice.mock.calls).toEqual([[{ tag: "a:m1" }]]);
    expect(p.postMessage.mock.calls).toEqual([[answer]]);
    expect(openNotification).not.toHaveBeenCalled();
    off();
  });
});
