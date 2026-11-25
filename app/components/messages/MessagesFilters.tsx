"use client";


import { useEffect, useState } from "react";

import { Button, Input } from "@/components/ui/primitives";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { cn } from "@/lib/utils";

import type { MessageDirection, MessageType, PaidStatus } from "@/hooks/usePaidMessages";

interface Props {
  accountId: string | null;
  onAccountChange: (id: string | null) => void;
  employeeId: number | null;
  onEmployeeChange: (id: number | null) => void;
  status: PaidStatus;
  onStatusChange: (s: PaidStatus) => void;
  showStatus?: boolean;
  fanQuery: string;
  onFanQueryChange: (q: string) => void;
  type?: MessageType;
  onTypeChange?: (t: MessageType) => void;
  direction?: MessageDirection;
  onDirectionChange?: (d: MessageDirection) => void;
}

export default function MessagesFilters({
  accountId,
  onAccountChange,
  employeeId,
  onEmployeeChange,
  status,
  onStatusChange,
  showStatus = true,
  fanQuery,
  onFanQueryChange,
  type,
  onTypeChange,
  direction,
  onDirectionChange,
}: Props) {
  const renderStatus = showStatus && type !== "free";
  const employeeDisabled = direction === "in";
  const accounts = useActiveAccounts();
  // Roster is owner-only at the Relay: a chatter's picker lists no Employees (no 403 retries).
  const { rows: employees } = useRoster({ includeDisabled: false, includeChatterMirrors: true });

  const [localFan, setLocalFan] = useState(fanQuery);
  useEffect(() => {
    setLocalFan(fanQuery);
  }, [fanQuery]);
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (localFan !== fanQuery) onFanQueryChange(localFan);
    }, 250);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localFan]);

  const showShortHint = localFan.length > 0 && localFan.length < 2;

  return (
    <div className="flex flex-wrap items-center gap-3 p-3 bg-panel border border-border rounded-xl">
      <Field label="Model">
        <select
          value={accountId ?? ""}
          onChange={(e) => onAccountChange(e.target.value || null)}
          className="bg-bg border border-border rounded-lg px-2 py-1.5 text-xs text-fg focus:outline-none focus:border-accent"
        >
          <option value="">All models</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.nickname || a.id}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Employee">
        <select
          value={employeeId ?? ""}
          onChange={(e) => onEmployeeChange(e.target.value ? Number(e.target.value) : null)}
          disabled={employeeDisabled}
          title={employeeDisabled ? "Inbound messages have no sending employee" : undefined}
          className="bg-bg border border-border rounded-lg px-2 py-1.5 text-xs text-fg focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <option value="">All employees</option>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.display_name}
            </option>
          ))}
        </select>
      </Field>

      {type !== undefined && onTypeChange && (
        <Field label="Type">
          <div className="flex items-center gap-1">
            <StatusBtn active={type === "all"} onClick={() => onTypeChange("all")}>All</StatusBtn>
            <StatusBtn active={type === "paid"} onClick={() => onTypeChange("paid")}>Paid</StatusBtn>
            <StatusBtn active={type === "free"} onClick={() => onTypeChange("free")}>Free</StatusBtn>
          </div>
        </Field>
      )}

      {direction !== undefined && onDirectionChange && (
        <Field label="Direction">
          <div className="flex items-center gap-1">
            <StatusBtn active={direction === "any"} onClick={() => onDirectionChange("any")}>All</StatusBtn>
            <StatusBtn active={direction === "out"} onClick={() => onDirectionChange("out")}>Outbound</StatusBtn>
            <StatusBtn active={direction === "in"} onClick={() => onDirectionChange("in")}>Inbound</StatusBtn>
          </div>
        </Field>
      )}

      {renderStatus && (
        <Field label="Status">
          <div className="flex items-center gap-1">
            <StatusBtn active={status === "all"} onClick={() => onStatusChange("all")}>All</StatusBtn>
            <StatusBtn active={status === "paid"} onClick={() => onStatusChange("paid")}>Paid</StatusBtn>
            <StatusBtn active={status === "unpaid"} onClick={() => onStatusChange("unpaid")}>Unpaid</StatusBtn>
          </div>
        </Field>
      )}

      <Field label="Fan">
        <div className="flex flex-col gap-0.5">
          <Input
            value={localFan}
            onChange={(e) => setLocalFan(e.target.value)}
            placeholder="username / display name"
            className="text-xs py-1.5 w-52"
            aria-label="Search fan"
          />
          {showShortHint && (
            <span className="text-[10px] text-warn">≥2 chars</span>
          )}
        </div>
      </Field>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-fg-dim">{label}</span>
      {children}
    </label>
  );
}

function StatusBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      variant={active ? "primary" : "secondary"}
      size="sm"
      onClick={onClick}
      className={cn(!active && "border-border")}
    >
      {children}
    </Button>
  );
}
