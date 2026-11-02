/**
 * lib/anchorPanel — popover placement. The legacy rows prove
 * the left-aligned output equals the inline math TagCreatorsPicker / TemplatePicker carried before the move.
 */
import { describe, expect, it } from "vitest";

import { anchorPanel, type PopoverCoords } from "@/lib/anchorPanel";

type Rect = { top: number; bottom: number; left: number; right: number };
const rect = (top: number, left: number, h = 32, w = 32): Rect => ({ top, bottom: top + h, left, right: left + w });
const VP = { width: 1280, height: 800 };
const PANEL = { width: 320, height: 384 };

/** TagCreatorsPicker's inline `update` body before the move, verbatim but for `window.inner*` → `vp`. */
function legacyTagPicker(r: Rect, vp: { width: number; height: number }) {
  const PANEL_W = 320;
  const PANEL_H_PREF = 384;
  const margin = 8;
  const wantLeft = r.left;
  const maxLeft = vp.width - PANEL_W - margin;
  const left = Math.max(margin, Math.min(wantLeft, maxLeft));
  const spaceAbove = r.top - margin;
  const spaceBelow = vp.height - r.bottom - margin;
  const openDown = spaceBelow >= PANEL_H_PREF || spaceBelow > spaceAbove;
  return openDown
    ? { top: r.bottom + 8, left, maxHeight: Math.min(PANEL_H_PREF, spaceBelow) }
    : { bottom: vp.height - r.top + 8, left, maxHeight: Math.min(PANEL_H_PREF, spaceAbove) };
}

describe("anchorPanel", () => {
  const rows: [string, Rect, { width: number; height: number }, "left" | "right", PopoverCoords][] = [
    ["fits below", rect(100, 200), VP, "left", { top: 140, left: 200, maxHeight: 384 }],
    ["flips up near the bottom", rect(700, 200), VP, "left", { bottom: 108, left: 200, maxHeight: 384 }],
    ["opens down when below has more room, though under pref", rect(300, 200), { width: 1280, height: 640 }, "left",
      { top: 340, left: 200, maxHeight: 300 }],
    ["clamps left at the margin", rect(100, -50), VP, "left", { top: 140, left: 8, maxHeight: 384 }],
    ["clamps the right edge", rect(100, 1250), VP, "left", { top: 140, left: 952, maxHeight: 384 }],
    ["align right", rect(100, 1000, 32, 100), VP, "right", { top: 140, right: 180, maxHeight: 384 }],
    ["align right clamps", rect(100, 0, 32, 40), VP, "right", { top: 140, right: 952, maxHeight: 384 }],
    ["tiny viewport", rect(80, 100), { width: 300, height: 200 }, "left", { top: 120, left: 8, maxHeight: 80 }],
  ];
  it.each(rows)("%s", (_name, r, vp, align, want) => {
    expect(anchorPanel(r, PANEL, vp, align)).toEqual(want);
  });

  it("defaults to left align and an 8px margin", () => {
    expect(anchorPanel(rect(100, 200), PANEL, VP)).toEqual({ top: 140, left: 200, maxHeight: 384 });
  });

  const legacyRows: [Rect, { width: number; height: number }][] = [
    ...rows.map(([, r, vp]) => [r, vp] as [Rect, { width: number; height: number }]),
    [rect(0, 0), VP], [rect(768, 1248), VP], [rect(400, 640), VP], [rect(384, 300), { width: 800, height: 800 }],
    [rect(10, 10), { width: 100, height: 50 }], [rect(392, 0), { width: 1024, height: 816 }],
  ];
  it.each(legacyRows)("left output equals the pickers' old inline math (%j in %j)", (r, vp) => {
    expect(anchorPanel(r, PANEL, vp)).toEqual(legacyTagPicker(r, vp));
  });
});
