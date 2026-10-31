import { describe, expect, it } from "vitest";

import { placeEmojiPopover } from "./emojiPopover";

/** A 32x32 trigger at (x, y). */
const btn = (x: number, y: number) => ({ left: x, top: y, right: x + 32, bottom: y + 32 });
const VP = { width: 1200, height: 900 };

describe("placeEmojiPopover", () => {
  it.each<[string, ReturnType<typeof btn>, { width: number; height: number }, "left" | "right", object]>([
    // below = 900-132-8 = 760 >= 400
    ["room below opens down", btn(1000, 100), VP, "right", { top: 140, maxHeight: 400, right: 168 }],
    // below = 900-832-8 = 60, above = 792
    ["room only above opens up", btn(1000, 800), VP, "right", { bottom: 108, maxHeight: 400, right: 168 }],
    // h 500: trigger at 300 -> above 292, below 160 -> up, capped to 292
    ["neither fits, above bigger", btn(1000, 300), { width: 1200, height: 500 }, "right", { bottom: 208, maxHeight: 292, right: 168 }],
    // trigger at 150 -> above 142, below 310 -> down, capped to 310
    ["neither fits, below bigger", btn(1000, 150), { width: 1200, height: 500 }, "right", { top: 190, maxHeight: 310, right: 168 }],
    // wantRight 1200-42=1158 > maxRight 1200-384-8=808
    ["right-aligned near the left edge clamps", btn(10, 100), VP, "right", { top: 140, maxHeight: 400, right: 808 }],
    // wantLeft 1150 > maxLeft 808
    ["left-aligned near the right edge clamps", btn(1150, 100), VP, "left", { top: 140, maxHeight: 400, left: 808 }],
    ["left-aligned with room keeps the trigger's left", btn(200, 100), VP, "left", { top: 140, maxHeight: 400, left: 200 }],
    // 320 wide: maxRight 320-392 < 8 -> margin; h 200 trigger at 100: above 92, below 60 -> up
    ["tiny viewport clamps to the margin", btn(200, 100), { width: 320, height: 200 }, "right", { bottom: 108, maxHeight: 92, right: 8 }],
    ["tiny viewport, left align", btn(200, 100), { width: 320, height: 200 }, "left", { bottom: 108, maxHeight: 92, left: 8 }],
  ])("%s", (_, rect, vp, align, want) => {
    expect(placeEmojiPopover(rect, vp, align)).toEqual(want);
  });
});
