import { describe, expect, it } from "vitest";

import {
  buildPatch, canSave, fieldsFromAi, initialEditorState, isDirty, parsePriceCents, vaultItemEditorReducer,
  type EditorAction, type EditorFields, type EditorState,
} from "./vaultItemEditorReducer";

const AI = {
  description: "old desc",
  tags: ["a", "b"],
  explicitness_tier: "suggestive",
  suggested_price_cents: 1250,
  breasts_vis: "covered",
};
const F = fieldsFromAi(AI);
const run = (actions: EditorAction[], from: EditorState = initialEditorState(F)): EditorState =>
  actions.reduce(vaultItemEditorReducer, from);
const edit = (field: keyof EditorFields, value: string): EditorAction => ({ type: "edit", field, value });
/** Re-describe: the item's `_ai` comes back with new text. */
const redescribed = fieldsFromAi({ ...AI, description: "new desc", tags: ["x", "y"] });

describe("fieldsFromAi", () => {
  it("reads the `_ai` projection into input strings", () => {
    expect(F).toEqual({
      desc: "old desc", tags: "a, b", tier: "suggestive", cap: "", script: "", price: "12.50",
      breasts: "covered", vulva: "", anus: "",
    });
  });
  it("falls back to the video description, and blanks for an undescribed item", () => {
    expect(fieldsFromAi({ video_description: "vid" }).desc).toBe("vid");
    expect(Object.values(fieldsFromAi({})).every((v) => v === "")).toBe(true);
  });
});

describe("parsePriceCents", () => {
  it.each<[string, number | null | undefined]>([
    ["12.50", 1250],
    [" $9.99 ", 999],
    ["7", 700],
    ["", null],
    ["   ", null],
    // Bug: "abc" stripped to "" and Number("") is 0, so a typo in the price box
    // saved and locked a $0.00 price.
    ["abc", undefined],
    ["$", undefined],
    ["1.2.3", undefined],
  ])("%j → %j", (raw, cents) => {
    expect(parsePriceCents(raw)).toBe(cents);
  });
});

describe("buildPatch / isDirty", () => {
  it.each<[string, EditorAction[], Record<string, unknown>]>([
    ["nothing edited", [], {}],
    ["description", [edit("desc", "mine")], { description: "mine" }],
    ["tags", [edit("tags", "x")], { tags: "x" }],
    ["tier", [edit("tier", "explicit")], { explicitness_tier: "explicit" }],
    ["caption + script", [edit("cap", "c"), edit("script", "s")], { suggested_caption: "c", suggested_script: "s" }],
    ["a flag", [edit("vulva", "bare")], { vulva_vis: "bare" }],
    ["price in dollars → cents", [edit("price", "20")], { suggested_price_cents: 2000 }],
    ["blank price clears it", [edit("price", "")], { suggested_price_cents: null }],
    ["garbage price is not sent", [edit("price", "abc")], {}],
    ["price with stray spaces is unchanged", [edit("price", " 12.50 ")], {}],
    ["edit then revert", [edit("desc", "mine"), edit("desc", "old desc")], {}],
  ])("%s", (_name, actions, patch) => {
    const s = run(actions);
    expect(buildPatch(s)).toEqual(patch);
    expect(isDirty(s)).toBe(Object.keys(patch).length > 0);
    expect(canSave(s)).toBe(Object.keys(patch).length > 0);
  });
});

describe("refresh (the open item's `_ai` changed under the editor)", () => {
  it("untouched fields follow the item, and nothing reads as edited", () => {
    // Bug: the old editor recomputed its baseline from the prop each render
    // while the inputs kept the old text — Re-describe left "old desc" on
    // screen and turned Save on with the old values.
    const s = run([{ type: "refresh", fields: redescribed }]);
    expect(s.draft.desc).toBe("new desc");
    expect(s.draft.tags).toBe("x, y");
    expect(isDirty(s)).toBe(false);
    expect(buildPatch(s)).toEqual({});
  });

  it("an edited field keeps the edit AND its baseline; the patch sends only it", () => {
    const s = run([edit("desc", "mine"), { type: "refresh", fields: redescribed }]);
    expect(s.draft.desc).toBe("mine");
    expect(s.base.desc).toBe("old desc");
    expect(s.draft.tags).toBe("x, y");
    // The old editor sent { description: "mine", tags: "a, b" } here — locking
    // the stale tags over the fresh describe.
    expect(buildPatch(s)).toEqual({ description: "mine" });
  });

  it("the same values again is a no-op (same object)", () => {
    const s = run([edit("desc", "mine")]);
    expect(vaultItemEditorReducer(s, { type: "refresh", fields: F })).toBe(s);
  });
});

describe("save", () => {
  it("saveStart freezes what is sent; typing during the save stays dirty afterwards", () => {
    let s = run([edit("desc", "my d"), { type: "saveStart" }]);
    expect(s.pending).toEqual({ desc: "my d" });
    expect(canSave(s)).toBe(false);
    s = run([edit("desc", "my desc"), { type: "saveOk", locked: ["description"] }], s);
    expect(s.base.desc).toBe("my d");
    expect(buildPatch(s)).toEqual({ description: "my desc" });
    expect(s.saved).toEqual(["description"]);
    expect([...s.locked]).toEqual(["description"]);
  });

  it("after a save the server's merge shows its spelling, clean", () => {
    const s = run([
      edit("tags", "p,q"), edit("price", "20"),
      { type: "saveStart" },
      { type: "saveOk", locked: ["tags", "suggested_price_cents"] },
      { type: "refresh", fields: fieldsFromAi({ ...AI, tags: ["p", "q"], suggested_price_cents: 2000 }) },
    ]);
    expect(s.draft.tags).toBe("p, q");
    expect(s.draft.price).toBe("20.00");
    expect(isDirty(s)).toBe(false);
    expect(s.saved).toEqual(["tags", "suggested_price_cents"]);
  });

  it("a garbage price is not sent, and stays out of the saved list", () => {
    const s = run([edit("desc", "mine"), edit("price", "abc"), { type: "saveStart" }]);
    expect(s.pending).toEqual({ desc: "mine" });
  });

  it("saveFail keeps the edits and shows the error; saveStart clears it", () => {
    let s = run([edit("desc", "mine"), { type: "saveStart" }, { type: "saveFail", msg: "boom" }]);
    expect(s.err).toBe("boom");
    expect(s.pending).toBeNull();
    expect(buildPatch(s)).toEqual({ description: "mine" });
    s = run([{ type: "saveStart" }], s);
    expect(s.err).toBe("");
  });

  it.each<[string, EditorAction[]]>([
    ["clean", [{ type: "saveStart" }]],
    ["already saving", [edit("desc", "x"), { type: "saveStart" }, { type: "saveStart" }]],
  ])("saveStart is ignored when %s", (_n, actions) => {
    const before = run(actions.slice(0, -1));
    expect(vaultItemEditorReducer(before, actions[actions.length - 1])).toBe(before);
  });

  it("a stray saveOk with nothing in flight is ignored", () => {
    const s = run([]);
    expect(vaultItemEditorReducer(s, { type: "saveOk", locked: ["x"] })).toBe(s);
  });
});
