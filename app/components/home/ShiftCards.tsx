"use client";

/** Dashboard schedule, personal shifts, and current clock-ins.
 * Owners see assigned employees across the selected dashboard period; chatters
 * keep their personal shifts and clock actions. Empty clock-in lists stay compact.
 */

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Users } from "lucide-react";

import { useChatter } from "@/contexts/ChatterContext";
import { useUser } from "@/contexts/UserContext";
import ClockDialog from "@/components/shifts/ClockDialog";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { EmptyState, IfButton, IfCard } from "@/components/ui/infloww";
import { useWeekStart } from "@/lib/appliedSettings";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import {
  addDays, hhmm, occurrenceLabel, SHIFTS_POLL_MS, useClock, useClockedIn, useMyShifts, weekStartOf,
  useShiftWeek, type ClockedInRow, type MyShiftOccurrence, type ShiftOccurrence,
} from "@/lib/shifts";
import { cn } from "@/lib/utils";

const BUTTON =
  "text-xs px-3 py-1.5 rounded-lg bg-bg-elev-1 hover:bg-bg-elev-2 border border-border disabled:opacity-50";
const LINK = "text-accent hover:underline underline-offset-2";
const OFF = "Time tracking is off";
const CLOCKED_IN = "Current clocked-in employees";
/** `IfCard`'s frame, for the Not wired card, which is a `<fieldset>` (#8, #9). */
const CARD = "rounded-[12px] bg-bg-elev-1 pt-5 px-6 pb-4 min-w-0";

/** The capture's card (#8, #9) and title (#12, #15): `IfCard`, named by its title; `after` sits right after it. */
function Card({ title, tip, after, className, scrollable = false, children }: {
  title: string; tip?: string; after?: ReactNode; className?: string; scrollable?: boolean; children: ReactNode;
}) {
  return (
    <IfCard aria-label={title} title={<>{title}{after}</>} info={tip} className={cn("min-w-0", className)}>
      <div role={scrollable ? "group" : undefined} aria-label={scrollable ? `${title} list` : undefined}
        tabIndex={scrollable ? 0 : undefined}
        className={cn("mt-4 space-y-3", scrollable && "min-h-0 overflow-y-auto overscroll-contain pr-2")}>{children}</div>
    </IfCard>
  );
}

/** The loading line, or the error line with Retry, or null once loaded. */
function loadGate(q: UseQueryResult<unknown>, what: string): ReactNode {
  if (q.isPending) return <p className="text-sm text-fg-dim">{`Loading ${what}…`}</p>;
  if (q.isError) {
    return (
      <p className="text-sm text-err flex flex-wrap items-center gap-2">
        {`Couldn't load ${what}: ${q.error.message}`}
        <button type="button" className={BUTTON} onClick={() => void q.refetch()}>Retry</button>
      </p>
    );
  }
  return null;
}

/** "Time tracking is off", ours: the bundle's cards have no such line. */
function TimeTrackingOff({ owner }: { owner: boolean }) {
  return (
    <p title={EXTRA_LABEL} className="text-[12px] text-muted">
      <span>{OFF}</span>
      {owner && (
        <>
          {" · "}
          <Link href="/settings/time-tracking" className={LINK}>Settings › Time tracking</Link>
        </>
      )}
    </p>
  );
}

/** Now, re-read every poll so an elapsed time moves while the data does not. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), SHIFTS_POLL_MS);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

/** "1h 05m" from `iso` to `now`. */
function elapsed(iso: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** The named parts of `iso` in `tz` (the viewer's zone when `tz` is empty). */
function partsIn(iso: string, tz: string, opts: Intl.DateTimeFormatOptions): Record<string, string> {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { ...opts, timeZone: tz || undefined })
      .formatToParts(new Date(iso)).map((p) => [p.type, p.value]),
  );
}

/** The bundle's shift date, `dddd, MMM. D, YYYY` (#69): "Wednesday, Oct. 14, 2026". */
function shiftDate(iso: string, tz: string): string {
  const p = partsIn(iso, tz, { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  return `${p.weekday}, ${p.month}. ${p.day}, ${p.year}`;
}

/** The bundle's shift time, `hh:mm A` (#69): "03:00 PM". */
function shiftTime(iso: string, tz: string): string {
  const p = partsIn(iso, tz, { hour: "2-digit", minute: "2-digit", hour12: true });
  return `${p.hour}:${p.minute} ${p.dayPeriod}`;
}

type PillState = "before" | "now" | "after";
/** The time pill's tint (#72): grey for a past shift, the bundle's green for one in progress, its red for an
 *  upcoming one, drawn in the house tokens (ADR-0010). */
const PILL: Record<PillState, string> = {
  before: "bg-fg-dim/10 text-fg",
  now: "bg-ok/10 text-ok",
  after: "bg-err/10 text-err",
};

/** The empty art and "No data" (#73, #93), 225px down from the card's title from `md` (#74). The live capture shows
 *  the plain "data" art here (16-dashboard.png), not the clock one. */
function NoData() {
  return <EmptyState className="py-8 md:pt-[225px] md:pb-0" />;
}

/** The "My shifts" card: the capture's title and tooltip (#65, #66), the full height of the bottom box from `md`
 *  (#67), its body scrolling as the bundle's `overflow:"overlay"`. */
function MyShiftsFrame({ children, owner = false }: { children: ReactNode; owner?: boolean }) {
  return (
    <Card
      title={owner ? "Scheduled shifts" : "My shifts"}
      tip="Your scheduled shifts during this period"
      className="flex max-h-[720px] flex-col md:absolute md:inset-0"
      scrollable
    >
      {children}
    </Card>
  );
}

export function MyShiftsCard({ from, to, ready = true }: { from?: string; to?: string; ready?: boolean }) {
  const { user } = useUser();
  const { chatter } = useChatter();
  if (user) return <OwnerMyShifts from={from} to={to} ready={ready} />;
  if (chatter) return <ChatterMyShifts />;
  return null;
}

function OwnerMyShifts({ from, to, ready }: { from?: string; to?: string; ready: boolean }) {
  const weekStart = weekStartOf(new Date(), useWeekStart());
  const q = useShiftWeek({ weekStart: from ? new Date(from) : weekStart,
    weekEnd: to ? new Date(Date.parse(to) + 1) : addDays(weekStart, 7) }, ready);
  const now = useNow();
  const slots = new Map<string, ShiftOccurrence>();
  for (const occurrence of q.data?.occurrences ?? []) {
    const key = `${occurrence.occurrence_start}:${occurrence.occurrence_end}:${occurrence.tz}`;
    const slot = slots.get(key);
    if (!slot) slots.set(key, { ...occurrence, employees: [...occurrence.employees] });
    else for (const employee of occurrence.employees) {
      if (!slot.employees.some((e) => e.id === employee.id)) slot.employees.push(employee);
    }
  }
  const rows = [...slots.values()].sort((a, b) => a.occurrence_start.localeCompare(b.occurrence_start));
  return (
    <MyShiftsFrame owner>
      {loadGate(q, "scheduled shifts") ?? (rows.length === 0 ? <NoData /> : (
        <ul className="divide-y divide-border/40">
          {rows.map((o) => {
            const state: PillState = now > Date.parse(o.occurrence_end) ? "before"
              : now >= Date.parse(o.occurrence_start) ? "now" : "after";
            return <li key={`${o.shift_id}:${o.occurrence_start}`} className="py-4 first:pt-0">
              <span data-date className="block text-[12px] mb-2">{scheduleDate(o.occurrence_start, o.tz)}</span>
              <span data-time data-state={state} className={cn("inline-block rounded px-1.5 py-1 text-[12px] leading-4", PILL[state])}>
                {`${scheduleTime(o.occurrence_start, o.tz)}-${scheduleTime(o.occurrence_end, o.tz)}`}
              </span>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {o.employees.map((e) => <span key={e.id} data-avatar title={e.display_name} aria-label={e.display_name}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[10px] font-medium text-accent">
                  {e.display_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("")}
                </span>)}
              </div>
            </li>;
          })}
        </ul>
      ))}
    </MyShiftsFrame>
  );
}

function scheduleDate(iso: string, tz: string) {
  const p = partsIn(iso, tz, { weekday: "long", day: "numeric", month: "numeric", year: "numeric" });
  return `${p.weekday}, ${p.day}.${p.month}.${p.year}`;
}

function scheduleTime(iso: string, tz: string) {
  const p = partsIn(iso, tz, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return `${p.hour}:${p.minute}`;
}

/** One of the chatter's occurrences as the bundle's shift row (#69 to #72). */
function ShiftRow({ o, now, creator }: { o: MyShiftOccurrence; now: number; creator: string }) {
  const start = new Date(o.occurrence_start).getTime();
  const end = new Date(o.occurrence_end).getTime();
  const state: PillState = now > end ? "before" : now >= start ? "now" : "after";
  return (
    <li className="py-4 border-b border-border/40 last:border-0">
      <span data-date className="block text-[12px] mb-2">{shiftDate(o.occurrence_start, o.tz)}</span>
      <span data-time data-state={state} className={cn("inline-block text-[12px] px-2 py-0.5 rounded", PILL[state])}>
        {`${shiftTime(o.occurrence_start, o.tz)}–${shiftTime(o.occurrence_end, o.tz)}`}
      </span>
      <div className="flex">
        <span data-avatar title={creator} className="w-7 h-7 mt-2 mr-1.5 rounded-full overflow-hidden shrink-0">
          <AccountAvatarPicture account={{ id: o.account_id, nickname: creator }} letters={1} initialClassName="text-[10px]" />
        </span>
      </div>
    </li>
  );
}

/** One "My shifts" week heading and its occurrences; nothing when it has none. The split is ours (phase-04, story
 *  20), so the heading carries the label. */
function WeekGroup({ label, list, now, creator }: {
  label: string;
  list: MyShiftOccurrence[];
  now: number;
  creator: (id: string | null) => string;
}) {
  if (list.length === 0) return null;
  return (
    <div role="group" aria-label={label}>
      <h3 title={EXTRA_LABEL} className="text-xs font-semibold text-fg-dim">{label}</h3>
      <ul>
        {list.map((o) => (
          <ShiftRow key={`${o.shift_id}:${o.occurrence_start}:${o.account_id}`} o={o} now={now} creator={creator(o.account_id)} />
        ))}
      </ul>
    </div>
  );
}

/**
 * ASSUMPTION: a chatter's card says "Time tracking is off" only when none of
 * its Creators' Agencies has it on; with one on, the card lists as usual and
 * the dialog explains a Creator that is off. The Shifts list whatever the
 * flag, as the bundle's card lists them (ticket 53). Rung 5. Overturned if a
 * chatter linked to two Agencies must see the off state per Creator on the
 * card.
 *
 * ASSUMPTION: the card's "week" (docs/spec/phase-04, story 20) is where its
 * today-plus-seven-days list splits into "This week" and "Next week", at the
 * Agency's week start in the browser's timezone; the range itself stays
 * Phase 2's. Rung 4: additive, and no occurrence leaves the card. The bundle
 * lists the header's period instead (#66), so the headings are labelled ours.
 * Overturned if the owner wants the card to follow the header's period, which
 * needs a period on `GET /admin/shifts/me`.
 */
function ChatterMyShifts() {
  const q = useMyShifts();
  const now = useNow();
  const nextWeekStart = addDays(weekStartOf(new Date(now), useWeekStart()), 7);
  const clock = useClock();
  const data = q.data;
  const open = clock.status.data?.open;
  const creator = (id: string | null) =>
    data?.accounts.find((a) => a.account_id === id)?.display_name ?? id ?? "a Creator";
  const occurrences = data?.occurrences ?? [];
  const thisWeek = occurrences.filter((o) => new Date(o.occurrence_start) < nextWeekStart);
  const nextWeek = occurrences.filter((o) => new Date(o.occurrence_start) >= nextWeekStart);

  let body = loadGate(q, "your shifts");
  if (!body && data) {
    const on = data.accounts.some((a) => a.time_tracking_enabled);
    body = (
      <>
        {occurrences.length === 0 ? (
          <NoData />
        ) : (
          <>
            <WeekGroup label="This week" list={thisWeek} now={now} creator={creator} />
            <WeekGroup label="Next week" list={nextWeek} now={now} creator={creator} />
          </>
        )}
        <div title={EXTRA_LABEL} className="pt-6 space-y-3">
          {!on ? <TimeTrackingOff owner={false} /> : (
            <>
              {open && (
                <p className="text-sm font-medium">
                  {`Clocked in${open.account_id ? ` on ${creator(open.account_id)}` : ""} · ${elapsed(open.in_utc, now)}`}
                </p>
              )}
              {clock.visible && (
                <div className="flex justify-end">
                  <IfButton disabled={clock.busy} onClick={() => void clock.act()}>{clock.label}</IfButton>
                </div>
              )}
            </>
          )}
        </div>
      </>
    );
  }
  return (
    <MyShiftsFrame>
      {body}
      {clock.picking && <ClockDialog onClose={clock.closePicker} />}
    </MyShiftsFrame>
  );
}

export function ClockedInCard() {
  const { user } = useUser();
  const { chatter } = useChatter();
  const q = useClockedIn(!!user);
  const mine = useMyShifts(!user && !!chatter);
  if (user) return <OwnerClockedIn q={q} />;
  if (chatter && mine.data?.accounts.some((a) => a.time_tracking_enabled)) {
    // #76: the bundle shows the card to this chatter, but no read the chatter is granted lists who is clocked in.
    return (
      <fieldset disabled title="not wired" aria-label={CLOCKED_IN} className={CARD}>
        <div className="flex items-center">
          <span className="text-[16px] font-medium mr-[9px] text-fg-dim">{CLOCKED_IN}</span>
          <Users size={14} aria-hidden className="text-fg-dim" />
        </div>
      </fieldset>
    );
  }
  return null;
}

/** " on <Creator>", or for an agency-wide event the Creators its Employee
 *  holds in the linked Shift; " · —" with neither. */
function creatorPart(r: ClockedInRow): string {
  const names = r.account ? [r.account.display_name] : (r.shift?.accounts ?? []).map((a) => a.display_name);
  return names.length > 0 ? ` on ${names.join(", ")}` : " · —";
}

function OwnerClockedIn({ q }: { q: ReturnType<typeof useClockedIn> }) {
  const rows = q.data?.clocked_in ?? [];
  // #75: the people icon and the count after the title, once the read has answered.
  const count = q.isSuccess ? (
    <span data-count aria-label={`${rows.length} clocked in`} className="ml-[9px] flex items-center gap-1 text-[14px] font-normal text-fg-dim">
      <Users size={14} aria-hidden className="text-border-light" />
      {rows.length}
    </span>
  ) : null;
  return (
    <Card title={CLOCKED_IN} after={count}>
      {loadGate(q, "clocked-in employees") ?? (
        <>
          {!q.data?.time_tracking_enabled && <TimeTrackingOff owner />}
          {/* Keep empty cards compact; scroll longer employee lists. */}
          <div data-clocked-in-list className="overflow-y-auto" style={{ maxHeight: 100 }}>
            {rows.length === 0 ? (
              <p className="text-[12px] text-muted">No employees have clocked in.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {rows.map((r) => (
                  <li key={r.clock_event_id}>
                    <span className="font-medium">{r.employee?.display_name ?? "A deleted employee"}</span>
                    {/* The bundle's row is the Employee's name only; the rest is ours. */}
                    <span data-detail title={EXTRA_LABEL} className="text-fg-dim">
                      {`${creatorPart(r)} · since ${occurrenceLabel(r.in_utc)} · ${r.shift
                        ? `Shift ${hhmm(new Date(r.shift.occurrence_start))}–${hhmm(new Date(r.shift.occurrence_end))}`
                        : "No shift"}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
