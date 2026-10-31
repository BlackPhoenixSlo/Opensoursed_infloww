import { describe, expect, it } from "vitest";

import { pageItems } from "@/components/ui/ifPager";

describe("pageItems", () => {
  it.each<[string, number, number, (number | "…")[]]>([
    ["1 page", 1, 1, [1]],
    ["≤7 pages: every page", 4, 7, [1, 2, 3, 4, 5, 6, 7]],
    ["8 pages, early: one fold", 4, 8, [1, 2, 3, 4, 5, 6, "…", 8]],
    ["first of 20", 1, 20, [1, 2, 3, 4, 5, 6, "…", 20]],
    ["middle of 20", 10, 20, [1, "…", 8, 9, 10, 11, 12, "…", 20]],
    ["last of 20", 20, 20, [1, "…", 15, 16, 17, 18, 19, 20]],
  ])("%s", (_, page, pages, items) => {
    expect(pageItems(page, pages)).toEqual(items);
  });
});
