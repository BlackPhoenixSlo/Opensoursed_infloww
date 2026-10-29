"use client";

/**
 * Smart Messages' "Automated Messages" tab (Phase 2 of
 * docs/spec/infloww-parity-round-2/phase-02-growth-pages.md), laid out from the
 * Layout capture (`docs/infloww-layouts/growth-smart-messages.md`, #23 to #53;
 * labels and sources in `smartMessagesControls`).
 *
 * The list holds per-Fan Triggers only, never a Mass message, and is built on
 * the client from the Creator's existing reads: no list endpoint. Three rows at
 * most, each present only when configured, in the Trigger catalogue's order:
 *
 * - "Nudge", the `nudge_online` rule, Status "Active" while the rule is on and
 *   "Canceled" while it is off; it opens the existing nudge editor
 *   (`NudgeOnlineTab`).
 * - "Delayed welcome" (ticket 43, rebound by the owner's ruling of
 *   2026-10-18), our `send_welcome` rule, Status "Active" while the rule is on
 *   and "Canceled" while it is off; it opens the Delayed welcome editor
 *   (`DelayedWelcomeEditor`: the rule's on/off, check interval, message and
 *   its Smart Message settings).
 *   OnlyFans' own welcome slot is no longer a row.
 * - "Purchased" (ticket 44, owner ruling N2 position B), the
 *   `purchase_followup` rule: one message to a fan after he buys a PPV,
 *   Status "Active" while the rule is on and "Canceled" while it is off; it
 *   opens `PurchaseFollowupEditor` (on/off, text, Smart Message settings).
 * - "Nearing expiry", "Expired", "Resubscribe" and "Birthday", the
 *   `expiry_message`, `expired_message`, `resubscribe_message` and
 *   `birthday_message` rules (automations/lifecycle_messages), built as the
 *   Purchased row; each opens `LifecycleMessageEditor` (on/off, text, and N
 *   hours for the two expiry Triggers). "Not Purchased" has no rule in the
 *   bundle's rules enum, so it stays Not wired.
 *
 * Each editor opens on the same Creator in a dialog labelled "Inflowwww
 * extra": it is our editor, not Infloww's seven-step wizard.
 *
 * The filter bar's search (on the message text), Status, Trigger and Date
 * created (the rule's creation day in the report time zone) filter the rows,
 * applied by Search as the bundle's bar is. The Actions cell offers the
 * bundle's Cancel on an Active row, confirmed in the bundle's "Cancel message"
 * dialog (the kind's switch, off); Duplicate has no meaning for a
 * one-rule-per-kind Trigger, so it is Not wired. Sent is the rules list's
 * `sent` (the messages the rule really sent; fans welcomed, for the welcome),
 * on every row but Nudge's. Attachment(s), Price, Start date and End date
 * read the rule's Smart Message settings (`SmartMessageFields`), "--" when
 * unset as the bundle shows them, and a rule that is on reads "Scheduled"
 * before its Effective date and "Completed" from its Expiry. The other
 * filters, the
 * Triggers and status values no row of ours can take, and every cell no
 * existing read fills are Not wired (`disabled`, `title="not wired"`, "—").
 *
 * It also fills the Create message pop-up's Automated messages section
 * (`AutomatedMessageCards`, ticket 42) from the same Trigger catalogue and
 * wired set, so the section and the filter cannot disagree.
 */

import { useMemo, useState, type ReactNode } from "react";

import NudgeOnlineTab from "@/components/settings/NudgeOnlineTab";
import {
  EmptyState, IF_TABLE, IfBody, IfButton, IfInput, IfModal, IfRangePicker, IfSelect, type IfOption,
} from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { useAutomationRules, useSwitchKind, type AutomationRule } from "@/hooks/useAutomations";
import { type LifecycleKind } from "@/hooks/useLifecycleMessageConfig";
import { useNudgeConfig, type NudgeSlots } from "@/hooks/useNudgeConfig";
import { useFreePageRefusal } from "@/hooks/usePaidPage";
import { useReportTimeZone } from "@/lib/appliedSettings";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { AutomatedCard } from "./CreateMessagePopUp";
import { extrasOfPayload } from "./SmartMessageFields";
import { DelayedWelcomeEditor } from "./DelayedWelcomeEditor";
import LifecycleMessageEditor, { PAID_ONLY_KINDS } from "./LifecycleMessageEditor";
import PurchaseFollowupEditor from "./PurchaseFollowupEditor";
import { SM, SM_AUTOMATED_COLUMNS, SM_TRIGGERS } from "./smartMessagesControls";
import { fmtPrice } from "@/lib/format";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { useAccounts } from "@/hooks/useAccounts";

const NUDGE = SM_TRIGGERS[0];
const WELCOME = SM_TRIGGERS[1];
const PURCHASED = SM_TRIGGERS[2];
/** The lifecycle Triggers, by list label, and the rule kind each one is. */
const LIFECYCLE = [
  [SM_TRIGGERS[3].label, "expiry_message"],
  [SM_TRIGGERS[4].label, "expired_message"],
  [SM_TRIGGERS[5].label, "resubscribe_message"],
  [SM_TRIGGERS[6].label, "birthday_message"],
] as const satisfies readonly (readonly [string, LifecycleKind])[];
type LifecycleTrigger = (typeof LIFECYCLE)[number][0];
const LIFECYCLE_KIND = new Map<string, LifecycleKind>(LIFECYCLE);
/** A wired Trigger: one a row of ours can carry, whose pop-up card opens its editor. */
export type WiredTrigger = typeof NUDGE.label | typeof WELCOME.label | typeof PURCHASED.label | LifecycleTrigger;
/** The wired Triggers; every other is Not wired in the filter and in the pop-up alike. */
const WIRED_TRIGGERS: ReadonlySet<string> = new Set<WiredTrigger>([
  NUDGE.label, WELCOME.label, PURCHASED.label, ...LIFECYCLE.map(([label]) => label),
]);
const STATUS_VALUES = [SM.statusScheduled, SM.statusActive, SM.statusCompleted, SM.statusCanceled];
/** Every status a row of ours can take: a rule is on or off, and one that is
 *  on can sit before its Effective date or past its Expiry. */
const WIRED_STATUS: ReadonlySet<string> = new Set(STATUS_VALUES.map((s) => s.label));
/** A rule or switch that is on reads "Active", off "Canceled"; on, before its
 *  Effective date "Scheduled", from its Expiry "Completed". */
function statusOf(on: boolean, payload?: Record<string, unknown>, now: number = Date.now()): string {
  if (!on) return SM.statusCanceled.label;
  const { starts_at, ends_at } = extrasOfPayload(payload);
  if (starts_at && Date.parse(starts_at) > now) return SM.statusScheduled.label;
  if (ends_at && Date.parse(ends_at) <= now) return SM.statusCompleted.label;
  return SM.statusActive.label;
}

type ColumnLabel = (typeof SM_AUTOMATED_COLUMNS)[number]["label"];
type Row = {
  trigger: WiredTrigger;
  /** The rule's kind and on/off: the Actions cell's Cancel switches it off. */
  kind: string;
  on: boolean;
  /** The rule's creation day, YYYY-MM-DD in the report time zone (Date created). */
  created: string | null;
  /** Every text the search looks in: the rule's name and each message line. */
  search: string[];
  /** The cells a read fills, by column; any column missing is Not wired. */
  cells: Partial<Record<ColumnLabel, ReactNode>>;
  status: string;
};
type Filters = { q: string; status: string; trigger: string; createdFrom: string; createdTo: string };
const NO_FILTERS: Filters = { q: "", status: "", trigger: "", createdFrom: "", createdTo: "" };

/** Every message line of the nudge's tease pools, in stored order. */
function slotLines(slots: NudgeSlots | undefined): string[] {
  return Object.values(slots ?? {})
    .flatMap((bucket) => Object.values(bucket ?? {}).flatMap((entry) => entry?.text ?? []))
    .map((t) => t.trim())
    .filter(Boolean);
}

/** The cells a rule's Smart Message settings fill: the bundle's " --" / "--"
 *  where one is unset (index.9f50f370.js @16299052, @16300051, @16301218). */
function extrasCells(payload: Record<string, unknown>, timeZone: string | null): Partial<Record<ColumnLabel, ReactNode>> {
  const x = extrasOfPayload(payload);
  const n = x.media_ids?.length ?? 0;
  const price = (x.price_cents ?? 0) / 100;
  return {
    "Attachment(s)": n ? `${n} media` : "--",
    Price: price ? fmtPrice(Math.round(price * 100)) : "--",
    "Start date": shortDate(x.starts_at ?? null, timeZone) ?? "--",
    "End date": shortDate(x.ends_at ?? null, timeZone) ?? "--",
  };
}

/** The Sent cell: the rules list's count of what the rule really sent. */
const sentOf = (r: AutomationRule) => (typeof r.sent === "number" ? r.sent.toLocaleString("en-US") : undefined);

/** "MMM D, YYYY" in the report time zone, as the bundle's date columns render
 *  (`dayjs(...).tz(sn).format("MMM D, YYYY")`, index.9f50f370.js @16301606);
 *  the browser's zone when none is saved. */
function shortDate(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: timeZone ?? undefined });
}

/** The day of `iso` as YYYY-MM-DD in the report time zone, for the Date
 *  created filter's comparison. */
function dayOf(iso: string | null, timeZone: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-CA", { timeZone: timeZone ?? undefined });
}

export default function AutomatedMessagesTab({ accountId }: { accountId: string | null }) {
  const rulesQ = useAutomationRules(accountId);
  // No Creator yet because the Creators are still loading: the table is loading, not empty.
  const accountsLoading = useAccounts().isLoading;
  const loading = rulesQ.isLoading || (!accountId && accountsLoading);
  const cfgQ = useNudgeConfig(accountId);
  const reportTz = useReportTimeZone(accountId);
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [editing, setEditing] = useState<WiredTrigger | null>(null);
  // The row whose Cancel waits on the bundle's confirmation.
  const [cancelling, setCancelling] = useState<Row | null>(null);
  const switchKind = useSwitchKind(accountId);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    const messages = (trigger: WiredTrigger, text: string) => (
      <button type="button" className="max-w-full truncate text-left hover:text-accent" onClick={() => setEditing(trigger)}>
        {text}
      </button>
    );
    // The rules read keeps the previous Creator's list while the next one
    // loads, so a rule counts only for the Creator it belongs to.
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
          Messages: messages(NUDGE.label, lines[0] ?? rule.name),
          Status: <StatusPill status={status} />,
          Trigger: NUDGE.label,
          "Date created": shortDate(rule.created_at, reportTz) ?? undefined,
        },
      });
    }
    // Our welcome automation, as the Nudge row: its rule, this Creator's only.
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
          Messages: messages(WELCOME.label, text),
          Status: <StatusPill status={status} />,
          Trigger: WELCOME.label,
          Sent: sentOf(welcome),
          // Media and price ride on the written message only.
          ...extrasCells(typeof saved === "string" && saved.trim() ? welcome.payload : { ...welcome.payload, media_ids: [] }, reportTz),
          "Date created": shortDate(welcome.created_at, reportTz) ?? undefined,
        },
      });
    }
    // The purchase message and the lifecycle messages: each rule holds its
    // text and its on/off.
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
          Messages: messages(trigger, text),
          Status: <StatusPill status={status} />,
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
    // Body padding 16px 24px 24px (#23).
    <IfBody className="pb-6">
      <form
        className="flex flex-wrap items-center"
        onSubmit={(e) => { e.preventDefault(); setApplied(draft); }}
      >
        {/* Search message (#24): 320px, the search icon at its right, 16px right (#25). */}
        <IfInput
          search
          aria-label={SM.autoSearch.label}
          placeholder={SM.autoSearch.label}
          value={draft.q}
          onChange={(e) => set({ q: e.target.value })}
          className="mb-4 mr-4 w-full sm:w-[320px]"
        />
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
        {/* Reset, then Search, 8px apart (#38). */}
        <div className="mb-4 flex gap-2">
          <IfButton onClick={() => { setDraft(NO_FILTERS); setApplied(NO_FILTERS); }}>{SM.autoReset.label}</IfButton>
          <IfButton type="submit" variant="primary">{SM.autoSearchButton.label}</IfButton>
        </div>
      </form>

      {/* The 14 columns at the capture's widths, in a horizontal scroller (a
          container, so an empty or loading line can span its visible width). */}
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
                  // The bundle opens a row on a click anywhere in it (`onRow`, index.9f50f370.js @16303616).
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
                {/* A failed read hides only its own row. */}
                {failures.map((f) => <EmptyRow key={f} extra>{f}</EmptyRow>)}
                {shown.length === 0 && failures.length === 0 && <EmptyRow>{SM.autoEmpty.label}</EmptyRow>}
              </>
            )}
          </tbody>
        </table>
      </div>

      {switchKind.isError && <p className="mt-2 text-sm text-err">Couldn&apos;t cancel: {switchKind.error.message}</p>}
      {/* The bundle's confirmation (AutoMessageTable's WithdrawModal, index.9f50f370.js @16304178): antd's 416px confirm. */}
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

/** The Actions cell (#52): the bundle's Cancel while a row is Active (its
 *  rule's switch, off), never on a Canceled one; Duplicate, Not wired (one
 *  rule per kind: a copy has nowhere to go). Its clicks never open the row. */
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

function StatusPill({ status }: { status: string }) {
  // Status pill (#98): 16px radius, 2px 8px padding; Active (#100) and
  // Canceled (#102) in the app's palette, Scheduled and Completed neutral.
  return (
    <span
      className={cn(
        "inline-block rounded-2xl px-2 py-0.5 text-xs",
        status === SM.statusActive.label ? "bg-accent/15 text-accent"
          : status === SM.statusCanceled.label ? "bg-warn/15 text-warn" : "bg-fg-dim/15 text-fg-dim",
      )}
    >
      {status}
    </span>
  );
}

/** A wired Trigger's editor, in a dialog headed with its Trigger label, on
 *  `accountId`: the existing nudge editor (`NudgeOnlineTab`) for "Nudge", the
 *  `send_welcome` rule's editor (`DelayedWelcomeEditor`) for "Delayed welcome",
 *  the purchase message's editor (`PurchaseFollowupEditor`) for "Purchased",
 *  `LifecycleMessageEditor` for the four lifecycle Triggers.
 *  Its row opens it, and so does its card in the Create message pop-up. */
export function AutomatedEditor({
  trigger, accountId, onClose,
}: {
  trigger: WiredTrigger;
  accountId: string | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sm-auto-editor-title"
        className="w-full max-w-[720px] max-h-[90vh] flex flex-col bg-panel border border-border rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center gap-2">
          <h2 id="sm-auto-editor-title" className="text-sm font-semibold">{trigger}</h2>
          {/* Our editor, not Infloww's seven-step wizard. */}
          <ExtraTag />
          <button
            type="button"
            aria-label="Close"
            title="Close"
            onClick={onClose}
            className="ml-auto text-fg-dim hover:text-fg text-lg leading-none"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {/* Keyed on the Creator: it opens on the chip's pick. */}
          {trigger === NUDGE.label
            ? <NudgeOnlineTab key={accountId ?? ""} initialAccountId={accountId} />
            : trigger === PURCHASED.label
              ? <PurchaseFollowupEditor key={accountId ?? ""} accountId={accountId} />
              : LIFECYCLE_KIND.has(trigger)
                ? <LifecycleMessageEditor key={accountId ?? ""} accountId={accountId} kind={LIFECYCLE_KIND.get(trigger)!} />
                : <DelayedWelcomeEditor key={accountId ?? ""} accountId={accountId} />}
        </div>
      </div>
    </div>
  );
}

/** The Create message pop-up's Automated messages section (#104, #105, #109,
 *  and the Triggers' cards), filled into the pop-up's slot: "Start from
 *  scratch" and the template line, then one card per Trigger that has one, in
 *  the catalogue's order. "Start from scratch" opens a blank Smart Message in
 *  the bundle, which we have no editor for, so it is Not wired. The cards read
 *  the same catalogue and the same wired set as the Trigger filter: every
 *  wired Trigger's card opens its editor (`onOpen`), every other is Not wired.
 *  On `accountId`'s free page the Triggers Infloww keeps for paid pages are
 *  refused with the bundle's message, as its card click refuses them. */
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
      {/* The bundle's line above the cards (`msg-modal-desc`, index.9f50f370.js @14715218). */}
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

// Status, Trigger, Sent to and Created by selects: 212px (#27, #29, #30, #33),
// each opening on the bundle's placeholder "All" (index.9f50f370.js @16287927,
// @16288417, @16288845, @16289680).

/** A filter option; one with nothing behind it is Not wired (disabled, titled). */
function option(label: string, wired: boolean): IfOption {
  return wired
    ? { value: label, label }
    : { value: label, text: label, label: <span title="not wired">{label}</span>, disabled: true };
}

/** A 212px filter select (`IfSelect`) showing the placeholder "All" until a pick; "All" is also its first option,
 *  which clears the pick. `disabled`: Not wired, titled so. Full width below `sm`. */
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

/** The Actions column (#52), which the bundle fixes at the table's right
 *  (`fixed:"right"`, `align:"center"`, index.9f50f370.js @16302024): it stays
 *  in view while the other 13 columns scroll under it. */
const ACTIONS = "growth-smart-messages#52";

/** One filter field: its label (70px wide, 4px right, #35) and control; 16px
 *  below and 40px right (#34). */
function Field({ id, label, labelWidth = 70, children }: { id: string; label: string; labelWidth?: number; children: ReactNode }) {
  return (
    <div className="mb-4 mr-10 flex max-w-full items-center max-sm:mr-0 max-sm:w-full">
      {/* At least the capture's width, on one line: our face is wider than
          the bundle's, so a label grows rather than wraps. */}
      <label htmlFor={id} style={{ minWidth: labelWidth }} className="mr-1 shrink-0 whitespace-nowrap text-[14px] text-fg">{label}</label>
      {children}
    </div>
  );
}

/** A line across the table. `extra`: the house's loading or read-failure
 *  line (T3 14px), labelled, in place of antd's spinner and `CommonRetryBox`;
 *  else the bundle's empty state, its art over "No Data" in a 400px body. */
function EmptyRow({ children, extra = false }: { children: ReactNode; extra?: boolean }) {
  return (
    <tr>
      {/* Pinned to the scroller's visible width, as antd pins its empty cell,
          so "No Data" shows without scrolling the 14 columns. */}
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
