"use client";

/** ReadyMadePanel's pinned rule table (Auto Post / Auto Mass) and the
 *  previous-runs strip under each row's chevron. */

import { Fragment, useMemo, useState } from "react";
import { ChevronRight, MoreHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, IF_TABLE, IfHelp, IfSwitch } from "@/components/ui/infloww";
import { Menu } from "@/components/ui/Menu";
import { StatusPill, ruleStatus, runStatus } from "@/components/automations/StatusPill";
import { TABLE_EMPTY } from "@/components/automations/automationPage";
import { cn } from "@/lib/utils";
import { fmtAgo, fmtDateTime } from "@/lib/format";
import type { AutomationRule } from "@/hooks/useAutomations";
import type { AutomationRunRow } from "@/hooks/useStats";
import { splitInterval } from "@/components/automations/ruleInterval";
import { summarize } from "@/components/automations/readyMadeContent";
import type { Kind } from "@/components/compose/payloadRules";

/** "in 2 h" / "in 30 min" for an upcoming due time (or null if past/missing). */
function timeUntil(iso: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const secs = Math.round((t - Date.now()) / 1000);
  if (secs <= 0) return "now";
  if (secs < 60) return `in ${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `in ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `in ${hrs} h`;
  return `in ${Math.round(hrs / 24)} d`;
}

// ── Pinned rule table (Auto Post / Auto Mass) ─────────────────────────

const RULE_COLUMNS = ["Name", "Status", "Schedule", "Next run", "Actions"] as const;
/** Below `sm` a row is the Name cell (status + next run under the name) and a "⋯" menu. */
const WIDE_ONLY = new Set<string>(["Status", "Schedule", "Next run"]);

/** "Every 24 hours" / "Every 30 minutes" from a rule's interval. */
function scheduleText(secs: number | null): string {
  if (!secs) return "—";
  const { value, unit } = splitInterval(secs);
  return `Every ${value} ${value === 1 ? unit.slice(0, -1) : unit}`;
}

const LINK = "text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50";

type RowAction = "run" | "edit" | "toggle" | "delete";

/** The phone row's "⋯": Run now, Edit, Pause / Resume (the wide row's switch), Delete. The page body clips (main's
 *  overflow-clip): on the last rows it opens upward (`flip`). */
function RowMenu({ rule, busy, onPick }: {
  rule: AutomationRule;
  busy: { toggle: boolean; run: boolean; remove: boolean };
  onPick: (a: RowAction) => void;
}) {
  const item = (a: RowAction, label: string, disabled: boolean) =>
    ({ key: a, label, disabled, danger: a === "delete", onClick: () => onPick(a) });
  return (
    <Menu align="right" position="flip" panelClassName="z-20 w-36" itemClassName="text-[14px] text-fg disabled:opacity-50"
      trigger={(p) => (
        <button type="button" aria-label={`More actions for ${rule.name}`} {...p}
          className="grid h-8 w-8 place-items-center rounded-md text-fg-dim hover:text-fg">
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </button>
      )}
      items={[
        item("run", "Run now", busy.run),
        item("edit", "Edit", false),
        item("toggle", rule.is_enabled ? "Pause" : "Resume", busy.toggle),
        item("delete", "Delete", busy.remove),
      ]} />
  );
}

/** The saved rules as Smart Messages' antd table: a row per rule, the Status
 *  switch and pill (`ruleStatus`), what the rule posts / sends under its name, the last run and previous runs behind
 *  the Name cell's chevron, Actions fixed right. Below `sm` the row is the name, its pill and next run, and a "⋯". */
export function RuleTable({
  kind, rules, runs, loading, error, empty, emptyHelp, emptyAction, busy, rowErr, onToggle, onRun, onEdit, onDelete,
}: {
  /** The kind every listed rule is (the panel's `only`). */
  kind: Kind;
  rules: AutomationRule[];
  runs: AutomationRunRow[];
  loading: boolean;
  error: string | null;
  empty: string;
  /** Under the empty text: one line on what a rule does. */
  emptyHelp?: React.ReactNode;
  /** Under the empty text: the next step (the page's "New …"). */
  emptyAction?: React.ReactNode;
  busy: { toggle: boolean; run: boolean; remove: boolean };
  rowErr: { id: number; msg: string } | null;
  onToggle: (r: AutomationRule) => void;
  onRun: (r: AutomationRule) => void;
  onEdit: (r: AutomationRule) => void;
  onDelete: (r: AutomationRule) => void;
}) {
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const flip = (id: number) => setOpen((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const act = (r: AutomationRule, a: RowAction) => {
    if (a === "run") onRun(r);
    else if (a === "edit") onEdit(r);
    else if (a === "toggle") onToggle(r);
    else onDelete(r);
  };
  const line = (children: React.ReactNode, cls = "text-muted") => (
    <tr><td colSpan={RULE_COLUMNS.length} className={cn("py-10 text-center text-[14px]", cls)}>{children}</td></tr>
  );
  return (
    // A phone row fits the screen (no sideways scroll), so the "⋯" menu may hang below the table.
    <div className="overflow-x-auto max-sm:overflow-visible">
      <table className={cn(IF_TABLE.table, "min-w-[760px] max-sm:min-w-0")}>
        <thead>
          <tr>
            {RULE_COLUMNS.map((c) => (
              <th key={c} className={cn(IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                WIDE_ONLY.has(c) && "max-sm:hidden",
                c === "Actions" && cn(IF_TABLE.fixedRightHead, "z-[1] w-[220px] max-sm:static max-sm:w-12 max-sm:shadow-none max-sm:[html[data-theme=light]_&]:shadow-none"))}>
                {c === "Actions" ? <span className="max-sm:sr-only">Actions</span> : c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? Array.from({ length: 4 }, (_, i) => (
            <tr key={i} className={IF_TABLE.row} data-loading>
              {RULE_COLUMNS.map((c) => (
                <td key={c} className={cn(IF_TABLE.td, WIDE_ONLY.has(c) && "max-sm:hidden")}><Skeleton className="h-3 w-20" /></td>
              ))}
            </tr>
          )) : error ? line(error, "text-err") : rules.length === 0 ? (
            <tr><td colSpan={RULE_COLUMNS.length}>
              <EmptyState kind="data" text={empty} className={TABLE_EMPTY}
                help={emptyHelp && <IfHelp className="mt-1 max-w-[360px] text-center">{emptyHelp}</IfHelp>}
                action={emptyAction} />
            </td></tr>
          ) : rules.map((r) => {
            const expanded = open.has(r.id);
            const due = timeUntil(r.next_due_at);
            const ago = fmtAgo(r.last_run?.started_at ?? null);
            const summary = summarize(r.payload ?? {}, kind);
            const status = ruleStatus(r);
            const next = r.has_pending_job ? <span className="text-warn">Queued (runs ~30s)</span>
              : r.is_enabled && r.next_due_at ? <span title={r.next_due_at}>{due ?? fmtDateTime(r.next_due_at)}</span>
              : null;
            return (
              <Fragment key={r.id}>
                <tr className={cn(IF_TABLE.row, expanded && "border-b-0")}>
                  <td className={cn(IF_TABLE.td, "max-sm:pr-0")}>
                    <div className="flex min-w-0 items-center gap-2">
                      <button type="button" aria-expanded={expanded} aria-label={`Previous runs of ${r.name}`}
                        onClick={() => flip(r.id)} className="grid h-5 w-5 shrink-0 place-items-center text-muted hover:text-fg">
                        <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} aria-hidden />
                      </button>
                      <span className="truncate">{r.name}</span>
                      {r.has_pending_job && <Badge color="warn">queued</Badge>}
                    </div>
                    {/* one rule = one post / message: its read-out, so the list shows every rule's content */}
                    {summary && <div className={cn("mt-0.5 max-w-[360px] pl-7 text-[12px] text-muted",
                      kind === "mass_premade" ? "line-clamp-6 whitespace-normal break-words" : "truncate")}
                      title={summary}>{summary}</div>}
                    {/* phone: the Status and Next run columns, under the name */}
                    <div data-testid="rule-phone-line" className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 pl-7 text-[12px] text-muted sm:hidden">
                      <StatusPill status={status} />
                      {next && (r.has_pending_job ? next : <span>Next run {next}</span>)}
                      {!next && r.every_seconds ? <span>{scheduleText(r.every_seconds)}</span> : null}
                    </div>
                    {r.last_run?.error_text && (
                      <div className="mt-1 whitespace-pre-wrap break-words pl-7 text-[12px] text-err">{r.last_run.error_text}</div>
                    )}
                    {rowErr?.id === r.id && <div className="mt-1 pl-7 text-[12px] text-err">{rowErr.msg}</div>}
                  </td>
                  <td className={cn(IF_TABLE.td, "max-sm:hidden")}>
                    <span className="flex items-center gap-3">
                      <IfSwitch aria-label={`Enabled: ${r.name}`} checked={r.is_enabled} disabled={busy.toggle}
                        onChange={() => onToggle(r)} />
                      <StatusPill status={status} />
                    </span>
                  </td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap max-sm:hidden")}>{scheduleText(r.every_seconds)}</td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap max-sm:hidden")}>
                    {next ?? <span className="text-muted">—</span>}
                  </td>
                  <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] w-[220px] whitespace-nowrap max-sm:static max-sm:w-12 max-sm:px-2 max-sm:align-top max-sm:shadow-none max-sm:[html[data-theme=light]_&]:shadow-none")}>
                    <span className="inline-flex gap-4 max-sm:hidden">
                      <button type="button" className={LINK} disabled={busy.run} onClick={() => onRun(r)}>Run now</button>
                      <button type="button" className={LINK} onClick={() => onEdit(r)}>Edit</button>
                      <button type="button" className={LINK} disabled={busy.remove} onClick={() => onDelete(r)}>Delete</button>
                    </span>
                    <span className="sm:hidden"><RowMenu rule={r} busy={busy} onPick={(a) => act(r, a)} /></span>
                  </td>
                </tr>
                {expanded && (
                  <tr className={IF_TABLE.row}>
                    <td colSpan={RULE_COLUMNS.length} className="px-4 pb-3 pl-[44px] text-[12px] text-muted">
                      <div className="mb-1" data-testid="rule-last-run">
                        Last run{" "}
                        {ago ? <span title={r.last_run?.started_at ?? ""} className="text-fg-dim">{ago}</span> : "—"}
                      </div>
                      <PreviousRuns kind={r.kind} accountId={r.account_id} runs={runs} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Previous-runs strip ────────────────────────────────────────────────

export function parseStats(s: string | null): Record<string, unknown> | null {
  if (!s || s === "{}") return null;
  try {
    const o = JSON.parse(s);
    return o && typeof o === "object" && !Array.isArray(o) ? (o as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Hours between two ISO timestamps, rounded — for "deleted after N hrs". */
function hoursBetween(a: string | null, b: string | null): number | null {
  if (!a || !b) return null;
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  return Math.round((ms / 3_600_000) * 10) / 10;
}

/** One previous-run chip: status · when · post id / delete window. */
export function runSummary(run: AutomationRunRow): string {
  const st = parseStats(run.stats_json);
  const bits: string[] = [];
  if (st) {
    if (st.dry_run) bits.push("dry run");
    const postId = st.of_post_id;
    if (typeof postId === "number") bits.push(`post #${postId}`);
    const delAt = typeof st.delete_at === "string" ? st.delete_at : null;
    const ttl = hoursBetween(run.started_at, delAt);
    if (ttl != null) bits.push(`auto-deletes after ${ttl} h`);
    if (typeof st.sent === "number" && st.sent > 0) bits.push(`sent ${st.sent}`);
    if (typeof st.remaining === "number" && st.remaining > 0) bits.push(`${st.remaining} left`);
    if (typeof st.reason === "string" && st.status === "skipped") bits.push(`skipped (${st.reason})`);
  }
  return bits.join(" · ");
}

/** The pinned table's expanded row: 12px T3 with no left inset. */
function PreviousRuns({
  kind,
  accountId,
  runs,
}: {
  kind: string;
  accountId: string;
  runs: AutomationRunRow[];
}) {
  const mine = useMemo(() => {
    // Run rows carry no rule_id, only (kind, account_id) — so we can't pin a run
    // to ONE rule. Account-scoped rows of this kind clearly belong here; the
    // global (account_id == null) rows are ambiguous (any account, any same-kind
    // rule), so only fall back to them when this account has no scoped runs of
    // the kind. That stops a global run from being claimed under every account.
    const ofKind = runs.filter((r) => r.kind === kind);
    const scoped = ofKind.filter((r) => r.account_id === accountId);
    const pool = scoped.length > 0 ? scoped : ofKind.filter((r) => r.account_id == null);
    return pool.slice(0, 4);
  }, [runs, kind, accountId]);
  if (mine.length === 0) {
    return <div className="text-[12px] text-muted italic">No previous runs.</div>;
  }
  return (
    <ul className="space-y-0.5">
      {mine.map((run) => {
        const ago = fmtAgo(run.started_at);
        const extra = runSummary(run);
        return (
          <li key={run.id} className="text-[12px] text-muted flex flex-wrap items-center gap-1.5">
            <StatusPill status={runStatus(run.status)} />
            <span title={run.started_at ?? ""}>{ago ?? fmtDateTime(run.started_at)}</span>
            {extra && <span className="text-fg-dim/80">· {extra}</span>}
          </li>
        );
      })}
    </ul>
  );
}
