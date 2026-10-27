"use client";

/**
 * SalesRecords — Analytics > Sales records (docs/spec/phase-05-remaining-parity-gaps.md, item 3; ticket 33,
 * stories 19-21, 25, 26 and 29): one row per sale from `GET /admin/stats/sales-records`, with the Rule that
 * credited it and who assigned it. In Infloww it is the second tab of Employee reports (bundle `SalesRecord`,
 * `SalesFilter`, `SalesTable`); page-parity ticket 28 gives it that tab's body.
 *
 * It is the tab's body alone (the toolbar, the batch bar, the table): Employee reports' frame (EmployeeReport, on
 * both its routes) draws the title, the UTC label and the icon Refresh.
 *
 * Toolbar, in the bundle's order: Creator tag (Not wired: Creators carry no tags), Creator, Employees/groups,
 * the assigned filter, Sales types, then the range (Day / Week / Month / Custom, in the Agency's report time zone,
 * through the shared `DateRangePicker`) and Reset; Export at the right downloads the Relay's CSV of the whole
 * filtered set (50,000 rows at most). Rows load as the end of the table scrolls into view (`before_id` pages), then
 * "You have reached the end of the page". Under Role enforcement the Relay narrows a chatter's rows to its Data
 * scope; the page shows what it is given.
 *
 * Earnings: every row the read returns counts, pending (uncleared) sales included: they show with Status
 * "Pending" under the default filters and are in the CSV.
 *
 * Action > "Reassign" (ticket 34, stories 22 and 23): an owner picks another Employee of the Agency, "No one" or
 * "Clear assignment", and Save sends the existing manual attribute route (`useAttributeTip`, body
 * `{employee_id|"no_one"|null}`), which refuses a chatter, another Agency's sale and an Employee outside the sale's
 * Agency, and records the `sales.reassign` action that "Assigned by" reads. Saving refetches the read, so the row's
 * Employee, Rule and Assigned by are the Relay's answer. "No one" (roadmap W6 6.5) credits the sale to nobody
 * whatever the Rules say; its row reads Employee "No one", Rule "Manual".
 *
 * Batch (roadmap W6 6.5, Infloww's "N sales records selected"): each row's checkbox, or "Select all" in the
 * selection column's head for the loaded rows, picks sales; the bar above the table reassigns them in one call
 * (`useBatchAttribute`, every sale or none). A batch holds at most MAX_BATCH (500) sales, the Relay's cap: "Select
 * all" picks the first 500 loaded, a row past it cannot be ticked, and the bar says so. A filter change drops the
 * selection.
 *
 * The assigned filter (bundle `baseOptions`): Assigned and unassigned sales, Assigned sales only or Unassigned sales
 * only, sent as `assigned`. As in Infloww, "Unassigned sales only" is disabled while an Employee or group is picked,
 * and the Employees/groups filter while it is chosen (the two together match nothing).
 *
 * ASSUMPTION: the page opens on (and Reset returns to) Assigned and unassigned sales and Month, although Infloww's
 * form opens on and resets to "Assigned sales only". Rung 3 (ticket 28: Reset sends no filter params; an agency
 * checks its unassigned sales first). Overturned by the owner wanting Infloww's default.
 *
 * ASSUMPTION: the picker lists the roster `GET /admin/employees` returns (`useRoster`, Mirror Employees and
 * deactivated Employees included, as the Employees filter), which the Relay scopes to the owner's Agency; for the
 * Master that roster is every Agency's, and the Relay's 400 refuses an Employee outside the sale's Agency. Rung 3
 * (the Employees filter's own source). Overturned if the picker should narrow by Creator access (`account_ids`),
 * which no Mirror Employee carries today, or hide deactivated Employees.
 *
 * ASSUMPTION: the selection column, the Action column and Reassign show for an owner session only, as the Employees
 * filter does; a chatter, whom the Relay refuses 403, gets none. Rung 3. Overturned if the owner grants Reassign to
 * a role.
 *
 * ASSUMPTION: Creator, Employees and Sales types are single-choice selects ("All …" or one value), although the
 * Relay takes several of each (`account_id*`, `employee_id*`, `kind*`). Rung 5: no multi-select primitive in the
 * app. Overturned if the owner wants several at once, which needs only the select changed.
 *
 * ASSUMPTION: Day is today, and Week and Month are the reports' own 7d and 30d presets (`presetRange`: the last 7
 * or 30 days through today, in the report time zone), so Month is Employee reports' 30d window; the page opens on
 * Month, as the other reports open on 30d (useReportRange). Rung 3 (the shared picker) for the spans; the Inventory
 * names the presets only. Overturned by Infloww's own preset definitions.
 *
 * ASSUMPTION: the Employees filter's options are the Agency's roster (`GET /admin/employees`), read only for an
 * owner session; a chatter, whom that list refuses (403), gets no Employees filter. Rung 3 (the Relay's own
 * rule, phase-05 story 13). Overturned if chatters with an "all" Data scope should filter by Employee.
 *
 * The Employees filter also lists the Agency's Employee groups (ticket 36, story 20; `useEmployeeGroups`, in tree
 * order) as "Group: …" choices; picking one sends `group_id` in place of `employee_id`, so one choice is one filter.
 *
 * Status is Infloww's pill (bundle `styles.status`): Complete (`cleared`), Pending (`pending`), Reverse
 * (`chargedback`) and Refunded (`refunded`, `refund_pending`). The read lists tracked sales only (`cleared`,
 * `pending`), so the two reversal labels show only if it ever lists reversals.
 */

import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Info, Upload } from "lucide-react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import DateRangePicker, { type RangePreset } from "@/components/stats/DateRangePicker";
import { EmptyState, IF_TABLE, IfButton, IfSelect, type IfOption } from "@/components/ui/infloww";
import { useUser } from "@/contexts/UserContext";
import { useAccounts } from "@/hooks/useAccounts";
import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";
import { useReportRange } from "@/hooks/useReportRange";
import { useRoster } from "@/hooks/useRoster";
import { reassignChoices, attributeTo, type ReassignEmployee } from "@/components/analytics/ReassignOptions";
import { MAX_BATCH, useAttributeTip, useBatchAttribute } from "@/hooks/useStats";
import { groupsInTreeOrder, useEmployeeGroups } from "@/lib/employeeGroups";
import { fmtPrice } from "@/lib/format";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

const ROUTE = "/admin/stats/sales-records";

/** The sale kinds the attribution view carries, with their Type labels. */
export const SALES_TYPES: { kind: string; label: string }[] = [
  { kind: "ppv", label: "PPV" },
  { kind: "ppv_message", label: "PPV message" },
  { kind: "ppv_post", label: "PPV post" },
  { kind: "ppv_stream", label: "PPV stream" },
  { kind: "tip", label: "Tip" },
  { kind: "tip_post", label: "Tip on post" },
  { kind: "tip_stream", label: "Tip on stream" },
  { kind: "custom", label: "Custom" },
];

const RULE_LABELS: Record<string, string> = {
  manual: "Manual",
  message: "Message sender",
  converters: "Converters",
  shift: "Shift schedule",
  unassigned: "Unassigned",
};

// Infloww's status pills (bundle `_status_1uff5`: 14px, radius 24, 4px 8px; the HB signal colours).
const REFUNDED = "bg-[#fb609f] text-white [html[data-theme=light]_&]:bg-[#ff5c9e]";
const STATUS: Record<string, { label: string; className: string }> = {
  cleared: { label: "Complete", className: "bg-ok text-white" },
  pending: { label: "Pending", className: "bg-[#af9423] text-white [html[data-theme=light]_&]:bg-[#b8991a]" },
  chargedback: {
    label: "Reverse",
    className: "bg-white/[.09] text-white/[.62] [html[data-theme=light]_&]:bg-black/[.09] [html[data-theme=light]_&]:text-black/[.62]",
  },
  refunded: { label: "Refunded", className: REFUNDED },
  refund_pending: { label: "Refunded", className: REFUNDED },
};

const COLUMNS = [
  "Date & time", "Employee", "Creator", "Fan", "Earnings", "Gross revenue", "Net revenue", "Type", "Rule",
  "Assigned by", "Status",
];
const EARNINGS_TIP = "Earnings shown are based on the organization’s sales settings";

export interface SalesRecord {
  tx_id: number;
  occurred_at: string;
  employee_id: number | null;
  employee_name: string | null;
  account_id: string;
  fan_id: number | null;
  fan_label: string | null;
  earnings_cents: number;
  gross_cents: number;
  net_cents: number | null;
  kind: string;
  rule: string;
  assigned_by: string;
  status: string;
}

interface SalesRecordsPage {
  rows: SalesRecord[];
  next_before_id: number | null;
}

/** Infloww's Date presets (docs/infloww-screens.md, Sales records) on the shared picker's spans; Day keeps the
 *  picker's own label. */
const DATE_PRESETS = ["day", "7d", "30d"] as const;
const DATE_LABELS = { "7d": "Week", "30d": "Month" };
/** The range Reset returns to: useReportRange's opening preset. */
const DEFAULT_PRESET: RangePreset = "30d";

const assignedOptions = (employeePicked: boolean): IfOption[] => [
  { value: "", label: "Assigned and unassigned sales" },
  { value: "assigned", label: "Assigned sales only" },
  { value: "unassigned", label: "Unassigned sales only", disabled: employeePicked },
];

interface Filters {
  from: string | null;
  to: string | null;
  accountId: string;
  /** An Employee id, or GROUP + an Employee group id. */
  employeeId: string;
  kind: string;
  /** "" (all sales), "assigned" or "unassigned". */
  assigned: string;
}

/** The Employees filter's value prefix for an Employee group. */
const GROUP = "group:";

/** The read's query string for these filters (no paging: `before_id` is per page, and CSV takes none). */
function filterQuery(f: Filters): URLSearchParams {
  const qs = new URLSearchParams();
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  if (f.accountId) qs.append("account_id", f.accountId);
  if (f.employeeId.startsWith(GROUP)) qs.set("group_id", f.employeeId.slice(GROUP.length));
  else if (f.employeeId) qs.append("employee_id", f.employeeId);
  if (f.kind) qs.append("kind", f.kind);
  if (f.assigned) qs.set("assigned", f.assigned);
  return qs;
}

/** Infloww's "MMM D, YYYY h:mma" ("May 4, 2026 10:00am") in the report time zone. */
function fmtWhen(iso: string, timeZone: string | null): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone ?? undefined, year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.month} ${p.day}, ${p.year} ${p.hour}:${p.minute}${(p.dayPeriod ?? "").toLowerCase()}`;
}

const CELL = cn(IF_TABLE.td, "whitespace-nowrap py-2 h-12");
const HEAD = cn(IF_TABLE.th, IF_TABLE.thDivider);

/** The batch bar: how many sales are selected, a picker, "Reassign selected" and "Clear selection". */
function BatchReassign({ txIds, employees, capped, onDone }: {
  txIds: number[]; employees: ReassignEmployee[]; capped: boolean; onDone: () => void;
}) {
  const [choice, setChoice] = useState("");
  const batch = useBatchAttribute();
  const save = () => batch.mutate(
    { employeeId: attributeTo(choice), txIds },
    { onSuccess: () => { setChoice(""); onDone(); } },
  );
  return (
    <div role="group" aria-label="Batch reassign" className="flex flex-wrap items-center gap-2 py-2 text-[14px]">
      <span className="font-medium text-fg">
        {`${txIds.length} sales record${txIds.length === 1 ? "" : "s"} selected`}
      </span>
      <IfSelect aria-label="Reassign selected to" value={choice} onChange={setChoice} searchable
        options={reassignChoices(employees, true)} placeholder="Choose an employee" className="w-[200px]" />
      <IfButton variant="primary" onClick={save} disabled={!choice || batch.isPending}>Reassign selected</IfButton>
      <IfButton onClick={onDone} disabled={batch.isPending}>Clear selection</IfButton>
      {capped && (
        <span className="text-fg-dim">{`At most ${MAX_BATCH} sales per batch: reassign these, then select the rest.`}</span>
      )}
      {batch.isError && <span className="text-err">{batch.error.message}</span>}
    </div>
  );
}

/** The Action cell: "Reassign", then a picker (`reassignChoices`), Save and Cancel. */
function ReassignCell({ txId, employees }: { txId: number; employees: ReassignEmployee[] }) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("");
  const attribute = useAttributeTip();
  if (!open) {
    return <IfButton onClick={() => { setChoice(""); setOpen(true); }}>Reassign</IfButton>;
  }
  const save = () => attribute.mutate(
    { txId, employeeId: attributeTo(choice) },
    { onSuccess: () => setOpen(false) },
  );
  return (
    <div className="flex items-center gap-2">
      <IfSelect aria-label="Reassign to" value={choice} onChange={setChoice} searchable
        options={reassignChoices(employees, true)} placeholder="Choose an employee" className="w-[180px]" />
      <IfButton variant="primary" onClick={save} disabled={!choice || attribute.isPending}>Save</IfButton>
      <IfButton onClick={() => setOpen(false)} disabled={attribute.isPending}>Cancel</IfButton>
      {attribute.isError && <span className="text-[12px] text-err">{attribute.error.message}</span>}
    </div>
  );
}

export default function SalesRecords() {
  const { user } = useUser();
  const { preset, from: fromDay, to: toDay, fromIso, toIso, reportTz, ready, handleRange } = useReportRange();
  const accounts = useAccounts().data?.accounts ?? [];
  // The Agency's roster, Mirror Employees included: the Employees filter's and Reassign's options.
  const employees = useRoster({ includeChatterMirrors: true }).rows;
  const pickers = employees.map((e) => ({ id: e.id, label: e.display_name }));
  const groups = groupsInTreeOrder(useEmployeeGroups(!!user).data?.groups ?? []);

  const [accountId, setAccountId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [kind, setKind] = useState("");
  const [assigned, setAssigned] = useState("");

  const qs = filterQuery({ from: fromIso, to: toIso, accountId, employeeId, kind, assigned });
  // The batch selection, kept for the filters it was made under only.
  const [picked, setPicked] = useState<{ query: string; ids: number[] }>({ query: "", ids: [] });
  const selected = picked.query === qs.toString() ? picked.ids : [];
  const select = (ids: number[]) => setPicked({ query: qs.toString(), ids });
  const csvQuery = new URLSearchParams(qs);
  csvQuery.set("format", "csv");

  const reset = () => {
    setAccountId("");
    setEmployeeId("");
    setKind("");
    setAssigned("");
    handleRange(null, null, DEFAULT_PRESET);
    select([]);
  };

  const pages = useInfiniteQuery<SalesRecordsPage>({
    queryKey: ["stats", "sales-records", qs.toString()],
    initialPageParam: null,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
    queryFn: ({ pageParam, signal }) => {
      const page = new URLSearchParams(qs);
      if (pageParam != null) page.set("before_id", String(pageParam));
      return relay.get<SalesRecordsPage>(`${ROUTE}?${page.toString()}`, undefined, signal);
    },
    enabled: ready,
  });
  const rows = pages.data?.pages.flatMap((p) => p.rows) ?? [];
  const loadedIds = [...new Set(rows.map((r) => r.tx_id))];
  const pickable = loadedIds.slice(0, MAX_BATCH);
  const allPicked = pickable.length > 0 && pickable.every((id) => selected.includes(id));
  const full = selected.length >= MAX_BATCH;

  // Infinite scroll: the next page loads when the sentinel under the table comes within 200px of the viewport.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = pages;
  const sentinel = useLoadMoreSentinel(hasNextPage, isFetchingNextPage, fetchNextPage);

  const creatorName = (id: string) => accounts.find((a) => a.id === id)?.nickname || id;
  const typeLabel = (k: string) => SALES_TYPES.find((t) => t.kind === k)?.label ?? k;

  let body;
  if (pages.isError) {
    body = <EmptyState kind="error" text={pages.error.message} onRetry={() => pages.refetch()} className="py-12" />;
  } else if (pages.isPending) {
    body = <p className="p-4 text-[14px] text-fg-dim">Loading…</p>;
  } else if (rows.length === 0) {
    body = <EmptyState className="py-12" />;
  } else {
    body = (
      <div className="overflow-x-auto">
        <table className={IF_TABLE.table}>
          <thead>
            <tr>
              {user && (
                <th className={cn(HEAD, "w-12")}>
                  <input type="checkbox" aria-label="Select all" checked={allPicked} className="accent-accent"
                    onChange={() => select(allPicked ? [] : pickable)} />
                </th>
              )}
              {COLUMNS.map((c) => (
                <th key={c} className={HEAD}>
                  {c === "Earnings" ? (
                    <span className="inline-flex items-center gap-1">
                      Earnings
                      <span role="img" aria-label={EARNINGS_TIP} title={EARNINGS_TIP} className="cursor-help">
                        <Info className="h-3.5 w-3.5" aria-hidden />
                      </span>
                    </span>
                  ) : c}
                </th>
              ))}
              {user && <th className={cn(HEAD, IF_TABLE.fixedRightHead)}>Action</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const status = STATUS[r.status];
              return (
                // A split sale is one row per credited Employee and Rule: the sale id alone repeats.
                <tr key={`${r.tx_id}:${r.employee_id}:${r.rule}`} className={IF_TABLE.row}>
                  {user && (
                    <td className={CELL}>
                      <input type="checkbox" aria-label={`Select sale ${r.tx_id}`} className="accent-accent"
                        checked={selected.includes(r.tx_id)}
                        disabled={full && !selected.includes(r.tx_id)}
                        onChange={() => select(selected.includes(r.tx_id)
                          ? selected.filter((id) => id !== r.tx_id) : [...selected, r.tx_id])} />
                    </td>
                  )}
                  <td className={cn(CELL, "tabular-nums")}>{fmtWhen(r.occurred_at, reportTz)}</td>
                  <td className={CELL}>
                    {r.employee_name
                      ?? (r.employee_id != null ? `Employee #${r.employee_id}` : r.rule === "manual" ? "No one" : "Unassigned")}
                  </td>
                  <td className={CELL}>{creatorName(r.account_id)}</td>
                  <td className={CELL}>{r.fan_label ?? (r.fan_id != null ? `Fan #${r.fan_id}` : "—")}</td>
                  <td className={cn(CELL, "tabular-nums")}>{fmtPrice(r.earnings_cents)}</td>
                  <td className={cn(CELL, "tabular-nums")}>{fmtPrice(r.gross_cents)}</td>
                  <td className={cn(CELL, "tabular-nums")}>{r.net_cents == null ? "—" : fmtPrice(r.net_cents)}</td>
                  <td className={CELL}>{typeLabel(r.kind)}</td>
                  <td className={CELL}>{RULE_LABELS[r.rule] ?? r.rule}</td>
                  <td className={CELL}>{r.assigned_by}</td>
                  <td className={CELL}>
                    <span className={cn("rounded-[24px] px-2 py-1 text-[14px]", status?.className ?? "text-fg")}>
                      {status?.label ?? r.status}
                    </span>
                  </td>
                  {user && (
                    <td className={cn(CELL, IF_TABLE.fixedRight)}>
                      <ReassignCell txId={r.tx_id} employees={pickers} />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span title="not wired">
            <IfSelect aria-label="Creator tag" value="" options={[]} onChange={() => {}} disabled
              placeholder="Creator tag" className="w-[140px]" />
          </span>
          <IfSelect aria-label="Creator" value={accountId} onChange={setAccountId} searchable className="w-[160px]"
            options={[
              { value: "", label: "All creators" },
              ...accounts.map((a) => ({ value: a.id, label: a.nickname || a.id })),
            ]} />
          {user && (
            <IfSelect aria-label="Employees" value={employeeId} onChange={setEmployeeId} searchable
              disabled={assigned === "unassigned"} className="w-[210px]"
              options={[
                { value: "", label: "All employees" },
                ...employees.map((e) => ({ value: String(e.id), label: e.display_name })),
                ...groups.map(({ group }) => ({ value: `${GROUP}${group.id}`, label: `Group: ${group.name}` })),
              ]} />
          )}
          <IfSelect aria-label="Assigned" value={assigned} onChange={setAssigned} className="w-[272px]"
            options={assignedOptions(!!employeeId)} />
          <IfSelect aria-label="Sales types" value={kind} onChange={setKind} className="w-[160px]"
            options={[
              { value: "", label: "All sales types" },
              ...SALES_TYPES.map((t) => ({ value: t.kind, label: t.label })),
            ]} />
          <DateRangePicker from={fromDay} to={toDay} preset={preset} onChange={handleRange} timeZone={reportTz}
            presets={DATE_PRESETS} labels={DATE_LABELS} />
          <button type="button" onClick={reset}
            className="ml-2 text-[14px] font-medium text-cta hover:opacity-80">
            Reset
          </button>
        </div>
        <CsvExportButton path={ROUTE} query={csvQuery.toString()} look="infloww" label="Export" icon={Upload}
          title="Download the filtered sales as CSV (up to 50,000 rows)" />
      </div>

      <section aria-label="Sales records">
        {user && selected.length > 0 && (
          <BatchReassign txIds={selected} employees={pickers} onDone={() => select([])}
            capped={full && loadedIds.length > selected.length} />
        )}
        {body}
        {hasNextPage && (
          <div ref={sentinel} className="py-4 text-center text-[14px] text-fg-dim">
            {isFetchingNextPage ? "Loading…" : null}
          </div>
        )}
        {!hasNextPage && rows.length > 0 && !pages.isError && (
          <p className="py-8 text-center text-[16px] text-white/[.38] [html[data-theme=light]_&]:text-black/[.38]">
            You have reached the end of the page
          </p>
        )}
      </section>
    </div>
  );
}
