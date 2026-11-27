import { describe, expect, it } from "vitest";

import {
  ALIAS_LANE_LABEL, aliasLane, BANNED_ALIASES, buildPayload, canSubmit, INITIAL_FORM, isTrimmed, leakIdentityFormReducer,
  TRIMMED_NOTE, validate,
  type Action, type LeakIdentityForm,
} from "./leakIdentityForm";
import type { LeakTrimmed } from "./leakCoverage";

const run = (actions: Action[], from: LeakIdentityForm = INITIAL_FORM) => actions.reduce(leakIdentityFormReducer, from);
const adopt = (over: Partial<Extract<Action, { type: "adopt" }>> = {}): Action =>
  ({ type: "adopt", tracked: false, username: "miavale", verified: true, display_name: "Mia Vale", ...over });
const edit = (field: "username" | "display_name" | "instagram" | "x", value: string): Action => ({ type: "edit", field, value });
const consent: Action = { type: "setConsent", value: true };
const valid = run([adopt(), consent]);

describe("leakIdentityFormReducer", () => {
  it("adopt fills the identity and resets consent and the error", () => {
    const s = run([adopt({ aliases: ["mia.vale.x"], instagram: "miavale", x: null }), consent,
      { type: "saveFailed", message: "boom" }, adopt({ tracked: true, username: "other", verified: false })]);
    expect(s).toEqual({ ...INITIAL_FORM, tracked: true, username: "other", verified: false, display_name: "Mia Vale" });
  });

  it.each<[string, Action[], Pick<LeakIdentityForm, "username" | "verified">]>([
    ["a verified handle stays verified while unchanged", [adopt()], { username: "miavale", verified: true }],
    ["clearing a verified handle makes it unverified", [adopt(), edit("username", "")], { username: "", verified: false }],
    ["typing another handle stays unverified", [adopt(), edit("username", ""), edit("username", "miavale")],
      { username: "miavale", verified: false }],
    ["an unverified suggestion stays unverified", [adopt({ username: "", verified: false }), edit("username", "mia")],
      { username: "mia", verified: false }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect({ username: s.username, verified: s.verified }).toEqual(want);
  });

  it("aliases add trimmed, skip blanks and remove by index", () => {
    const s = run([adopt(), { type: "addAlias", value: "  mia.v  " }, { type: "addAlias", value: "   " },
      { type: "addAlias", value: "vale.mia" }, { type: "removeAlias", index: 0 }]);
    expect(s.aliases).toEqual(["vale.mia"]);
  });

  it("an edit clears the save error", () => {
    const failed = run([adopt(), { type: "saveFailed", message: "Another Creator in this agency already uses that handle" }]);
    expect(failed.error).toBe("Another Creator in this agency already uses that handle");
    expect(leakIdentityFormReducer(failed, edit("display_name", "Mia")).error).toBeNull();
  });
});

describe("validate", () => {
  const six = ["alias1", "alias2", "alias3", "alias4", "alias5", "alias6"];
  it.each<[string, Action[], keyof ReturnType<typeof validate> | null]>([
    ["the adopted identity is valid", [], null],
    ["handle of 2", [edit("username", "mv")], null],
    ["handle of 64", [edit("username", "a".repeat(64))], null],
    ["handle with _ . -", [edit("username", "mia_vale.x-1")], null],
    ["handle empty", [edit("username", "")], "username"],
    ["handle of 1", [edit("username", "m")], "username"],
    ["handle of 65", [edit("username", "a".repeat(65))], "username"],
    ["handle with a space", [edit("username", "mia vale")], "username"],
    ["handle with @", [edit("username", "@miavale")], "username"],
    ["five aliases", ["alias1", "alias2", "alias3", "alias4", "alias5"].map((value) => ({ type: "addAlias", value }) as Action), null],
    ["six aliases", six.map((value) => ({ type: "addAlias", value }) as Action), "aliases"],
    ["alias of 4", [{ type: "addAlias", value: "mvx1" }], null],
    ["alias of 3", [{ type: "addAlias", value: "mvx" }], "aliases"],
    ["alias of 4 once _ . - are dropped", [{ type: "addAlias", value: "m.v_x-1" }], null],
    ["alias of 3 once _ . - are dropped", [{ type: "addAlias", value: "a.b-c" }], "aliases"],
    ["alias of 3 once %XX decodes", [{ type: "addAlias", value: "a%2Eb_c" }], "aliases"],
    ["alias of 4 with a bad %XX byte", [{ type: "addAlias", value: "abc%FF" }], null],
    ["alias of 3 with a bad %XX byte", [{ type: "addAlias", value: "ab%FF" }], "aliases"],
    ["alias equal to the handle once _ . - are dropped", [{ type: "addAlias", value: "mia.vale" }], "aliases"],
    ["alias twice once _ . - are dropped", [{ type: "addAlias", value: "mia.v" }, { type: "addAlias", value: "miav" }], "aliases"],
    ["alias of 65", [{ type: "addAlias", value: "a".repeat(65) }], "aliases"],
    ["alias on the blocked list", [{ type: "addAlias", value: "OnlyFans" }], "aliases"],
    ["alias twice, other case", [{ type: "addAlias", value: "mia.v" }, { type: "addAlias", value: "MIA.V" }], "aliases"],
    ["alias equal to the handle", [{ type: "addAlias", value: "MiaVale" }], "aliases"],
    ["instagram of 30 with _ .", [edit("instagram", "mia_vale." + "a".repeat(21))], null],
    ["instagram of 31", [edit("instagram", "a".repeat(31))], "instagram"],
    ["instagram with -", [edit("instagram", "mia-vale")], "instagram"],
    ["instagram empty is fine", [edit("instagram", "")], null],
    ["x of 15", [edit("x", "a".repeat(15))], null],
    ["x of 16", [edit("x", "a".repeat(16))], "x"],
    ["x with .", [edit("x", "mia.vale")], "x"],
    ["display name of 64", [edit("display_name", "a".repeat(64))], null],
    ["display name of 65", [edit("display_name", "a".repeat(65))], "display_name"],
  ])("%s", (_name, actions, field) => {
    const errors = validate(run(actions, valid));
    expect(Object.keys(errors)).toEqual(field ? [field] : []);
  });

  it("the blocked list is lowercase and holds the Platform names", () => {
    expect(BANNED_ALIASES).toContain("onlyfans");
    expect(BANNED_ALIASES).toContain("fansly");
    expect(BANNED_ALIASES.every((w) => w === w.toLowerCase())).toBe(true);
  });
});

describe("aliasLane", () => {
  it.each<[string, string, "alone" | "with_handle"]>([
    ["4 characters", "miav", "with_handle"],
    ["5 characters", "miava", "alone"],
    ["5 with _ . - counts 4", "mi.a_v", "with_handle"],
    ["upper case counts the same", "MIAVA", "alone"],
    ["%XX counts once decoded", "mia%2Ev", "with_handle"],
    ["a stray % counts as a character", "mia%v", "alone"],
    ["a bad %XX byte counts as one character", "abc%FF", "with_handle"],
    ["a leading byte-order mark counts as a character", "%EF%BB%BFabcd", "alone"],
    ["a mixed %XX run decodes like the service", "ab%C3%A9%FF", "with_handle"],
    ["a mixed %XX run of 5", "abc%C3%A9%FF", "alone"],
  ])("%s", (_name, alias, want) => {
    expect(aliasLane(alias)).toBe(want);
  });

  it("labels each lane", () => {
    expect(ALIAS_LANE_LABEL).toEqual({ alone: "Searched on its own", with_handle: "Only with the handle" });
  });
});

describe("canSubmit", () => {
  it.each<[string, Action[], boolean]>([
    ["create without consent", [adopt()], false],
    ["create with consent", [adopt(), consent], true],
    ["create with consent taken back", [adopt(), consent, { type: "setConsent", value: false }], false],
    ["update without consent", [adopt({ tracked: true })], true],
    ["create, consent, invalid handle", [adopt(), consent, edit("username", "m")], false],
    ["update, invalid alias", [adopt({ tracked: true }), { type: "addAlias", value: "leak" }], false],
  ])("%s", (_name, actions, want) => {
    expect(canSubmit(run(actions))).toBe(want);
  });
});

describe("buildPayload", () => {
  it("sends the trimmed identity, nulls for empty socials, and the consent", () => {
    const s = run([adopt(), edit("display_name", "  Mia Vale "), { type: "addAlias", value: "mia.vale.x" },
      edit("instagram", " miavale "), edit("x", ""), consent]);
    expect(buildPayload(s)).toEqual({
      username: "miavale", verified: true, display_name: "Mia Vale", aliases: ["mia.vale.x"],
      instagram: "miavale", x: null, consent: true,
    });
  });

  it("an unverified typed handle is sent as typed and unverified", () => {
    const s = run([adopt(), edit("username", ""), edit("username", " mia_v "), consent]);
    expect(buildPayload(s)).toMatchObject({ username: "mia_v", verified: false });
  });
});

describe("isTrimmed", () => {
  const TRIMMED = [{ field: "alias:1", value: "Mia V" }, { field: "instagram", value: "mia.vale" }];
  it.each<[string, "alias" | "instagram" | "x", string, LeakTrimmed[], boolean]>([
    ["a skipped alias", "alias", "Mia V", TRIMMED, true],
    ["a skipped alias in another case", "alias", " mia v ", TRIMMED, true],
    ["an alias that was searched", "alias", "miavale.x", TRIMMED, false],
    ["skipped Instagram", "instagram", "mia.vale", TRIMMED, true],
    ["Instagram edited since", "instagram", "mia.new", TRIMMED, false],
    ["an alias value under the Instagram field", "x", "mia.vale", TRIMMED, false],
    ["an empty field", "x", "", [{ field: "x", value: "" }], false],
    ["nothing trimmed", "alias", "Mia V", [], false],
  ])("%s", (_label, field, value, trimmed, want) => {
    expect(isTrimmed(trimmed, field, value)).toBe(want);
  });

  it("never says next full search", () => {
    expect(TRIMMED_NOTE.toLowerCase()).not.toContain("next full search");
  });
});
