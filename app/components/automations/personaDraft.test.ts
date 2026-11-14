import { describe, expect, it } from "vitest";

import { buildPayload, dirty, hasPersona, initPersonaDraft, personaDraftReducer, type Action, type PersonaDraft } from "./personaDraft";

// _persona.MODEL_NOTES_TEMPLATE, as GET /admin/account-config serves it.
const TEMPLATE = "Name: \nAge: \nFrom: \nPersonality: \nLikes: \nWon't do (hard limits): ";

const run = (actions: Action[], from: PersonaDraft = initPersonaDraft("Name: Mia")) => actions.reduce(personaDraftReducer, from);

describe("personaDraftReducer", () => {
  it.each<[string, Action[], { text: string; dirty: boolean }]>([
    ["opens clean on the server text", [], { text: "Name: Mia", dirty: false }],
    ["edit changes text and makes dirty", [{ type: "edit", text: "Name: Kay" }], { text: "Name: Kay", dirty: true }],
    ["saved clears dirty", [{ type: "edit", text: "Name: Kay" }, { type: "saved", text: "Name: Kay" }], { text: "Name: Kay", dirty: false }],
    // Typing while the PUT is out: the reply marks only what was sent as saved.
    ["saved of an older text keeps a newer edit dirty",
      [{ type: "edit", text: "Name: Kay" }, { type: "edit", text: "Name: Kayla" }, { type: "saved", text: "Name: Kay" }],
      { text: "Name: Kayla", dirty: true }],
    ["edit back to the saved text is clean", [{ type: "edit", text: "Name: Kay" }, { type: "edit", text: "Name: Mia" }],
      { text: "Name: Mia", dirty: false }],
    ["serverText replaces text and saved text", [{ type: "edit", text: "Name: Kay" }, { type: "serverText", text: "Name: Bea" }],
      { text: "Name: Bea", dirty: false }],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect({ text: s.text, dirty: dirty(s) }).toEqual(want);
  });

  it("serverText sets both fields", () => {
    expect(run([{ type: "serverText", text: "Age: 24" }])).toEqual({ text: "Age: 24", savedText: "Age: 24" });
  });
});

describe("buildPayload (Save's PUT body)", () => {
  it("is the old shape: the stored brain with only model_notes set to the text", () => {
    const config = { persona: "Ella.", model_notes: "Name: Mia", model: "deepseek-v4-flash", daily_cost_cap_cents: 500, voice: null };
    const s = run([{ type: "edit", text: "Name: Kay\nAge: 24" }]);
    expect(buildPayload(config, s)).toEqual({
      persona: "Ella.", model_notes: "Name: Kay\nAge: 24", model: "deepseek-v4-flash", daily_cost_cap_cents: 500, voice: null,
    });
    expect(config.model_notes).toBe("Name: Mia");
  });
});

describe("hasPersona (mirrors _persona._model_notes_block's blank-label rule)", () => {
  it.each<[string, string, boolean]>([
    ["the blank template", TEMPLATE, false],
    ["empty", "", false],
    ["only whitespace lines", "  \n\t\n", false],
    ["template with extra spaces after labels", "Name:    \nAge:\n  From:  ", false],
    ["labels in another case", "NAME:\nage:", false],
    ["one filled label line", "Name: Mia\nAge: \nFrom: ", true],
    ["filled last label", TEMPLATE.replace("Won't do (hard limits): ", "Won't do (hard limits): meetups"), true],
    ["a free line", "loves hiking", true],
    ["an unknown label left blank counts", "Looks:", true],
    ["a filled line past 1000 chars is cut off", `${"Name: \n".repeat(143)}Likes: tea`, false],
  ])("%s", (_name, text, want) => {
    expect(hasPersona(text, TEMPLATE)).toBe(want);
  });
});
