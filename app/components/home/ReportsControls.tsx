"use client";

/** Creator reports' filter bar controls: the date range and its presets, the granularity tabs and the "Shown by"
 *  select, the Channels, Creator and Custom metrics pickers, and the UTC chip. */

import { useEffect, useId, useRef, useState } from "react";
import { Filter as FilterFunnel, SlidersHorizontal, X } from "lucide-react";

import { type Gran, granAllowed, granShown } from "@/components/stats/chart";
import { dateBounds } from "@/lib/dateRange";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { type Chan, type RangeKey, CHANNELS, DEFAULT_COLS, datePresets, fmtRangeLabel, GRAN_LIMIT, GRANS, STAT_COLS } from "./reportsMath";

/* ── outside-click hook ── */

function useClickOutside<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    // pointerdown, not mousedown: iOS only synthesises mousedown for taps on
    // clickable nodes, so tapping the backdrop never dismissed these popovers.
    // pointerdown precedes mousedown for a mouse, so desktop is unchanged.
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  return ref;
}

/* ───────── interactive pills ───────── */

/** #40: a filter bar control's geometry, 28px high, 6px by 9px padding, 6px radius, 4px from icon to text, 14px. */
export const FILTER_FIELD = "min-h-7 px-[9px] py-1.5 gap-1 text-[14px]";

function PillTrigger({ open, ariaLabel, className, children, onClick }: {
  open?: boolean; ariaLabel?: string; className?: string; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-expanded={open}
      onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] outline-none", className)}
      style={{
        border: `1px solid ${open ? "var(--color-accent)" : "var(--color-border)"}`,
        background: "var(--color-bg-elev-1)",
        color: "var(--color-fg)",
        boxShadow: open ? "0 0 0 3px color-mix(in srgb, var(--color-accent) 25%, transparent)" : "none",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function PopoverBox({ children, anchor }: { children: React.ReactNode; anchor: "left" | "right" }) {
  return (
    <div
      style={{
        position: "absolute",
        top: "calc(100% + 6px)",
        [anchor]: 0,
        background: "var(--color-bg-elev-1)",
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        boxShadow: "0 12px 32px rgba(0,0,0,0.35), 0 2px 6px rgba(0,0,0,0.2)",
        padding: 8,
        zIndex: 20,
        minWidth: 200,
      } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

/** #21 to #24: the date range, the range's days (YYYY-MM-DD in the report time zone), the bundle's presets beside
 *  the two days, a year back to two days ahead. A cleared input or a day out of bounds changes nothing, so both
 *  sides always hold a day. */
export function DateRangePill({ from, to, preset, reportTz, onChange, onPreset }: {
  from: string | null; to: string | null; preset: RangeKey; reportTz: string | null;
  onChange: (f: string | null, t: string | null) => void;
  onPreset: (key: RangeKey, days: [string, string]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const [minDay, maxDay] = dateBounds(reportTz);
  const isDay = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v) && v >= minDay && v <= maxDay;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <PillTrigger open={open} ariaLabel="Date range" className={FILTER_FIELD} onClick={() => setOpen((v) => !v)}>
        <span style={{ color: "var(--color-fg)" }}>{fmtRangeLabel(from)}</span>
        <span style={{ color: "var(--color-fg-dim)" }}>{"  →  "}</span>
        <span style={{ color: "var(--color-fg)" }}>{fmtRangeLabel(to)}</span>
        <CalIcon />
      </PillTrigger>
      {open && (
        <PopoverBox anchor="left">
          <div className="flex gap-3">
          <div role="group" aria-label="Date presets" className="flex flex-col pr-3 border-r" style={{ borderColor: "var(--color-border)" }}>
            {datePresets(reportTz).map((p) => (
              <button
                key={p.key}
                type="button"
                aria-pressed={preset === p.key}
                onClick={() => onPreset(p.key, p.days)}
                className="text-left whitespace-nowrap px-2 py-1 rounded text-[12px]"
                style={{
                  color: preset === p.key ? "var(--color-accent)" : "var(--color-fg)",
                  background: preset === p.key ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 p-1" style={{ minWidth: 240 }}>
            <label className="flex items-center justify-between gap-3 text-[12px]" style={{ color: "var(--color-fg)" }}>
              <span>From</span>
              <input
                type="date"
                aria-label="From date"
                value={from ?? ""}
                min={minDay}
                max={to ?? maxDay}
                onChange={(e) => { if (isDay(e.target.value)) onChange(e.target.value, to); }}
                style={dateInputStyle}
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-[12px]" style={{ color: "var(--color-fg)" }}>
              <span>To</span>
              <input
                type="date"
                aria-label="To date"
                value={to ?? ""}
                min={from ?? minDay}
                max={maxDay}
                onChange={(e) => { if (isDay(e.target.value)) onChange(from, e.target.value); }}
                style={dateInputStyle}
              />
            </label>
          </div>
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #65, #66, #73: the Hour / Day / Week / Month toggle buttons, 28px, 6px by 8px, no gap and no strip. A choice the
 *  range rules out is disabled with the capture's tooltip (#28, #29). */
export function GranularityTabs({ name, pick, days, onPick }: {
  name: string; pick: Gran; days: number; onPick: (g: Gran) => void;
}) {
  const shown = granShown(pick, days);
  return (
    <div role="group" aria-label={name} className="flex">
      {GRANS.map(({ key, label }) => {
        const ok = granAllowed(key, days);
        const on = key === shown;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={on}
            disabled={!ok}
            title={ok ? undefined : GRAN_LIMIT[key]}
            onClick={() => onPick(key)}
            className="px-2 py-1.5 rounded-md min-h-7 text-sm font-medium leading-[1.1429] disabled:cursor-not-allowed"
            style={{
              // #16: toggle colours; a disabled one at the capture's 23.5% alpha on our token.
              color: !ok ? "color-mix(in srgb, var(--color-fg) 23.5%, transparent)" : on ? "var(--color-fg)" : "var(--color-fg-dim)",
              background: on ? "color-mix(in srgb, var(--color-fg) 5.5%, transparent)" : "transparent",
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

/** #27 to #29: Creator performance's "Shown by" select; a bucket the range rules out is disabled with the capture's
 *  tooltip. */
export function ShownBySelect({ value, days, onPick }: { value: Gran; days: number; onPick: (g: Gran) => void }) {
  return (
    <select
      aria-label="Shown by"
      value={value}
      onChange={(e) => onPick(e.target.value as Gran)}
      className={cn("rounded-md min-w-[140px]", FILTER_FIELD)}
      style={{ border: "1px solid var(--color-border)", background: "var(--color-bg-elev-1)", color: "var(--color-fg)" }}
    >
      {GRANS.map(({ key, label }) => {
        const ok = granAllowed(key, days);
        return (
          <option key={key} value={key} disabled={!ok} title={ok ? undefined : GRAN_LIMIT[key]}>
            {`Shown by ${label.toLowerCase()}`}
          </option>
        );
      })}
    </select>
  );
}

/** #71, #72: the Channels multi select, a funnel 5px from its text, clearable. */
export function ChannelsPill({ picked, onChange }: { picked: Set<Chan>; onChange: (next: Set<Chan>) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const names = CHANNELS.filter((c) => picked.has(c.key)).map((c) => c.label);
  const toggle = (key: Chan) => {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  };
  return (
    <div ref={ref} className="relative flex items-center gap-1">
      <PillTrigger open={open} ariaLabel="Channels" className={FILTER_FIELD} onClick={() => setOpen((v) => !v)}>
        <FilterFunnel size={16} className="mr-[5px]" aria-hidden />
        <span style={{ color: names.length ? "var(--color-fg)" : "var(--color-fg-dim)" }}>
          {names.length ? names.join(", ") : "Channels"}
        </span>
        <Chev />
      </PillTrigger>
      {names.length > 0 && (
        <button
          type="button"
          aria-label="Clear channels"
          onClick={() => onChange(new Set())}
          className="p-1 rounded-md"
          style={{ color: "var(--color-fg-dim)" }}
        >
          <X size={14} aria-hidden />
        </button>
      )}
      {open && (
        <PopoverBox anchor="left">
          <div className="flex flex-col">
            {CHANNELS.map((c) => (
              <label
                key={c.key}
                className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded cursor-pointer"
                style={{ color: "var(--color-fg)" }}
              >
                <input
                  type="checkbox"
                  checked={picked.has(c.key)}
                  onChange={() => toggle(c.key)}
                  style={{ accentColor: "var(--color-accent)" }}
                />
                <span className="w-2 h-2 rounded-full" style={{ background: c.color }} aria-hidden />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

export function FiltersPill({ models, selected, onChange }: {
  models: { id: string; name: string }[];
  selected: Set<string> | null;
  onChange: (next: Set<string> | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const isAll = selected === null;
  const count = isAll ? models.length : selected!.size;
  // #26: "Creator" until a pick; several picked read "creators selected".
  const label =
    isAll              ? "Creator" :
    count === 0        ? "No creators" :
    count === 1        ? models.find((m) => selected!.has(m.id))?.name ?? "1 creator selected" :
                         `${count} creators selected`;

  function toggle(id: string) {
    const next = new Set(isAll ? models.map((m) => m.id) : Array.from(selected!));
    if (next.has(id)) next.delete(id);
    else next.add(id);
    if (next.size === models.length) onChange(null);
    else onChange(next);
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <PillTrigger open={open} className={cn(FILTER_FIELD, "min-w-[140px] justify-between")} onClick={() => setOpen((v) => !v)}>
        <span>{label}</span>
        <Chev />
      </PillTrigger>
      {open && (
        <PopoverBox anchor="left">
          <div style={{ minWidth: 240, maxHeight: 320, overflowY: "auto" }} className="flex flex-col">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span className="text-[12px]" style={{ color: "var(--color-fg-dim)" }}>
                {isAll ? `All ${models.length} creators` : `${count}/${models.length} selected`}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="text-[11px]"
                  style={{ color: "var(--color-accent)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => onChange(null)}
                >
                  All
                </button>
                <button
                  type="button"
                  className="text-[11px]"
                  style={{ color: "var(--color-fg-dim)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => onChange(new Set())}
                >
                  None
                </button>
              </div>
            </div>
            <div style={{ borderTop: "1px solid var(--color-border)", marginBottom: 2 }} />
            {models.length === 0 ? (
              <div className="text-[12px] px-2 py-2" style={{ color: "var(--color-muted)" }}>No creators yet.</div>
            ) : models.map((m) => {
              const checked = isAll || selected!.has(m.id);
              return (
                <label
                  key={m.id}
                  className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded cursor-pointer"
                  style={{ color: "var(--color-fg)" }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(m.id)}
                    style={{ accentColor: "var(--color-accent)" }}
                  />
                  <span style={{ flex: 1 }}>{m.name}</span>
                </label>
              );
            })}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #105 to #107: "Custom metrics", opening "Creator report metrics": a checkbox per column in the capture's order,
 *  then ours, each labelled. */
export function CustomMetricsPill({ visible, onChange }: {
  visible: Set<string>; onChange: (next: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const headingId = useId();

  function toggle(key: string) {
    const next = new Set(visible);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }
  const linkBtn = "text-[11px] bg-transparent border-none p-0 cursor-pointer";

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 p-1.5 rounded-md text-sm"
        style={{ color: "var(--color-fg)" }}
      >
        Custom metrics
        <SlidersHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <PopoverBox anchor="right">
          <div role="group" aria-labelledby={headingId} style={{ minWidth: 260, maxHeight: 360, overflowY: "auto" }} className="flex flex-col">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span id={headingId} className="text-[12px] font-medium" style={{ color: "var(--color-fg)" }}>
                Creator report metrics
              </span>
              {/* Ours: the old picker's shortcuts. */}
              <div className="flex items-center gap-2" title={EXTRA_LABEL}>
                <button type="button" className={linkBtn} style={{ color: "var(--color-accent)" }} onClick={() => onChange(DEFAULT_COLS())}>
                  Default
                </button>
                <button type="button" className={linkBtn} style={{ color: "var(--color-accent)" }}
                  onClick={() => onChange(new Set(STAT_COLS.map((c) => c.key)))}>
                  All
                </button>
                <button type="button" className={linkBtn} style={{ color: "var(--color-fg-dim)" }} onClick={() => onChange(new Set())}>
                  None
                </button>
              </div>
            </div>
            <div style={{ borderTop: "1px solid var(--color-border)", marginBottom: 2 }} />
            {STAT_COLS.map((c) => (
              <label
                key={c.key}
                title={c.extra ? EXTRA_LABEL : c.v ? undefined : "not wired"}
                className="flex items-center gap-2 text-[12px] px-2 py-1.5 rounded cursor-pointer"
                style={{ color: c.v ? "var(--color-fg)" : "var(--color-fg-dim)" }}
              >
                <input
                  type="checkbox"
                  checked={visible.has(c.key)}
                  onChange={() => toggle(c.key)}
                  style={{ accentColor: "var(--color-accent)" }}
                />
                <span style={{ flex: 1 }}>{c.title}</span>
              </label>
            ))}
          </div>
        </PopoverBox>
      )}
    </div>
  );
}

/** #98 to #100: the "UTC+00:00" chip, 2px by 4px, 16px high, a pill, 10px weight 500. */
export function UtcChip() {
  return (
    <span
      className="inline-flex items-center ml-1 px-1 py-0.5 min-h-4 rounded-full text-[10px] font-medium leading-[1.2] align-middle"
      style={{ color: "var(--color-fg-dim)", background: "var(--color-bg-elev-2)" }}
    >
      UTC+00:00
    </span>
  );
}

const dateInputStyle: React.CSSProperties = {
  border: "1px solid var(--color-border)",
  borderRadius: 6,
  padding: "4px 6px",
  fontSize: 12,
  color: "var(--color-fg)",
  background: "var(--color-bg-elev-1)",
  outline: "none",
};

/* ───────── icons ───────── */

function Chev() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
      <path d="M6 9l6 6 6-6" className="stroke-fg-dim" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function CalIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ marginLeft: 6 }}>
      <rect x="3" y="5" width="18" height="16" rx="2" className="stroke-fg-dim" strokeWidth="1.6"/>
      <path d="M3 9h18M8 3v4M16 3v4" className="stroke-fg-dim" strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  );
}
