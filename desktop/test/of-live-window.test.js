"use strict";

// The Go live window (lib/of-live-window.js): OnlyFans's own streaming page in a
// non-persistent per-Creator partition, seeded from the Relay's session read
// before the first load (ticket 127, D26/D28). Electron is faked.

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  livePartition,
  allowPermission,
  isLogoutUrl,
  openOfLiveWindow,
  goLiveRefusal,
  goLiveSeed,
  createGoLive,
} = require("../lib/of-live-window");

const SECRET_XBC = "xbc-secret-7f3a";
const COOKIES = [
  { name: "auth_id", value: "1001", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: false, expires: null },
  { name: "sess", value: "sess-secret-9c1", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: 4102444800 },
  { name: "fp", value: "fp-1", domain: "onlyfans.com", path: "/", secure: true, httpOnly: false, expires: null },
  // Cloudflare's own: never seeded, even if a Relay ever sent them.
  { name: "__cf_bm", value: "cf-1", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: null },
  { name: "cf_clearance", value: "cf-2", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: null },
  { name: "_cfuvid", value: "cf-3", domain: ".onlyfans.com", path: "/", secure: true, httpOnly: true, expires: null },
  // Another site's cookie never lands in OnlyFans's partition.
  { name: "sess", value: "other", domain: ".example.com", path: "/", secure: true, httpOnly: true, expires: null },
];

// One log of every Electron call, in order, so "before the first load" is checkable.
function fakeElectron() {
  const log = [];
  const sessions = {};
  const windows = [];
  function fakeSession(partition) {
    const s = {
      partition,
      handlers: {},
      cookies: { set: async (d) => log.push(["cookie", partition, d]) },
      clearStorageData: async () => log.push(["clear", partition]),
      setPermissionRequestHandler: (fn) => (s.handlers.request = fn),
      setPermissionCheckHandler: (fn) => (s.handlers.check = fn),
      webRequest: {
        onBeforeSendHeaders: (fn) => (s.handlers.headers = fn),
        onBeforeRequest: (filter, fn) => (s.handlers.beforeRequest = typeof filter === "function" ? filter : fn),
      },
    };
    return s;
  }
  const session = {
    fromPartition: (p) => (sessions[p] = sessions[p] || fakeSession(p)),
  };
  class BrowserWindow {
    constructor(opts) {
      this.opts = opts;
      this.listeners = {};
      this.destroyed = false;
      this.wcListeners = {};
      const wcl = this.wcListeners;
      this.webContents = {
        ua: null,
        setUserAgent: (ua) => (this.webContents.ua = ua),
        getUserAgent: () => this.webContents.ua,
        on: (ev, fn) => (wcl[ev] = wcl[ev] || []).push(fn),
        loadURL: async (url, o) => log.push(["load", url, o || null]),
        executeJavaScript: async (code) => log.push(["js", code]),
      };
      windows.push(this);
      log.push(["window", opts.webPreferences.partition]);
    }
    on(ev, fn) {
      (this.listeners[ev] = this.listeners[ev] || []).push(fn);
    }
    once(ev, fn) {
      this.on(ev, fn);
    }
    show() {}
    isDestroyed() {
      return this.destroyed;
    }
  }
  return { log, sessions, windows, deps: { BrowserWindow, session } };
}

const open = (f, extra = {}) =>
  openOfLiveWindow(f.deps, { creatorId: "1001", cookies: COOKIES, xBc: SECRET_XBC, platform: "darwin", chromeMajor: "150", ...extra });

test("partition: of-live-<creatorId>, never persist:, and only for a numeric Creator id", () => {
  assert.equal(livePartition("1001"), "of-live-1001");
  assert.equal(livePartition(1001), "of-live-1001");
  for (const bad of ["", null, undefined, "persist:x", "1/2", "abc", "12 3"]) {
    assert.throws(() => livePartition(bad));
  }
});

test("window factory: own non-persistent partition, cookies and bcTokenSha seeded before the streaming page loads", async () => {
  const f = fakeElectron();
  const win = await open(f);
  const P = "of-live-1001";
  assert.equal(win.opts.webPreferences.partition, P);
  assert.ok(!P.startsWith("persist:"));
  // The page gets no Node and no preload: no secret crosses a bridge.
  assert.equal(win.opts.webPreferences.contextIsolation, true);
  assert.equal(win.opts.webPreferences.nodeIntegration, false);
  assert.equal(win.opts.webPreferences.sandbox, true);
  assert.equal(win.opts.webPreferences.preload, undefined);

  const live = f.log.findIndex((e) => e[0] === "load" && e[1] === "https://onlyfans.com/my/streaming");
  assert.ok(live > 0, "the streaming page is loaded");
  const before = f.log.slice(0, live);
  // Reseeded on every open: cleared before anything is set.
  assert.equal(before[0][0], "clear");
  const cookies = before.filter((e) => e[0] === "cookie").map((e) => e[2]);
  assert.deepEqual(cookies.map((c) => c.name), ["auth_id", "sess", "fp"]);
  for (const c of cookies) assert.equal(c.url, "https://onlyfans.com/");
  const sess = cookies.find((c) => c.name === "sess");
  assert.deepEqual(
    [sess.value, sess.domain, sess.path, sess.secure, sess.httpOnly, sess.expirationDate],
    ["sess-secret-9c1", ".onlyfans.com", "/", true, true, 4102444800],
  );
  // A host-only cookie stays host-only (no domain), a session cookie stays a session cookie.
  const fp = cookies.find((c) => c.name === "fp");
  assert.equal("domain" in fp, false);
  assert.equal("expirationDate" in fp, false);
  // localStorage.bcTokenSha = x_bc, written in an onlyfans.com document that never touched the network.
  const seedLoad = before.find((e) => e[0] === "load");
  assert.equal(seedLoad[1].startsWith("data:"), true);
  assert.deepEqual(seedLoad[2], { baseURLForDataURL: "https://onlyfans.com/" });
  const js = before.filter((e) => e[0] === "js").map((e) => e[1]);
  assert.equal(js.length, 1);
  assert.match(js[0], /localStorage\.setItem\("bcTokenSha", ?"xbc-secret-7f3a"\)/);
  // The secret never rides in a URL.
  for (const e of f.log.filter((x) => x[0] === "load")) assert.ok(!e[1].includes(SECRET_XBC));
});

test("window factory: the user agent and client hints say Chrome, never Electron", async () => {
  const f = fakeElectron();
  const win = await open(f);
  const ua = win.webContents.getUserAgent();
  assert.match(ua, /Chrome\/150\.0\.0\.0/);
  assert.doesNotMatch(ua, /Electron/i);
  const h = { "User-Agent": "x Electron/43" };
  let out = null;
  f.sessions["of-live-1001"].handlers.headers({ requestHeaders: h, url: "https://onlyfans.com/" }, (r) => (out = r.requestHeaders));
  assert.doesNotMatch(out["User-Agent"], /Electron/i);
  assert.match(out["sec-ch-ua"], /"Google Chrome";v="150"/);
});

test("window factory: the partition is cleared again when the window closes (no secrets kept)", async () => {
  const f = fakeElectron();
  const win = await open(f);
  const n = f.log.filter((e) => e[0] === "clear").length;
  for (const fn of win.listeners.closed || []) fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(f.log.filter((e) => e[0] === "clear").length, n + 1);
});

test("permission table: camera and mic only on https://onlyfans.com and its subdomains; everything else denied", () => {
  const rows = [
    ["media", "https://onlyfans.com", true],
    ["media", "https://onlyfans.com/", true],
    ["media", "https://onlyfans.com/my/streaming", true],
    ["media", "https://stream.onlyfans.com", true],
    ["media", "http://onlyfans.com", false],
    ["media", "https://onlyfans.com:8443", false],
    ["media", "https://evilonlyfans.com", false],
    ["media", "https://onlyfans.com.evil.test", false],
    ["media", "https://agora.io", false],
    ["media", "", false],
    ["media", "not a url", false],
    ["notifications", "https://onlyfans.com", false],
    ["geolocation", "https://onlyfans.com", false],
    ["display-capture", "https://onlyfans.com", false],
    ["clipboard-read", "https://onlyfans.com", false],
    ["openExternal", "https://onlyfans.com", false],
  ];
  for (const [perm, origin, want] of rows) assert.equal(allowPermission(perm, origin), want, `${perm} ${origin}`);
});

test("permission handlers on the partition use that table (request: the requesting URL; check: the origin)", async () => {
  const f = fakeElectron();
  await open(f);
  const h = f.sessions["of-live-1001"].handlers;
  const wc = { getURL: () => "https://onlyfans.com/my/streaming" };
  const answers = [];
  h.request(wc, "media", (v) => answers.push(v), { requestingUrl: "https://onlyfans.com/my/streaming" });
  h.request(wc, "media", (v) => answers.push(v), { requestingUrl: "https://agora.example/iframe" });
  h.request(wc, "notifications", (v) => answers.push(v), { requestingUrl: "https://onlyfans.com/" });
  assert.deepEqual(answers, [true, false, false]);
  assert.equal(h.check(wc, "media", "https://onlyfans.com"), true);
  assert.equal(h.check(wc, "media", "https://evil.test"), false);
  assert.equal(h.check(wc, "geolocation", "https://onlyfans.com"), false);
});

test("logout: OF's logout endpoints and pages are recognised; ordinary pages are not", () => {
  for (const u of [
    "https://onlyfans.com/api2/v2/users/logout",
    "https://onlyfans.com/api2/v2/users/helper-logout",
    "https://onlyfans.com/logout",
    "https://onlyfans.com/my/logout?x=1",
  ]) assert.equal(isLogoutUrl(u), true, u);
  for (const u of [
    "https://onlyfans.com/my/streaming",
    "https://onlyfans.com/api2/v2/users/me",
    "https://onlyfans.com/logouts-are-fine-here",
    "https://example.com/logout",
    "http://127.0.0.1:4555/logout",
    "",
  ]) assert.equal(isLogoutUrl(u), false, u);
});

test("logout blocked: the request is cancelled and a navigation to it is prevented in the window", async () => {
  const f = fakeElectron();
  const win = await open(f);
  const h = f.sessions["of-live-1001"].handlers;
  const cancel = (url) => {
    let out = null;
    h.beforeRequest({ url, method: "POST" }, (r) => (out = r));
    return out.cancel;
  };
  assert.equal(cancel("https://onlyfans.com/api2/v2/users/logout"), true);
  assert.equal(cancel("https://onlyfans.com/api2/v2/users/me"), false);
  for (const ev of ["will-navigate", "will-redirect"]) {
    const fns = win.wcListeners[ev] || [];
    assert.ok(fns.length, `${ev} guarded`);
    let prevented = 0;
    const event = (url) => ({ url, preventDefault: () => prevented++ });
    for (const fn of fns) fn(event("https://onlyfans.com/logout"), "https://onlyfans.com/logout");
    for (const fn of fns) fn(event("https://onlyfans.com/my/streaming"), "https://onlyfans.com/my/streaming");
    assert.equal(prevented, 1, ev);
  }
});

test("no seed, no window: missing x_bc or no auth cookies refuses before anything is opened", async () => {
  for (const extra of [{ xBc: "" }, { cookies: [] }, { cookies: COOKIES.filter((c) => c.name !== "sess") }]) {
    const f = fakeElectron();
    await assert.rejects(open(f, extra));
    assert.equal(f.windows.length, 0);
    assert.equal(f.log.filter((e) => e[0] === "cookie").length, 0);
  }
});

test("unseeded (the Relay has no session): opens OF's login page for a human, no cookie, no script, nothing filled", async () => {
  const f = fakeElectron();
  const win = await openOfLiveWindow(f.deps, { creatorId: "1001", unseeded: true, platform: "darwin", chromeMajor: "150" });
  assert.equal(win.opts.webPreferences.partition, "of-live-1001");
  assert.equal(f.log[0][0], "clear");
  assert.equal(f.log.filter((e) => e[0] === "cookie").length, 0);
  // Never a scripted login: no script runs in the page at all (no auto-fill, no submit, no seed).
  assert.equal(f.log.filter((e) => e[0] === "js").length, 0);
  assert.deepEqual(f.log.filter((e) => e[0] === "load").map((e) => e[1]), ["https://onlyfans.com/"]);
  assert.doesNotMatch(win.webContents.getUserAgent(), /Electron/i);
  // Camera/mic table and the logout block still hold.
  const h = f.sessions["of-live-1001"].handlers;
  assert.equal(h.check(null, "media", "https://evil.test"), false);
  let out = null;
  h.beforeRequest({ url: "https://onlyfans.com/api2/v2/users/logout" }, (r) => (out = r));
  assert.equal(out.cancel, true);
  // Unseeded ignores any cookies or x_bc handed in by mistake.
  const g = fakeElectron();
  await openOfLiveWindow(g.deps, { creatorId: "1", unseeded: true, cookies: COOKIES, xBc: SECRET_XBC, chromeMajor: "150" });
  assert.equal(g.log.filter((e) => e[0] === "cookie" || e[0] === "js").length, 0);
});

test("goLiveRefusal: plain words for the Relay's answers, no detail echoed", () => {
  assert.match(goLiveRefusal(401), /sign in/i);
  assert.match(goLiveRefusal(403), /not allowed/i);
  assert.match(goLiveRefusal(404), /not turned on/i);
  assert.match(goLiveRefusal(429), /wait/i);
  assert.match(goLiveRefusal(503), /OnlyFans session/i);
  assert.match(goLiveRefusal(500), /couldn't/i);
});

test("goLiveSeed: only an OK {session: null} is sign-in; every non-OK answer (any 503 too) is refused", () => {
  const seed = { cookies: COOKIES, x_bc: SECRET_XBC };
  assert.deepEqual(goLiveSeed(200, { session: null }), { signIn: true });
  assert.deepEqual(goLiveSeed(200, { session: seed }), { cookies: COOKIES, xBc: SECRET_XBC });
  for (const status of [503, 502, 500, 404, 403, 401, 429, 409, 0]) {
    assert.deepEqual(goLiveSeed(status, { session: null }), { refuse: status }, String(status));
  }
  // An OK answer that is not the Relay's shape is refused, never a sign-in.
  for (const body of [null, {}, { session: undefined }, { cookies: COOKIES, x_bc: SECRET_XBC },
    { session: {} }, { session: { cookies: "x", x_bc: SECRET_XBC } }, { session: { cookies: COOKIES } }, "text"]) {
    assert.deepEqual(goLiveSeed(200, body), { refuse: 0 }, JSON.stringify(body));
  }
});

// The open flow main.js registers on shell:open-go-live, with the Relay read faked.
function flow(answer, extra = {}) {
  const f = fakeElectron();
  const calls = [];
  const focused = [];
  const warned = [];
  const openGoLive = createGoLive({
    ...f.deps,
    platform: "darwin",
    chromeMajor: "150",
    focusWindow: (w) => focused.push(w),
    warn: (m) => warned.push(m),
    fetchSession: async (id) => {
      calls.push(id);
      const a = typeof answer === "function" ? await answer(id) : answer;
      return { status: a.status, json: async () => a.body };
    },
    ...extra,
  });
  return { f, calls, focused, warned, openGoLive };
}
const SEEDED = { status: 200, body: { session: { cookies: COOKIES, x_bc: SECRET_XBC } } };

test("open flow: a seeded answer opens the streaming page with that seed; the reply carries no secret", async () => {
  const t = flow(SEEDED);
  const r = await t.openGoLive("1001");
  assert.deepEqual(r, { ok: true });
  assert.deepEqual(t.calls, ["1001"]);
  assert.equal(t.f.windows.length, 1);
  assert.ok(t.f.log.some((e) => e[0] === "load" && e[1] === "https://onlyfans.com/my/streaming"));
  assert.ok(t.f.log.some((e) => e[0] === "cookie" && e[2].name === "sess"));
  assert.ok(!JSON.stringify(r).includes(SECRET_XBC));
});

test("open flow: only {session: null} opens OF's login page; a 503 (downtime, proxy, broken session) opens nothing", async () => {
  const t = flow({ status: 200, body: { session: null } });
  assert.deepEqual(await t.openGoLive("1001"), { ok: true, signIn: true });
  assert.deepEqual(t.f.log.filter((e) => e[0] === "load").map((e) => e[1]), ["https://onlyfans.com/"]);
  assert.equal(t.f.log.filter((e) => e[0] === "cookie" || e[0] === "js").length, 0);

  for (const answer of [
    { status: 503, body: { detail: { error: "no_session" } } },
    { status: 503, body: { detail: { error: "bad_session" } } },
    { status: 503, body: null },
    { status: 200, body: {} },
    { status: 200, body: null },
  ]) {
    const u = flow(answer);
    const r = await u.openGoLive("1001");
    assert.equal(r.ok, false, JSON.stringify(answer));
    assert.equal(typeof r.error, "string");
    assert.equal(u.f.windows.length, 0, JSON.stringify(answer));
  }
});

test("open flow: each refusal status gets its plain message and no window", async () => {
  for (const status of [401, 403, 404, 429]) {
    const t = flow({ status, body: { detail: "x" } });
    assert.deepEqual(await t.openGoLive("1001"), { ok: false, error: goLiveRefusal(status) });
    assert.equal(t.f.windows.length, 0);
  }
  const net = flow(async () => {
    throw new Error("offline");
  });
  assert.deepEqual(await net.openGoLive("1001"), { ok: false, error: goLiveRefusal(0) });
});

test("open flow: a bad Creator id is refused without a Relay read", async () => {
  for (const id of ["", "  ", "abc", "1/2", null, 42, undefined]) {
    const t = flow(SEEDED);
    const r = await t.openGoLive(id);
    assert.equal(r.ok, false, String(id));
    assert.deepEqual(t.calls, []);
  }
});

test("open flow: one window per Creator; a second open focuses it; a double click reads once; closing frees it", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const t = flow(async () => {
    await gate;
    return SEEDED;
  });
  const first = t.openGoLive("1001");
  const second = await t.openGoLive("1001"); // while the first is still reading
  assert.deepEqual(second, { ok: true });
  release();
  assert.deepEqual(await first, { ok: true });
  assert.equal(t.calls.length, 1);
  assert.equal(t.f.windows.length, 1);

  assert.deepEqual(await t.openGoLive("1001"), { ok: true });
  assert.deepEqual(t.focused, [t.f.windows[0]]);
  assert.equal(t.calls.length, 1);

  for (const fn of t.f.windows[0].listeners.closed || []) fn();
  t.f.windows[0].destroyed = true;
  await t.openGoLive("1001");
  assert.equal(t.calls.length, 2);
  assert.equal(t.f.windows.length, 2);
});

test("open flow: a window failure answers a plain error and warns with the message only, never the seed", async () => {
  const t = flow(SEEDED, { chromeMajor: "" });
  const r = await t.openGoLive("1001");
  assert.deepEqual(r, { ok: false, error: goLiveRefusal(0) });
  assert.equal(t.warned.length, 1);
  for (const m of t.warned) {
    assert.ok(!m.includes(SECRET_XBC) && !m.includes("sess-secret-9c1"), m);
  }
  // The in-flight guard is released after a failure.
  const again = await t.openGoLive("1001");
  assert.equal(again.ok, false);
});
