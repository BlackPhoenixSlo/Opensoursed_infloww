/** lifecycleForm's follow-up helpers: the delay check and the steps the Relay stores. */
import { describe, expect, it } from "vitest";

import { badDelay, cleanFollowUps } from "./lifecycleForm";

const WEEK = 7 * 24 * 60;

describe("badDelay", () => {
  it.each([
    // [text, delay, bad]
    ["", "", false], // a blank step is never flagged
    ["   ", "abc", false],
    ["hi", "", true], // Number("") = 0
    ["hi", "0", true],
    ["hi", "-5", true],
    ["hi", "abc", true],
    ["hi", "1.5", true],
    ["hi", "1", false],
    ["hi", " 5 ", false], // Number() trims
    ["hi", String(WEEK), false],
    ["hi", String(WEEK + 1), true],
    ["hi", "1e3", false], // as coded: Number("1e3") = 1000
  ])("text %j delay %j -> %s", (text, delay, bad) => {
    expect(badDelay({ text, delay })).toBe(bad);
  });
});

describe("cleanFollowUps", () => {
  it("empty -> []", () => {
    expect(cleanFollowUps([])).toEqual([]);
  });

  it("drops blank steps, trims text, keeps order", () => {
    expect(cleanFollowUps([
      { text: " first ", delay: "5" },
      { text: "", delay: "10" },
      { text: "  \n ", delay: "15" },
      { text: "second", delay: "60" },
      { text: "third\t", delay: "1" },
    ])).toEqual([
      { text: "first", delay_minutes: 5 },
      { text: "second", delay_minutes: 60 },
      { text: "third", delay_minutes: 1 },
    ]);
  });

  it("does not validate the delay (badDelay gates the save)", () => {
    expect(cleanFollowUps([{ text: "x", delay: "abc" }])).toEqual([{ text: "x", delay_minutes: Number.NaN }]);
  });
});
