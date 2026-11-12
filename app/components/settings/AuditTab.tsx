"use client";

/**
 * AuditTab — paginated view of the `actions` table.
 *
 * Each row: who (employee chip) · when · what (method + path) · target
 * + an expandable payload row; below sm one 2-line cell. Filters (one
 * reducer, auditFilters.ts): employee, creator, from/to day, and "Show
 * system writes" (the app's own perflog/error pings, hidden server-side by
 * default so pagination stays right).
 * The action column shows the server's readable label (raw method + path
 * underneath) when the action map knows the route.
 *
 * Read-only. The middleware appends; this tab just renders. No infinite
 * scroll (yet) — Load more button keeps the surface area small.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useReducer, useState } from "react";

import { relay, type AccountMeta, type AuditAction, type Employee } from "@/lib/relay";
import { useRoster } from "@/hooks/useRoster";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { IfCreatorSelect, IfSelect } from "@/components/ui/infloww";
import { IF_BTN, SettingsPanel, SettingsTable, TABLE_CELL, TABLE_ROW } from "@/components/settings/SettingsPanel";
import {
  AUDIT_PAGE, INITIAL_AUDIT_FILTERS, auditFiltersReducer, buildAuditQuery, isFiltered,
} from "@/components/settings/auditFilters";
import { cn } from "@/lib/utils";

interface AuditResp { actions: AuditAction[]; limit: number; offset: number }

const DATE_FIELD =
  "h-8 rounded-[var(--if-input-radius)] border border-[var(--if-line)] bg-[var(--if-bg)] px-2 " +
  "text-[length:var(--if-fs)] text-[var(--if-fg)] outline-none focus:border-[var(--if-accent)]";

const ALL_EMPLOYEES = "";

export default function AuditTab() {
  const [f, dispatch] = useReducer(auditFiltersReducer, INITIAL_AUDIT_FILTERS);

  // Keep chatter mirrors so audit rows attributed to one still resolve a name.
  const { rows: roster } = useRoster({ includeChatterMirrors: true });
  const byId = useMemo(
    () => new Map<number, Employee>(roster.map((e) => [e.id, e])),
    [roster],
  );
  const accounts = useActiveAccounts();
  const accountById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  const query = buildAuditQuery(f);
  const auditQ = useQuery<AuditResp>({
    queryKey: ["audit", query],
    queryFn: () => relay.get<AuditResp>(`/admin/audit?${query}`),
    staleTime: 5_000,
  });

  const rows = auditQ.data?.actions ?? [];
  const canPaginate = rows.length === AUDIT_PAGE; // assume more if we got a full page

  return (
    <SettingsPanel title="Audit log">
      <div className="mb-4 flex flex-wrap items-center gap-2 text-[length:var(--if-fs)] text-[var(--if-fg-2)]">
        <IfSelect
          aria-label="Employee"
          className="w-full sm:w-44"
          value={f.employeeId == null ? ALL_EMPLOYEES : String(f.employeeId)}
          options={[{ value: ALL_EMPLOYEES, label: "All employees" },
            ...roster.map((e) => ({ value: String(e.id), label: e.display_name }))]}
          onChange={(v) => dispatch({ type: "employee", id: v ? Number(v) : null })}
        />
        <IfCreatorSelect
          className="w-full sm:w-48"
          accounts={accounts}
          value={f.accountId}
          onChange={(id) => dispatch({ type: "account", id })}
          onAll={() => dispatch({ type: "account", id: null })}
        />
        <span className="flex items-center gap-2">
          <input type="date" aria-label="From" value={f.fromDay} className={DATE_FIELD}
            onChange={(e) => dispatch({ type: "from", day: e.target.value })} />
          <span>to</span>
          <input type="date" aria-label="To" value={f.toDay} className={DATE_FIELD}
            onChange={(e) => dispatch({ type: "to", day: e.target.value })} />
        </span>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={f.system} className="accent-[var(--if-accent)]"
            onChange={(e) => dispatch({ type: "system", on: e.target.checked })} />
          Show system writes
        </label>
      </div>

      {auditQ.isLoading && <TableSkeleton rows={8} />}
      {auditQ.error && (
        <div role="alert" className="text-err text-[length:var(--if-fs)]">{(auditQ.error as Error).message || "failed"}</div>
      )}
      {!auditQ.isLoading && !auditQ.error && rows.length === 0 && (
        <div className="py-8 text-center text-[length:var(--if-fs)] text-[var(--if-fg-3)]">
          No audit entries{isFiltered(f) ? " for this filter" : ""}.
        </div>
      )}

      {rows.length > 0 && (
        <SettingsTable columns={[
          { label: "When", className: "hidden sm:table-cell w-40" },
          { label: "Who", className: "hidden sm:table-cell w-36" },
          "Action",
          { label: "Account", className: "hidden sm:table-cell w-36" },
        ]}>
          {rows.map((a) => {
            const emp = a.employee_id != null ? byId.get(a.employee_id) : null;
            const acc = a.account_id ? accountById.get(a.account_id) : undefined;
            return <AuditRow key={a.id} a={a} emp={emp ?? null} account={acc} />;
          })}
        </SettingsTable>
      )}

      <div className="mt-3 flex items-center justify-between text-[length:var(--if-fs)] text-[var(--if-fg-3)]">
        <span>
          Showing {rows.length === 0 ? 0 : f.offset + 1}–{f.offset + rows.length}
        </span>
        <div className="flex items-center gap-2">
          <button type="button" className={IF_BTN} disabled={f.offset === 0}
            onClick={() => dispatch({ type: "page", dir: "newer" })}>Newer</button>
          <button type="button" className={IF_BTN} disabled={!canPaginate}
            onClick={() => dispatch({ type: "page", dir: "older" })}>Older</button>
        </div>
      </div>
    </SettingsPanel>
  );
}

function AuditRow({ a, emp, account }: { a: AuditAction; emp: Employee | null; account?: AccountMeta }) {
  const [open, setOpen] = useState(false);
  const hasPayload =
    a.payload != null &&
    !(typeof a.payload === "object" && a.payload && Object.keys(a.payload as object).length === 0);
  const who = emp ? (
    <span className="inline-flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full bg-[var(--if-fg-3)]" style={emp.color ? { background: emp.color } : undefined} />
      {emp.display_name}
    </span>
  ) : (
    <span className="italic text-[var(--if-fg-3)]">system</span>
  );
  const accountText = account ? account.nickname || account.name || account.id : a.account_id ?? "—";

  return (
    <>
      <tr
        className={cn(TABLE_ROW, hasPayload && "cursor-pointer hover:bg-[var(--if-accent-bg)]/40")}
        onClick={() => hasPayload && setOpen((v) => !v)}
      >
        <td className={cn(TABLE_CELL, "hidden sm:table-cell text-[var(--if-fg-2)]")}>{fmtDateTime(a.at)}</td>
        <td className={cn(TABLE_CELL, "hidden sm:table-cell")}>{who}</td>
        <td className={cn(TABLE_CELL, "whitespace-normal py-2")}>
          {a.label && <span className="mr-2">{a.label}</span>}
          <code className={a.label ? "text-[10px] text-[var(--if-fg-3)]" : "text-xs"}>{a.action}</code>
          {hasPayload && (
            <span className="ml-2 text-[10px] text-[var(--if-fg-3)]">{open ? "▾" : "▸"}</span>
          )}
          <div className="sm:hidden mt-0.5 flex flex-wrap gap-x-2 text-xs text-[var(--if-fg-3)]">
            <span>{fmtDateTime(a.at)}</span>·{who}{a.account_id && <>·<span>{accountText}</span></>}
          </div>
        </td>
        <td className={cn(TABLE_CELL, "hidden sm:table-cell text-[var(--if-fg-2)] truncate max-w-36")}>{accountText}</td>
      </tr>
      {open && hasPayload && (
        <tr className={TABLE_ROW}>
          <td colSpan={4} className="px-3 pb-3 pt-0">
            <pre className="bg-[var(--if-bg)] border border-[var(--if-line)] rounded-md p-3 text-[10px] font-mono whitespace-pre-wrap break-all max-h-64 overflow-auto">
              {JSON.stringify(a.payload, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
