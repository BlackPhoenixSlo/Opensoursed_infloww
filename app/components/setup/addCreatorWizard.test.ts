import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  buildAccountPayload, canBack, canNext, initialWizard, useWizardReducer, wizardReducer,
  type AccountStep, type WizardAction, type WizardState, type WizardStep,
} from "@/components/setup/addCreatorWizard";
import type { AccountDetails } from "@/components/setup/creatorFlow";

type Kind = WizardStep["kind"];
const ACCOUNT: AccountDetails = { nickname: "Bella", tag: "", employeeIds: [], notes: "" };
const BELLA = { name: "Bella", gender: "Female" as const };
const DETAILS1: WizardStep = { kind: "creators-details", busy: false };
const SAVING1: WizardStep = { kind: "creators-details", busy: true };
const LINKED_STEP: WizardStep = { kind: "linked", accountId: "a", account: ACCOUNT };
const ACC: AccountStep = { kind: "creator-details", accountId: "a", account: ACCOUNT, busy: false };
const ACC_SAVING: AccountStep = { ...ACC, busy: true };

/** A state on `step`, OnlyFans, valid details, nothing taken or picked. */
function on(step: WizardStep, over: Partial<WizardState> = {}): WizardState {
  return { ...initialWizard({}), details: BELLA, step, ...over };
}
const run = (s: WizardState, ...actions: WizardAction[]) => actions.reduce(wizardReducer, s);
const NEXT = { type: "next" } as const;
const BACK = { type: "back" } as const;
const START = { type: "submitStart" } as const;
const OK = { type: "submitOk" } as const;
const ERR = { type: "submitErr" } as const;
const LINKED = { type: "linked", accountId: "of-1", account: ACCOUNT } as const;

describe("initialWizard", () => {
  it.each<[string, Parameters<typeof initialWizard>[0], Kind, string, unknown]>([
    ["header Add creator", {}, "creators-details", "onlyfans", null],
    ["a draft", { draft: { ...BELLA, id: "d1" } }, "select-platform", "onlyfans", null],
    ["Link another (has OnlyFans)", { linkAnother: { creator: BELLA, linked: ["onlyfans"] } }, "select-platform", "fansly", null],
    ["recovery, OnlyFans", { recovery: "onlyfans" }, "login", "onlyfans", { type: "none" }],
    ["recovery, Fansly", { recovery: "fansly" }, "login", "fansly", { type: "none" }],
  ])("%s", (_, props, step, platform, picked) => {
    const s = initialWizard(props);
    expect(s.step.kind).toBe(step);
    expect(s.platform).toBe(platform);
    expect(s.picked).toEqual(picked);
  });
  it("a draft's details (with its id) are the Creator, and its id the draftId", () => {
    const draft = { ...BELLA, id: "d1", created_at: "t" };
    expect(initialWizard({ draft })).toMatchObject({ details: draft, draftId: "d1" });
  });
});

describe("next / back", () => {
  it.each<[string, WizardState, Kind]>([
    ["creators-details (unsaved) → select-platform", on(DETAILS1), "select-platform"],
    ["select-platform (OnlyFans) → select-proxy", on({ kind: "select-platform" }), "select-proxy"],
    ["select-platform (Fansly) → login", on({ kind: "select-platform" }, { platform: "fansly" }), "login"],
    ["select-proxy (default) → login", on({ kind: "select-proxy" }), "login"],
    ["select-proxy (custom, checked) → login", on({ kind: "select-proxy" }, { picked: { type: "custom", label: "p1", ok: true } }), "login"],
    ["login (OnlyFans) → role (Still unable…)", on({ kind: "login" }), "role"],
    ["role → alt (Admin/employee)", on({ kind: "role" }), "alt"],
    ["linked → creator-details", on(LINKED_STEP), "creator-details"],
  ])("next: %s", (_, s, to) => expect(wizardReducer(s, NEXT).step.kind).toBe(to));

  it.each<[string, WizardState, Kind]>([
    ["login (OnlyFans) → select-proxy", on({ kind: "login" }), "select-proxy"],
    ["login (Fansly) → select-platform", on({ kind: "login" }, { platform: "fansly" }), "select-platform"],
    ["role → login (Creator / Cancel)", on({ kind: "role" }), "login"],
    ["alt → login", on({ kind: "alt" }), "login"],
    ["select-proxy → select-platform", on({ kind: "select-proxy" }), "select-platform"],
    ["select-platform → creators-details (opened there)", on({ kind: "select-platform" }), "creators-details"],
  ])("back: %s", (_, s, to) => expect(wizardReducer(s, BACK).step.kind).toBe(to));

  it("select-platform's Back after step 1's save lands on creators-details, not busy, keeping the draft", () => {
    const s = run(on(DETAILS1), START, { type: "submitOk", draftId: "d9" }, BACK);
    expect(s).toMatchObject({ step: DETAILS1, draftId: "d9", details: BELLA });
  });

  it.each<[string, WizardState, boolean]>([
    ["creators-details", on(DETAILS1), false],
    ["select-platform, opened at creators-details", on({ kind: "select-platform" }), true],
    ["select-platform, opened there (a draft)", initialWizard({ draft: { ...BELLA, id: "d1" } }), false],
    ["select-platform, opened there (Link another)", initialWizard({ linkAnother: { creator: BELLA, linked: ["onlyfans"] } }), false],
    ["select-proxy", on({ kind: "select-proxy" }), true],
    ["login", on({ kind: "login" }), true],
    ["linked", on(LINKED_STEP), false],
    ["creator-details", on(ACC), false],
    ["success", on({ kind: "success" }), false],
    // A row's recovery opens at login: nothing before it, so its sign-in has no Back (its footer is Cancel → close).
    ["login, opened there (recovery, OnlyFans)", initialWizard({ recovery: "onlyfans" }), false],
    ["login, opened there (recovery, Fansly)", initialWizard({ recovery: "fansly" }), false],
    ["role in a recovery (back to its login)", { ...initialWizard({ recovery: "onlyfans" }), step: { kind: "role" } }, true],
  ])("canBack: %s", (_, s, ok) => expect(canBack(s)).toBe(ok));

  it("linked carries the account on to creator-details", () => {
    expect(run(on({ kind: "login" }), LINKED, NEXT).step).toEqual({ kind: "creator-details", accountId: "of-1", account: ACCOUNT, busy: false });
  });

  it("back keeps the details, platform and proxy picked", () => {
    const picked = { type: "custom" as const, label: "p1", ok: true };
    const s = run(on({ kind: "select-proxy" }), { type: "setField", field: "proxy", value: picked }, NEXT, BACK);
    expect(s).toMatchObject({ step: { kind: "select-proxy" }, picked, details: BELLA, platform: "onlyfans" });
  });
});

describe("canNext (what every Next button is disabled by)", () => {
  it.each<[string, WizardState, boolean]>([
    ["details valid", on(DETAILS1), true],
    ["details: no name", on(DETAILS1, { details: { name: " ", gender: "Female" } }), false],
    ["details: no gender", on(DETAILS1, { details: { name: "Bella", gender: "" } }), false],
    ["details: saving", on(SAVING1), false],
    ["platform free", on({ kind: "select-platform" }), true],
    ["platform taken", on({ kind: "select-platform" }, { taken: ["onlyfans"] }), false],
    ["proxy: default", on({ kind: "select-proxy" }), true],
    ["proxy: custom unchecked", on({ kind: "select-proxy" }, { picked: { type: "custom", label: "p1", ok: null } }), false],
    ["proxy: custom failed check", on({ kind: "select-proxy" }, { picked: { type: "custom", label: "p1", ok: false } }), false],
    ["login, OnlyFans", on({ kind: "login" }), true],
    ["login, Fansly (no Still unable…)", on({ kind: "login" }, { platform: "fansly" }), false],
    ["role", on({ kind: "role" }), true],
    ["alt", on({ kind: "alt" }), false],
    ["linked", on(LINKED_STEP), true],
    ["account: a nickname", on(ACC), true],
    ["account: blank nickname", on({ ...ACC, account: { ...ACCOUNT, nickname: "  " } }), false],
    ["account: saving", on(ACC_SAVING), false],
    ["success", on({ kind: "success" }), false],
  ])("%s", (_, s, ok) => expect(canNext(s)).toBe(ok));
});

describe("invalid transitions are no-ops", () => {
  it.each<[string, WizardState, WizardAction]>([
    ["next with invalid details", on(DETAILS1, { details: { name: "", gender: "" } }), NEXT],
    ["next while saving", on(SAVING1), NEXT],
    ["next to a taken platform", on({ kind: "select-platform" }, { taken: ["onlyfans"] }), NEXT],
    ["next on an unchecked custom proxy", on({ kind: "select-proxy" }, { picked: { type: "custom", label: "p1", ok: null } }), NEXT],
    ["next on Fansly's login", on({ kind: "login" }, { platform: "fansly" }), NEXT],
    ["next on alt", on({ kind: "alt" }), NEXT],
    ["next on creator-details (that is the save)", on(ACC), NEXT],
    ["next on success", on({ kind: "success" }), NEXT],
    ["back on creators-details", on(DETAILS1), BACK],
    ["back on select-platform opened there (a draft)", initialWizard({ draft: { ...BELLA, id: "d1" } }), BACK],
    ["back on select-platform opened there (Link another)",
      initialWizard({ linkAnother: { creator: BELLA, linked: ["onlyfans"] } }), BACK],
    ["back on a recovery's login (never to select-proxy, before where it opened)", initialWizard({ recovery: "onlyfans" }), BACK],
    ["back on linked (the account stays)", on(LINKED_STEP), BACK],
    ["back on creator-details", on(ACC), BACK],
    ["pick a taken platform", on({ kind: "select-platform" }, { taken: ["fansly"] }), { type: "setField", field: "platform", value: "fansly" }],
    ["account before linking", on({ kind: "login" }), { type: "setField", field: "account", value: ACCOUNT }],
    ["linked on success", on({ kind: "success" }), LINKED],
    ["submitStart on a step with no save", on({ kind: "login" }), START],
    // A double-click on "Next: Link creator account" (step 1's save) or account details' Next: the second
    // submitStart / next lands on a busy step and is dropped, so exactly one save runs.
    ["submitStart twice", on(SAVING1), START],
    ["submitStart twice on account details", on(ACC_SAVING), START],
    ["next while account details saves", on(ACC_SAVING), NEXT],
    ["back while step 1 saves", on(SAVING1), BACK],
    ["submitStart with invalid details", on(DETAILS1, { details: { name: "", gender: "" } }), START],
    ["submitStart with a blank nickname", on({ ...ACC, account: { ...ACCOUNT, nickname: "" } }), START],
    ["submitOk with no save running", on(ACC), OK],
    ["submitErr with no save running", on(DETAILS1), ERR],
  ])("%s", (_, s, a) => expect(wizardReducer(s, a)).toBe(s));
});

describe("late events land (HEAD parity, except: `linked` is ignored on success and while a save runs)", () => {
  it.each<WizardStep>([
    DETAILS1, { kind: "select-platform" }, { kind: "select-proxy" }, { kind: "login" }, { kind: "role" }, { kind: "alt" },
    LINKED_STEP, ACC,
  ])("linked from $kind switches to the newest account", (step) => {
    expect(wizardReducer(on(step), LINKED).step).toEqual({ kind: "linked", accountId: "of-1", account: ACCOUNT });
  });
  it("a proxy check settling after Connect still updates the pick", () => {
    const checked = { type: "custom" as const, label: "p1", ok: true };
    expect(wizardReducer(on({ kind: "login" }), { type: "setField", field: "proxy", value: checked }).picked).toEqual(checked);
  });
  it("an avatar landing after Next still updates the details", () => {
    const withAvatar = { ...BELLA, avatar: "data:x" };
    expect(wizardReducer(on({ kind: "select-platform" }), { type: "setField", field: "details", value: withAvatar }).details).toEqual(withAvatar);
  });
  it("a platform set off its step still applies (unless taken)", () => {
    expect(wizardReducer(on({ kind: "login" }), { type: "setField", field: "platform", value: "fansly" }).platform).toBe("fansly");
  });
});

describe("linked while a save runs (ignored, so the save's end still lands)", () => {
  const saving = on(ACC_SAVING);
  it("is ignored", () => expect(wizardReducer(saving, LINKED)).toBe(saving));
  it("then submitOk → success", () => expect(run(saving, LINKED, OK).step).toEqual({ kind: "success" }));
  it("then submitErr → creator-details, not busy", () => expect(run(saving, LINKED, ERR).step).toEqual(ACC));
  it("is ignored on step 1's save too", () => expect(wizardReducer(on(SAVING1), LINKED).step).toEqual(SAVING1));
});

describe("submit lifecycle", () => {
  it("a double-click on Next: Link creator account is one save: one busy step, its submitOk lands once", () => {
    const s1 = run(on(DETAILS1), START, START);
    expect(s1).toEqual(wizardReducer(on(DETAILS1), START));
    const s2 = run(s1, { type: "submitOk", draftId: "d9" }, OK);
    expect(s2).toMatchObject({ step: { kind: "select-platform" }, draftId: "d9" });
  });
  it("step 1, new Creator: start → ok moves to select-platform with the draft id", () => {
    const s1 = wizardReducer(on(DETAILS1), START);
    expect(s1.step).toEqual(SAVING1);
    expect(canNext(s1)).toBe(false);
    expect(wizardReducer(s1, { type: "submitOk", draftId: "d9" })).toMatchObject({ draftId: "d9", step: { kind: "select-platform" } });
  });
  it("step 1, existing draft: ok without an id keeps it", () => {
    expect(run(on(DETAILS1, { draftId: "d1" }), START, OK).draftId).toBe("d1");
  });
  it("step 1: err clears busy and stays", () => {
    expect(run(on(DETAILS1), START, ERR).step).toEqual(DETAILS1);
  });
  it("account details: start → ok → success; err stays with the edits", () => {
    const edited = { ...ACCOUNT, nickname: "Bella2" };
    const s0 = run(on(LINKED_STEP), NEXT, { type: "setField", field: "account", value: edited });
    const s1 = wizardReducer(s0, START);
    expect(canNext(s1)).toBe(false);
    expect(wizardReducer(s1, OK).step).toEqual({ kind: "success" });
    expect(wizardReducer(s1, ERR).step).toEqual({ kind: "creator-details", accountId: "a", account: edited, busy: false });
  });
});

describe("buildAccountPayload", () => {
  it("is useSaveAccountDetails' variables: the account, before \"\", the Creator details and draft", () => {
    const roster = [{ id: 7, display_name: "Eve", account_ids: [] }] as never;
    expect(buildAccountPayload(on(ACC, { draftId: "d1" }), ACC, roster)).toEqual({
      accountId: "a", before: "", roster, details: ACCOUNT, creator: BELLA, draftId: "d1",
    });
  });
});

/** The component's dispatch: on the newest state, and true only when the wizard took the action. */
describe("useWizardReducer", () => {
  it("two submitStarts before a re-render: the first is taken, the second refused", () => {
    const { result } = renderHook(() => useWizardReducer({}));
    const dispatch = result.current[1];
    act(() => { dispatch({ type: "setField", field: "details", value: BELLA }); });
    const taken: boolean[] = [];
    // One act: no re-render between the two (a double-click's worst case).
    act(() => { taken.push(dispatch(START), dispatch(START)); });
    expect(taken).toEqual([true, false]);
    expect(result.current[0].step).toEqual(SAVING1);
  });
  it.each<[string, WizardAction, boolean]>([
    ["a next canNext forbids (no details yet)", NEXT, false],
    ["a Back with nowhere to go", BACK, false],
    ["a field edit", { type: "setField", field: "details", value: BELLA }, true],
  ])("%s", (_, action, want) => {
    const { result } = renderHook(() => useWizardReducer({}));
    let got: boolean | undefined;
    act(() => { got = result.current[1](action); });
    expect(got).toBe(want);
  });
});
