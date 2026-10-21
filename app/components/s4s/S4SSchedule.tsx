"use client";

/**
 * S4S schedule (Inventory §3.6; docs/spec/phase-03-share-for-share.md, UI and Display status), on Infloww's `Index$5`
 * (page-parity 15), for the creator picked on the rail, in UTC (the header says so): left, "Scheduled S4S" and the
 * picked day's slots from `GET /admin/s4s/schedule?from&to` (one UTC month); right, 265px, a month calendar with a
 * red dot on days with S4S (only those days and today pickable), then "S4S statistics": the day's slots, Total Growth
 * (not wired, "In the statistics" as Infloww shows under 10) and the month's completed ones. Each slot shows the
 * partner as the request stored it at send (never a live read of the other Agency, ADR-0011) and Infloww's status:
 * "Will be posted shortly", "In progress", "Complete", "Cancelled", or "Failed" (Inflowwww extra, its tooltip) with
 * the reason. Ours, labelled: "Cancel" on a slot that will still post (`POST /admin/s4s/slots/{id}/cancel`, behind a
 * confirm), the live-posting line while the Deployment's live posting is off, and "Partner's post: …" on a slot
 * whose partner deleted, archived or edited its own post of the pair before removal (`partner_issue`, ADR-0015).
 *
 * ASSUMPTION: a reason is shown as its stored code with underscores read as spaces ("partner opted out"). Rung 5
 * (no reason copy exists in the Inventory). Overturned by Infloww's own reason wording.
 */

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { EmptyState, IfButton, IfModal } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { ProjectionAvatar, message, monthName, utcDate, utcDay, utcTime } from "@/components/s4s/s4sBits";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import {
  S4S_SCHEDULE_KEY, cancelS4SSlot, useS4SSchedule, type S4SDisplayStatus, type S4SProfile, type S4SSlot,
} from "@/lib/s4s";
import { cn } from "@/lib/utils";

export const BANNER = "Live posting is off on this deployment. Slots are planned, but nothing is posted to OnlyFans.";
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

/** Infloww's status words and colours; "Failed" is ours. */
export const STATUS: Record<S4SDisplayStatus, { text: string; color: string }> = {
  "Will be posted shortly": { text: "Will be posted shortly", color: "text-accent" },
  "In progress": { text: "In progress", color: "text-[#ffa15f]" },
  Completed: { text: "Complete", color: "text-[#2ad4ac]" },
  Canceled: { text: "Cancelled", color: "text-[#ff7c71]" },
  Failed: { text: "Failed", color: "text-[#ff7c71]" },
};

const utcMonthStart = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
const addMonths = (d: Date, n: number) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1));

/** "Posted at MMM. D HH:mm", the reason, or the planned time. */
function detailOf(s: S4SSlot): string {
  const d = new Date(s.slot_at);
  if (s.display_status === "Completed") return `Posted at ${monthName(d.getUTCMonth()).slice(0, 3)}. ${d.getUTCDate()} ${utcTime(s.slot_at)}`;
  if ((s.display_status === "Canceled" || s.display_status === "Failed") && s.reason) return s.reason.replace(/_/g, " ");
  return `${utcTime(s.slot_at)} UTC`;
}

export default function S4SSchedule({ profile, livePosting }: { profile: S4SProfile | null; livePosting?: boolean }) {
  const today = new Date();
  const [month, setMonth] = useState(() => utcMonthStart(today));
  const [picked, setPicked] = useState(() => utcDay(today));
  const q = useS4SSchedule(month);
  const pid = profile?.profile_id ?? null;
  const slots = (q.data ?? []).filter((s) => pid != null && s.own.profile_id === pid);

  const byDay = new Map<string, S4SSlot[]>();
  for (const s of slots) {
    const k = utcDay(new Date(s.slot_at));
    byDay.set(k, [...(byDay.get(k) ?? []), s]);
  }
  const daySlots = (byDay.get(picked) ?? []).slice().sort((a, b) => a.slot_at.localeCompare(b.slot_at));
  const completed = slots.filter((s) => s.display_status === "Completed").length;
  const pickedDate = new Date(`${picked}T00:00:00Z`);

  return (
    <div className="flex flex-col pl-6 md:flex-row">
      <section aria-label="Scheduled S4S" className="min-w-0 flex-1 pr-6 pt-6 pb-6">
        <h2 className="text-[16px] font-medium text-fg">Scheduled S4S</h2>
        <p className="mt-1 text-[14px] text-accent">{utcDate(pickedDate)}</p>
        {livePosting === false && (
          <p role="status" className="mt-1 text-[12px] text-[#999]">{BANNER} <ExtraTag /></p>
        )}
        {q.isError && <p role="alert" className="mt-4 text-[14px] text-err">{message(q.error)}</p>}
        {q.isLoading && <p className="mt-4 text-[14px] text-fg-dim">Loading…</p>}
        {q.isSuccess && daySlots.length === 0 && (
          <EmptyState size="md" className="mt-[180px]" textClassName="text-[14px] font-semibold text-fg" text="No scheduled Share for Shares" />
        )}
        {daySlots.length > 0 && (
          <ul className="mt-4 space-y-4">
            {daySlots.map((s) => <li key={s.id}><SlotRow slot={s} /></li>)}
          </ul>
        )}
      </section>
      <aside aria-label="S4S calendar"
        className="order-first w-full shrink-0 border-border pt-6 pr-3 pb-[50px] md:order-none md:w-[265px] md:border-l md:pl-6">
        <MonthCalendar month={month} picked={picked} today={utcDay(today)} marked={new Set(byDay.keys())}
          onMonth={(n) => setMonth((m) => addMonths(m, n))} onPick={setPicked} />
        <h3 className="mt-6 text-[16px] font-medium text-fg">S4S statistics</h3>
        <div className="mt-4 space-y-4">
          <Tile figure={String(daySlots.length)} caption={`Scheduled for ${monthName(pickedDate.getUTCMonth()).slice(0, 3)} ${pickedDate.getUTCDate()}`} />
          <Tile figure="In the statistics" small caption="Total Growth" title="not wired" />
          <Tile figure={String(completed)} caption="Completed Share for Shares" />
        </div>
      </aside>
    </div>
  );
}

function Tile({ figure, caption, small, title }: { figure: string; caption: string; small?: boolean; title?: string }) {
  return (
    <div title={title} className="rounded-lg bg-[#2f2f2f] p-4 [html[data-theme=light]_&]:bg-bg-elev-2">
      <div className={cn("text-fg", small ? "text-[18px] font-medium" : "text-[24px] font-bold")}>{figure}</div>
      <div className="mt-4 text-[12px] text-[#999]">{caption}</div>
    </div>
  );
}

/** A compact month: 20px round day cells, a 5px #f62828 dot under days with S4S; only those days and today pick. */
function MonthCalendar({ month, picked, today, marked, onMonth, onPick }: {
  month: Date;
  picked: string;
  today: string;
  marked: Set<string>;
  onMonth: (n: number) => void;
  onPick: (day: string) => void;
}) {
  const y = month.getUTCFullYear();
  const m = month.getUTCMonth();
  const days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const lead = month.getUTCDay();
  const arrow = "grid h-6 w-6 place-items-center rounded text-fg-dim hover:text-fg";
  return (
    <div>
      <div className="flex items-center justify-between">
        <button type="button" aria-label="Previous month" className={arrow} onClick={() => onMonth(-1)}><ChevronLeft className="h-4 w-4" /></button>
        <span className="text-[14px] font-medium text-fg">{`${monthName(m)} ${y}`}</span>
        <button type="button" aria-label="Next month" className={arrow} onClick={() => onMonth(1)}><ChevronRight className="h-4 w-4" /></button>
      </div>
      <div role="grid" aria-label={`${monthName(m)} ${y}`} className="mt-3 grid grid-cols-7 gap-y-2 text-center text-[12px]">
        {WEEKDAYS.map((w) => <span key={w} className="text-fg-dim">{w}</span>)}
        {Array.from({ length: lead }, (_, i) => <span key={`lead-${i}`} />)}
        {Array.from({ length: days }, (_, i) => {
          const key = utcDay(new Date(Date.UTC(y, m, i + 1)));
          const has = marked.has(key);
          const on = key === picked;
          return (
            <span key={key} className="flex flex-col items-center gap-0.5">
              <button type="button" aria-label={utcDate(new Date(Date.UTC(y, m, i + 1)))} aria-pressed={on}
                data-s4s={has || undefined} disabled={!has && key !== today} onClick={() => onPick(key)}
                className={cn("grid h-5 w-5 place-items-center rounded-full",
                  on ? "bg-accent text-white" : "text-fg hover:bg-bg-elev-2",
                  "disabled:cursor-default disabled:text-muted disabled:hover:bg-transparent")}>
                {i + 1}
              </button>
              <span aria-hidden className={cn("h-[5px] w-[5px] rounded-full", has ? "bg-[#f62828]" : "bg-transparent")} />
            </span>
          );
        })}
      </div>
    </div>
  );
}

function SlotRow({ slot: s }: { slot: S4SSlot }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancellable = s.display_status === "Will be posted shortly" && new Date(s.slot_at) > new Date();
  const status = STATUS[s.display_status];

  async function cancel() {
    setConfirm(false);
    setBusy(true);
    setError(null);
    try {
      await cancelS4SSlot(s.id);
      await qc.invalidateQueries({ queryKey: S4S_SCHEDULE_KEY });
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article aria-label={`S4S slot with ${s.partner.display_name}`}
      className="flex items-center gap-3 rounded-lg border border-border bg-bg-elev-1 py-[25px] pl-4 pr-2.5">
      <ProjectionAvatar item={s.partner} px={40} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <span className="truncate text-[16px] font-medium text-fg">{s.partner.display_name}</span>
          <span className={cn("shrink-0 text-[14px]", status.color)} title={s.display_status === "Failed" ? EXTRA_LABEL : undefined}>
            {status.text}
          </span>
        </div>
        <div className="mt-1 flex items-start justify-between gap-3">
          <span className="truncate text-[12px] font-medium text-[#999]">{`@${s.partner.username} · by ${s.own.display_name}`}</span>
          <span className="max-w-[240px] text-right text-[12px] text-[#666]">
            {detailOf(s)}
            {cancellable && (
              <button type="button" title={EXTRA_LABEL} disabled={busy} onClick={() => setConfirm(true)}
                className="ml-2 text-accent hover:text-accent-hover disabled:opacity-50">Cancel</button>
            )}
          </span>
        </div>
        {s.partner_issue && (
          <p className="mt-1 text-[12px] text-[#ff7c71]">{`Partner's post: ${s.partner_issue.replace(/_/g, " ")}`}</p>
        )}
        {error && <p role="alert" className="mt-1 text-[12px] text-err">{error}</p>}
      </div>
      {confirm && (
        <IfModal title="Cancel this Share for Share?" width={416} onClose={() => setConfirm(false)} footer={(
          <>
            <IfButton onClick={() => setConfirm(false)}>No</IfButton>
            <IfButton variant="primary" onClick={() => void cancel()}>Yes</IfButton>
          </>
        )}>
          <p className="text-fg-dim">{`Your post with ${s.partner.display_name} on ${utcDate(s.slot_at)} at ${utcTime(s.slot_at)} UTC will not be published.`}</p>
        </IfModal>
      )}
    </article>
  );
}
