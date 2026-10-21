"use client";

/**
 * Manage employees' modals and row menu, after Infloww's (bundle `index.9f50f370.js`: `EmployeeListPage`,
 * `AddModelComponent$3` with `modelType` 1 add / 2 edit, `MoreOperations`, the Reset password `AddModelComponent`):
 *
 *   • EmployeeFormModal — "+ Add employee" and "Edit": Name, Role, Group, Creators. Adding also picks how they
 *     sign in. Infloww mails an invite to an email address; here the owner either makes the login outright
 *     (username + password, POST /admin/employees/login), mints a one-shot invite link carrying the same setup
 *     (POST /admin/chatters/invite, applied when it is accepted), or adds an existing login by username
 *     (POST /admin/chatters/link). Edit saves PUT /admin/employees/{id}/setup.
 *   • RoleModal — the Role cell / "Set role": one role, with the link to Role Settings where the presets live.
 *   • ResetPasswordModal — Infloww mails reset instructions; the owner sets the new password here instead
 *     (POST /admin/employees/{id}/password).
 *   • AccessLimitsModal — the login's Creator and vault-folder limits (AccessEditor).
 *   • RowMenu — the row's "More", the header's "Batch actions" and the group tree's ⋮ dropdowns, rendered in a portal
 *     so the table or the tree column never clips or scrolls them.
 *   • Modal — every dialog here, on Infloww's antd modal (`IfModal`).
 *   • InviteLinkModal — a pending invite's fresh link after Resend (POST /admin/chatters/invites/{token}/resend).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { EllipsisVertical } from "lucide-react";

import { Button } from "@/components/ui/primitives";
import { IfModal } from "@/components/ui/infloww";
import { AccessEditor } from "@/components/employees/EmployeeAccess";
import { relay, type AccountMeta, type Employee } from "@/lib/relay";
import type { EmployeeGroup } from "@/lib/employeeGroups";
import type { PermissionRole } from "@/components/settings/PermissionEditor";
import { cn } from "@/lib/utils";

/** Where the Admin / Manager / Chatter / VA presets are edited. */
export const ROLE_SETTINGS_HREF = "/settings/roles";
export function ManageRolesLink({ className }: { className?: string }) {
  return (
    <Link href={ROLE_SETTINGS_HREF} className={cn("text-xs text-accent hover:underline whitespace-nowrap", className)}>
      Manage roles &amp; permissions →
    </Link>
  );
}

const INPUT = "w-full bg-bg border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:border-accent";
const LABEL = "block text-xs font-medium text-fg-dim mb-1";

function errText(err: unknown): string | null {
  return err ? (err as Error).message || "save failed" : null;
}

/** Infloww's antd modal (`IfModal`, 440 wide, `wide` 640) while `open`; `onOpenChange(false)` closes it. */
export function Modal({ open, onOpenChange, title, children, wide = false }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return <IfModal title={title} width={wide ? 640 : 440} onClose={() => onOpenChange(false)}>{children}</IfModal>;
}

function Footer({ error, saving, canSave, label, onCancel }: {
  error: string | null;
  saving: boolean;
  canSave: boolean;
  label: string;
  onCancel: () => void;
}) {
  return (
    <div className="mt-5 flex items-center justify-end gap-2">
      {error && <span role="alert" className="mr-auto text-err text-xs">{error}</span>}
      <Button size="sm" variant="ghost" type="button" onClick={onCancel}>Cancel</Button>
      <Button size="sm" type="submit" disabled={!canSave || saving}>{saving ? "Saving…" : label}</Button>
    </div>
  );
}

/** Role options for an Employee: every role but Owner. */
export const assignableRoles = (roles: PermissionRole[]) => roles.filter((r) => r.id !== "owner");

/** Every Employee holds a role (the Relay gives none the built-in Chatter): `id` when it is assignable, else Chatter. */
const roleOrChatter = (roles: PermissionRole[], id: string | undefined) =>
  id && assignableRoles(roles).some((r) => r.id === id) ? id : "chatter";

function RoleSelect({ id, roles, value, onChange }: {
  id: string;
  roles: PermissionRole[];
  value: string;
  onChange: (roleId: string) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className={LABEL}>Role</label>
        <ManageRolesLink />
      </div>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT}>
        {assignableRoles(roles).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
    </div>
  );
}

/** Creators: every Creator (null) or the ticked ones. */
function CreatorPicker({ creators, value, onChange }: {
  creators: AccountMeta[];
  value: string[] | null;
  onChange: (ids: string[] | null) => void;
}) {
  const all = value === null;
  const flip = (id: string) => {
    const cur = value ?? [];
    onChange(cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]);
  };
  return (
    <fieldset>
      <legend className={LABEL}>Creators</legend>
      <label className="flex items-center gap-2 text-sm mb-1.5">
        <input type="checkbox" checked={all} onChange={() => onChange(all ? [] : null)} />
        All creators
      </label>
      {!all && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 max-h-40 overflow-y-auto rounded-md border border-border p-2">
          {creators.length === 0 && <span className="text-xs text-fg-dim">No creators yet.</span>}
          {creators.map((c) => (
            <label key={c.id} className="flex items-center gap-2 text-sm min-w-0">
              <input type="checkbox" checked={(value ?? []).includes(c.id)} onChange={() => flip(c.id)} />
              <span className="truncate">{c.nickname || c.name || c.id}</span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

type SignIn = "create" | "invite" | "existing";
const SIGN_IN: Array<{ key: SignIn; label: string }> = [
  { key: "create", label: "Create login" },
  { key: "invite", label: "Invite link" },
  { key: "existing", label: "Existing login" },
];

export interface InviteResp { token: string; expires_at: string; accept_path: string; }

/** An invite's link to copy and send: from "+ Add employee" by invite link, or a pending row's Resend. */
function InviteLink({ invite, onDone }: { invite: InviteResp; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const url = `${typeof window !== "undefined" ? window.location.origin : ""}${invite.accept_path}`;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        Send this link to the new employee. They pick a username and password, and join your team with the role
        and creators you chose. It works once and expires {new Date(invite.expires_at).toLocaleString()}.
      </p>
      <div className="flex items-center gap-2">
        <input readOnly aria-label="Invite link" value={url} onFocus={(e) => e.currentTarget.select()}
          className={cn(INPUT, "font-mono text-xs")} />
        <Button size="sm" type="button" onClick={async () => {
          try { await navigator.clipboard.writeText(url); setCopied(true); } catch { /* select by hand */ }
        }}>{copied ? "Copied" : "Copy"}</Button>
      </div>
      <div className="flex justify-end"><Button size="sm" type="button" onClick={onDone}>Done</Button></div>
    </div>
  );
}

/** A pending invite's fresh link after Resend (the old link stops working). */
export function InviteLinkModal({ invite, onClose }: { invite: InviteResp | null; onClose: () => void }) {
  return (
    <Modal open={invite !== null} onOpenChange={(o) => !o && onClose()} title="Invite link">
      {invite && <InviteLink invite={invite} onDone={onClose} />}
    </Modal>
  );
}

/** "+ Add employee" (no `employee`) or "Edit" (that row). */
export function EmployeeFormModal({ open, onOpenChange, employee, roleId, roles, creators, groups }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employee?: Employee;
  /** The row's current role id ("" for none). */
  roleId?: string;
  roles: PermissionRole[];
  creators: AccountMeta[];
  groups: EmployeeGroup[];
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={employee ? "Edit employee" : "Add employee"} wide>
      {open && (
        <EmployeeForm
          employee={employee}
          initialRole={roleOrChatter(roles, employee ? roleId : undefined)}
          roles={roles}
          creators={creators}
          groups={groups}
          onDone={() => onOpenChange(false)}
        />
      )}
    </Modal>
  );
}

function EmployeeForm({ employee, initialRole, roles, creators, groups, onDone }: {
  employee?: Employee;
  initialRole: string;
  roles: PermissionRole[];
  creators: AccountMeta[];
  groups: EmployeeGroup[];
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [signIn, setSignIn] = useState<SignIn>("create");
  const [name, setName] = useState(employee?.display_name ?? "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(initialRole);
  const [groupId, setGroupId] = useState<string>(employee?.group_id != null ? String(employee.group_id) : "");
  const [accountIds, setAccountIds] = useState<string[] | null>(employee ? employee.account_ids ?? null : null);
  const [invite, setInvite] = useState<InviteResp | null>(null);

  const setup = {
    display_name: name.trim() || null,
    role_id: role || null,
    account_ids: accountIds && accountIds.length > 0 ? accountIds : null,
    group_id: groupId ? Number(groupId) : null,
  };
  const saveM = useMutation({
    mutationFn: async () => {
      if (employee) return relay.put<unknown>(`/admin/employees/${employee.id}/setup`, setup);
      if (signIn === "create") {
        return relay.post<unknown>("/admin/employees/login", { ...setup, username: username.trim().toLowerCase(), password });
      }
      if (signIn === "existing") {
        return relay.post<unknown>("/admin/chatters/link", { ...setup, username: username.trim().toLowerCase() });
      }
      setInvite(await relay.post<InviteResp>("/admin/chatters/invite", setup));
      return null;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["employees"] });
      void qc.invalidateQueries({ queryKey: ["settings-blob", "roles"] });
      if (employee || signIn !== "invite") onDone();
    },
  });

  const noCreators = accountIds !== null && accountIds.length === 0;
  const canSave = !noCreators && (employee
    ? name.trim() !== ""
    : signIn === "invite" || (username.trim() !== "" && (signIn === "existing" || password.length >= 6)));

  if (invite) return <InviteLink invite={invite} onDone={onDone} />;

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (canSave) saveM.mutate(); }} className="space-y-4">
      {!employee && (
        <div role="radiogroup" aria-label="How they sign in" className="flex gap-1 rounded-lg bg-bg p-1 border border-border">
          {SIGN_IN.map((o) => (
            <button key={o.key} type="button" role="radio" aria-checked={signIn === o.key}
              onClick={() => setSignIn(o.key)}
              className={cn("flex-1 rounded-md px-3 py-1.5 text-sm", signIn === o.key ? "bg-bg-elev-2 text-fg" : "text-fg-dim hover:text-fg")}>
              {o.label}
            </button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <div className={cn(employee && "col-span-2")}>
          <label htmlFor="emp-name" className={LABEL}>Name</label>
          <input id="emp-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={64}
            placeholder="Their name on your team" className={INPUT} />
        </div>
        {!employee && signIn !== "invite" && (
          <div>
            <label htmlFor="emp-username" className={LABEL}>Username</label>
            <input id="emp-username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off"
              placeholder={signIn === "existing" ? "Their existing username" : "3-32 chars, a-z 0-9 . _ -"} className={INPUT} />
          </div>
        )}
        {!employee && signIn === "create" && (
          <div>
            <label htmlFor="emp-password" className={LABEL}>Password</label>
            <input id="emp-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password" placeholder="At least 6 characters" className={INPUT} />
          </div>
        )}
        <RoleSelect id="emp-role" roles={roles} value={role} onChange={setRole} />
        <div>
          <label htmlFor="emp-group" className={LABEL}>Group</label>
          <select id="emp-group" value={groupId} onChange={(e) => setGroupId(e.target.value)} className={INPUT}>
            <option value="">No group</option>
            {groups.map((g) => <option key={g.id} value={String(g.id)}>{g.name}</option>)}
          </select>
        </div>
      </div>
      <CreatorPicker creators={creators} value={accountIds} onChange={setAccountIds} />
      {noCreators && <p className="text-xs text-fg-dim">Pick at least one creator, or All creators.</p>}
      <Footer error={errText(saveM.error)} saving={saveM.isPending} canSave={canSave}
        label={employee ? "Save" : signIn === "invite" ? "Create invite link" : "Add employee"} onCancel={onDone} />
    </form>
  );
}

/** The Role cell / "Set role". */
export function RoleModal({ employee, roleId, roles, onClose }: {
  employee: Employee | null;
  roleId: string;
  roles: PermissionRole[];
  onClose: () => void;
}) {
  return (
    <Modal open={employee !== null} onOpenChange={(o) => !o && onClose()} title="Set role">
      {employee && <RoleForm employee={employee} initial={roleId} roles={roles} onDone={onClose} />}
    </Modal>
  );
}

function RoleForm({ employee, initial, roles, onDone }: {
  employee: Employee;
  initial: string;
  roles: PermissionRole[];
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [role, setRole] = useState(roleOrChatter(roles, initial));
  const saveM = useMutation({
    mutationFn: () => relay.put<unknown>(`/admin/employees/${employee.id}/setup`, { role_id: role || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings-blob", "roles"] });
      onDone();
    },
  });
  const desc = roles.find((r) => r.id === role)?.description;
  return (
    <form onSubmit={(e) => { e.preventDefault(); saveM.mutate(); }} className="space-y-2">
      <p className="text-sm text-fg-dim mb-2">{employee.display_name}{employee.username ? ` (@${employee.username})` : ""}</p>
      <RoleSelect id="role-only" roles={roles} value={role} onChange={setRole} />
      {desc && <p className="text-xs text-fg-dim">{desc}</p>}
      <Footer error={errText(saveM.error)} saving={saveM.isPending} canSave={role !== initial} label="Save" onCancel={onDone} />
    </form>
  );
}

/** Reset password: the owner sets the Employee's new password. */
export function ResetPasswordModal({ employee, onClose }: { employee: Employee | null; onClose: () => void }) {
  return (
    <Modal open={employee !== null} onOpenChange={(o) => !o && onClose()} title="Reset password">
      {employee && <PasswordForm employee={employee} onDone={onClose} />}
    </Modal>
  );
}

function PasswordForm({ employee, onDone }: { employee: Employee; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const saveM = useMutation({
    mutationFn: () => relay.post<unknown>(`/admin/employees/${employee.id}/password`, { password: pw }),
  });
  if (saveM.isSuccess) {
    return (
      <div className="space-y-4">
        <p className="text-sm">
          {employee.display_name}&rsquo;s password is changed. Give them the new one; it works from their next sign-in.
        </p>
        <div className="flex justify-end"><Button size="sm" type="button" onClick={onDone}>Done</Button></div>
      </div>
    );
  }
  const mismatch = again !== "" && again !== pw;
  return (
    <form onSubmit={(e) => { e.preventDefault(); saveM.mutate(); }} className="space-y-3">
      <p className="text-sm text-fg-dim">
        Set a new password for <span className="text-fg">{employee.display_name}</span>
        {employee.username ? <> (<span className="font-mono">@{employee.username}</span>)</> : null}.
      </p>
      <div>
        <label htmlFor="new-password" className={LABEL}>New password</label>
        <input id="new-password" type="password" value={pw} onChange={(e) => setPw(e.target.value)}
          autoComplete="new-password" placeholder="At least 6 characters" className={INPUT} />
      </div>
      <div>
        <label htmlFor="new-password-again" className={LABEL}>Confirm password</label>
        <input id="new-password-again" type="password" value={again} onChange={(e) => setAgain(e.target.value)}
          autoComplete="new-password" className={INPUT} />
      </div>
      {mismatch && <p className="text-xs text-err">The passwords don&rsquo;t match.</p>}
      <Footer error={errText(saveM.error)} saving={saveM.isPending} canSave={pw.length >= 6 && pw === again}
        label="Reset password" onCancel={onDone} />
    </form>
  );
}

/** The login's Creator and vault-folder limits. */
export function AccessLimitsModal({ employee, onClose }: { employee: Employee | null; onClose: () => void }) {
  return (
    <Modal open={employee !== null} onOpenChange={(o) => !o && onClose()} title="Access limits" wide>
      {employee?.chatter_id && <AccessEditor chatterId={employee.chatter_id} onClose={onClose} />}
    </Modal>
  );
}

export interface RowMenuItem {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
  /** The item's text colour while enabled (the group tree's #2d74ff "Add sub-group", #e05757 "Delete group"). */
  className?: string;
}

const TRIGGER = {
  /** A row's "More": #999 text, M1 on hover (Infloww's `MoreOperations`). */
  link: "text-[14px] text-muted hover:text-accent",
  /** The header's "Batch actions": 160x32, radius 4, a 1px #1677ff outline and #1677ff 500 text, a 15px chevron. */
  outline: "inline-flex h-8 w-40 items-center justify-center gap-2 rounded border border-[#1677ff] text-[14px] font-medium text-[#1677ff] hover:bg-[#1677ff]/10",
  /** The group tree's ⋮ at a row's right. */
  kebab: "grid h-6 w-6 shrink-0 place-items-center rounded text-fg-dim hover:text-fg",
} as const;

/** "More": a dropdown in a portal, placed under its trigger (flipped above near the bottom of the window). */
export function RowMenu({ label = "More", ariaLabel, items, variant = "link", disabled = false, guard }: {
  label?: string;
  /** Names a trigger whose text is not its name (the ⋮). */
  ariaLabel?: string;
  items: RowMenuItem[];
  variant?: keyof typeof TRIGGER;
  disabled?: boolean;
  /** Asked on a click before opening; false keeps it shut (Batch actions with nobody selected). */
  guard?: () => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);

  if (open && disabled) setOpen(false);

  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const h = panel.current?.offsetHeight ?? 180;
    const w = 184;
    const below = r.bottom + 4 + h <= window.innerHeight;
    setPos({ top: below ? r.bottom + 4 : r.top - 4 - h, left: Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!btn.current?.contains(t) && !panel.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onScroll = () => setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onScroll);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  return (
    <>
      <button ref={btn} type="button" aria-haspopup="menu" aria-expanded={open} aria-label={ariaLabel} disabled={disabled}
        onClick={() => { if (!open && guard && !guard()) return; setOpen((o) => !o); }}
        className={cn(TRIGGER[variant], "disabled:cursor-not-allowed disabled:opacity-50")}>
        {variant === "kebab" ? <EllipsisVertical aria-hidden className="h-4 w-4" /> : label}
        {variant === "outline" && (
          <svg aria-hidden viewBox="0 0 12 12" className="h-[15px] w-[15px]"><path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg>
        )}
      </button>
      {open && typeof document !== "undefined" && createPortal(
        <div ref={panel} role="menu" style={{ position: "fixed", top: pos?.top ?? -9999, left: pos?.left ?? -9999, width: 184 }}
          className="z-[55] rounded-lg border border-border bg-panel p-1 shadow-xl">
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" disabled={item.disabled} title={item.title}
              onClick={() => { setOpen(false); item.onClick?.(); }}
              className={cn(
                "w-full text-left px-3 py-2 rounded-md text-sm",
                item.disabled ? "text-fg-dim opacity-50 cursor-not-allowed"
                  : cn(item.danger ? "text-err hover:bg-err/10" : "hover:bg-bg-elev-1", item.className),
              )}>
              {item.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
