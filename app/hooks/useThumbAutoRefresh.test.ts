import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// The reload itself (hooks/vaultRefresh): each call returns a promise the test settles.
const reloads: { accountId: string; resolve: () => void }[] = [];
vi.mock("@/hooks/vaultRefresh", () => ({
  reloadBrokenThumbs: vi.fn((_qc: unknown, accountId: string) =>
    new Promise<void>((resolve) => reloads.push({ accountId, resolve }))),
}));

import {
  COOLDOWN_MS,
  DEBOUNCE_MS,
  INITIAL_THUMB_REFRESH,
  fireDelay,
  retrySrc,
  thumbCooldown,
  thumbRefreshReducer as r,
  thumbSrc,
  useThumbAutoRefresh,
  type ThumbRefreshAction,
  type ThumbRefreshState,
} from "@/hooks/useThumbAutoRefresh";

const S0: ThumbRefreshState = { ...INITIAL_THUMB_REFRESH, scope: "A" };
const run = (acts: ThumbRefreshAction[], s: ThumbRefreshState = S0) => acts.reduce(r, s);
const broken = (id: string, src = `/t/${id}`): ThumbRefreshAction => ({ type: "broken", id, src });
const fire = (scope = "A"): ThumbRefreshAction => ({ type: "fire", scope });

describe("thumbRefreshReducer", () => {
  it.each<[string, ThumbRefreshAction[], Partial<ThumbRefreshState>]>([
    ["nothing broken: fire is a no-op", [fire()], { nonce: 0, nonces: {} }],
    ["N broken tiles, one fire: one reload's nonce", [broken("a"), broken("b"), broken("c"), fire()],
      { nonce: 1, pending: [], nonces: { a: 1, b: 1, c: 1 } }],
    ["the same tile twice counts once", [broken("a"), broken("a")], { pending: ["a"] }],
    // Review #2: a tile retried by an earlier reload keeps its nonce when a later one answers other tiles.
    ["retried tile, then another reload: the first keeps its nonce",
      [broken("a"), fire(), broken("b"), fire()], { nonce: 2, nonces: { a: 1, b: 2 } }],
    // R3-1: a tile broken for good is retried once, not on every cooldown.
    // R4-1: ... and remembers the src that failed, for its placeholder.
    ["a tile broken again after its retry is not retried again",
      [broken("a"), fire(), broken("a", "/t/a?_r=1")], { pending: [], nonces: { a: 1 }, failed: { a: "/t/a?_r=1" } }],
    ["... and a later reload of other tiles leaves it as is",
      [broken("a"), fire(), broken("a", "/t/a?_r=1"), broken("b"), fire()],
      { nonce: 2, nonces: { a: 1, b: 2 }, failed: { a: "/t/a?_r=1" } }],
    // R2-2: a reload of another Creator settling late answers none of this grid's tiles.
    ["a fire for another scope is ignored", [broken("a"), fire("B")], { nonce: 0, pending: ["a"], nonces: {} }],
    ["reset clears everything and takes the new scope", [broken("a"), fire(), broken("b"), { type: "reset", scope: "B" }],
      { ...INITIAL_THUMB_REFRESH, scope: "B" }],
  ])("%s", (_name, acts, want) => {
    expect(run(acts)).toMatchObject(want);
  });
});

describe("thumbSrc", () => {
  const base = "/admin/vault-ai/thumb?account_id=1&media_id=2";
  it.each<[string, ThumbRefreshAction[], string]>([
    ["never broken: as is", [], base],
    ["broken, waiting: the placeholder", [broken("2")], ""],
    ["retried: with its nonce", [broken("2"), fire()], `${base}&_r=1`],
    // Review #2: the old code fell back to nonce 0 here, the src went back to the one that failed.
    ["retried, then another tile's reload: still its nonce", [broken("2"), fire(), broken("9"), fire()], `${base}&_r=1`],
    // R4-1: not the browser's broken-image icon.
    ["retried, broken again: the placeholder", [broken("2", base), fire(), broken("2", `${base}&_r=1`)], ""],
  ])("%s", (_n, acts, want) => expect(thumbSrc(run(acts), "2", base)).toBe(want));

  it("src changes after the give-up (a Refresh's new url): the image again", () => {
    const s = run([broken("2", base), fire(), broken("2", `${base}&_r=1`)]);
    expect(thumbSrc(s, "2", `${base}&v=2`)).toBe(`${base}&v=2&_r=1`);
  });

  it("no picture stays no picture", () => expect(thumbSrc(run([broken("2")]), "2", "")).toBe(""));
});

// The cooldown is module state that outlives every grid (and test): each test takes fresh Creator ids.
let creators = 0;
const creator = () => `creator-${++creators}`;

// R2-1: the cooldown's one check.
describe("thumbCooldown.claim", () => {
  it("one claim per cooldown per Creator; another Creator is free", () => {
    const [a, b] = [creator(), creator()];
    expect(thumbCooldown.claim(a, 1000)).toBe(true);
    expect(thumbCooldown.claim(a, 2000)).toBe(false);
    expect(thumbCooldown.claim(b, 2000)).toBe(true);
    expect(thumbCooldown.claim(a, 1000 + COOLDOWN_MS - 1)).toBe(false);
    expect(thumbCooldown.claim(a, 1000 + COOLDOWN_MS)).toBe(true);
    expect(thumbCooldown.lastAt(a)).toBe(1000 + COOLDOWN_MS);
  });

  it("a CDN that stays down: at most one claim per cooldown over an hour of tries", () => {
    const a = creator();
    let n = 0;
    for (let t = 0; t < 60 * 60_000; t += 1000) if (thumbCooldown.claim(a, t)) n++;
    expect(n).toBe(Math.ceil((60 * 60_000) / COOLDOWN_MS));
  });
});

// Review #12: a tile broken during the cooldown is retried when it ends, not never.
describe("fireDelay", () => {
  it.each<[string, number | null, number, number]>([
    ["never reloaded: the debounce", null, 1000, DEBOUNCE_MS],
    ["cooldown long over: the debounce", 0, 2 * COOLDOWN_MS, DEBOUNCE_MS],
    ["inside the cooldown: until it ends", 0, 60_000, COOLDOWN_MS - 60_000],
    ["cooldown ends within the debounce: the debounce", 0, COOLDOWN_MS - 100, DEBOUNCE_MS],
  ])("%s", (_n, lastAt, now, want) => expect(fireDelay(lastAt, now)).toBe(want));
});

describe("retrySrc", () => {
  it.each<[string, number, string]>([
    ["/admin/vault-ai/thumb?account_id=1&media_id=2", 0, "/admin/vault-ai/thumb?account_id=1&media_id=2"],
    ["/admin/vault-ai/thumb?account_id=1&media_id=2", 3, "/admin/vault-ai/thumb?account_id=1&media_id=2&_r=3"],
    ["/x.jpg", 1, "/x.jpg?_r=1"],
    ["", 2, ""],
  ])("%s @%i", (src, nonce, want) => expect(retrySrc(src, nonce)).toBe(want));
});

// Review #15 / R2-2: the hook's real timer path (fake timers, the reload mocked at its module boundary).
describe("useThumbAutoRefresh", () => {
  const SRC = "/img?u=x";
  let client: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const grid = (accountId: string | null) =>
    renderHook(({ id }: { id: string | null }) => useThumbAutoRefresh(id, "live"), {
      wrapper, initialProps: { id: accountId },
    });
  const settle = async (i: number) => {
    await act(async () => { reloads[i].resolve(); await Promise.resolve(); });
  };
  const advance = async (ms: number) => { await act(async () => { vi.advanceTimersByTime(ms); }); };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(10 * COOLDOWN_MS);
    client = new QueryClient();
    reloads.length = 0;
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("the tile is retried only after its reload settled", async () => {
    const g = grid(creator());
    act(() => g.result.current.onBroken("m1", SRC));
    expect(g.result.current.thumbFor("m1", SRC)).toBe("");
    await advance(DEBOUNCE_MS);
    expect(reloads).toHaveLength(1);
    expect(g.result.current.thumbFor("m1", SRC)).toBe("");   // reload in flight: still the placeholder
    await settle(0);
    expect(g.result.current.thumbFor("m1", SRC)).toBe(`${SRC}&_r=1`);
  });

  it("two grids of one Creator: one reload per cooldown", async () => {
    const a = creator();
    const g1 = grid(a);
    const g2 = grid(a);
    act(() => { g1.result.current.onBroken("m1", SRC); g2.result.current.onBroken("m2", SRC); });
    await advance(DEBOUNCE_MS);
    expect(reloads).toHaveLength(1);
    await settle(0);
    await advance(COOLDOWN_MS - 1);
    expect(reloads).toHaveLength(1);
    await advance(1);   // the second grid's tile, still broken, is retried when the cooldown ends
    expect(reloads).toHaveLength(2);
  });

  it("a tile broken during the cooldown is retried when it ends", async () => {
    const g = grid(creator());
    act(() => g.result.current.onBroken("m1", SRC));
    await advance(DEBOUNCE_MS);
    await settle(0);
    act(() => g.result.current.onBroken("m2", SRC));
    await advance(COOLDOWN_MS - 1);
    expect(reloads).toHaveLength(1);
    expect(g.result.current.thumbFor("m2", SRC)).toBe("");
    await advance(1);
    expect(reloads).toHaveLength(2);
    await settle(1);
    expect(g.result.current.thumbFor("m2", SRC)).toBe(`${SRC}&_r=2`);
    expect(g.result.current.thumbFor("m1", SRC)).toBe(`${SRC}&_r=1`);
  });

  it("a reload settling after the grid moved to another Creator answers none of its tiles", async () => {
    const [a, b] = [creator(), creator()];
    const g = grid(a);
    act(() => g.result.current.onBroken("m1", SRC));
    await advance(DEBOUNCE_MS);
    expect(reloads[0].accountId).toBe(a);
    g.rerender({ id: b });
    act(() => g.result.current.onBroken("b1", SRC));
    await settle(0);   // A's reload lands late
    expect(g.result.current.thumbFor("b1", SRC)).toBe("");
    await advance(DEBOUNCE_MS);   // B's own reload
    expect(reloads.map((x) => x.accountId)).toEqual([a, b]);
    await settle(1);
    expect(g.result.current.thumbFor("b1", SRC)).toBe(`${SRC}&_r=1`);
  });

  // R3-1: a thumb broken for good costs one reload, not one per cooldown for as long as the grid is open.
  it("a tile broken again after its retry triggers no further reload", async () => {
    const g = grid(creator());
    act(() => g.result.current.onBroken("m1", SRC));
    await advance(DEBOUNCE_MS);
    await settle(0);
    act(() => g.result.current.onBroken("m1", `${SRC}&_r=1`));
    await advance(2 * COOLDOWN_MS);
    expect(reloads).toHaveLength(1);
    expect(g.result.current.thumbFor("m1", SRC)).toBe("");   // R4-1: its placeholder, not a broken image
  });

  it("no Creator: nothing reloads", async () => {
    const g = grid(null);
    act(() => g.result.current.onBroken("m1", SRC));
    await advance(COOLDOWN_MS);
    expect(reloads).toHaveLength(0);
  });
});
