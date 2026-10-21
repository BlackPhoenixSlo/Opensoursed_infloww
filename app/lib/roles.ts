/**
 * The `roles` Settings blob and how an Employee's assignment reads, shared by Role Settings (its enforce count)
 * and Manage employees (its By role filter and Role column), so both read an assignment the same way.
 */

import { PAGE_HREFS, type PermissionRole } from "@/components/settings/PermissionEditor";
import { REVENUE_CARD_KEYS } from "@/lib/dashboardCards";
import { CHATTER_OPT_IN_PAGES } from "@/lib/nav";

/** `assignments` maps an Employee id to a role id; absent until the first assignment is saved. `enforce` is the
 *  "Enforce role permissions" switch: on unless stored false (absent reads on, as the Relay reads it). */
export type RolesBlob = { roles: PermissionRole[]; assignments?: Record<string, string>; enforce?: boolean };

export const allPages = (allowed: boolean) => Object.fromEntries(PAGE_HREFS.map((href) => [href, allowed]));

/** The built-ins grant every page but My Automations (`CHATTER_OPT_IN_PAGES`), off for chatters until a role
 *  is stored with them ticked; the Relay grants an unstored built-in none of them either. */
const builtInPages = () => ({ ...allPages(true), ...Object.fromEntries([...CHATTER_OPT_IN_PAGES].map((h) => [h, false])) });

/** A built-in that grants only `pages` (the Relay's settings_schema.BUILT_IN_ROLE_DEFAULTS, kept in step). */
const only = (pages: readonly string[]) => ({ ...allPages(false), ...Object.fromEntries(pages.map((h) => [h, true])) });
// "/messages-pro" opens Focus too (nav.ts `permission`): no page of its own to grant.
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
  // Its Dashboard hides the revenue cards (the Relay's permissions._role, kept in step).
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

/** The built-ins first (stored when the blob has them, else the defaults above), then the custom roles. */
export function withBuiltIns(stored: PermissionRole[]): PermissionRole[] {
  const builtIns = BUILT_INS.map((b) => stored.find((r) => r.id === b.id) ?? b);
  return [...builtIns, ...stored.filter((r) => !isBuiltIn(r.id))];
}

/** An Employee's assigned role; the stored role id when no role has it; undefined when unassigned. Only a role
 *  (an object) counts as holding one: the Relay refuses an unknown id every page, as it does no role. */
export function assignedRole(
  roles: PermissionRole[], assignments: Record<string, string>, employeeId: number | string,
): PermissionRole | string | undefined {
  const roleId = assignments[String(employeeId)];
  if (roleId === undefined) return undefined;
  return roles.find((r) => r.id === roleId) ?? roleId;
}

/** The label for an assignment naming a role id no role has. */
export const unknownRoleLabel = (roleId: string) => `Unknown role (${roleId})`;
