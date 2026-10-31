import { describe, expect, it } from "vitest";

import { INITIAL_GIFS, PAGE_SIZE, gifReducer, hasMoreAfter, type GifState } from "@/components/chat/gifPickerState";
import type { GiphyItem, GiphyResponse } from "@/lib/relay";

const gif = (id: string) => ({ id, images: {} }) as unknown as GiphyItem;
const page = (n: number, from = 0, total = 100): GiphyResponse => ({
  data: Array.from({ length: n }, (_, i) => gif(`g${from + i}`)),
  pagination: { total_count: total, offset: from },
});
const SHOWN: GifState = { items: [gif("a"), gif("b")], loading: true, error: null, hasMore: true };

describe("hasMoreAfter", () => {
  it.each<[string, GiphyResponse, number, boolean]>([
    ["a full page with more left", page(PAGE_SIZE), 0, true],
    ["a short page", page(5), 0, false],
    ["a full last page", page(PAGE_SIZE, 76, 100), 76, false],
    ["no pagination", { data: page(PAGE_SIZE).data }, 0, false],
  ])("%s → %s", (_, resp, offset, want) => {
    expect(hasMoreAfter(resp, offset)).toBe(want);
  });
});

describe("gifReducer", () => {
  it.each<[string, GifState, Parameters<typeof gifReducer>[1], Partial<GifState> & { ids?: string[] }]>([
    ["start loads and clears the error", { ...INITIAL_GIFS, error: "x" }, { type: "start" },
      { loading: true, error: null }],
    ["a first page replaces the grid", SHOWN, { type: "loaded", resp: page(3), offset: 0 },
      { ids: ["g0", "g1", "g2"], loading: false, hasMore: false }],
    ["a first page reads hasMore at the answer's offset", SHOWN, { type: "loaded", resp: page(PAGE_SIZE, 76, 100), offset: 0 },
      { loading: false, hasMore: false }],
    ["a more page appends", SHOWN, { type: "loaded", resp: page(PAGE_SIZE, 2), offset: 2 },
      { loading: false, hasMore: true }],
    ["a more page reads hasMore at the answer's offset, not the one asked for", SHOWN,
      { type: "loaded", resp: page(PAGE_SIZE, 76, 100), offset: 2 }, { loading: false, hasMore: false }],
    ["no offset in the answer reads the one asked for", SHOWN,
      { type: "loaded", resp: { data: page(PAGE_SIZE).data, pagination: { total_count: 100 } }, offset: 76 },
      { loading: false, hasMore: false }],
    ["a first-page error empties the grid", SHOWN, { type: "failed", message: "boom", offset: 0 },
      { ids: [], loading: false, error: "boom", hasMore: false }],
    ["a more error keeps what is shown", SHOWN, { type: "failed", message: "boom", offset: 2 },
      { ids: ["a", "b"], loading: false, error: "boom", hasMore: true }],
  ])("%s", (_, s0, action, { ids, ...want }) => {
    const s = gifReducer(s0, action);
    expect(s).toMatchObject(want);
    if (ids) expect(s.items.map((g) => g.id)).toEqual(ids);
  });

  it("a more page keeps the shown items first", () => {
    const s = gifReducer(SHOWN, { type: "loaded", resp: page(2, 2), offset: 2 });
    expect(s.items.map((g) => g.id)).toEqual(["a", "b", "g2", "g3"]);
  });
});
