"use client";

/**
 * ReadyMadePanel — the ready-made posts & broadcasts page, pinned to one of
 * two rule kinds:
 *
 *   Auto Posts   (auto_posts)   — post a list one-by-one; each optionally
 *                                 auto-deletes after N hours (self-cleaning feed).
 *   Premade Mass (mass_premade) — ready broadcasts; resend on a timer and/or
 *                                 auto-unsend later. My Automations calls it
 *                                 Auto Mass (/growth/auto-mass).
 *
 * Unlike the old fire-once tabs, these are now SAVED, persisted definitions
 * stored as `automation_rules` rows (reusing that table — no new schema). Each
 * saved rule shows what's queued next (`next_due_at` / `has_pending_job`) and a
 * compact strip of previous runs (from the executor's run log). "New / Edit"
 * builds the payload with the existing PremadeForm in COMPOSE mode and persists
 * it via the automation-rules create/update hooks; "Run now" enqueues an
 * immediate job off the saved rule.
 *
 * The panel is the page (`only`, My Automations > Auto Post / Auto Mass):
 * Infloww's legacy list page (page-parity ticket 16, copied from Smart Messages
 * › Automated Messages): a PageFrame header with the creator select, the
 * blurb as Learn's popover and the primary "New …", then an IF_TABLE of the
 * saved rules with previous runs in an expandable row.
 */

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronRight, Plus } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import { EmptyState, IF_TABLE, IfButton, IfInput, IfLearn, IfModal, IfSelect, IfSwitch } from "@/components/ui/infloww";
import { PageFrame } from "@/components/shell/PageFrame";
import {
  ConfirmDelete, EDITOR_MODAL, FieldLabel, NoCreator, TABLE_EMPTY, useAutomationCreator,
} from "@/components/automations/automationPage";
import { cn } from "@/lib/utils";
import { fmtAgo, fmtDateTime } from "@/lib/format";
import {
  useAutomationRules,
  useCreateRule,
  useDeleteRule,
  useRunRuleNow,
  useUpdateRule,
  type AutomationRule,
} from "@/hooks/useAutomations";
import { useAutomationRuns, type AutomationRunRow } from "@/hooks/useStats";
import { PremadeForm } from "@/components/compose/PremadeComposer";

/** The two automation_rules kinds the panel can be pinned to. */
type RuleKind = "auto_posts" | "mass_premade";

/** The words each rule kind is shown with. Auto Mass sends OF mass messages
 *  (`mass_premade` delegates to `send_mass_message`, OF's messages/queue), so
 *  its copy uses Infloww's names: "mass message", "Auto-unsend". */
const KIND_COPY: Record<RuleKind, {
  /** The page title when the panel is pinned to this kind (`only`). */
  title: string;
  /** Learn's popover text when pinned. */
  blurb: string;
  /** The pinned header's primary. */
  button: string;
  /** "New …" (the editor's title). */
  noun: string;
  /** "No … yet" (the empty table). */
  plural: string;
  /** One item of the payload list, and the list's label. */
  item: string;
  items: string;
}> = {
  auto_posts: {
    title: "Auto Post",
    button: "New auto post",
    blurb:
      "Posts that publish on their own schedule, one at a time, and can delete " +
      "themselves after the hours you set. See what's queued next and the recent " +
      "runs below. “Run now” posts the next one immediately.",
    noun: "auto post",
    plural: "auto posts",
    item: "post",
    items: "Posts",
  },
  mass_premade: {
    title: "Auto Mass",
    button: "New auto mass",
    blurb:
      "Mass messages that send on their own schedule to the fans you pick, " +
      "through the same OF mass message path as Smart Messages (sent to the " +
      "general inbox). Each message can be resent on a timer and unsent " +
      "automatically after the hours you set. See what's queued next and the " +
      "recent runs below. “Run now” sends it immediately.",
    noun: "auto mass message",
    plural: "auto mass messages",
    item: "message",
    items: "Messages",
  },
};

type Unit = "minutes" | "hours";
const UNIT_S: Record<Unit, number> = { minutes: 60, hours: 3600 };

/** Largest tidy unit (≥ minutes) that divides `secs` cleanly. */
function splitInterval(secs: number): { value: number; unit: Unit } {
  if (secs > 0 && secs % 3600 === 0) return { value: secs / 3600, unit: "hours" };
  return { value: Math.max(1, Math.round(secs / 60)), unit: "minutes" };
}

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

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "ok" ? "ok" : status === "error" ? "err" : status === "running" ? "warn" : "muted";
  return <Badge color={color}>{status === "running" ? "running…" : status}</Badge>;
}

/** The panel pinned to one rule kind: how My Automations > Auto Post
 *  (/growth/auto-post) shows the Auto Posts list, and > Auto Mass
 *  (/growth/auto-mass) the mass_premade list. It renders the page (its
 *  PageFrame and header) itself. */
export default function ReadyMadePanel({ only }: { only: RuleKind }) {
  // The header's creator select, in `?creator=`.
  const creator = useAutomationCreator();
  const accountId = creator.accountId;

  const rulesQ = useAutomationRules(accountId);
  const runsQ = useAutomationRuns(200);
  const updateM = useUpdateRule(accountId);
  const deleteM = useDeleteRule(accountId);
  const runM = useRunRuleNow(accountId);

  const [editing, setEditing] = useState<AutomationRule | null>(null);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<AutomationRule | null>(null);
  const [rowErr, setRowErr] = useState<{ id: number; msg: string } | null>(null);

  const rules = useMemo(
    () => (rulesQ.data ?? []).filter((r) => r.kind === only),
    [rulesQ.data, only],
  );

  function closeEditor() {
    setEditing(null);
    setAdding(false);
  }

  // Switching creators closes a half-open editor (its account would mismatch).
  useEffect(() => {
    closeEditor();
  }, [accountId]);

  async function toggle(rule: AutomationRule) {
    setRowErr(null);
    try {
      await updateM.mutateAsync({ id: rule.id, is_enabled: !rule.is_enabled });
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Toggle failed" });
    }
  }

  async function runNow(rule: AutomationRule) {
    setRowErr(null);
    try {
      await runM.mutateAsync(rule.id);
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Run failed" });
    }
  }

  async function remove(rule: AutomationRule) {
    setDeleting(null);
    setRowErr(null);
    try {
      await deleteM.mutateAsync(rule.id);
      if (editing?.id === rule.id) closeEditor();
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Delete failed" });
    }
  }

  const runs = runsQ.data?.runs ?? [];
  const startNew = () => { setEditing(null); setAdding(true); };
  const copy = KIND_COPY[only];

  return (
    <PageFrame
      title={copy.title}
      extra={creator.picker}
      actions={(
        <>
          <IfLearn tip={copy.blurb}><span className="max-sm:sr-only">Learn</span></IfLearn>
          <IfButton variant="primary" icon={Plus} onClick={startNew} disabled={!accountId} className="max-sm:px-2.5">
            <span className="max-sm:sr-only">{copy.button}</span>
          </IfButton>
        </>
      )}
    >
      {accountId ? (
        <RuleTable
          rules={rules}
          runs={runs}
          loading={rulesQ.isLoading}
          error={rulesQ.isError ? (rulesQ.error as Error)?.message || "Failed to load saved definitions" : null}
          empty={`No ${copy.plural} yet`}
          busy={{ toggle: updateM.isPending, run: runM.isPending, remove: deleteM.isPending }}
          rowErr={rowErr}
          onToggle={toggle}
          onRun={runNow}
          onEdit={(r) => { setAdding(false); setEditing(r); }}
          onDelete={setDeleting}
        />
      ) : !creator.loading && <NoCreator />}
      {(adding || editing) && accountId && (
        <ReadyMadeRuleEditor
          key={editing?.id ?? "new"}
          kind={only}
          accountId={accountId}
          editing={editing}
          onClose={closeEditor}
        />
      )}
      {deleting && (
        <ConfirmDelete
          title={`Delete "${deleting.name}"?`}
          pending={deleteM.isPending}
          onConfirm={() => remove(deleting)}
          onClose={() => setDeleting(null)}
        >
          This stops the schedule.
        </ConfirmDelete>
      )}
    </PageFrame>
  );
}

// ── Pinned rule table (Auto Post / Auto Mass) ─────────────────────────

const RULE_COLUMNS = ["Name", "Status", "Schedule", "Next run", "Last run", "Actions"] as const;

/** "Every 24 hours" / "Every 30 minutes" from a rule's interval. */
function scheduleText(secs: number | null): string {
  if (!secs) return "—";
  const { value, unit } = splitInterval(secs);
  return `Every ${value} ${value === 1 ? unit.slice(0, -1) : unit}`;
}

const LINK = "text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-50";

/** The saved rules as Smart Messages' antd table: a row per rule, the Status
 *  switch, previous runs behind the Name cell's chevron, Actions fixed right. */
function RuleTable({
  rules, runs, loading, error, empty, busy, rowErr, onToggle, onRun, onEdit, onDelete,
}: {
  rules: AutomationRule[];
  runs: AutomationRunRow[];
  loading: boolean;
  error: string | null;
  empty: string;
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
  const line = (children: React.ReactNode, cls = "text-muted") => (
    <tr><td colSpan={RULE_COLUMNS.length} className={cn("py-10 text-center text-[14px]", cls)}>{children}</td></tr>
  );
  return (
    <div className="overflow-x-auto">
      <table className={cn(IF_TABLE.table, "min-w-[880px]")}>
        <thead>
          <tr>
            {RULE_COLUMNS.map((c) => (
              <th key={c} className={cn(IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                c === "Actions" && cn(IF_TABLE.fixedRightHead, "z-[1] w-[220px]"))}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? line("Loading…") : error ? line(error, "text-err") : rules.length === 0 ? (
            <tr><td colSpan={RULE_COLUMNS.length}><EmptyState kind="data" text={empty} className={TABLE_EMPTY} /></td></tr>
          ) : rules.map((r) => {
            const expanded = open.has(r.id);
            const due = timeUntil(r.next_due_at);
            const ago = fmtAgo(r.last_run?.started_at ?? null);
            return (
              <Fragment key={r.id}>
                <tr className={cn(IF_TABLE.row, expanded && "border-b-0")}>
                  <td className={IF_TABLE.td}>
                    <div className="flex min-w-0 items-center gap-2">
                      <button type="button" aria-expanded={expanded} aria-label={`Previous runs of ${r.name}`}
                        onClick={() => flip(r.id)} className="grid h-5 w-5 shrink-0 place-items-center text-muted hover:text-fg">
                        <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} aria-hidden />
                      </button>
                      <span className="truncate">{r.name}</span>
                      {r.has_pending_job && <Badge color="warn">queued</Badge>}
                    </div>
                    {r.last_run?.error_text && (
                      <div className="mt-1 whitespace-pre-wrap break-words pl-7 text-[12px] text-err">{r.last_run.error_text}</div>
                    )}
                    {rowErr?.id === r.id && <div className="mt-1 pl-7 text-[12px] text-err">{rowErr.msg}</div>}
                  </td>
                  <td className={IF_TABLE.td}>
                    <span className="flex items-center gap-3">
                      <IfSwitch aria-label={`Enabled: ${r.name}`} checked={r.is_enabled} disabled={busy.toggle}
                        onChange={() => onToggle(r)} />
                      {r.is_enabled
                        ? r.last_run ? <StatusBadge status={r.last_run.status} /> : <span className="text-muted">idle</span>
                        : <span className="text-muted">paused</span>}
                    </span>
                  </td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{scheduleText(r.every_seconds)}</td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>
                    {r.has_pending_job ? <span className="text-warn">Queued (runs ~30s)</span>
                      : r.is_enabled && r.next_due_at ? <span title={r.next_due_at}>{due ?? fmtDateTime(r.next_due_at)}</span>
                      : <span className="text-muted">—</span>}
                  </td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>
                    {ago ? <span title={r.last_run?.started_at ?? ""}>{ago}</span> : <span className="text-muted">—</span>}
                  </td>
                  <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] w-[220px] whitespace-nowrap")}>
                    <span className="inline-flex gap-4">
                      <button type="button" className={LINK} disabled={busy.run} onClick={() => onRun(r)}>Run now</button>
                      <button type="button" className={LINK} onClick={() => onEdit(r)}>Edit</button>
                      <button type="button" className={LINK} disabled={busy.remove} onClick={() => onDelete(r)}>Delete</button>
                    </span>
                  </td>
                </tr>
                {expanded && (
                  <tr className={IF_TABLE.row}>
                    <td colSpan={RULE_COLUMNS.length} className="px-4 pb-3 pl-[44px] text-[12px] text-muted">
                      <PreviousRuns kind={r.kind} accountId={r.account_id} runs={runs} inset={false} />
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

function parseStats(s: string | null): Record<string, unknown> | null {
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
function runSummary(run: AutomationRunRow): string {
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

/** `inset={false}`: the pinned table's expanded row, 12px T3 with no left inset. */
function PreviousRuns({
  kind,
  accountId,
  runs,
  inset = true,
}: {
  kind: string;
  accountId: string;
  runs: AutomationRunRow[];
  inset?: boolean;
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
    return <div className={cn(inset ? "ml-7 text-[11px] text-fg-dim/70" : "text-[12px] text-muted", "italic")}>No previous runs.</div>;
  }
  return (
    <ul className={cn(inset && "ml-7", "space-y-0.5")}>
      {mine.map((run) => {
        const ago = fmtAgo(run.started_at);
        const extra = runSummary(run);
        return (
          <li key={run.id} className={cn(inset ? "text-[11px] text-fg-dim" : "text-[12px] text-muted", "flex flex-wrap items-center gap-1.5")}>
            <StatusBadge status={run.status} />
            <span title={run.started_at ?? ""}>{ago ?? fmtDateTime(run.started_at)}</span>
            {extra && <span className="text-fg-dim/80">· {extra}</span>}
          </li>
        );
      })}
    </ul>
  );
}

// ── Inline editor (create / edit a saved ready-made definition) ─────────

/** One-line summary of a premade payload for the compose read-out. */
function summarize(payload: Record<string, unknown>): string | null {
  const posts = Array.isArray(payload.posts) ? payload.posts : null;
  const messages = Array.isArray(payload.messages) ? payload.messages : null;
  const arr = posts ?? messages;
  if (!arr || arr.length === 0) return null;
  const noun = posts ? "post" : "message";
  const bits = [`${arr.length} ${noun}${arr.length === 1 ? "" : "s"}`];
  const rc = payload.resend_count;
  if (typeof rc === "number" && rc > 0) bits.push(`reposts ×${rc}`);
  return bits.join(" · ");
}

function ReadyMadeRuleEditor({
  kind,
  accountId,
  editing,
  onClose,
}: {
  kind: RuleKind;
  accountId: string;
  editing: AutomationRule | null;
  onClose: () => void;
}) {
  const isEdit = editing !== null;
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);

  const [name, setName] = useState(editing?.name ?? "");
  const init = splitInterval(editing?.every_seconds ?? 24 * 3600);
  const [intervalValue, setIntervalValue] = useState<number>(init.value);
  const [intervalUnit, setIntervalUnit] = useState<Unit>(init.unit);
  const [enabled, setEnabled] = useState<boolean>(editing?.is_enabled ?? true);
  const [dryRun, setDryRun] = useState<boolean>(
    Boolean((editing?.payload as Record<string, unknown> | undefined)?.dry_run),
  );

  // The composed payload — seeded from the rule being edited so saving WITHOUT
  // re-composing preserves it. The composer only overwrites it on "Use in rule".
  const [composed, setComposed] = useState<Record<string, unknown>>(() => {
    const p = { ...((editing?.payload as Record<string, unknown>) ?? {}) };
    delete p.dry_run; // tracked by the toggle, re-merged on save
    return p;
  });
  const [composerOpen, setComposerOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Raw-JSON escape hatch: hand-edit / paste the whole
  // `{posts|messages:[…]}` payload directly — the composer forces you to PICK
  // every media id, so this is the only way to paste a big media_files pool or
  // tweak a field the form doesn't expose. `dry_run` stays owned by the toggle.
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");

  const everySeconds = Math.round(intervalValue * UNIT_S[intervalUnit]);
  const busy = createM.isPending || updateM.isPending;
  const summary = summarize(composed);

  /** The composed payload from whichever mode is active — raw text is parsed and
   *  required to be an object; `dry_run` is stripped (the toggle re-merges it on
   *  save). Throws with a clear message on bad JSON. */
  function currentComposed(): Record<string, unknown> {
    if (!rawMode) return composed;
    const t = rawText.trim();
    if (!t) return {};
    let parsed: unknown;
    try {
      parsed = JSON.parse(t);
    } catch (e) {
      throw new Error(`Payload is not valid JSON: ${(e as Error).message}`);
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error(
        `Payload must be a JSON object, e.g. { "${kind === "auto_posts" ? "posts" : "messages"}": [ … ] }`,
      );
    }
    const p = { ...(parsed as Record<string, unknown>) };
    delete p.dry_run; // owned by the Dry-run toggle; re-merged on save
    return p;
  }

  /** Enter raw mode: seed the textarea from the current composed payload. */
  function enterRaw() {
    setRawText(JSON.stringify(composed, null, 2));
    setErr(null);
    setRawMode(true);
  }
  /** Leave raw mode: parse the textarea back into `composed` (keeps the two
   *  views in sync so "Re-compose" opens pre-filled with the hand edits). */
  function exitRaw() {
    let parsed: Record<string, unknown>;
    try {
      parsed = currentComposed();
    } catch (e) {
      setErr((e as Error).message);
      return;
    }
    setComposed(parsed);
    setRawMode(false);
    setErr(null);
  }

  async function save() {
    setErr(null);
    if (everySeconds < 30) {
      setErr("Interval must be at least 30 seconds.");
      return;
    }
    let base: Record<string, unknown>;
    try {
      base = currentComposed();
    } catch (e) {
      setErr((e as Error).message);
      return;
    }
    const arr = kind === "auto_posts" ? base.posts : base.messages;
    if (!Array.isArray(arr) || arr.length === 0) {
      setErr(`Compose at least one ${KIND_COPY[kind].item} first.`);
      return;
    }
    const payload: Record<string, unknown> = { ...base };
    if (dryRun) payload.dry_run = true;
    try {
      if (isEdit && editing) {
        await updateM.mutateAsync({
          id: editing.id,
          name: name.trim() || editing.name,
          every_seconds: everySeconds,
          payload,
          is_enabled: enabled,
        });
      } else {
        await createM.mutateAsync({
          account_id: accountId,
          kind,
          name: name.trim() || undefined,
          every_seconds: everySeconds,
          payload,
          is_enabled: enabled,
        });
      }
      onClose();
    } catch (e) {
      setErr((e as Error)?.message || "Save failed");
    }
  }

  const ids = { name: `rm-${kind}-name`, every: `rm-${kind}-every` };
  return (
    <IfModal
      width={722}
      title={editing ? `Edit · ${editing.name}` : `New ${KIND_COPY[kind].noun}`}
      onClose={onClose}
      // The composer opens over this one: its Escape must not drop the draft.
      closable={!composerOpen}
      className={EDITOR_MODAL}
      footer={(
        <>
          <span className="mr-auto text-[12px] text-muted tabular-nums">= every {everySeconds}s</span>
          <IfButton onClick={onClose} disabled={busy}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create"}
          </IfButton>
        </>
      )}
    >
      <div className="space-y-6">
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor={ids.name}>Name (optional)</FieldLabel>
            <IfInput
              id={ids.name}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={kind === "auto_posts" ? "Auto posts" : "Auto mass"}
              className="w-full"
            />
          </div>

          <div>
            <FieldLabel htmlFor={ids.every}>Run every</FieldLabel>
            <div className="flex items-center gap-2">
              <IfInput
                id={ids.every}
                type="number"
                min={1}
                value={intervalValue}
                onChange={(e) => setIntervalValue(Math.max(1, Number(e.target.value) || 0))}
                className="w-24"
              />
              <IfSelect<Unit>
                aria-label="Interval unit"
                value={intervalUnit}
                onChange={setIntervalUnit}
                options={[{ value: "minutes", label: "minutes" }, { value: "hours", label: "hours" }]}
                className="w-[120px]"
              />
            </div>
          </div>

          <IfSwitch label="Enabled" checked={enabled} onChange={setEnabled} />
          <IfSwitch label={<>Dry run <span className="text-[12px] text-muted">(plan only)</span></>} aria-label="Dry run"
            checked={dryRun} onChange={setDryRun} />
        </div>

        {/* Compose the payload with the rich PremadeForm (return-payload mode), or
         *  hand-edit the raw JSON directly (paste a big media_files pool, tweak a
         *  field the form doesn't expose). */}
        <div className="space-y-2 rounded-lg border border-border p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[14px] text-fg">{KIND_COPY[kind].items}:</span>
            <button
              type="button"
              onClick={() => (rawMode ? exitRaw() : enterRaw())}
              className="hidden text-[14px] text-accent hover:text-accent-hover md:inline"
            >
              {rawMode ? "← Composer" : "Edit raw JSON →"}
            </button>
          </div>

          {rawMode ? (
            <>
              <textarea
                value={rawText}
                onChange={(e) => {
                  setRawText(e.target.value);
                  if (err) setErr(null);
                }}
                rows={12}
                spellCheck={false}
                className="w-full rounded-md bg-bg border border-border text-[12px] font-mono px-2 py-1.5 text-fg focus:outline-none focus:border-accent"
                placeholder={`{ "${kind === "auto_posts" ? "posts" : "messages"}": [ … ] }`}
              />
              <div className="text-[12px] text-muted leading-relaxed">
                Edit the whole <code className="text-accent">
                  {kind === "auto_posts" ? "{ posts: [ … ] }" : "{ messages: [ … ] }"}
                </code>{" "}
                payload by hand — e.g. paste a <code className="text-accent">media_files</code> list
                and set <code className="text-accent">media_count</code>. The Dry-run switch above
                owns <code className="text-accent">dry_run</code>, so leave it out here.
              </div>
            </>
          ) : (
            <>
              <div className="text-[12px] text-muted">
                {summary ?? `No content yet — build this ${kind === "auto_posts" ? "feed" : "broadcast"} with the composer.`}
              </div>
              <IfButton variant={summary ? "default" : "primary"} onClick={() => setComposerOpen(true)}>
                {summary ? "Re-compose" : "Compose…"}
              </IfButton>
              {summary && (
                <details className="pt-1">
                  <summary className="text-[12px] text-accent cursor-pointer select-none">
                    View JSON
                  </summary>
                  <pre className="mt-1 text-[12px] font-mono text-fg-dim bg-bg border border-border rounded-md p-2 overflow-x-auto whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                    {JSON.stringify(composed, null, 2)}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>

        {err && <div className="text-[12px] text-err whitespace-pre-wrap">{err}</div>}
      </div>

      {composerOpen && (
        <ComposeModal
          kind={kind}
          accountId={accountId}
          initialPayload={composed}
          onClose={() => setComposerOpen(false)}
          onComposePayload={(p) => {
            setComposed(p);
            setComposerOpen(false);
            setErr(null);
          }}
        />
      )}
    </IfModal>
  );
}

/** Modal wrapper around PremadeForm in return-payload (compose) mode. */
function ComposeModal({
  kind,
  accountId,
  initialPayload,
  onClose,
  onComposePayload,
}: {
  kind: RuleKind;
  accountId: string;
  initialPayload?: Record<string, unknown>;
  onClose: () => void;
  onComposePayload: (payload: Record<string, unknown>) => void;
}) {
  const title =
    kind === "auto_posts" ? "Compose auto posts" : "Compose premade mass";
  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[640px] max-h-[90vh] flex flex-col bg-panel border border-border rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-fg-dim hover:text-fg text-lg leading-none w-11 h-11 -mr-2 -my-2 grid place-items-center shrink-0 md:w-auto md:h-auto md:mr-0 md:my-0 md:inline"
            title="Close"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          <PremadeForm
            kind={kind}
            forcedAccountId={accountId}
            initialPayload={initialPayload}
            onComposePayload={onComposePayload}
          />
        </div>
      </div>
    </div>
  );
}
