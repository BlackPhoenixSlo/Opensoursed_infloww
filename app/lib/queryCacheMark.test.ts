import { describe, expect, it } from "vitest";
import { cacheMovedSince, type CacheMark } from "./queryCacheMark";

const data = { pages: [] };
const at = (dataUpdatedAt: number, d: unknown = data): CacheMark => ({ data: d, dataUpdatedAt });

describe("cacheMovedSince", () => {
  it.each<[string, CacheMark, CacheMark, boolean]>([
    ["untouched", at(5), at(5), false],
    ["no entry then or now", undefined, undefined, false],
    ["re-written later", at(5), at(9), true],
    ["re-written in the same ms (new data object)", at(5), at(5, { pages: [] }), true],
    ["dropped meanwhile", at(5), undefined, true],
    ["created meanwhile", undefined, at(5), true],
  ])("%s", (_name, before, now, moved) => {
    expect(cacheMovedSince(before, now)).toBe(moved);
  });
});
