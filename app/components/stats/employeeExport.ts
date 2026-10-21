/**
 * Employee reports' export (roadmap W5 5.9; Infloww's Employee export, 05-analytics M22): the Chatting statistics
 * rows on screen in total, each Employee's figures by day (the charts' `chatting-stats?bucket=` read), and each
 * Employee's figures by Creator (`per-employee?by_account=true`). Only the Employees the table shows: the Relay
 * already scoped them, and the Unattributed sales have no row. Sales follow the Sales Settings rules and count
 * pending sales.
 */

import type { ExportChoice } from "@/components/stats/ExportMenu";
import { granShown, rangeDays } from "@/components/stats/chart";
import type { ChattingSeriesResp, ChattingStatsRow, PerEmployeeResp } from "@/hooks/useStats";
import { relay } from "@/lib/relay";
import { type Cell, type Section, usd } from "@/lib/reportExport";

/** A Chatting statistics column the table shows: a numeric field and its title. */
export interface StatColumn { key: keyof ChattingStatsRow; label: string }

const name = (r: ChattingStatsRow) => r.display_name ?? `Employee #${r.employee_id}`;

/** A figure as exported: cents as dollars, clocked minutes as hours, the rest as read; empty when null. */
function value(key: string, v: unknown): Cell {
  if (typeof v !== "number") return null;
  if (key.endsWith("_cents")) return usd(v);
  if (key === "clocked_minutes") return Math.round((v / 60) * 100) / 100;
  return v;
}

function query(from: string | null, to: string | null, chatterOnly: boolean, extra: Record<string, string>) {
  const qs = new URLSearchParams(extra);
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  if (chatterOnly) qs.set("chatter_only", "true");
  return qs.toString();
}

/** The `build` of Employee reports' ExportMenu, over the table's `rows` and `columns` as shown. */
export function employeeExport({ rows, columns, from, to, chatterOnly }: {
  rows: ChattingStatsRow[]; columns: StatColumn[]; from: string | null; to: string | null; chatterOnly: boolean;
}) {
  return async (c: ExportChoice): Promise<Section[]> => {
    const sections: Section[] = [];
    if (c.displays.includes("total")) {
      sections.push({ title: "Total", rows: [
        ["Employee", "Creators", ...columns.map((col) => (col.key === "avg_reply_seconds" ? `${col.label} (seconds)` : col.label))],
        ...rows.map((r) => [
          name(r), r.per_account.map((a) => a.account_nickname ?? a.account_id).join(", "),
          ...columns.map((col) => value(col.key, r[col.key])),
        ]),
      ] });
    }
    if (c.displays.includes("day")) {
      // By day as the charts read it: a range the Relay will not show by day (over 31 days) comes by week or month.
      const bucket = granShown("day", from && to ? rangeDays(from, to) : 30);
      const data = await relay.get<ChattingSeriesResp>(
        `/admin/stats/chatting-stats?${query(from, to, chatterOnly, { bucket })}`);
      const head = bucket === "day" ? "Day" : bucket === "week" ? "Week of" : "Month";
      const out: Cell[][] = [["Employee", head, "Sales", "Direct messages sent", "Direct PPVs sent", "PPVs unlocked",
        "Fans chatted"]];
      for (const r of rows) {
        const points = data.by_employee[String(r.employee_id)] ?? [];
        data.series.forEach((s, i) => {
          const p = points[i];
          out.push([name(r), bucket === "month" ? s.start.slice(0, 7) : s.start.slice(0, 10), usd(p?.sales_cents ?? 0),
            p?.direct_messages_sent ?? 0, p?.direct_ppvs_sent ?? 0, p?.ppvs_unlocked ?? 0, p?.fans_chatted ?? 0]);
        });
      }
      sections.push({ title: "By day", rows: out });
    }
    if (c.displays.includes("creator")) {
      const data = await relay.get<PerEmployeeResp>(
        `/admin/stats/per-employee?${query(from, to, chatterOnly, { by_account: "true" })}`);
      const byId = new Map(data.employees.map((e) => [e.employee_id, e]));
      const out: Cell[][] = [["Employee", "Creator", "Sales", "PPV sales", "Tips", "Messages sent", "PPV conversions"]];
      for (const r of rows) {
        for (const a of byId.get(r.employee_id)?.per_account ?? []) {
          out.push([name(r), a.account_nickname ?? a.account_id ?? "", usd(a.revenue_cents), usd(a.revenue_by_kind.ppv),
            usd(a.revenue_by_kind.tip), a.messages_sent, a.ppv_conversions]);
        }
      }
      sections.push({ title: "By creator", rows: out });
    }
    return sections;
  };
}
