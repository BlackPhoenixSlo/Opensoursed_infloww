import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_KEY_ERROR_EVENT, ApiKeyError, RelayError, describeLoadError, isRateLimited, prefetchScreenBundle,
  relay, request,
  type ApiKeyErrorPayload,
} from "@/lib/relay";
import { resetInline, seedInline } from "@/lib/inlineBoot";
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
