import { describe, expect, it } from "vitest";

import { type VaultMedia } from "@/lib/relay";
import { buildPicked, pickedInit, pickedReducer, type Picked, type PickedAction } from "./vaultPickerPicked";

const m = (id: number, type: VaultMedia["type"] = "video", tag = ""): VaultMedia => ({ id, type, ...(tag ? { _thumb: tag } : {}) });
const run = (acts: PickedAction[], s: Picked = pickedInit([])) => acts.reduce(pickedReducer, s);
const view = (s: Picked) => ({ ids: [...s.ids], meta: [...s.meta.keys()] });

describe("pickedReducer", () => {
  it.each<[string, number[], PickedAction[], { ids: number[]; meta: number[] }]>([
    ["open: the Composer's ids, no media", [3, 4], [], { ids: [3, 4], meta: [] }],
    ["toggle picks", [], [{ type: "toggle", media: m(1) }], { ids: [1], meta: [1] }],
    ["toggle again unpicks; the media stays seen", [], [{ type: "toggle", media: m(1) }, { type: "toggle", media: m(1) }], { ids: [], meta: [1] }],
    ["toggle a pre-attached id unpicks it", [3], [{ type: "toggle", media: m(3) }], { ids: [], meta: [3] }],
    ["addMany adds, never removes", [1], [{ type: "addMany", media: [m(1), m(2)] }], { ids: [1, 2], meta: [1, 2] }],
    ["reset (reopen) drops picks and media", [], [{ type: "toggle", media: m(1) }, { type: "reset", ids: [9] }], { ids: [9], meta: [] }],
  ])("%s", (_n, init, acts, want) => {
    expect(view(run(acts, pickedInit(init)))).toEqual(want);
  });

  it("addMany of nothing is a no-op (same object)", () => {
    const s = pickedInit([1]);
    expect(pickedReducer(s, { type: "addMany", media: [] })).toBe(s);
  });
});

describe("buildPicked", () => {
  const listed = m(2, "video", "list");
  const seen = m(5, "gif", "seen");
  it.each<[string, PickedAction[], VaultMedia[], VaultMedia | undefined, VaultMedia[]]>([
    ["nothing picked", [], [listed], undefined, []],
    ["from the loaded list", [{ type: "toggle", media: m(2) }], [listed], undefined, [listed]],
    ["picked under another filter: the media seen then", [{ type: "toggle", media: seen }], [listed], undefined, [seen]],
    ["the loaded list wins over the seen copy", [{ type: "toggle", media: m(2, "video", "old") }], [listed], undefined, [listed]],
    ["a pre-attached id never loaded: a photo stub", [{ type: "reset", ids: [7] }], [], undefined, [{ id: 7, type: "photo" } as VaultMedia]],
    ["dblclick extra: in even when its two clicks unpicked it", [{ type: "toggle", media: m(2) }, { type: "toggle", media: m(2) }], [listed], m(2, "video", "x"), [m(2, "video", "x")]],
    ["extra joins the others, after them", [{ type: "toggle", media: seen }], [listed], listed, [seen, listed]],
  ])("%s", (_n, acts, items, extra, want) => {
    expect(buildPicked(run(acts), items, extra)).toEqual(want);
  });
});
