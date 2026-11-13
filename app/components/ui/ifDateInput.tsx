"use client";

/**
 * `IfDateInput`: a drop-in for `<input type="date" | "time" | "datetime-local">` that opens an Infloww-themed pop-over
 * (antd's DatePicker / TimePicker: a month grid, hour and minute columns, Today / Now, OK) instead of the browser's.
 * The native input stays, so the value string, typing a date, `min`/`max`/`required`/`step`, form posts and tests'
 * `fireEvent.change` are as before; a pick sets its value and fires `input`, so the call site's `onChange` runs with a
 * real event. The browser's picker icon is hidden and the theme's drawn (`.if-date`, globals.css; `bare` drops it, for a
 * box that leads with its own). The pop-over renders beside the input, fixed to the viewport, not in a portal: a
 * pop-over holding the input (a date-range popover) still sees clicks in it as inside. Touch screens keep the phone's
 * own picker.
 */

import {
  forwardRef, useCallback, useEffect, useLayoutEffect, useRef, useState, type InputHTMLAttributes,
} from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { IF_FIELD } from "@/components/ui/ifSelect";
import {
  clampValue, dayAllowed, dayKey, joinValue, minuteOptions, monthGrid, setTimePart, shiftMonth, splitValue, timeKey, type DateMode,
} from "@/components/ui/ifDateValue";
import { cn } from "@/lib/utils";

/** Set the input's value as the browser would and fire `input` + `change`; React's value tracker sees the change. */
function emit(el: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);
const CELL = "h-7 rounded text-[13px] tabular-nums";
const pad = (n: number) => String(n).padStart(2, "0");

/** `IfInput`'s field box (32px, `padding:0 11px`) on the input itself: a date field standing alone. */
export const IF_DATE_FIELD = cn(IF_FIELD, "h-8 px-[11px] outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-50");

export const IfDateInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  type: DateMode;
  /** No calendar / clock icon at the right (the surrounding box draws one). */
  bare?: boolean;
}>(({ type, bare, className, onClick, onKeyDown, onBlur, ...rest }, ref) => {
  const input = useRef<HTMLInputElement | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const setRef = useCallback((el: HTMLInputElement | null) => {
    input.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  }, [ref]);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState("");
  const [, rerender] = useState(0);

  const value = rest.value != null ? String(rest.value) : input.current?.value ?? "";
  const { day, time } = splitValue(type, value);
  const today = dayKey(new Date());

  const openPanel = () => {
    if (open || rest.disabled || rest.readOnly) return;
    if (window.matchMedia?.("(pointer: coarse)")?.matches) return; // the phone's own picker
    setMonth((splitValue(type, input.current?.value ?? value).day || today).slice(0, 7));
    setOpen(true);
  };
  const pick = (v: string, close: boolean) => {
    if (input.current) emit(input.current, clampValue(v, rest.min as string | undefined, rest.max as string | undefined));
    rerender((n) => n + 1);
    if (close) setOpen(false);
  };

  // Place the pop-over under the input (above when there is no room), inside the viewport; scroll the time columns
  // to the picked hour and minute.
  useLayoutEffect(() => {
    const el = input.current, box = panel.current;
    if (!open || !el || !box) return;
    const r = el.getBoundingClientRect();
    const below = r.bottom + 4;
    const top = below + box.offsetHeight > window.innerHeight - 8 && r.top - 4 - box.offsetHeight >= 8
      ? r.top - 4 - box.offsetHeight : below;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - box.offsetWidth - 8));
    // Still at 0,0: where it lands is the frame's offset (a transformed ancestor becomes the fixed box's frame). The
    // pop-in scales from the top-left corner, so that corner is exact mid-animation too.
    const frame = box.getBoundingClientRect();
    box.style.top = `${top - frame.top}px`;
    box.style.left = `${left - frame.left}px`;
    box.style.visibility = "visible";
    box.querySelectorAll<HTMLElement>("[data-col]").forEach((col) => {
      const sel = col.querySelector<HTMLElement>("[aria-pressed=true]");
      if (sel) col.scrollTop = sel.offsetTop - 4;
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const inside = (t: EventTarget | null) => t instanceof Node && (!!panel.current?.contains(t) || !!input.current?.contains(t));
    const outside = (e: PointerEvent) => { if (!inside(e.target)) setOpen(false); };
    const scroll = (e: Event) => { if (!inside(e.target)) setOpen(false); };
    const resize = () => setOpen(false);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]);

  const nowValue = joinValue(type, today, timeKey(new Date()));
  const btn = (key: string, label: string, onPick: () => void, cls: string, extra: Record<string, unknown> = {}) => (
    <button key={key} type="button" tabIndex={-1} onClick={onPick} className={cls} {...extra}>{label}</button>
  );

  const calendar = (
    <div className="w-[248px]">
      <div className="flex h-10 items-center justify-between border-b border-border px-2">
        <button type="button" tabIndex={-1} aria-label="Previous month" onClick={() => setMonth((m) => shiftMonth(m, -1))}
          className="grid h-7 w-7 place-items-center rounded text-muted hover:bg-bg-elev-2 hover:text-fg">
          <ChevronLeft aria-hidden className="h-4 w-4" />
        </button>
        <span className="font-medium">
          {month && new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1)
            .toLocaleString("en-US", { month: "short", year: "numeric" })}
        </span>
        <button type="button" tabIndex={-1} aria-label="Next month" onClick={() => setMonth((m) => shiftMonth(m, 1))}
          className="grid h-7 w-7 place-items-center rounded text-muted hover:bg-bg-elev-2 hover:text-fg">
          <ChevronRight aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-y-1 p-2">
        {WEEKDAYS.map((w) => <span key={w} className="grid h-7 place-items-center text-[12px] text-muted">{w}</span>)}
        {month && monthGrid(month).map((d) => {
          const ok = dayAllowed(d, rest.min as string | undefined, rest.max as string | undefined);
          return btn(d, String(Number(d.slice(8))), () => {
            if (d.slice(0, 7) !== month) setMonth(d.slice(0, 7));
            pick(joinValue(type, d, time), type === "date");
          }, cn(CELL, "mx-auto w-7",
            d.slice(0, 7) !== month && "text-muted",
            d === day ? "bg-accent text-white" : "hover:bg-bg-elev-2",
            d === today && d !== day && "ring-1 ring-inset ring-accent",
            !ok && "cursor-not-allowed opacity-30 hover:bg-transparent"),
          { "aria-label": d, "aria-pressed": d === day, disabled: !ok });
        })}
      </div>
    </div>
  );

  const column = (label: string, items: number[], part: "h" | "m") => (
    <div data-col aria-label={label} className="relative h-[232px] w-14 overflow-y-auto py-1 [scrollbar-width:thin]">
      {items.map((n) => {
        const sel = !!time && Number(time.slice(part === "h" ? 0 : 3, part === "h" ? 2 : 5)) === n;
        return btn(String(n), pad(n), () => pick(joinValue(type, day || today, setTimePart(time, part, n)), false),
          cn(CELL, "block w-full", sel ? "bg-selected font-medium text-fg" : "hover:bg-bg-elev-2"),
          { "aria-label": `${label} ${pad(n)}`, "aria-pressed": sel });
      })}
    </div>
  );

  const clock = (
    <div className={cn(type === "datetime-local" && "border-l border-border")}>
      <div className="flex h-10 items-center justify-center border-b border-border tabular-nums text-fg-dim">{time || "--:--"}</div>
      <div className="flex divide-x divide-border">
        {column("Hour", HOURS, "h")}
        {column("Minute", minuteOptions(rest.step), "m")}
      </div>
    </div>
  );

  return (
    <>
      <input
        ref={setRef}
        type={type}
        {...rest}
        className={cn("if-date", className, !bare && "if-date-icon pr-7")}
        onClick={(e) => { onClick?.(e); openPanel(); }}
        onKeyDown={(e) => {
          onKeyDown?.(e);
          if ((e.altKey && e.key === "ArrowDown") || e.key === "F4") { e.preventDefault(); openPanel(); }
          else if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); }
          else if (e.key === "Enter" && open) setOpen(false);
        }}
        onBlur={(e) => { onBlur?.(e); setOpen(false); }}
      />
      {open && (
        <div
          ref={panel}
          role="dialog"
          aria-label={type === "time" ? "Choose time" : "Choose date"}
          style={{ left: 0, top: 0, visibility: "hidden" }}
          onMouseDown={(e) => e.preventDefault()}
          className="pop-menu fixed z-[2000] origin-top-left overflow-hidden rounded-md border border-border bg-panel text-[14px] text-fg shadow-lg"
        >
          <div className="flex">
            {type !== "time" && calendar}
            {type !== "date" && clock}
          </div>
          <div className="flex h-10 items-center justify-between gap-4 border-t border-border px-3">
            {btn("now", type === "date" ? "Today" : "Now", () => pick(nowValue, type === "date"),
              "text-accent hover:text-accent-hover disabled:cursor-not-allowed disabled:opacity-40",
              { disabled: type !== "time" && !dayAllowed(today, rest.min as string | undefined, rest.max as string | undefined) })}
            {type !== "date" && btn("ok", "OK", () => setOpen(false),
              "h-6 rounded bg-accent px-2.5 text-[12px] text-white hover:bg-accent-hover")}
          </div>
        </div>
      )}
    </>
  );
});
IfDateInput.displayName = "IfDateInput";
