/**
 * readAllFanLists: every OnlyFans fan list through the relay proxy, which caps a page at 50. The first read is exactly
 * `?limit=50` (the cache other surfaces share asks the same), the next ones add `&offset=<rows so far>`, and the walk
 * stops on `hasMore:false`, an empty page, a page with no new id, a bare array, or after 40 pages.
 */
import { describe, expect, it, vi } from "vitest";

import { FAN_LISTS_MAX_PAGES, readAllFanLists, type FanList, type ListsResp } from "@/components/audience/fanLists";

const lists = (from: number, n: number): FanList[] =>
  Array.from({ length: n }, (_, i) => ({ id: 700000 + from + i, name: `List ${from + i}`, type: "custom" }));

describe("readAllFanLists", () => {
  it("reads a second page while OnlyFans says hasMore, at the offset of the rows so far", async () => {
    const get = vi.fn(async (path: string): Promise<ListsResp> =>
      path.endsWith("offset=50") ? { list: lists(50, 10), hasMore: false } : { list: lists(0, 50), hasMore: true });
    const out = await readAllFanLists(get);
    expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/of/v2/lists?limit=50", "/api/of/v2/lists?limit=50&offset=50"]);
    expect(out).toHaveLength(60);
    expect(out[59].name).toBe("List 59");
  });

  it("reads once when the first page has no more", async () => {
    const get = vi.fn(async (): Promise<ListsResp> => ({ list: lists(0, 3), hasMore: false }));
    expect(await readAllFanLists(get)).toHaveLength(3);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("takes a bare array as the whole answer", async () => {
    const get = vi.fn(async (): Promise<ListsResp> => lists(0, 50));
    expect(await readAllFanLists(get)).toHaveLength(50);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops when a page repeats the last one (an offset OnlyFans ignores), keeping each list once", async () => {
    const get = vi.fn(async (): Promise<ListsResp> => ({ list: lists(0, 50), hasMore: true }));
    const out = await readAllFanLists(get);
    expect(get).toHaveBeenCalledTimes(2);
    expect(out).toHaveLength(50);
  });

  it("stops on an empty page even when it says hasMore", async () => {
    const get = vi.fn(async (path: string): Promise<ListsResp> =>
      path.includes("offset") ? { list: [], hasMore: true } : { list: lists(0, 50), hasMore: true });
    expect(await readAllFanLists(get)).toHaveLength(50);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("keeps the lists already read when a later page fails", async () => {
    const get = vi.fn(async (path: string): Promise<ListsResp> => {
      if (path.includes("offset")) throw new Error("502 Bad Gateway");
      return { list: lists(0, 50), hasMore: true };
    });
    const out = await readAllFanLists(get);
    expect(out).toHaveLength(50);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("fails when the first page fails (nothing read)", async () => {
    const get = vi.fn(async (): Promise<ListsResp> => { throw new Error("502 Bad Gateway"); });
    await expect(readAllFanLists(get)).rejects.toThrow("502 Bad Gateway");
  });

  it("stops after 40 pages when OnlyFans always has more", async () => {
    let n = 0;
    const get = vi.fn(async (): Promise<ListsResp> => ({ list: lists(50 * n++, 50), hasMore: true }));
    const out = await readAllFanLists(get);
    expect(get).toHaveBeenCalledTimes(FAN_LISTS_MAX_PAGES);
    expect(out).toHaveLength(50 * FAN_LISTS_MAX_PAGES);
  });
});
