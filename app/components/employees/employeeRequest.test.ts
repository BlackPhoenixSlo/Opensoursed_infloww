import { describe, expect, it } from "vitest";

import { buildEmployeeRequest, canSaveEmployee, type EmployeeFormValues } from "@/components/employees/employeeRequest";

const F: EmployeeFormValues = {
  signIn: "create",
  name: "  Ana  ",
  username: "  Ana.B ",
  password: "secret1",
  role: "manager",
  groupId: "7",
  accountIds: ["a1", "a2"],
};
const SETUP = { display_name: "Ana", role_id: "manager", account_ids: ["a1", "a2"], group_id: 7 };

describe("buildEmployeeRequest", () => {
  it.each<[string, Partial<EmployeeFormValues>, ReturnType<typeof buildEmployeeRequest>]>([
    ["create", { signIn: "create" },
      { kind: "login", path: "/admin/employees/login", body: { ...SETUP, username: "ana.b", password: "secret1" } }],
    ["existing", { signIn: "existing" },
      { kind: "link", path: "/admin/chatters/link", body: { ...SETUP, username: "ana.b" } }],
    ["invite", { signIn: "invite" },
      { kind: "invite", path: "/admin/chatters/invite", body: SETUP }],
    ["edit (signIn ignored)", { employeeId: 42, signIn: "create" },
      { kind: "setup", path: "/admin/employees/42/setup", body: SETUP }],
  ])("%s", (_, over, want) => {
    expect(buildEmployeeRequest({ ...F, ...over })).toEqual(want);
  });

  it("blanks become null: no name, role, group, and All creators", () => {
    const req = buildEmployeeRequest({ ...F, signIn: "invite", name: " ", role: "", groupId: "", accountIds: null });
    expect(req.body).toEqual({ display_name: null, role_id: null, account_ids: null, group_id: null });
  });
});

describe("canSaveEmployee", () => {
  it.each<[string, Partial<EmployeeFormValues>, boolean]>([
    ["create ok", { signIn: "create" }, true],
    ["create short password", { signIn: "create", password: "12345" }, false],
    ["create no username", { signIn: "create", username: " " }, false],
    ["existing needs no password", { signIn: "existing", password: "" }, true],
    ["existing no username", { signIn: "existing", username: "" }, false],
    ["invite needs nothing", { signIn: "invite", username: "", password: "" }, true],
    ["empty creator pick blocks", { signIn: "invite", accountIds: [] }, false],
    ["All creators ok", { signIn: "invite", accountIds: null }, true],
    ["edit ok", { employeeId: 1, username: "", password: "" }, true],
    ["edit needs a name", { employeeId: 1, name: " " }, false],
    ["edit empty creator pick blocks", { employeeId: 1, accountIds: [] }, false],
  ])("%s", (_, over, want) => {
    expect(canSaveEmployee({ ...F, ...over })).toBe(want);
  });
});
