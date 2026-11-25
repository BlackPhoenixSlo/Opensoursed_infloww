export type SignIn = "create" | "invite" | "existing";

export interface EmployeeFormValues {
  employeeId?: number;
  signIn: SignIn;
  name: string;
  username: string;
  password: string;
  role: string;
  groupId: string;
  accountIds: string[] | null;
}

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

export const picksNoCreators = (f: Pick<EmployeeFormValues, "accountIds">) => f.accountIds !== null && f.accountIds.length === 0;

export function canSaveEmployee(f: EmployeeFormValues): boolean {
  if (picksNoCreators(f)) return false;
  if (f.employeeId !== undefined) return f.name.trim() !== "";
  if (f.signIn === "invite") return true;
  return f.username.trim() !== "" && (f.signIn === "existing" || f.password.length >= 6);
}
