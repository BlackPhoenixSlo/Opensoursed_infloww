"use client";

/**
 * EmployeesTab — Manage employees, laid out as Infloww's `EmployeeListPage` (bundle `index.9f50f370.js` @12350186,
 * CSS `_9ql8v`; the parity doc docs/infloww-screens.md §3.8). An Employee is a person with their own login (a
 * `chatter` in the code and the Relay), so their role, Creator access and Data scope are enforced on them. The owner's
 * own row heads the list (role Owner, nothing to edit). The retired name-only rows (`kind: "name"`, the old "Who's
 * chatting?" names) are not shown; their history stays on the Relay.
 *
 * Frame, full bleed under the page header: the group tree (GroupTree) in a 260px #262626 column on the left, the list
 * on #151515 on the right. Picking a tree node filters the list to that group (the root, the Agency, is every group);
 * on a phone the tree folds into a group select above the filters.
 *
 * Title row: the picked node's name with the counts (our extra), "Manage roles & permissions →" (Role Settings, where
 * the Admin / Manager / Chatter / VA presets are edited; our extra), "Batch actions" (outlined; with nobody selected
 * it warns "Select at least one employee", as Infloww does) and "+ Add employee". One line of labelled filters: By
 * employee, By Creator, By status (Activated / Deactivated / Pending), By role (our extra), Reset; they apply as you
 * type, so there is no Search button.
 *
 * Pending invites (GET /admin/chatters/invites) follow the logins, as Infloww's pending employee: name, Creators and
 * role from the invite's setup, status "Inactive" with "Resend" (a fresh link, the old one stops working;
 * POST …/invites/{token}/resend) and the action "Delete" (revokes it; DELETE …/invites/{token}).
 *
 * Table (fixed layout, on Infloww's antd table): Employee (name and @username), Assigned Creators (click: Edit; "+
 * Assign" when none), Role (click: Set role), Status, Group (from xl up), This month (recorded earnings, then worked
 * of scheduled shifts, from the Shift schedule's Timesheet in the Agency's time zone), Actions "Edit  More". A
 * deactivated row's cells are grey, not links. More opens in a portal: Reset password, Access limits, Deactivate /
 * Activate, Delete (off: an Employee is deactivated, never deleted, so their audit history is kept). Over ten rows a
 * pager shows ten a page.
 *
 * Writes:
 *   • + Add employee / Edit (EmployeeFormModal): POST /admin/employees/login, POST /admin/chatters/invite,
 *     POST /admin/chatters/link, PUT /admin/employees/{id}/setup — name, role, Creators and group in one go
 *   • Set role (RoleModal): PUT /admin/employees/{id}/setup with the role alone
 *   • Reset password: POST /admin/employees/{id}/password (owner-only; refused for a login another Agency shares)
 *   • Deactivate: DELETE /admin/employees/{id} (unlinks the login; history kept); Activate: PATCH is_active
 *   • Batch edit roles: one PUT /admin/settings/roles carrying the whole blob (ADR-0007); Assign: PUT
 *     /admin/employees/{id}/access per Employee; Batch edit group: PUT /admin/employee-groups/members
 *
 * Changing the group or a filter clears the selection, so a batch never writes a row the list hides.
 *
 * ASSUMPTION: Reset password sets the new password directly, where Infloww mails reset instructions (no email on
 * file here). Rung 5. Overturned when Employees carry an email address.
 *
 * ASSUMPTION: earnings and both shift counts share one "This month" column, so the list fits 1440px with the tree.
 * Rung 6: Infloww's list has no shift columns at all. Overturned if the owner wants them apart again.
 *
 * ASSUMPTION: By role's "No role" also matches an assignment naming a role id no role has, which the Role column
 * shows as "Unknown role (<id>)". Rung 3: Role Settings counts it as no role and the Relay refuses it every page.
 *
 * ASSUMPTION: Select all ticks the shown page's rows, as antd's row selection does; a row ticked on another page
 * stays ticked. Rung 3 (antd's default). Overturned if the owner wants Select all to span every page.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Plus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/primitives";
import { EmptyState, IfButton, IfInput, IfPager, IfSelect, IF_TABLE, type IfOption } from "@/components/ui/infloww";
import { GateNoteText, type GateNote } from "@/components/settings/StickySaveBar";
import type { PermissionRole } from "@/components/settings/PermissionEditor";
import {
  AccessLimitsModal, EmployeeFormModal, InviteLinkModal, ManageRolesLink, Modal, ResetPasswordModal, RoleModal, RowMenu,
  type InviteResp,
} from "@/components/employees/EmployeeModals";
import GroupTree, { useAgencyName } from "@/components/employees/GroupTree";
import EmployeeLimitModal, { isEmployeeLimit } from "@/components/settings/EmployeeLimitModal";
import { relay, type AccountMeta, type Employee } from "@/lib/relay";
import { GROUPS_KEY, groupsInTreeOrder, useEmployeeGroups, type EmployeeGroup } from "@/lib/employeeGroups";
import { useRoster } from "@/hooks/useRoster";
import { useAccounts } from "@/hooks/useAccounts";
import { useSettingsBlob } from "@/lib/settingsBlob";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { monthRange } from "@/lib/dateRange";
import { fmtCents } from "@/lib/format";
import { RECORDED_EARNINGS_TIP, useTimesheet, type TimesheetRow } from "@/lib/shifts";
import { assignedRole, unknownRoleLabel, withBuiltIns, type RolesBlob } from "@/lib/roles";
import { cn } from "@/lib/utils";

/** The four filters; "" is each select's "All" option. "pending" is the invites not accepted yet. */
type Filters = { name: string; creator: string; status: "" | "active" | "inactive" | "pending"; role: string };
const NO_FILTERS: Filters = { name: "", creator: "", status: "", role: "" };
/** The By role option for an Employee holding no role. */
const NO_ROLE = "\u0000none";
/** Rows a page (Infloww: 10, no size changer); the pager shows only past one page. */
const PAGE_SIZE = 10;
/** The phone group select's value for the tree root (every group). */
const ROOT = "root";

type HeldRole = ReturnType<typeof assignedRole>;
const isOwner = (e: Employee) => e.kind === "owner";

/** Whether `e` passes every filter. All Creators access matches every Creator. A role id no role has counts as
 *  no role, as Role Settings counts it and the Relay refuses it every page. */
function passes(e: Employee, f: Filters, roleOf: (e: Employee) => HeldRole): boolean {
  const q = f.name.trim().toLowerCase();
  if (q && !e.display_name.toLowerCase().includes(q) && !(e.username ?? "").toLowerCase().includes(q)) return false;
  if (f.creator && e.account_ids != null && !e.account_ids.includes(f.creator)) return false;
  if (f.status === "pending") return false;
  if (f.status && e.is_active !== (f.status === "active")) return false;
  if (f.role) {
    const role = roleOf(e);
    const held = typeof role === "object" ? role : undefined;
    if (f.role === NO_ROLE ? held !== undefined : held?.id !== f.role) return false;
  }
  return true;
}

/** An invite not accepted yet (GET /admin/chatters/invites), listed as Infloww's pending employee: "Inactive". */
export interface PendingInvite extends InviteResp {
  created_at: string;
  display_name: string | null;
  role_id: string | null;
  account_ids: string[] | null;
  group_id: number | null;
}
export const INVITES_KEY = ["employees", "invites"];

/** Whether a pending invite passes the filters: only All or Pending status, and its setup's name, Creators and role. */
function invitePasses(i: PendingInvite, f: Filters, roles: PermissionRole[]): boolean {
  if (f.status && f.status !== "pending") return false;
  const q = f.name.trim().toLowerCase();
  if (q && !(i.display_name ?? "").toLowerCase().includes(q)) return false;
  if (f.creator && i.account_ids != null && !i.account_ids.includes(f.creator)) return false;
  if (f.role) {
    const held = roles.find((r) => r.id === i.role_id);
    if (f.role === NO_ROLE ? held !== undefined : held?.id !== f.role) return false;
  }
  return true;
}

/** The Batch dialogs' native selects. */
const FILTER = "h-8 min-w-0 bg-bg border border-border rounded-md px-2 text-sm focus:outline-none focus:border-accent";
/** A labelled filter: 14px T2 label with its colon, 8px to the field. */
const FILTER_LABEL = "flex items-center gap-2 text-[14px] text-fg-dim whitespace-nowrap";
const TH = cn(IF_TABLE.th, IF_TABLE.thDivider);
/** Infloww's link colour in the table (Assigned Creators, Role) and the warn / ok status colours (sampled). */
const LINK = "text-[#2d74ff] hover:opacity-80";
const GREY = "text-muted";
/** The Group column, from xl up. */
const XL_CELL = "hidden xl:table-cell";

/** The Assigned Creators cell's text: every Creator, none (""), or the granted Creators' names. */
function assignedCreators(ids: string[] | null | undefined, creators: AccountMeta[]): string {
  if (ids == null) return "All Creators";
  return ids.map((id) => {
    const c = creators.find((a) => a.id === id);
    return c?.nickname || c?.name || id;
  }).join(", ");
}

const MONTH_TIP = `Recorded earnings, then shifts worked of shifts scheduled, this calendar month. ${RECORDED_EARNINGS_TIP}`;

/** The This month cell: earnings and worked/scheduled shifts, "—" until the Timesheet answers. */
function monthCell(sheet: TimesheetRow[] | undefined, id: number): { earnings: string; shifts: string } {
  if (!sheet) return { earnings: "—", shifts: "" };
  const r = sheet.find((row) => row.key === String(id));
  return { earnings: fmtCents(r?.recorded_earnings_cents ?? 0), shifts: `${r?.shifts_worked ?? 0}/${r?.scheduled_shifts ?? 0} shifts` };
}

/** The Role cell: the assigned role's name, "" for none, or the stored id no role has (as Role Settings shows it). */
function roleLabel(role: HeldRole): string {
  if (role === undefined) return "";
  return typeof role === "string" ? unknownRoleLabel(role) : role.name;
}

/** A link cell (Assigned Creators, Role): the text in Infloww's blue, two lines at most, or "+ Assign" when empty;
 *  grey plain text when the row is not editable (the owner's own, a deactivated one). */
function LinkCell({ text, editable, onClick, title }: { text: string; editable: boolean; onClick: () => void; title: string }) {
  if (!editable) return <span className={cn(GREY, "line-clamp-2")} title={text || undefined}>{text || "—"}</span>;
  if (!text) {
    return (
      <button type="button" onClick={onClick} title={title} className={cn(LINK, "inline-flex items-center gap-1")}>
        <Plus aria-hidden className="h-3.5 w-3.5" />Assign
      </button>
    );
  }
  return (
    <button type="button" onClick={onClick} title={`${title}: ${text}`} className={cn(LINK, "line-clamp-2 text-left")}>
      {text}
    </button>
  );
}

/** antd's `message.warning`: a #4d5159 pill at the top centre for three seconds. */
function useWarning(): [ReactNode, (text: string) => void] {
  const [note, setNote] = useState<{ text: string; at: number } | null>(null);
  useEffect(() => {
    if (!note) return;
    const t = setTimeout(() => setNote(null), 3000);
    return () => clearTimeout(t);
  }, [note]);
  const node = note && (
    <div role="status" className={cn(
      "fixed left-1/2 top-[calc(var(--chrome-top)+8px)] z-[60] flex -translate-x-1/2 items-center gap-2 rounded-lg",
      "bg-[#4d5159] px-3 py-[9px] text-[14px] text-fg shadow-lg [html[data-theme=light]_&]:bg-white",
    )}>
      <CircleAlert aria-hidden className="h-4 w-4 text-[#faad14]" />
      {note.text}
    </div>
  );
  return [node, (text) => setNote({ text, at: Date.now() })];
}

type Line = { kind: "employee"; e: Employee } | { kind: "invite"; i: PendingInvite };

export default function EmployeesTab() {
  const qc = useQueryClient();

  // Every row, so the owner's own heads the list; the retired name-only rows are dropped.
  const { query: q, rows: all } = useRoster({ includeChatterMirrors: true });
  const owner = all.find(isOwner);
  const logins = all.filter((e) => e.kind === "login" || (e.kind === undefined && !!e.chatter_id));
  const creators = useAccounts().data?.accounts ?? [];
  const rolesBlob = useSettingsBlob<RolesBlob>("roles", { roles: [] });
  const roles = withBuiltIns(rolesBlob.value.roles);
  const assignments = rolesBlob.value.assignments ?? {};
  const agencyName = useAgencyName();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [page, setPage] = useState(1);
  const groupTree = groupsInTreeOrder(useEmployeeGroups().data?.groups ?? []);
  const groupList = groupTree.map((g) => g.group);
  /** The tree's group, or null for the root (every group). A group deleted meanwhile falls back to the root. */
  const [pickedId, setPickedId] = useState<number | null>(null);
  const picked = groupList.find((g) => g.id === pickedId);
  const groupId = picked ? picked.id : null;
  const groupName = (id: number | null | undefined) => groupList.find((g) => g.id === id)?.name ?? "—";
  const clearSelection = () => { setSelected(new Set()); setPage(1); };
  const pickGroup = (id: number | null) => { setPickedId(id); clearSelection(); };
  const filter = (patch: Partial<Filters>) => { setFilters((f) => ({ ...f, ...patch })); clearSelection(); };
  const [warning, warn] = useWarning();

  const roleOf = (e: Employee): HeldRole =>
    isOwner(e) ? roles.find((r) => r.id === "owner") : assignedRole(roles, assignments, e.id);
  const roleIdOf = (e: Employee) => { const r = roleOf(e); return typeof r === "object" ? r.id : ""; };
  const listed = owner ? [owner, ...logins] : logins;
  const shown = listed.filter((e) => (groupId === null || e.group_id === groupId) && passes(e, filters, roleOf));
  const toggleSelected = (id: number) => setSelected((s) => {
    const next = new Set(s);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const targets = shown.filter((e) => !isOwner(e) && selected.has(e.id));
  const [batch, setBatch] = useState<BatchAction | null>(null);
  const closeBatch = () => { setBatch(null); clearSelection(); };

  // The modals: at most one open, on one row.
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [roleFor, setRoleFor] = useState<Employee | null>(null);
  const [passwordFor, setPasswordFor] = useState<Employee | null>(null);
  const [accessFor, setAccessFor] = useState<Employee | null>(null);

  const invitesQ = useQuery<PendingInvite[]>({
    queryKey: INVITES_KEY,
    queryFn: () => relay.get<PendingInvite[]>("/admin/chatters/invites"),
    staleTime: 10_000,
  });
  const invites = (invitesQ.data ?? []).filter((i) => (groupId === null || i.group_id === groupId)
    && invitePasses(i, filters, roles));
  const [resent, setResent] = useState<InviteResp | null>(null);
  const resendM = useMutation({
    mutationFn: (token: string) => relay.post<InviteResp>(`/admin/chatters/invites/${encodeURIComponent(token)}/resend`, {}),
    onSuccess: (fresh) => { setResent(fresh); void qc.invalidateQueries({ queryKey: INVITES_KEY }); },
  });
  const revokeM = useMutation({
    mutationFn: (token: string) => relay.delete<unknown>(`/admin/chatters/invites/${encodeURIComponent(token)}`),
    onSettled: () => qc.invalidateQueries({ queryKey: INVITES_KEY }),
  });

  // Ten a page, the logins then the invites.
  const lines: Line[] = [
    ...shown.map((e): Line => ({ kind: "employee", e })),
    ...invites.map((i): Line => ({ kind: "invite", i })),
  ];
  const pageAt = Math.min(page, Math.max(1, Math.ceil(lines.length / PAGE_SIZE)));
  const pageLines = lines.slice((pageAt - 1) * PAGE_SIZE, pageAt * PAGE_SIZE);
  const selectable = pageLines.flatMap((l) => (l.kind === "employee" && !isOwner(l.e) ? [l.e] : []));
  const allTicked = selectable.length > 0 && selectable.every((e) => selected.has(e.id));
  const tickAll = () => setSelected((s) => {
    const next = new Set(s);
    for (const e of selectable) {
      if (allTicked) next.delete(e.id);
      else next.add(e.id);
    }
    return next;
  });

  const applied = useAppliedSettings();
  const [monthStart, monthEnd] = monthRange(applied.data?.preferences?.tz ?? null);
  const sheet = useTimesheet(monthStart, monthEnd, "employee", !applied.isPending).data?.rows;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["employees"] });
  const assignM = useMutation({
    mutationFn: (args: { ids: number[]; accountIds: string[] }) => Promise.all(args.ids.map((id) =>
      relay.put<unknown>(`/admin/employees/${id}/access`, { account_ids: args.accountIds }))),
    onSuccess: () => { closeBatch(); void invalidate(); },
    onError: () => invalidate(),
  });
  const groupM = useMutation({
    mutationFn: (args: { groupId: number | null; ids: number[] }) =>
      relay.put<unknown>("/admin/employee-groups/members", { group_id: args.groupId, employee_ids: args.ids }),
    onSuccess: () => {
      closeBatch();
      void invalidate();
      void qc.invalidateQueries({ queryKey: GROUPS_KEY });
    },
  });
  const activateM = useMutation({
    mutationFn: (id: number) => relay.patch<Employee>(`/admin/employees/${id}`, { is_active: true }),
    onSettled: () => invalidate(),
  });
  const disableM = useMutation({
    mutationFn: (id: number) => relay.delete<unknown>(`/admin/employees/${id}`),
    onSettled: () => invalidate(),
  });
  // The employee cap is a modal (EmployeeLimitModal), not the error line.
  const activateError = isEmployeeLimit(activateM.error) ? null : activateM.error;
  const saveError = (activateError || disableM.error || resendM.error || revokeM.error) as Error | null;

  const active = logins.filter((e) => e.is_active).length;
  const creatorOptions: IfOption[] = [
    { value: "", label: "All Creators" },
    ...creators.map((c) => ({ value: c.id, label: c.nickname || c.name || c.id })),
  ];
  const statusOptions: IfOption<Filters["status"]>[] = [
    { value: "", label: "All statuses" },
    { value: "active", label: "Activated" },
    { value: "inactive", label: "Deactivated" },
    { value: "pending", label: "Pending" },
  ];
  const roleOptions: IfOption[] = [
    { value: "", label: "All roles" },
    ...roles.map((r) => ({ value: r.id, label: r.name })),
    { value: NO_ROLE, label: "No role" },
  ];
  const groupOptions: IfOption[] = [
    { value: ROOT, label: agencyName, text: agencyName },
    ...groupTree.map((g) => ({
      value: String(g.group.id),
      label: <span style={{ paddingLeft: (g.depth + 1) * 12 }}>{g.group.name}</span>,
      text: g.group.name,
    })),
  ];

  const employeeRow = (e: Employee) => {
    const own = isOwner(e);
    const editable = !own && e.is_active;
    const month = monthCell(sheet, e.id);
    return (
      <tr key={e.id} data-employee={e.display_name}
        className={cn(IF_TABLE.row, "hover:bg-bg-elev-1/60", !e.is_active && "opacity-60")}>
        <td className="px-4">
          {own
            ? <input type="checkbox" disabled aria-label="Owner (not selectable)" />
            : (
              <input type="checkbox" checked={selected.has(e.id)} onChange={() => toggleSelected(e.id)}
                aria-label={`Select ${e.display_name}`} />
            )}
        </td>
        <td className={IF_TABLE.td}>
          <div className="flex items-center gap-2.5 min-w-0">
            <span aria-hidden className="h-7 w-7 shrink-0 rounded-full grid place-items-center text-[11px] font-semibold text-black/80"
              style={{ background: e.color || "#888888" }}>
              {e.display_name.slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <div className={cn("truncate", !e.is_active && "line-through")} title={e.display_name}>
                {e.display_name}{own && <span className="ml-1.5 text-[12px] text-muted">(you)</span>}
              </div>
              {e.username && <div className="truncate text-[12px] text-muted">@{e.username}</div>}
            </div>
          </div>
        </td>
        <td className={IF_TABLE.td}>
          <LinkCell text={own ? "All Creators" : assignedCreators(e.account_ids, creators)} editable={editable}
            onClick={() => setEditing(e)} title="Edit" />
        </td>
        <td className={IF_TABLE.td}>
          <LinkCell text={roleLabel(roleOf(e))} editable={editable} onClick={() => setRoleFor(e)} title="Set role" />
        </td>
        <td className={IF_TABLE.td}>
          {e.is_active ? <span className="text-[#2ad4ac]">Activated</span> : <span className={GREY}>Deactivated</span>}
        </td>
        <td className={cn(IF_TABLE.td, XL_CELL, "truncate")}>{own ? "—" : groupName(e.group_id)}</td>
        <td className={cn(IF_TABLE.td, "tabular-nums")}>
          {own ? "—" : (
            <>
              <div className="truncate">{month.earnings}</div>
              {month.shifts && <div className="truncate text-[12px] text-muted">{month.shifts}</div>}
            </>
          )}
        </td>
        <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>
          {own ? <span className={GREY}>Owner</span> : (
            <span className="inline-flex items-center gap-4">
              <button type="button" onClick={() => setEditing(e)} className="text-[14px] text-muted hover:text-accent">
                Edit
              </button>
              <RowMenu items={[
                { label: "Reset password", onClick: () => setPasswordFor(e) },
                {
                  label: "Access limits", onClick: () => setAccessFor(e), disabled: !e.is_active,
                  title: e.is_active ? undefined : "activate this employee first",
                },
                e.is_active
                  ? { label: "Deactivate", onClick: () => disableM.mutate(e.id) }
                  : { label: "Activate", onClick: () => activateM.mutate(e.id) },
                {
                  label: "Delete", disabled: true,
                  title: "Employees are deactivated, never deleted, so their history is kept",
                },
              ]} />
            </span>
          )}
        </td>
      </tr>
    );
  };

  const inviteRow = (i: PendingInvite) => {
    const name = i.display_name || "Invited employee";
    const role = roles.find((r) => r.id === i.role_id)?.name ?? "No role";
    return (
      <tr key={i.token} data-invite={name} className={cn(IF_TABLE.row, "hover:bg-bg-elev-1/60")}>
        <td className="px-4" />
        <td className={IF_TABLE.td}>
          <div className="truncate" title={name}>{name}</div>
          <div className="truncate text-[12px] text-muted">
            Invited · link expires {new Date(i.expires_at).toLocaleDateString()}
          </div>
        </td>
        <td className={cn(IF_TABLE.td, "text-[#2d74ff]")}>
          <span className="line-clamp-2">{assignedCreators(i.account_ids, creators) || "—"}</span>
        </td>
        <td className={cn(IF_TABLE.td, "text-[#2d74ff] truncate")}>{role}</td>
        <td className={IF_TABLE.td}>
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span className="text-[#F2994A]">Inactive</span>
            <button type="button" className="text-[#1677ff] hover:opacity-80 disabled:opacity-50"
              disabled={resendM.isPending} onClick={() => resendM.mutate(i.token)}>
              Resend
            </button>
          </span>
        </td>
        <td className={cn(IF_TABLE.td, XL_CELL, "truncate")}>{groupName(i.group_id)}</td>
        <td className={IF_TABLE.td}>—</td>
        <td className={IF_TABLE.td}>
          <button type="button" className="text-[#e05757] hover:opacity-80 disabled:opacity-50"
            disabled={revokeM.isPending} onClick={() => revokeM.mutate(i.token)}>
            Delete
          </button>
        </td>
      </tr>
    );
  };

  return (
    <div className="flex flex-col bg-bg-elev-1 md:h-[calc(100dvh-var(--chrome-top)-48px)] md:flex-row">
      <aside className="hidden w-[260px] shrink-0 overflow-auto border-r border-border bg-bg-elev-1 p-2.5 md:block">
        <GroupTree selected={groupId} onSelect={pickGroup} />
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto bg-bg px-4 pb-[60px]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pt-5 pr-[5px]">
          <h2 className="max-w-[300px] truncate text-[16px] font-semibold text-fg">{picked ? picked.name : agencyName}</h2>
          <span className="text-[12px] text-muted whitespace-nowrap">
            {active} active · {logins.length} total{targets.length > 0 && ` · ${targets.length} selected`}
          </span>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2.5">
            <ManageRolesLink className="mr-1.5 text-[14px]" />
            <RowMenu label="Batch actions" variant="outline"
              guard={() => {
                if (targets.length > 0) return true;
                warn("Select at least one employee");
                return false;
              }}
              items={BATCH_ACTIONS.map((a) => ({ label: a, onClick: () => setBatch(a) }))} />
            <IfButton variant="primary" onClick={() => setAdding(true)}>+ Add employee</IfButton>
          </div>
        </div>

        <label className={cn(FILTER_LABEL, "pt-5 md:hidden")}>
          Group:
          <IfSelect aria-label="Employee group" value={groupId === null ? ROOT : String(groupId)} options={groupOptions}
            onChange={(v) => pickGroup(v === ROOT ? null : Number(v))} className="min-w-0 flex-1" />
        </label>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-[5px] pt-5">
          <label className={FILTER_LABEL}>
            By employee:
            <IfInput aria-label="By employee" placeholder="Employee" value={filters.name}
              onChange={(ev) => filter({ name: ev.target.value })} className="w-[150px]" />
          </label>
          <label className={FILTER_LABEL}>
            By Creator:
            <IfSelect aria-label="By Creator" placeholder="Creator" value={filters.creator || null} options={creatorOptions}
              onChange={(v) => filter({ creator: v })} className="w-[200px]" />
          </label>
          <label className={FILTER_LABEL}>
            By status:
            <IfSelect aria-label="By status" placeholder="Status" value={filters.status || null} options={statusOptions}
              onChange={(v) => filter({ status: v })} className="w-[150px]" />
          </label>
          <label className={FILTER_LABEL}>
            By role:
            <IfSelect aria-label="By role" placeholder="Role" value={filters.role || null} options={roleOptions}
              onChange={(v) => filter({ role: v })} className="w-[150px]" />
          </label>
          <IfButton onClick={() => filter(NO_FILTERS)} className="ml-auto">Reset</IfButton>
        </div>

        {(q.error || saveError) && (
          <p role="alert" className="px-[5px] pt-3 text-err text-xs">
            {((q.error || saveError) as Error).message || "failed"}
          </p>
        )}
        <EmployeeLimitModal error={activateM.error} onClose={() => activateM.reset()} />

        <div className="mt-4 overflow-x-auto">
          <table className={cn(IF_TABLE.table, "table-fixed min-w-[860px]")}>
            <colgroup>
              <col className="w-12" />
              <col />
              <col className="w-[17%]" />
              <col className="w-[11%]" />
              <col className="w-[12%]" />
              <col className="hidden w-[10%] xl:table-column" />
              <col className="w-[11%]" />
              <col className="w-[116px]" />
            </colgroup>
            <thead>
              <tr>
                <th className={cn(TH, "px-4")}>
                  <input type="checkbox" aria-label="Select all" checked={allTicked} disabled={selectable.length === 0}
                    onChange={tickAll} />
                </th>
                <th className={TH}>Employee</th>
                <th className={TH}>Assigned Creators</th>
                <th className={TH}>Role</th>
                <th className={TH}>Status</th>
                <th className={cn(TH, XL_CELL)}>Group</th>
                <th className={cn(TH, "cursor-help")} title={MONTH_TIP}>
                  <span className="underline decoration-dotted underline-offset-4">This month</span>
                </th>
                <th className={TH}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {q.isLoading && (
                <tr><td colSpan={8} className="p-6 text-center text-muted">Loading…</td></tr>
              )}
              {!q.isLoading && pageLines.length === 0 && (
                <tr><td colSpan={8}><EmptyState kind="data" className="py-[12vh]" /></td></tr>
              )}
              {pageLines.map((l) => (l.kind === "employee" ? employeeRow(l.e) : inviteRow(l.i)))}
            </tbody>
          </table>
        </div>
        {lines.length > PAGE_SIZE && (
          <IfPager total={lines.length} noun="employees" page={pageAt} size={PAGE_SIZE} onPage={setPage}
            className="justify-end py-5" />
        )}
      </section>
      {warning}

      <EmployeeFormModal open={adding} onOpenChange={setAdding} roles={roles} creators={creators} groups={groupList} />
      <EmployeeFormModal open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} employee={editing ?? undefined}
        roleId={editing ? roleIdOf(editing) : ""} roles={roles} creators={creators} groups={groupList} />
      <RoleModal employee={roleFor} roleId={roleFor ? roleIdOf(roleFor) : ""} roles={roles} onClose={() => setRoleFor(null)} />
      <ResetPasswordModal employee={passwordFor} onClose={() => setPasswordFor(null)} />
      <AccessLimitsModal employee={accessFor} onClose={() => setAccessFor(null)} />
      <InviteLinkModal invite={resent} onClose={() => setResent(null)} />

      {batch === "Batch edit roles" && (
        <BatchRoles
          open
          roles={roles.filter((r) => r.id !== "owner")}
          loaded={rolesBlob.loaded}
          note={rolesBlob.save.gateNote ?? null}
          saving={rolesBlob.save.saving}
          error={rolesBlob.save.error ?? null}
          onCancel={() => { rolesBlob.resetSave(); setBatch(null); }}
          onSave={(roleId) => rolesBlob.commit(
            { assignments: { ...assignments, ...Object.fromEntries(targets.map((e) => [String(e.id), roleId])) } },
            closeBatch,
          )}
        />
      )}
      {batch === "Assign" && (
        <BatchAssign
          open
          creators={creators}
          saving={assignM.isPending}
          error={(assignM.error as Error | null)?.message ?? null}
          onCancel={() => { assignM.reset(); setBatch(null); }}
          onSave={(accountIds) => assignM.mutate({ ids: targets.map((e) => e.id), accountIds })}
        />
      )}
      {batch === "Batch edit group" && (
        <BatchGroup
          open
          groups={groupList}
          saving={groupM.isPending}
          error={(groupM.error as Error | null)?.message ?? null}
          onCancel={() => { groupM.reset(); setBatch(null); }}
          onSave={(id) => groupM.mutate({ groupId: id, ids: targets.map((e) => e.id) })}
        />
      )}
    </div>
  );
}

const BATCH_ACTIONS = ["Batch edit roles", "Assign", "Batch edit group"] as const;
type BatchAction = (typeof BATCH_ACTIONS)[number];

interface BatchProps {
  open: boolean;
  saving: boolean;
  error: string | null;
  onCancel: () => void;
}

function BatchDialog({ open, title, children, canSave, note = null, saving, error, onCancel, onSave }: BatchProps & {
  title: BatchAction;
  children: React.ReactNode;
  canSave: boolean;
  /** The Load gate's note, beside Save, while the blob a save replaces has not loaded. */
  note?: GateNote | null;
  onSave: () => void;
}) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onCancel()} title={title}>
      <div className="space-y-3">
        {children}
        {error && <p role="alert" className="text-err text-xs">{error}</p>}
        <div className="flex items-center justify-end gap-2">
          {note && <span className="mr-auto"><GateNoteText note={note} /></span>}
          <Button size="sm" variant="ghost" type="button" onClick={onCancel}>Cancel</Button>
          <Button size="sm" type="button" disabled={!canSave || saving} onClick={onSave}>{saving ? "Saving…" : "Save"}</Button>
        </div>
      </div>
    </Modal>
  );
}

/** One role for every selected Employee, saved with the rest of the roles blob behind its Load gate. */
function BatchRoles({ roles, loaded, onSave, ...rest }: BatchProps & {
  roles: PermissionRole[];
  loaded: boolean;
  note: GateNote | null;
  onSave: (roleId: string) => void;
}) {
  const [roleId, setRoleId] = useState("");
  return (
    <BatchDialog title="Batch edit roles" {...rest} canSave={loaded && roleId !== ""} onSave={() => onSave(roleId)}>
      <select aria-label="Role" value={roleId} onChange={(ev) => setRoleId(ev.target.value)} className={cn(FILTER, "w-full")}>
        <option value="" disabled>Choose a role</option>
        {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
      <ManageRolesLink />
    </BatchDialog>
  );
}

/** The "No group" choice of Batch edit group. */
const NO_GROUP = "none";

/** One group, or none, for every selected Employee. */
function BatchGroup({ groups, onSave, ...rest }: BatchProps & {
  groups: EmployeeGroup[];
  onSave: (groupId: number | null) => void;
}) {
  const [choice, setChoice] = useState("");
  return (
    <BatchDialog title="Batch edit group" {...rest} canSave={choice !== ""}
      onSave={() => onSave(choice === NO_GROUP ? null : Number(choice))}>
      <select aria-label="Group" value={choice} onChange={(ev) => setChoice(ev.target.value)} className={cn(FILTER, "w-full")}>
        <option value="" disabled>Choose a group</option>
        {groups.map((g) => <option key={g.id} value={String(g.id)}>{g.name}</option>)}
        <option value={NO_GROUP}>No group</option>
      </select>
    </BatchDialog>
  );
}

/** The Creators every selected Employee gets access to. */
function BatchAssign({ creators, onSave, ...rest }: BatchProps & {
  creators: AccountMeta[];
  onSave: (accountIds: string[]) => void;
}) {
  const [chosen, setChosen] = useState<string[]>([]);
  const flip = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  return (
    <BatchDialog title="Assign" {...rest} canSave={chosen.length > 0}
      onSave={() => onSave(creators.map((c) => c.id).filter((id) => chosen.includes(id)))}>
      <div className="grid grid-cols-2 gap-2">
        {creators.map((c) => (
          <label key={c.id} className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={chosen.includes(c.id)} onChange={() => flip(c.id)} />
            {c.nickname || c.name || c.id}
          </label>
        ))}
      </div>
    </BatchDialog>
  );
}
