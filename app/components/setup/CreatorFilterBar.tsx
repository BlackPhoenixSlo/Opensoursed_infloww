"use client";

/**
 * CreatorFilterBar — the filter form above the Manage creators table, as the Layout capture draws it
 * (docs/infloww-layouts/creators-manage.md #14 to #26): one inline row that wraps, the capture's six filters in its
 * order, each HB's filled filter box (ticket 00's `HbFilter`). No Reset, as the bundle has none (#14): a select clears
 * on its own first option, the name box by emptying it and pressing Enter. Presentational: AccountsTable holds the state and does the filtering, on the client, never in
 * the URL (docs/spec/infloww-parity-round-2/phase-04-creators-pages.md, Interfaces).
 *
 * ASSUMPTION: the filters' labels are keys with no English in the bundle on disk (the capture's Notes), so the words
 * are the Clone's, from the capture's Clone fixes for #18 to #26 (rung 3). Overturned by the en locale chunk.
 */

import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { HbFilter } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

const NOT_WIRED = "not wired";

export interface CreatorFilters {
  /** Creator name or id, applied on Enter (creators-manage#18). */
  q: string;
  /** "" for any, else a platform value. */
  platform: string;
  /** "" for any, else a connectivity label. */
  conn: string;
  /** "" for any, else an Employee id. */
  employee: string;
  /** "" for any, else a Tag (the account details' Tag, useCreatorProfiles). */
  tag: string;
  /** "" for any, else "Activated" or "Deactivated" (the account's `is_active`). */
  status: string;
}
export const NO_FILTERS: CreatorFilters = { q: "", platform: "", conn: "", employee: "", tag: "", status: "" };

/** The capture's connectivity options, in its order (creators-manage#23). "2FA required" is a login-job state that no
 *  stored Creator is in, so it matches no row (spec, Connectivity mapping).
 *  ASSUMPTION: no "ID verification" option. The ticket and the Inventory name one, but the bundle's options have none,
 *  and the capture's Notes say the bundle values stand (rung 1). Overturned by a bundle that lists it. */
export const CONNECTIVITY_OPTIONS = ["Connected", "Disconnected", "Not connected", "Pending connection", "2FA required"] as const;

/** Platform options (creators-manage#20); the gated mym and Fanvue are not shown, as in the Clone. */
const PLATFORM_OPTIONS = [["onlyfans", "OnlyFans"], ["fansly", "Fansly"]] as const;
/** Account status options (creators-manage#26). */
const ACCOUNT_STATUS_OPTIONS = ["Activated", "Deactivated"] as const;

/** A filter box: HB's filled #161616, no border, 28px tall, 14px text, the label and placeholder #a6a6a6 (01-home.png;
 *  ticket 00's `HbFilter`), 9px sides (creators-manage#16, #17).
 *  ASSUMPTION: the text runs 0.03em tight, because Sora sets wider than the bundle's font, and at its own spacing
 *  "Account status" (108px) overruns the 102px its 138px box leaves beside the arrow (#25), as "Employee" and
 *  "Connectivity status" do by 2px and 1px; tightened, each fits its capture width (rung 5). Overturned if the house
 *  font changes or the reviewer wants the boxes widened instead. */
const BOX = cn(HbFilter, "px-[9px] tracking-[-0.03em] disabled:cursor-not-allowed disabled:opacity-50");
/** The chevron, #a6a6a6 as the label (01-home.png). */
const CHEVRON = "pointer-events-none absolute right-[9px] top-1/2 h-4 w-4 -translate-y-1/2 text-[#a6a6a6]";
/** A select shows its own label (no value) in the placeholder's #a6a6a6, a picked value white. */
const valueTone = (v: string | undefined) => (v ? "text-white [html[data-theme=light]_&]:text-fg" : "text-[#a6a6a6]");

/** A select whose first option is its own label, the Clone's "first option Platform" (its Clone fix for #19). */
function Filter({ label, width, value, onChange, disabled, children }: {
  label: string;
  width: number;
  value?: string;
  onChange?: (v: string) => void;
  /** Not wired: disabled with the house marker. */
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    // The 16px arrow sits 9px from the right inside a 25px right padding, as the capture's Clone draws it (its Clone
    // fix for #17), so the label keeps the room antd gives it.
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
  /** The Employees to pick from; null when the read was refused or failed (Not wired). */
  employees: ReadonlyArray<{ id: number; display_name: string }> | null;
  /** False when the health read failed, so no row has a status to match. */
  connWired: boolean;
  /** The Tags in use; null when the profile read was refused (Not wired). */
  tags?: readonly string[] | null;
}) {
  const set = (patch: Partial<CreatorFilters>) => onChange({ ...value, ...patch });
  // What the name box holds until Enter applies it (`onPressEnter`; typing alone is skipped, creators-manage#18).
  // ASSUMPTION: the bundle's Enter replaces spec story 8's "as I type", as ticket 61 asks (rung 2). Overturned if the
  // owner rules as-you-type an intentional extra.
  const [draft, setDraft] = useState(value.q);
  return (
    // `layout:"inline"`, wrapping, 16px after each filter (creators-manage#14, #15).
    // ASSUMPTION: wrapped rows keep 16px between them, as the capture's Clone does at 390px (its Notes, rung 3).
    // Overturned by a 390px render of the bundle.
    <form role="search" aria-label="Filter creators" onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-center gap-4">
      {/* creators-manage#18: 203px, 50 characters. */}
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
      {/* creators-manage#19, #20. */}
      <Filter label="Platform" width={120} value={value.platform} onChange={(platform) => set({ platform })}>
        {PLATFORM_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </Filter>
      {/* creators-manage#21: the Tags the account details hold. */}
      <Filter label="Tag" width={102} value={value.tag} onChange={(tag) => set({ tag })} disabled={!tags}>
        {(tags ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
      </Filter>
      {/* creators-manage#22, #23. */}
      <Filter label="Connectivity status" width={174} value={value.conn} onChange={(conn) => set({ conn })} disabled={!connWired}>
        {CONNECTIVITY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </Filter>
      {/* creators-manage#24: Employees' Creator access, searched by name. */}
      <EmployeeFilter value={value.employee} onChange={(employee) => set({ employee })} employees={employees} />
      {/* creators-manage#25, #26. */}
      <Filter label="Account status" width={138} value={value.status} onChange={(status) => set({ status })}>
        {ACCOUNT_STATUS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </Filter>
    </form>
  );
}

/**
 * The Employee filter (creators-manage#24): 104px, `showSearch` and `allowClear`, its options kept by a part of their
 * name (`filterOption`: the label, lower-cased, `includes` what is typed). A text box over a datalist of the names: the
 * browser offers the names that hold what is typed, a whole name applies its Employee, and an empty box clears it.
 * ASSUMPTION: the browser's datalist stands in for antd's search popup, the smallest searchable select (rung 5); two
 * Employees with one name pick the first. Overturned if the reviewer wants antd's popup drawn.
 */
function EmployeeFilter({ value, onChange, employees }: {
  value: string;
  onChange: (id: string) => void;
  /** null: the read was refused or failed (Not wired). */
  employees: ReadonlyArray<{ id: number; display_name: string }> | null;
}) {
  const listId = useId();
  // What is typed; null shows the picked Employee's name.
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
        // Chrome's own datalist arrow would take the label's room beside our chevron; typing or the down arrow still
        // opens the list.
        className={cn(BOX, "pr-[25px] [&::-webkit-calendar-picker-indicator]:hidden!")}
      />
      <ChevronDown aria-hidden className={CHEVRON} />
      <datalist id={listId}>
        {employees?.map((e) => <option key={e.id} value={e.display_name} />)}
      </datalist>
    </span>
  );
}
