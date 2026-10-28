/**
 * describeLoadError — the one place an upstream failure becomes English.
 *
 * It lives in relay.ts beside the code that formats `upstream <status>: <body>`,
 * because the two must agree on that shape. These cases pin the split that
 * actually matters to an operator: a 404 is PERMANENT (the thing is gone; no
 * amount of retrying helps) while a timeout/network/session error is transient
 * and retrying is exactly right.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_KEY_ERROR_EVENT, ApiKeyError, RelayError, describeLoadError, relay, request, type ApiKeyErrorPayload,
} from "@/lib/relay";

const err = (m: string) => new Error(m);

describe("describeLoadError", () => {
  it("reads the real 404 body a deleted fan produces", () => {
    // Verbatim from prod: fan 582413509 deleted his account mid-conversation.
    const raw = 'upstream 404: {"error":{"code":0,"message":"User not found"}}';
    const out = describeLoadError(err(raw), "This fan's OnlyFans account no longer exists.");
    expect(out).toBe("This fan's OnlyFans account no longer exists.");
    // The raw json must never reach the operator.
    expect(out).not.toContain('{"error"');
    expect(out).not.toContain("upstream");
  });

  it("defaults a 404 to wording that is true ANYWHERE", () => {
    // The caller decides what was missing. A roster or vault-list query must not
    // claim a fan's account is gone — that default was a bug caught in review.
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

  it("survives a null/blank error without rendering 'undefined'", () => {
    expect(describeLoadError(null)).toBe("Couldn't refresh: unknown error");
    expect(describeLoadError(undefined)).toBe("Couldn't refresh: unknown error");
    expect(describeLoadError({})).toBe("Couldn't refresh: unknown error");
  });
});

// ── The typed API-key refusal (424 `api_key_*`) ─────────────────────────────

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
    expect(err).toBeInstanceOf(RelayError); // every existing `instanceof RelayError` still holds
    expect(err.status).toBe(424);
    expect(err.payload).toEqual(KEY_PAYLOAD);
    // The relay's sentence, so inline `e.message` fallbacks read right too.
    expect(err.message).toBe(KEY_PAYLOAD.message);
    expect(seen).toEqual([KEY_PAYLOAD]); // one toast event per refusal
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

// ── Scoped calls skip the browser cache (Chrome's per-URL cache lock) ───────

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
