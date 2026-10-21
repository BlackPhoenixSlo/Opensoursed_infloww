"use client";

/**
 * Employees > "Manage employees" (`/employees`): Infloww's `EmployeeListPage`, the group tree on the left and the
 * Employees (people with their own login, role and permissions) on the right (see EmployeesTab). There is one
 * concept, Employee, as in Infloww: an Employee IS a login. The Organization Chart is not a tab: its tree is the
 * page's left column (GroupTree), and `/employees/org-chart` redirects here. Owner-only; the relay 403s these
 * endpoints for an employee session, this just says so.
 */

import EmployeesTab from "@/components/settings/EmployeesTab";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";

export default function ManageEmployees() {
  const { user } = useUser();
  const { chatter } = useChatter();

  if (!user) return chatter ? <p className="p-4 text-sm text-fg-dim">Only the agency owner can manage employees.</p> : null;
  return <EmployeesTab />;
}
