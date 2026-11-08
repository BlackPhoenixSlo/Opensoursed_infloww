import { describe, expect, it } from "vitest";

import {
  BATCH_EDIT_INIT, batchAll, batchEditReducer, batchShown, buildBatchPayload, type BatchEditAction,
} from "./batchEditState";
import { type RowMeta } from "./VaultImportDetails";

const run = (acts: BatchEditAction[]) => acts.reduce(batchEditReducer, BATCH_EDIT_INIT);

describe("batchEditReducer", () => {
  it.each<[string, BatchEditAction[], boolean, string[], RowMeta]>([
    // name, actions, All on, shown keys, Save payload
    ["opens on Hashtags + Notes", [], false, ["hashtags", "notes"], { hashtags: "", notes: "" }],
    ["typed values go out, untouched shown fields as \"\"", [{ type: "set", key: "notes", value: "beach" }], false,
      ["hashtags", "notes"], { hashtags: "", notes: "beach" }],
    ["tick Price: it shows and goes out", [{ type: "toggle", key: "price" }], false,
      ["hashtags", "notes", "price"], { hashtags: "", notes: "", price: "" }],
    ["untick Notes: a value typed there is not written", [{ type: "set", key: "notes", value: "x" }, { type: "toggle", key: "notes" }],
      false, ["hashtags"], { hashtags: "" }],
    ["All: every field", [{ type: "all" }], true, ["tag", "category", "hashtags", "notes", "price"],
      { tag: "", category: "", hashtags: "", notes: "", price: "" }],
    ["ticking every one is All", [{ type: "toggle", key: "tag" }, { type: "toggle", key: "category" }, { type: "toggle", key: "price" }],
      true, ["tag", "category", "hashtags", "notes", "price"], { tag: "", category: "", hashtags: "", notes: "", price: "" }],
    ["from All, a tick narrows to it", [{ type: "all" }, { type: "toggle", key: "category" }, { type: "set", key: "category", value: "7" }],
      false, ["category"], { category: "7" }],
  ])("%s", (_n, acts, all, shown, payload) => {
    const s = run(acts);
    expect(batchAll(s)).toBe(all);
    expect(batchShown(s).map((c) => c.key)).toEqual(shown);
    expect(buildBatchPayload(s)).toEqual(payload);
  });

  it("returns the same object on a no-op", () => {
    const s = run([{ type: "all" }]);
    expect(batchEditReducer(s, { type: "all" })).toBe(s);
    const v = run([{ type: "set", key: "notes", value: "a" }]);
    expect(batchEditReducer(v, { type: "set", key: "notes", value: "a" })).toBe(v);
  });
});
