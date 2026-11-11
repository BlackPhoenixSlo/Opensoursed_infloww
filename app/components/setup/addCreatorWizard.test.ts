import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  buildAccountPayload, canBack, canClose, canNext, canPickPlatform, initialWizard, profileName, useWizardReducer, wizardReducer,
  type LinkedStep, type WizardAction, type WizardState, type WizardStep,
} from "@/components/setup/addCreatorWizard";
import type { AccountDetails } from "@/components/setup/creatorFlow";

const ACCOUNT: AccountDetails = { nickname: "Bella", tag: "", employeeIds: [], notes: "" };
const BELLA = { name: "Bella", gender: "Female" as const };
const LOGIN: WizardStep = { kind: "login" };
const ACC: LinkedStep = { kind: "linked", accountId: "a", account: ACCOUNT, busy: false };
const ACC_SAVING: LinkedStep = { ...ACC, busy: true };
const SUCCESS: WizardStep = { kind: "success" };

/** A state on `step`: OnlyFans, Browser login, nothing taken. */
function on(step: WizardStep, over: Partial<WizardState> = {}): WizardState {
  return { ...initialWizard({}), step, ...over };
}
const run = (s: WizardState, ...actions: WizardAction[]) => actions.reduce(wizardReducer, s);
const START = { type: "submitStart" } as const;
const OK = { type: "submitOk" } as const;
const ERR = { type: "submitErr" } as const;
const LINKED = { type: "linked", accountId: "of-1", account: ACCOUNT, platform: "onlyfans" } as const;
const IDLE = { login: false, extension: false, proxy: false };
const method = (value: "browser" | "extension") => ({ type: "setField", field: "method", value }) as const;
const platform = (value: "onlyfans" | "fansly") => ({ type: "setField", field: "platform", value }) as const;

describe("initialWizard", () => {
  it("header Add creator starts with details", () => {
    expect(initialWizard({})).toMatchObject({ step: { kind: "details" }, platform: "onlyfans", method: "browser" });
  });
  it.each<[string, Parameters<typeof initialWizard>[0], string, string, boolean]>([
    ["a draft", { draft: { ...BELLA, id: "d1" } }, "onlyfans", "browser", false],
    ["Link another (has OnlyFans)", { linkAnother: { creator: BELLA, linked: ["onlyfans"] } }, "fansly", "extension", false],
    ["Link another (has Fansly)", { linkAnother: { creator: BELLA, linked: ["fansly"] } }, "onlyfans", "browser", false],
    ["recovery, OnlyFans, Browser login", { recovery: "onlyfans", method: "browser" }, "onlyfans", "browser", true],
    ["recovery, OnlyFans, Extension", { recovery: "onlyfans", method: "extension" }, "onlyfans", "extension", true],
    ["recovery, Fansly (method ignored)", { recovery: "fansly", method: "browser" }, "fansly", "extension", true],
  ])("%s: existing creators start at sign-in", (_, props, plat, m, recovery) => {
    const s = initialWizard(props);
    expect(s.step).toEqual(LOGIN);
    expect(s).toMatchObject({ platform: plat, method: m, recovery });
  });
  it("a draft's details (with its id) are the Creator, and its id the draftId", () => {
    const draft = { ...BELLA, id: "d1", created_at: "t" };
    expect(initialWizard({ draft })).toMatchObject({ details: draft, draftId: "d1" });
  });
  it("the header's Add creator has no Creator details", () => {
    expect(initialWizard({}).details).toEqual({ name: "", gender: "" });
  });
  it.each<[string, Parameters<typeof initialWizard>[0], boolean]>([
    ["header", {}, true],
    ["draft", { draft: { ...BELLA, id: "d1" } }, false],
    ["Link another", { linkAnother: { creator: BELLA, linked: ["onlyfans"] } }, false],
    ["recovery", { recovery: "onlyfans" }, false],
  ])("fresh: %s → %s", (_, props, fresh) => {
    expect(initialWizard(props)).toMatchObject({ fresh, busy: { login: false, extension: false, proxy: false } });
  });
});

describe("new creator setup", () => {
  it.each(["onlyfans", "fansly"] as const)("details survive back navigation and reach the %s save", (value) => {
    const details = { ...BELLA, avatar: "data:image/png;base64,test" };
    const entered = run(initialWizard({}), { type: "setDetails", value: details }, { type: "detailsNext" });
    expect(entered.step.kind).toBe("platform");
    const login = run(entered, platform(value), { type: "platformNext" });
    expect(login).toMatchObject({ step: LOGIN, details, platform: value, method: value === "fansly" ? "extension" : "browser" });
    const back = run(login, { type: "back" }, { type: "back" });
    expect(back).toMatchObject({ step: { kind: "details" }, details });
    const linked = run(back, { type: "detailsNext" }, { type: "platformNext" }, { ...LINKED, platform: value });
    expect(buildAccountPayload(linked, linked.step as LinkedStep, null).creator).toEqual(details);
  });
  it.each([
    { draft: { ...BELLA, id: "d1" } },
    { recovery: "onlyfans" as const },
    { linkAnother: { creator: BELLA, linked: ["onlyfans" as const] } },
  ])("existing entry cannot go back into new creator details: %j", (props) => {
    const s = initialWizard(props);
    expect(run(s, { type: "back" })).toBe(s);
  });
  it.each<[string, WizardState, boolean]>([
    ["platform", on({ kind: "platform" }), true],
    ["a new Creator's sign-in", on(LOGIN), true],
    ["a new Creator's sign-in, a Browser login running", on(LOGIN, { busy: { ...IDLE, login: true } }), false],
    ["a new Creator's sign-in, the Extension capturing or waiting on Retry / Continue", on(LOGIN, { busy: { ...IDLE, extension: true } }), false],
    ["a draft's sign-in", on(LOGIN, { fresh: false }), false],
    ["details", on({ kind: "details" }), false],
    ["linked", on(ACC), false],
  ])("canBack: %s", (_, s, ok) => {
    expect(canBack(s)).toBe(ok);
    expect(run(s, { type: "back" }) !== s).toBe(ok);
  });
});

describe("method (the two choices)", () => {
  it.each<[string, WizardState, "browser" | "extension", "browser" | "extension"]>([
    ["Browser login to Extension", on(LOGIN), "extension", "extension"],
    ["Extension back to Browser login", on(LOGIN, { method: "extension" }), "browser", "browser"],
    ["Fansly: Browser login refused", on(LOGIN, { platform: "fansly", method: "extension" }), "browser", "extension"],
    ["off the sign-in: refused", on(ACC, { method: "browser" }), "extension", "browser"],
  ])("%s", (_, s, value, expected) => {
    expect(run(s, method(value)).method).toBe(expected);
  });
  it("an unchanged method returns the same state (refused)", () => {
    const s = on(LOGIN);
    expect(wizardReducer(s, method("browser"))).toBe(s);
  });
});

describe("platform (the small Fansly link)", () => {
  it.each<[string, WizardState, "onlyfans" | "fansly", string, string]>([
    ["to Fansly: the extension's session copy", on(LOGIN), "fansly", "fansly", "extension"],
    ["back to OnlyFans: Browser login first again", on(LOGIN, { platform: "fansly", method: "extension" }), "onlyfans", "onlyfans", "browser"],
    ["a taken platform: refused", on(LOGIN, { taken: ["fansly"] }), "fansly", "onlyfans", "browser"],
    ["a recovery: refused", on(LOGIN, { recovery: true }), "fansly", "onlyfans", "browser"],
    ["off the sign-in: refused", on(ACC), "fansly", "onlyfans", "browser"],
  ])("%s", (_, s, value, plat, m) => {
    expect(run(s, platform(value))).toMatchObject({ platform: plat, method: m });
  });
  it.each<[string, WizardState, "onlyfans" | "fansly", boolean]>([
    ["header, Fansly", on(LOGIN), "fansly", true],
    ["taken", on(LOGIN, { taken: ["fansly"] }), "fansly", false],
    ["recovery", on(LOGIN, { recovery: true }), "fansly", false],
    ["linked step", on(ACC), "fansly", false],
  ])("canPickPlatform: %s", (_, s, p, ok) => {
    expect(canPickPlatform(s, p)).toBe(ok);
  });
});

describe("linked", () => {
  it("from the sign-in", () => {
    expect(run(on(LOGIN, { busy: { login: true, extension: true, proxy: false } }), LINKED))
      .toMatchObject({ step: { kind: "linked", accountId: "of-1" }, busy: IDLE });
  });
  it.each<[string, WizardState]>([
    // A Browser login settling after the Extension linked another account must not replace it (or its typed details).
    ["a late sign-in for another account on the linked step", on(ACC)],
    ["the same account again on the linked step (keeps its details)", on({ ...ACC, accountId: "of-1", account: { ...ACCOUNT, nickname: "Typed" } })],
    ["while saving", on(ACC_SAVING)],
    ["after success", on(SUCCESS)],
    ["on details", on({ kind: "details" })],
  ])("refused (same state): %s", (_, s) => {
    expect(wizardReducer(s, LINKED)).toBe(s);
  });
  it("carries the account and its details, not busy", () => {
    expect(run(on(LOGIN), LINKED).step).toEqual({ kind: "linked", accountId: "of-1", account: ACCOUNT, busy: false });
  });
  it("takes the platform of the sign-in that linked (a Browser login finishing after a swap to Fansly)", () => {
    const s = run(on(LOGIN), platform("fansly"));
    expect(s.platform).toBe("fansly");
    expect(run(s, LINKED)).toMatchObject({ platform: "onlyfans", step: { kind: "linked", accountId: "of-1" } });
  });
  it("a save running keeps its account", () => {
    expect(run(on(ACC_SAVING), LINKED).step).toBe(ACC_SAVING);
  });
});

describe("profile (the OF read prefills the nickname)", () => {
  const BLANK: LinkedStep = { ...ACC, account: { ...ACCOUNT, nickname: "" } };
  const prof = (name: string, accountId = "a") => ({ type: "profile", accountId, name }) as const;
  const nick = (s: WizardState) => (s.step as LinkedStep).account.nickname;
  it.each<[string, WizardState, string, string]>([
    ["blank nickname: the OF name", on(BLANK), "Mia Rose", "Mia Rose"],
    ["whitespace-only nickname: the OF name, trimmed", on({ ...BLANK, account: { ...ACCOUNT, nickname: "  " } }), " Mia ", "Mia"],
    ["typed nickname kept", on(ACC), "Mia Rose", "Bella"],
    ["blank name: nothing", on(BLANK), "  ", ""],
  ])("%s", (_, s, name, expected) => {
    expect(nick(run(s, prof(name)))).toBe(expected);
  });
  it.each<[string, WizardState, WizardAction]>([
    ["another account's read", on(BLANK), prof("Mia", "other")],
    ["while saving", on({ ...BLANK, busy: true }), prof("Mia")],
    ["a recovery (no details)", on(BLANK, { recovery: true }), prof("Mia")],
    ["on the sign-in", on(LOGIN), prof("Mia")],
    ["after success", on(SUCCESS), prof("Mia")],
    ["a typed nickname", on(ACC), prof("Mia")],
  ])("refused (same state): %s", (_, s, a) => {
    expect(wizardReducer(s, a)).toBe(s);
  });
  it("a typed nickname after the prefill wins, and a later read does not clobber it", () => {
    const typed = { type: "setField", field: "account", value: { ...ACCOUNT, nickname: "Mimi" } } as const;
    expect(nick(run(on(BLANK), prof("Mia"), typed, prof("Mia Rose")))).toBe("Mimi");
  });
  it.each<[string, Parameters<typeof profileName>[0], string]>([
    ["display name", { name: " Mia Rose ", username: "miarose" }, "Mia Rose"],
    ["no display name: the username", { name: "", username: "miarose" }, "miarose"],
    ["neither", { name: null, username: null }, ""],
    ["no read", null, ""],
  ])("profileName: %s", (_, me, expected) => {
    expect(profileName(me)).toBe(expected);
  });
});

describe("account details + Done", () => {
  it("setField account edits the linked step, not while saving", () => {
    const edited = { ...ACCOUNT, tag: "vip" };
    const field = { type: "setField", field: "account", value: edited } as const;
    expect((run(on(ACC), field).step as LinkedStep).account).toEqual(edited);
    expect(run(on(ACC_SAVING), field).step).toBe(ACC_SAVING);
    expect(run(on(LOGIN), field).step).toEqual(LOGIN);
  });
  it.each<[string, WizardState, boolean]>([
    ["linked", on(ACC), true],
    ["linked, the proxy editor working", on(ACC, { busy: { ...IDLE, proxy: true } }), false],
    ["saving", on(ACC_SAVING), false],
    ["sign-in", on(LOGIN), false],
    ["success", on(SUCCESS), false],
  ])("canNext: %s", (_, s, ok) => {
    expect(canNext(s)).toBe(ok);
  });
  it.each<[string, WizardState, WizardAction[], WizardStep]>([
    ["Done saves (busy)", on(ACC), [START], ACC_SAVING],
    ["a second Done while saving: refused", on(ACC_SAVING), [START], ACC_SAVING],
    ["a recovery has nothing to save", on(ACC, { recovery: true }), [START], ACC],
    ["saved: success", on(ACC), [START, OK], SUCCESS],
    ["failed: back to editable", on(ACC), [START, ERR], ACC],
    ["submitOk without a save: ignored", on(ACC), [OK], ACC],
    ["submitErr without a save: ignored", on(ACC), [ERR], ACC],
    ["submitStart on the sign-in: ignored", on(LOGIN), [START], LOGIN],
  ])("%s", (_, s, actions, step) => {
    expect(run(s, ...actions).step).toEqual(step);
  });
  it("a refused action returns the very same state", () => {
    const s = on(ACC_SAVING);
    expect(wizardReducer(s, START)).toBe(s);
  });
  it.each<[string, WizardState, boolean]>([
    ["details", on({ kind: "details" }), true],
    ["sign-in, a Browser login running (unmount stops it)", on(LOGIN, { busy: { ...IDLE, login: true } }), true],
    ["sign-in, the Extension capturing or waiting on Retry / Continue", on(LOGIN, { busy: { ...IDLE, extension: true } }), false],
    ["linked", on(ACC), true],
    ["linked, the proxy editor working", on(ACC, { busy: { ...IDLE, proxy: true } }), false],
  ])("canClose: %s", (_, s, ok) => {
    expect(canClose(s)).toBe(ok);
  });
  it("Done waits for the proxy editor", () => {
    const s = on(ACC, { busy: { ...IDLE, proxy: true } });
    expect(wizardReducer(s, START)).toBe(s);
    expect(run(s, { type: "busy", source: "proxy", value: false }, START).step).toEqual(ACC_SAVING);
  });
  it.each(["login", "extension", "proxy"] as const)("busy %s: one source changes, an unchanged value is refused", (source) => {
    const s = on(LOGIN);
    expect(wizardReducer(s, { type: "busy", source, value: false })).toBe(s);
    expect(wizardReducer(s, { type: "busy", source, value: true }).busy).toEqual({ ...IDLE, [source]: true });
  });
});

describe("buildAccountPayload", () => {
  const roster = [{ id: 7, display_name: "Eve", account_ids: [] }] as never;
  it("a draft: the account, before \"\", the Creator details and draft", () => {
    expect(buildAccountPayload(on(ACC, { details: BELLA, draftId: "d1" }), ACC, roster)).toEqual({
      accountId: "a", before: "", roster, details: ACCOUNT, creator: BELLA, draftId: "d1",
    });
  });
  it("empty Creator details do not overwrite the profile", () => {
    expect(buildAccountPayload(on(ACC), ACC, roster).creator).toBeUndefined();
  });
  it.each<[string, string, string, string]>([
    ["typed nickname wins", "Bella", "Bella OF", "Bella"],
    ["blank: the account's own name", "  ", "Bella OF", "Bella OF"],
    ["blank, no name read: blank", "", "", ""],
  ])("nickname: %s", (_, typed, fallback, expected) => {
    const step = { ...ACC, account: { ...ACCOUNT, nickname: typed } };
    expect(buildAccountPayload(on(step), step, roster, fallback).details.nickname).toBe(expected);
  });
});

/** The component's dispatch: on the newest state, and true only when the wizard took the action. */
describe("useWizardReducer", () => {
  it("two submitStarts before a re-render: the first is taken, the second refused", () => {
    const { result } = renderHook(() => useWizardReducer({ draft: { ...BELLA, id: "d1" } }));
    const dispatch = result.current[1];
    act(() => { dispatch(LINKED); });
    const taken: boolean[] = [];
    // One act: no re-render between the two (a double-click's worst case).
    act(() => { taken.push(dispatch(START), dispatch(START)); });
    expect(taken).toEqual([true, false]);
    expect(result.current[0].step).toMatchObject({ kind: "linked", busy: true });
  });
  it("a refused method answers false and keeps the state", () => {
    const { result } = renderHook(() => useWizardReducer({ recovery: "fansly" }));
    const before = result.current[0];
    let took = true;
    act(() => { took = result.current[1](method("browser")); });
    expect(took).toBe(false);
    expect(result.current[0]).toBe(before);
  });
});
