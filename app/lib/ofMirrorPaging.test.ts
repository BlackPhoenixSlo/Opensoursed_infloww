import { describe, expect, it } from "vitest";
import { nextFeedOffset, nextMarker, nextOffset, pageRows, POSTS_PAGE, rowsOf, uniqueRows } from "./ofMirrorPaging";

const rows = (n: number, from = 0) => Array.from({ length: n }, (_, i) => ({ id: from + i }));

describe("nextOffset", () => {
  it.each([
    ["last page short, hasMore false", { list: rows(3), hasMore: false }, [{ list: rows(10) }], undefined],
    ["hasMore missing", { list: rows(10) }, [{ list: rows(10) }], undefined],
    ["empty page, hasMore true", { list: [], hasMore: true }, [{ list: rows(10) }, { list: [] }], undefined],
    ["more: the rows read so far", { list: rows(10, 10), hasMore: true }, [{ list: rows(10) }, { list: rows(10, 10) }], 20],
    ["OF's nextOffset honoured", { list: rows(10), hasMore: true, nextOffset: 37 }, [{ list: rows(10) }], 37],
    ["non-numeric nextOffset: the rows read", { list: rows(4), hasMore: true, nextOffset: "9" }, [{ list: rows(4) }], 4],
    ["not OF's list", { hasMore: true }, [{ hasMore: true }], undefined],
    ["null page", null, [null], undefined],
  ])("%s", (_, last, pages, want) => expect(nextOffset(last, pages)).toBe(want));
});

describe("nextFeedOffset", () => {
  it.each([
    ["bare array, full page", rows(POSTS_PAGE), [rows(POSTS_PAGE)], POSTS_PAGE],
    ["bare array, two full pages", rows(POSTS_PAGE, 20), [rows(POSTS_PAGE), rows(POSTS_PAGE, 20)], 2 * POSTS_PAGE],
    ["bare array, short page", rows(POSTS_PAGE - 1), [rows(POSTS_PAGE - 1)], undefined],
    ["bare array, empty", [], [[]], undefined],
    ["OF's list: as nextOffset", { list: rows(5), hasMore: true, nextOffset: 25 }, [{ list: rows(5) }], 25],
    ["OF's list, no more", { list: rows(POSTS_PAGE), hasMore: false }, [{ list: rows(POSTS_PAGE) }], undefined],
  ])("%s", (_, last, pages, want) => expect(nextFeedOffset(last, pages)).toBe(want));
});

describe("nextMarker", () => {
  it.each([
    ["string marker", { list: rows(2), hasMore: true, tailMarker: "1700000000.5" }, null, "1700000000.5"],
    ["numeric marker stringified", { list: rows(2), hasMore: true, tailMarker: 1700000000 }, null, "1700000000"],
    ["marker null", { list: rows(2), hasMore: true, tailMarker: null }, null, undefined],
    ["marker empty", { list: rows(2), hasMore: true, tailMarker: "" }, null, undefined],
    ["same marker as lastParam", { list: rows(2), hasMore: true, tailMarker: 17 }, "17", undefined],
    ["moved marker", { list: rows(2), hasMore: true, tailMarker: 16 }, "17", "16"],
    ["hasMore false", { list: rows(2), hasMore: false, tailMarker: "1" }, null, undefined],
    ["no rows", { list: [], hasMore: true, tailMarker: "1" }, null, undefined],
    ["no page", undefined, null, undefined],
  ])("%s", (_, last, lastParam, want) => expect(nextMarker(last, [], lastParam)).toBe(want));
});

describe("uniqueRows", () => {
  it.each([
    ["duplicate ids across pages: the first kept", [{ id: 1, p: 1 }, { id: 2, p: 1 }, { id: 2, p: 2 }, { id: 3, p: 2 }], [{ id: 1, p: 1 }, { id: 2, p: 1 }, { id: 3, p: 2 }]],
    ["number and string id are one", [{ id: 1, p: 1 }, { id: "1", p: 2 }], [{ id: 1, p: 1 }]],
    ["id-less rows all stay", [{ p: 1 }, { id: null, p: 2 }, { p: 3 }, { id: 1, p: 4 }, { id: 1, p: 5 }], [{ p: 1 }, { id: null, p: 2 }, { p: 3 }, { id: 1, p: 4 }]],
    ["none", undefined, undefined],
  ])("%s", (_, input, want) => expect(uniqueRows(input as { id?: unknown }[] | undefined)).toEqual(want));
});

describe("pageRows / rowsOf", () => {
  it.each([
    ["no pages", undefined, undefined],
    ["empty pages", [], undefined],
    ["first page not a list", [{ error: "x" }, { list: rows(1) }], undefined],
    ["pages in order; a non-list later page adds none", [{ list: rows(2) }, { error: "x" }, rows(1, 5), { chats: rows(1, 9) }], [{ id: 0 }, { id: 1 }, { id: 5 }, { id: 9 }]],
  ])("pageRows: %s", (_, pages, want) => expect(pageRows(pages)).toEqual(want));

  it.each([
    ["bare array", [1], [1]],
    ["list", { list: [2] }, [2]],
    ["chats", { chats: [3] }, [3]],
    ["list over chats", { list: [4], chats: [5] }, [4]],
    ["neither", { items: [6] }, undefined],
    ["null", null, undefined],
  ])("rowsOf: %s", (_, r, want) => expect(rowsOf(r)).toEqual(want));
});
