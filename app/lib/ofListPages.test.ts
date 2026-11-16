import { describe, expect, it, vi } from "vitest";
import { OF_USER_LISTS, readAllListPages } from "./ofListPages";

const rows = (start: number, count: number) =>
  Array.from({ length: count }, (_, i) => ({ id: start + i, name: `List ${start + i}`, canAddUsers: true }));

describe("complete list pagination", () => {
  it.each([132, 2051])("loads all %i lists with no screen or page-count cap", async (count) => {
    const all = rows(0, count);
    const get = vi.fn(async (path: string) => {
      const offset = Number(new URL(path, "https://relay.test").searchParams.get("offset"));
      return { list: all.slice(offset, offset + 50), hasMore: offset + 50 < count };
    });
    expect(await readAllListPages(get, OF_USER_LISTS)).toEqual(all);
    expect(get).toHaveBeenCalledTimes(Math.ceil(count / 50));
    expect(get.mock.calls[0][0]).toBe(OF_USER_LISTS);
    expect(get.mock.calls.at(-1)![0]).toBe(`${OF_USER_LISTS}&offset=${Math.floor((count - 1) / 50) * 50}`);
  });

  it("advances by upstream rows when pages overlap, retaining each id once", async () => {
    const get = vi.fn()
      .mockResolvedValueOnce({ list: rows(0, 50), hasMore: true })
      .mockResolvedValueOnce({ list: rows(49, 50), hasMore: true })
      .mockResolvedValueOnce({ list: rows(99, 33), hasMore: false });
    expect(await readAllListPages(get, OF_USER_LISTS)).toEqual(rows(0, 132));
    expect(get.mock.calls.map(([path]) => path)).toEqual([
      OF_USER_LISTS, `${OF_USER_LISTS}&offset=50`, `${OF_USER_LISTS}&offset=100`,
    ]);
  });

  it("recognizes a bare array and an empty terminal page", async () => {
    expect(await readAllListPages(async () => rows(0, 50), OF_USER_LISTS)).toEqual(rows(0, 50));
    expect(await readAllListPages(async () => ({ list: [], hasMore: false }), OF_USER_LISTS)).toEqual([]);
  });

  it.each([{ stalled: [] }, { stalled: rows(0, 50) }])("rejects a stalled walk instead of silently returning the first page", async ({ stalled }) => {
    const get = vi.fn()
      .mockResolvedValueOnce({ list: rows(0, 50), hasMore: true })
      .mockResolvedValueOnce({ list: stalled, hasMore: true });
    await expect(readAllListPages(get, OF_USER_LISTS)).rejects.toThrow("Could not load every list");
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("propagates a later-page failure instead of caching a truncated success", async () => {
    const get = vi.fn()
      .mockResolvedValueOnce({ list: rows(0, 50), hasMore: true })
      .mockRejectedValueOnce(new Error("Relay unavailable"));
    await expect(readAllListPages(get, OF_USER_LISTS)).rejects.toThrow("Relay unavailable");
  });
});
