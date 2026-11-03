import { describe, expect, it } from "vitest";

import {
  effectiveFields, fanDrawerFormReducer, INITIAL_FORM, nickPatch, notesPatch, tagsPatch, type Action, type FanDrawerForm,
} from "./fanDrawerForm";

const run = (actions: Action[], from: FanDrawerForm = INITIAL_FORM) => actions.reduce(fanDrawerFormReducer, from);
const adopt = (nick: string, notes = "", tags = ""): Action => ({ type: "adopt", nick, notes, tags });
const edit = (field: "nick" | "notes" | "tags", value: string): Action => ({ type: "edit", field, value });

describe("fanDrawerFormReducer", () => {
  it.each<[string, Action[], Pick<FanDrawerForm, "nick" | "notes" | "tags">]>([
    ["clean adopt takes fresh", [adopt("Ann", "n1", "a, b"), adopt("Bea", "n2", "c")], { nick: "Bea", notes: "n2", tags: "c" }],
    ["dirty adopt keeps typing", [adopt("Ann", "n1", "a"), edit("nick", "Typed"), edit("notes", "mine"), adopt("Bea", "n2", "b")],
      { nick: "Typed", notes: "mine", tags: "b" }],
    // Blur saved "Typed": the cache adopt brings it back as fresh, so a later out-of-band value wins again.
    ["adopt after blur-save", [adopt("Ann"), edit("nick", "Typed"), adopt("Typed"), adopt("Cy")], { nick: "Cy", notes: "", tags: "" }],
    // Chat-list "Old" first paints; the resolved OF read is empty and replaces it.
    ["empty OF value once resolved wins over chat-list value", [adopt("Old", "old note"), adopt("", "")], { nick: "", notes: "", tags: "" }],
    ["dirty field kept through several adopts", [adopt("Ann"), edit("nick", "T"), adopt("Bea"), adopt("Cy")], { nick: "T", notes: "", tags: "" }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect({ nick: s.nick, notes: s.notes, tags: s.tags }).toEqual(want);
  });

  it("applied always takes the fresh values, dirty or not", () => {
    const s = run([adopt("Ann", "n1", "a"), edit("nick", "Typed"), adopt("Bea", "n2", "b")]);
    expect(s.applied).toEqual({ nick: "Bea", notes: "n2", tags: "b" });
  });

  it("an adopt that changes nothing keeps the same state object", () => {
    const s = run([adopt("Ann", "n", "t")]);
    expect(fanDrawerFormReducer(s, adopt("Ann", "n", "t"))).toBe(s);
  });

  it.each<["nick" | "notes", string]>([
    ["nick", "Saved locally, but OnlyFans rejected the nickname change — it may revert on the next sync."],
    ["notes", "Saved locally, but OnlyFans rejected the note change — it may revert on the next sync."],
  ])("ofWriteFailed %s sets its error; clearError clears it", (field, text) => {
    const failed = run([{ type: "ofWriteFailed", field }]);
    expect(failed.ofWriteError).toBe(text);
    expect(fanDrawerFormReducer(failed, { type: "clearError" }).ofWriteError).toBeNull();
  });
});

describe("effectiveFields", () => {
  type Of = Parameters<typeof effectiveFields>[0];
  const resolved = (displayName: string | null, notice: string | null): Of => ({ isSuccess: true, data: { displayName, notice } });
  const pending: Of = { isSuccess: false, data: undefined };
  const chatUser = { displayName: "ChatName", notice: "chat note" };
  const mirror = { custom_nickname: "Mirror", notes: "mirror note" };

  it.each<[string, Of, typeof chatUser | object, typeof mirror | undefined, string, string]>([
    ["resolved OF value wins", resolved("OfName", "of note"), chatUser, mirror, "OfName", "of note"],
    ["resolved-empty OF beats chat-list value", resolved("", ""), chatUser, undefined, "", ""],
    ["resolved-null OF beats chat-list value", resolved(null, null), chatUser, undefined, "", ""],
    ["resolved-empty OF still falls back to local mirror", resolved("", ""), chatUser, mirror, "Mirror", "mirror note"],
    ["unresolved uses chat-list value", pending, chatUser, mirror, "ChatName", "chat note"],
    ["unresolved, no chat value: local mirror", pending, {}, mirror, "Mirror", "mirror note"],
    ["nothing anywhere: empty", pending, {}, undefined, "", ""],
  ])("%s", (_name, of, withUser, fan, nick, notes) => {
    expect(effectiveFields(of, withUser, fan)).toEqual({ effectiveNickname: nick, effectiveNotes: notes });
  });
});

describe("blur patches", () => {
  it.each<[string, unknown, unknown]>([
    ["nick unchanged → no patch", nickPatch("Ann", "Ann"), null],
    ["nick compares trimmed → no patch", nickPatch("  Ann ", "Ann "), null],
    ["nick changed → trimmed", nickPatch(" Bea ", "Ann"), { custom_nickname: "Bea" }],
    ["nick cleared → null", nickPatch("  ", "Ann"), { custom_nickname: null }],
    ["notes unchanged → no patch", notesPatch("n", "n"), null],
    ["notes compare untrimmed → patch", notesPatch("n ", "n"), { notes: "n " }],
    ["notes cleared → null", notesPatch("", "n"), { notes: null }],
    ["tags reorder → no patch", tagsPatch("b, a", ["a", "b"]), null],
    ["tags spaces/empties dropped → no patch", tagsPatch(" a ,, b ,", ["a", "b"]), null],
    ["tags changed → list", tagsPatch("a, c", ["a", "b"]), { tags: ["a", "c"] }],
    ["tags duplicate is not the same list", tagsPatch("a, a", ["a"]), { tags: ["a", "a"] }],
  ])("%s", (_name, got, want) => {
    expect(got).toEqual(want);
  });
});
