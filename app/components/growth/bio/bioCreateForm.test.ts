import { describe, expect, it } from "vitest";

import {
  INITIAL_CREATE, NAME_MSG, RESERVED_MSG, USERNAME_MSG, bioCreateReducer, buildCreatePayload, canSubmit,
  createFormError, isDirty, normalizeUsername, suggestUsername, type Action, type BioCreateForm,
} from "@/components/growth/bio/bioCreateForm";

const run = (actions: Action[], from: BioCreateForm = INITIAL_CREATE) => actions.reduce(bioCreateReducer, from);
const filled = (username: string, displayName = "Alice") => run([{ type: "set", patch: { username, displayName } }]);

describe("normalizeUsername", () => {
  it.each([
    ["@Alice ", "alice"],
    ["  bob_1", "bob_1"],
    ["@@x", "@x"],
  ])("%j → %j", (raw, want) => expect(normalizeUsername(raw)).toBe(want));
});

describe("createFormError", () => {
  it.each([
    ["ab", USERNAME_MSG],
    ["a".repeat(31), USERNAME_MSG],
    ["a-b", USERNAME_MSG],
    ["api", RESERVED_MSG],
    ["edit", RESERVED_MSG],
    ["images", RESERVED_MSG],
    ["internal", RESERVED_MSG],
    ["@Netlify", RESERVED_MSG],
    ["abc", null],
    ["a".repeat(30), null],
  ])("username %j → %j", (username, msg) => {
    expect(createFormError(filled(username))?.msg ?? null).toBe(msg);
  });

  it.each([[""], ["   "]])("display name %j → refused", (name) => {
    expect(createFormError(filled("alice", name))).toEqual({ msg: NAME_MSG, fields: ["display_name"] });
  });
});

describe("bioCreateReducer", () => {
  it.each([
    ["clean", {}, false], ["username", { username: "a" }, true],
    ["name", { displayName: "A" }, true], ["Creator", { accountId: "1" }, true],
  ])("dirty: %s", (_name, patch, want) => expect(isDirty({ ...INITIAL_CREATE, ...patch })).toBe(want));
  it("submit with a refusal shows it and stays idle; an edit clears it", () => {
    const s = run([{ type: "set", patch: { username: "ab", displayName: "A" } }, { type: "submit" }]);
    expect(s.busy).toBe(false);
    expect(s.error?.fields).toEqual(["username"]);
    expect(run([{ type: "set", patch: { username: "abc" } }], s).error).toBeNull();
  });

  it("a valid submit goes busy and blocks a second one; failed shows the API's field", () => {
    const s = run([{ type: "set", patch: { username: "alice", displayName: "A" } }, { type: "submit" }]);
    expect(s.busy).toBe(true);
    expect(canSubmit(s)).toBe(false);
    expect(run([{ type: "submit" }], s)).toBe(s);
    const f = run([{ type: "failed", msg: "That username is taken.", fields: ["username"] }], s);
    expect(f).toMatchObject({ busy: false, error: { msg: "That username is taken.", fields: ["username"] } });
  });

  it("the body: normalized username, trimmed name, Creator only when picked", () => {
    expect(buildCreatePayload(filled("@Alice ", " Alice A "))).toEqual({ username: "alice", display_name: "Alice A" });
    const withCreator = run([{ type: "pick_creator", accountId: "1000001" }], filled("alice"));
    expect(buildCreatePayload(withCreator)).toEqual({ username: "alice", display_name: "Alice", account_id: "1000001" });
  });

  it("with a Creator a blank display name is the server's to fill", () => {
    const s = run([{ type: "pick_creator", accountId: "1" }], filled("alice", " "));
    expect(createFormError(s)).toBeNull();
    expect(buildCreatePayload(s)).toEqual({ username: "alice", display_name: "", account_id: "1" });
  });
});

describe("suggestUsername", () => {
  it.each<[string | null | undefined, string | null]>([
    ["Alice", "alice"],
    ["Alice.B-1", "aliceb1"],
    ["u12345678", "u12345678"],
    ["a".repeat(40), "a".repeat(30)],
    ["a.b", null],
    ["api", null],
    ["", null],
    [null, null],
    [undefined, null],
  ])("%j → %j", (raw, want) => expect(suggestUsername(raw)).toBe(want));
});

describe("creator prefill", () => {
  const me = (accountId = "1", name: string | null = "Alice A", username: string | null = "alice.a") =>
    ({ type: "creator_identity", accountId, name, username }) as const;
  const picked = (from: BioCreateForm = INITIAL_CREATE, accountId = "1") =>
    run([{ type: "pick_creator", accountId }], from);

  it.each<[string, BioCreateForm, Action[], { username: string; displayName: string }]>([
    ["blank fields fill", picked(), [me()], { username: "alicea", displayName: "Alice A" }],
    ["typed fields stay", picked(filled("mine", "Mine")), [me()], { username: "mine", displayName: "Mine" }],
    ["typed name stays, blank username fills", picked(filled("", "Mine")), [me()], { username: "alicea", displayName: "Mine" }],
    ["a late answer for another Creator is dropped", picked(), [me("2")], { username: "", displayName: "" }],
    ["no OF name or username leaves both", picked(), [me("1", null, null)], { username: "", displayName: "" }],
    ["an unusable OF username fills only the name", picked(), [me("1", "Bo", "b")], { username: "", displayName: "Bo" }],
    ["a long OF name is cut to the limit", picked(), [me("1", "x".repeat(150), null)], { username: "", displayName: "x".repeat(100) }],
    [
      "switching Creator replaces the prefill",
      picked(), [me(), { type: "pick_creator", accountId: "2" }, me("2", "Bob", "bob")],
      { username: "bob", displayName: "Bob" },
    ],
    [
      "an edit after the prefill sticks through a switch",
      picked(), [me(), { type: "set", patch: { displayName: "Mine" } }, { type: "pick_creator", accountId: "2" }, me("2", "Bob", "bob")],
      { username: "bob", displayName: "Mine" },
    ],
  ])("%s", (_n, from, actions, want) => {
    expect(run(actions, from)).toMatchObject(want);
  });

  it("a repeat answer with nothing to change keeps the state", () => {
    const s = run([me()], picked());
    expect(run([me()], s)).toBe(s);
  });

  it("a prefilled form submits", () => {
    const s = run([me(), { type: "submit" }], picked());
    expect(s.busy).toBe(true);
    expect(buildCreatePayload(s)).toEqual({ username: "alicea", display_name: "Alice A", account_id: "1" });
  });
});
