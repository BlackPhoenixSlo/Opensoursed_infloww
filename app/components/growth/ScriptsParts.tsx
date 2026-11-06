"use client";

/**
 * Growth > Scripts' parts (`ScriptsPage.tsx`): the More menu, a sidebar row's menu, the Tag / Sequence sidebar, the
 * sequence empty panel, a script row and its chips. Item numbers are the Layout capture's
 * (`docs/infloww-layouts/growth-scripts.md`).
 */

import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  ArrowRight, AtSign, ChevronDown, LayoutTemplate, List, MinusCircle, MoreHorizontal, Pencil, Plus, PlusSquare,
  Share2, StickyNote, Tags, Trash2, Workflow, type LucideIcon,
} from "lucide-react";

import { MediaStrip } from "@/components/settings/TemplateDraftEditor";
import { OfRichText } from "@/components/chat/OfRichText";
import { useOutsideClose } from "@/components/ui/Menu";
import { EmptyState } from "@/components/ui/infloww";
import { fmtPrice } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import type { SavedReply } from "@/lib/relay";
import { cn } from "@/lib/utils";

export const NOT_WIRED = "not wired";

/** antd's dropdown: #1f1f1f, radius 8, 32px items at 14px T1, hover #2b2b2b, L1 dividers. */
const MENU_PANEL =
  "absolute z-20 mt-1 rounded-lg bg-[#1f1f1f] p-1 shadow-lg [html[data-theme=light]_&]:bg-white";
const MENU_ITEM =
  "flex h-8 w-full items-center rounded px-3 text-left text-sm text-fg outline-none";
const MENU_HOVER =
  "hover:bg-[#2b2b2b] focus-visible:bg-[#2b2b2b] [html[data-theme=light]_&]:hover:bg-black/5 [html[data-theme=light]_&]:focus-visible:bg-black/5";

/**
 * A menu's keyboard, on its wrapper: ArrowDown / ArrowUp move between the enabled `menuitem`s (wrapping), Escape
 * calls `close` (which closes and puts focus back on the trigger, as a pick does).
 */
function onMenuKey(e: ReactKeyboardEvent<HTMLElement>, close: () => void) {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    close();
    return;
  }
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[role='menuitem']:not([disabled])"));
  if (!items.length) return;
  e.preventDefault();
  const at = items.indexOf(document.activeElement as HTMLElement);
  const by = e.key === "ArrowDown" ? 1 : -1;
  const next = at < 0 ? (by > 0 ? 0 : items.length - 1) : (at + by + items.length) % items.length;
  items[next].focus();
}

/** The More menu (#12 to #17). Add sequence and Import open submenus in the bundle; they are shown open, as labelled
 *  groups. */
export function MoreMenu({
  onAddScript, onAddSequence, onAddTag, onImportExcel, onImportCreators,
}: {
  onAddScript: () => void;
  onAddSequence: () => void;
  onAddTag: () => void;
  onImportExcel: () => void;
  onImportCreators: () => void;
}) {
  const { open, setOpen, ref } = useOutsideClose();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };
  const item = (label: string, onClick?: () => void, inset = false) => (
    <button
      key={label}
      type="button"
      role="menuitem"
      disabled={!onClick}
      title={onClick ? undefined : NOT_WIRED}
      onClick={() => {
        close();
        onClick?.();
      }}
      className={cn(
        MENU_ITEM,
        inset && "pl-6",
        onClick ? MENU_HOVER : "text-fg-dim opacity-60 cursor-not-allowed",
      )}
    >
      {label}
    </button>
  );
  const group = (label: string, children: Array<[string, (() => void) | undefined]>) => (
    <div role="group" aria-label={label}>
      <div className="flex h-8 items-center px-3 text-sm text-fg-dim">{label}</div>
      {children.map(([c, fn]) => item(c, fn, true))}
    </div>
  );
  const divider = <div role="separator" className="my-1 border-t border-border" />;
  return (
    <div ref={ref} className="relative" onKeyDown={(e) => onMenuKey(e, close)}>
      <button
        ref={triggerRef}
        type="button"
        aria-label="More"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="w-6 h-6 grid place-items-center rounded-full bg-accent text-white hover:opacity-90"
      >
        <Plus size={16} strokeWidth={2.5} aria-hidden />
      </button>
      {open && (
        <div role="menu" aria-label="More" className={cn(MENU_PANEL, "right-0 w-52")}>
          {item("Add script", onAddScript)}
          {divider}
          {group("Add sequence", [["Create new", onAddSequence], ["Use template", undefined], ["Import from tag", undefined]])}
          {item("Add tag", onAddTag)}
          {divider}
          {group("Import", [["From Excel", onImportExcel], ["From other creators", onImportCreators]])}
        </div>
      )}
    </div>
  );
}

/** A sidebar row's Rename / Delete menu (#58; Share is Not wired, so it is left out). */
function RowMenu({ label, onRename, onDelete }: { label: string; onRename: () => void; onDelete: () => void }) {
  const { open, setOpen, ref } = useOutsideClose();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };
  return (
    // The row itself answers Enter and Space, so the menu's keys stop here.
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => { e.stopPropagation(); onMenuKey(e, close); }}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={`${label} menu`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="text-fg-dim hover:text-fg"
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <div role="menu" aria-label={`${label} menu`} className={cn(MENU_PANEL, "right-0 w-32")}>
          <button type="button" role="menuitem" className={cn(MENU_ITEM, MENU_HOVER)}
            onClick={() => { close(); onRename(); }}>
            Rename
          </button>
          <button type="button" role="menuitem" className={cn(MENU_ITEM, MENU_HOVER, "text-err")}
            onClick={() => { close(); onDelete(); }}>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

export interface SidebarItem {
  id: string;
  name: string;
  count: number;
  /** The fixed entries ("All scripts", the untagged ones) have no menu. */
  fixed?: boolean;
}

/** The Tag and Sequence sidebar (#53 to #58): 248px, a search, then one row per entry with its script count. */
export function Sidebar({
  kind, items, selected, onSelect, onRename, onDelete,
}: {
  kind: "tag" | "sequence";
  items: SidebarItem[];
  selected: string | null;
  onSelect: (id: string) => void;
  onRename: (item: SidebarItem) => void;
  onDelete: (item: SidebarItem) => void;
}) {
  const [q, setQ] = useState("");
  const shown = q.trim()
    ? items.filter((i) => i.fixed || i.name.toLowerCase().includes(q.trim().toLowerCase()))
    : items;
  return (
    <aside
      aria-label={kind === "tag" ? "Tags" : "Sequences"}
      className="w-full md:w-[248px] shrink-0 px-4 py-2 border-b md:border-b-0 md:border-r border-border"
    >
      <input
        type="search"
        aria-label={`Search ${kind === "tag" ? "tags" : "sequences"}`}
        placeholder="Search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="w-full mb-2 rounded-md border border-border bg-transparent px-2 py-1 text-sm"
      />
      {shown.length === 0 && <EmptyState size="sm" text="No data" />}
      <ul className="space-y-0.5 max-h-60 md:max-h-none overflow-y-auto">
        {shown.map((i) => (
          <li key={i.id}>
            <div
              role="button"
              tabIndex={0}
              aria-current={selected === i.id ? "true" : undefined}
              onClick={() => onSelect(i.id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(i.id)}
              className={cn(
                "px-2 py-1.5 rounded-md cursor-pointer",
                selected === i.id ? "bg-accent/15 text-accent" : "hover:bg-bg-elev-1",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="flex-1 min-w-0 truncate text-sm font-medium">{i.name}</span>
                {!i.fixed && (
                  <RowMenu label={i.name} onRename={() => onRename(i)} onDelete={() => onDelete(i)} />
                )}
              </div>
              <div className="text-xs text-fg-dim">{i.count} {i.count === 1 ? "script" : "scripts"}</div>
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}

/** The bundle's empty panel for Tag and Sequence (#62 to #71): B1 under the whole body, three B-nav cards with no
 *  border, each a 48px icon, its label and a 20px M1 arrow, 12px apart. The bundle's card art is a remote PNG; these
 *  are lucide stand-ins (owner: no Infloww PNG assets). */
export function SequenceEmpty({ onCreate }: { onCreate: () => void }) {
  const card = (label: string, Icon: LucideIcon, onClick?: () => void) => (
    <button
      type="button"
      disabled={!onClick}
      title={onClick ? undefined : NOT_WIRED}
      onClick={onClick}
      className="w-full sm:w-[276px] h-40 sm:h-[234px] flex flex-col items-center justify-center gap-3 rounded-lg bg-bg text-sm text-fg hover:bg-bg-elev-2 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:bg-bg"
    >
      <Icon size={48} strokeWidth={1.5} aria-hidden className="text-fg-dim" />
      {label}
      <ArrowRight size={20} aria-hidden data-arrow className="text-accent" />
    </button>
  );
  return (
    <div className="flex-1 pt-12 sm:pt-[98px] pb-12 px-4 text-center bg-bg-elev-1">
      <h2 className="text-2xl sm:text-[32px] font-medium">Try out our new sequence feature</h2>
      <p className="mt-6 px-4 text-sm font-medium leading-[150%] text-fg-dim">
        Use sequences to arrange scripts into storylines and conversations to engage fans.
      </p>
      <div className="mt-12 flex flex-wrap justify-center gap-6 sm:gap-[60px]">
        {card("Create new sequence", PlusSquare, onCreate)}
        {card("Use a template", LayoutTemplate)}
        {card("Import from tag", Tags)}
      </div>
    </div>
  );
}

/** The tags and sequences column (#41): three chips, then a "+N" count; a chip opens its tag or sequence. */
function ScriptChips({
  r, onOpen,
}: {
  r: SavedReply;
  onOpen: (kind: "tag" | "sequence", name: string) => void;
}) {
  const chips: Array<{ kind: "tag" | "sequence"; name: string }> = [
    ...(r.tags ?? []).map((name) => ({ kind: "tag" as const, name })),
    ...(r.script_id ? [{ kind: "sequence" as const, name: r.script_id }] : []),
  ];
  const [all, setAll] = useState(false);
  if (chips.length === 0) return <span className="text-fg-dim">—</span>;
  const shown = all ? chips : chips.slice(0, 3);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((c) => {
        const Icon = c.kind === "tag" ? List : Workflow;
        return (
          <button
            key={`${c.kind}:${c.name}`}
            type="button"
            title={c.kind === "tag" ? `Tag: ${c.name}` : `Sequence: ${c.name}`}
            onClick={() => onOpen(c.kind, c.name)}
            className="max-w-full inline-flex items-center gap-1 rounded bg-bg-elev-1 px-1.5 py-0.5 text-xs hover:text-accent"
          >
            <Icon size={12} aria-hidden className="shrink-0" />
            <span className="truncate">{c.name}</span>
          </button>
        );
      })}
      {!all && chips.length > 3 && (
        <button
          type="button"
          onClick={() => setAll(true)}
          title={chips.slice(3).map((c) => c.name).join(", ")}
          className="rounded bg-bg-elev-1 px-1.5 py-0.5 text-xs text-fg-dim hover:text-fg"
        >
          +{chips.length - 3}
        </button>
      )}
    </div>
  );
}

/** One script (#38 to #49): checkbox, name (or the step in a sequence), tags, then text, media, price, stats and
 *  notes, then the actions. Phone-wide the cells wrap under the name. */
export function ScriptRow({
  r, stepLabel, accountId, expanded, checked, onCheck, onEdit, onShare, onDelete, removeLabel, onOpenChip, busy,
}: {
  r: SavedReply;
  /** In a sequence, the 72px cell shows the step and the name moves above the text. */
  stepLabel?: string;
  accountId: string | null;
  expanded: boolean;
  checked: boolean;
  onCheck: (on: boolean) => void;
  onEdit: () => void;
  onShare: () => void;
  onDelete: () => void;
  /** Set inside a tag or a sequence: the delete action removes the script from it instead (#47, #49). */
  removeLabel?: string;
  onOpenChip: (kind: "tag" | "sequence", name: string) => void;
  busy: boolean;
}) {
  const media = r.media ?? [];
  const tagged = r.tagged_users?.length ?? 0;
  // #42: each row expands on its own (the bundle's `scripts-expand` arrow, index.9f50f370.js @14227264); the
  // Expand scripts switch sets every row.
  const [open, setOpen] = useState(expanded);
  const [switchSeen, setSwitchSeen] = useState(expanded);
  if (switchSeen !== expanded) {
    setSwitchSeen(expanded);
    setOpen(expanded);
  }
  const inSequence = stepLabel != null;
  return (
    <li
      className={cn(
        "flex flex-wrap sm:flex-nowrap items-start min-h-10 py-2 pl-4 pr-6 border-b border-border",
        checked && "bg-accent/5",
        busy && "opacity-60",
      )}
    >
      <input
        type="checkbox"
        aria-label={`Select ${r.title || "script"}`}
        checked={checked}
        onChange={(e) => onCheck(e.target.checked)}
        className="mt-3 shrink-0 accent-accent"
      />
      {/* #38, #40: a 118px name cell (72px holding the step in a sequence), 8px 16px padding, at most three lines. */}
      <div
        className={cn(
          "shrink-0 px-4 py-2 text-sm font-medium break-words line-clamp-3",
          inSequence ? "w-[72px]" : "w-[118px]",
        )}
      >
        {inSequence ? stepLabel : r.title}
      </div>
      {/* #41: the tags and sequences column. */}
      <div aria-label="Tags" className="w-[172px] shrink-0 px-4 py-2 text-sm">
        <ScriptChips r={r} onOpen={onOpenChip} />
      </div>
      <div className="flex-1 min-w-[200px] py-2">
        {inSequence && r.title && <div className="text-sm font-medium mb-0.5">{r.title}</div>}
        {/* #42: two lines, then the row's arrow or the Expand scripts switch lifts the clamp. */}
        <div className="flex items-start gap-2">
          <OfRichText as="p" raw={r.text} className={cn("flex-1 text-sm whitespace-pre-wrap break-words", !open && "line-clamp-2")} />
          <button
            type="button"
            aria-label="Expand script"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="mt-0.5 shrink-0 text-fg-dim hover:text-fg"
          >
            <ChevronDown size={12} aria-hidden className={cn("transition-transform", open && "rotate-180")} />
          </button>
        </div>
        {media.length > 0 && <MediaStrip media={media} accountId={accountId} />}
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-fg-dim">
          {/* #44: the price, when the media is priced (`fmtPrice`, not the bundle's "$ 10.00"). */}
          {r.price > 0 && <span className="text-warn">{fmtPrice(Math.round(r.price * 100))}</span>}
          {/* #45: sent, purchases and sales; the store keeps no statistics. */}
          <span aria-label="Stats" title={NOT_WIRED}>—</span>
          {tagged > 0 && (
            <span aria-label={`Tagged Creators: ${tagged}`} title={EXTRA_LABEL} className="inline-flex items-center gap-1">
              <AtSign size={12} aria-hidden /> {tagged}
            </span>
          )}
        </div>
        {/* #46: the internal notes on one line behind a notes icon. */}
        {r.notes && (
          <div aria-label="Internal notes" title={r.notes} className="mt-1 flex items-center gap-1 text-xs text-fg-dim">
            <StickyNote size={12} aria-hidden className="shrink-0" />
            <span className="truncate">{r.notes}</span>
          </div>
        )}
      </div>
      {/* #47, #48: edit, share, delete (or remove), 16px left padding, 24px apart. */}
      <div className="flex items-center gap-6 pl-4 py-2 text-fg-dim">
        <button type="button" aria-label="Edit" onClick={onEdit} className="hover:text-fg">
          <Pencil size={16} aria-hidden />
        </button>
        <button type="button" aria-label="Share script" onClick={onShare} className="hover:text-fg">
          <Share2 size={16} aria-hidden />
        </button>
        {removeLabel ? (
          <button type="button" aria-label={removeLabel} title={removeLabel} onClick={onDelete} disabled={busy}
            className="text-[#FC584D] hover:opacity-80">
            <MinusCircle size={16} aria-hidden />
          </button>
        ) : (
          <button type="button" aria-label="Delete" onClick={onDelete} disabled={busy} className="hover:text-err">
            <Trash2 size={16} aria-hidden />
          </button>
        )}
      </div>
    </li>
  );
}
