"use client";

/**
 * Role Settings (docs/spec/settings-tabs/phase-03-roles-sales.md): the Agency's
 * Permission roles, saved whole to the `roles` Settings blob behind the Load
 * gate. Owner and Admin are built in and always listed first; "+ Add Role"
 * appends a custom role, deny-all with scope `self`. "Edit" reopens the same
 * modal pre-filled (a built-in's name locked). "Set Permissions" swaps the Panel
 * for that role's Permission editor. No built-in role is deleted. Roles are
 * assigned on Employees (EmployeesTab), which a line here links to; every write
 * here commits at once, so the Panel has no Save. Built-ins with no stored
 * description show a display-only one (BUILT_IN_DESCRIPTIONS, never saved).
 * Below sm Description hides and the Operations stack, so they fit a 390px phone.
 * The "Enforce role permissions" switch, on unless `enforce: false` is stored, saves `enforce`
 * at once: with it on the Relay refuses each chatter the pages its role does not
 * grant (docs/spec/phase-04-apply-stored-settings.md). Turning it on first
 * confirms with the count of active Employees whose role grants no page, who will
 * be refused every page; turning it off needs no confirm. The not-enforced note
 * shows only while it is off; while it is on, a warning counts those Employees.
 *
 * Every Employee holds a role (one never assigned reads as Chatter, which the
 * Relay gives it on joining and on any save), and a role in use cannot be deleted, as Infloww refuses ("This role is in use and
 * cannot be deleted").
 *
 * A custom role's Status switch (Infloww's RolePermissions_DisableActiveRole) saves `disabled` at once: a
 * disabled role grants nothing on the Relay, and its Employees keep it, so switching it back on restores them.
 * Disabling a role some active Employee holds first confirms. The built-ins' switch is always on.
 *
 * ASSUMPTION: an Employee whose assignment names a role id no role has counts as
 * granted no page, since the Relay refuses it every page too. Rung 5. Overturned
 * if the owner wants the count to mean pageless roles only.
 */

import { useState, type ReactNode } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { useRoster } from "@/hooks/useRoster";
import {
  BlobNotes, Card, Field, FieldInput, IF_BTN, IF_BTN_PRIMARY, LoadError, NotAppliedYet, SettingsPanel, SettingsTable,
  Switch, TABLE_CELL, TABLE_ROW, type TableColumn,
} from "@/components/settings/SettingsPanel";
import PermissionEditor, { type PermissionRole } from "@/components/settings/PermissionEditor";
import {
  allPages, assignedRole, isBuiltIn, withBuiltIns, type RolesBlob,
} from "@/lib/roles";
import { IF_MODAL_BOX, IF_MODAL_MASK } from "@/components/ui/ifModal";
import { cn } from "@/lib/utils";
import { ifAlert, ifConfirm } from "@/components/ui/ifConfirm";

const ENFORCE = "Enforce role permissions";

const COLUMNS: TableColumn[] = [
  "Name", { label: "Description", className: "hidden sm:table-cell" }, "Status",
  "Operations",
];

/** What a built-in does, shown when its stored description is empty; display only, never saved. */
const BUILT_IN_DESCRIPTIONS: Record<string, string> = {
  owner: "Full access; owns the Agency",
  admin: "Full access to every page",
  "team-leader": "Chatting, creators, employees and reports for their team",
  chatter: "Dashboard and chatting pages, own chats only",
  creator: "OF Manager pages: posts, vault, queue, profile",
};
const roleDescription = (r: PermissionRole) => r.description || BUILT_IN_DESCRIPTIONS[r.id] || "";

/** The Status switch is off: a built-in role is always on, as the Relay reads it. */
const isOff = (r: PermissionRole) => r.disabled === true && !isBuiltIn(r.id);

/** An Operations cell action: a plain text button in `--if-accent` (M1); Delete is D1. */
const OPERATION = "text-[var(--if-accent)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const DELETE = cn(OPERATION, "text-[#ff7c71]");

/** One `._tabble-content_1r0jx_77` block: a 16px / 500 T1 title 16px over its table, 32px before the next. */
function TableBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h3 className="mb-4 text-[length:var(--if-fs-lg)] font-medium text-[var(--if-fg)]">{title}</h3>
      {children}
    </section>
  );
}

/** The role an Employee with no assignment reads as: the Relay gives it Chatter (settings_api.DEFAULT_LOGIN_ROLE). */
const DEFAULT_ROLE = "chatter";


/** The tab's one save-error line, under Add Role's Submit and above the Permission editor. */
function SaveError({ error }: { error: string | null }) {
  if (!error) return null;
  return <span role="alert" className="text-[length:var(--if-fs-sm)] text-[var(--if-danger)]">{error}</span>;
}

/** The role modal's body, for "Add Role" (`role` undefined) and "Edit Role"; mounted on open, so each
 *  opening starts blank or from the edited role. The duplicate check skips the edited role. */
function RoleForm({ role, roles, saving, error, onSubmit, onCancel }: {
  role?: PermissionRole;
  roles: PermissionRole[];
  saving: boolean;
  error: string | null;
  onSubmit: (name: string, description: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const key = name.trim().toLowerCase();
  const taken = roles.some((r) => r.id !== role?.id && r.name.trim().toLowerCase() === key);

  return (
    <>
      <Field label="Role Name" htmlFor="role-name">
        <FieldInput
          id="role-name"
          value={name}
          disabled={role !== undefined && isBuiltIn(role.id)}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Description" htmlFor="role-description">
        <FieldInput id="role-description" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="mb-5 flex items-center justify-end gap-3">
        <SaveError error={error} />
        <button type="button" className={IF_BTN} onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className={IF_BTN_PRIMARY}
          disabled={saving || !key || taken}
          onClick={() => onSubmit(name.trim(), description)}
        >
          Submit
        </button>
      </div>
    </>
  );
}

export default function RoleSettingsTab() {
  const blob = useSettingsBlob<RolesBlob>("roles", { roles: [] });
  const roles = withBuiltIns(blob.value.roles);
  /** The open role modal: `{}` adds a role, `{ role }` edits that one; null while closed. */
  const [modal, setModal] = useState<{ role?: PermissionRole } | null>(null);
  const close = () => setModal(null);
  const [editing, setEditing] = useState<string | null>(null);
  const editRole = roles.find((r) => r.id === editing);
  const { query: rosterQuery, rows: employees } = useRoster({ includeDisabled: false });
  const assignments = blob.value.assignments ?? {};

  /** Active Employees the Relay refuses every page: their role grants none, or names a role no role has. */
  const pageless = employees.filter((e) => {
    const role = assignedRole(roles, { [String(e.id)]: DEFAULT_ROLE, ...assignments }, e.id);
    // Pages only: a `<page>#<action>` key grants no page of its own.
    return typeof role !== "object" || isOff(role)
      || !Object.entries(role.permissions ?? {}).some(([key, ok]) => ok === true && !key.includes("#"));
  }).length;
  const pagelessWho = pageless === 1 ? "1 active Employee holds" : `${pageless} active Employees hold`;

  const enforced = blob.value.enforce !== false;
  /** Saves the switch; turning it on first confirms with the active Employees the Relay will refuse every page. */
  const setEnforce = async (on: boolean) => {
    if (on && pageless > 0) {
      if (!(await ifConfirm(`Turn on ${ENFORCE}? ${pagelessWho} a role granting no page and will be refused every page.`)))
        return;
    }
    blob.commit({ enforce: on });
  };

  const add = (name: string, description: string) => {
    const role: PermissionRole = {
      id: `role-${Date.now().toString(36)}`, name, description, permissions: allPages(false), scope: "self",
    };
    blob.commit({ roles: [...roles, role] }, close);
  };

  /** Saves the whole `roles` blob with `role` replaced in place, then `onSaved`. */
  const replaceRole = (role: PermissionRole, onSaved: () => void) => {
    blob.commit({ roles: roles.map((r) => (r.id === role.id ? role : r)) }, onSaved);
  };

  /** Saves a custom role's Status; disabling one an active Employee holds first confirms. */
  const setStatus = async (role: PermissionRole, on: boolean) => {
    const holders = employees.filter((e) => assignments[String(e.id)] === role.id).length;
    if (!on && holders > 0) {
      const who = holders === 1 ? "1 active Employee holds it" : `${holders} active Employees hold it`;
      if (!(await ifConfirm(`Disable the role "${role.name}"? ${who} and will be refused every page.`))) return;
    }
    replaceRole({ ...role, disabled: !on }, () => {});
  };

  /** Deletes a role no Employee holds; one in use is refused, as Infloww refuses it. */
  const removeRole = async (role: PermissionRole) => {
    if (Object.values(assignments).includes(role.id)) {
      void ifAlert("This role is in use and cannot be deleted. Give its Employees another role first.");
      return;
    }
    if (!(await ifConfirm(`Delete the role "${role.name}"?`, { danger: true }))) return;
    blob.commit({ roles: roles.filter((r) => r.id !== role.id) });
  };

  const operations = (r: PermissionRole) => (
    <div className="flex flex-col items-start gap-1 sm:flex-row sm:gap-4">
      <button type="button" className={OPERATION} disabled={!blob.loaded} onClick={() => setModal({ role: r })}>
        Edit
      </button>
      <button type="button" className={OPERATION} disabled={!blob.loaded} onClick={() => setEditing(r.id)}>
        Set Permissions
      </button>
      {!isBuiltIn(r.id) && (
        <button type="button" className={DELETE} disabled={!blob.loaded} onClick={() => removeRole(r)}>
          Delete
        </button>
      )}
    </div>
  );

  const roleModal = (
    <Dialog.Root open={modal !== null} onOpenChange={(open) => setModal(open ? {} : null)}>
      <Dialog.Trigger asChild>
        <button type="button" className={IF_BTN_PRIMARY} disabled={!blob.loaded}>
          + Add Role
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={cn("fixed inset-0 z-40", IF_MODAL_MASK)} />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn("fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(var(--if-input-w)+48px)] max-w-[calc(100vw-32px)] px-6 pt-[22px] pb-px", IF_MODAL_BOX)}
        >
          <Dialog.Title className="mb-6 text-[16px] font-semibold text-fg">
            {modal?.role ? "Edit Role" : "Add Role"}
          </Dialog.Title>
          <RoleForm
            role={modal?.role}
            roles={roles}
            saving={blob.save.saving}
            error={blob.save.error ?? null}
            onCancel={close}
            onSubmit={(name, description) => {
              const edited = modal?.role;
              if (edited) replaceRole({ ...edited, name, description }, close);
              else add(name, description);
            }}
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );

  if (editRole) {
    return (
      <PermissionEditor
        key={editRole.id}
        role={editRole}
        canSave={!blob.save.saving}
        onBack={() => setEditing(null)}
        onSave={(role) => replaceRole(role, () => setEditing(null))}
      >
        {blob.save.error && (
          <div className="mb-4">
            <SaveError error={blob.save.error} />
          </div>
        )}
      </PermissionEditor>
    );
  }

  return (
    <SettingsPanel
      title="Role Settings"
      actions={roleModal}
    >
      <BlobNotes className="mb-4" note={blob.save.gateNote} q={blob.query} />
      {blob.save.error && modal === null && (
        <div className="mb-4"><SaveError error={blob.save.error} /></div>
      )}
      <div className="mb-4">
        <Card
          box="bordered"
          title={ENFORCE}
          control={
            <Switch
              checked={enforced}
              label={ENFORCE}
              onChange={blob.loaded && !blob.save.saving ? setEnforce : undefined}
            />
          }
        />
        {!enforced && (
          <NotAppliedYet>Saved for your organization; not enforced until {ENFORCE} is on.</NotAppliedYet>
        )}
        {enforced && pageless > 0 && (
          <p role="status" className="mt-2 text-[length:var(--if-fs-sm)] text-[var(--if-danger)]">
            {pagelessWho} a role granting no page and {pageless === 1 ? "is" : "are"} refused every page.
          </p>
        )}
      </div>
      <TableBlock title="Roles">
        <SettingsTable aria-label="Roles" columns={COLUMNS}>
          {roles.map((r) => (
            <tr key={r.id} className={TABLE_ROW}>
              <td className={TABLE_CELL}>{r.name}</td>
              <td className={cn(TABLE_CELL, "hidden sm:table-cell text-[var(--if-fg-2)]")}>{roleDescription(r)}</td>
              <td className={TABLE_CELL}>
                <Switch
                  checked={!isOff(r)}
                  label={`${r.name} status`}
                  title={isBuiltIn(r.id) ? "Built-in roles are always on" : undefined}
                  onChange={!isBuiltIn(r.id) && blob.loaded && !blob.save.saving ? (on) => setStatus(r, on) : undefined}
                />
              </td>
              <td className={cn(TABLE_CELL, "max-sm:h-auto max-sm:py-2")}>{operations(r)}</td>
            </tr>
          ))}
        </SettingsTable>
      </TableBlock>
      <LoadError error={rosterQuery.error} />
      <p className="text-[length:var(--if-fs)] text-[var(--if-fg-2)]">
        Assign roles to Employees on{" "}
        <Link href="/employees" className="text-[var(--if-accent)] hover:underline">Employees</Link>.
      </p>
    </SettingsPanel>
  );
}
