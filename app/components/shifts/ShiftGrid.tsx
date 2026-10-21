"use client";

/**
 * The Shift schedule's week grid, Infloww's legacy `ScheduleList$1` (bundle @16728089, CSS `_1f33j` / `_aluuy`;
 * page-parity ticket 18): a 64px sticky day header (weekday 10px over the date 20px, today in M1, prev / next
 * chevrons in its corners), then one row per Creator, an 80px gutter (avatar and name) and seven day cells. A cell
 * holds up to two Shift tiles (a 6px bar in the Employee's colour, the Employee, "9:00 AM - 5:00 PM" in the Agency's
 * zone) and then "+N more"; a click on its empty area creates a Shift for that Creator and day. Hovering a tile
 * (600ms) or focusing it shows the detail popover: Edit / Delete / Close, the date and times in the Shift's own zone
 * (named when it is not the Agency's), Repeats, Creator, Employee. A Shift with several Creators shows in each row.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Loader2, Pencil, Trash2, X } from "lucide-react";

import { AccountAvatarPicture, type AvatarAccount } from "@/components/ui/AccountAvatarPicture";
import { EmptyState } from "@/components/ui/infloww";
import {
  MONTHS, WEEKDAYS, employeeColours, fmtShiftTime, gmtOffset, type ShiftOccurrence, type ZonedDay,
} from "@/lib/shifts";
import { cn } from "@/lib/utils";

/** Infloww's `pastRecordBackgroundColor`: the bar of a Shift that has ended. */
const PAST_BAR = "#D9D9D9";
/** Tiles a cell shows before "+N more". */
const CELL_CAP = 2;
const HOVER_MS = 600;

// #1a1a1a is `--tc-B-th` (dark); light falls back to the card fill.
const B_TH = "bg-[#1a1a1a] [html[data-theme=light]_&]:bg-bg-elev-1";

const dayLabel = (d: ZonedDay) => `${d.ddd} ${Number(d.dd)} ${MONTHS[Number(d.date.slice(5, 7)) - 1]}`;
const employeeLine = (o: ShiftOccurrence) =>
  o.employees.length === 0 ? "No employee" : `${o.employees[0].display_name}${o.employees.length > 1 ? ` +${o.employees.length - 1}` : ""}`;
const timeLine = (o: ShiftOccurrence, tz: string) =>
  `${fmtShiftTime(o.occurrence_start, tz)} - ${fmtShiftTime(o.occurrence_end, tz)}`;

/** "Thursday, October 15, 2026" in `tz`. */
const longDate = (iso: string, tz: string) =>
  new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "long", month: "long", day: "2-digit", year: "numeric" })
    .format(new Date(iso));
/** "Dec. 31, 2026" (Infloww's `MMM. D, YYYY`) from a YYYY-MM-DD date. */
const untilDate = (date: string) => {
  const [y, m, d] = date.split("-").map(Number);
  return `${MONTHS[m - 1]}. ${d}, ${y}`;
};

type Peek =
  | { kind: "detail"; o: ShiftOccurrence; anchor: DOMRect }
  | { kind: "more"; title: string; list: ShiftOccurrence[]; anchor: DOMRect };

export interface GridRow { account: AvatarAccount; name: string }

export default function ShiftGrid({
  days, tz, now, rows, occurrences, colourOrder, loading, error, onRetry, onPrev, onNext, onEdit, onDelete, onCreate,
}: {
  days: ZonedDay[];
  /** The Agency's time zone: the tiles' times. */
  tz: string;
  now: Date;
  rows: GridRow[];
  /** The week's occurrences after the filters. */
  occurrences: ShiftOccurrence[];
  /** The unfiltered week, so a filter does not recolour anyone. */
  colourOrder: ShiftOccurrence[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onPrev: () => void;
  onNext: () => void;
  onEdit: (o: ShiftOccurrence) => void;
  onDelete: (o: ShiftOccurrence) => void;
  onCreate: (accountId: string, date: string) => void;
}) {
  const colour = employeeColours(colourOrder);
  const [peek, setPeek] = useState<Peek | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimers = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    if (leaveTimer.current) clearTimeout(leaveTimer.current);
    hoverTimer.current = leaveTimer.current = null;
  };
  useEffect(() => clearTimers, []);
  const close = () => { clearTimers(); setPeek(null); };
  const closeSoon = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    leaveTimer.current = setTimeout(() => setPeek(null), 150);
  };

  // Each occurrence on the day it starts (one that started before the week sits on its first day), per Creator.
  const cells = new Map<string, ShiftOccurrence[]>();
  for (const o of occurrences) {
    const start = new Date(o.occurrence_start);
    const i = days.findIndex((d) => start < d.end);
    for (const a of o.accounts) {
      const key = `${a.id}|${i === -1 ? 6 : i}`;
      cells.set(key, [...(cells.get(key) ?? []), o]);
    }
  }

  const tile = (o: ShiftOccurrence, inList = false) => {
    const past = new Date(o.occurrence_end) <= now;
    return (
      <button
        key={`${o.shift_id}-${o.occurrence_start}`}
        type="button"
        onClick={() => { close(); onEdit(o); }}
        onMouseEnter={inList ? undefined : (e) => {
          clearTimers();
          const anchor = e.currentTarget.getBoundingClientRect();
          hoverTimer.current = setTimeout(() => setPeek({ kind: "detail", o, anchor }), HOVER_MS);
        }}
        onMouseLeave={inList ? undefined : closeSoon}
        onFocus={inList ? undefined : (e) => {
          clearTimers();
          setPeek({ kind: "detail", o, anchor: e.currentTarget.getBoundingClientRect() });
        }}
        className={cn(
          "relative z-[1] my-[5px] flex h-10 w-full overflow-hidden rounded text-left",
          "drop-shadow-[0_1px_3px_rgba(0,0,0,.12)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
          B_TH,
        )}
      >
        <span aria-hidden data-bar className="w-1.5 shrink-0 rounded-l"
          style={{ background: past ? PAST_BAR : colour(o.employees[0]?.id ?? -1) }} />
        <span className="flex min-w-0 flex-col justify-center pl-[4.5px] pr-1">
          <span className="max-w-[100px] truncate text-[12px] font-bold leading-4 text-fg">{employeeLine(o)}</span>
          <span className="truncate text-[10px] leading-[14px] text-muted">{timeLine(o, tz)}</span>
        </span>
      </button>
    );
  };

  let body: ReactNode;
  if (loading) {
    body = (
      <div role="status" aria-label="Loading" className="grid min-h-[100px] place-items-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent" aria-hidden />
      </div>
    );
  } else if (error) {
    body = <EmptyState kind="error" className="min-h-[200px]" text={error} onRetry={onRetry} />;
  } else if (rows.length === 0) {
    body = <EmptyState kind="schedule" className="min-h-[200px]" text="No shifts this week" />;
  } else {
    body = rows.map(({ account, name }) => (
      <div key={account.id} role="row" aria-label={name} className={cn("flex", B_TH)}>
        <div role="rowheader" className="flex min-h-[60px] w-20 shrink-0 flex-col items-center justify-center px-1">
          <span className="mb-1 block h-6 w-6 overflow-hidden rounded-full">
            <AccountAvatarPicture account={account} letters={1} initialClassName="text-[10px] font-medium" />
          </span>
          <span title={name} className="max-w-[70px] truncate text-[12px] font-medium text-fg">{name}</span>
        </div>
        {days.map((d) => {
          const list = cells.get(`${account.id}|${days.indexOf(d)}`) ?? [];
          const shown = list.slice(0, CELL_CAP);
          const more = list.slice(CELL_CAP);
          return (
            <div key={d.date} role="gridcell" aria-label={`${name}, ${dayLabel(d)}`}
              className="relative min-h-[50px] min-w-0 flex-1 border-l border-t border-border bg-bg-elev-1 px-1 [html[data-theme=light]_&]:bg-bg">
              <button type="button" aria-label={`Create a shift for ${name} on ${dayLabel(d)}`}
                onClick={() => onCreate(account.id, d.date)}
                className="absolute inset-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent" />
              {shown.map((o) => tile(o))}
              {more.length > 0 && (
                <button type="button"
                  onClick={(e) => {
                    clearTimers();
                    setPeek({ kind: "more", title: dayLabel(d), list: more, anchor: e.currentTarget.getBoundingClientRect() });
                  }}
                  className="relative z-[1] mb-1 px-1 text-[12px] text-accent hover:text-accent-hover">
                  {`+${more.length} more`}
                </button>
              )}
            </div>
          );
        })}
      </div>
    ));
  }

  return (
    <div role="grid" aria-label="Shift schedule"
      className="max-h-[calc(100dvh-var(--chrome-top)-230px)] min-h-[264px] overflow-auto rounded border border-[#1a1a1a] [html[data-theme=light]_&]:border-border">
      <div className="min-w-[720px]">
        <div className={cn("sticky top-0 z-[3] h-16 shadow-[0_3px_4px_rgba(0,0,0,.07)]", B_TH)}>
          <div role="row" className="flex h-full items-center pl-20">
            {days.map((d) => (
              <div key={d.date} role="columnheader" aria-label={dayLabel(d)}
                className={cn("flex flex-1 flex-col items-start gap-1 pl-3.5", d.today ? "text-accent" : "text-fg")}>
                <span className={cn("text-[10px] leading-[10px]", !d.today && "text-fg-dim")}>{d.ddd}</span>
                <span className="text-[20px] font-medium leading-5">{d.dd}</span>
              </div>
            ))}
          </div>
          <button type="button" aria-label="Show previous week" onClick={onPrev}
            className="absolute left-4 top-5 grid h-6 w-6 place-items-center text-border-light hover:text-accent">
            <ChevronLeft className="h-6 w-6" aria-hidden />
          </button>
          <button type="button" aria-label="Show next week" onClick={onNext}
            className="absolute right-4 top-5 grid h-6 w-6 place-items-center text-border-light hover:text-accent">
            <ChevronRight className="h-6 w-6" aria-hidden />
          </button>
        </div>
        {body}
      </div>
      {peek && (
        <PeekPopover anchor={peek.anchor} onClose={close}
          onEnter={() => { if (leaveTimer.current) clearTimeout(leaveTimer.current); }}
          onLeave={peek.kind === "detail" ? closeSoon : undefined}
          label={peek.kind === "detail" ? "Shift details" : `More shifts on ${peek.title}`}>
          {peek.kind === "detail" ? (
            <ShiftDetail o={peek.o} tz={tz} account={(id) => rows.find((r) => r.account.id === id)?.account}
              onEdit={() => { close(); onEdit(peek.o); }}
              onDelete={() => { close(); onDelete(peek.o); }}
              onClose={close} />
          ) : (
            <>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[14px] font-medium text-fg">{peek.title}</span>
                <IconButton label="Close" onClick={close}><X className="h-4 w-4" aria-hidden /></IconButton>
              </div>
              {peek.list.map((o) => tile(o, true))}
            </>
          )}
        </PeekPopover>
      )}
    </div>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded text-muted hover:text-accent">
      {children}
    </button>
  );
}

/** antd's popover (#1f1f1f, radius 10, 16px padding, 300px), fixed under its tile (above it near the viewport foot),
 *  in a portal so the grid's scroll box does not clip it. Escape and an outside click close it. */
function PeekPopover({ anchor, label, onClose, onEnter, onLeave, children }: {
  anchor: DOMRect;
  label: string;
  onClose: () => void;
  onEnter: () => void;
  onLeave?: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRef.current(); };
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) closeRef.current(); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, []);
  const vw = typeof window === "undefined" ? 1440 : window.innerWidth;
  const vh = typeof window === "undefined" ? 900 : window.innerHeight;
  const left = Math.max(8, Math.min(anchor.left, vw - 308));
  const below = anchor.bottom + 280 <= vh;
  return createPortal(
    <div ref={ref} role="dialog" aria-label={label} onMouseEnter={onEnter} onMouseLeave={onLeave}
      style={{ left, ...(below ? { top: anchor.bottom + 4 } : { bottom: vh - anchor.top + 4 }) }}
      className="fixed z-50 w-[300px] rounded-[10px] bg-[#1f1f1f] p-4 text-[14px] text-fg shadow-2xl [html[data-theme=light]_&]:bg-white">
      {children}
    </div>,
    document.body,
  );
}

function ShiftDetail({ o, tz, account, onEdit, onDelete, onClose }: {
  o: ShiftOccurrence;
  tz: string;
  account: (id: string) => AvatarAccount | undefined;
  onEdit: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  // The Shift's own zone: its wall clock is what was scheduled; named when it is not the Agency's.
  const zone = o.tz;
  const offset = gmtOffset(o.occurrence_start, zone);
  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-1">
        <IconButton label="Edit" onClick={onEdit}><Pencil className="h-4 w-4" aria-hidden /></IconButton>
        <IconButton label="Delete" onClick={onDelete}><Trash2 className="h-4 w-4" aria-hidden /></IconButton>
        <IconButton label="Close" onClick={onClose}><X className="h-4 w-4" aria-hidden /></IconButton>
      </div>
      <p className="font-medium">
        {`${longDate(o.occurrence_start, zone)} (${offset}${zone !== tz ? `, ${zone}` : ""})`}
      </p>
      <p>{timeLine(o, zone)}</p>
      {o.repeat_days && (
        <p className="text-fg-dim">
          {`Repeats: Weekly on ${o.repeat_days.map((d) => WEEKDAYS[d - 1]).join(", ")}${
            o.repeat_until ? `, until ${untilDate(o.repeat_until)}` : ""}`}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted">Creator:</span>
        {o.accounts.map((a) => (
          <span key={a.id} className="inline-flex items-center gap-1.5">
            <span className="block h-5 w-5 overflow-hidden rounded-full">
              <AccountAvatarPicture account={account(a.id) ?? { id: a.id, nickname: a.display_name }} letters={1}
                initialClassName="text-[10px] font-medium" />
            </span>
            {a.display_name}
          </span>
        ))}
      </div>
      <p><span className="text-muted">Employee: </span>{o.employees.map((e) => e.display_name).join(", ")}</p>
    </div>
  );
}
