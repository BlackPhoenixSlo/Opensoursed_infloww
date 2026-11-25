import { PAGE_HREFS, type PermissionRole } from "@/components/settings/PermissionEditor";
import { REVENUE_CARD_KEYS } from "@/lib/dashboardCards";
import { CHATTER_OPT_IN_PAGES } from "@/lib/nav";

export type RolesBlob = { roles: PermissionRole[]; assignments?: Record<string, string>; enforce?: boolean };

export const allPages = (allowed: boolean) => Object.fromEntries(PAGE_HREFS.map((href) => [href, allowed]));

const builtInPages = () => ({ ...allPages(true), ...Object.fromEntries([...CHATTER_OPT_IN_PAGES].map((h) => [h, false])) });

const only = (pages: readonly string[]) => ({ ...allPages(false), ...Object.fromEntries(pages.map((h) => [h, true])) });
const CHATTING = [
  "/messages-pro", "/of-manager/messages", "/of-manager/notifications", "/growth/scripts", "/growth/get-to-know-fans",
];

/** Owner, Admin, Team Leader, Chatter, Creator: Infloww's live default roles (w5-a), no Delete, fixed names. */
const BUILT_INS: PermissionRole[] = [
  { id: "owner", name: "Owner", description: "", permissions: builtInPages(), scope: "all" },
  { id: "admin", name: "Admin", description: "", permissions: builtInPages(), scope: "all" },
  {
    id: "team-leader", name: "Team Leader", description: "", scope: "subordinates",
    permissions: only([
      "/", ...CHATTING, "/growth/smart-messages", "/of-manager/home", "/of-manager/vault", "/creators",
      "/creators/proxy", "/employees", "/employees/shifts", "/analytics/creator-reports",
      "/analytics/employee-reports", "/analytics/message-dashboard", "/analytics/sales-records",
    ]),
  },
  {
    id: "chatter", name: "Chatter", description: "", scope: "self",
    permissions: { ...only(["/", ...CHATTING]), ...Object.fromEntries(REVENUE_CARD_KEYS.map((k) => [k, false])) },
  },
  {
    id: "creator", name: "Creator", description: "", scope: "self",
    permissions: only([
      "/of-manager/home", "/of-manager/new-post", "/of-manager/vault", "/of-manager/queue",
      "/of-manager/collections", "/of-manager/collections/bookmarks/all", "/of-manager/profile", "/of-manager/release-forms",
      "/growth/vault-pro",
    ]),
  },
];

export const isBuiltIn = (id: string) => BUILT_INS.some((b) => b.id === id);

export function withBuiltIns(stored: PermissionRole[]): PermissionRole[] {
  const builtIns = BUILT_INS.map((b) => stored.find((r) => r.id === b.id) ?? b);
  return [...builtIns, ...stored.filter((r) => !isBuiltIn(r.id))];
}

// Only a role object counts as held: the Relay refuses an unknown id every page, as it does no role.
export function assignedRole(
  roles: PermissionRole[], assignments: Record<string, string>, employeeId: number | string,
): PermissionRole | string | undefined {
  const roleId = assignments[String(employeeId)];
  if (roleId === undefined) return undefined;
  return roles.find((r) => r.id === roleId) ?? roleId;
}

export const unknownRoleLabel = (roleId: string) => `Unknown role (${roleId})`;
