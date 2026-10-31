/**
 * "+ Add employee" / "Edit": the form's values → the one Relay call that saves them, and whether Save is on.
 * Pure, so each sign-in mode's wire shape is pinned by a table test (employeeRequest.test.ts).
 *
 *   kind     form             call (setup = PUT, rest POST)
 *   • setup  edit             /admin/employees/{id}/setup   setup                       (employees.EmployeeSetup)
 *   • login  create           /admin/employees/login        setup + username + password (employees._CreateLoginBody)
 *   • link   existing         /admin/chatters/link          setup + username            (chatters._LinkBody)
 *   • invite invite           /admin/chatters/invite        setup                       (chatters._InviteBody)
 */

export type SignIn = "create" | "invite" | "existing";

export interface EmployeeFormValues {
  /** The row being edited; absent when adding. */
  employeeId?: number;
  signIn: SignIn;
  name: string;
  username: string;
  password: string;
  role: string;
  /** The Group select's value ("" = no group). */
  groupId: string;
  /** null = every Creator. */
  accountIds: string[] | null;
}

/** employees.EmployeeSetup: what every call carries. */
export interface EmployeeSetup {
  display_name: string | null;
  role_id: string | null;
  account_ids: string[] | null;
  group_id: number | null;
}

export type EmployeeRequest =
  | { kind: "setup"; path: string; body: EmployeeSetup }
  | { kind: "login"; path: string; body: EmployeeSetup & { username: string; password: string } }
  | { kind: "link"; path: string; body: EmployeeSetup & { username: string } }
  | { kind: "invite"; path: string; body: EmployeeSetup };

export function buildEmployeeRequest(f: EmployeeFormValues): EmployeeRequest {
  const setup: EmployeeSetup = {
    display_name: f.name.trim() || null,
    role_id: f.role || null,
    account_ids: f.accountIds && f.accountIds.length > 0 ? f.accountIds : null,
    group_id: f.groupId ? Number(f.groupId) : null,
  };
  if (f.employeeId !== undefined) return { kind: "setup", path: `/admin/employees/${f.employeeId}/setup`, body: setup };
  const username = f.username.trim().toLowerCase();
  switch (f.signIn) {
    case "create": return { kind: "login", path: "/admin/employees/login", body: { ...setup, username, password: f.password } };
    case "existing": return { kind: "link", path: "/admin/chatters/link", body: { ...setup, username } };
    case "invite": return { kind: "invite", path: "/admin/chatters/invite", body: setup };
  }
}

/** Ticked "no creators" (an empty pick, not All creators). */
export const picksNoCreators = (f: Pick<EmployeeFormValues, "accountIds">) => f.accountIds !== null && f.accountIds.length === 0;

export function canSaveEmployee(f: EmployeeFormValues): boolean {
  if (picksNoCreators(f)) return false;
  if (f.employeeId !== undefined) return f.name.trim() !== "";
  if (f.signIn === "invite") return true;
  return f.username.trim() !== "" && (f.signIn === "existing" || f.password.length >= 6);
}
