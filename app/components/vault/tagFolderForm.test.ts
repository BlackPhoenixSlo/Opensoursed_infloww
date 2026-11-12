import { describe, expect, it } from "vitest";

import {
  INITIAL_TAG_FOLDER_FORM as I, TAG_FOLDER_MAX, buildPayload, canSubmit, capText, defaultFolderName, folderName,
  publishedText, publishQuestion, savedText, tagFolderFormReducer, type TagFolderAction, type TagFolderForm,
} from "./tagFolderForm";

const run = (actions: TagFolderAction[], from: TagFolderForm = I) => actions.reduce(tagFolderFormReducer, from);
const TAGS = ["feet", "lace"];
const F = { folderId: 7, name: "feet + lace", items: 12 };
const saved = run([{ type: "open" }, { type: "start" }, { type: "done", folder: F }]);

describe("name follows the chips until typed", () => {
  it.each<[string, TagFolderAction[], readonly string[], string]>([
    ["default", [{ type: "open" }], TAGS, "feet + lace"],
    ["chips change, still default", [{ type: "open" }], ["feet"], "feet"],
    ["typed wins", [{ type: "open" }, { type: "name", value: "Soles" }], TAGS, "Soles"],
    ["typed blank stays blank", [{ type: "open" }, { type: "name", value: "" }], TAGS, ""],
    ["close forgets the typing", [{ type: "open" }, { type: "name", value: "x" }, { type: "close" }], TAGS, "feet + lace"],
  ])("%s", (_n, actions, tags, want) => {
    expect(folderName(run(actions), tags)).toBe(want);
  });
  it("default name caps at 120", () => {
    expect(defaultFolderName(["a".repeat(100), "b".repeat(100)])).toHaveLength(120);
  });
});

describe("canSubmit", () => {
  const open = run([{ type: "open" }]);
  it.each<[string, TagFolderForm, readonly string[], number, boolean]>([
    ["open, chips, default name", open, TAGS, 12, true],
    ["closed", I, TAGS, 12, false],
    ["no chip", open, [], 12, false],
    ["nothing matches", open, TAGS, 0, false],
    ["at the cap", open, TAGS, TAG_FOLDER_MAX, true],
    ["over the cap", open, TAGS, TAG_FOLDER_MAX + 1, false],
    ["blank typed name", run([{ type: "name", value: "  " }], open), TAGS, 12, false],
    ["saving", run([{ type: "start" }], open), TAGS, 12, false],
  ])("%s", (_n, s, tags, total, want) => {
    expect(canSubmit(s, tags, total)).toBe(want);
  });
  it("capText only over the cap", () => {
    expect(capText(TAG_FOLDER_MAX)).toBeNull();
    expect(capText(7213)).toBe("7,213 items match; a saved folder holds at most 5,000. Pick another chip or filter to narrow it.");
  });
});

describe("save lifecycle", () => {
  it("start blocks a second start; done closes, resets and shows the saved row; a failure keeps the form", () => {
    const saving = run([{ type: "open" }, { type: "name", value: "Soles" }, { type: "start" }]);
    expect(tagFolderFormReducer(saving, { type: "start" })).toBe(saving);
    expect(tagFolderFormReducer(saving, { type: "close" })).toBe(saving);
    expect(tagFolderFormReducer(saving, { type: "done", folder: F })).toEqual({ ...I, saved: F });
    expect(tagFolderFormReducer(saving, { type: "failed", text: "nope" }))
      .toMatchObject({ open: true, saving: false, name: "Soles", error: "nope", saved: null });
  });
  it("the saved row stays through a new form and is replaced by the next save; dismiss clears it", () => {
    const reopened = run([{ type: "open" }], saved);
    expect(reopened.saved).toEqual(F);
    const next = { ...F, folderId: 8, name: "feet + lace 2" };
    expect(run([{ type: "start" }, { type: "done", folder: next }], reopened).saved).toEqual(next);
    expect(run([{ type: "dismiss" }], saved)).toEqual(I);
    expect(tagFolderFormReducer(I, { type: "dismiss" })).toBe(I);
  });
});

describe("publish: ask, then one at a time", () => {
  it.each<[string, TagFolderAction[], TagFolderForm["publish"]]>([
    ["ask", [{ type: "publishAsk" }], { step: "confirm" }],
    ["cancel", [{ type: "publishAsk" }, { type: "publishCancel" }], { step: "idle" }],
    ["start without asking: no-op", [{ type: "publishStart" }], { step: "idle" }],
    ["publishing", [{ type: "publishAsk" }, { type: "publishStart" }], { step: "publishing" }],
    ["done", [{ type: "publishAsk" }, { type: "publishStart" }, { type: "publishDone", text: "ok" }], { step: "done", text: "ok" }],
    ["failed, may ask again", [{ type: "publishAsk" }, { type: "publishStart" }, { type: "publishFailed", text: "502" },
      { type: "publishAsk" }], { step: "confirm" }],
    ["done: no second ask", [{ type: "publishAsk" }, { type: "publishStart" }, { type: "publishDone", text: "ok" },
      { type: "publishAsk" }], { step: "done", text: "ok" }],
  ])("%s", (_n, actions, want) => {
    expect(run(actions, saved).publish).toEqual(want);
  });
  it("nothing saved: no ask; publishing: no dismiss and no new save", () => {
    expect(tagFolderFormReducer(I, { type: "publishAsk" })).toBe(I);
    const busy = run([{ type: "publishAsk" }, { type: "publishStart" }], saved);
    expect(tagFolderFormReducer(busy, { type: "dismiss" })).toBe(busy);
    const opened = run([{ type: "open" }], busy);
    expect(tagFolderFormReducer(opened, { type: "start" })).toBe(opened);
  });
});

describe("buildPayload: the grid's filters, the trimmed name", () => {
  it("sends chips, type, search and the open folder (a Fansly snowflake stays a string)", () => {
    const s = run([{ type: "open" }, { type: "name", value: "  Soles  " }]);
    expect(buildPayload(s, { accountId: "A", tags: TAGS, type: "photo", query: "bed", ofFolderId: "900000000000000777" }))
      .toEqual({ account_id: "A", name: "Soles", tags: TAGS, type: "photo", query: "bed", of_folder_id: "900000000000000777" });
    expect(buildPayload(run([{ type: "open" }]), { accountId: "A", tags: ["feet"], type: "all", query: "", ofFolderId: null }).name)
      .toBe("feet");
  });
});

describe("texts", () => {
  it.each<[number, string]>([
    [1, "Saved locally · f · 1 item"],
    [1200, "Saved locally · f · 1,200 items"],
  ])("saved %s", (items, want) => {
    expect(savedText({ folderId: 1, name: "f", items })).toBe(want);
  });
  it("the confirm states the count; published says what was sent", () => {
    expect(publishQuestion(F)).toContain("adds all 12 items");
    expect(publishedText({ pushed: 12 })).toBe("Published to OnlyFans · 12 items");
  });
});
