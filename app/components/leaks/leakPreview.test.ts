import { afterEach, describe, expect, it } from "vitest";

import { golden } from "@/app/creators/leaks/leakPageHarness";

import {
  PREVIEW_LABEL, STRIP_MAX, previewTiles, stripTiles, thumbSrc, thumbState, TILE_START, tileReducer, tileView,
  type ThumbState, type TileAction, type TileState,
} from "./leakPreview";
import type { Leak } from "./leakView";

const CREATOR_LEAKS: Leak[] = golden("creator_leaks").leaks;
const MEDIA = CREATOR_LEAKS.find((l) => l.preview)!;
const NOW = new Date("2026-11-28T10:00:00Z");
const TZ = "UTC";

const media = (id: string, seen: string | null, first = "2026-11-20T00:00:00Z", over: Partial<Leak> = {}): Leak => ({
  ...MEDIA, leak_id: id, first_seen_at: first, preview: seen ? { vertical: "images", seen_at: seen } : null, ...over,
});

describe("thumbState", () => {
  it.each<[boolean, boolean, boolean, ThumbState]>([
    [true, true, false, "placeholder"],
    [true, true, true, "placeholder"],
    [true, false, false, "placeholder"],
    [true, false, true, "placeholder"],
    [false, false, false, "placeholder"],
    [false, false, true, "placeholder"],
    [false, true, false, "blurred"],
    [false, true, true, "clear"],
  ])("sfw %s, previews %s, revealed %s -> %s", (sfw, previews, revealed, want) => {
    expect(thumbState(sfw, previews, revealed)).toBe(want);
  });
});

describe("previewTiles", () => {
  it("keeps only Leaks with a preview, newest seen_at first, then first_seen_at", () => {
    const leaks = [
      media("a", "2026-11-25T00:00:00Z"),
      media("b", null),
      media("c", "2026-11-27T00:00:00Z", "2026-11-01T00:00:00Z"),
      media("d", "2026-11-27T00:00:00Z", "2026-11-05T00:00:00Z"),
      { ...CREATOR_LEAKS.find((l) => l.kind === "page")!, preview: null },
    ];
    expect(previewTiles(leaks, true, "acc-a", NOW, TZ).map((t) => t.leakId)).toEqual(["d", "c", "a"]);
  });

  it("the golden media Leak reads its site, title, pill and the seen line", () => {
    const [t] = previewTiles(CREATOR_LEAKS, true, "acc-a", NOW, TZ);
    expect(t).toMatchObject({
      leakId: "lk_0005", accountId: "acc-a", site: "example-leaks.test", title: "miavale set 2", pill: "not_checked",
      url: "https://pics.example-leaks.test/miavale/set-2", seen: "Seen in Google Images · 27 Nov", thumb: true,
    });
  });

  it("videos read Google Videos, and an empty title falls back to the url", () => {
    const [t] = previewTiles([media("v", "2026-11-27T00:00:00Z", undefined, { title: "", preview: { vertical: "videos", seen_at: "2026-11-27T00:00:00Z" } })], true, "acc-a", NOW, TZ);
    expect([t.seen, t.title]).toEqual(["Seen in Google Videos · 27 Nov", MEDIA.url]);
  });

  it("a seen_at that does not parse drops the date, never prints raw text", () => {
    const [t] = previewTiles([media("bad", "not a date")], true, "acc-a", NOW, TZ);
    expect(t.seen).toBe("Seen in Google Images");
  });

  it("previews off: media Leaks become text tiles with no thumb, page Leaks stay out", () => {
    const tiles = previewTiles([...CREATOR_LEAKS.map((l) => ({ ...l, preview: null })), media("b", null)], false, "acc-a", NOW, TZ);
    expect(tiles.map((t) => [t.leakId, t.thumb, t.kind])).toEqual([["lk_0005", false, "media"], ["b", false, "media"]]);
    expect(tiles[0].seen).not.toContain("Google");
  });

  it("a Leak's own account_id wins over the drill-in's Creator", () => {
    const [t] = previewTiles([media("x", "2026-11-27T00:00:00Z", undefined, { account_id: "acc-c" })], true, "acc-a", NOW, TZ);
    expect([t.accountId, t.key]).toEqual(["acc-c", "acc-c:x"]);
  });
});

describe("stripTiles", () => {
  const names = { "acc-a": "Creator A", "acc-c": "Creator C" };
  it("caps at 12, newest seen_at first, each naming its Creator", () => {
    const rows = Array.from({ length: 15 }, (_, i) =>
      media(`m${i}`, `2026-11-${String(10 + i).padStart(2, "0")}T00:00:00Z`, undefined, { account_id: i % 2 ? "acc-c" : "acc-a" }));
    const tiles = stripTiles(rows, names, NOW, TZ);
    expect(tiles).toHaveLength(STRIP_MAX);
    expect(tiles.map((t) => t.leakId)).toEqual(Array.from({ length: 12 }, (_, i) => `m${14 - i}`));
    expect(tiles.map((t) => t.creator)).toEqual(tiles.map((t) => names[t.accountId as keyof typeof names]));
  });

  it("drops rows with no preview, no account or a Creator not in view", () => {
    const rows = [
      media("ok", "2026-11-27T00:00:00Z", undefined, { account_id: "acc-a" }),
      media("np", null, undefined, { account_id: "acc-a" }),
      media("na", "2026-11-27T00:00:00Z"),
      media("hidden", "2026-11-27T00:00:00Z", undefined, { account_id: "acc-z" }),
    ];
    expect(stripTiles(rows, names, NOW, TZ).map((t) => t.leakId)).toEqual(["ok"]);
  });
});

describe("thumbSrc", () => {
  it.each([
    [null, "/admin/leaks/watches/acc-a/leaks/lk_0005/thumb"],
    ["acc-b", "/admin/leaks/watches/acc-a/leaks/lk_0005/thumb?account_id=acc-b"],
  ])("scope %s -> %s", (scope, want) => {
    expect(thumbSrc({ accountId: "acc-a", leakId: "lk_0005" }, scope)).toBe(want);
  });

  afterEach(() => window.localStorage.clear());

  it("a share token rides along", () => {
    window.localStorage.setItem("chatterly:share_token", "share-tok");
    expect(thumbSrc({ accountId: "acc-a", leakId: "lk_0005" }, "acc-b"))
      .toBe("/admin/leaks/watches/acc-a/leaks/lk_0005/thumb?account_id=acc-b&t=share-tok");
  });
});

describe("tileReducer", () => {
  it.each<[string, TileState, TileAction, TileState]>([
    ["toggle unblurs", TILE_START, { type: "toggle" }, { revealed: true, phase: "first" }],
    ["toggle again blurs", { revealed: true, phase: "first" }, { type: "toggle" }, TILE_START],
    ["a first error waits to retry, reveal kept", { revealed: true, phase: "first" }, { type: "error" }, { revealed: true, phase: "waiting" }],
    ["the wait ends in one retry", { revealed: true, phase: "waiting" }, { type: "retry" }, { revealed: true, phase: "retry" }],
    ["a retry before any error does nothing", TILE_START, { type: "retry" }, TILE_START],
    ["an error while waiting does nothing", { revealed: false, phase: "waiting" }, { type: "error" }, { revealed: false, phase: "waiting" }],
    ["the retry failing latches and drops the reveal", { revealed: true, phase: "retry" }, { type: "error" }, { revealed: false, phase: "failed" }],
    ["a failed tile ignores toggles", { revealed: false, phase: "failed" }, { type: "toggle" }, { revealed: false, phase: "failed" }],
    ["a failed tile ignores retries", { revealed: false, phase: "failed" }, { type: "retry" }, { revealed: false, phase: "failed" }],
  ])("%s", (_label, state, action, want) => {
    expect(tileReducer(state, action)).toEqual(want);
  });
});

describe("tileView", () => {
  const IMG = { image: true, label: "Unblur preview", attempt: 0, hidden: false } as const;
  it.each<[string, TileState, boolean, boolean, ReturnType<typeof tileView>]>([
    ["sfw on", TILE_START, true, true, { image: false, failed: false }],
    ["sfw on, failed", { revealed: false, phase: "failed" }, true, true, { image: false, failed: false }],
    ["no thumb (previews off or none yet)", TILE_START, false, false, { image: false, failed: false }],
    ["start", TILE_START, false, true, { ...IMG, blurred: true, pressed: false }],
    ["revealed keeps one label, pressed carries it", { revealed: true, phase: "first" }, false, true, { ...IMG, blurred: false, pressed: true }],
    ["waiting hides the broken image", { revealed: false, phase: "waiting" }, false, true, { ...IMG, blurred: true, pressed: false, hidden: true }],
    ["the retry is a fresh image", { revealed: false, phase: "retry" }, false, true, { ...IMG, blurred: true, pressed: false, attempt: 1 }],
    ["failed", { revealed: false, phase: "failed" }, false, true, { image: false, failed: true }],
  ])("%s", (_label, state, sfw, thumb, want) => {
    expect(tileView(state, sfw, thumb)).toEqual(want);
  });

  it("the label says the image may be unrelated", () => {
    expect(PREVIEW_LABEL).toBe("Google preview · image may be unrelated");
  });
});
