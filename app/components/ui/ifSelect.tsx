"use client";

/**
 * `infloww.tsx`'s selects (re-exported there): the shared `Listbox` (also `IfCreatorSelect`'s and `HbPager`'s),
 * `IfSelect`, `HbSelect` and the `HbFilter` boxes, plus the HB greys and the antd field box the other primitives share.
 */

import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";

import { useOutsideClose } from "@/components/ui/Menu";
import { cn } from "@/lib/utils";

/** An option of `IfSelect`, `HbSelect`, `IfTabs` and `IfSegmented`. `text` is what `searchable` filters on (the
 *  label when it is a string, else the value). `title` is a tab's tooltip (`IfTabs` only). */
export type IfOption<T extends string = string> = {
  value: T; label: ReactNode; text?: string; disabled?: boolean; title?: string;
};

// HB greys with no theme token: the sampled dark hex, then the light stand-in.
export const HB_TEXT = "text-white [html[data-theme=light]_&]:text-fg";
export const HB_DIM = "text-[#a3a3a3] [html[data-theme=light]_&]:text-fg-dim";
export const HB_FILL_1 = "bg-[#1a1a1a] [html[data-theme=light]_&]:bg-black/5";
export const HB_FILL_2 = "bg-[#232323] [html[data-theme=light]_&]:bg-black/5";
export const HB_FILL_3 = "bg-[#2c2c2c] [html[data-theme=light]_&]:bg-black/[.09]";
export const HB_HAIR = "border-white/[.09] [html[data-theme=light]_&]:border-black/[.09]";

export type IconProp = { icon?: LucideIcon };

// ── Listbox (shared by IfSelect, HbSelect, IfCreatorSelect) ──────────────────────────────────────────────────────

const optionText = (o: IfOption) => o.text ?? (typeof o.label === "string" ? o.label : o.value);

/**
 * A button that opens a listbox: Enter, Space or the arrows open it, the arrows move, Enter picks, Escape or Tab
 * closes, an outside click closes. Focus stays on the button (`aria-activedescendant`), or on the filter box when
 * `searchable`.
 */
export function Listbox<T extends string>({
  value, options, onChange, renderValue, placeholder, searchable, disabled, id, ariaLabel, ariaDescribedby,
  className, triggerClassName, menuClassName, chevronClassName, openUp,
}: {
  value: T | null | undefined;
  options: IfOption<T>[];
  onChange: (value: T) => void;
  renderValue?: (option: IfOption<T> | undefined) => ReactNode;
  placeholder?: string;
  searchable?: boolean;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
  ariaDescribedby?: string;
  className?: string;
  triggerClassName: string;
  menuClassName: string;
  chevronClassName?: string;
  /** Open the menu above the trigger (a control at the page foot), not below. */
  openUp?: boolean;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  const [active, setActive] = useState(0);
  const [query, setQuery] = useState("");
  const listId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selected = options.find((o) => o.value === value);
  const q = query.trim().toLowerCase();
  const shown = searchable && q ? options.filter((o) => optionText(o).toLowerCase().includes(q)) : options;

  const openMenu = () => {
    if (disabled) return;
    setQuery("");
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };
  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };
  const pick = (o: IfOption<T> | undefined) => {
    if (!o || o.disabled) return;
    onChange(o.value);
    close();
  };
  const move = (by: number) => {
    if (!shown.length) return;
    setActive((i) => (Math.min(i, shown.length - 1) + by + shown.length) % shown.length);
  };

  const onKey = (e: ReactKeyboardEvent) => {
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); openMenu(); }
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter" || (e.key === " " && !searchable)) { e.preventDefault(); pick(shown[active]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") close(false);
  };

  const optionId = (i: number) => `${listId}-${i}`;
  return (
    <div ref={ref} className={cn("relative inline-block", className)}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && !searchable && shown[active] ? optionId(active) : undefined}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedby}
        disabled={disabled}
        onClick={() => (open ? close(false) : openMenu())}
        onKeyDown={onKey}
        className={cn("flex w-full items-center gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50", triggerClassName)}
      >
        <span className={cn("min-w-0 flex-1 truncate", !selected && "text-muted")}>
          {renderValue ? renderValue(selected) : selected?.label ?? placeholder}
        </span>
        <ChevronDown aria-hidden className={cn("h-3 w-3 shrink-0 text-muted transition-transform", open && "rotate-180", chevronClassName)} />
      </button>
      {open && (
        <div className={cn("absolute left-0 z-50 min-w-full overflow-hidden rounded-md py-1 shadow-lg",
          openUp ? "bottom-full mb-1" : "top-full mt-1", menuClassName)}>
          {searchable && (
            <div className="px-2 pb-1">
              <input
                autoFocus
                aria-label="Search"
                aria-controls={listId}
                aria-activedescendant={shown[active] ? optionId(active) : undefined}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setActive(0); }}
                onKeyDown={onKey}
                className="h-7 w-full rounded border border-border bg-transparent px-2 text-[14px] text-fg outline-none placeholder:text-muted focus:border-accent"
                placeholder="Search"
              />
            </div>
          )}
          <ul role="listbox" id={listId} aria-label={ariaLabel} className="max-h-64 overflow-y-auto">
            {shown.map((o, i) => (
              <li
                key={o.value}
                id={optionId(i)}
                role="option"
                aria-selected={o.value === value}
                aria-disabled={o.disabled || undefined}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(o)}
                className={cn(
                  "flex h-8 cursor-pointer items-center gap-2 whitespace-nowrap px-3 text-[14px] text-fg",
                  i === active && "bg-bg-elev-2",
                  o.value === value && "font-medium text-accent",
                  o.disabled && "cursor-not-allowed opacity-50",
                )}
              >
                {o.label}
              </li>
            ))}
            {!shown.length && <li className="px-3 py-2 text-[14px] text-muted">No data</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

type SelectProps<T extends string> = {
  value: T | null | undefined;
  options: IfOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  /** A filter box at the top of the menu (type to narrow; time zones, creators). */
  searchable?: boolean;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  /** Width and placement; the trigger fills it. */
  className?: string;
};

/** The antd field box: 1px L1, radius 6, B-nav fill, 14px T1; 32px (the Dashboard's `lg` 36px). */
export const IF_FIELD = "rounded-md border border-border bg-bg text-[14px] text-fg hover:border-accent";

/** antd's select (button + listbox): 32px, `padding:0 11px`, a 12px T3 chevron; `size="lg"` is the Dashboard's 36px
 *  "Net earnings" with T2 text. The menu is the panel colour, 32px items. */
export function IfSelect<T extends string>({ size = "md", ...p }: SelectProps<T> & { size?: "md" | "lg" }) {
  return (
    <Listbox
      {...p}
      ariaLabel={p["aria-label"]}
      ariaDescribedby={p["aria-describedby"]}
      triggerClassName={cn(IF_FIELD, "px-[11px]", size === "lg" ? "h-9 text-fg-dim" : "h-8")}
      menuClassName="border border-border bg-panel"
    />
  );
}

/** HB's filter field, as a class string: filled #161616, no border, 28px, radius 4, 14px text, #a6a6a6 placeholder.
 *  Put it on an `<input>`; `HbSelect` is the select built on it. */
export const HbFilter =
  "h-7 rounded-[4px] border-0 bg-[#161616] px-3 text-[14px] text-fg placeholder:text-[#a6a6a6] outline-none " +
  "focus-visible:ring-1 focus-visible:ring-border-light [html[data-theme=light]_&]:bg-black/5";

/** HB's filter at Tracking links' 36px: radius 8, 16px text (its filter bar, #17-#22). */
export const HbFilterLg = cn(HbFilter, "h-9 rounded-lg text-[16px]");

/** HB's select: the `HbFilter` box with the chevron at the right, a panel-coloured menu. `size="lg"` is the 36px
 *  `HbFilterLg`; `icon` leads the trigger (Tracking links' Source and Tag), not the menu's options. */
export function HbSelect<T extends string>({ size = "md", icon: Icon, ...p }: SelectProps<T> & IconProp & { size?: "md" | "lg" }) {
  return (
    <Listbox
      {...p}
      ariaLabel={p["aria-label"]}
      ariaDescribedby={p["aria-describedby"]}
      triggerClassName={size === "lg" ? HbFilterLg : HbFilter}
      chevronClassName="h-4 w-4 text-[#a6a6a6]"
      menuClassName={cn("border bg-panel", HB_HAIR)}
      renderValue={Icon ? (o) => (
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-fg" aria-hidden />
          <span className={cn("truncate", !o && "text-[#a6a6a6]")}>{o?.label ?? p.placeholder}</span>
        </span>
      ) : undefined}
    />
  );
}
