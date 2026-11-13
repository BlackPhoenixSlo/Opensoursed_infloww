import { describe, expect, it } from "vitest";

import {
  canLoadOlder, hasOlder, initialOlderPager, isLoadingOlder, olderFailed, olderPagerReducer,
  type OlderPager, type OlderPagerAction,
} from "./olderPager";

const run = (actions: OlderPagerAction[], from: OlderPager = initialOlderPager()) => actions.reduce(olderPagerReducer, from);
const start = (seq: number): OlderPagerAction => ({ type: "start", seq });
const page = (seq: number, hasMore: boolean, progressed = true): OlderPagerAction => ({ type: "page", seq, hasMore, progressed });
const fail = (seq: number): OlderPagerAction => ({ type: "fail", seq });
const head = (hasMore: boolean): OlderPagerAction => ({ type: "head", hasMore });

describe("olderPagerReducer", () => {
  it.each<[string, OlderPagerAction[], OlderPager["status"]]>([
    ["a new chat is idle", [], "idle"],
    ["start loads", [start(1)], "loading"],
    ["a progressing page with more goes back to idle", [start(1), page(1, true)], "idle"],
    ["a page saying nothing older exhausts", [start(1), page(1, false)], "exhausted"],
    ["an empty / non-progressing page that still says more: error, not idle (no hot loop)", [start(1), page(1, true, false)], "error"],
    ["a non-progressing page saying nothing older still exhausts", [start(1), page(1, false, false)], "exhausted"],
    ["a failure (5xx, timeout) is an error", [start(1), fail(1)], "error"],
    ["Retry from error loads", [start(1), fail(1), start(2)], "loading"],
    ["Retry that lands goes back to idle", [start(1), fail(1), start(2), page(2, true)], "idle"],
    ["a second start while loading is dropped", [start(1), start(2), page(1, true)], "idle"],
    ["a stale page (other seq) changes nothing", [start(2), page(1, false)], "loading"],
    ["a stale failure changes nothing", [start(2), fail(1)], "loading"],
    ["a page with no start changes nothing", [page(1, false)], "idle"],
    ["start on exhausted is dropped", [start(1), page(1, false), start(2)], "exhausted"],
    // Tail exhaustion is sticky: head polls report the HEAD page's hasMore.
    ["a head poll saying more never reopens an exhausted pager", [start(1), page(1, false), head(true)], "exhausted"],
    ["a head page saying nothing older exhausts an idle pager", [head(false)], "exhausted"],
    ["a head page saying more leaves idle idle", [head(true)], "idle"],
    ["a head page saying more leaves an error an error", [start(1), fail(1), head(true)], "error"],
    ["a head page saying nothing older ends an error", [start(1), fail(1), head(false)], "exhausted"],
    ["a head page saying nothing older mid-load exhausts; the late page is stale", [start(1), head(false), page(1, true)], "exhausted"],
  ])("%s", (_name, actions, want) => {
    expect(run(actions).status).toBe(want);
  });

  it("an action that changes nothing keeps the same state object", () => {
    const s = run([start(1)]);
    expect(olderPagerReducer(s, start(2))).toBe(s);
    expect(olderPagerReducer(s, page(9, true))).toBe(s);
    const done = run([head(false)]);
    expect(olderPagerReducer(done, head(true))).toBe(done);
  });

  it("a chat whose prefetched head page said nothing older starts exhausted", () => {
    expect(initialOlderPager(true).status).toBe("exhausted");
    expect(initialOlderPager(false).status).toBe("idle");
  });
});

describe("olderPager reads", () => {
  it.each<[string, OlderPagerAction[], { hasOlder: boolean; loading: boolean; failed: boolean; canLoad: boolean }]>([
    ["idle", [], { hasOlder: true, loading: false, failed: false, canLoad: true }],
    ["loading", [start(1)], { hasOlder: true, loading: true, failed: false, canLoad: false }],
    ["error: button reads Retry, an explicit call may load", [start(1), fail(1)], { hasOlder: true, loading: false, failed: true, canLoad: true }],
    ["exhausted", [head(false)], { hasOlder: false, loading: false, failed: false, canLoad: false }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect({ hasOlder: hasOlder(s), loading: isLoadingOlder(s), failed: olderFailed(s), canLoad: canLoadOlder(s) }).toEqual(want);
  });
});
