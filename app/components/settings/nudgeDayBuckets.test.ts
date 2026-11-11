import { describe, expect, it } from "vitest";

import { bucketHasContent, fallbackChain, inherited, setSlot, shownImageIds, type DayBucket } from "./nudgeDayBuckets";

const SLOTS = {
  default: { night: { text: ["d"], image: [1] }, evening: { text: ["de"], image: [] } },
  weekend: { night: { text: ["w"], image: [] } },
  saturday: { night: { text: [], image: [7] } },
};

describe("fallbackChain (mirrors nudge_online._pick_pool)", () => {
  it.each<[DayBucket, DayBucket[]]>([
    ["default", []], ["weekday", ["default"]], ["weekend", ["default"]],
    ["monday", ["weekday", "default"]], ["friday", ["weekday", "default"]],
    ["saturday", ["weekend", "default"]], ["sunday", ["weekend", "default"]],
  ])("%s → %j", (b, want) => expect(fallbackChain(b)).toEqual(want));
});

describe("inherited (per field, nearest bucket that has it)", () => {
  it.each<[DayBucket, string, unknown]>([
    ["saturday", "night", { text: { from: "weekend", lines: ["w"] }, image: { from: "default", ids: [1] } }],
    ["sunday", "night", { text: { from: "weekend", lines: ["w"] }, image: { from: "default", ids: [1] } }],
    ["monday", "evening", { text: { from: "default", lines: ["de"] }, image: null }],
    ["default", "night", { text: null, image: null }],
    ["friday", "morning_1", { text: null, image: null }],
  ])("%s %s", (b, k, want) => expect(inherited(SLOTS, b, k)).toEqual(want));
});

describe("setSlot", () => {
  it.each<[string, DayBucket, string, { text: string[]; image?: number[] }, unknown]>([
    ["sets a day slot", "friday", "night", { text: ["f"] }, { ...SLOTS, friday: { night: { text: ["f"] } } }],
    ["empty entry drops the slot and the emptied day", "saturday", "night", { text: [], image: [] },
      { default: SLOTS.default, weekend: SLOTS.weekend }],
    ["every day is kept even when emptied", "default", "evening", { text: [] },
      { ...SLOTS, default: { night: SLOTS.default.night } }],
    ["a blank line being typed keeps the slot", "monday", "night", { text: [""] },
      { ...SLOTS, monday: { night: { text: [""] } } }],
  ])("%s", (_n, b, k, e, want) => expect(setSlot(SLOTS, b, k, e)).toEqual(want));
});

describe("bucketHasContent / shownImageIds", () => {
  it.each<[DayBucket, boolean]>([["default", true], ["weekend", true], ["saturday", true], ["friday", false]])(
    "%s has content: %s", (b, want) => expect(bucketHasContent(SLOTS, b)).toBe(want));
  it("own + inherited image ids", () => {
    expect(shownImageIds(SLOTS, "sunday", ["night", "evening"]).sort()).toEqual([1]);
    expect(shownImageIds(SLOTS, "saturday", ["night"]).sort()).toEqual([7]);
  });
});
