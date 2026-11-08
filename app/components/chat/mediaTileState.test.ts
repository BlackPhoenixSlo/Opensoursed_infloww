import { describe, expect, it } from "vitest";

import {
  MEDIA_TILE_INIT, mediaTileLoadKey, mediaTileReducer, type MediaTileAction, type MediaTileState,
} from "./mediaTileState";

const run = (acts: MediaTileAction[], s: MediaTileState = MEDIA_TILE_INIT) => acts.reduce(mediaTileReducer, s);
const A = "/img?u=a&sig=1";
const B = "/img?u=a&sig=2";

describe("mediaTileReducer", () => {
  it.each<[string, MediaTileAction[], MediaTileState]>([
    ["initial: loading", [], { kind: "loading" }],
    ["loaded", [{ type: "loaded", url: "blob:1" }], { kind: "loaded", url: "blob:1" }],
    ["failed: remembers the url that failed", [{ type: "failed", at: A }], { kind: "failed", at: A }],
    ["failed, retried on a new url, loaded", [{ type: "failed", at: A }, { type: "loaded", url: "blob:1" }],
      { kind: "loaded", url: "blob:1" }],
    ["failed, retry failed too: the newer url", [{ type: "failed", at: A }, { type: "failed", at: B }],
      { kind: "failed", at: B }],
  ])("%s", (_n, acts, want) => expect(run(acts)).toEqual(want));

  it("returns the same object on a no-op (no re-render)", () => {
    const f = run([{ type: "failed", at: A }]);
    expect(mediaTileReducer(f, { type: "failed", at: A })).toBe(f);
    const l = run([{ type: "loaded", url: "blob:1" }]);
    expect(mediaTileReducer(l, { type: "loaded", url: "blob:1" })).toBe(l);
  });
});

describe("mediaTileLoadKey", () => {
  it.each<[string, MediaTileState, string, string]>([
    ["no url: nothing to load", MEDIA_TILE_INIT, "", ""],
    ["first load", MEDIA_TILE_INIT, A, "load"],
    ["loaded: a re-signed url is the same key (no reload)", { kind: "loaded", url: "blob:1" }, B, "load"],
    ["failed, still on the url that failed: nothing to load", { kind: "failed", at: A }, A, ""],
    ["failed, a new url came: its retry", { kind: "failed", at: A }, B, B],
  ])("%s", (_n, s, url, want) => expect(mediaTileLoadKey(s, url)).toBe(want));
});
