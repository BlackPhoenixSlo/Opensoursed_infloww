import { describe, expect, it } from "vitest";

import {
  aiFoldersFormReducer, buildPayload, canSubmit, changesLine, confirmLabel, INITIAL_FORM, KEEP_CHOICES, keepLabel,
  type Action, type AiFoldersForm, type PlanChanges,
} from "./vaultAiFoldersForm";

const run = (actions: Action[], from: AiFoldersForm = INITIAL_FORM) => actions.reduce(aiFoldersFormReducer, from);
const changes = (over: Partial<PlanChanges> = {}): PlanChanges =>
  ({ create: 3, keep: 9, retire: 0, retire_on_of: 0, retired: [], ...over });

describe("aiFoldersFormReducer", () => {
  it.each<[string, Action[], AiFoldersForm]>([
    ["defaults: 2 shoots, no solo, mirror on", [], { keep: 2, solo: false, mirrorToOf: true }],
    ["keep 0 stays 0 (lanes only)", [{ type: "keep", keep: 0 }], { keep: 0, solo: false, mirrorToOf: true }],
    ["keep 20 is allowed", [{ type: "keep", keep: 20 }], { keep: 20, solo: false, mirrorToOf: true }],
    ["keep clamps to 0..20", [{ type: "keep", keep: 99 }], { keep: 20, solo: false, mirrorToOf: true }],
    ["keep NaN reads as 0", [{ type: "keep", keep: Number("x") }], { keep: 0, solo: false, mirrorToOf: true }],
    ["solo and mirror toggle independently", [{ type: "solo", on: true }, { type: "mirror", on: false }],
      { keep: 2, solo: true, mirrorToOf: false }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toEqual(want);
  });

  it("a no-op action keeps the same state object", () => {
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "keep", keep: 2 })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "solo", on: false })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "mirror", on: true })).toBe(INITIAL_FORM);
  });

  it("buildPayload is exactly the preview's options", () => {
    expect(buildPayload(run([{ type: "keep", keep: 0 }, { type: "solo", on: true }])))
      .toEqual({ keep: 0, solo: true, mirrorToOf: true });
  });
});

describe("copy", () => {
  it("keep choices run 0..20, 0 = lanes only", () => {
    expect(KEEP_CHOICES[0]).toBe(0);
    expect(KEEP_CHOICES[KEEP_CHOICES.length - 1]).toBe(20);
    expect(KEEP_CHOICES).toHaveLength(21);
    expect([0, 1, 5].map(keepLabel)).toEqual(["none (lanes only)", "top 1 shoot", "top 5 shoots"]);
  });

  it.each<[string, boolean, number, boolean]>([
    ["idle with folders", false, 4, true],
    ["busy", true, 4, false],
    ["no folders", false, 0, false],
  ])("canSubmit: %s", (_n, busy, folders, want) => {
    expect(canSubmit(busy, folders)).toBe(want);
  });

  it("changesLine says create / keep / retire, nothing before the plan", () => {
    expect(changesLine(changes({ retire: 2 }))).toBe("will create 3 · keep 9 · retire 2");
    expect(changesLine(undefined)).toBeNull();
  });

  it.each<[string, Parameters<typeof confirmLabel>[0], string]>([
    ["first build", { busy: false, built: false, folders: 12, changes: changes() }, "Create 12 folders"],
    ["retire without OF lists", { busy: false, built: false, folders: 12, changes: changes({ retire: 2 }) },
      "Create 12 folders"],
    ["retire with OF lists says so", { busy: false, built: false, folders: 12,
      changes: changes({ retire: 3, retire_on_of: 2 }) }, "Create 12 folders · retire 2 linked to OnlyFans"],
    ["rebuild with OF lists says so", { busy: false, built: true, folders: 12, changes: changes({ retire_on_of: 1 }) },
      "Rebuild · retire 1 linked to OnlyFans"],
    ["plan not landed", { busy: false, built: false, folders: 0, changes: undefined }, "Create 0 folders"],
    ["busy wins", { busy: true, built: false, folders: 12, changes: changes({ retire_on_of: 2 }) }, "Creating…"],
  ])("confirmLabel: %s", (_n, opts, want) => {
    expect(confirmLabel(opts)).toBe(want);
  });
});
