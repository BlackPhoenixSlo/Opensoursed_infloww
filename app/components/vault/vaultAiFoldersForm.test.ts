import { describe, expect, it } from "vitest";

import {
  aiFoldersFormReducer, buildPayload, canSubmit, changesLine, confirmLabel, INITIAL_FORM, KEEP_CHOICES, keepLabel,
  topicsUsable,
  type Action, type AiFoldersForm, type PlanChanges,
} from "./vaultAiFoldersForm";

const run = (actions: Action[], from: AiFoldersForm = INITIAL_FORM) => actions.reduce(aiFoldersFormReducer, from);
const changes = (over: Partial<PlanChanges> = {}): PlanChanges =>
  ({ create: 3, keep: 9, retire: 0, retire_on_of: 0, retired: [], ...over });

describe("aiFoldersFormReducer", () => {
  it.each<[string, Action[], AiFoldersForm]>([
    ["defaults: 10 shoots, no solo, mirror on", [], { keep: 10, solo: false, mirrorToOf: true, topics: [], split: true }],
    ["keep 0 stays 0 (lanes only)", [{ type: "keep", keep: 0 }], { keep: 0, solo: false, mirrorToOf: true, topics: [], split: true }],
    ["keep 20 is allowed", [{ type: "keep", keep: 20 }], { keep: 20, solo: false, mirrorToOf: true, topics: [], split: true }],
    ["keep clamps to 0..20", [{ type: "keep", keep: 99 }], { keep: 20, solo: false, mirrorToOf: true, topics: [], split: true }],
    ["keep NaN reads as 0", [{ type: "keep", keep: Number("x") }], { keep: 0, solo: false, mirrorToOf: true, topics: [], split: true }],
    ["solo and mirror toggle independently", [{ type: "solo", on: true }, { type: "mirror", on: false }],
      { keep: 10, solo: true, mirrorToOf: false, topics: [], split: true }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toEqual(want);
  });

  it("a no-op action keeps the same state object", () => {
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "keep", keep: 10 })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "solo", on: false })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "mirror", on: true })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "split", on: true })).toBe(INITIAL_FORM);
  });

  it("buildPayload is exactly the preview's options", () => {
    expect(buildPayload(run([{ type: "keep", keep: 0 }, { type: "solo", on: true }])))
      .toEqual({ keep: 0, solo: true, mirrorToOf: true, topics: [], split: true });
    expect(buildPayload(run([{ type: "topic", slug: "spread", on: true }, { type: "topic", slug: "bikini", on: true }])))
      .toEqual({ keep: 10, solo: false, mirrorToOf: true, topics: ["bikini", "spread"], split: true });
    expect(buildPayload(run([{ type: "split", on: false }, { type: "topic", slug: "bikini", on: true }])))
      .toEqual({ keep: 10, solo: false, mirrorToOf: true, topics: ["bikini"], split: false });
  });
});

describe("topics", () => {
  const ALL = ["heels_stockings", "bikini", "spread"];
  it.each<[string, Action[], string[]]>([
    ["none ticked by default", [], []],
    ["tick one", [{ type: "topic", slug: "bikini", on: true }], ["bikini"]],
    ["ticks stay sorted", [{ type: "topic", slug: "spread", on: true }, { type: "topic", slug: "bikini", on: true }],
      ["bikini", "spread"]],
    ["tick twice is one", [{ type: "topic", slug: "bikini", on: true }, { type: "topic", slug: "bikini", on: true }],
      ["bikini"]],
    ["untick", [{ type: "topic", slug: "bikini", on: true }, { type: "topic", slug: "spread", on: true },
      { type: "topic", slug: "bikini", on: false }], ["spread"]],
    ["select all = the catalogue", [{ type: "topicsAll", slugs: ALL }], ["bikini", "heels_stockings", "spread"]],
    ["none clears", [{ type: "topicsAll", slugs: ALL }, { type: "topicsNone" }], []],
  ])("%s", (_name, actions, want) => {
    expect(run(actions).topics).toEqual(want);
  });

  it("topic actions leave the other options alone", () => {
    const from = run([{ type: "keep", keep: 5 }, { type: "solo", on: true }, { type: "mirror", on: false },
      { type: "split", on: false }]);
    expect(run([{ type: "topicsAll", slugs: ALL }], from))
      .toMatchObject({ keep: 5, solo: true, mirrorToOf: false, split: false });
  });

  it("a no-op topic action keeps the same state object", () => {
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "topicsNone" })).toBe(INITIAL_FORM);
    expect(aiFoldersFormReducer(INITIAL_FORM, { type: "topic", slug: "bikini", on: false })).toBe(INITIAL_FORM);
    const one = run([{ type: "topic", slug: "bikini", on: true }]);
    expect(aiFoldersFormReducer(one, { type: "topic", slug: "bikini", on: true })).toBe(one);
    expect(aiFoldersFormReducer(one, { type: "topicsAll", slugs: ["bikini"] })).toBe(one);
  });

  it.each<[string, Parameters<typeof topicsUsable>[0], boolean]>([
    ["Jev on with data", { enabled: true, with_jev: 3 }, true],
    ["Jev on, nothing read yet", { enabled: true, with_jev: 0 }, false],
    ["Jev off, old data", { enabled: false, with_jev: 9 }, false],
    ["no plan yet", undefined, false],
  ])("topicsUsable: %s", (_n, jev, want) => {
    expect(topicsUsable(jev)).toBe(want);
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
