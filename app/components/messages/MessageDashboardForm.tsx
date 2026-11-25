"use client";


import { useState, type ReactNode } from "react";

import { useActiveAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { IfButton, IfInput, IfSelect, type IfOption } from "@/components/ui/infloww";
import type { MessageKind, PaidStatus, SenderType, UsePaidMessagesParams } from "@/hooks/usePaidMessages";
import type { FanId } from "@/lib/fanId";
import { dollarsToCents as toCents } from "@/lib/format";
import { cn } from "@/lib/utils";

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

export function sentToFor(fanId: FanId | null | undefined): string {
  return fanId != null ? `#${fanId}` : "";
}

function toParams(d: Draft, kind: MessageKind): DashboardParams {
  const purchased = kind === "mass" ? "all" : d.purchased;
  const one = /^#(\d+)$/.exec(d.sentTo.trim());
  const fan = d.sentTo.trim();
  let lo = toCents(d.minPrice);
  let hi = toCents(d.maxPrice);
  if (lo != null && hi != null && lo > hi) [lo, hi] = [hi, lo];
  const q = d.q.trim();
  return {
    q: q.length >= 2 ? q : "",
    employee_id: d.sender ? Number(d.sender) : null,
    account_id: d.creator || null,
    // fan_id is opaque text, never numeric (lib/fanId.ts)
    fan_id: one ? one[1] : null,
    fan_query: !one && fan.length >= 2 ? fan : "",
    min_price_cents: lo,
    max_price_cents: hi,
    status: purchased,
    type: purchased === "all" ? "all" : "paid",
    unsent_only: d.status === "unsent",
    sender_type: d.source,
    kind,
  };
}

export function initialParams(kind: MessageKind, fanId?: FanId | null): DashboardParams {
  return toParams({ ...EMPTY, sentTo: sentToFor(fanId) }, kind);
}

export default function MessageDashboardForm({ kind, fanId, onSearch, range }: {
  kind: MessageKind;
  fanId?: FanId | null;
  onSearch: (params: DashboardParams) => void;
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4 mr-10 flex items-center text-[14px] text-fg">
      <span className="mr-1 w-[70px] shrink-0 whitespace-nowrap">{label}:</span>
      {children}
    </div>
  );
}

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
      <span aria-hidden className="pointer-events-none absolute left-[11px] top-1/2 -translate-y-1/2 text-[14px] text-fg">$</span>
    </span>
  );
}
