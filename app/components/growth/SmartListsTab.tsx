"use client";

/**
 * SmartListsTab — Growth → Smart lists, on Infloww's `SmartLists` page (page-parity 13): GrowthRailFrame draws the
 * 48px header and the creator rail; this is the content: the top box ("Search list name", "Create list"), the table
 * (List name, Criteria, Incl. expired, Fans, Actions), "Create smart list" / "Edit smart list" at 600 and the
 * "Delete smart list?" confirm at 416.
 *
 * A smart list is a saved rule set — spend (this creator or the whole agency, with a timeframe), purchase and message
 * recency, subscription facts, tags — resolved when used; reuse it as a mass-message audience (include/exclude in the
 * composer). Sync (Infloww's Smart lists Beta) keeps a real OnlyFans list in step with it, so Fans shows that list's
 * member count; an unsynced list has none ("-"). Ours, labelled: Match any (Infloww is all-only), the exact-count
 * preview, the active-list quota line and the preset cards that pre-fill the builder.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";
import { Plus, PlusCircle, X } from "lucide-react";

import { Badge, ExtraTag } from "@/components/ui/primitives";
import { EmptyState, IF_TABLE, IfButton, IfInput, IfModal } from "@/components/ui/infloww";
import { errMsg, useIfConfirm } from "@/components/growth/_bits";
import {
  useSmartListsPage, useCreateSmartList, useUpdateSmartList, useDeleteSmartList,
  useSetSmartListActive, usePreviewSmartList,
  type SmartField, type SmartOp, type SmartRule, type SmartRules, type SmartList,
  type SmartScope, type SmartTimeframe,
} from "@/hooks/useSmartLists";
import { cn } from "@/lib/utils";
import { GrowthRailFrame } from "@/components/growth/GrowthFrame";
import { useGrowthCreator } from "@/hooks/useAccounts";

/** Ours: the header's tooltip (Infloww's page has no description). */
export const SMART_LISTS_ABOUT =
  "Saved dynamic fan lists: build the criteria once (spend / recency / subscription / tag) and reuse the list as a " +
  "mass-message audience, or sync it to an OnlyFans list. Preview the exact count before you save.";

/** The condition row's native selects at antd's 32px. */
const SELECT_CLS =
  "h-8 rounded-md border border-border bg-transparent px-2 text-[14px] text-fg focus:outline-none focus:border-accent";

type Kind = "money" | "days" | "date" | "enum" | "tag";

interface FieldDef {
  field: SmartField;
  label: string;
  group: string;
  kind: Kind;
  scoped?: boolean;     // creator | org
  timeframe?: boolean;  // all | today | … | 90d
}

const FIELD_DEFS: FieldDef[] = [
  { field: "lifetime_spend",       group: "Spend", label: "Lifetime spend (OnlyFans total)", kind: "money" },
  { field: "total_spend",          group: "Spend", label: "Total spend",              kind: "money", scoped: true, timeframe: true },
  { field: "ppv_spend",            group: "Spend", label: "Messages / PPV spend",     kind: "money", scoped: true, timeframe: true },
  { field: "tips_spend",           group: "Spend", label: "Tips spend",               kind: "money", scoped: true, timeframe: true },
  { field: "subscription_spend",   group: "Spend", label: "Subscription spend",       kind: "money", scoped: true, timeframe: true },
  { field: "highest_spend",        group: "Spend", label: "Highest single purchase",  kind: "money", scoped: true, timeframe: true },
  { field: "last_spend_amount",    group: "Spend", label: "Last purchase amount",     kind: "money", scoped: true },
  { field: "recent_spend",         group: "Spend", label: "Spend in the last N days", kind: "money" },
  { field: "last_purchase_at",     group: "Activity", label: "Last purchase",         kind: "date", scoped: true },
  { field: "last_message_sent_at", group: "Activity", label: "Last message sent",     kind: "date" },
  { field: "last_active_days",     group: "Activity", label: "Days since active",     kind: "days" },
  { field: "idle_days",            group: "Activity", label: "Last purchase, message or subscribe", kind: "date" },
  { field: "status",               group: "Subscription", label: "Subscription status", kind: "enum" },
  { field: "renew",                group: "Subscription", label: "Auto-renew",        kind: "enum" },
  { field: "sub_start",            group: "Subscription", label: "Subscribed",        kind: "date" },
  { field: "expires_at",           group: "Subscription", label: "Subscription expires", kind: "date" },
  { field: "resubscribed_at",      group: "Subscription", label: "Resubscribed",      kind: "date" },
  { field: "tag",                  group: "Tags", label: "Tag",                      kind: "tag" },
];
const GROUPS = ["Spend", "Activity", "Subscription", "Tags"];

const ENUM_VALUES: Partial<Record<SmartField, string[]>> = {
  status: ["active", "expired"],
  renew: ["on", "off"],
};

const NUMERIC_OPS: SmartOp[] = [">=", "<=", ">", "<", "==", "!=", "between"];
const OP_LABEL: Partial<Record<SmartOp, string>> = {
  within_last: "in the last",
  more_than: "more than",
  within_next: "in the next",
  has: "has",
  not_has: "doesn't have",
};

const TIMEFRAME_LABEL: Record<SmartTimeframe, string> = {
  all: "all time", today: "today", yesterday: "yesterday", this_week: "this week",
  "7d": "last 7 days", "30d": "last 30 days", "90d": "last 90 days",
};

function defOf(field: SmartField): FieldDef {
  return FIELD_DEFS.find((f) => f.field === field) ?? FIELD_DEFS[0];
}

function opsFor(field: SmartField): SmartOp[] {
  const k = defOf(field).kind;
  if (k === "money" || k === "days") return NUMERIC_OPS;
  if (k === "date") {
    return field === "expires_at"
      ? ["within_next", "within_last", "more_than", "between"]
      : ["within_last", "more_than", "between"];
  }
  if (k === "enum") return ["==", "!="];
  return ["has", "not_has"];
}

/** UI rule row — values kept as strings (dollars for money, days for dates); converted to the wire shape (cents /
 *  days) on save. */
interface RuleUI {
  field: SmartField; op: SmartOp; value: string; value2: string; days: string;
  scope: SmartScope; timeframe: SmartTimeframe;
}

const EMPTY_RULE: RuleUI = {
  field: "lifetime_spend", op: ">=", value: "100", value2: "", days: "30",
  scope: "creator", timeframe: "all",
};

function defaultValue(field: SmartField): string {
  const k = defOf(field).kind;
  if (k === "enum") return ENUM_VALUES[field]![0];
  if (k === "tag") return "";
  return k === "money" ? "100" : "30";
}

function toUI(r: SmartRule): RuleUI {
  const money = defOf(r.field).kind === "money";
  const show = (v: unknown) => String(money ? Number(v) / 100 : v ?? "");
  const pair = Array.isArray(r.value) ? r.value : null;
  return {
    field: r.field, op: r.op,
    value: pair ? show(pair[0]) : show(r.value),
    value2: pair ? show(pair[1]) : "",
    days: String(r.days ?? 30),
    scope: r.scope ?? "creator",
    timeframe: r.timeframe ?? "all",
  };
}

function fromUI(r: RuleUI): SmartRule {
  const d = defOf(r.field);
  if (d.kind === "enum" || d.kind === "tag") return { field: r.field, op: r.op, value: r.value };
  const num = (s: string) =>
    d.kind === "money" ? Math.round(Number(s || 0) * 100) : Number(s || 0);
  const out: SmartRule = {
    field: r.field, op: r.op,
    value: r.op === "between" ? [num(r.value), num(r.value2)] : num(r.value),
  };
  if (d.scoped) out.scope = r.scope;
  if (d.timeframe) out.timeframe = r.timeframe;
  if (r.field === "recent_spend") out.days = Math.max(1, Math.round(Number(r.days || 30)));
  return out;
}

function describe(r: SmartRule): string {
  const d = defOf(r.field);
  const fmt = (v: unknown) =>
    d.kind === "money" ? `$${(Number(v) / 100).toLocaleString()}` : String(v);
  const val = Array.isArray(r.value) ? `${fmt(r.value[0])}–${fmt(r.value[1])}` : fmt(r.value);
  const unit = d.kind === "date" ? (r.op === "more_than" || r.op === "between" ? " days ago" : " days") : "";
  let s = `${d.label} ${OP_LABEL[r.op] ?? r.op} ${val}${unit}`;
  if (r.field === "recent_spend") s += ` (${r.days ?? 30}d)`;
  if (d.timeframe && r.timeframe && r.timeframe !== "all") s += ` (${TIMEFRAME_LABEL[r.timeframe]})`;
  if (d.scoped && r.scope === "org") s += " [agency]";
  return s;
}

function summarize(rules: SmartRules): string {
  if (!rules.rules?.length) return "everyone (no filters)";
  return rules.rules.map(describe).join(rules.match === "any" ? " OR " : " AND ");
}

/** A rule that keeps only active subscribers (so the list leaves expired fans out). */
const activeOnly = (r: SmartRule) =>
  r.field === "status" && ((r.op === "==" && r.value === "active") || (r.op === "!=" && r.value === "expired"));

/** Infloww's "Incl. expired": does the list let expired fans in? */
export function includesExpired(rules: SmartRules): boolean {
  const rs = rules.rules ?? [];
  if (!rs.length) return true;
  return rules.match === "any" ? !rs.every(activeOnly) : !rs.some(activeOnly);
}

// ── Presets: the legacy segments + Smart Tags, as builder pre-fills (ours) ──

interface Preset { group: string; name: string; hint: string; rules: SmartRules }
const all = (...rules: SmartRule[]): SmartRules => ({ match: "all", rules });
const PRESETS: Preset[] = [
  { group: "Spend segments", name: "Non-spenders", hint: "Lifetime spend $0",
    rules: all({ field: "lifetime_spend", op: "==", value: 0 }) },
  { group: "Spend segments", name: "Low spenders", hint: "Lifetime $1–$99",
    rules: all({ field: "lifetime_spend", op: "between", value: [100, 9999] }) },
  { group: "Spend segments", name: "Mid spenders", hint: "Lifetime $100–$499",
    rules: all({ field: "lifetime_spend", op: "between", value: [10000, 49999] }) },
  { group: "Spend segments", name: "Whales", hint: "Lifetime $500+",
    rules: all({ field: "lifetime_spend", op: ">=", value: 50000 }) },
  { group: "Sub length", name: "Subscribed under 1 month", hint: "Active, started ≤ 30 days ago",
    rules: all({ field: "status", op: "==", value: "active" }, { field: "sub_start", op: "within_last", value: 30 }) },
  { group: "Sub length", name: "Subscribed 1–6 months", hint: "Active, started 30–180 days ago",
    rules: all({ field: "status", op: "==", value: "active" }, { field: "sub_start", op: "between", value: [30, 180] }) },
  { group: "Sub length", name: "Subscribed 6+ months", hint: "Active, started > 180 days ago",
    rules: all({ field: "status", op: "==", value: "active" }, { field: "sub_start", op: "more_than", value: 180 }) },
  { group: "Lifecycle", name: "New fans", hint: "Subscribed in the last 7 days",
    rules: all({ field: "status", op: "==", value: "active" }, { field: "sub_start", op: "within_last", value: 7 }) },
  { group: "Lifecycle", name: "Expiring soon", hint: "Expires in 7 days, auto-renew off",
    rules: all({ field: "expires_at", op: "within_next", value: 7 }, { field: "renew", op: "==", value: "off" }) },
  { group: "Lifecycle", name: "Recently expired", hint: "Expired in the last 30 days",
    rules: all({ field: "status", op: "==", value: "expired" }, { field: "expires_at", op: "within_last", value: 30 }) },
  { group: "Lifecycle", name: "Resubscribed", hint: "Came back in the last 30 days",
    rules: all({ field: "resubscribed_at", op: "within_last", value: 30 }) },
  { group: "Lifecycle", name: "Ghost audience", hint: "Active, no purchase, message or subscribe in 30+ days",
    rules: all({ field: "status", op: "==", value: "active" }, { field: "idle_days", op: "more_than", value: 30 }) },
  { group: "Smart Tags", name: "$ fans", hint: "Spent $1–$99 in the last 30 days",
    rules: all({ field: "total_spend", op: "between", value: [100, 9999], scope: "creator", timeframe: "30d" }) },
  { group: "Smart Tags", name: "$$ fans", hint: "Spent $100–$499 in the last 30 days",
    rules: all({ field: "total_spend", op: "between", value: [10000, 49999], scope: "creator", timeframe: "30d" }) },
  { group: "Smart Tags", name: "$$$ fans", hint: "Spent $500+ in the last 30 days",
    rules: all({ field: "total_spend", op: ">=", value: 50000, scope: "creator", timeframe: "30d" }) },
];
const PRESET_GROUPS = Array.from(new Set(PRESETS.map((p) => p.group)));

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return d.toLocaleString();
}

function SyncBadge({ l }: { l: SmartList }) {
  if (!l.is_active) return null;
  const s = l.sync_state;
  if (s === "ok") return <Badge color="ok">synced</Badge>;
  if (s === "error") return <Badge color="err">sync error</Badge>;
  if (s === "syncing") return <Badge color="info">syncing…</Badge>;
  if (s === "pending") return <Badge color="warn">catching up</Badge>;
  return <Badge color="muted">queued</Badge>;
}

const HEADS = ["List name", "Criteria", "Incl. expired", "Fans", "Actions"];

interface Draft { key: number; editing: SmartList | null; name: string; rules: SmartRules | null }

export default function SmartListsTab({ accountId }: { accountId: string | null }) {
  const pageQ = useSmartListsPage(accountId);
  const createM = useCreateSmartList(accountId);
  const updateM = useUpdateSmartList(accountId);
  const deleteM = useDeleteSmartList(accountId);
  const activeM = useSetSmartListActive(accountId);
  const confirm = useIfConfirm();
  const alsoOf = useRef(false);

  const [draft, setDraft] = useState<Draft | null>(null);
  const [showPresets, setShowPresets] = useState(false);
  const [search, setSearch] = useState("");
  const [actionErr, setActionErr] = useState<string | null>(null);

  const lists = pageQ.data?.lists ?? [];
  const maxActive = pageQ.data?.max_active ?? 0;
  const activeCount = lists.filter((l) => l.is_active).length;
  const needle = search.trim().toLowerCase();
  const shown = needle ? lists.filter((l) => l.name.toLowerCase().includes(needle)) : lists;

  const open = (editing: SmartList | null, name = "", rules: SmartRules | null = null) =>
    setDraft((d) => ({ key: (d?.key ?? 0) + 1, editing, name: editing?.name ?? name, rules: editing?.rules ?? rules }));

  async function act(fn: () => Promise<unknown>) {
    setActionErr(null);
    try { await fn(); }
    catch (e) { setActionErr(errMsg(e, "Something went wrong. Try again")); }
  }

  async function remove(l: SmartList) {
    alsoOf.current = false;
    const body: ReactNode = (
      <div className="space-y-3">
        <p>&quot;{l.name}&quot; will be deleted. Messages already sent are not affected.</p>
        {l.of_list_id != null && (
          <label className="flex items-center gap-2 text-[14px] text-fg">
            <input type="checkbox" className="h-4 w-4 accent-accent"
              onChange={(e) => { alsoOf.current = e.target.checked; }} />
            Also delete the OnlyFans list
          </label>
        )}
      </div>
    );
    if (await confirm.ask("Delete smart list?", body, "Delete")) {
      const deleteOfList = alsoOf.current && l.of_list_id != null;
      await act(() => deleteM.mutateAsync({ id: l.id, deleteOfList }));
    }
  }

  const createButton = (
    <IfButton variant="primary" icon={PlusCircle} onClick={() => open(null)} disabled={!accountId}>Create list</IfButton>
  );

  let body: ReactNode;
  if (!accountId) body = <EmptyState kind="creator" text="No creator connected yet" />;
  else if (pageQ.isLoading) body = <p className="py-10 text-center text-fg-dim">Loading…</p>;
  else if (pageQ.isError) body = <EmptyState kind="error" text={errMsg(pageQ.error, "Failed to load")} onRetry={() => void pageQ.refetch()} />;
  else if (!lists.length) body = <EmptyState text="You haven’t created a smart list yet" action={createButton} />;
  else if (!shown.length) body = <EmptyState kind="search" />;

  return (
    <div className="space-y-4">
      {/* The bundle's top box: the search, then Create list, right-aligned, 16px apart. */}
      <div className="flex flex-wrap items-center justify-end gap-4">
        {maxActive > 0 && lists.length > 0 && (
          <span className="mr-auto flex items-center gap-2 text-[12px] text-fg-dim">
            {activeCount} / {maxActive} lists syncing to OnlyFans <ExtraTag />
          </span>
        )}
        <IfInput search aria-label="Search list name" placeholder="Search list name" value={search}
          onChange={(e) => setSearch(e.target.value)} className="w-[260px]" />
        <IfButton onClick={() => setShowPresets((v) => !v)} disabled={!accountId}>Presets</IfButton>
        {createButton}
      </div>

      {showPresets && (
        <div className="space-y-3 rounded-md border border-border p-4">
          <div className="flex items-center gap-2 text-[14px] text-fg">Start from a preset <ExtraTag /></div>
          {PRESET_GROUPS.map((g) => (
            <div key={g} className="space-y-1.5">
              <div className="text-[12px] text-fg-dim">{g}</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {PRESETS.filter((p) => p.group === g).map((p) => (
                  <button
                    key={p.name}
                    type="button"
                    onClick={() => { open(null, p.name, p.rules); setShowPresets(false); }}
                    className="rounded-md border border-border px-3 py-2 text-left hover:border-accent"
                  >
                    <div className="text-[14px] font-medium text-fg">{p.name}</div>
                    <div className="text-[12px] text-fg-dim">{p.hint}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {actionErr && <div role="alert" className="text-[12px] text-err">{actionErr}</div>}

      <div className="overflow-x-auto">
        <table aria-label="Smart lists" className={cn(IF_TABLE.table, "min-w-[720px]")}>
          <thead>
            <tr>
              {HEADS.map((h, i) => (
                <th key={h} className={cn(IF_TABLE.th, i < HEADS.length - 1 ? IF_TABLE.thDivider : IF_TABLE.fixedRightHead)}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body ? (
              <tr><td colSpan={HEADS.length} className="py-10">{body}</td></tr>
            ) : shown.map((l) => {
              const locked = l.sync_state === "syncing";
              const full = !l.is_active && maxActive > 0 && activeCount >= maxActive;
              return (
                <tr key={l.id} className={IF_TABLE.row}>
                  <td className={cn(IF_TABLE.td, "font-medium")}>
                    <span className="flex items-center gap-2">{l.name}<SyncBadge l={l} /></span>
                    {l.is_active && (
                      <span className="block text-[12px] font-normal text-fg-dim">
                        Last updated {fmtWhen(l.synced_at)}
                      </span>
                    )}
                    {l.is_active && l.sync_error && (
                      <span className="block text-[12px] font-normal text-err">{l.sync_error}</span>
                    )}
                  </td>
                  <td className={cn(IF_TABLE.td, "text-fg-dim")}>{summarize(l.rules)}</td>
                  <td className={IF_TABLE.td}>{includesExpired(l.rules) ? "Yes" : "No"}</td>
                  {/* An unsynced list is resolved when used, so it has no stored count. */}
                  <td className={IF_TABLE.td}>{l.is_active && l.member_count != null ? l.member_count : "-"}</td>
                  <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight)}>
                    <span className="flex items-center gap-4">
                      <IfButton
                        variant="link"
                        aria-label={`${l.is_active ? "Stop syncing" : "Sync"} ${l.name}`}
                        title={full ? `A maximum of ${maxActive} smart lists can sync` : undefined}
                        disabled={activeM.isPending || locked || full}
                        onClick={() => void act(() => activeM.mutateAsync({ id: l.id, active: !l.is_active }))}
                      >
                        {l.is_active ? "Stop sync" : "Sync"}
                      </IfButton>
                      <IfButton variant="link" aria-label={`Edit ${l.name}`} disabled={locked} onClick={() => open(l)}>Edit</IfButton>
                      <IfButton variant="link" aria-label={`Delete ${l.name}`} disabled={locked || deleteM.isPending} onClick={() => void remove(l)}>Delete</IfButton>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {draft && accountId && (
        <SmartListEditor
          key={draft.key}
          accountId={accountId}
          editing={draft.editing}
          initialName={draft.name}
          initialRules={draft.rules}
          onClose={() => setDraft(null)}
          onSave={async (name, rules) => {
            if (draft.editing) await updateM.mutateAsync({ id: draft.editing.id, name, rules });
            else await createM.mutateAsync({ name, rules });
            setDraft(null);
          }}
        />
      )}
      {confirm.modal}
    </div>
  );
}

/** Infloww's `CreateListPop`: "Create smart list" / "Edit smart list" at 600, the name, the criteria with "Add
 *  condition". Ours, labelled: Match any (Infloww is all-only) and the exact-count preview. */
function SmartListEditor({
  accountId, editing, initialName, initialRules, onClose, onSave,
}: {
  accountId: string;
  editing: SmartList | null;
  initialName: string;
  initialRules: SmartRules | null;
  onClose: () => void;
  onSave: (name: string, rules: SmartRules) => Promise<void>;
}) {
  const preview = usePreviewSmartList(accountId);
  const [name, setName] = useState(initialName);
  const [match, setMatch] = useState<"all" | "any">(initialRules?.match ?? "all");
  const [rows, setRows] = useState<RuleUI[]>(
    initialRules?.rules?.length ? initialRules.rules.map(toUI) : [{ ...EMPTY_RULE }],
  );
  const [err, setErr] = useState<string | null>(null);
  const [nameErr, setNameErr] = useState(false);
  const [busy, setBusy] = useState(false);

  const rules: SmartRules = useMemo(
    () => ({ match, rules: rows.map(fromUI) }), [match, rows],
  );

  const setRow = (i: number, patch: Partial<RuleUI>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addRow = () => setRows((rs) => [...rs, { ...EMPTY_RULE }]);
  const removeRow = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i));

  async function doPreview() {
    setErr(null);
    try { await preview.mutateAsync(rules); }
    catch (e) { setErr(errMsg(e, "Preview failed")); }
  }

  async function save() {
    setErr(null);
    if (!name.trim()) { setNameErr(true); return; }
    setBusy(true);
    try { await onSave(name.trim(), rules); }
    catch (e) { setErr(errMsg(e, editing ? "Unable to save smart list. Try again" : "Unable to create smart list. Try again")); }
    finally { setBusy(false); }
  }

  return (
    <IfModal
      title={editing ? "Edit smart list" : "Create smart list"}
      width={600}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={() => void save()} disabled={busy}>
            {busy ? "Saving…" : editing ? "Save changes" : "Create smart list"}
          </IfButton>
        </>
      )}
    >
      <div className="space-y-5">
        <div className="space-y-2">
          <label className="block text-[14px] text-fg" htmlFor="smart-list-name">Smart list name</label>
          <IfInput id="smart-list-name" value={name} placeholder="e.g. Active whales" className="w-full"
            onChange={(e) => { setName(e.target.value); setNameErr(false); }} />
          {nameErr && <span role="alert" className="block text-[12px] text-err">This is a required field</span>}
        </div>

        <div className="space-y-3">
          <div>
            <div className="text-[14px] text-fg">Criteria</div>
            <p className="mt-1 text-[12px] text-fg-dim">
              {match === "any"
                ? "Fans who meet any of the conditions are included on the list"
                : "Fans must meet all the conditions to be included on the list"}
            </p>
          </div>
          <label className="flex items-center gap-2 text-[14px] text-fg">
            <input type="checkbox" checked={match === "any"} onChange={(e) => setMatch(e.target.checked ? "any" : "all")}
              className="h-4 w-4 accent-accent" />
            Match any condition <ExtraTag />
          </label>

          {rows.map((r, i) => {
            const d = defOf(r.field);
            const unit = d.kind === "money" ? "$" : d.kind === "tag" ? "tag" : "days";
            return (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Condition"
                  className={SELECT_CLS}
                  value={r.field}
                  onChange={(e) => {
                    const field = e.target.value as SmartField;
                    setRow(i, { field, op: opsFor(field)[0], value: defaultValue(field), value2: "" });
                  }}
                >
                  {GROUPS.map((g) => (
                    <optgroup key={g} label={g}>
                      {FIELD_DEFS.filter((f) => f.group === g).map((f) => (
                        <option key={f.field} value={f.field}>{f.label}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <select aria-label="Operator" className={SELECT_CLS} value={r.op} onChange={(e) => setRow(i, { op: e.target.value as SmartOp })}>
                  {opsFor(r.field).map((op) => <option key={op} value={op}>{OP_LABEL[op] ?? op}</option>)}
                </select>
                {d.kind === "enum" ? (
                  <select aria-label="Value" className={SELECT_CLS} value={r.value} onChange={(e) => setRow(i, { value: e.target.value })}>
                    {ENUM_VALUES[r.field]!.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <IfInput
                    aria-label="Value"
                    className="w-24"
                    value={r.value}
                    onChange={(e) => setRow(i, { value: e.target.value })}
                    placeholder={unit}
                  />
                )}
                {r.op === "between" && (
                  <>
                    <span className="text-[12px] text-fg-dim">and</span>
                    <IfInput aria-label="Upper value" className="w-24" value={r.value2}
                      onChange={(e) => setRow(i, { value2: e.target.value })} placeholder={unit} />
                  </>
                )}
                {d.kind === "date" && (
                  <span className="text-[12px] text-fg-dim">
                    {r.op === "more_than" || r.op === "between" ? "days ago" : "days"}
                  </span>
                )}
                {r.field === "recent_spend" && (
                  <span className="flex items-center gap-1 text-[12px] text-fg-dim">
                    in last
                    <IfInput aria-label="Days" className="w-16" value={r.days} onChange={(e) => setRow(i, { days: e.target.value })} />
                    days
                  </span>
                )}
                {d.timeframe && (
                  <select aria-label="Timeframe" className={SELECT_CLS} value={r.timeframe}
                    onChange={(e) => setRow(i, { timeframe: e.target.value as SmartTimeframe })}>
                    {(Object.keys(TIMEFRAME_LABEL) as SmartTimeframe[]).map((t) => (
                      <option key={t} value={t}>{TIMEFRAME_LABEL[t]}</option>
                    ))}
                  </select>
                )}
                {d.scoped && (
                  <select aria-label="Scope" className={SELECT_CLS} value={r.scope}
                    onChange={(e) => setRow(i, { scope: e.target.value as SmartScope })}>
                    <option value="creator">this creator</option>
                    <option value="org">whole agency</option>
                  </select>
                )}
                {rows.length > 1 && (
                  <button type="button" className="grid h-6 w-6 place-items-center text-muted hover:text-err" onClick={() => removeRow(i)} aria-label="Remove condition">
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                )}
              </div>
            );
          })}
          <IfButton variant="link" icon={Plus} onClick={addRow}>Add condition</IfButton>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <IfButton onClick={() => void doPreview()} disabled={preview.isPending}>
            {preview.isPending ? "Counting…" : "Preview count"}
          </IfButton>
          <ExtraTag />
          {preview.data && (
            <span className="text-[14px] text-fg">
              <b>{preview.data.count}</b>
              <span className="text-fg-dim"> / {preview.data.total_fans} fans match</span>
            </span>
          )}
        </div>
        {preview.data && preview.data.sample.length > 0 && (
          <div className="text-[12px] text-fg-dim">
            Sample: {preview.data.sample.slice(0, 8).map((s) => s.name).join(", ")}
            {preview.data.count > 8 && " …"}
          </div>
        )}
        {err && <div role="alert" className="text-[12px] text-err">{err}</div>}
      </div>
    </IfModal>
  );
}

/** /growth/smart-lists: this tab in the Growth rail frame, its title carrying SMART_LISTS_ABOUT. */
export function SmartListsPage() {
  const creator = useGrowthCreator();
  return (
    <GrowthRailFrame title={<span title={SMART_LISTS_ABOUT}>Smart lists</span>} creator={creator}>
      <SmartListsTab accountId={creator.accountId} />
    </GrowthRailFrame>
  );
}
