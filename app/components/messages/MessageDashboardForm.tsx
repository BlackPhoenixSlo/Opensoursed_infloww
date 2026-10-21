"use client";

/**
 * MessageDashboardForm — Infloww's Message dashboard filter form (page-parity ticket 30; bundle `AllMessageFilter$1`):
 * "Search for Creator message" (320px, a search icon) with the range box at the right, then a wrapping row of
 * `Label: field` pairs (70px label, 212px field, 40px apart): Sender, Creator, Sent to; Price `$ - $`; Purchased;
 * Status; Source; Type; then Reset and Search.
 *
 * The fields are staged, as Infloww's: edits change the form only; Search applies them, Reset clears and applies. The
 * range box beside the search is the page's and applies at once. The kind (Direct messages / OnlyFans mass messages)
 * comes from the tab, not the form.
 *
 * Wiring: Search = `q`; Sender = `employee_id`; Creator = `account_id`; Sent to = the fan search (`fan_query`, from 2
 * characters), or `#<fan id>` for one fan (`fan_id`, what a `?fan_id=` deep link fills in); Price = min / max in
 * dollars, sent as cents; Purchased = `status` paid / unpaid (on priced messages only, so `type=paid`), not wired on
 * the mass tab (a broadcast's summary row has no paid flag: paid / unpaid is per recipient, and the read ignores
 * `status` there); Status
 * Unsent = `unsent_only` (Sent is not wired: the read has no "not unsent" filter); Source AI chatbot / Employee =
 * `sender_type` automation / employee (AI Copilot is not wired: a Copilot send is recorded as the Employee's); Type
 * (the script filter) is not wired: no message row records the script it came from.
 */

import { useState, type ReactNode } from "react";

import { useActiveAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { IfButton, IfInput, IfSelect, type IfOption } from "@/components/ui/infloww";
import type { MessageKind, PaidStatus, SenderType, UsePaidMessagesParams } from "@/hooks/usePaidMessages";
import type { FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";

/** What Search hands up: the paid-messages params the form owns. */
export type DashboardParams = Required<Pick<UsePaidMessagesParams,
  "q" | "employee_id" | "account_id" | "fan_query" | "fan_id" | "min_price_cents" | "max_price_cents"
  | "status" | "type" | "unsent_only" | "sender_type" | "kind">>;

type Draft = {
  q: string;
  sender: string;
  creator: string;
  sentTo: string;
  minPrice: string;
  maxPrice: string;
  purchased: PaidStatus;
  status: "all" | "unsent";
  source: SenderType;
};

const EMPTY: Draft = {
  q: "", sender: "", creator: "", sentTo: "", minPrice: "", maxPrice: "", purchased: "all", status: "all", source: "any",
};

const NOT_WIRED = "not wired";

/** A 212px select; at its default ("All") the value is antd's placeholder colour, T3, as Infloww's form shows an empty
 *  field (`.ant-select-selection-placeholder{color:var(--tc-T3)}`); a picked value is T1. */
const field = (idle: boolean) => cn("w-[212px]", idle && "[&>button]:text-muted");

const PURCHASED: IfOption<PaidStatus>[] = [
  { value: "all", label: "All" },
  { value: "paid", label: "Paid" },
  { value: "unpaid", label: "Unpaid" },
];
const STATUS: IfOption<"all" | "sent" | "unsent">[] = [
  { value: "all", label: "All" },
  { value: "sent", label: <span title={NOT_WIRED}>Sent</span>, text: "Sent", disabled: true },
  { value: "unsent", label: "Unsent" },
];
const SOURCE: IfOption<SenderType | "copilot">[] = [
  { value: "any", label: "AI & Employee" },
  { value: "copilot", label: <span title={NOT_WIRED}>AI Copilot</span>, text: "AI Copilot", disabled: true },
  { value: "automation", label: "AI chatbot" },
  { value: "employee", label: "Employee" },
];
const SCRIPT: IfOption<"all" | "with" | "without">[] = [
  { value: "all", label: "All" },
  { value: "with", label: "With Script" },
  { value: "without", label: "No Script" },
];

/** A typed dollar amount as cents; blank or not a non-negative number = no bound. */
function toCents(raw: string): number | null {
  const n = Number(raw);
  return raw.trim() === "" || !Number.isFinite(n) || n < 0 ? null : Math.round(n * 100);
}

/** The Sent to box's initial text for a `?fan_id=` deep link. */
export function sentToFor(fanId: FanId | null | undefined): string {
  return fanId != null ? `#${fanId}` : "";
}

function toParams(d: Draft, kind: MessageKind): DashboardParams {
  const purchased = kind === "mass" ? "all" : d.purchased;
  const one = /^#(\d+)$/.exec(d.sentTo.trim());
  const fan = d.sentTo.trim();
  let lo = toCents(d.minPrice);
  let hi = toCents(d.maxPrice);
  if (lo != null && hi != null && lo > hi) [lo, hi] = [hi, lo]; // Infloww swaps a reversed pair
  const q = d.q.trim();
  return {
    q: q.length >= 2 ? q : "",
    employee_id: d.sender ? Number(d.sender) : null,
    account_id: d.creator || null,
    fan_id: one ? one[1] : null, // opaque: kept as the text typed (lib/fanId.ts)
    fan_query: !one && fan.length >= 2 ? fan : "",
    min_price_cents: lo,
    max_price_cents: hi,
    status: purchased,
    // Purchased only means something on a priced message (Infloww shows "--" on a free one).
    type: purchased === "all" ? "all" : "paid",
    unsent_only: d.status === "unsent",
    sender_type: d.source,
    kind,
  };
}

/** The params for a fresh form (Reset, and the tab's first read). */
export function initialParams(kind: MessageKind, fanId?: FanId | null): DashboardParams {
  return toParams({ ...EMPTY, sentTo: sentToFor(fanId) }, kind);
}

export default function MessageDashboardForm({ kind, fanId, onSearch, range }: {
  kind: MessageKind;
  /** A `?fan_id=` deep link: fills Sent to with `#<id>`. */
  fanId?: FanId | null;
  onSearch: (params: DashboardParams) => void;
  /** The page's range box, at the first row's right. */
  range?: ReactNode;
}) {
  const [draft, setDraft] = useState<Draft>(() => ({ ...EMPTY, sentTo: sentToFor(fanId) }));
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const accounts = useActiveAccounts();
  const { rows: employees } = useRoster({ includeDisabled: false, includeChatterMirrors: true });

  const senders: IfOption[] = [
    { value: "", label: "All" },
    ...employees.map((e) => ({ value: String(e.id), label: e.display_name, text: e.display_name })),
  ];
  const creators: IfOption[] = [
    { value: "", label: "All" },
    ...accounts.map((a) => ({ value: a.id, label: a.nickname || a.id, text: a.nickname || a.id })),
  ];

  const search = () => onSearch(toParams(draft, kind));
  const reset = () => {
    setDraft(EMPTY);
    onSearch(toParams(EMPTY, kind));
  };

  return (
    <form
      aria-label="Message filters"
      onSubmit={(e) => { e.preventDefault(); search(); }}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <IfInput
          search
          value={draft.q}
          onChange={(e) => set({ q: e.target.value })}
          maxLength={64}
          placeholder="Search for Creator message"
          aria-label="Search for Creator message"
          className="w-[320px] max-w-full rounded-lg"
        />
        {range}
      </div>

      <div className="flex flex-wrap items-center">
        <Field label="Sender">
          <IfSelect value={draft.sender} options={senders} onChange={(v) => set({ sender: v })} searchable
            aria-label="Sender" className={field(!draft.sender)} />
        </Field>
        <Field label="Creator">
          <IfSelect value={draft.creator} options={creators} onChange={(v) => set({ creator: v })} searchable
            aria-label="Creator" className={field(!draft.creator)} />
        </Field>
        <Field label="Sent to">
          <IfInput value={draft.sentTo} onChange={(e) => set({ sentTo: e.target.value })} maxLength={64}
            placeholder="Select recipient" aria-label="Sent to" title="A fan's username or name (2+ characters), or #<fan id>"
            className="w-[212px]" />
        </Field>
        <Field label="Price">
          <span className="flex items-center text-fg">
            <PriceInput label="Minimum price" value={draft.minPrice} onChange={(v) => set({ minPrice: v })} />
            <span aria-hidden className="px-2">-</span>
            <PriceInput label="Maximum price" value={draft.maxPrice} onChange={(v) => set({ maxPrice: v })} />
          </span>
        </Field>
        <Field label="Purchased">
          {kind === "mass" ? (
            <span title={NOT_WIRED} className="inline-block">
              <IfSelect value="all" options={PURCHASED} onChange={() => {}} disabled aria-label="Purchased"
                className={field(true)} />
            </span>
          ) : (
            <IfSelect value={draft.purchased} options={PURCHASED} onChange={(v) => set({ purchased: v })}
              aria-label="Purchased" className={field(draft.purchased === "all")} />
          )}
        </Field>
        <Field label="Status">
          <IfSelect value={draft.status} options={STATUS}
            onChange={(v) => { if (v !== "sent") set({ status: v }); }}
            aria-label="Status" className={field(draft.status === "all")} />
        </Field>
        <Field label="Source">
          <IfSelect value={draft.source} options={SOURCE}
            onChange={(v) => { if (v !== "copilot") set({ source: v }); }}
            aria-label="Source" className={field(draft.source === "any")} />
        </Field>
        <Field label="Type">
          <span title={NOT_WIRED} className="inline-block">
            <IfSelect value="all" options={SCRIPT} onChange={() => {}} disabled aria-label="Type"
              className={field(true)} />
          </span>
        </Field>
        <div className="mb-4 flex items-center gap-2">
          <IfButton onClick={reset}>Reset</IfButton>
          <IfButton type="submit" variant="primary">Search</IfButton>
        </div>
      </div>
    </form>
  );
}

/** Infloww's `bot-span` pair: a 70px left-aligned "Label:" 4px before the field; 16px under, 40px to the next. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4 mr-10 flex items-center text-[14px] text-fg">
      <span className="mr-1 w-[70px] shrink-0 whitespace-nowrap">{label}:</span>
      {children}
    </div>
  );
}

/** A 96px "$" box; typed in dollars. */
function PriceInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <span className="relative inline-flex">
      <IfInput
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^\d.]/g, ""))}
        maxLength={10}
        aria-label={label}
        className="w-24 [&_input]:pl-6"
      />
      {/* After the box, so it paints over the box's fill. */}
      <span aria-hidden className="pointer-events-none absolute left-[11px] top-1/2 -translate-y-1/2 text-[14px] text-fg">$</span>
    </span>
  );
}
