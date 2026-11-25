"use client";


import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { HbFilter } from "@/components/ui/infloww";
import { PLATFORMS } from "@/lib/platform";
import { cn } from "@/lib/utils";

const NOT_WIRED = "not wired";

export interface CreatorFilters {
  q: string;
  platform: string;
  conn: string;
  employee: string;
  tag: string;
  status: string;
}
export const NO_FILTERS: CreatorFilters = { q: "", platform: "", conn: "", employee: "", tag: "", status: "" };

export const CONNECTIVITY_OPTIONS = ["Connected", "Disconnected", "Not connected", "Pending connection", "2FA required"] as const;

const ACCOUNT_STATUS_OPTIONS = ["Activated", "Deactivated"] as const;

// Text runs 0.03em tight: Sora sets wider than the bundle's font and "Account status" would overrun its box.
const BOX = cn(HbFilter, "px-[9px] tracking-[-0.03em] disabled:cursor-not-allowed disabled:opacity-50");
const CHEVRON = "pointer-events-none absolute right-[9px] top-1/2 h-4 w-4 -translate-y-1/2 text-[#a6a6a6] [html[data-theme=light]_&]:text-fg-dim";
const valueTone = (v: string | undefined) => (v ? "text-white [html[data-theme=light]_&]:text-fg" : "text-[#a6a6a6] [html[data-theme=light]_&]:text-fg-dim");

function Filter({ label, width, value, onChange, disabled, children }: {
  label: string;
  width: number;
  value?: string;
  onChange?: (v: string) => void;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <span className="relative inline-flex">
      <select
        aria-label={label}
        value={disabled ? "" : value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled}
        title={disabled ? NOT_WIRED : undefined}
        style={{ width }}
        className={cn(BOX, "appearance-none pr-[25px]", valueTone(disabled ? "" : value))}
      >
        <option value="">{label}</option>
        {children}
      </select>
      <ChevronDown aria-hidden className={CHEVRON} />
    </span>
  );
}

export default function CreatorFilterBar({ value, onChange, employees, connWired, tags = null }: {
  value: CreatorFilters;
  onChange: (next: CreatorFilters) => void;
  employees: ReadonlyArray<{ id: number; display_name: string }> | null;
  connWired: boolean;
  tags?: readonly string[] | null;
}) {
  const set = (patch: Partial<CreatorFilters>) => onChange({ ...value, ...patch });
  const [draft, setDraft] = useState(value.q);
  return (
    <form role="search" aria-label="Filter creators" onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-center gap-4">
      <input
        type="text"
        aria-label="Creator name"
        placeholder="Creator name"
        maxLength={50}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") set({ q: draft }); }}
        style={{ width: 203 }}
        className={BOX}
      />
      <Filter label="Platform" width={120} value={value.platform} onChange={(platform) => set({ platform })}>
        {PLATFORMS.map(({ key, label }) => <option key={key} value={key}>{label}</option>)}
      </Filter>
      <Filter label="Tag" width={102} value={value.tag} onChange={(tag) => set({ tag })} disabled={!tags}>
        {(tags ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
      </Filter>
      <Filter label="Connectivity status" width={174} value={value.conn} onChange={(conn) => set({ conn })} disabled={!connWired}>
        {CONNECTIVITY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </Filter>
      <EmployeeFilter value={value.employee} onChange={(employee) => set({ employee })} employees={employees} />
      <Filter label="Account status" width={138} value={value.status} onChange={(status) => set({ status })}>
        {ACCOUNT_STATUS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </Filter>
    </form>
  );
}

function EmployeeFilter({ value, onChange, employees }: {
  value: string;
  onChange: (id: string) => void;
  employees: ReadonlyArray<{ id: number; display_name: string }> | null;
}) {
  const listId = useId();
  const [typed, setTyped] = useState<string | null>(null);
  const picked = employees?.find((e) => String(e.id) === value)?.display_name ?? "";
  return (
    <span className="relative inline-flex">
      <input
        type="text"
        aria-label="Employee"
        placeholder="Employee"
        list={listId}
        value={employees ? typed ?? picked : ""}
        onChange={(e) => {
          const text = e.target.value;
          setTyped(text);
          if (!text) { onChange(""); return; }
          const hit = employees?.find((x) => x.display_name === text);
          if (hit) onChange(String(hit.id));
        }}
        onBlur={() => setTyped(null)}
        disabled={!employees}
        title={employees ? undefined : NOT_WIRED}
        style={{ width: 104 }}
        className={cn(BOX, "pr-[25px] [&::-webkit-calendar-picker-indicator]:hidden!")}
      />
      <ChevronDown aria-hidden className={CHEVRON} />
      <datalist id={listId}>
        {employees?.map((e) => <option key={e.id} value={e.display_name} />)}
      </datalist>
    </span>
  );
}
