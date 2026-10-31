import { afterEach, describe, expect, it, vi } from "vitest";

import { RelayError } from "@/lib/relay";
import { errorCode, postAuthJSON, signIn, TwoFactorRequired } from "@/lib/twoFactor";

function stubFetch(status: number, text: string) {
  const f = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: status >= 200 && status < 300, status, text: async () => text }) as unknown as Response);
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => vi.unstubAllGlobals());

describe("postAuthJSON", () => {
  it("POSTs JSON same-origin", async () => {
    const f = stubFetch(200, "{}");
    await postAuthJSON("/auth/login", { username: "a", password: "p" });
    expect(f).toHaveBeenCalledWith("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username: "a", password: "p" }),
      credentials: "same-origin",
    });
  });

  it.each([
    ["JSON", '{"user_id":"u1"}', { user_id: "u1" }],
    ["empty", "", null],
    ["non-JSON", "ok", "ok"],
  ])("200 %s body → parsed", async (_, text, want) => {
    stubFetch(200, text);
    await expect(postAuthJSON("/x", {})).resolves.toEqual(want);
  });

  it.each([
    [401, '{"detail":"Invalid username or password"}', "Invalid username or password", undefined],
    [403, '{"detail":{"code":"account_deactivated","message":"Deactivated"}}', "Deactivated", "account_deactivated"],
    [429, '{"detail":{"code":"too_many_attempts","message":"Slow down"}}', "Slow down", "too_many_attempts"],
    [500, "boom", "HTTP 500", undefined],
  ])("%i → authError", async (status, text, message, code) => {
    stubFetch(status, text);
    const err = await postAuthJSON("/x", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(RelayError);
    expect(err).toMatchObject({ status, message });
    expect(errorCode(err)).toBe(code);
  });
});

describe("signIn", () => {
  it("2FA challenge → TwoFactorRequired", async () => {
    const challenge = { two_factor: "verify", ticket: "t", username: "a" };
    const f = stubFetch(200, JSON.stringify(challenge));
    const err = await signIn("a", "p").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(TwoFactorRequired);
    expect(err).toMatchObject({ challenge });
    expect(f.mock.calls[0][0]).toBe("/auth/sign-in");
  });

  it.each(["user", "chatter"])("ok → kind %s", async (kind) => {
    stubFetch(200, JSON.stringify({ kind }));
    await expect(signIn("a", "p")).resolves.toBe(kind);
  });

  it("401 throws authError, not TwoFactorRequired", async () => {
    stubFetch(401, '{"detail":"Invalid username or password"}');
    const err = await signIn("a", "p").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(RelayError);
    expect(err).toMatchObject({ status: 401 });
  });
});
