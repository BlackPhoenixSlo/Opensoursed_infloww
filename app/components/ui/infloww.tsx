"use client";

/**
 * Infloww's own page primitives (page-parity ticket 00), built once so every page ticket swaps its hand-rolled copy
 * for one of these. Two sets, because Infloww ships two design systems side by side:
 *
 * - The legacy antd set (`--tc-*` tokens): `InflowwPageHeader`, `IfCard`, `IfTabs`, `IfBody`, `IfInput`, `IfTextArea`,
 *   `IfSelect`, `IfSegmented`, `IfRangePicker`, `IfButton`, `IfLearn`, `IfCreatorSelect` (+ `useCreatorParam`),
 *   `IfModal`, `IfPager`, `IfSwitch`, `IF_TABLE`. Most Growth pages, the Dashboard, Employees, Custom proxy.
 * - The HB set (the new design system): `HbButton`, `HbFilter`/`HbSelect`, `HB_TABLE`, `HbPager`, `HbModal`, on the
 *   `bg-hb-bg` page body. Manage creators, Tracking links.
 *
 * `EmptyState` serves both. Measurements: `.scratch/page-parity/00-shared-infloww-primitives.md` §3 (live captures
 * `.scratch/infloww-live/16-dashboard.png`, `01-home.png`; the bundle's `index.9fc9db54.css`). Dark values are the
 * sampled ones; light values ride on the theme tokens, or on a `[html[data-theme=light]_&]:` override where a sampled
 * dark hex has no token.
 */

import {
  forwardRef, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore,
  type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type TextareaHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowRight, BookOpen, Calendar, ChevronDown, ChevronLeft, ChevronRight, Info, Loader2, Search, X,
  type LucideIcon,
} from "lucide-react";

import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { useOutsideClose } from "@/components/ui/Menu";
import { EmptyArt, type EmptyKind } from "@/components/ui/emptyArt";
import { useExitGhost } from "@/hooks/useExitGhost";
import type { AccountMeta } from "@/lib/relay";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";

export type { EmptyKind } from "@/components/ui/emptyArt";

/** An option of `IfSelect`, `HbSelect`, `IfTabs` and `IfSegmented`. `text` is what `searchable` filters on (the
 *  label when it is a string, else the value). `title` is a tab's tooltip (`IfTabs` only). */
export type IfOption<T extends string = string> = {
  value: T; label: ReactNode; text?: string; disabled?: boolean; title?: string;
};

// HB greys with no theme token: the sampled dark hex, then the light stand-in.
const HB_TEXT = "text-white [html[data-theme=light]_&]:text-fg";
const HB_DIM = "text-[#a3a3a3] [html[data-theme=light]_&]:text-fg-dim";
const HB_FILL_1 = "bg-[#1a1a1a] [html[data-theme=light]_&]:bg-black/5";
const HB_FILL_2 = "bg-[#232323] [html[data-theme=light]_&]:bg-black/5";
const HB_FILL_3 = "bg-[#2c2c2c] [html[data-theme=light]_&]:bg-black/[.09]";
const HB_HAIR = "border-white/[.09] [html[data-theme=light]_&]:border-black/[.09]";

// ── Page header ─────────────────────────────────────────────────────────────────────────────────────────────────

/** "UTC-09:00 ⓘ": the report time zone after a title (16-dashboard.png title row; dashboard.md #16-#19). */
function UtcLabel({ zone }: { zone: string | null }) {
  return (
    <span className="flex shrink-0 items-center gap-1 text-[14px] text-fg-dim tabular-nums">
      <span suppressHydrationWarning>{utcOffsetLabel(zone)}</span>
      <span role="img" aria-label="Set by your organization" title="Set by your organization" className="cursor-help">
        <Info className="h-3.5 w-3.5" aria-hidden />
      </span>
    </span>
  );
}

/**
 * Infloww's `PageHeader$1`: a 48px bar, `padding:0 24px`, the page colour with a 1px L1 rule under it, the one `<h1>`
 * at 16px / 600 T1. `extra` sits 24px right of the title (a creator select, a note); `actions` (and `children`, the
 * same slot) sit right-aligned in the same row, 16px apart.
 */
export function InflowwPageHeader({
  title, utc, extra, actions, children, weight = "semibold", onBack, className,
}: {
  title: ReactNode;
  /** The report time zone id; `null` = the browser's zone; leave it out to show none. */
  utc?: string | null;
  extra?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  /** `medium` = 16 / 500, the few pages whose title CSS says so (Sensitive words). */
  weight?: "semibold" | "medium";
  /** Draws a back chevron before the title (Notifications). */
  onBack?: () => void;
  className?: string;
}) {
  const right = actions || children;
  return (
    <header className={cn("flex h-12 shrink-0 items-center justify-between gap-4 border-b border-border bg-bg px-6", className)}>
      <div className="flex min-w-0 items-center gap-6">
        <div className="flex min-w-0 items-center gap-3">
          {onBack && (
            <button type="button" aria-label="Back" onClick={onBack}
              className="-ml-1 grid h-6 w-6 shrink-0 place-items-center text-fg-dim hover:text-accent">
              <ChevronLeft className="h-5 w-5" aria-hidden />
            </button>
          )}
          <h1 className={cn("truncate text-[16px] text-fg", weight === "medium" ? "font-medium" : "font-semibold")}>
            {title}
          </h1>
          {utc !== undefined && <UtcLabel zone={utc} />}
        </div>
        {extra}
      </div>
      {right && <div className="flex shrink-0 items-center gap-4">{actions}{children}</div>}
    </header>
  );
}

/** The legacy list-page body under the header (or the tabs): `padding:16px 24px`. */
export function IfBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 py-4", className)} {...rest} />;
}

// ── Empty state ─────────────────────────────────────────────────────────────────────────────────────────────────

const ART_HEIGHT = { sm: 40, md: 90, lg: 100 } as const;

/**
 * Infloww's `Empty$1` (`._empty-wrap_1iayr_1 img{height:100px;margin-bottom:8px}`, text T3): the illustration, 8px,
 * then a 14px #999 line, centred. `size="sm"` is the antd table's simple empty (40px art, 32px above and below);
 * `md` the 90px art Sensitive words uses. `kind="error"` with `onRetry` adds `AbnormalRequestError`'s primary "Retry"
 * 10px below; `action` puts any other button there. `data-empty-state` names it for slop's page sweep (an empty state
 * on screen before a page's first read answered is a false one).
 */
export function EmptyState({
  kind = "data", text = "No data", onRetry, action, size = "lg", className, textClassName,
}: {
  kind?: EmptyKind;
  text?: ReactNode;
  onRetry?: () => void;
  action?: ReactNode;
  size?: keyof typeof ART_HEIGHT;
  className?: string;
  textClassName?: string;
}) {
  return (
    <div data-empty-state={kind} className={cn("flex flex-col items-center justify-center text-center", size === "sm" && "py-8", className)}>
      <EmptyArt kind={kind} height={ART_HEIGHT[size]} />
      <p className={cn("text-[14px] text-muted", size === "md" ? "mt-2.5" : "mt-2", textClassName)}>{text}</p>
      {kind === "error" && onRetry && (
        <IfButton variant="primary" className="mt-2.5" onClick={onRetry}>Retry</IfButton>
      )}
      {action && <div className="mt-2.5">{action}</div>}
    </div>
  );
}

// ── Card ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A legacy page card: #262626, 12px corners, no border, `padding:20px 24px 16px`; the title 16px / 500 white with
 *  an optional ⓘ 9px after it, and `extra` at the title row's right. `Card` stays for our own panels. */
export function IfCard({
  title, info, extra, className, children, ...rest
}: Omit<HTMLAttributes<HTMLElement>, "title"> & { title?: ReactNode; info?: string; extra?: ReactNode }) {
  return (
    <section className={cn("rounded-[12px] bg-bg-elev-1 px-6 pb-4 pt-5", className)} {...rest}>
      {(title || extra) && (
        <div className="flex items-center justify-between gap-3">
          <h2 className={cn("flex items-center text-[16px] font-medium", HB_TEXT)}>
            {title}
            {info && (
              <span role="img" aria-label={info} title={info} className="ml-[9px] cursor-help text-fg-dim">
                <Info className="h-3.5 w-3.5" aria-hidden />
              </span>
            )}
          </h2>
          {extra}
        </div>
      )}
      {children}
    </section>
  );
}

// ── Buttons ─────────────────────────────────────────────────────────────────────────────────────────────────────

type IconProp = { icon?: LucideIcon };

/** antd's button: 32px (`lg` 36px), radius 6, 14px, `padding:0 15px`, an icon 8px before the label. `primary` M1 fill
 *  and white text; `default` a 1px L1 outline, T1 text, transparent; `link` M1 text only. */
export const IfButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & IconProp & { variant?: "primary" | "default" | "link"; size?: "md" | "lg" }
>(({ variant = "default", size = "md", icon: Icon, className, children, type = "button", ...rest }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-[14px] transition-colors",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
      "disabled:cursor-not-allowed disabled:opacity-50",
      size === "lg" ? "h-9" : "h-8",
      variant === "primary" && "bg-accent px-[15px] text-white hover:bg-accent-hover",
      variant === "default" && "border border-border bg-transparent px-[15px] text-fg hover:border-accent hover:text-accent",
      variant === "link" && "px-0 text-accent hover:text-accent-hover",
      className,
    )}
    {...rest}
  >
    {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
    {children}
  </button>
));
IfButton.displayName = "IfButton";

const LEARN = "inline-flex items-center gap-1 text-[14px] text-accent hover:text-accent-hover";

/** The header's "Learn" link: a 16px book, then 14px M1 text, to the help article (new tab). With no `href`: `tip`
 *  makes it a button that opens the help text in a popover under it (Escape or an outside click closes it); with
 *  neither it is a disabled button titled "not wired", at half opacity but never grey. */
export function IfLearn({ href, tip, children = "Learn", className }: {
  href?: string;
  tip?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const { open, setOpen, ref } = useOutsideClose<HTMLSpanElement>();
  const tipId = useId();
  const body = <><BookOpen className="h-4 w-4" aria-hidden />{children}</>;
  if (href) {
    return <a href={href} target="_blank" rel="noreferrer" className={cn(LEARN, className)}>{body}</a>;
  }
  if (!tip) {
    return (
      <button type="button" disabled title="not wired"
        className={cn(LEARN, "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:text-accent", className)}>
        {body}
      </button>
    );
  }
  return (
    <span ref={ref} className="relative inline-flex">
      <button type="button" aria-expanded={open} aria-controls={open ? tipId : undefined} onClick={() => setOpen(!open)}
        onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); } }}
        className={cn(LEARN, className)}>
        {body}
      </button>
      {open && (
        <span id={tipId} role="note"
          className="absolute right-0 top-full z-50 mt-2 w-[320px] max-w-[calc(100vw-32px)] rounded-md border border-border bg-panel p-3 text-[14px] leading-[22px] text-fg shadow-lg">
          {tip}
        </span>
      )}
    </span>
  );
}

/** HB's button: `primary` the orange action fill with black text, `secondary` #2c2c2c with white; 36px (`sm` 28px),
 *  radius 4, 14px / 500, a 16px leading icon. `lg` is Manage creators' "Add creator": 36px, 16px text, radius 8. */
export const HbButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & IconProp & { variant?: "primary" | "secondary"; size?: "sm" | "md" | "lg" }
>(({ variant = "primary", size = "md", icon: Icon, className, children, type = "button", ...rest }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap font-medium transition-opacity",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta/50",
      "disabled:cursor-not-allowed disabled:opacity-50",
      size === "sm" && "h-7 rounded-[4px] px-3 text-[14px]",
      size === "md" && "h-9 rounded-[4px] px-4 text-[14px]",
      size === "lg" && "h-9 rounded-lg px-4 text-[16px]",
      variant === "primary" ? "bg-cta text-black hover:opacity-90" : cn(HB_FILL_3, HB_TEXT, "hover:opacity-90"),
      className,
    )}
    {...rest}
  >
    {Icon && <Icon className="h-4 w-4" aria-hidden />}
    {children}
  </button>
));
HbButton.displayName = "HbButton";

// ── Listbox (shared by IfSelect, HbSelect, IfCreatorSelect) ──────────────────────────────────────────────────────

const optionText = (o: IfOption) => o.text ?? (typeof o.label === "string" ? o.label : o.value);

/**
 * A button that opens a listbox: Enter, Space or the arrows open it, the arrows move, Enter picks, Escape or Tab
 * closes, an outside click closes. Focus stays on the button (`aria-activedescendant`), or on the filter box when
 * `searchable`.
 */
function Listbox<T extends string>({
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

// ── Legacy fields ───────────────────────────────────────────────────────────────────────────────────────────────

/** The antd field box: 1px L1, radius 6, B-nav fill, 14px T1; 32px (the Dashboard's `lg` 36px). */
const IF_FIELD = "rounded-md border border-border bg-bg text-[14px] text-fg hover:border-accent";

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

/** antd's input at 32px (`size="lg"` 36px); `search` draws the 14px search icon at the right. `className` sizes the
 *  box (`w-[320px]`); the input fills it. */
export const IfInput = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "size"> & { size?: "md" | "lg"; search?: boolean }
>(({ size = "md", search, className, ...rest }, ref) => (
  <span className={cn(IF_FIELD, "relative inline-flex items-center focus-within:border-accent", size === "lg" ? "h-9" : "h-8", className)}>
    <input
      ref={ref}
      className={cn("h-full w-full min-w-0 bg-transparent px-[11px] outline-none placeholder:text-muted", search && "pr-8")}
      {...rest}
    />
    {search && <Search aria-hidden className="pointer-events-none absolute right-[11px] h-3.5 w-3.5 text-muted" />}
  </span>
));
IfInput.displayName = "IfInput";

/** antd's TextArea: the same field box as `IfInput`, `padding:4px 11px`, drag-resizable in height. `className` sizes
 *  it (full width by default). */
export const IfTextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...rest }, ref) => (
    <textarea
      ref={ref}
      className={cn(IF_FIELD, "block w-full resize-y px-[11px] py-1 outline-none placeholder:text-muted focus:border-accent", className)}
      {...rest}
    />
  ),
);
IfTextArea.displayName = "IfTextArea";

/** antd's date range (250x32): "Start date → End date" with a calendar icon at the right, as one box (a `group`). Two
 *  native date inputs inside, transparent; an empty end that has no focus is a text box showing antd's 12px T3
 *  placeholder (a date box would show "mm/dd/yyyy"); a click opens the browser's picker (no custom calendar). Emits
 *  both ends together. `id` goes on the first end, for a `<label htmlFor>`; `disabled` (with `title`, "not wired")
 *  dims the box and needs no `onChange`. */
export function IfRangePicker({ from = "", to = "", onChange, id, disabled, title, className }: {
  from?: string;
  to?: string;
  onChange?: (range: { from: string; to: string }) => void;
  id?: string;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  const [focused, setFocused] = useState<"from" | "to" | null>(null);
  const field = (v: string) => cn(
    "h-full w-0 min-w-0 flex-1 bg-transparent text-[14px] outline-none [color-scheme:inherit] placeholder:text-[12px] placeholder:text-muted",
    "[&::-webkit-calendar-picker-indicator]:hidden disabled:cursor-not-allowed",
    v ? "text-fg" : "text-muted",
  );
  const openPicker = (e: ReactMouseEvent<HTMLInputElement>) => {
    try { e.currentTarget.showPicker?.(); } catch { /* not allowed (jsdom, cross-origin frame) */ }
  };
  const end = (which: "from" | "to", v: string) => ({
    type: v || focused === which ? "date" : "text",
    value: v,
    disabled,
    title,
    placeholder: which === "from" ? "Start date" : "End date",
    onFocus: () => setFocused(which),
    onBlur: () => setFocused(null),
    onClick: openPicker,
    className: field(v),
  });
  return (
    <span role="group" className={cn(IF_FIELD, "inline-flex h-8 w-[250px] items-center gap-2 px-[11px] focus-within:border-accent",
      disabled && "opacity-50 hover:border-border", className)}>
      <input id={id} aria-label="Start date" max={to || undefined} {...end("from", from)}
        onChange={(e) => onChange?.({ from: e.target.value, to })} />
      <ArrowRight aria-hidden className="h-3 w-3 shrink-0 text-muted" />
      <input aria-label="End date" min={from || undefined} {...end("to", to)}
        onChange={(e) => onChange?.({ from, to: e.target.value })} />
      <Calendar aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted" />
    </span>
  );
}

/** antd's segmented radio strip: #262626 with a 1px L1 border, 4px padding, radius 4; 24px tabs, 12px T2, the active
 *  one #353535 with M1 text (the Dashboard's period tabs). */
export function IfSegmented<T extends string>({ options, value, onChange, "aria-label": ariaLabel, className }: {
  options: IfOption<T>[];
  value: T;
  onChange: (value: T) => void;
  "aria-label"?: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel}
      className={cn("inline-flex rounded-[4px] border border-border bg-bg-elev-1 p-1", className)}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-6 whitespace-nowrap rounded-[4px] px-5 text-[12px] transition-colors disabled:opacity-50",
            o.value === value ? "bg-bg-elev-2 text-accent" : "text-fg-dim hover:text-fg",
          )}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** antd's line tabs: a 48px full-width bar with an L1 rule, the first tab 24px in, 32px between, 14px T1; the active
 *  tab M1 with a 2px M1 underline; a disabled tab T4, `aria-disabled`, its `title` the tooltip. The arrows move focus along the strip, Enter / Space picks (the native button
 *  click), Home / End jump. `extra` sits at the bar's right (Shifts' "Create shift(s)"). */
export function IfTabs<T extends string>({ tabs, value, onChange, extra, idPrefix, "aria-label": ariaLabel, className }: {
  tabs: IfOption<T>[];
  value: T;
  onChange: (value: T) => void;
  extra?: ReactNode;
  /** Gives each tab the id `<idPrefix>-tab-<value>` and `aria-controls="<idPrefix>-panel-<value>"`, so the caller's
   *  `role="tabpanel"` (id `<idPrefix>-panel-<value>`) can point back with `aria-labelledby`. */
  idPrefix?: string;
  "aria-label"?: string;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  // The Tab stop: the selected tab, or the first when `value` names none.
  const stop = tabs.some((t) => t.value === value) ? value : tabs[0]?.value;
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const btns = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)') ?? []);
    const at = btns.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    const to = e.key === "ArrowRight" ? (at + 1) % btns.length
      : e.key === "ArrowLeft" ? (at - 1 + btns.length) % btns.length
        : e.key === "Home" ? 0
          : e.key === "End" ? btns.length - 1
            : -1;
    if (to < 0) return;
    e.preventDefault();
    btns[to].focus();
  };
  return (
    <div className={cn("flex h-12 shrink-0 items-center gap-4 border-b border-border px-6", className)}>
      <div ref={listRef} role="tablist" aria-label={ariaLabel} onKeyDown={onKey} className="flex h-full min-w-0 gap-8 overflow-x-auto">
        {tabs.map((t) => {
          const on = t.value === value;
          return (
            <button key={t.value} type="button" role="tab" aria-selected={on} tabIndex={t.value === stop ? 0 : -1} disabled={t.disabled}
              id={idPrefix && `${idPrefix}-tab-${t.value}`} aria-controls={idPrefix && `${idPrefix}-panel-${t.value}`}
              aria-disabled={t.disabled || undefined} title={t.title}
              onClick={() => onChange(t.value)}
              className={cn(
                "relative h-full shrink-0 whitespace-nowrap text-[14px] transition-colors",
                "disabled:cursor-not-allowed disabled:text-border-light",
                "focus-visible:outline-none focus-visible:text-accent",
                on ? "text-accent after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-accent" : "text-fg hover:text-accent",
              )}>
              {t.label}
            </button>
          );
        })}
      </div>
      {extra && <div className="ml-auto flex shrink-0 items-center gap-4">{extra}</div>}
    </div>
  );
}

/** antd's switch: a 44x22 track, an 18px white knob 2px in; on #2d74ff, off white at 25%; disabled (and `loading`)
 *  at .65 opacity, `loading` spinning a 14px loader in the knob; the label 16px after it. Space / Enter toggles. */
export function IfSwitch({ checked, onChange, label, loading, disabled, "aria-label": ariaLabel, className }: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}) {
  const off = disabled || loading;
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={ariaLabel} aria-busy={loading || undefined}
      disabled={off} onClick={() => onChange(!checked)}
      className={cn("inline-flex items-center gap-4 text-left disabled:cursor-not-allowed", className)}>
      <span aria-hidden className={cn(
        "relative h-[22px] w-11 shrink-0 rounded-full transition-colors",
        checked ? "bg-[#2d74ff]" : "bg-white/25 [html[data-theme=light]_&]:bg-black/25",
        off && "opacity-[.65]",
      )}>
        <span className={cn(
          "absolute top-[2px] grid h-[18px] w-[18px] place-items-center rounded-full bg-white transition-[left]",
          checked ? "left-6" : "left-[2px]",
        )}>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-[#2d74ff]" />}
        </span>
      </span>
      {label && <span className="text-[14px] text-fg">{label}</span>}
    </button>
  );
}

// ── Creator select + ?creator= ──────────────────────────────────────────────────────────────────────────────────

const creatorName = (a: AccountMeta) => a.nickname || a.name || a.id;

/** A 20px creator avatar with the online dot (a live session) at its foot. */
function CreatorAvatar({ account }: { account: AccountMeta }) {
  const online = !!account.has_session && !account.session_dead_at;
  return (
    <span className="relative h-5 w-5 shrink-0">
      <span className="block h-5 w-5 overflow-hidden rounded-full">
        <AccountAvatarPicture account={account} letters={1} initialClassName="text-[10px] font-medium" />
      </span>
      {online && <span data-online className="absolute -bottom-px -right-px h-1.5 w-1.5 rounded-full bg-ok ring-1 ring-[#1e1e1e]" />}
    </span>
  );
}

/** The `IfCreatorSelect` value of its "All creators" option (no account id is empty). */
const ALL_CREATORS = "";

/** The legacy header's creator picker: 160x32 on `--tc-select-creator-b` #1E1E1E, a 20px avatar with the online dot,
 *  the name, a chevron. Pair it with `useCreatorParam` so the page body reads the same pick. `onAll` adds "All
 *  creators" first, picked while `value` is null. */
export function IfCreatorSelect({ accounts, value, onChange, onAll, searchable, disabled, className }: {
  accounts: AccountMeta[];
  value: string | null | undefined;
  onChange: (accountId: string) => void;
  onAll?: () => void;
  searchable?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const all: IfOption[] = onAll ? [{ value: ALL_CREATORS, text: "All creators", label: "All creators" }] : [];
  const options: IfOption[] = [...all, ...accounts.map((a) => ({
    value: a.id,
    text: creatorName(a),
    label: (
      <>
        <CreatorAvatar account={a} />
        <span className="truncate">{creatorName(a)}</span>
      </>
    ),
  }))];
  return (
    <Listbox
      value={onAll ? value ?? ALL_CREATORS : value}
      options={options}
      onChange={(v) => (onAll && v === ALL_CREATORS ? onAll() : onChange(v))}
      searchable={searchable}
      disabled={disabled}
      ariaLabel="Creator"
      placeholder="No creators"
      className={cn("w-[160px]", className)}
      triggerClassName="h-8 rounded-md bg-[#1e1e1e] px-2 text-[14px] text-fg [html[data-theme=light]_&]:bg-bg-elev-1"
      menuClassName="border border-border bg-panel"
      renderValue={(o) => {
        if (o?.value === ALL_CREATORS && onAll) return "All creators";
        const a = o && byId.get(o.value);
        return a ? (
          <span className="flex min-w-0 items-center gap-2">
            <CreatorAvatar account={a} />
            <span className="truncate">{creatorName(a)}</span>
          </span>
        ) : "No creators";
      }}
    />
  );
}

const subscribePopstate = (cb: () => void) => {
  window.addEventListener("popstate", cb);
  return () => window.removeEventListener("popstate", cb);
};
const readCreatorParam = () => new URLSearchParams(window.location.search).get("creator");

/**
 * The page's creator, in `?creator=<account_id>`, so a header picker and the page body share the pick without lifting
 * state. An unknown or missing id falls back to the first account (null while there are none); a pick writes the URL
 * with `router.replace` (no history entry). Reads `window.location` rather than `useSearchParams`, which would make
 * every caller grow a `<Suspense>` boundary (see `useTabParam`); the server render reads no param.
 */
export function useCreatorParam(accounts: AccountMeta[] | undefined): [string | null, (accountId: string) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const fromUrl = useSyncExternalStore(subscribePopstate, readCreatorParam, () => null);
  const [picked, setPicked] = useState<string | null>(null);
  const list = accounts ?? [];
  const want = picked ?? fromUrl;
  const id = want && list.some((a) => a.id === want) ? want : list[0]?.id ?? null;
  const set = useCallback((accountId: string) => {
    setPicked(accountId);
    const params = new URLSearchParams(window.location.search);
    params.set("creator", accountId);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [router, pathname]);
  return [id, set];
}

// ── Pagers ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** antd's page items: every page up to 7, else the first, the last, and two either side of the current, with "…". */
function pageItems(page: number, pages: number): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const start = Math.max(2, Math.min(page - 2, pages - 5));
  const end = Math.min(pages - 1, Math.max(page + 2, 6));
  const out: (number | "…")[] = [1];
  if (start > 2) out.push("…");
  for (let i = start; i <= end; i++) out.push(i);
  if (end < pages - 1) out.push("…");
  out.push(pages);
  return out;
}

const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(total / Math.max(1, size)));

/** The page buttons both pagers share; `item(current)` styles one page box. */
function PageButtons({ page, pages, onPage, arrow, item }: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  arrow: string;
  item: (current: boolean) => string;
}) {
  return (
    <>
      <button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} className={arrow}>
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
      </button>
      {pageItems(page, pages).map((p, i) => p === "…" ? (
        <span key={`gap-${i}`} aria-hidden className="px-1 text-muted">…</span>
      ) : (
        <button key={p} type="button" aria-label={`Page ${p}`} aria-current={p === page ? "page" : undefined}
          onClick={() => p !== page && onPage(p)} className={item(p === page)}>
          {p}
        </button>
      ))}
      <button type="button" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)} className={arrow}>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </>
  );
}

/** antd's pagination, left-aligned: "Total: N records" 14px T1, then prev / pages / next, 32px items 8px apart, radius
 *  6; the current page a 1px M1 outline and M1 text; disabled arrows T4. No size changer. */
export function IfPager({ total, noun = "records", page, size, onPage, className }: {
  total: number;
  noun?: string;
  page: number;
  size: number;
  onPage: (page: number) => void;
  className?: string;
}) {
  return (
    <nav aria-label="Pagination" className={cn("flex flex-wrap items-center gap-2 text-[14px] text-fg", className)}>
      <span className="mr-1">Total: {total} {noun}</span>
      <PageButtons
        page={page}
        pages={pageCount(total, size)}
        onPage={onPage}
        arrow="grid h-8 w-8 place-items-center rounded-md text-fg hover:bg-bg-elev-2 disabled:bg-transparent disabled:text-border-light disabled:cursor-not-allowed"
        item={(on) => cn("h-8 min-w-8 rounded-md px-1.5", on ? "border border-accent text-accent" : "text-fg hover:bg-bg-elev-2")}
      />
    </nav>
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

/** HB's pager footer: a 1px #232323 rule above; "Total: N creators" #a3a3a3, prev / next 28px boxes on #232323, the
 *  current page a #1a1a1a box with a white digit; then "Per page" and the size select (#1a1a1a, 10 / 20 / 50). Pin
 *  it to the page foot with the caller's layout. */
export function HbPager({ total, noun, page, size, sizes = [10, 20, 50], onPage, onSize, className }: {
  total: number;
  noun: string;
  page: number;
  size: number;
  sizes?: number[];
  onPage: (page: number) => void;
  onSize: (size: number) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-[#232323] py-4 text-[14px]",
      "[html[data-theme=light]_&]:border-black/[.09]", className)}>
      <nav aria-label="Pagination" className="flex flex-wrap items-center gap-2">
        <span className={cn("mr-0.5", HB_DIM)}>Total: {total} {noun}</span>
        <PageButtons
          page={page}
          pages={pageCount(total, size)}
          onPage={onPage}
          arrow={cn("grid h-7 w-7 place-items-center rounded-[4px] disabled:cursor-not-allowed disabled:opacity-60", HB_FILL_2, HB_TEXT)}
          item={(on) => cn("h-7 min-w-7 rounded-[4px] px-1.5", on ? cn(HB_FILL_1, HB_TEXT) : cn(HB_DIM, "hover:opacity-80"))}
        />
      </nav>
      <span className={cn("flex items-center gap-2", HB_DIM)}>
        Per page
        <Listbox
          value={String(size)}
          options={sizes.map((s) => ({ value: String(s), label: String(s) }))}
          onChange={(v) => onSize(Number(v))}
          ariaLabel="Per page"
          triggerClassName={cn("h-7 rounded-[4px] px-2 text-[14px]", HB_FILL_1, HB_TEXT)}
          chevronClassName={cn("h-4 w-4", HB_TEXT)}
          menuClassName={cn("border bg-panel", HB_HAIR)}
          // The pager sits at the page foot, so its menu opens upward or it runs off the viewport.
          openUp
        />
      </span>
    </div>
  );
}

// ── Tables ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** HB table classes: head and fixed Action column #171717 (`surface-level-01`), head text white 14px / 500, 48px rows
 *  with a 1px #2c2c2c rule, 18px cell padding, white 14px cells; `iconButton` the Action column's 28px #2c2c2c box. */
export const HB_TABLE = {
  table: "w-full border-collapse text-[14px]",
  th: cn("h-12 whitespace-nowrap bg-panel px-[18px] text-left font-medium", HB_TEXT),
  row: "border-b border-[#2c2c2c] [html[data-theme=light]_&]:border-black/[.09]",
  td: cn("h-12 px-[18px]", HB_TEXT),
  fixedAction: "sticky right-0 bg-panel",
  iconButton: cn("grid h-7 w-7 place-items-center rounded-[4px] hover:opacity-80", HB_FILL_3, HB_TEXT),
} as const;

/** Legacy antd table classes: a 46px head on #353535 with 14px / 500 T3 text and 22px L1 dividers between head cells
 *  (`thDivider` on every head cell; the last one hides it), L1 row rules, 14px T1 cells with 16px padding, and the
 *  100px "Actions" column fixed right with a left shadow (`fixedRight` on cells, `fixedRightHead` on its head cell). */
export const IF_TABLE = {
  table: "w-full border-collapse text-[14px]",
  th: "relative h-[46px] whitespace-nowrap bg-bg-elev-2 px-4 text-left font-medium text-muted [html[data-theme=light]_&]:bg-[#fafbff]",
  thDivider: "before:absolute before:right-0 before:top-1/2 before:h-[22px] before:w-px before:-translate-y-1/2 before:bg-border last:before:hidden",
  row: "border-b border-border",
  td: "p-4 text-fg",
  fixedRight: "sticky right-0 w-[100px] bg-bg shadow-[-6px_0_6px_-4px_rgba(0,0,0,.35)] [html[data-theme=light]_&]:shadow-[-6px_0_6px_-4px_#f5f6fa]",
  fixedRightHead: "sticky right-0 w-[100px] shadow-[-6px_0_6px_-4px_rgba(0,0,0,.35)] [html[data-theme=light]_&]:shadow-[-6px_0_6px_-4px_#f5f6fa]",
} as const;

// ── Modals ──────────────────────────────────────────────────────────────────────────────────────────────────────

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Open modals, top last: only the top one answers Escape and traps Tab. */
const modalStack: object[] = [];

/**
 * The one dialog hook both modal looks share: focus moves into the box (unless a child already took it with
 * `autoFocus`), Tab and Shift+Tab cycle inside it, Escape closes when `closable`, and focus returns to the opener.
 */
function useModalFocus(onClose: () => void, closable: boolean) {
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const closableRef = useRef(closable);
  useEffect(() => {
    closeRef.current = onClose;
    closableRef.current = closable;
  });
  useEffect(() => {
    const token = {};
    modalStack.push(token);
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const box = boxRef.current;
    if (box && !box.contains(document.activeElement)) box.focus();
    const onKey = (e: KeyboardEvent) => {
      if (modalStack[modalStack.length - 1] !== token || !box) return;
      if (e.key === "Escape" && closableRef.current) {
        e.preventDefault();
        closeRef.current();
      } else if (e.key === "Tab") {
        const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (!items.length) { e.preventDefault(); box.focus(); return; }
        const first = items[0];
        const last = items[items.length - 1];
        const at = document.activeElement;
        if (e.shiftKey && (at === first || at === box)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (at === last || !box.contains(at))) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      modalStack.splice(modalStack.indexOf(token), 1);
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return boxRef;
}

type ModalProps = {
  title?: ReactNode;
  /** The dialog's accessible name when it draws no `title`. */
  label?: string;
  width?: number;
  footer?: ReactNode;
  onClose: () => void;
  /** `false` draws no × and Escape does not close (Infloww's `closable:false`). */
  closable?: boolean;
  children?: ReactNode;
  className?: string;
};

const widthStyle = (width: number) => ({ width: `min(${width}px, calc(100vw - 32px))` });

/** Both modals' mask: it pops in (the mask fades, the box scales from 0.96, globals.css `pop-*`) and leaves on a copy
 *  that takes no click (`useExitGhost`), so closing never holds up the page. */
function ModalMask({ children }: { children: ReactNode }) {
  const maskRef = useRef<HTMLDivElement>(null);
  useExitGhost(true, maskRef);
  return (
    <div ref={maskRef} className="pop-backdrop fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/70 p-4">
      {children}
    </div>
  );
}

/** antd's modal: a 70% black mask; the box `colorBgElevated` #1f1f1f, radius 10, no border; header `22px 24px 0`
 *  (16 / 600 T1), body 24px, footer right with 8px between buttons; the 16px T3 × 16px in from the top right. */
export function IfModal({ title, label, width = 520, footer, onClose, closable = true, children, className }: ModalProps) {
  const boxRef = useModalFocus(onClose, closable);
  const titleId = useId();
  return (
    <ModalMask>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : label}
        tabIndex={-1}
        style={widthStyle(width)}
        className={cn("pop-modal relative flex max-h-[calc(100vh-32px)] flex-col rounded-[10px] bg-[#1f1f1f] outline-none shadow-2xl",
          "[html[data-theme=light]_&]:bg-white", className)}
      >
        {closable && (
          <button type="button" aria-label="Close" onClick={onClose}
            className="absolute right-4 top-4 grid h-6 w-6 place-items-center rounded text-muted hover:text-fg">
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
        {title && (
          <h2 id={titleId} className={cn("px-6 pt-[22px] text-[16px] font-semibold text-fg", closable && "pr-12")}>{title}</h2>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-6 text-[14px] text-fg">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 px-6 pb-5">{footer}</div>}
      </div>
    </ModalMask>
  );
}

/** HB's modal (`.hb-design-modal-content`): #171717 with a 1px 9%-white border, radius 12, `padding:12px 16px`, at
 *  least 480 wide and at most 80vh tall; the title 24px / 500 white over a hairline (`padding:0 16px 12px`), the body
 *  16px / 1.25 at 62% white, the footer over a hairline (`padding:12px 16px 0`) with its buttons right, 12px apart. */
export function HbModal({ title, width = 600, footer, onClose, closable = true, children, className }: ModalProps) {
  const boxRef = useModalFocus(onClose, closable);
  const titleId = useId();
  return (
    <ModalMask>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        style={{ ...widthStyle(width), minWidth: "min(480px, calc(100vw - 32px))" }}
        className={cn("pop-modal flex max-h-[80vh] flex-col rounded-[12px] border bg-panel px-4 py-3 outline-none shadow-2xl", HB_HAIR, className)}
      >
        {(title || closable) && (
          <div className={cn("flex items-center justify-between gap-3 border-b px-4 pb-3", HB_HAIR)}>
            <h2 id={titleId} className={cn("text-[24px] font-medium", HB_TEXT)}>{title}</h2>
            {closable && (
              <button type="button" aria-label="Close" onClick={onClose}
                className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-[4px] hover:opacity-80", HB_TEXT)}>
                <X className="h-5 w-5" aria-hidden />
              </button>
            )}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 text-[16px] leading-[1.25] text-white/[.62] [html[data-theme=light]_&]:text-black/[.62]">
          {children}
        </div>
        {footer && <div className={cn("flex items-center justify-end gap-3 border-t px-4 pt-3", HB_HAIR)}>{footer}</div>}
      </div>
    </ModalMask>
  );
}
