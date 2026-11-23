import { describe, expect, it } from "vitest";

import type { FreshnessValues } from "@/lib/creatorFreshness";
import { circleTitle, redCircle, shownUnread, type RedCircle } from "./redCircle";

const NONE: RedCircle = { kind: "none" };
const count = (text: string, n: number): RedCircle => ({ kind: "count", text, n });
const grey = (reason: string): RedCircle => ({ kind: "grey", reason });
const slot = (n: number | null, g: string | null = null) => ({ n, at: 1, v: 1, grey: g });

describe("redCircle", () => {
  it.each<[string, FreshnessValues["unread_total"], boolean, number | undefined, boolean, RedCircle]>([
    ["0: no circle", slot(0), true, 5, true, NONE],
    ["1", slot(1), true, 5, true, count("1", 1)],
    ["8", slot(8), true, 5, true, count("8", 8)],
    ["9: 9+", slot(9), true, 5, true, count("9+", 9)],
    ["35: 9+", slot(35), true, 5, true, count("9+", 35)],
    ["negative: no circle", slot(-2), true, 5, true, NONE],
    ["n null: grey", slot(null), true, 5, true, grey("unknown")],
    ["unseeded, whatever n", slot(4, "unseeded"), true, 5, true, grey("unseeded")],
    ["socket_down, whatever n", slot(4, "socket_down"), true, 5, true, grey("socket_down")],
    ["r_unknown, whatever n", slot(null, "r_unknown"), true, 5, true, grey("r_unknown")],
    ["a later Phase's reason", slot(0, "stale"), true, 5, true, grey("stale")],
    ["relay unreachable beats a slot", slot(3), false, 5, true, grey("relay_unreachable")],
    ["the slot, not the route", { n: 3, at: null }, true, 12, true, count("3", 3)],
    ["null (non-OF): the route", null, true, 12, true, count("9+", 12)],
    ["null, unsettled: grey", null, true, 12, false, grey("relay_unreachable")],
    ["Knob off settled: the route, new rule", undefined, true, 12, true, count("9+", 12)],
    ["Knob off settled, 0", undefined, true, 0, true, NONE],
    ["Knob off settled, no route row", undefined, true, undefined, true, NONE],
    ["Knob off unsettled: grey", undefined, true, 3, false, grey("relay_unreachable")],
    ["Knob off, relay unreachable", undefined, false, 3, true, grey("relay_unreachable")],
  ])("%s", (_name, s, reachable, route, settled, want) => {
    expect(redCircle(s, reachable, route, settled)).toEqual(want);
  });

  it("title and the sort's number", () => {
    expect([NONE, count("3", 3), count("9+", 35), grey("unseeded")].map(circleTitle))
      .toEqual(["0 unread", "3 unread", "9+ unread", "unread count unknown"]);
    expect([NONE, count("3", 3), count("9+", 35), grey("unseeded")].map(shownUnread)).toEqual([0, 3, 35, 0]);
  });
});
