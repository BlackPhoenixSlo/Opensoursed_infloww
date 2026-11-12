import { describe, expect, it } from "vitest";

import { moveLink } from "@/components/growth/bio/bioLinksOrder";

const IDS = ["a", "b", "c"];

describe("moveLink", () => {
  it.each<[string, string, -1 | 1, string[]]>([
    ["top ↑ unchanged", "a", -1, IDS],
    ["bottom ↓ unchanged", "c", 1, IDS],
    ["middle ↑ swaps", "b", -1, ["b", "a", "c"]],
    ["middle ↓ swaps", "b", 1, ["a", "c", "b"]],
    ["unknown id unchanged", "z", 1, IDS],
  ])("%s", (_n, id, dir, want) => {
    expect(moveLink(IDS, id, dir)).toEqual(want);
  });

  it("no move answers the same array (the caller skips the write)", () => {
    expect(moveLink(IDS, "a", -1)).toBe(IDS);
  });
});
