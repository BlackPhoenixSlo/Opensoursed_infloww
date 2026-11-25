"use client";


import {
  forwardRef, useCallback, useId, useRef, useState, useSyncExternalStore,
  type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type LabelHTMLAttributes, type TextareaHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowRight, BookOpen, Calendar, ChevronLeft, Loader2, Search, SlidersHorizontal } from "lucide-react";

import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { InfoTip } from "@/components/ui/InfoTip";
import { useOutsideClose } from "@/components/ui/Menu";
import { EmptyArt, type EmptyKind } from "@/components/ui/emptyArt";
import { HB_FILL_3, HB_TEXT, IF_FIELD, Listbox, type IconProp, type IfOption } from "@/components/ui/ifSelect";
import type { AccountMeta, WatcherAccount } from "@/lib/relay";
import { utcOffsetLabel } from "@/lib/utcOffset";
import { cn } from "@/lib/utils";

export type { EmptyKind } from "@/components/ui/emptyArt";
export { HbFilter, HbFilterLg, HbSelect, IfNativeSelect, IfSelect, type IfOption } from "@/components/ui/ifSelect";
export { HbPager, IfPager } from "@/components/ui/ifPager";
export { HbModal, IfModal } from "@/components/ui/ifModal";


function UtcLabel({ zone }: { zone: string | null }) {
  return (
    <span className="flex shrink-0 items-center gap-1 text-[14px] text-fg-dim tabular-nums">
      <span suppressHydrationWarning>{utcOffsetLabel(zone)}</span>
      <InfoTip text="Set by your organization" />
    </span>
  );
}

export function InflowwPageHeader({
  title, utc, extra, actions, children, weight = "semibold", onBack, className,
}: {
  title: ReactNode;
  utc?: string | null;
  extra?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  weight?: "semibold" | "medium";
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

export function IfBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 py-4", className)} {...rest} />;
}


const ART_HEIGHT = { sm: 40, md: 90, lg: 100 } as const;

export function EmptyState({
  kind = "data", text = "No data", help, onRetry, action, size = "lg", art = true, className, textClassName, ...rest
}: Omit<HTMLAttributes<HTMLDivElement>, "children"> & {
  kind?: EmptyKind;
  text?: ReactNode;
  help?: ReactNode;
  onRetry?: () => void;
  action?: ReactNode;
  size?: keyof typeof ART_HEIGHT;
  art?: boolean;
  textClassName?: string;
}) {
  return (
    <div {...rest} data-empty-state={kind}
      className={cn("sticky left-0 flex max-w-[calc(100vw-32px)] flex-col items-center justify-center text-center",
        size === "sm" && "py-8", className)}>
      {art && <EmptyArt kind={kind} height={ART_HEIGHT[size]} />}
      <p className={cn("text-[14px] text-muted", art && (size === "md" ? "mt-2.5" : "mt-2"), textClassName)}>{text}</p>
      {help}
      {kind === "error" && onRetry && (
        <IfButton variant="primary" className="mt-2.5" onClick={onRetry}>Retry</IfButton>
      )}
      {action && <div className="mt-2.5">{action}</div>}
    </div>
  );
}


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
              <InfoTip text={info} className="ml-[9px] text-fg-dim" />
            )}
          </h2>
          {extra}
        </div>
      )}
      {children}
    </section>
  );
}


type IfButtonVariant = "primary" | "default" | "link";

export function ifButtonClass(variant: IfButtonVariant = "default", size: "md" | "lg" = "md", className?: string) {
  return cn(
    "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-[14px] transition-colors",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
    "disabled:cursor-not-allowed disabled:opacity-50",
    size === "lg" ? "h-9" : "h-8",
    variant === "primary" && "bg-accent px-[15px] text-white hover:bg-accent-hover",
    variant === "default" && "border border-border bg-transparent px-[15px] text-fg hover:border-accent hover:text-accent",
    variant === "link" && "px-0 text-accent hover:text-accent-hover",
    className,
  );
}

export const IfButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & IconProp & { variant?: IfButtonVariant; size?: "md" | "lg" }
>(({ variant = "default", size = "md", icon: Icon, className, children, type = "button", ...rest }, ref) => (
  <button
    ref={ref}
    type={type}
    className={ifButtonClass(variant, size, className)}
    {...rest}
  >
    {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
    {children}
  </button>
));
IfButton.displayName = "IfButton";

export interface SaveVerdict { pending: boolean; saved: boolean; error: string | null }

export const saveVerdict = (
  m: { isPending: boolean; isSuccess: boolean; error: Error | null }, clean = true,
): SaveVerdict => ({ pending: m.isPending, saved: m.isSuccess && clean, error: m.error ? m.error.message || "Save failed" : null });

export function SaveRow({ save, onSave, disabled, warn, label = "Save", form, children }: {
  save: SaveVerdict;
  disabled?: boolean;
  warn?: string | null;
  label?: string;
  children?: ReactNode;
} & ({ onSave: () => void; form?: never } | { form: string; onSave?: never })) {
  return (
    <div className="flex items-center gap-3">
      <IfButton type={form ? "submit" : "button"} form={form} variant="primary" onClick={onSave}
        disabled={save.pending || disabled} className="min-w-[76px]">
        {save.pending ? "Saving…" : label}
      </IfButton>
      {children}
      {warn && <span className="text-[12px] text-warn">{warn}</span>}
      {save.saved && <span className="text-[12px] text-ok">Saved</span>}
      {save.error && <span className="text-[12px] text-err">{save.error}</span>}
    </div>
  );
}

export const LEARN = "inline-flex items-center gap-1 text-[14px] text-accent hover:text-accent-hover";

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

export function IfLabel({ required, className, children, ...rest }: LabelHTMLAttributes<HTMLLabelElement> & {
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label {...rest} className={cn("mb-2 block text-[14px] text-fg", className)}>
      {children}
      {required && <span aria-hidden className="ml-0.5 text-err">*</span>}
    </label>
  );
}

export function IfHelp({ className, children, ...rest }: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return <div {...rest} className={cn("mt-1 text-[12px] text-muted", className)}>{children}</div>;
}

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

export function IfTabs<T extends string>({ tabs, value, onChange, extra, idPrefix, "aria-label": ariaLabel, className, wrap }: {
  tabs: IfOption<T>[];
  value: T;
  onChange: (value: T) => void;
  extra?: ReactNode;
  idPrefix?: string;
  "aria-label"?: string;
  className?: string;
  wrap?: boolean;
}) {
  const listRef = useRef<HTMLDivElement>(null);
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
    <div className={cn("flex h-12 shrink-0 items-center gap-4 border-b border-border px-6", wrap && "max-sm:h-auto", className)}>
      <div ref={listRef} role="tablist" aria-label={ariaLabel} onKeyDown={onKey}
        className={cn("flex h-full min-w-0 gap-8 overflow-x-auto", wrap && "max-sm:flex-wrap max-sm:gap-x-6 max-sm:gap-y-0")}>
        {tabs.map((t) => {
          const on = t.value === value;
          return (
            <button key={t.value} type="button" role="tab" aria-selected={on} tabIndex={t.value === stop ? 0 : -1} disabled={t.disabled}
              id={idPrefix && `${idPrefix}-tab-${t.value}`} aria-controls={idPrefix && `${idPrefix}-panel-${t.value}`}
              aria-disabled={t.disabled || undefined} title={t.title}
              onClick={() => onChange(t.value)}
              className={cn(
                "relative h-full shrink-0 whitespace-nowrap text-[14px] transition-colors", wrap && "max-sm:h-10",
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

export function IfSwitch({ id, checked, onChange, label, loading, disabled, "aria-label": ariaLabel, className }: {
  id?: string;
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
    <button id={id} type="button" role="switch" aria-checked={checked} aria-label={ariaLabel} aria-busy={loading || undefined}
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


export function countActiveFilters<F extends object, K extends keyof F>(
  values: F, defaults: Pick<F, K>, filters: ReadonlyArray<K | readonly K[]>,
): number {
  return filters.filter((f) => (Array.isArray(f) ? f : [f]).some((k: K) => values[k] !== defaults[k])).length;
}

export function IfFilterFold({ active, className, children }: { active: number; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <IfButton
        icon={SlidersHorizontal}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cn("md:hidden", active > 0 && "border-accent text-accent", className)}
      >
        Filters{active > 0 && ` (${active} active)`}
      </IfButton>
      <div id={id} data-filter-fold className={cn(open ? "contents" : "hidden", "md:contents")}>{children}</div>
    </>
  );
}


const creatorName = (a: AccountMeta | WatcherAccount) => a.nickname || a.name || a.id;

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

const ALL_CREATORS = "";

export function IfCreatorSelect({ accounts, value, onChange, onAll, allLabel, watchers, searchable, disabled, className }: {
  accounts: AccountMeta[];
  value: string | null | undefined;
  onChange: (accountId: string) => void;
  onAll?: () => void;
  allLabel?: string;
  watchers?: WatcherAccount[];
  searchable?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const all: IfOption[] = onAll ? [{ value: ALL_CREATORS, text: allLabel ?? "All creators", label: allLabel ?? "All creators" }] : [];
  const options: IfOption[] = [...all, ...accounts.map((a) => ({
    value: a.id,
    text: creatorName(a),
    label: (
      <>
        <CreatorAvatar account={a} />
        <span className="truncate">{creatorName(a)}</span>
      </>
    ),
  })), ...(watchers ?? []).map((w) => ({
    value: `watcher:${w.id}`,
    text: creatorName(w),
    disabled: true,
    title: "Watcher account: not a Creator",
    label: (
      <>
        <span className="truncate">{creatorName(w)}</span>
        <span className="rounded bg-bg-elev-2 px-1 text-[10px] text-fg-dim">watcher</span>
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
        if (o?.value === ALL_CREATORS && onAll) return allLabel ?? "All creators";
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


export const HB_TABLE = {
  table: "w-full border-collapse text-[14px]",
  th: cn("h-12 whitespace-nowrap bg-panel px-[18px] text-left font-medium", HB_TEXT),
  row: "border-b border-[#2c2c2c] [html[data-theme=light]_&]:border-black/[.09]",
  td: cn("h-12 px-[18px]", HB_TEXT),
  fixedAction: "sticky right-0 bg-panel",
  iconButton: cn("grid h-7 w-7 place-items-center rounded-[4px] hover:opacity-80", HB_FILL_3, HB_TEXT),
} as const;

export const IF_TABLE = {
  table: "w-full border-collapse text-[14px]",
  th: "relative h-[46px] whitespace-nowrap bg-bg-elev-2 px-4 text-left font-medium text-muted [html[data-theme=light]_&]:bg-[#fafbff]",
  thDivider: "before:absolute before:right-0 before:top-1/2 before:h-[22px] before:w-px before:-translate-y-1/2 before:bg-border last:before:hidden",
  row: "border-b border-border",
  td: "p-4 text-fg",
  fixedRight: "sticky right-0 w-[100px] bg-bg shadow-[-6px_0_6px_-4px_rgba(0,0,0,.35)] [html[data-theme=light]_&]:shadow-[-6px_0_6px_-4px_#f5f6fa]",
  fixedRightHead: "sticky right-0 w-[100px] shadow-[-6px_0_6px_-4px_rgba(0,0,0,.35)] [html[data-theme=light]_&]:shadow-[-6px_0_6px_-4px_#f5f6fa]",
  unpinPhone: "max-sm:static max-sm:shadow-none max-sm:[html[data-theme=light]_&]:shadow-none",
} as const;

