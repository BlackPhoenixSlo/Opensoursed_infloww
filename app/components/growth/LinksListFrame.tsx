"use client";

/**
 * LinksListFrame — the HB frame Infloww draws for both its link lists (bundle index.9f50f370.js: one component with
 * `LINK_LIST_VIEW_TYPE.TRACKING` and `.FREETRIAL`, `LINK_LIST_CREATE_TEXT` @14052200): the attribution tip, the
 * filter bar (Creator, the name search, Source, Tag, Date created, the switches, Create and Export), the update row,
 * the HB table with its fixed name and Actions columns, and `HbPager`. Tracking links (`TrackingLinksTab`) and Free
 * trial links (`TrialLinksTab`) render through it; each passes its own rows, columns, switches and row actions.
 *
 * The pieces both pages share (the page frame `GrowthHbFrame` with its title and report time zone, the tabs' toggle
 * look, the creator and Source / Tag filters, HB's switch, the reconnect state, the row actions and their confirm) are
 * exported from here too.
 */

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Calendar, ChevronDown, EllipsisVertical, GitMerge, Info, MessageSquareWarning, Pencil, Plus, Search, Tag, Upload, X,
} from "lucide-react";

import { ExtraTag } from "@/components/ui/primitives";
import {
  EmptyState, HB_TABLE, HbButton, HbFilterLg, HbModal, HbPager, HbSelect, type IfOption,
} from "@/components/ui/infloww";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { MENU_ITEM, MENU_PANEL, useOutsideClose } from "@/components/ui/Menu";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useActiveAccounts } from "@/hooks/useAccounts";
import type { AccountMeta } from "@/lib/relay";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { downloadCsv as saveCsv } from "@/lib/csv";
import { parseUtc } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";
import { SkeletonRows } from "@/components/ui/Skeleton";

export const NOT_WIRED = "not wired";

/** The bundle's two list variants and the words that differ between them. */
export type LinksVariant = "TRACKING" | "FREETRIAL";
const VARIANT_TEXT: Record<LinksVariant, { create: string; search: string; name: string }> = {
  TRACKING: { create: "Create tracking link", search: "Search tracking link name", name: "Tracking link" },
  FREETRIAL: { create: "Create free trial link", search: "Search free trial link name", name: "Free trial links" },
};

// ── Time zone and dates ──

/** The Agency's report time zone from the Applied settings (`null`: the browser's), as the Dashboard reads it. */
export function useReportTz(): { reportTz: string | null; ready: boolean } {
  const applied = useAppliedSettings();
  return { reportTz: applied.data?.preferences?.report_tz ?? null, ready: !applied.isPending };
}

/** #6 to #9: the report time zone after the title, 8px either side, 14px/1.5, then a 16px info icon whose tooltip
 *  is "Set by your organization". The page header (`GrowthHbFrame`) renders it. */
function ReportTimeZone() {
  const { reportTz, ready } = useReportTz();
  return (
    <span className="mx-2 flex items-center text-sm leading-normal text-fg-dim">
      <span className="mr-2 tabular-nums">{ready ? utcOffsetLabel(reportTz) : "UTC"}</span>
      <span title="Set by your organization" className="inline-flex">
        <Info size={16} aria-hidden />
      </span>
    </span>
  );
}

/** Tracking links and Free trial links are one HB frame (its Layout capture, #4 to #9): the HB body, a 16px-padded
 *  header with a 24px weight-500 title and the report time zone; its own panels carry the 16px sides. With no
 *  Creator it still draws the whole frame (the Creator filter empty, Create disabled, the table's "No data"). The
 *  page (TrackingLinksPage, TrialLinksPage) draws it around its tab; the list below is `LinksListFrame`. */
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

/** #38: date only, in the report time zone the title names (#6). */
export function dateOnly(iso: string | null, tz: string | null): string {
  const d = parseUtc(iso);
  return d ? d.toLocaleDateString(undefined, { timeZone: tz ?? undefined }) : "—";
}

/** `at` as YYYY-MM-DD in the report time zone (`en-CA` prints the ISO order). */
export function dayKey(at: Date, tz: string | null): string {
  return at.toLocaleDateString("en-CA", { timeZone: tz ?? undefined, year: "numeric", month: "2-digit", day: "2-digit" });
}

/** The day a link was created, in the report time zone; null with no (or a bad) date. Our links' stamps come
 *  zone-less (naive UTC), so they are read as UTC. */
export function createdDay(l: { created_at: string | null }, tz: string | null): string | null {
  const d = parseUtc(l.created_at);
  return d ? dayKey(d, tz) : null;
}

/** The time the relay's read landed, in the report time zone the title names. */
export function readTime(at: number, tz: string | null): string {
  return new Date(at).toLocaleTimeString(undefined, { timeZone: tz ?? undefined, hour: "numeric", minute: "2-digit" });
}

// ── Heads and tips ──

/** A head with a tip: the words wrap, the 16px info icon (the bundle's `tips` text) stays on the last word's line. */
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
    <span title={text} className="ml-2 inline-flex align-middle text-fg-dim cursor-help">
      <Info size={16} aria-hidden />
    </span>
  );
}

// ── Tabs ──

/** HB's `hb-button--color-toggle-active`: #2c2c2c with white text (light #e5e5e5 with T1). */
export const TOGGLE_ACTIVE = "bg-[#2c2c2c] text-white [html[data-theme=light]_&]:bg-[#e5e5e5] [html[data-theme=light]_&]:text-fg";

/** #10, #12: 16px from the edge, 16px weight 500. The bundle's `HBTab` draws each tab as a 36px toggle button, 12px
 *  padding, 8px radius, the selected one filled. The panel is the caller's, `${idPrefix}-panel-${key}`. */
export function FrameTabs<T extends string>({ tabs, value, onChange, label, idPrefix }: {
  tabs: Array<{ key: T; label: string }>;
  value: T;
  onChange: (key: T) => void;
  label: string;
  idPrefix: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="ml-4 flex w-fit max-w-full items-center overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${t.key}`}
          aria-selected={t.key === value}
          aria-controls={`${idPrefix}-panel-${t.key}`}
          onClick={() => onChange(t.key)}
          className={cn(
            "h-9 px-3 rounded-lg text-base font-medium transition-colors whitespace-nowrap",
            t.key === value ? TOGGLE_ACTIVE : "text-fg hover:bg-white/5 [html[data-theme=light]_&]:hover:bg-black/5",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── Table classes ──

/** #35, #91, #93, #96: the HB table (`HB_TABLE`): a 48px head on #171717 with white 14px/500 text, 48px cells
 *  padded 0 18px over a 1px #2c2c2c rule. */
export const TH = cn(HB_TABLE.th, "text-start");
export const TD = cn(HB_TABLE.td, HB_TABLE.row, "overflow-hidden text-ellipsis whitespace-nowrap");
/** The fixed cells: the head's on the panel colour, the body's on the page colour they sit over. */
export const STICKY_TD = "bg-hb-bg";
/** The fixed Actions column's 1px divider at its left. */
export const ACTIONS_RULE = "border-l border-[#2c2c2c] [html[data-theme=light]_&]:border-black/[.09]";
/** The list's fit: 12px sides on the metric cells, a 200px name, a 160px Actions. */
export const FIT_PAD = "px-3";
const FIT_NAME = 200;
const FIT_ACTIONS = 160;
export const OFF = "disabled:opacity-50 disabled:cursor-not-allowed";

/** A 16px icon led into a 36px control, 12px from its left edge, as the bundle's Search, Source, Tag and Date created
 *  fields draw it (`SearchMdLine` @14060359, `GitMergeLine` @14062703, `Tag01Line` @14064090; the range picker's
 *  own calendar). */
export const LEAD = "pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg";

// ── Filters ──

/** #19, #20, #80: the Source or Tag filter, HB filled and led by its icon, over the values the Edit dialog set on the
 *  account's links ("" is every link, and shows the label as the placeholder). */
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

/** The Source and Tag filters' state and test. */
export function useMetaFilter() {
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  const keep = (l: MetaRow) => (!source || l.link_source === source) && (!tag || (l.tags ?? []).includes(tag));
  return { source, setSource, tag, setTag, keep };
}

/** The creator filter (#17, #80): it picks the Creator every read and write on the page is for. */
export function CreatorFilter({
  accountId, onAccountChange,
}: { accountId: string | null; onAccountChange: (id: string) => void }) {
  const accounts = useActiveAccounts();
  // The chip: the creator's avatar with its online dot, the name, the chevron; at most 250px.
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

/** A 20px avatar with the online dot at its foot (the Creator chip, #17). */
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

/** #24 to #26, #80: a 16px label 6px before HB's 40x22 switch, an 18px white knob; on the CTA orange, off #3a3a3a.
 *  Without `onChange` it is disabled and Not wired. */
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

// ── Date created (#21, #22) ──

/** A YYYY-MM-DD day moved by `n` days. */
function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The first of the month `m` months before a YYYY-MM-DD day (dayjs `subtract(m,"month").startOf("month")`). */
function monthStartBefore(day: string, m: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - m);
  return d.toISOString().slice(0, 10);
}

/** The bundle's `datePresets` (`getDatePresetValue`): from and to, inclusive, around today in the report time zone. */
const DATE_PRESETS: Array<{ label: string; range: (today: string) => [string, string] }> = [
  { label: "Today", range: (t) => [t, t] },
  { label: "Yesterday", range: (t) => [addDays(t, -1), addDays(t, -1)] },
  { label: "Last 7 days", range: (t) => [addDays(t, -7), addDays(t, -1)] },
  { label: "Last 30 days", range: (t) => [addDays(t, -30), addDays(t, -1)] },
  { label: "Last 6 months", range: (t) => [monthStartBefore(t, 6), addDays(t, -1)] },
  { label: "Last 12 months", range: (t) => [monthStartBefore(t, 12), addDays(t, -1)] },
];

/** A bare date input inside the Date created box: no picker glyph (the box leads with its own calendar); a click
 *  opens the browser's picker. */
const DATE_FIELD = "min-w-0 flex-1 bg-transparent text-sm outline-none [&::-webkit-calendar-picker-indicator]:hidden";
function openPicker(e: React.MouseEvent<HTMLInputElement>) {
  try { e.currentTarget.showPicker?.(); } catch { /* not allowed (jsdom, a cross-origin frame) */ }
}

/** #21 to #23: a calendar, then "Date created" as a text prefix, the range, then the bundle's presets (its picker's
 *  side panel) as a borderless chevron menu. An inclusive YYYY-MM-DD range in the report time zone; "" is open. */
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
      <input
        type="date"
        aria-label="Start date"
        value={from}
        max={to || undefined}
        onChange={(e) => onRange(e.target.value, to)}
        onClick={openPicker}
        className={cn(DATE_FIELD, from ? "text-fg" : "text-[#a6a6a6]")}
      />
      <span className="text-fg-dim" aria-hidden>→</span>
      <input
        type="date"
        aria-label="End date"
        value={to}
        min={from || undefined}
        onChange={(e) => onRange(from, e.target.value)}
        onClick={openPicker}
        className={cn(DATE_FIELD, to ? "text-fg" : "text-[#a6a6a6]")}
      />
      <span className="relative inline-flex shrink-0 items-center">
        <select
          aria-label="Date created presets"
          value={preset}
          onChange={(e) => pickPreset(e.target.value)}
          className="h-7 w-5 cursor-pointer appearance-none bg-transparent text-transparent outline-none [&>option]:bg-panel [&>option]:text-fg"
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

// ── Tip, reconnect, unreachable ──

/** #14 to #16: the attribution tip: a 40px box on the panel colour with a 1px hairline, a 16px filled "!" badge, the
 *  14px sentence, then "Learn more" 8px after it in the CTA orange (Infloww's own article, off-host: Not wired). */
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

/** Whether the picked creator's OnlyFans session is dead or missing. */
export function useSessionGone(accountId: string | null): boolean {
  const a = useActiveAccounts().find((x) => x.id === accountId);
  return !!a && (!a.has_session || !!a.session_dead_at);
}

/** #68: the bundle's reconnect state for a creator whose OnlyFans session is gone (ticket 04's dead-session art). */
export function Reconnect() {
  return (
    <EmptyState
      kind="creator"
      text="Creator's OnlyFans account is disconnected from Infloww"
      action={<Link href="/creators" className="text-sm text-cta hover:opacity-90">Relink OnlyFans account</Link>}
    />
  );
}

/** Ours in place of the bundle's reconnect state when the read fails on a live session, labelled as ours. */
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

// ── Pager (#66) ──

/** `PAGE_SIZE_OPTIONS=["10","20","50"];const DEFAULT_PAGE_SIZE=50`. */
const PAGE_SIZES = [10, 20, 50] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 50;

/** The bundle's `HBPagination` (`HbPager`): "Total: N records", the pages, then "Per page" and 10 / 20 / 50, over a
 *  1px top rule. It shows only when there are rows. */
export function Pager({ total, page, size, onPage, onSize }: {
  total: number; page: number; size: PageSize; onPage: (p: number) => void; onSize: (s: PageSize) => void;
}) {
  return (
    <HbPager total={total} noun="records" page={page} size={size} sizes={[...PAGE_SIZES]}
      onPage={onPage} onSize={(s) => onSize(s as PageSize)} />
  );
}

// ── Export (#28) ──

/** The bundle emails its export (#81); ours downloads `lines` (the head first) as `<name>-<day>.csv`. */
export function downloadCsv(name: string, lines: string[][], tz: string | null) {
  saveCsv(`${name}-${dayKey(new Date(), tz)}.csv`, lines);
}

// ── Row actions (#62 to #64, #94, #95) ──

/** #95: HB's 28px ghost buttons (#2c2c2c), 9px side padding; an icon-only one is 28px square. */
export const ACT = cn(HB_TABLE.iconButton, "w-auto min-w-7 px-[9px] text-sm", OFF);

/** The dots menu's one action and its confirm: the bundle's Deactivate, or ours (`extra`, labelled). Without `run`
 *  the item is disabled. */
export type RowMenuAction = {
  label: string;
  extra?: boolean;
  confirmTitle: string;
  confirmBody: ReactNode;
  failText: string;
  run?: () => Promise<unknown>;
};

/** Details, Edit (an icon, as the bundle draws it), then the dots menu, 8px apart (#63). */
export function RowActions({ name, onDetails, detailsOpen, onEdit, action }: {
  name: string;
  onDetails?: () => void;
  /** Details opens in place; while it is open the button says "Hide". */
  detailsOpen?: boolean;
  onEdit?: () => void;
  action: RowMenuAction;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const [confirming, setConfirming] = useState(false);

  function toggle(e: React.MouseEvent<HTMLButtonElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    setPos({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
    setOpen((o) => !o);
  }

  return (
    <div ref={ref} className="inline-flex items-center gap-2">
      <button type="button" disabled={!onDetails} onClick={onDetails} className={ACT}>{detailsOpen ? "Hide" : "Details"}</button>
      <button type="button" disabled={!onEdit} onClick={onEdit} aria-label={`Edit ${name}`} className={ACT}>
        <Pencil size={14} aria-hidden />
      </button>
      <button
        type="button"
        aria-label={`More actions for ${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
        className={ACT}
      >
        <EllipsisVertical size={14} aria-hidden />
      </button>
      {/* #94: an overlay under the dots, right-aligned to them, above the table's sticky cells. */}
      {open && pos && (
        <div role="menu" className={cn(MENU_PANEL, "fixed z-50 mt-0 w-48")} style={{ top: pos.top, right: pos.right }}>
          <button
            type="button"
            role="menuitem"
            disabled={!action.run}
            title={action.extra ? EXTRA_LABEL : undefined}
            onClick={() => { setOpen(false); setConfirming(true); }}
            className={cn(MENU_ITEM, "flex items-center gap-2 hover:bg-bg-elev-1 disabled:text-fg-dim disabled:cursor-not-allowed disabled:hover:bg-transparent")}
          >
            {action.label}
            {action.extra && <ExtraTag />}
          </button>
        </div>
      )}
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
    </div>
  );
}

/** The bundle's Deactivate confirm (`HBModal.confirm`, index.9f50f370.js @14028314): 600px, centred, Cancel then a
 *  red action; a failure keeps it open with the bundle's toast words. */
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

// ── The frame ──

/** A column after the name (#38 to #55): its head (with the bundle's tip, when it has one) and its cell; `hint` is a
 *  tooltip on the cell when it needs a caveat. The cell carries `data-metric` = the title. */
export type FrameCol<T> = {
  title: string;
  width: number;
  tip?: string;
  cell: (row: T) => ReactNode;
  hint?: (row: T) => string | undefined;
};

/** The rows a frame filters: the name search, Source, Tag and the day created. */
type FrameRow = MetaRow & { name: string; created_at: string | null };

/** The frame's filter and page state: the name search, Source and Tag, Date created, the page and its size. Every
 *  filter change goes back to page 1; `keep` tests a row against all of them in the report time zone. */
export function useFrameFilters() {
  const { reportTz } = useReportTz();
  const mf = useMetaFilter();
  const [search, setSearchRaw] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
  const needle = search.trim().toLowerCase();
  return {
    reportTz,
    search, setSearch: (v: string) => { setSearchRaw(v); setPage(1); },
    source: mf.source, setSource: (v: string) => { mf.setSource(v); setPage(1); },
    tag: mf.tag, setTag: (v: string) => { mf.setTag(v); setPage(1); },
    from, to, setRange: (f: string, t: string) => { setFrom(f); setTo(t); setPage(1); },
    page, setPage,
    pageSize, setPageSize: (s: PageSize) => { setPageSize(s); setPage(1); },
    keep: (l: FrameRow) => {
      if (!mf.keep(l)) return false;
      if (from || to) {
        const day = createdDay(l, reportTz);
        if (!day || (from && day < from) || (to && day > to)) return false;
      }
      return !needle || l.name.toLowerCase().includes(needle);
    },
  };
}
export type FrameFilters = ReturnType<typeof useFrameFilters>;

/**
 * The Links list: #13 the search panel (the tip, then #17 to #29 the filter bar), #30 to #33 the update row and the
 * table panel, #34 to #66 the table and the pager. `rows` are the rows left after the caller's own filters and
 * `filters.keep`; the frame cuts the pages. `expanded` draws a full-width row under a row (Free trial links'
 * Details, in place). `selection` wires #36's checkboxes and "Batch edit" (the head's box picks the page's rows).
 */
export default function LinksListFrame<T>({
  variant, accountId, onAccountChange, filters, sources, tags, switches, onCreate, onExport, exportTitle,
  update, notice, loading, columns, rows, rowKey, rowName, nameCell, actions, expanded, selection,
}: {
  variant: LinksVariant;
  accountId: string | null;
  onAccountChange: (id: string) => void;
  filters: FrameFilters;
  sources: string[];
  tags: string[];
  /** #24 to #26: the switches after Date created. */
  switches: ReactNode;
  onCreate: () => void;
  onExport: () => void;
  exportTitle: string;
  /** #30 to #32: the update row; `null` hides it. */
  update: ReactNode;
  /** Ours, above the table: the "OnlyFans not reachable" line. */
  notice?: ReactNode;
  loading: boolean;
  columns: Array<FrameCol<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  rowName: (row: T) => string;
  nameCell: (row: T) => ReactNode;
  actions: (row: T) => ReactNode;
  expanded?: (row: T) => ReactNode;
  /** The picked rows' keys, and Batch edit on them; `canSelect` false leaves a row's box off (no OnlyFans id). */
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
  // #66: the reads return every link at once, so the pages are cut here.
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

  return (
    <div>
      {/* #13: the search panel, 16px padding but none at the bottom. */}
      <div className="px-4 pt-4">
        <AttributionTip />

        {/* #17 to #29: the filter bar, items 16px apart and 16px below. */}
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
              onChange={(e) => f.setSearch(e.target.value)}
            />
          </span>
          {/* #19, #20: the Edit dialog's Source and Tag. */}
          <FilterSelect label="Source" icon={GitMerge} options={sources} value={f.source} onChange={f.setSource} />
          <FilterSelect label="Tag" icon={Tag} options={tags} value={f.tag} onChange={f.setTag} />
          <DateCreated from={f.from} to={f.to} onRange={f.setRange} tz={f.reportTz} />
          {switches}
          {/* #27 to #29: right-aligned, 16px apart, 36px tall. Create opens the editor pop-up (#69). */}
          <div className="mb-4 ml-auto flex flex-wrap items-center gap-4">
            <HbButton size="lg" icon={Plus} onClick={onCreate} disabled={!accountId}>
              {text.create}
            </HbButton>
            {/* #28: the bundle emails an export (#81); ours downloads a CSV of the filtered rows. Hidden where the
                role denies Export CSV. */}
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

      {/* #33: the table panel, 16px at the sides and below. */}
      <div className="px-4 mb-4 space-y-2">
        {update != null && (
          <div className="flex items-center justify-between gap-4">
            {update}
          </div>
        )}
        {notice}

        {/* #34: it scrolls sideways past 1000px. */}
        <div className="overflow-x-auto">
          <table aria-label="Links list" className={cn(HB_TABLE.table, "min-w-[1000px] table-fixed")}>
            <thead>
              <tr>
                {/* #36: the picks Batch edit works on. */}
                <th className={cn(TH, "w-12 md:sticky left-0")}>
                  {sel ? (
                    <input type="checkbox" aria-label="Select all" checked={pagePicked} disabled={pageKeys.length === 0}
                      onChange={(e) => pickPage(e.target.checked)} />
                  ) : <input type="checkbox" disabled title={NOT_WIRED} aria-label="Select all" />}
                </th>
                {/* #37: fixed left, after the selection column. */}
                <th className={cn(TH, "md:sticky left-12")} style={{ width: FIT_NAME }}>{text.name}</th>
                {columns.map((c) => (
                  <th key={c.title} className={cn(TH, FIT_PAD)} style={{ width: c.width }}>
                    {/* A head may wrap to fit; a tip's icon stays on the line of the head's last word. */}
                    {c.tip ? <TipHead title={c.title} tip={c.tip} /> : c.title}
                  </th>
                ))}
                {/* #56: fixed right. */}
                <th className={cn(TH, ACTIONS_RULE, "md:sticky right-0 px-2")} style={{ width: FIT_ACTIONS }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                /* Ours: the bundle spins (`loading:{spinning}`); the house draws placeholder rows. */
                <SkeletonRows cols={span} rows={5} cellClassName={TD} />
              ) : sessionGone && shown.length === 0 ? (
                <tr><td colSpan={span} className="py-16"><Reconnect /></td></tr>
              ) : shown.length === 0 ? (
                /* #65: the search art and "No data", centred in ~250px. */
                <tr><td colSpan={span} className="h-[250px]"><EmptyState kind="search" text="No data" /></td></tr>
              ) : shown.map((r) => (
                <FrameRows key={rowKey(r)} span={span} more={expanded?.(r)}>
                  <td className={cn(TD, STICKY_TD, "md:sticky left-0 overflow-visible")}>
                    {sel && sel.canSelect(r) ? (
                      <input type="checkbox" aria-label={`Select ${rowName(r)}`} checked={sel.selected.includes(rowKey(r))}
                        onChange={(e) => pick(rowKey(r), e.target.checked)} />
                    ) : (
                      <input type="checkbox" disabled title={sel ? "Not on OnlyFans" : NOT_WIRED} aria-label={`Select ${rowName(r)}`} />
                    )}
                  </td>
                  <td className={cn(TD, STICKY_TD, "md:sticky left-12")}>{nameCell(r)}</td>
                  {columns.map((c) => (
                    <td key={c.title} className={cn(TD, FIT_PAD, "tabular-nums")} title={c.hint?.(r)} data-metric={c.title}>
                      {c.cell(r)}
                    </td>
                  ))}
                  <td className={cn(TD, STICKY_TD, ACTIONS_RULE, "md:sticky right-0 overflow-visible px-2")}>
                    {actions(r)}
                  </td>
                </FrameRows>
              ))}
            </tbody>
          </table>
        </div>
        {shown.length > 0 && (
          <Pager page={current} total={rows.length} size={f.pageSize} onPage={f.setPage} onSize={f.setPageSize} />
        )}
      </div>
    </div>
  );
}

/** A row, and under it the full-width `more` (Details in place) when there is one. */
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
