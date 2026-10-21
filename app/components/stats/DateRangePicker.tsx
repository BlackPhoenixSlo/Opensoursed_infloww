"use client";

/**
 * DateRangePicker — the legacy reports' range box (page-parity ticket 25), fully controlled. Parent owns `from`/`to`
 * (as YYYY-MM-DD strings, YYYY-MM-DDTHH:00 with `hours`, or null = backend default) and is told whenever either
 * side changes.
 *
 * Infloww's look (live 08-employee-reports.png, the Message dashboard capture; bundle `Index$H`): one 32px #2a2a2a
 * box, "Oct 12, 2026 → Oct 19, 2026" (with the hour when `hours`) and a calendar icon, opening a popover with the
 * presets on the left (Custom, then Last 7 / 30 / 90 / 365 days by default; a page may offer "day" too and rename
 * them, as Sales records' Day / Week / Month) and From / To on the right. A preset calls back with its pair; a date
 * edit flips the mode to "custom". Days run a year back to two days ahead (`dateBounds`), a span of more than a
 * year (by the same calendar year, `shiftYears`) is refused with Infloww's line, and so is a From after the To,
 * hours included.
 *
 * With `timeZone` (the Agency's report time zone) the presets count days from today in that zone
 * (docs/spec/phase-04-apply-stored-settings.md, story 18); without it, from the browser's local today. Presets run
 * through today (Infloww's stop at yesterday), so today's pending sales show.
 *
 * The backend treats missing dates as "last 7d" for coverage, "last 30d" for per-model. We don't try to mirror that
 * here — when a preset is selected we send explicit dates so the URL state stays deterministic regardless of which
 * endpoint reads it.
 */

import { useState, type KeyboardEvent } from "react";
import { ArrowRight, Calendar } from "lucide-react";

import { useOutsideClose } from "@/components/ui/Menu";
import { IfSelect, type IfOption } from "@/components/ui/infloww";
import { dateBounds, presetRange, shiftYears, type FixedRangePreset } from "@/lib/dateRange";
import { cn } from "@/lib/utils";

export type RangePreset = FixedRangePreset | "custom";

const DEFAULT_PRESETS: readonly FixedRangePreset[] = ["7d", "30d", "90d", "365d"];
const DEFAULT_LABELS: Record<FixedRangePreset, string> = {
  day: "Day", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", "365d": "Last 365 days",
};
/** Infloww's own refusal (bundle: `end - start > 365 days`; ours counts the calendar year `dateBounds` does, so a
 *  leap year's 366 days fit). */
export const SPAN_LIMIT = "Selected time frame cannot be more than a year";
/** Ours: a From later than the To. */
export const REVERSED = "The start must not be after the end";
/** About the popover's width (presets plus the dates, with hours), to open it leftwards when the box sits near the
 *  right edge and there is room on that side. */
const POPOVER_W = 360;

interface Props {
  from: string | null;
  to: string | null;
  preset: RangePreset;
  onChange: (from: string | null, to: string | null, preset: RangePreset) => void;
  /** The Agency's report time zone; null or absent = the browser's. */
  timeZone?: string | null;
  /** The presets, in order, after Custom; Last 7 / 30 / 90 / 365 days when absent. */
  presets?: readonly FixedRangePreset[];
  /** Preset labels, over the defaults ("Day", "Last 7 days", …). */
  labels?: Partial<Record<FixedRangePreset, string>>;
  /** From and To hour selects under the dates: a side off its whole-day default (From 12 AM, To 11 PM) is sent as
   *  YYYY-MM-DDTHH:00, which `toLocalIso` reads as that wall-clock hour. */
  hours?: boolean;
}

const HOUR_OPTIONS: IfOption[] = Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: hourLabel(h) }));
function hourLabel(h: number) {
  return `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
}
/** A side's hour: its THH suffix, else the whole-day default. */
const hourOf = (v: string | null, dflt: number) => (v && v.length > 10 ? Number(v.slice(11, 13)) : dflt);
/** The day with hour `h`, bare when `h` is the side's whole-day default. */
const withHour = (day: string, h: number, dflt: number) => (h === dflt ? day : `${day}T${String(h).padStart(2, "0")}:00`);
/** "Oct 12, 2026", plus " 3 PM" with `hours`; the day is read as UTC so no browser zone shifts it. */
function sideLabel(v: string, hours: boolean, dflt: number) {
  const day = new Date(`${v.slice(0, 10)}T00:00:00Z`)
    .toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
  return hours ? `${day} ${hourLabel(hourOf(v, dflt))}` : day;
}
/** A side as YYYY-MM-DDTHH, its hour the whole-day default when bare, so two sides compare as strings. */
const sideKey = (v: string, dflt: number) => `${v.slice(0, 10)}T${String(hourOf(v, dflt)).padStart(2, "0")}`;

const DATE_INPUT = cn(
  "h-8 w-[150px] rounded-md border border-border bg-bg px-[11px] text-[14px] text-fg outline-none [color-scheme:inherit]",
  "hover:border-accent focus:border-accent",
);

export default function DateRangePicker({
  from, to, preset, onChange, timeZone, presets = DEFAULT_PRESETS, labels, hours = false,
}: Props) {
  const { open, setOpen, ref } = useOutsideClose<HTMLDivElement>();
  const [refusal, setRefusal] = useState<string | null>(null);
  const [alignRight, setAlignRight] = useState(false);
  const [minDay, maxDay] = dateBounds(timeZone);

  /** Every change goes through here: a From after the To (hours included), or a To more than a year after the From,
   *  is refused, and says so. */
  const emit = (f: string | null, t: string | null, p: RangePreset) => {
    const why = !f || !t ? null
      : sideKey(f, 0) > sideKey(t, 23) ? REVERSED
      : t.slice(0, 10) > shiftYears(f.slice(0, 10), 1) ? SPAN_LIMIT
      : null;
    setRefusal(why);
    if (!why) onChange(f, t, p);
  };

  const toggle = () => {
    if (!open) {
      const box = ref.current?.getBoundingClientRect();
      setAlignRight(!!box && box.left + POPOVER_W > window.innerWidth && box.right >= POPOVER_W);
    }
    setOpen(!open);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); }
  };

  // A new date keeps the side's picked hour.
  const handleFrom = (v: string) => emit(v ? withHour(v, hourOf(from, 0), 0) : null, to, "custom");
  const handleTo = (v: string) => emit(from, v ? withHour(v, hourOf(to, 23), 23) : null, "custom");

  const presetButton = (key: RangePreset, label: string, onClick: () => void) => (
    <button
      key={key}
      type="button"
      aria-pressed={preset === key}
      onClick={onClick}
      className={cn(
        "h-8 whitespace-nowrap rounded px-2 text-left text-[14px] text-fg hover:bg-bg-elev-2",
        preset === key && "bg-bg-elev-2 text-accent",
      )}
    >
      {label}
    </button>
  );

  return (
    <div ref={ref} className="relative inline-block" onKeyDown={onKey}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={toggle}
        className={cn(
          "inline-flex h-8 max-w-full items-center gap-2 whitespace-nowrap rounded px-[11px] text-[14px] text-fg",
          "border border-[#2a2a2a] bg-[#2a2a2a] hover:border-accent",
          "[html[data-theme=light]_&]:border-border [html[data-theme=light]_&]:bg-bg-elev-1",
        )}
      >
        <span className="sr-only">Date range: </span>
        <span className={cn("truncate", !from && "text-muted")}>{from ? sideLabel(from, hours, 0) : "Start date"}</span>
        <ArrowRight aria-hidden className="h-3 w-3 shrink-0 text-muted" />
        <span className={cn("truncate", !to && "text-muted")}>{to ? sideLabel(to, hours, 23) : "End date"}</span>
        <Calendar aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Date range"
          className={cn(
            "absolute top-full z-50 mt-1.5 flex max-w-[calc(100vw-24px)] gap-3 rounded-md border border-border bg-panel p-2 shadow-lg",
            alignRight ? "right-0" : "left-0",
          )}
        >
          <div role="group" aria-label="Date presets" className="flex flex-col border-r border-border pr-3">
            {presetButton("custom", "Custom", () => emit(from, to, "custom"))}
            {presets.map((p) => presetButton(p, labels?.[p] ?? DEFAULT_LABELS[p], () => emit(...presetRange(p, timeZone), p)))}
          </div>
          <div className="flex flex-col gap-2 p-1">
            <Side label="From">
              <input type="date" aria-label="From date" value={from?.slice(0, 10) ?? ""} min={minDay}
                max={to?.slice(0, 10) ?? maxDay} onChange={(e) => handleFrom(e.target.value)} className={DATE_INPUT} />
              {hours && (
                <IfSelect aria-label="From hour" className="w-[150px]" options={HOUR_OPTIONS}
                  value={String(hourOf(from, 0))} disabled={!from}
                  onChange={(h) => emit(withHour(from!.slice(0, 10), Number(h), 0), to, "custom")} />
              )}
            </Side>
            <Side label="To">
              <input type="date" aria-label="To date" value={to?.slice(0, 10) ?? ""} min={from?.slice(0, 10) ?? minDay}
                max={maxDay} onChange={(e) => handleTo(e.target.value)} className={DATE_INPUT} />
              {hours && (
                <IfSelect aria-label="To hour" className="w-[150px]" options={HOUR_OPTIONS}
                  value={String(hourOf(to, 23))} disabled={!to}
                  onChange={(h) => emit(from, withHour(to!.slice(0, 10), Number(h), 23), "custom")} />
              )}
            </Side>
            {refusal && <p role="alert" className="max-w-[200px] text-[12px] text-err">{refusal}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

/** One side of the range: its label left, the date (and the hour under it) right. */
function Side({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="flex h-8 items-center text-[14px] text-fg">{label}</span>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}
