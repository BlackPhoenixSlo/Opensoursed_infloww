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
  thumbGiveUp,
  thumbRefreshReducer as r,
  thumbSrc,
  useThumbAutoRefresh,
  type ThumbRefreshAction,
  type ThumbRefreshState,
} from "@/hooks/useThumbAutoRefresh";
import { type VaultMedia } from "@/lib/relay";

const S0: ThumbRefreshState = { ...INITIAL_THUMB_REFRESH, scope: "A" };
const run = (acts: ThumbRefreshAction[], s: ThumbRefreshState = S0) => acts.reduce(r, s);
const broken = (id: string, src = `/t/${id}`): ThumbRefreshAction => ({ type: "broken", id, src });
const fire = (scope = "A"): ThumbRefreshAction => ({ type: "fire", scope });
const refreshed = (scope = "A"): ThumbRefreshAction => ({ type: "refreshed", scope });

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
    // F7: given up on in an earlier mount (a reopened picker): no reload again.
    ["given up in an earlier mount: its placeholder, no reload",
      [{ type: "broken", id: "a", src: "/t/a", gaveUp: true }], { pending: [], nonces: {}, failed: { a: "/t/a" } }],
    // F8: the user's Refresh is the retry of every tile waiting or given up on.
    ["refreshed: waiting and given-up tiles on a new nonce, give-ups dropped",
      [broken("a"), fire(), broken("a", "/t/a?_r=1"), broken("b"), refreshed()],
      { nonce: 2, pending: [], nonces: { a: 2, b: 2 }, failed: {} }],
    ["refreshed leaves a tile that loaded after its retry as is",
      [broken("a"), fire(), broken("b"), refreshed()], { nonce: 2, nonces: { a: 1, b: 2 } }],
    ["refreshed with nothing broken is a no-op", [refreshed()], { nonce: 0, nonces: {} }],
    ["refreshed for another scope is ignored", [broken("a"), refreshed("B")], { nonce: 0, pending: ["a"] }],
    ["broken again after the Refresh: given up, no reload",
      [broken("a"), fire(), broken("a", "/t/a?_r=1"), refreshed(), broken("a", "/t/a?_r=2")],
      { pending: [], nonces: { a: 2 }, failed: { a: "/t/a?_r=2" } }],
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
    // F8: the mirror's thumb url is stable; after the Refresh it is asked for again on a new nonce.
    ["given up, then the user's Refresh: on its new nonce",
      [broken("2", base), fire(), broken("2", `${base}&_r=1`), refreshed()], `${base}&_r=2`],
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
  type Grid = ReturnType<typeof grid>;
  const M = (id: string, src = SRC) => ({ id, _thumb: src }) as unknown as VaultMedia;
  const thumb = (g: Grid, id: string) => g.result.current.tile(M(id)).src;
  const broke = (g: Grid, id: string) => act(() => g.result.current.tile(M(id)).onError());
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
    broke(g, "m1");
    expect(thumb(g, "m1")).toBe("");
    await advance(DEBOUNCE_MS);
    expect(reloads).toHaveLength(1);
    expect(thumb(g, "m1")).toBe("");   // reload in flight: still the placeholder
    await settle(0);
    expect(thumb(g, "m1")).toBe(`${SRC}&_r=1`);
  });

  it("two grids of one Creator: one reload per cooldown", async () => {
    const a = creator();
    const g1 = grid(a);
    const g2 = grid(a);
    act(() => { g1.result.current.tile(M("m1")).onError(); g2.result.current.tile(M("m2")).onError(); });
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
    broke(g, "m1");
    await advance(DEBOUNCE_MS);
    await settle(0);
    broke(g, "m2");
    await advance(COOLDOWN_MS - 1);
    expect(reloads).toHaveLength(1);
    expect(thumb(g, "m2")).toBe("");
    await advance(1);
    expect(reloads).toHaveLength(2);
    await settle(1);
    expect(thumb(g, "m2")).toBe(`${SRC}&_r=2`);
    expect(thumb(g, "m1")).toBe(`${SRC}&_r=1`);
  });

  it("a reload settling after the grid moved to another Creator answers none of its tiles", async () => {
    const [a, b] = [creator(), creator()];
    const g = grid(a);
    broke(g, "m1");
    await advance(DEBOUNCE_MS);
    expect(reloads[0].accountId).toBe(a);
    g.rerender({ id: b });
    broke(g, "b1");
    await settle(0);   // A's reload lands late
    expect(thumb(g, "b1")).toBe("");
    await advance(DEBOUNCE_MS);   // B's own reload
    expect(reloads.map((x) => x.accountId)).toEqual([a, b]);
    await settle(1);
    expect(thumb(g, "b1")).toBe(`${SRC}&_r=1`);
  });

  // R3-1: a thumb broken for good costs one reload, not one per cooldown for as long as the grid is open.
  it("a tile broken again after its retry triggers no further reload", async () => {
    const g = grid(creator());
    broke(g, "m1");
    await advance(DEBOUNCE_MS);
    await settle(0);
    broke(g, "m1");   // its retried src, `${SRC}&_r=1`
    await advance(2 * COOLDOWN_MS);
    expect(reloads).toHaveLength(1);
    expect(thumb(g, "m1")).toBe("");   // R4-1: its placeholder, not a broken image
  });

  // F7: a give-up survives a remount (a reopened picker), so it costs no further relay vault-cache drop.
  it("a tile given up on stays given up after a remount: no reload", async () => {
    const a = creator();
    const g = grid(a);
    broke(g, "m1");
    await advance(DEBOUNCE_MS);
    await settle(0);
    broke(g, "m1");
    await act(async () => {});
    expect(thumbGiveUp.has(a, "m1")).toBe(true);
    g.unmount();
    await advance(2 * COOLDOWN_MS);
    const g2 = grid(a);
    broke(g2, "m1");
    expect(thumb(g2, "m1")).toBe("");
    await advance(2 * COOLDOWN_MS);
    expect(reloads).toHaveLength(1);
  });

  // F8: the user's Refresh draws a given-up tile again, once; the give-up is forgotten.
  it("refreshed: a given-up tile is asked for again, and given up again on failure without a reload", async () => {
    const a = creator();
    const g = grid(a);
    broke(g, "m1");
    await advance(DEBOUNCE_MS);
    await settle(0);
    broke(g, "m1");
    await act(async () => {});
    expect(thumb(g, "m1")).toBe("");
    act(() => g.result.current.refreshed(a));
    expect(thumbGiveUp.has(a, "m1")).toBe(false);
    expect(thumb(g, "m1")).toBe(`${SRC}&_r=2`);
    broke(g, "m1");
    expect(thumb(g, "m1")).toBe("");
    await advance(2 * COOLDOWN_MS);
    expect(reloads).toHaveLength(1);
  });

  it("no Creator: nothing reloads", async () => {
    const g = grid(null);
    broke(g, "m1");
    await advance(COOLDOWN_MS);
    expect(reloads).toHaveLength(0);
  });
});
