import { describe, expect, it } from "vitest";

import {
  buildPatch, canSave, fieldsFromAi, initialEditorState, isDirty, jevPatch, parsePriceCents, vaultItemEditorReducer,
  type EditorAction, type EditorFields, type EditorState,
} from "./vaultItemEditorReducer";
import { aiValue, picksFromAi, unsetLabel, type JevKey } from "./jevPicks";

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
const pick = (key: JevKey, value: string | null): EditorAction => ({ type: "pick", key, value });
/** Re-describe: the item's `_ai` comes back with new text. */
const redescribed = fieldsFromAi({ ...AI, description: "new desc", tags: ["x", "y"] });

describe("fieldsFromAi", () => {
  it("reads the `_ai` projection into input strings", () => {
    expect(F).toEqual({
      desc: "old desc", tags: "a, b", tier: "suggestive", cap: "", script: "", price: "12.50",
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
    ["a Jev pick", [pick("crotch", "bare")], { jev: { crotch: "bare" } }],
    ["a pick then back to the AI", [pick("lane", "$50"), pick("lane", null)], {}],
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

describe("Jev picks", () => {
  const stored = initialEditorState(F, { lane: "$50", watermark: "y" });

  it.each<[string, EditorAction[], Record<string, unknown>]>([
    ["nothing changed", [], {}],
    ["a new pick", [pick("outfit", "nude")], { jev: { outfit: "nude" } }],
    ["a stored pick changed", [pick("lane", "$100")], { jev: { lane: "$100" } }],
    ["a stored pick cleared → null", [pick("watermark", null)], { jev: { watermark: null } }],
    ["picked back to what is stored", [pick("lane", "free"), pick("lane", "$50")], {}],
    ["with a field", [edit("desc", "mine"), pick("toy", "no_toy")], { description: "mine", jev: { toy: "no_toy" } }],
  ])("%s", (_n, actions, patch) => {
    const s = run(actions, stored);
    expect(buildPatch(s)).toEqual(patch);
    expect(isDirty(s)).toBe(Object.keys(patch).length > 0);
  });

  it("save moves the stored picks; the server's merge is then a no-op; picks lock nothing", () => {
    let s = run([pick("lane", "$100"), pick("watermark", null), { type: "saveStart" }], stored);
    expect(s.pendingJev).toEqual({ lane: "$100", watermark: null });
    s = run([{ type: "saveOk", locked: [] }], s);
    expect(s.jevBase).toEqual({ lane: "$100" });
    expect(s.saved).toEqual(["jev"]);
    expect(isDirty(s)).toBe(false);
    expect(vaultItemEditorReducer(s, { type: "refresh", fields: F, picks: { lane: "$100" } })).toBe(s);
  });

  it("refresh: an untouched pick follows the item, a changed one keeps the change", () => {
    const s = run([pick("lane", "free"), { type: "refresh", fields: F, picks: { lane: "$10", toy: "no_toy" } }], stored);
    expect(s.jev).toEqual({ lane: "free", toy: "no_toy" });
    expect(s.jevBase).toEqual({ lane: "$50", toy: "no_toy" });
    expect(jevPatch(s)).toEqual({ lane: "free" });
  });

  it("saveFail keeps the picks to retry", () => {
    const s = run([pick("lane", "$10"), { type: "saveStart" }, { type: "saveFail", msg: "400" }], stored);
    expect(s.pendingJev).toBeNull();
    expect(buildPatch(s)).toEqual({ jev: { lane: "$10" } });
  });

  it("picksFromAi keeps known keys and options only", () => {
    expect(picksFromAi({ jev_picks: { lane: "$10", breasts: "covered", nope: "y", watermark: "n" } }))
      .toEqual({ lane: "$10", watermark: "n" });
    expect(picksFromAi({})).toEqual({});
  });

  it.each<[string, unknown, JevKey, string | null, string]>([
    ["the reading", { lane5: "$50", state: { butt: "bare" } }, "butt", "bare", "AI: bare"],
    ["the lane", { lane5: "$50" }, "lane", "$50", "auto: $50"],
    ["a tag y/n", { tags: { watermark: "n" } }, "watermark", "n", "AI: no"],
    ["a picked key: the AI's own answer", { lane5: "$100", op: ["lane"], ai: { lane: "free" } }, "lane", "free",
      "auto: free"],
    ["a manual blob reads nothing", { made: "manual", lane5: "$10" }, "lane", null, "auto"],
    ["feet with nothing read", null, "wears_socks", null, "None"],
    ["no blob", undefined, "outfit", null, "—"],
  ])("aiValue / unsetLabel: %s", (_n, jev, key, ai, label) => {
    expect(aiValue(jev, key)).toBe(ai);
    expect(unsetLabel(key, ai)).toBe(label);
  });
});
