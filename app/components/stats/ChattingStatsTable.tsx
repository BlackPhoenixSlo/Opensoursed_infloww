"use client";



import { useMemo, useState } from "react";

import { CLOCKED_HOURS_TIP } from "@/components/stats/ClockedHoursCard";
import ExportMenu from "@/components/stats/ExportMenu";
import { employeeExport } from "@/components/stats/employeeExport";
import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { type ChattingStatsRow, useChattingStats } from "@/hooks/useStats";
import { fmtCents, fmtInt, fmtPrice, fmtReplyTime, growthOf } from "@/lib/format";
import { useOptionalUser } from "@/contexts/UserContext";
import { RelayError } from "@/lib/relay";
import { calcMinutes, useTimesheet, type TimesheetRow } from "@/lib/shifts";
import { cn } from "@/lib/utils";
import { InfoTip } from "@/components/ui/InfoTip";

type NumKey = Exclude<
  { [K in keyof ChattingStatsRow]: ChattingStatsRow[K] extends number | null ? K : never }[keyof ChattingStatsRow],
  "employee_id" | "replies"
>;
type Key = NumKey | "display_name";

const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(2)}%`);
const rate = (v: number | null) => (v == null ? "—" : v.toFixed(2));

const COLUMNS: {
  key: NumKey; label: string; tip: string; fmt: (r: ChattingStatsRow) => string; lowerIsBetter?: boolean;
}[] = [
  { key: "sales_cents", label: "Sales", tip: "Total sales generated, according to your sales settings",
    fmt: (r) => fmtCents(r.sales_cents) },
  { key: "ppv_sales_cents", label: "PPV sales", tip: "Sales generated from PPVs, according to your sales settings",
    fmt: (r) => fmtCents(r.ppv_sales_cents) },
  { key: "tip_sales_cents", label: "Tips", tip: "Sales generated from tips, according to your sales settings",
    fmt: (r) => fmtCents(r.tip_sales_cents) },
  { key: "direct_message_sales_cents", label: "Direct message sales",
    tip: "Sales generated from messages sent to fans by employee. Does not include mass messages or automated messages",
    fmt: (r) => fmtCents(r.direct_message_sales_cents) },
  { key: "priority_mass_message_sales_cents", label: "Priority mass messages sales",
    tip: "Sales generated from priority mass messages sent",
    fmt: (r) => fmtCents(r.priority_mass_message_sales_cents) },
  { key: "mass_message_sales_cents", label: "OF mass messages sales",
    tip: "Sales generated from OF mass messages sent by employee", fmt: (r) => fmtCents(r.mass_message_sales_cents) },
  { key: "direct_messages_sent", label: "Direct messages sent",
    tip: "Number of messages sent to fans by employee, including PPVs. Does not include mass messages or automated messages",
    fmt: (r) => fmtInt(r.direct_messages_sent) },
  { key: "direct_ppvs_sent", label: "Direct PPVs sent",
    tip: "Number of PPVs sent to fans by employee. Does not include PPVs sent through mass messages or automated messages",
    fmt: (r) => fmtInt(r.direct_ppvs_sent) },
  { key: "golden_ratio", label: "Golden ratio",
    tip: "Percentage of direct messages sent that were PPVs: direct PPVs sent divided by direct messages sent, × 100",
    fmt: (r) => pct(r.golden_ratio) },
  { key: "ppvs_unlocked", label: "PPVs unlocked",
    tip: "Number of direct PPVs sent by employee that were unlocked by fans, counted on the date the PPV was sent",
    fmt: (r) => fmtInt(r.ppvs_unlocked) },
  { key: "unlock_rate", label: "Unlock rate",
    tip: "Percentage of direct PPVs sent that were unlocked by fans, by the date the PPV was sent", fmt: (r) => pct(r.unlock_rate) },
  { key: "fans_chatted", label: "Fans chatted",
    tip: "Number of unique fans that employee sent at least one message to. Does not include mass messages or automated messages",
    fmt: (r) => fmtInt(r.fans_chatted) },
  { key: "fans_who_spent", label: "Fans who spent money",
    tip: "Number of unique fans who tipped or purchased PPVs from messages sent by employee directly",
    fmt: (r) => fmtInt(r.fans_who_spent) },
  { key: "fan_cvr", label: "Fan CVR",
    tip: "Fans who spent money divided by fans chatted, × 100", fmt: (r) => pct(r.fan_cvr) },
  { key: "avg_spend_per_fan_cents", label: "Avg earnings per fan who spent money",
    tip: "Average spent by each fan who spent money, through direct messages and tips",
    fmt: (r) => fmtPrice(r.avg_spend_per_fan_cents) },
  { key: "character_count", label: "Character count",
    tip: "Total number of characters in messages sent by employee. Does not include mass messages or automated messages",
    fmt: (r) => fmtInt(r.character_count) },
  { key: "avg_reply_seconds", label: "Response time",
    tip: "Average time taken by employee to reply to a fan, from the fan's first unanswered message. Does not include unreplied messages, or chats a mass or automated message answered first",
    fmt: (r) => fmtReplyTime(r.avg_reply_seconds), lowerIsBetter: true },
  { key: "clocked_minutes", label: "Clocked hours", tip: CLOCKED_HOURS_TIP,
    fmt: (r) => (r.clocked_minutes == null ? "—" : calcMinutes(r.clocked_minutes)) },
  { key: "sales_per_clocked_hour_cents", label: "Sales per clocked hour",
    tip: "Average sales for every hour worked, based on clocked time. Includes sales through direct messages and tips",
    fmt: (r) => fmtPrice(r.sales_per_clocked_hour_cents) },
  { key: "messages_per_clocked_hour", label: "Messages sent per clocked hour",
    tip: "Average number of direct messages sent for every hour worked, based on clocked time",
    fmt: (r) => rate(r.messages_per_clocked_hour) },
  { key: "fans_chatted_per_clocked_hour", label: "Fans chatted per clocked hour",
    tip: "Number of fans that employee chats with every hour, based on clocked time",
    fmt: (r) => rate(r.fans_chatted_per_clocked_hour) },
];

const CLOCKED: NumKey[] = ["clocked_minutes", "sales_per_clocked_hour_cents", "messages_per_clocked_hour",
  "fans_chatted_per_clocked_hour"];

const CELL = "whitespace-nowrap";
const PIN_EMP = "sticky left-0 z-[1] w-40 min-w-40 max-w-40";
const PIN_CREATORS = "sticky left-40 z-[1] max-w-48 shadow-[6px_0_6px_-4px_rgba(0,0,0,.35)] [html[data-theme=light]_&]:shadow-[6px_0_6px_-4px_#f5f6fa]";

const EXPORT_OUTLINE = "h-6 gap-1.5 rounded-[4px] border border-accent bg-transparent px-2 py-0 text-[14px] font-normal text-accent hover:border-accent hover:bg-accent/10";

const pctOf = (num: number, den: number) => (den > 0 ? `${((num / den) * 100).toFixed(2)}%` : "-");

// Total sales includes pending sales (Sales Settings rules).
export function chattingKpis(
  rows: ChattingStatsRow[], sheet: TimesheetRow[] | null = null, chatterOnly = false, sheetNote: string | null = null,
  roster: number[] | null = null,
): { label: string; tip: string; value: string; wired: boolean; note?: string }[] {
  const sum = (f: (r: ChattingStatsRow) => number) => rows.reduce((s, r) => s + f(r), 0);
  const timed = rows.filter((r) => r.avg_reply_seconds != null && r.replies > 0);
  const replies = timed.reduce((s, r) => s + r.replies, 0);
  const ids = new Set(roster);
  const waiting = chatterOnly && sheet != null && roster == null;
  const scheduled = waiting ? undefined : sheet?.filter((t) => !chatterOnly || (t.employee_id != null && ids.has(t.employee_id)))
    .reduce((s, t) => s + t.scheduled_minutes, 0);
  return [
    { label: "Total sales", tip: "Total sales generated, according to your sales settings",
      value: fmtCents(sum((r) => r.sales_cents)), wired: true },
    { label: "Unlock rate", tip: "Percentage of direct PPVs sent that were unlocked by fans",
      value: pctOf(sum((r) => r.ppvs_unlocked), sum((r) => r.direct_ppvs_sent)), wired: true },
    { label: "Average response time (based on scheduled hours)",
      tip: "Average time taken to reply to a fan during scheduled shift hours", value: "-", wired: false },
    { label: "Average response time (all replies)",
      tip: "Average time taken by employees to reply to a fan, from the fan's first unanswered message, over every reply, clocked in or not",
      value: replies > 0 ? fmtReplyTime(timed.reduce((s, r) => s + r.avg_reply_seconds! * r.replies, 0) / replies) : "-",
      wired: true },
    { label: "Total number of scheduled hours", tip: "Hours of the shifts scheduled in the time frame",
      value: waiting ? "…" : scheduled == null ? "-" : `${(scheduled / 60).toLocaleString("en-US", { maximumFractionDigits: 1 })}h`,
      wired: waiting || scheduled != null, ...(scheduled == null && sheetNote ? { note: `Not shown: ${sheetNote}.` } : {}) },
  ];
}

function KpiCard({ label, tip, value, wired, note }: ReturnType<typeof chattingKpis>[number]) {
  return (
    <div role="group" aria-label={label} title={wired || note ? undefined : "not wired"}
      className={cn("flex min-h-[128px] flex-col rounded-[4px] border border-border bg-bg px-6 pt-7 pb-4",
        !wired && !note && "opacity-60")}>
      <span className="text-[28px] font-semibold leading-9 text-fg tabular-nums">{value}</span>
      <span className="mt-1 flex items-start justify-between gap-3 text-[12px] text-muted">
        {label}
        <InfoTip text={tip} className="mt-0.5" />
      </span>
      {note && <span className="mt-1 text-[12px] text-fg-dim">{note}</span>}
    </div>
  );
}

function Change({ cur, prev, lowerIsBetter }: { cur: number | null; prev: number | null | undefined; lowerIsBetter?: boolean }) {
  if (cur == null) return null;
  const g = growthOf(cur, prev);
  const good = g.dir != null && (g.dir === "up") !== !!lowerIsBetter;
  return (
    <div className={cn("text-[11px]", g.dir == null ? "text-fg-dim" : good ? "text-ok" : "text-pink")}>
      {g.dir && <span role="img" aria-label={g.dir === "up" ? "rising" : "falling"}>{g.dir === "up" ? "↑" : "↓"}</span>}
      {g.text}
    </div>
  );
}

export default function ChattingStatsTable({
  from, to, priorFrom = null, priorTo = null, chatterOnly = false, onChatterOnly,
}: {
  from: string | null; to: string | null;
  priorFrom?: string | null; priorTo?: string | null;
  chatterOnly?: boolean;
  onChatterOnly?: (on: boolean) => void;
}) {
  const q = useChattingStats(from, to, chatterOnly);
  const pq = useChattingStats(priorFrom, priorTo, chatterOnly, priorFrom != null && priorTo != null);
  const before = useMemo(() => new Map((pq.data?.employees ?? []).map((r) => [r.employee_id, r])), [pq.data]);
  const ranged = !!from && !!to;
  const sheet = useTimesheet(new Date(from ?? 0), new Date(to ?? 0), "employee", !!useOptionalUser()?.user && ranged);
  const sheetNote = sheet.error instanceof RelayError && sheet.error.status === 422 ? sheet.error.message : null;
  const [sortKey, setSortKey] = useState<Key>("sales_cents");
  const [desc, setDesc] = useState(true);

  const rows = useMemo(() => {
    const out = [...(q.data?.employees ?? [])];
    out.sort((a, b) => {
      const cmp = sortKey === "display_name"
        ? (a.display_name ?? "").localeCompare(b.display_name ?? "")
        : (a[sortKey] ?? -Infinity) - (b[sortKey] ?? -Infinity);
      return desc ? -cmp : cmp;
    });
    return out;
  }, [q.data, sortKey, desc]);

  const sortBy = (k: Key) => {
    if (k === sortKey) setDesc((d) => !d);
    else { setSortKey(k); setDesc(k !== "display_name"); }
  };
  const arrow = (k: Key) => (k === sortKey ? (desc ? " ↓" : " ↑") : "");
  const columns = rows.some((r) => r.clocked_minutes != null) ? COLUMNS
    : COLUMNS.filter((c) => !CLOCKED.includes(c.key));

  return (
    <section aria-label="Chatting statistics" className="space-y-4">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <h2 className="text-[16px] font-medium text-fg">Chatting statistics</h2>
        {onChatterOnly && <ChatterOnlyCheckbox checked={chatterOnly} onChange={onChatterOnly} />}
        {rows.length > 0 && (
          <div className="ml-auto">
            <ExportMenu className={EXPORT_OUTLINE} fileName={`employee-reports_${(from ?? "").slice(0, 10)}_${(to ?? "").slice(0, 10)}`}
              sheet="Employee reports" displays={["total", "day", "creator"]}
              build={employeeExport({ rows, columns, from, to, chatterOnly })} />
          </div>
        )}
      </header>
      <p className="text-[12px] text-fg-dim">
        Percentage changes are calculated based on the change in value in the selected time frame against the same
        time frame preceding it.
      </p>
      {q.isError ? (
        <EmptyState kind="error" text={(q.error as Error)?.message || "Failed to load chatting statistics"}
          onRetry={() => { void q.refetch(); }} className="py-8" />
      ) : q.isPending ? (
        <p className="py-4 text-sm text-fg-dim">Loading…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {chattingKpis(rows, sheet.data?.rows ?? null, chatterOnly, sheetNote,
              q.isPlaceholderData ? null : q.data?.chatter_ids ?? null).map((k) => <KpiCard key={k.label} {...k} />)}
          </div>
          {rows.length === 0 ? (
            <EmptyState size="sm" text="No chatting in this window." />
          ) : (
        <div className="overflow-x-auto rounded-[4px]">
          <table className={cn(IF_TABLE.table, "transition-opacity", q.isFetching && q.isPlaceholderData && "opacity-60")}>
            <thead>
              <tr>
                <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, CELL, "cursor-pointer select-none", PIN_EMP, "z-[2]")}
                  onClick={() => sortBy("display_name")}>
                  Employees{arrow("display_name")}
                </th>
                <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, CELL, PIN_CREATORS, "z-[2]")}>Creators</th>
                {columns.map((c) => (
                  <th key={c.key} title={c.tip} onClick={() => sortBy(c.key)}
                    className={cn(IF_TABLE.th, IF_TABLE.thDivider, CELL, "text-right cursor-pointer select-none",
                      c.key === sortKey && "text-fg")}>
                    {c.label}{arrow(c.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.employee_id} className={IF_TABLE.row}>
                  <td className={cn(IF_TABLE.td, CELL, "bg-bg truncate", PIN_EMP)}>
                    {r.display_name ?? `Employee #${r.employee_id}`}
                  </td>
                  <td className={cn(IF_TABLE.td, CELL, "bg-bg text-fg-dim truncate", PIN_CREATORS)}
                    title={r.per_account.map((a) => a.account_nickname ?? a.account_id).join(", ")}>
                    {r.per_account.length === 1
                      ? (r.per_account[0].account_nickname ?? r.per_account[0].account_id)
                      : `${r.per_account.length} creators`}
                  </td>
                  {columns.map((c) => (
                    <td key={c.key} className={cn(IF_TABLE.td, CELL, "text-right tabular-nums")}>
                      {c.fmt(r)}
                      <Change cur={r[c.key]} prev={before.get(r.employee_id)?.[c.key]} lowerIsBetter={c.lowerIsBetter} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
          )}
        </>
      )}
    </section>
  );
}

export function ChatterOnlyCheckbox({ checked, onChange, className }: {
  checked: boolean; onChange: (on: boolean) => void; className?: string;
}) {
  return (
    <label className={cn("flex items-center gap-2 text-[14px] text-fg whitespace-nowrap cursor-pointer", className)}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-accent" />
      Show employees with chatter role only
    </label>
  );
}
