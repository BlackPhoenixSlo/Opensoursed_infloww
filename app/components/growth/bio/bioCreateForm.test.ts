import { describe, expect, it } from "vitest";

import {
  INITIAL_CREATE, NAME_MSG, RESERVED_MSG, USERNAME_MSG, bioCreateReducer, buildCreatePayload, canSubmit,
  createFormError, isDirty, normalizeUsername, type Action, type BioCreateForm,
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
    const withCreator = run([{ type: "set", patch: { accountId: "1000001" } }], filled("alice"));
    expect(buildCreatePayload(withCreator)).toEqual({ username: "alice", display_name: "Alice", account_id: "1000001" });
  });
});
