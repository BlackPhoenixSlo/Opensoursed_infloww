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

describe("POST /site-auth on a fleet", () => {
  const FRONT = "https://login.fleet.test";
  const S02 = "https://s02.fleet.test";
  const S03 = "https://s03.fleet.test";
  const SELF = "http://127.0.0.1:8787"; // RELAY_URL's default
  const S02_RELAY = "http://127.0.0.1:18702"; // the `|` form: whois straight to the relay
  const SECRET = "s".repeat(40);
  const TRICKY = `pw"<&>'x`;

  type Whois = boolean | "error";
  type Call = { url: string; headers: Record<string, string>; body?: string };

  async function loadFleet(env: Record<string, string>): Promise<Post> {
    vi.resetModules();
    vi.stubEnv("SITE_URL", SITE);
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    return (await import("@/app/site-auth/route")).POST;
  }
  const front = (extra: Record<string, string> = {}) => loadFleet({
    FLEET_SECRET: SECRET, FLEET_FRONT_ORIGIN: FRONT,
    FLEET_PEERS: `${S02}|${S02_RELAY}, ${S03}`, ...extra,
  });

  /** whois answers per relay base (self, s02's relay, s03), plus local relay replies. */
  function mockFleet(who: Partial<Record<string, Whois>>, relayReplies: Record<string, Reply> = {}) {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = new URL(url);
      calls.push({ url, headers: { ...(init.headers as Record<string, string>) }, body: init.body as string | undefined });
      if (u.pathname === "/auth/fleet/whois") {
        const w = who[u.origin] ?? false;
        if (w === "error") throw new TypeError("fetch failed");
        return new Response(JSON.stringify({ exists: w }), { status: 200 });
      }
      const r = u.origin === SELF ? relayReplies[u.pathname] : undefined;
      if (!r) throw new Error(`unexpected call ${url}`);
      const headers = new Headers({ "Content-Type": "application/json" });
      for (const c of r.cookies ?? []) headers.append("Set-Cookie", c);
      return new Response(JSON.stringify(r.body ?? (r.status < 400 ? { kind: "user" } : {})), { status: r.status, headers });
    }));
    return calls;
  }
  const paths = (calls: Call[]) => calls.map((c) => `${new URL(c.url).origin}${new URL(c.url).pathname}`);
  const ip = (n: number) => ({ "X-Forwarded-For": `198.51.100.7, 203.0.113.${n}` });

  it("asks every relay with the secret and the name in headers, then signs a local user in as today", async () => {
    POST = await front();
    const calls = mockFleet({ [SELF]: true }, { "/auth/sign-in": { status: 200, cookies: [COOKIE] } });
    const res = await post({ username: " Alice ", password: PASSWORD }, ORIGIN, ip(1));
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("/");
    expect(res.headers.getSetCookie()).toEqual([COOKIE]);
    expect(paths(calls).sort()).toEqual([
      `${S02_RELAY}/auth/fleet/whois`, `${SELF}/auth/fleet/whois`, `${SELF}/auth/sign-in`, `${S03}/auth/fleet/whois`,
    ].sort());
    for (const c of calls.filter((c) => c.url.endsWith("/whois"))) {
      expect(c.headers).toEqual({ "X-Fleet-Secret": SECRET, "X-Fleet-Username": "alice" });
      expect(c.body).toBeUndefined();
    }
  });

  it("hands a peer's user to that shard: a 200 page re-posting the form there, escaped, under a CSP that allows only it and the site", async () => {
    POST = await front();
    const calls = mockFleet({ [S02_RELAY]: true });
    const res = await post({ username: "bob", password: TRICKY }, ORIGIN, ip(2));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/html; charset=utf-8");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("referrer-policy")).toBe("origin-when-cross-origin");
    expect(res.headers.getSetCookie()).toEqual([]);
    const html = await res.text();
    expect(html).toContain(`<form method="post" action="${S02}/site-auth">`);
    expect(html).toContain(`name="password" value="pw&#34;&#60;&#38;&#62;&#39;x"`);
    expect(html).not.toContain(TRICKY);
    expect(html).toContain(`name="mode" value="login"`);
    const script = /<script>(.*?)<\/script>/.exec(html)![1];
    const { createHash } = await import("node:crypto");
    const hash = createHash("sha256").update(script).digest("base64");
    expect(res.headers.get("content-security-policy")).toBe(
      `default-src 'none'; script-src 'sha256-${hash}'; form-action ${S02} ${ORIGIN}; frame-ancestors 'none'`,
    );
    expect(paths(calls).filter((p) => !p.endsWith("/whois"))).toEqual([]); // no sign-in here
  });

  it("is wrong when no shard has the name, unavailable when one did not answer, workspace on two", async () => {
    POST = await front();
    mockFleet({});
    expect((await post({ username: "nobody", password: PASSWORD }, ORIGIN, ip(3))).headers.get("location"))
      .toBe(`${SITE}/login/#error=wrong&username=nobody`);
    mockFleet({ [S03]: "error" });
    expect((await post({ username: "nobody", password: PASSWORD }, ORIGIN, ip(3))).headers.get("location"))
      .toBe(`${SITE}/login/#error=unavailable&username=nobody`);
    const calls = mockFleet({ [S02_RELAY]: true, [S03]: true });
    const res = await post({ username: "dup", password: PASSWORD }, ORIGIN, ip(3));
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=workspace&username=dup`);
    expect(paths(calls).every((p) => p.endsWith("/whois"))).toBe(true);
  });

  it("treats a whois non-200 or a body without a bool as no answer", async () => {
    POST = await front();
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      new URL(url).origin === S03 ? new Response("{}", { status: 403 }) : new Response('{"exists":"yes"}', { status: 200 })));
    const res = await post({ username: "alice", password: PASSWORD }, ORIGIN, ip(4));
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=unavailable&username=alice`);
  });

  it("throttles lookups after 30 from one client IP, sending no whois, and leaves other IPs alone", async () => {
    POST = await front();
    const calls = mockFleet({});
    for (let i = 0; i < 30; i++) {
      expect((await post({ username: "x", password: PASSWORD }, ORIGIN, ip(5))).headers.get("location")).toContain("error=wrong");
    }
    const sent = calls.length;
    const res = await post({ username: "x", password: PASSWORD }, ORIGIN, ip(5));
    expect(res.headers.get("location")).toBe(`${SITE}/login/#error=throttled&username=x`);
    expect(calls.length).toBe(sent);
    // Keyed on the LAST X-Forwarded-For entry: a different first entry is the same client.
    const spoof = await post({ username: "x", password: PASSWORD }, ORIGIN, { "X-Forwarded-For": "1.2.3.4, 203.0.113.5" });
    expect(spoof.headers.get("location")).toContain("error=throttled");
    expect((await post({ username: "x", password: PASSWORD }, ORIGIN, ip(6))).headers.get("location")).toContain("error=wrong");
  });

  it("signup: taken when any shard has the name, handed to FLEET_OPEN, or local when the front is open", async () => {
    POST = await front({ FLEET_OPEN: S03 });
    mockFleet({ [S02_RELAY]: true });
    expect((await post({ mode: "register", username: "bob", password: PASSWORD }, ORIGIN, ip(7))).headers.get("location"))
      .toBe(`${SITE}/signup/#error=taken&username=bob`);
    mockFleet({ [S02_RELAY]: "error" });
    expect((await post({ mode: "register", username: "new1", password: PASSWORD }, ORIGIN, ip(7))).headers.get("location"))
      .toBe(`${SITE}/signup/#error=unavailable&username=new1`);
    const calls = mockFleet({});
    const handed = await post({ mode: "register", username: "new1", password: PASSWORD }, ORIGIN, ip(7));
    expect(handed.status).toBe(200);
    const html = await handed.text();
    expect(html).toContain(`action="${S03}/site-auth"`);
    expect(html).toContain(`name="mode" value="register"`);
    expect(paths(calls).every((p) => p.endsWith("/whois"))).toBe(true);

    POST = await front({ FLEET_OPEN: FRONT });
    const local = mockFleet({}, { "/auth/register": { status: 200, cookies: [COOKIE] } });
    const res = await post({ mode: "register", username: "new2", password: PASSWORD }, ORIGIN, ip(7));
    expect(res.headers.get("location")).toBe("/");
    expect(paths(local)).toContain(`${SELF}/auth/register`);
  });

  it("an owning shard accepts the front's hand-off post and still refuses every other origin", async () => {
    POST = await loadFleet({ FLEET_SECRET: SECRET, FLEET_FRONT_ORIGIN: FRONT });
    const calls = mockFleet({}, { "/auth/sign-in": { status: 200, cookies: [COOKIE] } });
    const res = await post({ username: "bob", password: PASSWORD, mode: "login" }, FRONT);
    expect(res.status).toBe(303);
    expect(res.headers.getSetCookie()).toEqual([COOKIE]);
    expect(paths(calls)).toEqual([`${SELF}/auth/sign-in`]); // no peers here: no whois
    for (const origin of [S02, "null", null]) expect((await post({ username: "bob", password: PASSWORD }, origin)).status).toBe(403);
  });

  it("refuses Origin: null on the front with no fetch made", async () => {
    POST = await front();
    const calls = mockFleet({ [SELF]: true });
    for (const origin of ["null", null, S02]) {
      expect((await post({ username: "alice", password: PASSWORD }, origin, ip(8))).status).toBe(403);
    }
    expect(calls).toEqual([]);
  });

  it("maps a relay 429 to error=throttled", async () => {
    mockRelay({ "/auth/sign-in": { status: 429, detail: "too many attempts" } });
    expect((await post({ username: "alice", password: PASSWORD })).headers.get("location"))
      .toBe(`${SITE}/login/#error=throttled&username=alice`);
  });

  it("ignores a FLEET_FRONT_ORIGIN that is not http(s) and drops bad FLEET_PEERS entries with a boot error", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    POST = await loadFleet({ FLEET_SECRET: SECRET, FLEET_FRONT_ORIGIN: "javascript:alert(1)",
      FLEET_PEERS: `not a url, ${S02}|ftp://x, ${S03}|a|b` });
    expect(err.mock.calls.length).toBe(3);
    // No peer survived: single-box sign-in, and the bogus front origin is not accepted.
    const calls = mockRelay({ "/auth/sign-in": { status: 401 } });
    expect((await post({ username: "a", password: PASSWORD })).headers.get("location")).toContain("error=wrong");
    expect(calls.map((c) => c.path)).toEqual(["/auth/sign-in"]);
    expect((await post({ username: "a", password: PASSWORD }, "javascript:alert(1)")).status).toBe(403);
    err.mockRestore();
  });

  it("never puts the password in a URL or a console.* call", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));
    POST = await front({ FLEET_OPEN: S03 });
    const calls = mockFleet({ [S02_RELAY]: true });
    const res = await post({ username: "bob", password: PASSWORD }, ORIGIN, ip(9));
    expectNoPassword(res);
    mockFleet({}, {});
    await post({ mode: "register", username: "new3", password: PASSWORD }, ORIGIN, ip(9));
    for (const c of calls) {
      expect(c.url).not.toContain(PASSWORD);
      expect(JSON.stringify(c.headers)).not.toContain(PASSWORD);
    }
    for (const s of spies) {
      for (const args of s.mock.calls) expect(JSON.stringify(args)).not.toContain(PASSWORD);
      s.mockRestore();
    }
  });
});
