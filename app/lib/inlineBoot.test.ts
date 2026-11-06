/**
 * The HTML's inline boot (lib/inlineBoot.ts, lib/inlineBoot.server.ts): which GETs a document load starts on the
 * server (the browser's own guess, from its cookies), each request's own answers, and the browser taking each once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { inlineKey, KEEP_MS, resetInline, seedInline, takeInline, type InlineAnswer } from "./inlineBoot";
import { inlinePaths, INLINE_TIMEOUT_MS, startInline } from "./inlineBoot.server";
import { relay } from "./relay";
import { bundlePath, screenKey } from "./screenKey";
import { entryScreen, type DashboardEntry } from "./screenEntry";

const ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const enc = (e: DashboardEntry) => encodeURIComponent(JSON.stringify(e));
const dash = (search: string, hint: DashboardEntry | null) => bundlePath(screenKey(entryScreen("/", search, hint)!));

describe("inlinePaths: what the browser would fetch first, per document", () => {
  it.each<[string, string | null, string | undefined, string | undefined, string[]]>([
    ["no tag (not a document load): none", null, undefined, ZONE, []],
    ["another page: none", "/creators", undefined, ZONE, []],
    ["Messages Pro: the probes and the inbox bundle", "/messages-pro", undefined, undefined,
      ["/auth/me", "/chatter/me", "/admin/screens/inbox?cursor=0"]],
    ["Dashboard, no zone known (first load here): no bundle", "/", undefined, undefined,
      ["/auth/me", "/chatter/me", "/admin/settings/applied"]],
    ["Dashboard, cards hidden: no bundle", "/", enc({ tz: "Asia/Tokyo", weekStart: "monday", grid: false }), ZONE,
      ["/auth/me", "/chatter/me", "/admin/settings/applied"]],
  ])("%s", (_n, path, entry, tz, want) => {
    expect(inlinePaths(path, entry, tz)).toEqual(want);
  });

  it("Dashboard, nothing saved: the browser's guess (its zone from the cookie, Monday): the key AuthGate starts", () => {
    // The browser's guess with tz null is its own zone: here, the test process's.
    expect(inlinePaths("/", undefined, encodeURIComponent(ZONE))[3]).toBe(dash("", null));
  });

  it("Dashboard, a saved entry: its zone and week start win over the browser's zone; the URL's window counts", () => {
    vi.useFakeTimers({ now: new Date("2026-11-06T12:00:00Z") });
    try {
      const tokyo: DashboardEntry = { tz: "Asia/Tokyo", weekStart: "sunday", grid: true };
      expect(inlinePaths("/?window=month", enc(tokyo), "Europe/Ljubljana")[3]).toBe(dash("?window=month", tokyo));
      // A saved null zone (no report zone): the browser's.
      const none: DashboardEntry = { tz: null, weekStart: "sunday", grid: true };
      expect(inlinePaths("/", enc(none), "Asia/Tokyo")[3]).toBe(dash("", { ...none, tz: "Asia/Tokyo" }));
      // Junk in the entry cookie: as none saved.
      expect(inlinePaths("/", "%7Boops", "Asia/Tokyo")[3]).toBe(dash("", { tz: "Asia/Tokyo", weekStart: "monday", grid: true }));
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("startInline: this request's GETs on the relay", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("each path once, to the relay only, with this request's cookie, never cached; an answer per path", async () => {
    const fetchMock = vi.fn((url: string) => Promise.resolve(new Response(`{"u":"${url}"}`, { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const d = startInline(["/auth/me", "/admin/screens/inbox?cursor=0"], "chatterly_session=A", "http://relay:8787/")!;
    expect(await d["/auth/me"]).toEqual({ status: 200, body: '{"u":"http://relay:8787/auth/me"}' });
    expect(await d["/admin/screens/inbox?cursor=0"]).toMatchObject({ status: 200 });
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["http://relay:8787/auth/me", "http://relay:8787/admin/screens/inbox?cursor=0"]);
    for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.headers).toEqual({ cookie: "chatterly_session=A", accept: "application/json" });
      expect(init.cache).toBe("no-store");
    }
    // Another request: its own GETs with its own cookie, not the first one's answers.
    const e = startInline(["/auth/me"], "chatterly_session=B", "http://relay:8787")!;
    await e["/auth/me"];
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect((fetchMock.mock.calls[2] as unknown as [string, RequestInit])[1].headers).toMatchObject({ cookie: "chatterly_session=B" });
  });

  it("no cookie or nothing to start: null; a 5xx, a redirect, a network error: null (the browser fetches)", async () => {
    expect(startInline(["/auth/me"], null, "http://r")).toBeNull();
    expect(startInline([], "c=1", "http://r")).toBeNull();
    const answers = [new Response("x", { status: 502 }), new Response(null, { status: 302 }), null];
    vi.stubGlobal("fetch", vi.fn(() => {
      const r = answers.shift();
      return r ? Promise.resolve(r) : Promise.reject(new TypeError("refused"));
    }));
    const d = startInline(["/a", "/b", "/c"], "c=1", "http://r")!;
    expect(await Promise.all([d["/a"], d["/b"], d["/c"]])).toEqual([null, null, null]);
  });

  it("a 401 (a stale cookie) is an answer: the browser shows the sign-in as if it had asked", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response('{"detail":"no"}', { status: 401 }))));
    expect(await startInline(["/admin/settings/applied"], "c=1", "http://r")!["/admin/settings/applied"])
      .toEqual({ status: 401, body: '{"detail":"no"}' });
  });

  it("past INLINE_TIMEOUT_MS: null", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", vi.fn((_u: string, init: RequestInit) => new Promise((_res, rej) => {
        init.signal!.addEventListener("abort", () => rej(init.signal!.reason));
      })));
      const p = startInline(["/a"], "c=1", "http://r")!["/a"];
      await vi.advanceTimersByTimeAsync(INLINE_TIMEOUT_MS + 1);
      expect(await p).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("takeInline: the browser's first GET of each", () => {
  beforeEach(() => resetInline());
  afterEach(() => { resetInline(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  const ok = (body: unknown): Promise<InlineAnswer> => Promise.resolve({ status: 200, body: JSON.stringify(body) });

  it("once per URL; the share token and the bundle's focus do not change the key; unseeded: nothing", async () => {
    expect(takeInline("/auth/me")).toBeNull(); // synchronously: the caller's fetch leaves in the same tick as before
    seedInline({ "/x": ok({}) });
    expect(takeInline("/auth/me")).toBeNull(); // seeded, not this URL: synchronously too
    resetInline();
    seedInline({ "/auth/me": ok({ user_id: "u1" }), "/admin/screens/dashboard?from=a&to=b": ok({ creators: [] }) });
    expect(await (await takeInline("/auth/me"))!.json()).toEqual({ user_id: "u1" });
    expect(await takeInline("/auth/me")).toBeNull();
    expect(inlineKey("/admin/screens/dashboard?from=a&to=b&focus=7&t=s")).toBe("/admin/screens/dashboard?from=a&to=b");
    expect(await takeInline("/admin/screens/dashboard?from=a&to=b&focus=7")).not.toBeNull();
  });

  it("a second seed (a refresh's render) is ignored; past KEEP_MS nothing is taken", async () => {
    vi.useFakeTimers({ now: 1_000_000 });
    seedInline({ "/a": ok(1) });
    seedInline({ "/b": ok(2) });
    expect(await takeInline("/b")).toBeNull();
    vi.setSystemTime(1_000_000 + KEEP_MS + 1);
    expect(await takeInline("/a")).toBeNull();
  });

  it("a null answer (server gave up): null, the caller fetches; a 401 keeps its status", async () => {
    seedInline({ "/a": Promise.resolve(null), "/b": Promise.resolve({ status: 401, body: '{"detail":"x"}' }) });
    expect(await takeInline("/a")).toBeNull();
    expect((await takeInline("/b"))!.status).toBe(401);
  });

  it("relay.get takes it instead of the network, once; a Creator-scoped GET never does", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response('{"net":true}', { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    seedInline({ "/admin/settings/applied": ok({ inline: true }), "/admin/accounts": ok({ inline: true }) });
    expect(await relay.get("/admin/settings/applied")).toEqual({ inline: true });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await relay.get("/admin/settings/applied")).toEqual({ net: true });
    expect(await relay.get("/admin/accounts", { accountId: "9" })).toEqual({ net: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("takeInline with React's client-side promise props", () => {
  afterEach(() => resetInline());

  // react-server-dom's Chunk: inherits Promise.prototype, `then(resolve, reject)` returns undefined.
  function chunk(value: InlineAnswer | Error, later = true): Promise<InlineAnswer> {
    const c = Object.create(Promise.prototype) as { then: (ok: (v: InlineAnswer) => void, bad: (e: unknown) => void) => void };
    c.then = (ok, bad) => {
      const go = () => (value instanceof Error ? bad(value) : ok(value));
      if (later) setTimeout(go, 0); else go();
    };
    return c as unknown as Promise<InlineAnswer>;
  }

  it("takes a chunk's answer, and a rejected chunk is a miss", async () => {
    seedInline({ "/auth/me": chunk({ status: 200, body: '{"user_id":"u1"}' }), "/chatter/me": chunk(new Error("x"), false) });
    expect(await (await takeInline("/auth/me"))!.json()).toEqual({ user_id: "u1" });
    expect(await takeInline("/chatter/me")).toBeNull();
  });
});
