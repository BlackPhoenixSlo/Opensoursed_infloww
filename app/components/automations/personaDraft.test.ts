import { describe, expect, it } from "vitest";

import {
  BUSY_LINE, busyLine, buildPayload, canDraft, dirty, hasPersona, initPersonaDraft, personaDraftReducer, requestBody, type Action, type PersonaDraft,
} from "./personaDraft";

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
    expect(run([{ type: "serverText", text: "Age: 24" }]))
      .toEqual({ text: "Age: 24", savedText: "Age: 24", phase: "idle", error: null, notes: [] });
  });
});

describe("draft from the Creator's images (click / confirm / cancel / draftOk / draftEmpty / draftFail)", () => {
  const blank = () => initPersonaDraft(TEMPLATE);
  const DRAFTED = "Name: Kay\nAge: 19\nFrom: Austin, TX\nLooks: blonde, freckles";
  const NEED = "No described images yet. Run Prepare content or the vault describe first.";
  const mia = () => initPersonaDraft("Name: Mia");
  const click: Action = { type: "click", template: TEMPLATE };

  it.each<[string, PersonaDraft, Action[], Partial<PersonaDraft> & { dirty?: boolean }]>([
    ["blank template → click → drafting", blank(), [{ type: "click", template: TEMPLATE }],
      { phase: "drafting", text: TEMPLATE, dirty: false }],
    ["draftOk replaces the text, makes dirty, saves nothing", blank(),
      [{ type: "click", template: TEMPLATE }, { type: "draftOk", text: DRAFTED, notes: [] }],
      { phase: "idle", text: DRAFTED, savedText: TEMPLATE, error: null, notes: [], dirty: true }],
    ["draftOk carries the route's notes", blank(),
      [click, { type: "draftOk", text: DRAFTED, notes: ["No OF name stored; type her name."] }],
      { phase: "idle", text: DRAFTED, notes: ["No OF name stored; type her name."] }],
    ["text present → click → confirm (no request yet)", mia(), [click], { phase: "confirm", text: "Name: Mia", dirty: false }],
    ["confirm → drafting", mia(), [click, { type: "confirm" }], { phase: "drafting", text: "Name: Mia" }],
    ["cancel keeps the text and makes no request", mia(), [click, { type: "cancel" }],
      { phase: "idle", text: "Name: Mia", savedText: "Name: Mia", error: null }],
    ["click while confirm changes nothing", mia(), [click, click], { phase: "confirm" }],
    ["confirm or cancel with no question open changes nothing", mia(), [{ type: "confirm" }, { type: "cancel" }],
      { phase: "idle", text: "Name: Mia" }],
    ["confirm then draftOk replaces his persona, unsaved", mia(), [click, { type: "confirm" }, { type: "draftOk", text: DRAFTED, notes: [] }],
      { phase: "idle", text: DRAFTED, savedText: "Name: Mia", dirty: true }],
    ["draftEmpty shows its note and keeps the text", mia(), [click, { type: "confirm" }, { type: "draftEmpty", note: NEED }],
      { phase: "idle", text: "Name: Mia", notes: [NEED], error: null, dirty: false }],
    ["a new click clears the last notes", blank(), [click, { type: "draftEmpty", note: NEED }, click], { phase: "drafting", notes: [] }],
    ["draftFail keeps the text and shows the error", blank(),
      [{ type: "click", template: TEMPLATE }, { type: "draftFail", error: "The AI provider failed. Try again." }],
      { phase: "error", text: TEMPLATE, error: "The AI provider failed. Try again." }],
    ["draftFail (cap hit) keeps his persona and sets the error", mia(),
      [click, { type: "confirm" }, { type: "draftFail", error: "Today's AI limit for this creator is reached." }],
      { phase: "error", text: "Name: Mia", savedText: "Name: Mia", error: "Today's AI limit for this creator is reached." }],
    ["click after a failure drafts again and clears the error", blank(),
      [{ type: "click", template: TEMPLATE }, { type: "draftFail", error: "x" }, { type: "click", template: TEMPLATE }],
      { phase: "drafting", error: null }],
    ["a draft reply with no request out is ignored", blank(),
      [{ type: "draftOk", text: DRAFTED, notes: [] }, { type: "draftEmpty", note: NEED }, { type: "draftFail", error: "x" }],
      { phase: "idle", text: TEMPLATE, error: null, notes: [] }],
    ["serverText keeps the phase", blank(), [{ type: "click", template: TEMPLATE }, { type: "serverText", text: TEMPLATE }],
      { phase: "drafting" }],
  ])("%s", (_name, from, actions, want) => {
    const s = actions.reduce(personaDraftReducer, from);
    const { dirty: wantDirty, ...fields } = want;
    expect(s).toMatchObject(fields);
    if (wantDirty !== undefined) expect(dirty(s)).toBe(wantDirty);
  });

  it("canDraft: no request out and no question open (a double tap is one request)", () => {
    const s = blank();
    expect(canDraft(s)).toBe(true);
    const drafting = personaDraftReducer(s, click);
    expect(canDraft(drafting)).toBe(false);
    expect(personaDraftReducer(drafting, click)).toBe(drafting);   // click while drafting changes nothing
    expect(canDraft(mia())).toBe(true);
    expect(canDraft(personaDraftReducer(mia(), click))).toBe(false);
  });

  it("busyLine: the gap-describe line only while the request is out (ticket 54)", () => {
    expect(BUSY_LINE).toBe("Describing up to 6 photos, then drafting…");
    const drafting = personaDraftReducer(blank(), click);
    expect.soft(busyLine(blank())).toBeNull();
    expect.soft(busyLine(personaDraftReducer(mia(), click))).toBeNull();   // confirm: no request yet
    expect.soft(busyLine(drafting)).toBe(BUSY_LINE);
    expect.soft(busyLine(personaDraftReducer(drafting, { type: "draftOk", text: "Name: Kay", notes: [] }))).toBeNull();
    expect.soft(busyLine(personaDraftReducer(drafting, { type: "draftEmpty", note: NEED }))).toBeNull();
    expect.soft(busyLine(personaDraftReducer(drafting, { type: "draftFail", error: "x" }))).toBeNull();
  });

  it("requestBody carries the unsaved text as current_text", () => {
    const s = personaDraftReducer(blank(), { type: "edit", text: "Won't do (hard limits): meetups" });
    expect(requestBody(s, "8000186")).toEqual({ account_id: "8000186", current_text: "Won't do (hard limits): meetups" });
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
