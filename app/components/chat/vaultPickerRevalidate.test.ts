import { describe, expect, it } from "vitest";

import {
  mediaReady, revalidateDue, revalidateInit, revalidateReducer,
  type MediaPaint, type RevalidateAction, type RevalidateState, type RevalidateTarget,
} from "./vaultPickerRevalidate";

const run = (acts: RevalidateAction[], s: RevalidateState = revalidateInit) => acts.reduce(revalidateReducer, s);
const sent = (target: RevalidateTarget): RevalidateAction => ({ type: "sent", target });

describe("revalidateReducer", () => {
  it.each<[string, RevalidateAction[], RevalidateState]>([
    ["never opened: nothing due", [], { lists: "idle", media: "idle" }],
    ["open arms both", [{ type: "open" }], { lists: "armed", media: "armed" }],
    ["each read sent on its own", [{ type: "open" }, sent("lists")], { lists: "idle", media: "armed" }],
    ["both sent: none due", [{ type: "open" }, sent("media"), sent("lists")], { lists: "idle", media: "idle" }],
    ["a reopen arms both again", [{ type: "open" }, sent("media"), sent("lists"), { type: "open" }],
      { lists: "armed", media: "armed" }],
  ])("%s", (_n, acts, want) => {
    expect(run(acts)).toEqual(want);
  });

  it("a second sent is a no-op (same object)", () => {
    const s = run([{ type: "open" }, sent("lists")]);
    expect(revalidateReducer(s, sent("lists"))).toBe(s);
  });
});

const live: MediaPaint = { source: "live", sourceSettled: true, folderSettled: true, painted: true };

describe("mediaReady", () => {
  it.each<[string, Partial<MediaPaint>, boolean]>([
    ["the live grid painted", {}, true],
    ["the mirror's grid: never (it reads the mirror)", { source: "mirror" }, false],
    ["the mirror summary still out: the source may still flip", { sourceSettled: false }, false],
    ["a restricted chatter's folder gate still out", { folderSettled: false }, false],
    ["the first page not on screen yet", { painted: false }, false],
  ])("%s", (_n, p, want) => {
    expect(mediaReady({ ...live, ...p })).toBe(want);
  });
});

describe("revalidateDue", () => {
  const armed = run([{ type: "open" }]);
  it.each<[string, RevalidateState, Record<RevalidateTarget, boolean>, RevalidateTarget[]]>([
    ["armed and painted: both", armed, { lists: true, media: true }, ["lists", "media"]],
    ["only what has painted", armed, { lists: true, media: false }, ["lists"]],
    ["nothing painted yet", armed, { lists: false, media: false }, []],
    ["sent this open: never twice", run([{ type: "open" }, sent("lists"), sent("media")]),
      { lists: true, media: true }, []],
    ["never opened", revalidateInit, { lists: true, media: true }, []],
  ])("%s", (_n, s, ready, want) => {
    expect(revalidateDue(s, ready)).toEqual(want);
  });
});
