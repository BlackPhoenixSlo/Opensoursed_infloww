import { describe, expect, it } from "vitest";

import {
  GESTURE_GAP_MS, initialLoadMore, listCaller, mayAutoPage, pendingFor, scrollGesture, scrollIntent, type IntentEvent, loadMoreReducer, startedBy,
  type Busy, type ListCaller, type LoadMoreState, type Pending,
} from "./chatListLoadMore";

describe("listCaller", () => {
  type In = Parameters<typeof listCaller>[0];
  const base: In = { fetchMore: false, pending: null, refresh: false, cached: false, offset: 0, query: false };
  it.each<[string, Partial<In>, ListCaller]>([
    ["cold page 0", {}, "mount"],
    ["cold page 0 of a search", { query: true }, "search"],
    ["walk over cached pages", { cached: true }, "replay"],
    ["walk past page 0", { offset: 25 }, "replay"],
    ["a search walk over cached pages is a replay, not a search", { cached: true, query: true }, "replay"],
    ["manual refresh", { refresh: true, cached: true, offset: 50 }, "refresh"],
    ["next page started by a click", { fetchMore: true, pending: "loadmore", cached: true, offset: 25 }, "loadmore"],
    ["next page started by autofill", { fetchMore: true, pending: "autofill", cached: true, offset: 25 }, "autofill"],
    ["next page with no known starter", { fetchMore: true, cached: true, offset: 25 }, "auto"],
    ["next page under a search, no starter", { fetchMore: true, query: true, cached: true, offset: 25 }, "auto"],
  ])("%s → %s", (_n, change, want) => {
    expect(listCaller({ ...base, ...change })).toBe(want);
  });
});

const K = "key-a";
const req = (caller: ListCaller, busy: Busy, more: Partial<{ hasMore: boolean; failed: boolean; mayAuto: boolean }> = {}) =>
  ({ type: "request", caller, busy, hasMore: true, failed: false, mayAuto: true, ...more }) as const;
const pend = (caller: ListCaller, explicit: boolean): Pending => ({ caller, explicit });

describe("loadMoreReducer: request", () => {
  it.each<[string, LoadMoreState, ReturnType<typeof req>, Pending | null, Pending | null]>([
    ["idle, automatic within budget: starts", initialLoadMore(K), req("autofill", "idle"), pend("autofill", false), null],
    ["idle, automatic past budget: nothing", initialLoadMore(K), req("autofill", "idle", { mayAuto: false }), null, null],
    ["idle, search past budget: nothing", initialLoadMore(K), req("search", "idle", { mayAuto: false }), null, null],
    ["idle, click past budget: starts with intent", initialLoadMore(K), req("loadmore", "idle", { mayAuto: false }), pend("loadmore", true), null],
    ["idle, fresh scroll past budget: starts with intent", initialLoadMore(K), req("scroll", "idle", { mayAuto: false }), pend("scroll", true), null],
    ["after a failed page, automatic: nothing", initialLoadMore(K), req("fill", "idle", { failed: true }), null, null],
    ["after a failed page, click: starts", initialLoadMore(K), req("loadmore", "idle", { failed: true }), pend("loadmore", true), null],
    ["no next page: nothing", initialLoadMore(K), req("loadmore", "idle", { hasMore: false }), null, null],
    ["next page in flight, click: joins", initialLoadMore(K), req("loadmore", "next"), null, null],
    ["walk in flight, automatic: nothing", initialLoadMore(K), req("autofill", "walk"), null, null],
    ["walk in flight, click: queued", initialLoadMore(K), req("loadmore", "walk"), null, pend("loadmore", true)],
    ["walk in flight over a list cached as ended, click: queued (the walk may find more)", initialLoadMore(K), req("loadmore", "walk", { hasMore: false }), null, pend("loadmore", true)],
    ["walk in flight, second click: still one queued", { ...initialLoadMore(K), queued: pend("scroll", true) }, req("loadmore", "walk"), null, pend("scroll", true)],
    ["a start not yet taken: a joiner never overwrites it", { ...initialLoadMore(K), pending: pend("autofill", false) }, req("loadmore", "idle"), pend("autofill", false), null],
  ])("%s", (_n, from, action, pending, queued) => {
    const s = loadMoreReducer(from, action);
    expect(s.pending).toEqual(pending);
    expect(s.queued).toEqual(queued);
  });
});

describe("loadMoreReducer: a queued click after the walk", () => {
  const queued = { ...initialLoadMore(K), queued: pend("loadmore", true) };
  it.each<[string, { ok: boolean; hasMore: boolean }, Pending | null]>([
    ["walk landed with more: the click's page starts", { ok: true, hasMore: true }, pend("loadmore", true)],
    ["walk landed, no more: dropped", { ok: true, hasMore: false }, null],
    ["walk failed: dropped, a new click is needed", { ok: false, hasMore: true }, null],
  ])("%s", (_n, settled, started) => {
    const s = loadMoreReducer(queued, { type: "settled", ...settled });
    expect(startedBy(queued, s)).toEqual(started);
    expect(s.queued).toBeNull();
  });

  it("another list drops the queue and the pending start", () => {
    const busy = { ...queued, pending: pend("autofill", false) };
    expect(loadMoreReducer(busy, { type: "reset", key: "key-b" })).toEqual(initialLoadMore("key-b"));
    expect(loadMoreReducer(busy, { type: "reset", key: K })).toBe(busy);
  });

  it("a taken start stays with its offset until the fetch settles, so a retry keeps its intent", () => {
    const p = pend("loadmore", true);
    const s = loadMoreReducer({ ...initialLoadMore(K), pending: p }, { type: "taken", pending: p, offset: 100 });
    expect(s.pending).toBeNull();
    expect(pendingFor(s, 100)).toBe(p);
    expect(pendingFor(s, 125)).toBeNull();
    expect(pendingFor(loadMoreReducer(s, { type: "settled", ok: false, hasMore: true }), 100)).toBeNull();
  });

  it("taken clears only its own start", () => {
    const p = pend("scroll", true);
    const s = { ...initialLoadMore(K), pending: p };
    expect(loadMoreReducer(s, { type: "taken", pending: p }).pending).toBeNull();
    expect(loadMoreReducer(s, { type: "taken", pending: pend("scroll", true) })).toBe(s);
  });
});

describe("mayAutoPage", () => {
  it.each<[number, number, boolean, string]>([
    [0, 0, true, ""],
    [1, 25, true, "floor"],
    [2, 7, true, ""],
    [2, 8, false, ""],
    [3, 0, true, ""],
    [3, 7, true, ""],
    [3, 8, false, ""],
    [4, 0, false, "ceiling"],
    [6, 0, false, "cached deep list"],
    [3, 2, true, "group unresolved, sparse relay rows"],
  ])("pages %i, visible rows %i: %s %s", (pagesLoaded, visibleRows, want) => {
    expect(mayAutoPage({ pagesLoaded, visibleRows })).toBe(want);
  });
});

describe("scrollIntent", () => {
  it.each<[IntentEvent, boolean]>([
    [{ type: "wheel", deltaY: 40 }, true],
    [{ type: "wheel", deltaY: -40 }, false],
    [{ type: "wheel", deltaY: 0 }, false],
    [{ type: "touchmove" }, true],
    [{ type: "keydown", key: "PageDown" }, true],
    [{ type: "keydown", key: "End" }, true],
    [{ type: "keydown", key: " " }, true],
    [{ type: "keydown", key: "ArrowUp" }, false],
    [{ type: "keydown", key: "a" }, false],
    [{ type: "scroll" }, false],
  ])("%j -> %s", (e, want) => {
    expect(scrollIntent(e)).toBe(want);
  });
});

describe("scrollGesture", () => {
  it.each<[string, Array<[IntentEvent, number]>, boolean[]]>([
    ["one wheel gesture is one start", [[{ type: "wheel", deltaY: 9 }, 0], [{ type: "wheel", deltaY: 9 }, 50], [{ type: "wheel", deltaY: 9 }, 400]], [true, false, false]],
    ["a pause starts a new gesture", [[{ type: "wheel", deltaY: 9 }, 0], [{ type: "wheel", deltaY: 9 }, GESTURE_GAP_MS + 1]], [true, true]],
    ["non-intent events never start one", [[{ type: "scroll" }, 0], [{ type: "wheel", deltaY: -9 }, 1000]], [false, false]],
    ["held key repeats cannot rearm after the gap", [[{ type: "keydown", key: "PageDown" }, 0], [{ type: "keydown", key: "PageDown", repeat: true }, GESTURE_GAP_MS + 1], [{ type: "keydown", key: "PageDown" }, GESTURE_GAP_MS + 2]], [true, false, true]],
  ])("%s", (_name, events, want) => {
    const fresh = scrollGesture();
    expect(events.map(([e, t]) => fresh(e, t))).toEqual(want);
  });
});
