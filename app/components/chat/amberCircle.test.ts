import { describe, expect, it } from "vitest";

import type { FreshnessValues } from "@/lib/creatorFreshness";
import { amberCircle, amberTitle, type AmberCircle } from "./amberCircle";

const NONE: AmberCircle = { kind: "none" };
const GREY: AmberCircle = { kind: "grey" };
const count = (text: string, n: number): AmberCircle => ({ kind: "count", text, n });
const slot = (amber: number | null) => ({ n: 2, at: 1, v: 1, grey: null, amber, amber_at: 1 });

describe("amberCircle", () => {
  it.each<[string, FreshnessValues["unread_total"], "none" | "count" | "grey", number | undefined, AmberCircle]>([
    ["null: grey", slot(null), "count", 5, GREY],
    ["0: none", slot(0), "count", 5, NONE],
    ["1", slot(1), "count", 5, count("1", 1)],
    ["8", slot(8), "count", 5, count("8", 8)],
    ["9: 9+", slot(9), "count", 5, count("9+", 9)],
    ["40: 9+", slot(40), "count", 5, count("9+", 40)],
    ["red known at 0: still drawn", slot(3), "none", 5, count("3", 3)],
    ["red grey: none (one grey circle)", slot(3), "grey", 5, NONE],
    ["red grey, amber null: none", slot(null), "grey", 5, NONE],
    ["key absent (Knob off): the route's owe_reply", { n: 2, at: 1, v: 1, grey: null }, "count", 5, count("5", 5)],
    ["no slot (Knob off): the route's", undefined, "count", 12, count("9+", 12)],
    ["null slot (non-OF): the route's", null, "count", 0, NONE],
    ["no slot, no route row: none", undefined, "none", undefined, NONE],
  ])("%s", (_name, s, redKind, routeOwe, want) => {
    expect(amberCircle(s, redKind, routeOwe)).toEqual(want);
  });

  it("title", () => {
    expect([NONE, count("3", 3), count("9+", 40), GREY].map(amberTitle))
      .toEqual([null, "3 awaiting reply", "9+ awaiting reply", "awaiting reply unknown"]);
  });
});
