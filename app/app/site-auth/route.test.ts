// @vitest-environment node
/**
 * POST /site-auth: the public site's form post becomes a relay JSON call and a
 * 303, with the relay's cookies copied on success and an error code (in the
 * fragment) on failure.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SITE_URL } from "@/lib/site";

const SITE = "https://site.example/sub";
const ORIGIN = "https://site.example";
const PASSWORD = "hunter22-secret";
const COOKIE = "chatterly_session=abc.def; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax";
const IMP = "chatterly_impersonate=; Max-Age=0; Path=/; SameSite=lax";

type Reply = { status: number; detail?: string; cookies?: string[]; body?: unknown };
type Post = (req: Request) => Promise<Response>;

/** The route reads SITE_URL once at import, so each test imports it fresh. */
async function loadRoute(siteUrl = SITE): Promise<Post> {
  vi.resetModules();
  vi.stubEnv("SITE_URL", siteUrl);
  return (await import("@/app/site-auth/route")).POST;
}

/** Answer relay calls by path; record what was sent. */
function mockRelay(replies: Record<string, Reply>) {
  const calls: { path: string; body: unknown; forwarded?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = new URL(url).pathname;
    const forwarded = (init.headers as Record<string, string>)["X-Forwarded-For"];
    calls.push({ path, body: JSON.parse(String(init.body)), ...(forwarded ? { forwarded } : {}) });
    const r = replies[path];
    if (!r) throw new Error(`unexpected relay call ${path}`);
    const headers = new Headers({ "Content-Type": "application/json" });
    for (const c of r.cookies ?? []) headers.append("Set-Cookie", c);
    const body = r.body ?? (r.status < 400 ? { kind: "user" } : { detail: r.detail ?? "" });
    return new Response(JSON.stringify(body), { status: r.status, headers });
  }));
  return calls;
}

let POST: Post;
function post(fields: Record<string, string>, origin: string | null = ORIGIN, extra: Record<string, string> = {}) {
  const headers: Record<string, string> = { "Content-Type": "application/x-www-form-urlencoded", ...extra };
  if (origin) headers.Origin = origin;
  return POST(new Request("http://localhost:3001/site-auth", {
    method: "POST",
    headers,
    body: new URLSearchParams(fields).toString(),
  }));
}

function expectNoPassword(res: Response) {
  for (const [, v] of res.headers) expect(v).not.toContain(PASSWORD);
}

beforeEach(async () => {
  POST = await loadRoute();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("POST /site-auth", () => {
  it("registers, copies every Set-Cookie, wipes site storage and lands on the Dashboard", async () => {
    const calls = mockRelay({ "/auth/register": { status: 200, cookies: [COOKIE, IMP] } });
    const res = await post({ mode: "register", username: " Alice ", password: PASSWORD });
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("/");
    expect(res.headers.getSetCookie()).toEqual([COOKIE, IMP]);
    expect(res.headers.get("clear-site-data")).toBe('"storage"');
    expect(calls).toEqual([{ path: "/auth/register", body: { username: "alice", password: PASSWORD } }]);
    expectNoPassword(res);
  });

  it("signs an owner or an employee in with one relay call, and forwards the client's address", async () => {
    const chatterCookie = "chatterly_chatter_session=x; HttpOnly; Path=/; SameSite=lax";
    for (const [kind, cookie] of [["user", COOKIE], ["chatter", chatterCookie]]) {
      const calls = mockRelay({ "/auth/sign-in": { status: 200, cookies: [cookie], body: { kind } } });
      const res = await post({ username: "alice", password: PASSWORD }, ORIGIN, { "X-Forwarded-For": "203.0.113.9" });
      expect(res.headers.get("location")).toBe("/");
      expect(res.headers.getSetCookie()).toEqual([cookie]);
      expect(calls).toEqual([{ path: "/auth/sign-in", body: { username: "alice", password: PASSWORD }, forwarded: "203.0.113.9" }]);
    }
  });

  it("sends a 2FA sign-in to the app's /login, where the code step is, with no cookie", async () => {
    mockRelay({ "/auth/sign-in": { status: 200, body: { two_factor: "verify", ticket: "t.sig", username: "alice" } } });
    const res = await post({ username: "alice", password: PASSWORD });
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("/login?username=alice");
    expect(res.headers.getSetCookie()).toEqual([]);
    expect(res.headers.get("location")).not.toContain("t.sig");
  });

  it("sends a wrong password back to the site's /login/ with error=wrong in the fragment", async () => {
    mockRelay({ "/auth/sign-in": { status: 401, detail: "invalid username or password" } });
    const res = await post({ username: "alice", password: PASSWORD });
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=wrong&username=alice`);
    expect(res.headers.getSetCookie()).toEqual([]);
    expect(res.headers.get("clear-site-data")).toBeNull();
    expectNoPassword(res);
  });

  it("maps a deactivated employee (403) to error=disabled", async () => {
    mockRelay({ "/auth/sign-in": { status: 403, detail: "deactivated" } });
    const res = await post({ username: "carol", password: PASSWORD });
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=disabled&username=carol`);
  });

  it("maps a sign-in 400 or 422 to error=invalid", async () => {
    for (const status of [400, 422]) {
      mockRelay({ "/auth/sign-in": { status, detail: "username required" } });
      const res = await post({ username: "alice", password: PASSWORD });
      expect(res.headers.get("location")).toBe(`${SITE}/login/#error=invalid&username=alice`);
    }
  });

  it("sends a taken username back to /signup/ with error=taken", async () => {
    mockRelay({ "/auth/register": { status: 409, detail: "username already taken" } });
    const res = await post({ mode: "register", username: "alice", password: PASSWORD });
    expect(res.headers.get("location")).toBe(`${SITE}/signup/#error=taken&username=alice`);
    expectNoPassword(res);
  });

  it("maps a reserved name to error=reserved and other 400s to error=invalid", async () => {
    mockRelay({ "/auth/register": { status: 400, detail: "username 'admin' is reserved" } });
    const reserved = await post({ mode: "register", username: "admin", password: PASSWORD });
    expect(reserved.headers.get("location")).toBe(`${SITE}/signup/#error=reserved&username=admin`);

    mockRelay({ "/auth/register": { status: 400, detail: "password must be at least 6 chars" } });
    const short = await post({ mode: "register", username: "alice", password: "abc" });
    expect(short.headers.get("location")).toBe(`${SITE}/signup/#error=invalid&username=alice`);
  });

  it("reports an unreachable relay as error=unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    const res = await post({ username: "alice", password: PASSWORD });
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=unavailable&username=alice`);
  });

  it("refuses posts from any other origin and never calls the relay", async () => {
    const calls = mockRelay({});
    for (const origin of ["https://evil.example", "null", null]) {
      const res = await post({ username: "alice", password: PASSWORD }, origin);
      expect(res.status).toBe(403);
      expect(res.headers.get("location")).toBeNull();
      expect(await res.text()).not.toContain(PASSWORD);
    }
    expect(calls).toEqual([]);
  });

  it("falls back to the default site when SITE_URL is empty or malformed", async () => {
    for (const bad of ["", "not a url", "javascript:alert(1)"]) {
      POST = await loadRoute(bad);
      mockRelay({ "/auth/sign-in": { status: 401 } });
      const res = await post({ username: "alice", password: PASSWORD }, new URL(SITE_URL).origin);
      expect([bad, res.status, res.headers.get("location")]).toEqual([bad, 303, `${SITE_URL}/login/#error=wrong&username=alice`]);
    }
  });

  it("never logs the password", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));
    mockRelay({ "/auth/sign-in": { status: 401 } });
    await post({ username: "alice", password: PASSWORD });
    for (const s of spies) {
      for (const args of s.mock.calls) expect(JSON.stringify(args)).not.toContain(PASSWORD);
      s.mockRestore();
    }
  });
});
