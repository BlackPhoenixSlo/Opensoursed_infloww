import { describe, expect, it } from "vitest";

import {
  BAD_IMAGE, buildPayload, canSubmit, iconFormReducer, INITIAL_ICON_FORM, MAX_ICON_BYTES, TOO_BIG,
  type Action, type IconForm,
} from "./vaultCategoryIconForm";

const run = (actions: Action[], from: IconForm = INITIAL_ICON_FORM) => actions.reduce(iconFormReducer, from);
const img = (size = 1000) => ({ size, name: "a.png" }) as File;
const SMALL = img();
const BIG = img(MAX_ICON_BYTES + 1);
const choose = (file?: File): Action => ({ type: "choose", file, preview: file ? "blob:1" : "" });
const move = (axis: "x" | "y", value: number): Action => ({ type: "move", axis, value });

describe("iconFormReducer", () => {
  it.each<[string, Action[], Partial<IconForm>]>([
    ["choose: preview, crop centred, not ready", [choose(SMALL)],
      { file: SMALL, preview: "blob:1", x: 50, y: 50, ready: false, error: "" }],
    ["preview loads: ready", [choose(SMALL), { type: "loaded" }], { ready: true }],
    ["bad image: not ready, error", [choose(SMALL), { type: "loaded" }, { type: "loadFailed" }],
      { ready: false, error: BAD_IMAGE }],
    ["move sets one axis", [choose(SMALL), move("x", 20), move("y", 80)], { x: 20, y: 80 }],
    ["new file resets the crop and ready", [choose(SMALL), { type: "loaded" }, move("x", 20), choose(img(5))],
      { x: 50, y: 50, ready: false }],
    // Bug: the over-8 MB branch returned before the crop reset, keeping the previous file's x / y.
    ["over 8 MB: no file, no preview, crop reset, error", [choose(SMALL), { type: "loaded" }, move("x", 20), choose(BIG)],
      { file: undefined, preview: "", x: 50, y: 50, ready: false, error: TOO_BIG }],
    ["cleared input: nothing chosen", [choose(SMALL), choose()], { file: undefined, preview: "", error: "" }],
    ["submit: busy, error cleared", [choose(BIG), choose(SMALL), { type: "loaded" }, { type: "submit" }],
      { busy: true, error: "" }],
    ["failed: not busy, error kept", [choose(SMALL), { type: "submit" }, { type: "failed", error: "nope" }],
      { busy: false, error: "nope" }],
    ["done: not busy", [choose(SMALL), { type: "submit" }, { type: "done" }], { busy: false }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect(Object.fromEntries(Object.keys(want).map((k) => [k, s[k as keyof IconForm]]))).toEqual(want);
  });
});

describe("canSubmit", () => {
  const loaded = run([choose(SMALL), { type: "loaded" }]);
  it.each<[string, IconForm, boolean, boolean]>([
    ["nothing chosen", INITIAL_ICON_FORM, false, true],
    ["chosen, preview not loaded", run([choose(SMALL)]), false, true],
    ["loaded", loaded, true, true],
    ["bad image", iconFormReducer(loaded, { type: "loadFailed" }), false, true],
    ["saving", iconFormReducer(loaded, { type: "submit" }), false, false],
  ])("%s → save %s, use default %s", (_name, state, save, reset) => {
    expect(canSubmit(state)).toBe(save);
    expect(canSubmit(state, true)).toBe(reset);
  });
});

describe("buildPayload", () => {
  it("sends the file and the crop as fractions", () => {
    expect(buildPayload(run([choose(SMALL), move("x", 25), move("y", 100)]))).toEqual({ file: SMALL, x: 0.25, y: 1 });
  });
  it("none without a file", () => {
    expect(buildPayload(INITIAL_ICON_FORM)).toBeNull();
  });
});
