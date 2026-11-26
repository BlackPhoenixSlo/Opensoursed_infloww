"use client";


import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import DateRangePicker, { type RangePreset } from "@/components/stats/DateRangePicker";
import { EmptyState, IF_TABLE, IfButton, IfSelect, type IfOption } from "@/components/ui/infloww";
import { useUser } from "@/contexts/UserContext";
import { useAccounts } from "@/hooks/useAccounts";
import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";
import { useReportRange } from "@/hooks/useReportRange";
import { useRoster } from "@/hooks/useRoster";
import { reassignChoices, attributeTo, type ReassignEmployee } from "@/components/analytics/ReassignOptions";
import { MAX_BATCH, useAttributeTip, useBatchAttribute, type SaleRef } from "@/hooks/useStats";
import { groupsInTreeOrder, useEmployeeGroups } from "@/lib/employeeGroups";
import { fmtPrice } from "@/lib/format";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { InfoTip } from "@/components/ui/InfoTip";

const ROUTE = "/admin/stats/sales-records";

export const SALES_TYPES: { kind: string; label: string }[] = [
  { kind: "ppv", label: "PPV" },
  { kind: "ppv_message", label: "PPV message" },
  { kind: "ppv_post", label: "PPV post" },
  { kind: "ppv_stream", label: "PPV stream" },
  { kind: "tip", label: "Tip" },
  { kind: "tip_post", label: "Tip on post" },
  { kind: "tip_stream", label: "Tip on stream" },
  { kind: "custom", label: "Custom" },
  { kind: "subscription", label: "Subscription" },
  { kind: "rebill", label: "Rebill" },
  { kind: "referral", label: "Referral" },
];

const RULE_LABELS: Record<string, string> = {
  manual: "Manual",
  message: "Message sender",
  converters: "Converters",
  shift: "Shift schedule",
  unassigned: "Unassigned",
};

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

const DATE_PRESETS = ["day", "7d", "30d"] as const;
const DATE_LABELS = { "7d": "Week", "30d": "Month" };
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
  employeeId: string;
  kind: string;
  assigned: string;
}

const GROUP = "group:";

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

function fmtWhen(iso: string, timeZone: string | null): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone ?? undefined, year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.month} ${p.day}, ${p.year} ${p.hour}:${p.minute}${(p.dayPeriod ?? "").toLowerCase()}`;
}

const CELL = cn(IF_TABLE.td, "whitespace-nowrap py-2 h-12");
const HEAD = cn(IF_TABLE.th, IF_TABLE.thDivider);

const saleRef = (r: SalesRecord): SaleRef => ({ txId: r.tx_id, accountId: r.account_id });
const sameSale = (a: SaleRef) => (b: SaleRef) => a.txId === b.txId && a.accountId === b.accountId;

function BatchReassign({ sales, employees, capped, onDone }: {
  sales: SaleRef[]; employees: ReassignEmployee[]; capped: boolean; onDone: () => void;
}) {
  const [choice, setChoice] = useState("");
  const batch = useBatchAttribute();
  const save = () => batch.mutate(
    { employeeId: attributeTo(choice), sales },
    { onSuccess: () => { setChoice(""); onDone(); } },
  );
  return (
    <div role="group" aria-label="Batch reassign" className="flex flex-wrap items-center gap-2 py-2 text-[14px]">
      <span className="font-medium text-fg">
        {`${sales.length} sales record${sales.length === 1 ? "" : "s"} selected`}
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

function ReassignCell({ txId, accountId, employees }: { txId: number; accountId: string; employees: ReassignEmployee[] }) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("");
  const attribute = useAttributeTip();
  if (!open) {
    return <IfButton onClick={() => { setChoice(""); setOpen(true); }}>Reassign</IfButton>;
  }
  const save = () => attribute.mutate(
    { txId, accountId, employeeId: attributeTo(choice) },
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

// Pending (uncleared) sales count as earnings: shown as Status "Pending" and included in the CSV.
export default function SalesRecords() {
  const { user } = useUser();
  const { preset, from: fromDay, to: toDay, fromIso, toIso, reportTz, ready, handleRange } = useReportRange();
  const accounts = useAccounts().data?.accounts ?? [];
  const employees = useRoster({ includeChatterMirrors: true }).rows;
  const pickers = employees.map((e) => ({ id: e.id, label: e.display_name }));
  const groups = groupsInTreeOrder(useEmployeeGroups(!!user).data?.groups ?? []);

  const [accountId, setAccountId] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [kind, setKind] = useState("");
  const [assigned, setAssigned] = useState("");

  const qs = filterQuery({ from: fromIso, to: toIso, accountId, employeeId, kind, assigned });
  const [picked, setPicked] = useState<{ query: string; ids: SaleRef[] }>({ query: "", ids: [] });
  const selected = picked.query === qs.toString() ? picked.ids : [];
  const select = (ids: SaleRef[]) => setPicked({ query: qs.toString(), ids });
  const isPicked = (ref: SaleRef) => selected.some(sameSale(ref));
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
  const loadedIds = [...new Map(rows.map((r): [string, SaleRef] => [`${r.account_id}:${r.tx_id}`, saleRef(r)])).values()];
  const pickable = loadedIds.slice(0, MAX_BATCH);
  const allPicked = pickable.length > 0 && pickable.every(isPicked);
  const full = selected.length >= MAX_BATCH;

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = pages;
  const sentinel = useLoadMoreSentinel(hasNextPage, isFetchingNextPage, fetchNextPage, pages.isError);

  const creatorName = (id: string) => accounts.find((a) => a.id === id)?.nickname || id;
  const typeLabel = (k: string) => SALES_TYPES.find((t) => t.kind === k)?.label ?? k;

  let body;
  if (pages.isError) {
    body = <EmptyState kind="error" text={pages.error.message} onRetry={() => pages.refetch()} className="py-12" />;
  } else if (pages.isPending) {
    body = <TableSkeleton rows={8} className="m-4" />;
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
                      <InfoTip text={EARNINGS_TIP} />
                    </span>
                  ) : c}
                </th>
              ))}
              {user && <th className={cn(HEAD, IF_TABLE.fixedRightHead, IF_TABLE.unpinPhone)}>Action</th>}
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
                        checked={isPicked(saleRef(r))}
                        disabled={full && !isPicked(saleRef(r))}
                        onChange={() => select(isPicked(saleRef(r))
                          ? selected.filter((p) => !sameSale(p)(saleRef(r))) : [...selected, saleRef(r)])} />
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
                    <td className={cn(CELL, IF_TABLE.fixedRight, IF_TABLE.unpinPhone)}>
                      <ReassignCell txId={r.tx_id} accountId={r.account_id} employees={pickers} />
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
      <div className="flex items-start justify-between gap-4 max-sm:flex-wrap">
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
        <CsvExportButton path={ROUTE} query={csvQuery.toString()} label="Export" icon={Upload}
          title="Download the filtered sales as CSV (up to 50,000 rows)" />
      </div>

      <section aria-label="Sales records">
        {user && selected.length > 0 && (
          <BatchReassign sales={selected} employees={pickers} onDone={() => select([])}
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
