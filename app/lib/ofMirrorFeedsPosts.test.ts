import { describe, expect, it, vi } from "vitest";
import { applyData } from "./ofMirrorData";
import { markerPagesQuery } from "./ofMirrorDataQueries";
import { nextFeedOffset, nextMarker } from "./ofMirrorPaging";
import { feedTime } from "./ofMirrorFeedsPosts";
import type { MirrorPost } from "./ofMirrorFeedsShared";
import { relay } from "./relay";
import { load, POST_TPL } from "./ofMirrorData.fixtures";

describe("feedTime: OF's post time (UtilsTime, type feed)", () => {
  const now = new Date("2026-10-18T15:00:00");
  const at = (iso: string) => feedTime(new Date(iso), now);
  it("today relative as dayjs's fromNow, then Yesterday, this year's day, an older year's date; a scheduled one ahead", () => {
    expect(["2026-10-18T14:59:30", "2026-10-18T14:59:00", "2026-10-18T14:58:00", "2026-10-18T14:16:00", "2026-10-18T14:00:00", "2026-10-18T11:00:00", "2026-10-18T00:30:00"].map(at)).toEqual([
      "seconds ago", "1 minute ago", "2 minutes ago", "44 minutes ago", "1 hour ago", "4 hours ago", "15 hours ago",
    ]);
    expect(["2026-10-17T23:59:00", "2026-10-16T12:00:00", "2026-01-02T08:00:00", "2025-12-31T08:00:00"].map(at)).toEqual(["Yesterday", "Oct 16", "Jan 2", "Dec 31, 2025"]);
    expect(["2026-10-18T18:00:00", "2026-10-19T09:05:00", "2026-11-02T21:30:00", "2027-01-03T08:00:00"].map(at)).toEqual(["in 3 hours", "Tomorrow, 9:05 am", "Nov 2, 9:30 pm", "Jan 3 2027, 8:00 am"]);
  });
});

describe("Home's feed and My profile's wall: OF's infinite scroll (U4)", () => {
  const P = (n: number, from = 1) => Array.from({ length: n }, (_, i) => ({ id: from + i }));
  const io = () => {
    const seen: Element[] = [];
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: typeof fire) {
        fire = cb;
      }
      observe(el: Element) {
        seen.push(el);
      }
      disconnect() {}
    });
    return { seen, fire: (v: boolean) => fire([{ isIntersecting: v }]) };
  };

  it("the wall's next page is OF's tailMarker while it says hasMore with rows and a marker that moved", () => {
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: "1760000000.000000" }, [], null)).toBe("1760000000.000000");
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: 1760000000 }, [], null)).toBe("1760000000");
    expect(nextMarker({ list: P(20), hasMore: false, tailMarker: "1" }, [], null)).toBeUndefined();
    expect(nextMarker({ list: [], hasMore: true, tailMarker: "1" }, [], null)).toBeUndefined();
    expect(nextMarker({ list: P(20), hasMore: true }, [], null)).toBeUndefined();
    expect(nextMarker({ list: P(20), hasMore: true, tailMarker: "7" }, [], "7")).toBeUndefined();
    expect(nextMarker(P(20), [], null)).toBeUndefined();
  });

  it("the wall reads its first page, then each before the last one's marker", async () => {
    const get = vi.spyOn(relay, "get").mockResolvedValue({ list: [] });
    try {
      const o = markerPagesQuery("a1", "/api/of/v2/users/9/posts?limit=20&format=infinite", true);
      expect(o.queryKey).toEqual(["of-mirror-data", "a1", "/api/of/v2/users/9/posts?limit=20&format=infinite", "pages"]);
      const fn = o.queryFn as unknown as (c: { pageParam: string | null }) => Promise<unknown>;
      await fn({ pageParam: null });
      await fn({ pageParam: "1760000000.5" });
      expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/of/v2/users/9/posts?limit=20&format=infinite", "/api/of/v2/users/9/posts?limit=20&format=infinite&before_publish_time=1760000000.5"]);
      expect(markerPagesQuery("a1", null, true).enabled).toBe(false);
    } finally {
      get.mockRestore();
    }
  });

  it("Home's next offset: OF's hasMore/nextOffset when it sends a list; a bare array has more when it is a full page", () => {
    expect(nextFeedOffset(P(20), [P(20)])).toBe(20);
    expect(nextFeedOffset(P(20, 21), [P(20), P(20, 21)])).toBe(40);
    expect(nextFeedOffset(P(7), [P(20), P(7)])).toBeUndefined();
    expect(nextFeedOffset([], [[]])).toBeUndefined();
    expect(nextFeedOffset({ list: P(20), hasMore: true }, [{ list: P(20) }])).toBe(20);
    expect(nextFeedOffset({ list: P(20), hasMore: false }, [{ list: P(20) }])).toBeUndefined();
  });

  it("Home: OF's loading row trails the feed, asks for the next page in view, spins while it loads, and offers Retry on an error", () => {
    const doc = load("home/index");
    const box = doc.querySelector(".b-feed-content > .infinite-loading-container")!;
    expect(box).not.toBeNull();
    const prompts = () => [...box.querySelectorAll<HTMLElement>(":scope > .infinite-status-prompt")].map((p) => p.style.display !== "none");
    expect(prompts()).toEqual([false, false, false, false]);
    const next = vi.fn();
    const posts = [{ id: 11, author: { id: 515 } }, { id: 12, author: { id: 4242 } }] as MirrorPost[];
    const w = io();
    try {
      applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: false, error: null, next } });
      expect(w.seen).toEqual([box]);
      const rows = [...doc.querySelectorAll(".b-feed-content .user_posts [data-oi-post]")];
      expect(rows).toHaveLength(2);
      expect(rows.every((r) => r.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      w.fire(false);
      expect(next).not.toHaveBeenCalled();
      w.fire(true);
      expect(next).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
    applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: true, error: null, next } });
    expect(prompts()).toEqual([true, false, false, false]);
    applyData(doc, "home/index", { home: posts, templates: { post: POST_TPL }, homeMore: { loading: false, error: "boom", next } });
    expect(prompts()).toEqual([false, false, false, true]);
    box.querySelector<HTMLButtonElement>(".infinite-status-prompt:last-child button")!.click();
    expect(next).toHaveBeenCalledTimes(2);
    applyData(doc, "home/index", {});
    expect(prompts()).toEqual([false, false, false, false]);
  });

  it("My profile: OF's loading row stays under the wall's rows and asks for the next page in view; none when the wall is empty", () => {
    const doc = load("profile/index");
    const box = doc.querySelector(".user_posts .infinite-loading-container")!;
    expect(box).not.toBeNull();
    const next = vi.fn();
    const w = io();
    try {
      applyData(doc, "profile/index", { posts: [{ id: 1 }, { id: 2 }, { id: 3 }] as MirrorPost[], postsMore: { loading: false, error: null, next } });
      const rows = [...doc.querySelectorAll(".user_posts .vue-recycle-scroller__item-view")].filter((r) => !r.closest("[style*='display:none']") && r.querySelector("div.b-post"));
      expect(rows).toHaveLength(3);
      expect(rows.every((r) => r.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
      expect(w.seen).toEqual([box]);
      w.fire(true);
      expect(next).toHaveBeenCalledTimes(1);
      applyData(doc, "profile/index", { posts: [], postsMore: { loading: false, error: null, next } });
      expect(w.seen).toEqual([box]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
