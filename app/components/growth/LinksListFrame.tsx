"use client";


import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Calendar, ChevronDown, EllipsisVertical, GitMerge, MessageSquareWarning, Pencil, Plus, Search, Tag, Upload, X,
} from "lucide-react";

import { ExtraTag } from "@/components/ui/primitives";
import {
  EmptyState, HB_TABLE, HbButton, HbFilterLg, HbModal, HbPager, HbSelect, IfFilterFold, countActiveFilters, type IfOption,
} from "@/components/ui/infloww";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { Menu } from "@/components/ui/Menu";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useActiveAccounts } from "@/hooks/useAccounts";
import type { AccountMeta } from "@/lib/relay";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { downloadCsv as saveCsv } from "@/lib/csv";
import { parseUtc } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";
import { Skeleton, SkeletonRows } from "@/components/ui/Skeleton";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { usePagedFilters } from "@/hooks/pagedFilters";
import { addDays, createdDay, dayKey, monthStartBefore } from "@/components/growth/frameDates";
import { InfoTip } from "@/components/ui/InfoTip";
import { IfDateInput } from "@/components/ui/ifDateInput";

export const NOT_WIRED = "not wired";

export type LinksVariant = "TRACKING" | "FREETRIAL";
const VARIANT_TEXT: Record<LinksVariant, { create: string; search: string; name: string }> = {
  TRACKING: { create: "Create tracking link", search: "Search tracking link name", name: "Tracking link" },
  FREETRIAL: { create: "Create free trial link", search: "Search free trial link name", name: "Free trial links" },
};


export function useReportTz(): { reportTz: string | null; ready: boolean } {
  const applied = useAppliedSettings();
  return { reportTz: applied.data?.preferences?.report_tz ?? null, ready: !applied.isPending };
}

function ReportTimeZone() {
  const { reportTz, ready } = useReportTz();
  return (
    <span className="mx-2 flex items-center text-sm leading-normal text-fg-dim">
      <span className="mr-2 tabular-nums">{ready ? utcOffsetLabel(reportTz) : "UTC"}</span>
      <InfoTip text="Set by your organization" iconClassName="h-4 w-4" />
    </span>
  );
}

export function GrowthHbFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-full bg-hb-bg">
      <header className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="flex flex-wrap items-center min-w-0">
          <h1 className="text-2xl font-medium leading-[1.1667]">{title}</h1>
          <ReportTimeZone />
        </div>
      </header>
      {children}
    </div>
  );
}

export function dateOnly(iso: string | null, tz: string | null): string {
  const d = parseUtc(iso);
  return d ? d.toLocaleDateString(undefined, { timeZone: tz ?? undefined }) : "—";
}

export function readTime(at: number, tz: string | null): string {
  return new Date(at).toLocaleTimeString(undefined, { timeZone: tz ?? undefined, hour: "numeric", minute: "2-digit" });
}


export function TipHead({ title, tip }: { title: string; tip: string }) {
  const cut = title.lastIndexOf(" ");
  return (
    <>
      {cut > 0 && `${title.slice(0, cut)} `}
      <span className="whitespace-nowrap">{title.slice(cut + 1)}<Tip text={tip} /></span>
    </>
  );
}

export function Tip({ text }: { text: string }) {
  return (
    <InfoTip text={text} iconClassName="h-4 w-4" className="ml-2 align-middle text-fg-dim" />
  );
}


export const TOGGLE_ACTIVE = "bg-[#2c2c2c] text-white [html[data-theme=light]_&]:bg-[#e5e5e5] [html[data-theme=light]_&]:text-fg";

export type FrameTab<T extends string> = { key: T; label: string; extra?: boolean };

export function FrameTabs<T extends string>({ tabs, value, onChange, label, idPrefix }: {
  tabs: Array<FrameTab<T>>;
  value: T;
  onChange: (key: T) => void;
  label: string;
  idPrefix: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="ml-4 flex w-fit max-w-[calc(100%-1rem)] items-center overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${t.key}`}
          aria-selected={t.key === value}
          aria-controls={`${idPrefix}-panel-${t.key}`}
          onClick={() => onChange(t.key)}
          title={t.extra ? `${EXTRA_LABEL}: ${t.label}` : undefined}
          className={cn(
            "h-9 px-3 rounded-lg text-base font-medium transition-colors whitespace-nowrap",
            "inline-flex items-center gap-1.5",
            t.key === value ? TOGGLE_ACTIVE : "text-fg hover:bg-white/5 [html[data-theme=light]_&]:hover:bg-black/5",
          )}
        >
          {t.label}
          {t.extra && <span className="hidden sm:inline-flex"><ExtraTag /></span>}
        </button>
      ))}
    </div>
  );
}


export const TH = cn(HB_TABLE.th, "text-start whitespace-normal");
export const TD = cn(HB_TABLE.td, HB_TABLE.row, "overflow-hidden text-ellipsis whitespace-nowrap");
export const STICKY_TD = "bg-hb-bg";
// Under border-collapse Chrome draws neither a sticky cell's border-l nor its box-shadow; the shadow is a transparent after: box.
export const PIN_SHADOW = "after:pointer-events-none after:absolute after:inset-0 after:content-[''] "
  + "after:shadow-[-8px_0_8px_-4px_rgba(0,0,0,.5)] [html[data-theme=light]_&]:after:shadow-[-8px_0_8px_-4px_rgba(0,0,0,.2)]";
const EDGE = cn(PIN_SHADOW, "after:border-l after:border-border "
  + "before:pointer-events-none before:absolute before:inset-y-0 before:right-full before:w-6 before:bg-linear-to-l before:to-transparent before:content-['']");
const ACTIONS_EDGE_HEAD = cn(EDGE, "before:from-panel");
const ACTIONS_EDGE = cn(EDGE, "before:from-hb-bg");
export const FIT_PAD = "px-3";
const FIT_NAME = 200;
const FIT_ACTIONS = 160;
export const OFF = "disabled:opacity-50 disabled:cursor-not-allowed";

export const LEAD = "pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg";


export function FilterSelect({ label, icon, options, value, onChange }: {
  label: string; icon: typeof GitMerge; options: string[]; value: string; onChange: (v: string) => void;
}) {
  const opts: IfOption[] = [{ value: "", label: `All ${label.toLowerCase()}s` }, ...options.map((o) => ({ value: o, label: o }))];
  return (
    <HbSelect
      size="lg"
      icon={icon}
      aria-label={label}
      placeholder={label}
      value={value || null}
      options={opts}
      onChange={onChange}
      className="mb-4 max-w-[250px]"
    />
  );
}

type MetaRow = { link_source?: string | null; tags?: string[] | null };

export function useMetaFilter() {
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  return { source, setSource, tag, setTag, keep: (l: MetaRow) => metaKeep(l, source, tag) };
}

function metaKeep(l: MetaRow, source: string, tag: string): boolean {
  return (!source || l.link_source === source) && (!tag || (l.tags ?? []).includes(tag));
}

export function CreatorFilter({
  accountId, onAccountChange,
}: { accountId: string | null; onAccountChange: (id: string) => void }) {
  const accounts = useActiveAccounts();
  const options: IfOption[] = accounts.map((a) => ({
    value: a.id,
    text: a.nickname || a.id,
    label: (
      <span className="flex min-w-0 items-center gap-2">
        <CreatorDot account={a} />
        <span className="truncate">{a.nickname || a.id}</span>
      </span>
    ),
  }));
  return (
    <HbSelect
      size="lg"
      aria-label="Creator"
      placeholder="Creator"
      value={accountId}
      options={options}
      onChange={onAccountChange}
      className="mb-4 max-w-[250px]"
    />
  );
}

function CreatorDot({ account }: { account: AccountMeta }) {
  const online = !!account.has_session && !account.session_dead_at;
  return (
    <span className="relative h-5 w-5 shrink-0">
      <span className="block h-5 w-5 overflow-hidden rounded-full">
        <AccountAvatarPicture account={account} letters={1} initialClassName="text-[10px] font-medium" />
      </span>
      {online && <span className="absolute -bottom-px -right-px h-1.5 w-1.5 rounded-full bg-ok" />}
    </span>
  );
}

export function Switch({ label, on, onChange }: { label: string; on: boolean; onChange?: (on: boolean) => void }) {
  return (
    <span className="mb-4 flex items-center gap-1.5 text-base">
      <span aria-hidden>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        disabled={!onChange}
        title={onChange ? undefined : NOT_WIRED}
        onClick={() => onChange?.(!on)}
        className={cn(
          "relative h-[22px] w-10 shrink-0 rounded-full transition-colors",
          on ? "bg-cta" : "bg-[#3a3a3a] [html[data-theme=light]_&]:bg-[#e6e6e6]",
          OFF,
        )}
      >
        <span className={cn("absolute top-[2px] h-[18px] w-[18px] rounded-full bg-white transition-[left]", on ? "left-5" : "left-[2px]")} />
      </button>
    </span>
  );
}


const DATE_PRESETS: Array<{ label: string; range: (today: string) => [string, string] }> = [
  { label: "Today", range: (t) => [t, t] },
  { label: "Yesterday", range: (t) => [addDays(t, -1), addDays(t, -1)] },
  { label: "Last 7 days", range: (t) => [addDays(t, -7), addDays(t, -1)] },
  { label: "Last 30 days", range: (t) => [addDays(t, -30), addDays(t, -1)] },
  { label: "Last 6 months", range: (t) => [monthStartBefore(t, 6), addDays(t, -1)] },
  { label: "Last 12 months", range: (t) => [monthStartBefore(t, 12), addDays(t, -1)] },
];

const DATE_FIELD = "min-w-0 flex-1 bg-transparent text-sm outline-none";

function DateCreated({ from, to, onRange, tz }: {
  from: string; to: string; onRange: (from: string, to: string) => void; tz: string | null;
}) {
  const today = () => dayKey(new Date(), tz);
  const preset = DATE_PRESETS.find((p) => {
    const [f, t] = p.range(today());
    return f === from && t === to;
  })?.label ?? "";
  function pickPreset(label: string) {
    const p = DATE_PRESETS.find((x) => x.label === label);
    if (p) onRange(...p.range(today()));
  }
  return (
    <div
      role="group"
      aria-label="Date created"
      className={cn(HbFilterLg, "mb-4 flex w-[424px] max-w-full items-center gap-2")}
    >
      <Calendar size={20} aria-hidden className="shrink-0 text-fg" />
      <span className="text-fg whitespace-nowrap">Date created</span>
      <IfDateInput
        type="date"
        aria-label="Start date"
        value={from}
        max={to || undefined}
        onChange={(e) => onRange(e.target.value, to)}
        bare
        className={cn(DATE_FIELD, from ? "text-fg" : "text-[#a6a6a6]")}
      />
      <span className="text-fg-dim" aria-hidden>→</span>
      <IfDateInput
        type="date"
        aria-label="End date"
        value={to}
        min={from || undefined}
        onChange={(e) => onRange(from, e.target.value)}
        bare
        className={cn(DATE_FIELD, to ? "text-fg" : "text-[#a6a6a6]")}
      />
      <span className="relative inline-flex shrink-0 items-center">
        <select
          aria-label="Date created presets"
          value={preset}
          onChange={(e) => pickPreset(e.target.value)}
          className="h-7 w-5 cursor-pointer appearance-none bg-transparent text-transparent outline-none supports-[appearance:base-select]:[appearance:base-select] [&::picker-icon]:hidden [&>option]:text-fg"
        >
          <option value="" disabled>Presets</option>
          {DATE_PRESETS.map((p) => <option key={p.label} value={p.label}>{p.label}</option>)}
        </select>
        <ChevronDown size={16} aria-hidden className="pointer-events-none absolute right-0.5 text-[#a6a6a6]" />
      </span>
      {(from || to) && (
        <button type="button" aria-label="Clear date created" onClick={() => onRange("", "")} className="shrink-0 text-fg-dim hover:text-fg">
          <X size={14} aria-hidden />
        </button>
      )}
    </div>
  );
}


export function AttributionTip() {
  return (
    <div className="mb-4 flex min-h-10 items-center gap-2 rounded-lg border border-white/[.09] bg-panel px-3 py-2 text-sm text-fg [html[data-theme=light]_&]:border-black/[.09]">
      <MessageSquareWarning size={16} aria-hidden className="shrink-0 fill-fg text-panel" />
      <span>
        <span>Each fan&apos;s spending is always attributed to the last free trial link, tracking link or promotion campaign that has been clicked by the fan.</span>
        <button type="button" disabled title={NOT_WIRED} className={cn("ml-2 text-sm text-cta", OFF)}>
          Learn more
        </button>
      </span>
    </div>
  );
}

export function useSessionGone(accountId: string | null): boolean {
  const a = useActiveAccounts().find((x) => x.id === accountId);
  return !!a && (!a.has_session || !!a.session_dead_at);
}

export function Reconnect() {
  return (
    <EmptyState
      kind="creator"
      text="Creator's OnlyFans account is disconnected from Infloww"
      action={<Link href="/creators" className="text-sm text-cta hover:opacity-90">Relink OnlyFans account</Link>}
    />
  );
}

export function Unreachable({ className, text = "OnlyFans not reachable — showing nothing." }: {
  className?: string; text?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2 text-sm text-warn", className)}>
      {text}
      <ExtraTag />
    </div>
  );
}


const PAGE_SIZES = [10, 20, 50] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 50;

export function Pager({ total, page, size, onPage, onSize }: {
  total: number; page: number; size: PageSize; onPage: (p: number) => void; onSize: (s: PageSize) => void;
}) {
  return (
    <HbPager total={total} noun="records" page={page} size={size} sizes={[...PAGE_SIZES]}
      onPage={onPage} onSize={(s) => onSize(s as PageSize)} />
  );
}


export function downloadCsv(name: string, lines: string[][], tz: string | null) {
  saveCsv(`${name}-${dayKey(new Date(), tz)}.csv`, lines);
}


export const ACT = cn(HB_TABLE.iconButton, "w-auto min-w-7 px-[9px] text-sm", OFF);

export type RowMenuAction = {
  label: string;
  extra?: boolean;
  confirmTitle: string;
  confirmBody: ReactNode;
  failText: string;
  run?: () => Promise<unknown>;
};

export function RowActions({ name, onDetails, detailsOpen, onEdit, action }: {
  name: string;
  onDetails?: () => void;
  detailsOpen?: boolean;
  onEdit?: () => void;
  action: RowMenuAction;
}) {
  return (
    <div className="inline-flex items-center gap-2">
      <button type="button" disabled={!onDetails} onClick={onDetails} className={ACT}>{detailsOpen ? "Hide" : "Details"}</button>
      <button type="button" disabled={!onEdit} onClick={onEdit} aria-label={`Edit ${name}`} className={ACT}>
        <Pencil size={14} aria-hidden />
      </button>
      <RowMenu name={name} action={action} />
    </div>
  );
}

export function RowMenu({ name, action }: { name: string; action: RowMenuAction }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      <Menu align="right" position="fixed" panelClassName="w-48" itemClassName="flex items-center gap-2"
        trigger={(p) => (
          <button type="button" aria-label={`More actions for ${name}`} {...p} className={ACT}>
            <EllipsisVertical size={14} aria-hidden />
          </button>
        )}
        items={[{
          key: action.label,
          label: <>{action.label}{action.extra && <ExtraTag />}</>,
          disabled: !action.run,
          title: action.extra ? EXTRA_LABEL : undefined,
          onClick: () => setConfirming(true),
        }]} />
      {confirming && action.run && (
        <ConfirmModal
          title={action.confirmTitle}
          confirmLabel={action.label}
          failText={action.failText}
          onConfirm={action.run}
          onClose={() => setConfirming(false)}
        >
          {action.confirmBody}
        </ConfirmModal>
      )}
    </>
  );
}

function ConfirmModal({ title, confirmLabel, failText, onConfirm, onClose, children }: {
  title: string;
  confirmLabel: string;
  failText: string;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
  children: ReactNode;
}) {
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function ok() {
    setErr(null);
    setPending(true);
    try {
      await onConfirm();
      onClose();
    } catch {
      setErr(failText);
      setPending(false);
    }
  }

  return (
    <HbModal
      title={title}
      width={600}
      onClose={onClose}
      className="whitespace-normal"
      footer={(
        <>
          <HbButton variant="secondary" onClick={onClose}>Cancel</HbButton>
          <HbButton className="bg-err text-white" onClick={() => void ok()} disabled={pending}>{confirmLabel}</HbButton>
        </>
      )}
    >
      <p>{children}</p>
      {err && <div className="mt-4 text-err text-xs">{err}</div>}
    </HbModal>
  );
}


export type FrameCol<T> = {
  title: string;
  width: number;
  tip?: string;
  cell: (row: T) => ReactNode;
  hint?: (row: T) => string | undefined;
};

type FrameRow = MetaRow & { name: string; created_at: string | null };

export function useFrameFilters<X extends object>(extra: X) {
  const { reportTz } = useReportTz();
  const f = usePagedFilters<FrameFields & X>({
    search: "", source: "", tag: "", from: "", to: "", pageSize: DEFAULT_PAGE_SIZE, ...extra,
  });
  const needle = f.search.trim().toLowerCase();
  return {
    ...f,
    reportTz,
    keep: (l: FrameRow) => {
      if (!metaKeep(l, f.source, f.tag)) return false;
      if (f.from || f.to) {
        const day = createdDay(l, reportTz);
        if (!day || (f.from && day < f.from) || (f.to && day > f.to)) return false;
      }
      return !needle || l.name.toLowerCase().includes(needle);
    },
  };
}
type FrameFields = { search: string; source: string; tag: string; from: string; to: string; pageSize: PageSize };
const NO_FRAME_FILTERS = { source: "", tag: "", from: "", to: "" };
const FOLDED = ["source", "tag", ["from", "to"]] as const;
export type FrameFilters = ReturnType<typeof useFrameFilters>;

export default function LinksListFrame<T>({
  variant, accountId, onAccountChange, filters, sources, tags, switches, onCreate, onExport, exportTitle,
  update, notice, loading, columns, rows, rowKey, rowName, nameCell, actions, expanded, selection, phoneMetrics = [],
}: {
  variant: LinksVariant;
  accountId: string | null;
  onAccountChange: (id: string) => void;
  filters: FrameFilters;
  sources: string[];
  tags: string[];
  switches: ReactNode;
  onCreate: () => void;
  onExport: () => void;
  exportTitle: string;
  update: ReactNode;
  notice?: ReactNode;
  loading: boolean;
  columns: Array<FrameCol<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  rowName: (row: T) => string;
  nameCell: (row: T) => ReactNode;
  actions: (row: T) => ReactNode;
  expanded?: (row: T) => ReactNode;
  phoneMetrics?: string[];
  selection?: {
    selected: string[];
    onChange: (keys: string[]) => void;
    canSelect: (row: T) => boolean;
    onBatchEdit: () => void;
  };
}) {
  const text = VARIANT_TEXT[variant];
  const sessionGone = useSessionGone(accountId);
  const exportAllowed = useActionAllowed("export");
  const f = filters;
  const pages = Math.max(1, Math.ceil(rows.length / f.pageSize));
  const current = Math.min(f.page, pages);
  const shown = rows.slice((current - 1) * f.pageSize, current * f.pageSize);
  const span = columns.length + 3;
  const sel = selection;
  const pageKeys = sel ? shown.filter(sel.canSelect).map(rowKey) : [];
  const pagePicked = pageKeys.length > 0 && pageKeys.every((k) => sel!.selected.includes(k));
  const pickPage = (on: boolean) => sel?.onChange(on
    ? [...new Set([...sel.selected, ...pageKeys])] : sel.selected.filter((k) => !pageKeys.includes(k)));
  const pick = (k: string, on: boolean) => sel?.onChange(on ? [...sel.selected, k] : sel.selected.filter((x) => x !== k));
  const phone = useMediaQuery(PHONE);
  const rowBox = (r: T) => (sel && sel.canSelect(r) ? (
    <input type="checkbox" aria-label={`Select ${rowName(r)}`} checked={sel.selected.includes(rowKey(r))}
      onChange={(e) => pick(rowKey(r), e.target.checked)} />
  ) : (
    <input type="checkbox" disabled title={sel ? "Not on OnlyFans" : NOT_WIRED} aria-label={`Select ${rowName(r)}`} />
  ));

  return (
    <div>
      <div className="px-4 pt-4">
        <AttributionTip />

        <div className="flex flex-wrap items-center gap-x-4">
          <CreatorFilter accountId={accountId} onAccountChange={onAccountChange} />
          <span className="relative mb-4 inline-flex w-[280px] max-w-full">
            <Search size={20} aria-hidden className={LEAD} />
            <input
              className={cn(HbFilterLg, "w-full pl-10")}
              aria-label={text.search}
              placeholder={text.search}
              maxLength={100}
              value={f.search}
              onChange={(e) => f.set({ search: e.target.value })}
            />
          </span>
          <IfFilterFold active={countActiveFilters(f, NO_FRAME_FILTERS, FOLDED)} className="mb-4 h-9">
            <FilterSelect label="Source" icon={GitMerge} options={sources} value={f.source} onChange={(source) => f.set({ source })} />
            <FilterSelect label="Tag" icon={Tag} options={tags} value={f.tag} onChange={(tag) => f.set({ tag })} />
            <DateCreated from={f.from} to={f.to} onRange={(from, to) => f.set({ from, to })} tz={f.reportTz} />
            {switches}
          </IfFilterFold>
          <div className="mb-4 ml-auto flex flex-wrap items-center gap-4">
            <HbButton size="lg" icon={Plus} onClick={onCreate} disabled={!accountId}>
              {text.create}
            </HbButton>
            {exportAllowed && (
              <HbButton variant="secondary" size="lg" icon={Upload} disabled={rows.length === 0} title={exportTitle} onClick={onExport}>
                Export
              </HbButton>
            )}
            {sel && (
              <HbButton variant="secondary" size="lg" icon={Pencil} disabled={sel.selected.length === 0}
                title="Set Source, Promo cost or Tag on the picked links" onClick={sel.onBatchEdit}>
                Batch edit{sel.selected.length > 0 && ` (${sel.selected.length})`}
              </HbButton>
            )}
          </div>
        </div>
      </div>

      <div className="px-4 mb-4 space-y-2">
        {update != null && (
          <div className="flex items-center justify-between gap-4">
            {update}
          </div>
        )}
        {notice}

        {phone ? (
          <PhoneCards
            rows={shown} loading={loading} sessionGone={sessionGone} rowKey={rowKey} nameCell={nameCell} actions={actions}
            expanded={expanded} rowBox={rowBox}
            metrics={phoneMetrics.map((t) => columns.find((c) => c.title === t)).filter((c): c is FrameCol<T> => !!c).slice(0, 3)}
          />
        ) : (
        <div className="overflow-x-auto">
          <table aria-label="Links list" className={cn(HB_TABLE.table, "min-w-[1000px] table-fixed")}>
            <thead>
              <tr>
                <th className={cn(TH, "w-12 md:sticky left-0")}>
                  {sel ? (
                    <input type="checkbox" aria-label="Select all" checked={pagePicked} disabled={pageKeys.length === 0}
                      onChange={(e) => pickPage(e.target.checked)} />
                  ) : <input type="checkbox" disabled title={NOT_WIRED} aria-label="Select all" />}
                </th>
                <th className={cn(TH, "md:sticky left-12")} style={{ width: FIT_NAME }}>{text.name}</th>
                {columns.map((c) => (
                  <th key={c.title} className={cn(TH, FIT_PAD)} style={{ width: c.width }}>
                    {c.tip ? <TipHead title={c.title} tip={c.tip} /> : c.title}
                  </th>
                ))}
                <th className={cn(TH, ACTIONS_EDGE_HEAD, "md:sticky right-0 px-2")} style={{ width: FIT_ACTIONS }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <SkeletonRows cols={span} rows={5} cellClassName={TD} />
              ) : sessionGone && shown.length === 0 ? (
                <tr><td colSpan={span} className="py-16"><Reconnect /></td></tr>
              ) : shown.length === 0 ? (
                <tr><td colSpan={span} className="h-[250px]"><EmptyState kind="search" text="No data" /></td></tr>
              ) : shown.map((r) => (
                <FrameRows key={rowKey(r)} span={span} more={expanded?.(r)}>
                  <td className={cn(TD, STICKY_TD, "md:sticky left-0 overflow-visible")}>{rowBox(r)}</td>
                  <td className={cn(TD, STICKY_TD, "md:sticky left-12")}>{nameCell(r)}</td>
                  {columns.map((c) => (
                    <td key={c.title} className={cn(TD, FIT_PAD, "tabular-nums")} title={c.hint?.(r)} data-metric={c.title}>
                      {c.cell(r)}
                    </td>
                  ))}
                  <td className={cn(TD, STICKY_TD, ACTIONS_EDGE, "md:sticky right-0 overflow-visible px-2")}>
                    {actions(r)}
                  </td>
                </FrameRows>
              ))}
            </tbody>
          </table>
        </div>
        )}
        {shown.length > 0 && (
          <Pager page={current} total={rows.length} size={f.pageSize} onPage={f.setPage} onSize={(pageSize) => f.set({ pageSize })} />
        )}
      </div>
    </div>
  );
}

const PHONE = "(max-width: 767px)";

function PhoneCards<T>({ rows, loading, sessionGone, rowKey, nameCell, actions, expanded, rowBox, metrics }: {
  rows: T[];
  loading: boolean;
  sessionGone: boolean;
  rowKey: (row: T) => string;
  nameCell: (row: T) => ReactNode;
  actions: (row: T) => ReactNode;
  expanded?: (row: T) => ReactNode;
  rowBox: (row: T) => ReactNode;
  metrics: Array<FrameCol<T>>;
}) {
  if (loading) {
    return <div className="space-y-2" data-loading>{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-lg" />)}</div>;
  }
  if (rows.length === 0) {
    return <div className="py-12">{sessionGone ? <Reconnect /> : <EmptyState kind="search" text="No data" />}</div>;
  }
  return (
    <ul aria-label="Links list" className="space-y-2">
      {rows.map((r) => {
        const more = expanded?.(r);
        return (
          <li key={rowKey(r)} className="flex flex-col gap-3 rounded-lg bg-panel p-3">
            <div className="flex items-start gap-3">
              <span className="pt-0.5">{rowBox(r)}</span>
              <div className="min-w-0 flex-1">{nameCell(r)}</div>
            </div>
            {metrics.length > 0 && (
              <dl className="grid grid-cols-3 gap-2">
                {metrics.map((c) => (
                  <div key={c.title} className="min-w-0">
                    <dt className="truncate text-xs text-fg-dim">{c.title}</dt>
                    <dd className="truncate text-sm tabular-nums text-fg" title={c.hint?.(r)} data-metric={c.title}>{c.cell(r)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <div className="flex justify-end">{actions(r)}</div>
            {more != null && more !== false && <div className="whitespace-normal">{more}</div>}
          </li>
        );
      })}
    </ul>
  );
}

function FrameRows({ span, more, children }: { span: number; more: ReactNode; children: ReactNode }) {
  return (
    <>
      <tr>{children}</tr>
      {more != null && more !== false && (
        <tr><td colSpan={span} className={cn(HB_TABLE.row, "px-4 py-3 whitespace-normal")}>{more}</td></tr>
      )}
    </>
  );
}
