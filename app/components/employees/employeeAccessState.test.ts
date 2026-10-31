import { describe, expect, it } from "vitest";

import {
  accountsInvalid, buildPayload, canSubmit, employeeAccessReducer, foldersInvalid, seedEmployeeAccess,
  visibleAccountIds, type AccessResp, type EmployeeAccessAction, type EmployeeAccessState,
} from "./employeeAccessState";

const A = "100000001";
const B = "100000002";
const C = "100000003";
const OWNER = [A, B, C];
const DATA: AccessResp = { account_ids: [A, B], folder_access: { [A]: [11, 12], [B]: [] } };

const run = (actions: EmployeeAccessAction[], from: EmployeeAccessState): EmployeeAccessState =>
  actions.reduce(employeeAccessReducer, from);
const loaded = (data = DATA) => seedEmployeeAccess(data);

describe("seedEmployeeAccess", () => {
  it("seeds the draft from the server payload", () => {
    const s = loaded();
    expect(s.limitModels).toBe(true);
    expect([...s.selectedAccounts]).toEqual([A, B]);
    expect(s.folders[A]).toEqual({
      limit: true, grants: [{ folder_id: 11, folder_name: null }, { folder_id: 12, folder_name: null }],
    });
    expect(s.folders[B]).toEqual({ limit: false, grants: [] });
    expect([s.savedAt, s.saveErr]).toEqual([null, null]);
  });

  it("no account_ids = Limit models off", () => {
    const s = loaded({ account_ids: [], folder_access: {} });
    expect(s.limitModels).toBe(false);
    expect(s.selectedAccounts.size).toBe(0);
  });
});

describe("edits and the save verdict", () => {
  const saved = run([{ type: "saveStart" }, { type: "saveOk", at: 42 }], loaded());

  it.each<[string, EmployeeAccessAction]>([
    ["limitModels", { type: "limitModels", on: false }],
    ["toggleAccount", { type: "toggleAccount", id: C, on: true }],
    ["folder", { type: "folder", accountId: C, entry: { limit: true, grants: [] } }],
  ])("%s clears savedAt", (_name, a) => {
    expect(saved.savedAt).toBe(42);
    expect(employeeAccessReducer(saved, a).savedAt).toBeNull();
  });

  it("toggleAccount adds and removes", () => {
    const s = run([{ type: "toggleAccount", id: C, on: true }, { type: "toggleAccount", id: A, on: false }], loaded());
    expect([...s.selectedAccounts].sort()).toEqual([B, C]);
  });

  it("saveOk clears a prior error; saveErr clears a prior Saved.", () => {
    const failed = run([{ type: "saveErr", msg: "boom" }], saved);
    expect([failed.savedAt, failed.saveErr]).toEqual([null, "boom"]);
    const ok = run([{ type: "saveStart" }, { type: "saveOk", at: 7 }], failed);
    expect([ok.savedAt, ok.saveErr]).toEqual([7, null]);
  });
});

describe("an edit while a save is in flight", () => {
  const edit: EmployeeAccessAction = { type: "toggleAccount", id: C, on: true };

  it.each<[string, EmployeeAccessAction[], number | null, string | null]>([
    ["no mid-flight edit → Saved.", [{ type: "saveStart" }, { type: "saveOk", at: 5 }], 5, null],
    ["edit before saveStart → Saved.", [edit, { type: "saveStart" }, { type: "saveOk", at: 5 }], 5, null],
    ["mid-flight edit → no Saved.", [{ type: "saveStart" }, edit, { type: "saveOk", at: 5 }], null, null],
    ["re-save after it → Saved.", [{ type: "saveStart" }, edit, { type: "saveOk", at: 5 },
      { type: "saveStart" }, { type: "saveOk", at: 6 }], 6, null],
    ["saveErr still clears Saved.", [{ type: "saveStart" }, { type: "saveOk", at: 5 },
      { type: "saveStart" }, { type: "saveErr", msg: "boom" }], null, "boom"],
  ])("%s", (_name, actions, savedAt, saveErr) => {
    const s = run(actions, loaded());
    expect([s.savedAt, s.saveErr]).toEqual([savedAt, saveErr]);
  });
});

describe("visibleAccountIds", () => {
  it.each<[string, EmployeeAccessAction[], string[]]>([
    ["limit on → picked, in owner order", [{ type: "toggleAccount", id: A, on: false }, { type: "toggleAccount", id: A, on: true }], [A, B]],
    ["limit off → all owner accounts", [{ type: "limitModels", on: false }], OWNER],
    ["picks not owned are ignored", [{ type: "toggleAccount", id: "999", on: true }], [A, B]],
  ])("%s", (_name, actions, want) => {
    expect(visibleAccountIds(run(actions, loaded()), OWNER)).toEqual(want);
  });
});

describe("canSubmit (DA-2)", () => {
  it.each<[string, EmployeeAccessAction[], boolean, boolean]>([
    ["as loaded", [], false, false],
    ["limit on, nothing picked", [
      { type: "toggleAccount", id: A, on: false }, { type: "toggleAccount", id: B, on: false }], true, false],
    ["limit off, nothing picked", [
      { type: "toggleAccount", id: A, on: false }, { type: "toggleAccount", id: B, on: false },
      { type: "limitModels", on: false }], false, false],
    ["visible folder limit with no grants", [
      { type: "folder", accountId: B, entry: { limit: true, grants: [] } }], false, true],
    ["hidden account's empty folder limit does not block", [
      { type: "folder", accountId: C, entry: { limit: true, grants: [] } }], false, false],
    ["…until the account becomes visible", [
      { type: "folder", accountId: C, entry: { limit: true, grants: [] } }, { type: "limitModels", on: false }],
      false, true],
  ])("%s", (_name, actions, accBad, folderBad) => {
    const s = run(actions, loaded());
    expect(accountsInvalid(s)).toBe(accBad);
    expect(foldersInvalid(s, OWNER)).toBe(folderBad);
    expect(canSubmit(s, OWNER)).toBe(!accBad && !folderBad);
  });
});

describe("buildPayload", () => {
  const G11 = { folder_id: 11, folder_name: null };
  const G12 = { folder_id: 12, folder_name: null };

  it.each<[string, EmployeeAccessAction[], string[], [string, unknown[]][]]>([
    ["as loaded", [], [A, B], [[A, [G11, G12]], [B, []], [C, []]]],
    ["limit off sends [] accounts, keeps folder grants", [{ type: "limitModels", on: false }], [],
      [[A, [G11, G12]], [B, []], [C, []]]],
    ["de-selected account's folder grants are cleared", [{ type: "toggleAccount", id: A, on: false }], [B],
      [[A, []], [B, []], [C, []]]],
    ["folder limit off sends [] even with grants", [
      { type: "folder", accountId: A, entry: { limit: false, grants: [G11] } }], [A, B],
      [[A, []], [B, []], [C, []]]],
  ])("%s", (_name, actions, accountIds, folders) => {
    const p = buildPayload(run(actions, loaded()), OWNER);
    expect(p.accounts.account_ids).toEqual(accountIds);
    expect(p.folders.map((f) => [f.account_id, f.folders])).toEqual(folders);
  });
});
