"use client";


import { useMemo, useState, type ReactNode } from "react";

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import {
  EmptyState, IF_TABLE, IfBody, IfButton, IfFilterFold, IfInput, IfModal, IfRangePicker, IfSelect, countActiveFilters,
  type IfOption,
} from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { useAutomationRules, useSwitchKind, type AutomationRule } from "@/hooks/useAutomations";
import { type LifecycleKind } from "@/hooks/useLifecycleMessageConfig";
import { useNudgeConfig } from "@/hooks/useNudgeConfig";
import { useFreePageRefusal } from "@/hooks/usePaidPage";
import { useReportTimeZone } from "@/lib/appliedSettings";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { AutomatedCard } from "./CreateMessagePopUp";
import { type ColumnLabel, dayOf, extrasCells, shortDate, slotLines, statusOf } from "./automatedRows";
import { DelayedWelcomeEditor } from "./DelayedWelcomeEditor";
import LifecycleMessageEditor, { PAID_ONLY_KINDS } from "./LifecycleMessageEditor";
import PurchaseFollowupEditor from "./PurchaseFollowupEditor";
import { SM, SM_AUTOMATED_COLUMNS, SM_TRIGGERS } from "./smartMessagesControls";
import { StatusPill } from "@/components/automations/StatusPill";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { useAccounts } from "@/hooks/useAccounts";

const NUDGE = SM_TRIGGERS[0];
const WELCOME = SM_TRIGGERS[1];
const PURCHASED = SM_TRIGGERS[2];
const LIFECYCLE = [
  [SM_TRIGGERS[3].label, "expiry_message"],
  [SM_TRIGGERS[4].label, "expired_message"],
  [SM_TRIGGERS[5].label, "resubscribe_message"],
  [SM_TRIGGERS[6].label, "birthday_message"],
] as const satisfies readonly (readonly [string, LifecycleKind])[];
type LifecycleTrigger = (typeof LIFECYCLE)[number][0];
const LIFECYCLE_KIND = new Map<string, LifecycleKind>(LIFECYCLE);
export type WiredTrigger = typeof NUDGE.label | typeof WELCOME.label | typeof PURCHASED.label | LifecycleTrigger;
const WIRED_TRIGGERS: ReadonlySet<string> = new Set<WiredTrigger>([
  NUDGE.label, WELCOME.label, PURCHASED.label, ...LIFECYCLE.map(([label]) => label),
]);
const STATUS_VALUES = [SM.statusScheduled, SM.statusActive, SM.statusCompleted, SM.statusCanceled];
const WIRED_STATUS: ReadonlySet<string> = new Set(STATUS_VALUES.map((s) => s.label));

type Row = {
  trigger: WiredTrigger;
  kind: string;
  on: boolean;
  created: string | null;
  search: string[];
  cells: Partial<Record<ColumnLabel, ReactNode>>;
  status: string;
};
type Filters = { q: string; status: string; trigger: string; createdFrom: string; createdTo: string };
const NO_FILTERS: Filters = { q: "", status: "", trigger: "", createdFrom: "", createdTo: "" };
const FOLDED = ["status", "trigger", ["createdFrom", "createdTo"]] as const;

const sentOf = (r: AutomationRule) => (typeof r.sent === "number" ? r.sent.toLocaleString("en-US") : undefined);

export default function AutomatedMessagesTab({ accountId }: { accountId: string | null }) {
  const rulesQ = useAutomationRules(accountId);
  const accountsLoading = useAccounts().isLoading;
  const loading = rulesQ.isLoading || (!accountId && accountsLoading);
  const cfgQ = useNudgeConfig(accountId);
  const reportTz = useReportTimeZone(accountId);
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [editing, setEditing] = useState<WiredTrigger | null>(null);
  const [cancelling, setCancelling] = useState<Row | null>(null);
  const switchKind = useSwitchKind(accountId);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    const messages = (trigger: WiredTrigger, text: string, status: string) => (
      <div className="max-md:max-w-[calc(100cqw-132px)]">
        <button type="button" className="max-w-full break-words text-left hover:text-accent md:truncate max-md:line-clamp-2"
          onClick={() => setEditing(trigger)}>
          {text}
        </button>
        <span className="block truncate text-[12px] text-fg-dim md:hidden">{trigger} · {status}</span>
      </div>
    );
    // rulesQ keeps the previous Creator's list while the next loads: match account_id.
    const rule = (rulesQ.data ?? []).find((r) => r.kind === "nudge_online" && r.account_id === accountId);
    if (rule) {
      const cfg = cfgQ.data?.account_id === accountId ? cfgQ.data : undefined;
      const lines = slotLines({ ...cfg?.defaults, ...cfg?.config }.slots);
      const status = statusOf(rule.is_enabled);
      out.push({
        trigger: NUDGE.label,
        kind: rule.kind,
        on: rule.is_enabled,
        created: dayOf(rule.created_at, reportTz),
        search: [rule.name, ...lines],
        status,
        cells: {
          Messages: messages(NUDGE.label, lines[0] ?? rule.name, status),
          Status: <SmPill status={status} />,
          Trigger: NUDGE.label,
          "Date created": shortDate(rule.created_at, reportTz) ?? undefined,
        },
      });
    }
    const welcome = (rulesQ.data ?? []).find((r) => r.kind === "send_welcome" && r.account_id === accountId);
    if (welcome) {
      const stored = welcome.payload?.message;
      const saved = Array.isArray(stored) ? stored[0] : stored;
      const text = typeof saved === "string" && saved.trim() ? saved : welcome.name;
      const status = statusOf(welcome.is_enabled, welcome.payload);
      out.push({
        trigger: WELCOME.label,
        kind: welcome.kind,
        on: welcome.is_enabled,
        created: dayOf(welcome.created_at, reportTz),
        search: [welcome.name, text],
        status,
        cells: {
          Messages: messages(WELCOME.label, text, status),
          Status: <SmPill status={status} />,
          Trigger: WELCOME.label,
          Sent: sentOf(welcome),
          ...extrasCells(typeof saved === "string" && saved.trim() ? welcome.payload : { ...welcome.payload, media_ids: [] }, reportTz),
          "Date created": shortDate(welcome.created_at, reportTz) ?? undefined,
        },
      });
    }
    const textRules: (readonly [WiredTrigger, string])[] = [[PURCHASED.label, "purchase_followup"], ...LIFECYCLE];
    for (const [trigger, kind] of textRules) {
      const r = (rulesQ.data ?? []).find((x) => x.kind === kind && x.account_id === accountId);
      if (!r) continue;
      const saved = r.payload?.text;
      const text = typeof saved === "string" && saved.trim() ? saved : r.name;
      const status = statusOf(r.is_enabled, r.payload);
      out.push({
        trigger,
        kind,
        on: r.is_enabled,
        created: dayOf(r.created_at, reportTz),
        search: [r.name, text],
        status,
        cells: {
          Messages: messages(trigger, text, status),
          Status: <SmPill status={status} />,
          Trigger: trigger,
          Sent: sentOf(r),
          ...extrasCells(r.payload, reportTz),
          "Date created": shortDate(r.created_at, reportTz) ?? undefined,
        },
      });
    }
    return out;
  }, [rulesQ.data, cfgQ.data, accountId, reportTz]);

  const q = applied.q.trim().toLowerCase();
  const shown = rows.filter((r) =>
    (!q || r.search.some((s) => s.toLowerCase().includes(q)))
    && (!applied.status || r.status === applied.status)
    && (!applied.trigger || r.trigger === applied.trigger)
    && (!applied.createdFrom || (!!r.created && r.created >= applied.createdFrom))
    && (!applied.createdTo || (!!r.created && r.created <= applied.createdTo)));

  const failures = [
    rulesQ.isError && rulesQ.data === undefined && "Couldn't load this Creator's automations.",
  ].filter((f): f is string => !!f);

  const set = (patch: Partial<Filters>) => setDraft((d) => ({ ...d, ...patch }));
  const tableWidth = SM_AUTOMATED_COLUMNS.reduce((w, c) => w + c.width, 0);

  return (
    <IfBody className="pb-6">
      <form
        className="flex flex-wrap items-center"
        onSubmit={(e) => { e.preventDefault(); setApplied(draft); }}
      >
        <IfInput
          search
          aria-label={SM.autoSearch.label}
          placeholder={SM.autoSearch.label}
          value={draft.q}
          onChange={(e) => set({ q: e.target.value })}
          className="mb-4 mr-4 w-full sm:w-[320px]"
        />
        <IfFilterFold active={countActiveFilters(applied, NO_FILTERS, FOLDED)} className="mb-4 mr-2">
          <Field id="sm-auto-status" label={SM.autoStatus.label}>
            <FilterSelect id="sm-auto-status" value={draft.status} onChange={(status) => set({ status })}
              options={STATUS_VALUES.map((s) => option(s.label, WIRED_STATUS.has(s.label)))} />
          </Field>
          <Field id="sm-auto-trigger" label={SM.autoTrigger.label}>
            <FilterSelect id="sm-auto-trigger" value={draft.trigger} onChange={(trigger) => set({ trigger })}
              options={SM_TRIGGERS.map((t) => option(t.label, WIRED_TRIGGERS.has(t.label)))} />
          </Field>
          <Field id="sm-auto-sent-to" label={SM.autoSentTo.label}>
            <FilterSelect id="sm-auto-sent-to" disabled />
          </Field>
          <Field id="sm-auto-start-date" label={SM.autoStartDate.label}>
            <IfRangePicker id="sm-auto-start-date" disabled title="not wired" className="max-w-full" />
          </Field>
          <Field id="sm-auto-date-created" label={SM.autoDateCreated.label} labelWidth={90}>
            <IfRangePicker
              id="sm-auto-date-created"
              from={draft.createdFrom}
              to={draft.createdTo}
              onChange={({ from, to }) => set({ createdFrom: from, createdTo: to })}
              className="max-w-full"
            />
          </Field>
          <Field id="sm-auto-created-by" label={SM.autoCreatedBy.label} labelWidth={80}>
            <FilterSelect id="sm-auto-created-by" disabled />
          </Field>
        </IfFilterFold>
        <div className="mb-4 flex gap-2">
          <IfButton onClick={() => { setDraft(NO_FILTERS); setApplied(NO_FILTERS); }}>{SM.autoReset.label}</IfButton>
          <IfButton type="submit" variant="primary">{SM.autoSearchButton.label}</IfButton>
        </div>
      </form>

      <div className="@container overflow-x-auto">
        <table className={cn(IF_TABLE.table, "table-fixed")} style={{ width: tableWidth }}>
          <thead>
            <tr>
              {SM_AUTOMATED_COLUMNS.map((c) => (
                <th key={c.id} style={{ width: c.width }}
                  className={cn(IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border", c.id === ACTIONS && cn(IF_TABLE.fixedRightHead, "z-[1] text-center"))}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonRows cols={SM_AUTOMATED_COLUMNS.length} rows={5} cellClassName={IF_TABLE.td} />
            ) : (
              <>
                {shown.map((r) => (
                  <tr key={r.trigger} onClick={() => setEditing(r.trigger)} className={cn(IF_TABLE.row, "group cursor-pointer hover:bg-bg-elev-1")}>
                    {SM_AUTOMATED_COLUMNS.map((c) => {
                      const v = c.id === ACTIONS
                        ? <RowActions row={r} pending={switchKind.isPending} onCancel={() => setCancelling(r)} />
                        : r.cells[c.label];
                      const fixed = c.id === ACTIONS && cn(IF_TABLE.fixedRight, "z-[1] text-center group-hover:bg-bg-elev-1");
                      return v === undefined
                        ? <td key={c.id} title="not wired" className={cn(IF_TABLE.td, "text-muted", fixed)}>—</td>
                        : <td key={c.id} className={cn(IF_TABLE.td, fixed)}>{v}</td>;
                    })}
                  </tr>
                ))}
                {failures.map((f) => <EmptyRow key={f} extra>{f}</EmptyRow>)}
                {shown.length === 0 && failures.length === 0 && <EmptyRow>{SM.autoEmpty.label}</EmptyRow>}
              </>
            )}
          </tbody>
        </table>
      </div>

      {switchKind.isError && <p className="mt-2 text-sm text-err">Couldn&apos;t cancel: {switchKind.error.message}</p>}
      {cancelling && (
        <IfModal
          width={416}
          title="Cancel message"
          onClose={() => setCancelling(null)}
          footer={(
            <>
              <IfButton onClick={() => setCancelling(null)}>Not now</IfButton>
              <IfButton
                variant="primary"
                disabled={switchKind.isPending}
                onClick={() => switchKind.mutate(
                  { kind: cancelling.kind, enable: false }, { onSettled: () => setCancelling(null) })}
              >
                Proceed with cancellation
              </IfButton>
            </>
          )}
        >
          <p className="text-fg-dim">The selected smart message will no longer be sent.</p>
        </IfModal>
      )}
      {editing && <AutomatedEditor trigger={editing} accountId={accountId} onClose={() => setEditing(null)} />}
    </IfBody>
  );
}

function RowActions({ row, pending, onCancel }: { row: Row; pending: boolean; onCancel: () => void }) {
  return (
    <span className="inline-flex flex-wrap justify-center gap-x-2" onClick={(e) => e.stopPropagation()}>
      {row.on && (
        <button
          type="button"
          aria-label={`Cancel ${row.trigger}`}
          disabled={pending}
          onClick={onCancel}
          className="text-accent hover:underline disabled:opacity-50"
        >
          Cancel
        </button>
      )}
      <button type="button" disabled title="not wired" className="text-fg-dim disabled:opacity-50 disabled:cursor-not-allowed">
        Duplicate
      </button>
    </span>
  );
}

function SmPill({ status }: { status: string }) {
  const tone = status === SM.statusActive.label ? "active" : status === SM.statusCanceled.label ? "warn" : "idle";
  return <StatusPill status={{ label: status, tone }} className="leading-4" />;
}

export function AutomatedEditor({
  trigger, accountId, onClose,
}: {
  trigger: WiredTrigger;
  accountId: string | null;
  onClose: () => void;
}) {
  // Escape closes only a clean draft (× and Cancel still close); the Nudge editor keeps its draft in localStorage and reports none.
  const [touched, setTouched] = useState(false);
  const onTouched = () => setTouched(true);
  return (
    <IfModal title={trigger} width={722} size="editor" onClose={onClose} keyboard={!touched}
      footer={<IfButton onClick={onClose}>Cancel</IfButton>} footerSlot>
      <div className="mb-4"><ExtraTag /></div>
      {trigger === NUDGE.label
        ? <NudgeOnlineTab key={accountId ?? ""} initialAccountId={accountId} />
        : trigger === PURCHASED.label
          ? <PurchaseFollowupEditor key={accountId ?? ""} accountId={accountId} onTouched={onTouched} />
          : LIFECYCLE_KIND.has(trigger)
            ? <LifecycleMessageEditor key={accountId ?? ""} accountId={accountId} kind={LIFECYCLE_KIND.get(trigger)!}
                onTouched={onTouched} />
            : <DelayedWelcomeEditor key={accountId ?? ""} accountId={accountId} onTouched={onTouched} />}
    </IfModal>
  );
}

export function AutomatedMessageCards({ onOpen, accountId = null }: {
  onOpen: (trigger: WiredTrigger) => void;
  accountId?: string | null;
}) {
  const freeRefusal = useFreePageRefusal(accountId);
  const refusalOf = (label: string) => {
    const kind = LIFECYCLE_KIND.get(label);
    return kind && PAID_ONLY_KINDS.has(kind) ? freeRefusal : null;
  };
  return (
    <>
      <p className="sm:col-span-2 text-sm text-fg-dim">
        <button
          type="button"
          disabled
          title="not wired"
          className="text-accent disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {SM.popUpScratch.label}
        </button>
        {" "}{SM.popUpTemplates.label}
      </p>
      {SM_TRIGGERS.map((t) => t.card && (
        <AutomatedCard
          key={t.id}
          title={t.card.label}
          desc={t.card.desc}
          tag={"tag" in t.card ? t.card.tag : undefined}
          onNext={WIRED_TRIGGERS.has(t.label) ? () => onOpen(t.label as WiredTrigger) : undefined}
          refusal={refusalOf(t.label)}
        />
      ))}
    </>
  );
}


function option(label: string, wired: boolean): IfOption {
  return wired
    ? { value: label, label }
    : { value: label, text: label, label: <span title="not wired">{label}</span>, disabled: true };
}

function FilterSelect({ id, value = "", options = [], onChange, disabled }: {
  id: string;
  value?: string;
  options?: IfOption[];
  onChange?: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <span title={disabled ? "not wired" : undefined} className="inline-flex w-full sm:w-[212px]">
      <IfSelect
        id={id}
        value={value || null}
        placeholder="All"
        options={[{ value: "", label: "All" }, ...options]}
        onChange={(v) => onChange?.(v)}
        disabled={disabled}
        className="w-full"
      />
    </span>
  );
}

const ACTIONS = "growth-smart-messages#52";

function Field({ id, label, labelWidth = 70, children }: { id: string; label: string; labelWidth?: number; children: ReactNode }) {
  return (
    <div className="mb-4 mr-10 flex max-w-full items-center max-sm:mr-0 max-sm:w-full">
      <label htmlFor={id} style={{ minWidth: labelWidth }} className="mr-1 shrink-0 whitespace-nowrap text-[14px] text-fg">{label}</label>
      {children}
    </div>
  );
}

function EmptyRow({ children, extra = false }: { children: ReactNode; extra?: boolean }) {
  return (
    <tr>
      <td colSpan={SM_AUTOMATED_COLUMNS.length} className="p-0">
        <div className="sticky left-0 w-[100cqw]">
          {extra
            ? <p title={EXTRA_LABEL} className="py-10 text-center text-[14px] text-muted">{children}</p>
            : <EmptyState kind="data" text={children} className="min-h-[400px]" />}
        </div>
      </td>
    </tr>
  );
}
