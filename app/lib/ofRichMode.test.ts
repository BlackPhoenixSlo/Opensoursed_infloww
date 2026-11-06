import { describe, expect, it } from "vitest";
import { PLAIN_MODE, richMode, type RichMode, type RichModeEvent } from "./ofRichMode";

const M = (toolbar: boolean, rich: boolean): RichMode => ({ toolbar, rich });

describe("richMode: the Aa state machine", () => {
  it.each<[string, RichMode, RichModeEvent, RichMode]>([
    ["Aa on: toolbar + rich editor", M(false, false), { type: "aa", formatted: false }, M(true, true)],
    ["Aa off, no formatting: textarea back", M(true, true), { type: "aa", formatted: false }, M(false, false)],
    ["Aa off, formatted: toolbar hides, editor + formatting stay (OF)", M(true, true), { type: "aa", formatted: true }, M(false, true)],
    ["formatted script loaded: rich editor, toolbar as it was", M(false, false), { type: "loaded", formatted: true }, M(false, true)],
    ["plain loaded, Aa off: textarea", M(false, true), { type: "loaded", formatted: false }, M(false, false)],
    ["plain loaded, Aa on: stays rich", M(true, true), { type: "loaded", formatted: false }, M(true, true)],
    ["edit dropping formatting: never swaps the box under the caret", M(false, true), { type: "edited", formatted: false }, M(false, true)],
    ["edit adding formatting in the textarea (paste): rich", M(false, false), { type: "edited", formatted: true }, M(false, true)],
    ["sent, Aa off: textarea back", M(false, true), { type: "sent" }, M(false, false)],
    ["sent, Aa on: stays rich", M(true, true), { type: "sent" }, M(true, true)],
  ])("%s", (_n, m, e, want) => expect(richMode(m, e)).toEqual(want));

  it.each<RichModeEvent>([
    { type: "aa", formatted: true }, { type: "loaded", formatted: true }, { type: "edited", formatted: true }, { type: "sent" },
  ])("not allowed (Fansly): always plain, no toolbar (%o)", (e) => {
    expect(richMode(M(true, true), e, false)).toBe(PLAIN_MODE);
    expect(richMode(PLAIN_MODE, e, false)).toBe(PLAIN_MODE);
  });

  it("no change returns the same object (React bails out)", () => {
    const m = M(true, true);
    expect(richMode(m, { type: "edited", formatted: false })).toBe(m);
  });
});
