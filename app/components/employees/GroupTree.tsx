"use client";


import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { RowMenu, type RowMenuItem } from "@/components/employees/EmployeeModals";
import { IfButton, IfInput, IfModal, IfSelect, type IfOption } from "@/components/ui/infloww";
import { useUser } from "@/contexts/UserContext";
import { GROUPS_KEY, groupsInTreeOrder, useEmployeeGroups, type EmployeeGroup } from "@/lib/employeeGroups";
import { relay } from "@/lib/relay";
import { useSettingsBlob } from "@/lib/settingsBlob";
import { cn } from "@/lib/utils";

const NAME_MAX = 64;
const ROOT = "root";
const INDENT = 24;

function Caret({ className }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 10 10" className={className}><path d="M1 3h8L5 8z" fill="currentColor" /></svg>
  );
}

export function useAgencyName(): string {
  const username = useUser().user?.username ?? "";
  const agencyName = useSettingsBlob<{ agency_name?: string }>("account", {}).value.agency_name;
  return agencyName || username || "Agency";
}

export default function GroupTree({ selected, onSelect }: {
  selected: number | null;
  onSelect: (groupId: number | null) => void;
}) {
  const qc = useQueryClient();
  const rootName = useAgencyName();
  const q = useEmployeeGroups();
  const [dialog, setDialog] = useState<GroupDialogMode | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const del = useMutation({
    mutationFn: (id: number) => relay.delete(`/admin/employee-groups/${id}`),
    onSettled: () => qc.invalidateQueries({ queryKey: GROUPS_KEY }),
  });

  const groups = q.data?.groups ?? [];
  const children = (parentId: number | null) => groups.filter((g) => g.parent_id === parentId);
  const flip = (key: string) => setCollapsed((c) => {
    const next = new Set(c);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  const parentOptionsFor = (group: EmployeeGroup): IfOption[] => {
    const ordered = groupsInTreeOrder(groups);
    const own = new Set([group.id]);
    for (const { group: g } of ordered) if (g.parent_id !== null && own.has(g.parent_id)) own.add(g.id);
    return [
      { value: ROOT, label: rootName },
      ...ordered.filter(({ group: g }) => !own.has(g.id)).map(({ group: g, depth }) => ({
        value: String(g.id), text: g.name, label: <span style={{ paddingLeft: (depth + 1) * 16 }}>{g.name}</span>,
      })),
    ];
  };

  const node = (label: string, group: EmployeeGroup | null, depth: number) => {
    const id = group ? group.id : null;
    const key = group ? String(group.id) : "root";
    const subs = children(id);
    const open = !collapsed.has(key);
    const items: RowMenuItem[] = [
      { label: "Add sub-group", onClick: () => setDialog({ kind: "add", parentId: id }), className: "text-[#2d74ff]" },
    ];
    if (group) {
      const empty = subs.length === 0 && group.employee_count === 0;
      items.push({
        label: "Edit group",
        onClick: () => setDialog({ kind: "edit", group, parentOptions: parentOptionsFor(group) }),
        className: "text-[#2d74ff]",
      });
      items.push({
        label: "Delete group",
        onClick: () => del.mutate(group.id),
        disabled: !empty,
        title: empty ? undefined : "Only a group with no sub-groups and no Employees can be deleted",
        className: "text-[#e05757]",
      });
    }
    const picked = selected === id;
    return (
      <li key={key} aria-label={label}>
        <div className="flex h-10 items-center" style={{ paddingLeft: depth * INDENT }}>
          <span className="grid w-6 shrink-0 place-items-center">
            {subs.length > 0 && (
              <button type="button" aria-label={`${open ? "Collapse" : "Expand"} ${label}`} aria-expanded={open}
                onClick={() => flip(key)} className="grid h-6 w-6 place-items-center text-fg hover:text-accent">
                <Caret className={cn("h-2.5 w-2.5 transition-transform", !open && "-rotate-90")} />
              </button>
            )}
          </span>
          <div className={cn("group flex h-10 min-w-0 flex-1 items-center gap-1 rounded px-2 text-fg",
            picked ? "bg-[#38393c] [html[data-theme=light]_&]:bg-bg-elev-2" : "hover:bg-bg-elev-2")}>
            <button type="button" aria-pressed={picked} onClick={() => onSelect(id)} title={label}
              className={cn("min-w-0 flex-1 truncate text-left", depth === 0 ? "text-[16px] font-semibold" : "text-[14px]")}>
              {label}
            </button>
            <RowMenu variant="kebab" ariaLabel={`Actions for ${label}`} items={items} />
          </div>
        </div>
        {subs.length > 0 && open && <ul>{subs.map((g) => node(g.name, g, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <div className="space-y-2">
      {q.isError && <p role="alert" className="px-2 text-sm text-err">Couldn&apos;t load the groups: {q.error.message}</p>}
      {del.isError && <p role="alert" className="px-2 text-sm text-err">{del.error.message}</p>}
      <nav aria-label="Employee groups">
        <ul aria-label="Employee groups">{node(rootName, null, 0)}</ul>
      </nav>
      {dialog && <GroupDialog mode={dialog} onClose={() => setDialog(null)} />}
    </div>
  );
}

type GroupDialogMode =
  | { kind: "add"; parentId: number | null }
  | { kind: "edit"; group: EmployeeGroup; parentOptions: IfOption[] };

function GroupDialog({ mode, onClose }: { mode: GroupDialogMode; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(mode.kind === "edit" ? mode.group.name : "");
  const startParent = mode.kind === "edit" ? mode.group.parent_id : mode.parentId;
  const [parent, setParent] = useState(startParent === null ? ROOT : String(startParent));
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), parent_id: parent === ROOT ? null : Number(parent) };
      return mode.kind === "edit"
        ? relay.patch<EmployeeGroup>(`/admin/employee-groups/${mode.group.id}`, body)
        : relay.post<EmployeeGroup>("/admin/employee-groups", body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GROUPS_KEY });
      onClose();
    },
  });
  const ok = name.trim().length > 0 && name.trim().length <= NAME_MAX;
  const submit = () => { if (ok && !save.isPending) save.mutate(); };

  return (
    <IfModal
      title={mode.kind === "edit" ? "Edit Group Settings" : "Add Group Settings"}
      width={520}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" disabled={!ok || save.isPending} onClick={submit}>Submit</IfButton>
        </>
      )}
    >
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="block space-y-2">
          <span>Group name</span>
          <IfInput size="lg" value={name} maxLength={NAME_MAX} autoFocus
            onChange={(e) => setName(e.target.value)} className="h-10 w-full" />
        </label>
        {mode.kind === "edit" && (
          <div className="space-y-2">
            <span>Parent group</span>
            <IfSelect size="lg" aria-label="Parent group" value={parent} options={mode.parentOptions}
              onChange={setParent} className="w-full" />
          </div>
        )}
        {save.isError && <p role="alert" className="text-xs text-err">{save.error.message}</p>}
      </form>
    </IfModal>
  );
}
