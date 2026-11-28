import { cleanup, renderHook } from "@testing-library/react";
import { resetCellFlagForTests } from "@/lib/cellFlag";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  nextGen, API_KEY_ERROR_EVENT, ApiKeyError, RelayError, STALE_CELL_GEN_EVENT, chatListRetry, describeLoadError, isDeepRefused,
  isRateLimited, isUnknownAccount, prefetchScreenBundle, relay, relayFile, request, resetCellGens,
  type ApiKeyErrorPayload,
} from "@/lib/relay";
import { resetInline, seedInline } from "@/lib/inlineBoot";
import { ACTOR_RENEW_MS, resetActorRenewal } from "@/lib/actorRenew";
import { BUNDLE_TIMEOUT_MS, resetScreenBundles, useScreen } from "@/lib/screenBundle";
import { bundlePath, type Screen } from "@/lib/screenKey";

const INBOX: Screen = { kind: "inbox", cursor: 0 };

const err = (m: string) => new Error(m);

describe("describeLoadError", () => {
  it("reads the real 404 body a deleted fan produces", () => {
    const raw = 'upstream 404: {"error":{"code":0,"message":"User not found"}}';
    const out = describeLoadError(err(raw), "This fan's OnlyFans account no longer exists.");
    expect(out).toBe("This fan's OnlyFans account no longer exists.");
    expect(out).not.toContain('{"error"');
    expect(out).not.toContain("upstream");
  });

  it("defaults a 404 to wording that is true ANYWHERE", () => {
    expect(describeLoadError(err("upstream 404: nope"))).toBe("OnlyFans no longer has this.");
  });

  it("separates the transient failures, because those ARE worth retrying", () => {
    expect(describeLoadError(err("upstream timeout: ..."))).toContain("timed out");
    expect(describeLoadError(err("upstream proxy_unreachable: ..."))).toContain("Can't reach");
    expect(describeLoadError(err("upstream network: ..."))).toContain("Can't reach");
    expect(describeLoadError(err("upstream 401: Access denied"))).toContain("session expired");
    expect(describeLoadError(err("upstream 403: Access denied"))).toContain("session expired");
  });

  it("never claims a transient failure is permanent", () => {
    for (const m of ["upstream timeout: x", "upstream 401: x", "upstream network: x"]) {
      expect(describeLoadError(err(m), "GONE")).not.toBe("GONE");
    }
  });

  it("passes an unrecognised error through rather than swallowing it", () => {
    expect(describeLoadError(err("HTTP 500"))).toBe("Couldn't refresh: HTTP 500");
  });

  const OF_429 = 'upstream 429: {"error":{"code":0,"message":"Too many requests. Please allow 1 seconds.","payload":{"retry":1}}}';
  const rateLimit = new RelayError(502, { detail: { upstream_status: 429, upstream_body: "busy" } }, OF_429);
  it("renders structured upstream throttling without promising another retry", () => {
    expect(describeLoadError(rateLimit)).toBe("OnlyFans is busy. Try again shortly.");
  });
  it.each([
    ['upstream 500: {"error":{"code":0,"message":"Something broke"}}', "Couldn't refresh: Something broke"],
    ["upstream 4290: x", "Couldn't refresh: upstream 4290: x"],
  ])("%s -> %s (never the raw JSON)", (raw, want) => {
    const out = describeLoadError(err(raw), "GONE");
    expect(out).toBe(want);
    expect(out).not.toContain("{");
  });

  it.each([
    [err(OF_429), false],
    [new RelayError(429, null), true],
    [rateLimit, true],
    [err("upstream 404: x"), false],
    [err("HTTP 500"), false],
    [null, false],
    [undefined, false],
  ])("isRateLimited(%s) = %s", (e, want) => {
    expect(isRateLimited(e)).toBe(want);
  });

  it("survives a null/blank error without rendering 'undefined'", () => {
    expect(describeLoadError(null)).toBe("Couldn't refresh: unknown error");
    expect(describeLoadError(undefined)).toBe("Couldn't refresh: unknown error");
    expect(describeLoadError({})).toBe("Couldn't refresh: unknown error");
  });
});


const KEY_PAYLOAD: ApiKeyErrorPayload = {
  error: "api_key_invalid", feature: "Vault describe", provider: "deepinfra",
  fix_url: "/settings/ai-keys",
  message: "Vault describe stopped: DeepInfra rejected the API key (wrong or revoked).",
  fix: "Paste the right key in Settings › AI keys.",
};

function answer(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

describe("parseResponse › API-key errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("maps a 424 api_key_* body to ApiKeyError carrying the relay's payload", async () => {
    answer(424, { detail: KEY_PAYLOAD });
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(API_KEY_ERROR_EVENT, on);
    const err = (await relay.post("/admin/vault-ai/describe", { account_id: "a", media_id: 1 })
      .catch((e: unknown) => e)) as ApiKeyError;
    window.removeEventListener(API_KEY_ERROR_EVENT, on);

    expect(err).toBeInstanceOf(ApiKeyError);
    expect(err).toBeInstanceOf(RelayError);
    expect(err.status).toBe(424);
    expect(err.payload).toEqual(KEY_PAYLOAD);
    expect(err.message).toBe(KEY_PAYLOAD.message);
    expect(seen).toEqual([KEY_PAYLOAD]);
  });

  it("leaves every other error a plain RelayError, with no toast", async () => {
    answer(429, { detail: { error: "daily_cap_reached" } });
    const on = vi.fn();
    window.addEventListener(API_KEY_ERROR_EVENT, on);
    const err = await relay.get("/x").catch((e: unknown) => e);
    window.removeEventListener(API_KEY_ERROR_EVENT, on);
    expect(err).toBeInstanceOf(RelayError);
    expect(err).not.toBeInstanceOf(ApiKeyError);
    expect(on).not.toHaveBeenCalled();
  });
});


describe("request › cache mode", () => {
  afterEach(() => vi.unstubAllGlobals());
  const modeOf = async (ctx?: Parameters<typeof relay.get>[1], init: RequestInit = { method: "GET" }) => {
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await request("/api/of/v2/users/me", init, ctx);
    return (f.mock.calls[0] as unknown as [string, RequestInit])[1].cache;
  };

  it("sends a Creator-scoped call with cache: no-store, so N Creators' calls run in parallel", async () => {
    expect(await modeOf({ accountId: "123" })).toBe("no-store");
  });

  it("reads the scope from the sent headers, so a caller's own X-Account-Id skips the cache too", async () => {
    expect(await modeOf(undefined, { method: "GET", headers: { "X-Account-Id": "123" } })).toBe("no-store");
  });

  it("lets a caller's own init.cache win", async () => {
    expect(await modeOf({ accountId: "123" }, { method: "GET", cache: "default" })).toBe("default");
  });

  it("leaves an unscoped call on the browser's default cache", async () => {
    expect(await modeOf()).toBeUndefined();
  });
});

describe("request › maxAge", () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each<[string, string, number | undefined, string]>([
    ["appended", "/api/of/v2/users/me", 1800, "/api/of/v2/users/me?max_age=1800"],
    ["absent", "/api/of/v2/users/me", undefined, "/api/of/v2/users/me"],
    ["a caller's own wins", "/api/of/v2/users/me?max_age=60", 1800, "/api/of/v2/users/me?max_age=60"],
  ])("%s", async (_name, path, maxAge, want) => {
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await request(path, { method: "GET" }, { accountId: "123", maxAge });
    expect((f.mock.calls[0] as unknown as [string])[0]).toMatch(new RegExp(`${want.replace("?", "\\?")}$`));
  });
});

describe("request › a failed screen bundle's reads keep a slot (slop fan-list-chips 2026-11-07)", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); resetScreenBundles(); });

  it("two hung rail feeds of a Creator never hold back its chat list once the bundle failed", async () => {
    const sent: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      sent.push(url.split("?")[0]);
      if (url.startsWith("/admin/screens/")) return Promise.resolve(new Response("{}", { status: 404 }));
      if (url.startsWith("/api/of/v2/chats")) return Promise.resolve(new Response('{"list":[],"hasMore":false}'));
      return new Promise<Response>(() => {});
    }));
    renderHook(() => useScreen(INBOX));
    await prefetchScreenBundle(INBOX);
    const bg = { accountId: "a", priority: "background" as const };
    void relay.get("/api/of/v2/users/notifications?limit=10", bg);
    void relay.get("/api/of/v2/users/notifications?limit=10&type=tip", bg);
    await expect(relay.get("/api/of/v2/chats?limit=25&offset=0&order=recent", bg))
      .resolves.toEqual({ list: [], hasMore: false });
    expect(sent).toEqual(["/admin/screens/inbox", "/api/of/v2/users/notifications", "/api/of/v2/chats"]);
  });

  it("a hung bundle times out at BUNDLE_TIMEOUT_MS: the screen's reads go out per Creator", async () => {
    const timer = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(timer.signal);
    const sent: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
      sent.push(url.split("?")[0]);
      if (url.startsWith("/admin/screens/")) {
        return new Promise<Response>((_, rej) => init.signal!.addEventListener("abort", () => rej(init.signal!.reason)));
      }
      return Promise.resolve(new Response('{"list":[],"hasMore":false}'));
    }));
    renderHook(() => useScreen(INBOX));
    const page = relay.get("/api/of/v2/chats?limit=25&offset=0&order=recent", { accountId: "a" });
    await vi.waitFor(() => expect(sent).toEqual(["/admin/screens/inbox"]));
    expect(timeout).toHaveBeenCalledWith(BUNDLE_TIMEOUT_MS);
    timer.abort(new DOMException("timed out", "TimeoutError"));
    await expect(page).resolves.toEqual({ list: [], hasMore: false });
    expect(sent).toEqual(["/admin/screens/inbox", "/api/of/v2/chats"]);
  });

  it("a stalled inline bundle answer times out at BUNDLE_TIMEOUT_MS too: a miss, the read goes out per Creator", async () => {
    const timer = new AbortController();
    vi.spyOn(AbortSignal, "timeout").mockReturnValue(timer.signal);
    const sent: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (!url.includes("/notifications")) sent.push(url.split("?")[0]);
      return Promise.resolve(new Response('{"list":[],"hasMore":false}'));
    }));
    try {
      seedInline({ [bundlePath(INBOX)]: new Promise(() => {}) });
      renderHook(() => useScreen(INBOX));
      const page = relay.get("/api/of/v2/chats?limit=25&offset=0&order=recent", { accountId: "a" });
      await new Promise((r) => setTimeout(r, 0));
      expect(sent).toEqual([]);
      timer.abort(new DOMException("timed out", "TimeoutError"));
      await expect(page).resolves.toEqual({ list: [], hasMore: false });
      expect(sent).toEqual(["/api/of/v2/chats"]);
    } finally {
      resetInline();
    }
  });

  it.each([
    { name: "a slow bundle (5 s, past the old 3 s) still answers: no per-Creator read", answerMs: 5_000 as number | null },
    { name: "a true hang is a miss at BUNDLE_TIMEOUT_MS: the read goes out per Creator", answerMs: null },
  ])("$name", async ({ answerMs }) => {
    vi.useFakeTimers();
    try {
      vi.spyOn(AbortSignal, "timeout").mockImplementation((ms) => {
        const c = new AbortController();
        setTimeout(() => c.abort(new DOMException("timed out", "TimeoutError")), ms);
        return c.signal;
      });
      const bundle = { answers: [{ accountId: "a", read: "chats", body: { list: ["b"], hasMore: false } }] };
      const sent: string[] = [];
      vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
        if (!url.includes("/notifications")) sent.push(url.split("?")[0]);
        if (!url.startsWith("/admin/screens/")) return Promise.resolve(new Response('{"list":[],"hasMore":false}'));
        return new Promise<Response>((res, rej) => {
          init.signal!.addEventListener("abort", () => rej(init.signal!.reason));
          if (answerMs != null) setTimeout(() => res(new Response(JSON.stringify(bundle))), answerMs);
        });
      }));
      renderHook(() => useScreen(INBOX));
      const page = relay.get("/api/of/v2/chats?limit=25&offset=0&order=recent", { accountId: "a" });
      await vi.advanceTimersByTimeAsync(answerMs ?? BUNDLE_TIMEOUT_MS - 1);
      if (answerMs == null) {
        expect(sent).toEqual(["/admin/screens/inbox"]);
        await vi.advanceTimersByTimeAsync(1);
      }
      await expect(page).resolves.toEqual(answerMs != null ? bundle.answers[0].body : { list: [], hasMore: false });
      expect(sent).toEqual(answerMs != null ? ["/admin/screens/inbox"] : ["/admin/screens/inbox", "/api/of/v2/chats"]);
    } finally {
      vi.useRealTimers();
    }
  });
});


describe("chat-list caller and intent", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); resetScreenBundles(); });
  const CHATS = "/api/of/v2/chats?limit=25&offset=100&order=recent";
  const sentWith = () => {
    const sent: Array<{ path: string; caller: string | null; intent: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      const h = new Headers(init.headers);
      sent.push({ path: url.split("?")[0], caller: h.get("X-List-Caller"), intent: h.get("X-List-Intent") });
      return new Response(url.startsWith("/admin/screens/") ? '{"answers":[]}' : '{"list":[],"hasMore":false}');
    }));
    return sent;
  };

  it.each<[string, Parameters<typeof relay.get>[1], string | null, string | null]>([
    ["untagged", { accountId: "a" }, null, null],
    ["caller only", { accountId: "a", caller: "autofill" }, "autofill", null],
    ["caller and explicit intent", { accountId: "a", caller: "loadmore", intent: "explicit" }, "loadmore", "explicit"],
  ])("headers: %s", async (_n, ctx, caller, intent) => {
    const sent = sentWith();
    await relay.get(CHATS, ctx);
    expect(sent).toEqual([{ path: "/api/of/v2/chats", caller, intent }]);
  });

  it("an explicit read skips the screen bundle; an automatic one starts it, and the bundle carries its caller", async () => {
    const sent = sentWith();
    renderHook(() => useScreen(INBOX));
    await relay.get(CHATS, { accountId: "a", caller: "scroll", intent: "explicit" });
    expect(sent).toEqual([{ path: "/api/of/v2/chats", caller: "scroll", intent: "explicit" }]);
    sent.length = 0;
    await relay.get(CHATS, { accountId: "a", caller: "replay" });
    expect(sent[0]).toEqual({ path: "/admin/screens/inbox", caller: "replay", intent: null });
  });

  const refused = new RelayError(428, { detail: "Reload the page to load older chats." });
  const busy = new RelayError(502, { detail: { upstream_status: 429, upstream_body: "busy" } });
  it.each<[string, unknown, number, boolean, boolean]>([
    ["428 refused", refused, 0, true, false],
    ["429 busy", busy, 0, false, false],
    ["other error, first failure", new RelayError(502, {}), 0, false, true],
    ["other error, second failure", new RelayError(502, {}), 1, false, false],
    ["unknown account", new RelayError(404, { detail: { error: "unknown_account", message: "Unknown account_id '1'" } }), 0, false, false],
    ["other 404", new RelayError(404, { detail: "Not Found" }), 0, false, true],
  ])("%s: deep refused %s, retried %s", (name, e, failures, deep, retried) => {
    expect(isDeepRefused(e)).toBe(deep);
    expect(isUnknownAccount(e)).toBe(name === "unknown account");
    expect(chatListRetry(failures, e)).toBe(retried);
  });
});

describe("request › background queue", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    { name: "an unqueued read goes out at once, still X-Priority: background", unqueued: true, sent: true },
    { name: "a normal background read waits for a slot", unqueued: false, sent: false },
  ])("$name", async ({ unqueued, sent }) => {
    const ac = new AbortController();
    const f = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_, reject) => {
      if (init.signal?.aborted) reject(init.signal.reason);
      init.signal?.addEventListener("abort", () => reject(init.signal!.reason), { once: true });
    }));
    vi.stubGlobal("fetch", f);
    const bg = { accountId: "q1", priority: "background" } as const;
    const calls = [
      request("/api/of/v2/payouts/transactions", { signal: ac.signal }, bg),
      request("/api/of/v2/payouts/tips", { signal: ac.signal }, bg),
      request("/api/of/v2/payouts/chargebacks", { signal: ac.signal }, bg),
      request("/api/of/v2/lists", { signal: ac.signal }, { ...bg, unqueued }),
    ].map((p) => p.catch(() => null));
    try {
      await vi.waitFor(() => expect(f.mock.calls.length).toBeGreaterThanOrEqual(1));
      for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
      const payouts = f.mock.calls.filter((c) => c[0].includes("/payouts/")).length;
      expect(payouts).toBeGreaterThanOrEqual(1);
      expect(payouts).toBeLessThan(3);
      const q = f.mock.calls.find((c) => c[0] === "/api/of/v2/lists");
      expect(!!q).toBe(sent);
      if (q) expect(new Headers(q[1].headers).get("X-Priority")).toBe("background");
    } finally {
      ac.abort();
      await Promise.all(calls);
    }
  });
});

describe("cell mode", () => {
  const meta = () => {
    const m = document.createElement("meta");
    m.name = "oi-cells";
    document.head.append(m);
    resetCellFlagForTests();
  };
  const answer = (gen: string | null, status = 200, body: unknown = {}) =>
    vi.fn(async (_u: string, _i: RequestInit) => new Response(JSON.stringify(body), {
      status, headers: gen ? { "X-Cell-Gen": gen } : {},
    }));
  const relayCalls = (f: ReturnType<typeof answer>) => f.mock.calls.filter((c) => !c[0].startsWith("/auth/actor") && !c[0].startsWith("/auth/cells"));
  afterEach(() => {
    document.head.querySelectorAll('meta[name="oi-cells"]').forEach((m) => m.remove());
    resetCellFlagForTests();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    resetCellGens();
    resetActorRenewal();
  });

  const byUrl = (routes: Record<string, number[]>) => vi.fn(async (u: string, _i: RequestInit) => {
    const key = Object.keys(routes).find((k) => u.startsWith(k))!;
    const status = routes[key].length > 1 ? routes[key].shift()! : routes[key][0];
    return new Response(JSON.stringify(status === 200 ? {} : { detail: { error: "actor_stale" } }), { status });
  });
  const urls = (f: ReturnType<typeof byUrl>) => f.mock.calls.map((c) => c[0].split("?")[0]);

  it("a 401 renews oi_actor on control once, then retries the call", async () => {
    meta();
    const f = byUrl({ "/auth/actor": [200], "/admin/chats/recent": [401, 200] });
    vi.stubGlobal("fetch", f);
    await relay.get("/admin/chats/recent?account_id=900539700124344320");
    expect(urls(f)).toEqual(["/auth/actor", "/admin/chats/recent", "/auth/actor", "/admin/chats/recent"]);
    expect(f.mock.calls[2][1]).toMatchObject({ method: "POST", credentials: "same-origin" });
  });

  it("parallel 401s share one renewal; a failed renewal returns the 401 without a retry", async () => {
    meta();
    const f = byUrl({ "/auth/actor": [200], "/admin/chats/recent": [401, 401, 200] });
    vi.stubGlobal("fetch", f);
    await Promise.all([relay.get("/admin/chats/recent?account_id=1"), relay.get("/admin/chats/recent?account_id=2")]);
    expect(urls(f).filter((u) => u === "/auth/actor")).toHaveLength(2);
    const g = byUrl({ "/auth/actor": [401], "/admin/chats/recent": [401] });
    vi.stubGlobal("fetch", g);
    const heard = vi.fn();
    window.addEventListener(STALE_CELL_GEN_EVENT, heard, { once: true });
    await expect(relay.get("/admin/chats/recent?account_id=1")).rejects.toMatchObject({ status: 401 });
    expect(urls(g)).toEqual(["/admin/chats/recent", "/auth/actor"]);
    expect(heard.mock.calls[0]?.[0].detail).toMatchObject({ reason: "actor_stale" });
    const h = byUrl({ "/auth/me": [401] });
    vi.stubGlobal("fetch", h);
    await expect(relay.get("/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(urls(h)).toEqual(["/auth/me"]);
  });

  it("mints before the first cell-mode call of a page, then renews every 5 min", async () => {
    vi.useFakeTimers();
    meta();
    const f = byUrl({ "/auth/actor": [200], "/admin/chats/recent": [200] });
    vi.stubGlobal("fetch", f);
    await relay.get("/admin/chats/recent?account_id=1");
    await relay.get("/admin/chats/recent?account_id=2");
    await vi.advanceTimersByTimeAsync(ACTOR_RENEW_MS - 1);
    expect(urls(f)).toEqual(["/auth/actor", "/admin/chats/recent", "/admin/chats/recent"]);
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(ACTOR_RENEW_MS);
    expect(urls(f)).toEqual(["/auth/actor", "/admin/chats/recent", "/admin/chats/recent", "/auth/actor", "/auth/actor"]);
  });

  it("env unset: a 401 is returned as is, no renewal, no timer", async () => {
    vi.useFakeTimers();
    const f = byUrl({ "/auth/actor": [200], "/admin/chats/recent": [401] });
    vi.stubGlobal("fetch", f);
    await expect(relay.get("/admin/chats/recent?account_id=1")).rejects.toMatchObject({ status: 401 });
    await vi.advanceTimersByTimeAsync(ACTOR_RENEW_MS * 2);
    expect(urls(f)).toEqual(["/admin/chats/recent"]);
  });

  it("refuses an unclassified call that names no Creator, before any fetch", async () => {
    meta();
    const f = answer(null);
    vi.stubGlobal("fetch", f);
    await expect(relay.post("/admin/mass-messages/1/cancel")).rejects.toMatchObject({
      status: 400, body: { detail: { error: "account_required" } },
    });
    await expect(relay.get("/api/of/v2/users/me")).rejects.toMatchObject({ status: 400 });
    await expect(relayFile("/admin/reports/run", undefined, {})).rejects.toMatchObject({ status: 400 });
    expect(f).not.toHaveBeenCalled();
  });

  it("lets control, account-named, cell-named and app calls through", async () => {
    meta();
    const f = answer(null);
    vi.stubGlobal("fetch", f);
    await relay.get("/auth/me");
    await relay.post("/admin/mass-messages/1/cancel", undefined, { accountId: "900539700124344321" });
    await relay.get("/admin/screens/inbox", { cellId: "s02" });
    await relay.get("/api/assistant");
    expect(relayCalls(f)).toHaveLength(4);
    expect(new Headers(relayCalls(f)[2][1].headers).get("X-Cell-Id")).toBe("s02");
  });

  it("echoes the Creator's X-Cell-Gen on writes only, per Creator", async () => {
    meta();
    const f = answer("3");
    vi.stubGlobal("fetch", f);
    await relay.get("/api/of/v2/users/me", { accountId: "900539700124344320" });
    await relay.post("/admin/messages/900539700124344320/x", {});
    await relay.get("/api/of/v2/users/me", { accountId: "900539700124344320" });
    await relay.post("/admin/messages/900539700124344321/x", {});
    const sent = relayCalls(f).map((c) => new Headers(c[1].headers).get("X-Cell-Gen"));
    expect(sent).toEqual([null, "3", null, null]);
  });

  it("keeps the generation of the read that supplied mutation ids", async () => {
    meta();
    vi.stubGlobal("fetch", answer("1"));
    await relay.get("/admin/accounts/42");
    vi.stubGlobal("fetch", answer("2"));
    await relay.get("/admin/accounts/42");
    const write = answer("2");
    vi.stubGlobal("fetch", write);
    await relay.post("/admin/accounts/42/x", {});
    expect(new Headers(relayCalls(write)[0][1].headers).get("X-Cell-Gen")).toBe("1");
  });

  it("409 stale_cell_gen asks the view to refetch and adopts the Cell's generation", async () => {
    meta();
    vi.stubGlobal("fetch", answer("3"));
    await relay.get("/admin/accounts/42");
    vi.stubGlobal("fetch", answer("2", 409, { detail: { error: "stale_cell_gen", cell_gen: 2 } }));
    const old = Promise.withResolvers<Response>();
    const stale = vi.mocked(fetch);
    stale.mockReturnValueOnce(old.promise);
    const beforeFence = relay.get("/admin/accounts/42");
    const heard = vi.fn();
    window.addEventListener(STALE_CELL_GEN_EVENT, heard);
    await expect(relay.post("/admin/accounts/42/x", {})).rejects.toMatchObject({ status: 409 });
    window.removeEventListener(STALE_CELL_GEN_EVENT, heard);
    expect(heard).toHaveBeenCalledTimes(1);
    expect((heard.mock.calls[0][0] as CustomEvent).detail).toEqual({ accountId: "42", reason: "stale" });
    const f = answer("2");
    vi.stubGlobal("fetch", f);
    old.resolve(await answer("3")("", {}));
    await beforeFence;
    await expect(relay.post("/admin/accounts/42/x", {})).rejects.toMatchObject({ status: 409, body: { detail: { error: "stale_cell_gen" } } });
    expect(f).not.toHaveBeenCalled();
    await relay.get("/admin/accounts/43");
    await expect(relay.post("/admin/accounts/42/x", {})).rejects.toMatchObject({ status: 409 });
    await relay.get("/admin/accounts/42");
    await relay.post("/admin/accounts/42/x", {});
    expect(new Headers(relayCalls(f).at(-1)![1].headers).get("X-Cell-Gen")).toBe("2");
  });

  it("cellAccountId names the Creator only in cell mode", async () => {
    const f = answer(null);
    vi.stubGlobal("fetch", f);
    await relay.post("/admin/promotions/7", {}, { cellAccountId: "900539700124344321" });
    meta();
    await relay.post("/admin/promotions/7", {}, { cellAccountId: "900539700124344321" });
    expect(relayCalls(f).map((c) => new Headers(c[1].headers).get("X-Account-Id"))).toEqual([null, "900539700124344321"]);
  });

  it("resolves the Cell flag once across single-box requests", async () => {
    vi.stubGlobal("fetch", answer(null));
    const lookup = vi.spyOn(document, "querySelector");
    try {
      await relay.get("/admin/accounts/42");
      await relay.get("/admin/accounts/42");
      expect(lookup.mock.calls.filter(([selector]) => selector === 'meta[name="oi-cells"]')).toHaveLength(1);
    } finally {
      lookup.mockRestore();
    }
  });

  it("env unset: no refusal, no echo (as main)", async () => {
    const f = answer(null);
    vi.stubGlobal("fetch", f);
    await relay.post("/admin/mass-messages/1/cancel");
    await relay.post("/admin/accounts/42/x", {});
    expect(f).toHaveBeenCalledTimes(2);
    expect(f.mock.calls.every((c) => !new Headers(c[1].headers).has("X-Cell-Gen"))).toBe(true);
  });
});

it.each([
  [undefined, "3", "ok", "3"],
  ["3", "4", "ok", "3"],
  ["3", "3", "stale", "3"],
  ["3", "2", "stale", "2"],
  ["3", null, "stale", undefined],
] as const)("nextGen(%s, %s, %s) returns %s", (known, header, phase, expected) => {
  expect(nextGen(known, header, phase)).toBe(expected);
});
