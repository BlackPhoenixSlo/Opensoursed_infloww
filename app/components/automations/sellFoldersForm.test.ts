import { describe, expect, it } from "vitest";

import {
  buildPayload, canSubmit, initFolders, NO_FOLDER_TEXT, sellFoldersReducer, type Action, type FolderPick,
} from "./sellFoldersForm";

const stored = (include: string[], exclude: string[] = []) => ({ include, exclude });
const run = (actions: Action[], from: FolderPick = initFolders(stored([]))) => actions.reduce(sellFoldersReducer, from);
const toggle = (ref: string): Action => ({ type: "toggle", ref });
const ALL: Action = { type: "all" };

describe("sellFoldersReducer", () => {
  it.each<[string, FolderPick, Action[], FolderPick]>([
    ["stored All opens with All on", initFolders(stored([])), [], { include: [], all: true }],
    ["stored list opens ticked, All off", initFolders(stored(["vf:1", "of:2"])), [], { include: ["vf:1", "of:2"], all: false }],
    ["ticking a folder turns All off", initFolders(stored([])), [toggle("vf:1")], { include: ["vf:1"], all: false }],
    ["ticking twice unticks", initFolders(stored([])), [toggle("vf:1"), toggle("vf:1")], { include: [], all: false }],
    ["All on clears the ticks", initFolders(stored(["vf:1"])), [ALL], { include: [], all: true }],
    ["All off again: nothing ticked", initFolders(stored(["vf:1"])), [ALL, ALL], { include: [], all: false }],
    ["tick while All on: All off, only that folder", initFolders(stored(["vf:1"])), [ALL, toggle("of:9")],
      { include: ["of:9"], all: false }],
    ["reset drops edits back to stored", initFolders(stored(["vf:1"])), [toggle("of:9"), ALL, { type: "reset", stored: stored(["of:3"]) }],
      { include: ["of:3"], all: false }],
    ["reset to All", initFolders(stored(["vf:1"])), [{ type: "reset", stored: stored([]) }], { include: [], all: true }],
  ])("%s", (_name, from, actions, want) => {
    expect(run(actions, from)).toEqual(want);
  });
});

describe("canSubmit", () => {
  it.each<[string, FolderPick, boolean]>([
    ["All on", { include: [], all: true }, true],
    ["one folder", { include: ["vf:1"], all: false }, true],
    ["nothing ticked, All off", { include: [], all: false }, false],
  ])("%s", (_name, s, want) => expect(canSubmit(s)).toBe(want));

  it("names why it is blocked", () => expect(NO_FOLDER_TEXT).toBe("pick at least one folder, or All"));
});

describe("buildPayload", () => {
  it.each<[string, FolderPick, { include: string[]; exclude: string[] }, { include: string[]; exclude: string[] }]>([
    ["All sends include []", { include: ["vf:1"], all: true }, stored(["vf:1"], ["of:7"]), { include: [], exclude: ["of:7"] }],
    ["picked list goes as include", { include: ["vf:1", "of:2"], all: false }, stored([]), { include: ["vf:1", "of:2"], exclude: [] }],
    ["stored exclude carried untouched", { include: ["vf:1"], all: false }, stored([], ["vf:5", "of:6"]),
      { include: ["vf:1"], exclude: ["vf:5", "of:6"] }],
  ])("%s", (_name, s, from, want) => expect(buildPayload(s, from)).toEqual(want));

  it("does not alias the stored exclude array", () => {
    const from = stored([], ["vf:5"]);
    const out = buildPayload({ include: [], all: true }, from);
    expect(out.exclude).not.toBe(from.exclude);
  });
});
