"use client";

/**
 * Growth > Scripts, laid out from its Layout capture (`docs/infloww-layouts/growth-scripts.md`, tickets 35 and 56):
 * the bundle's script manager over our saved replies.
 *
 * - The header (#3 to #17): "Scripts", "Learn" (Not wired: the help article is off-host) and
 *   "Share" (the selected scripts, or all of them, to other Creators), and the More menu behind the bundle shot's
 *   filled accent plus: Add script, Add sequence > Create new, Add tag, Import > From Excel / From other creators;
 *   Use template and Import from tag are Not wired. Import and Share are `ScriptsImportDialogs`. The Creator is
 *   picked on the creator column left of the page (`CreatorRail`, as Smart lists') in place of the bundle's header
 *   select (#6), without its per-Creator script count (`showScriptCount`): the store has no count read (YAGNI).
 * - The toolbar (#18 to #33): the "Tag" and "Sequence" tabs (Tag first, as the bundle opens, #23), the search, and
 *   "Manage scripts", which swaps the tabs for a back arrow and its title and sorts by Recent or Name (#31 to #33).
 * - Tag and Sequence (#53 to #64): a 248px sidebar beside the selected entry's scripts. Tag lists "All scripts",
 *   each tag, then the untagged scripts (the bundle's `UncategorizedCommon` 8888 / 9999 entries, index.9f50f370.js
 *   @13877942); a sequence lists its steps, numbered by step, "2.1" / "2.2" when one step holds several options
 *   (the bundle's `stepIndex`, @14238300). Each tag and sequence row renames and deletes. No tag or sequence (or no
 *   script at all on Tag) shows the bundle's sequence empty panel.
 * - The list (#34 to #50): the select-all box, the "Expand scripts" switch, then one row per script: name (the step
 *   number in a sequence, #38), its tag and sequence chips (#41, three then "+N"), text, media, price, stats (Not
 *   wired), internal notes (#46), then edit, share and delete, which removes the script from the open
 *   tag or sequence instead (#47, #49). A selection opens the bar (#51): Add to tag, and Delete or Remove.
 *
 * Tags, notes and sequences are stored on the saved reply: `tags`, `notes`, and `script_id` + `script_step` (the
 * pair the chat composer's next-step suggestion follows). A tag exists while a script carries it; a new empty tag
 * lives on this page until a script takes it. The list, the editor and their routes are the Templates tab's
 * (`useSavedReplyEditor`); renames, deletes and bulk tagging go through `POST /admin/saved-replies/relabel`.
 */

import { useMemo, useReducer, useRef, useState, type ComponentProps, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  ArrowLeft, ArrowRight, AtSign, BookOpen, ChevronDown, LayoutTemplate, List, MinusCircle, MoreHorizontal, Pencil,
  Plus, PlusSquare, Search, Share2, StickyNote, Tags, Trash2, Workflow, X, type LucideIcon,
} from "lucide-react";

import {
  MediaStrip, SCRIPT_NAME_MAX, SCRIPT_TAG_MAX, TemplateDraftEditor, extractError,
} from "@/components/settings/TemplateDraftEditor";
import { useSavedReplyEditor, useScopedAccount } from "@/components/settings/TemplatesTab";
import { CopyScriptsDialog, ExcelImportDialog } from "@/components/growth/ScriptsImportDialogs";
import { NameModal, ScriptEditModal } from "@/components/growth/ScriptModals";
import { useOutsideClose } from "@/components/ui/Menu";
import { CreatorRail } from "@/components/shell/CreatorRail";
import { EmptyState, IfSelect, InflowwPageHeader } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useDeleteSavedReply, useRelabelSavedReplies } from "@/hooks/useSavedReplies";
import { fmtPrice } from "@/lib/format";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import type { SavedReply } from "@/lib/relay";
import { cn } from "@/lib/utils";
import {
  ALL, INITIAL, UNCATEGORIZED, activeEntry, kindOf, livePending, scriptsPageReducer, type EntryKind,
} from "@/components/growth/scriptsPageState";

const NOT_WIRED = "not wired";

/** The Learn and Share boxes (#9, #10): 75px wide, 0 8px padding, 14px weight 500 T1, an 18px icon 4px from the
 *  text, at full ink, as the bundle shot draws them (#d9d9d9 dark). Learn is Not wired (disabled and titled). */
const HEADER_BOX =
  "min-w-[75px] h-6 px-2 flex items-center justify-center text-sm font-medium text-fg disabled:cursor-not-allowed";

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

const byName = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base" });

/** A sequence's scripts in step order, each with its label: the step, or "step.option" when a step holds several. */
function sequenceSteps(rows: SavedReply[]): Array<{ r: SavedReply; label: string }> {
  const sorted = [...rows].sort((a, b) => (a.script_step ?? 0) - (b.script_step ?? 0) || a.id - b.id);
  const perStep = new Map<number, number>();
  for (const r of sorted) perStep.set(r.script_step ?? 0, (perStep.get(r.script_step ?? 0) ?? 0) + 1);
  const seen = new Map<number, number>();
  return sorted.map((r) => {
    const step = r.script_step ?? 0;
    const i = (seen.get(step) ?? 0) + 1;
    seen.set(step, i);
    return { r, label: (perStep.get(step) ?? 1) > 1 ? `${step}.${i}` : String(step) };
  });
}

/** The first step number a sequence skips: the chat's next-step suggestion stops before it. */
function firstGap(rows: SavedReply[]): number | null {
  const steps = new Set(rows.map((r) => r.script_step ?? 0));
  const max = Math.max(0, ...steps);
  for (let s = 1; s <= max; s++) if (!steps.has(s)) return s;
  return null;
}

/** The More menu (#12 to #17). Add sequence and Import open submenus in the bundle; they are shown open, as labelled
 *  groups. */
function MoreMenu({
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

interface SidebarItem {
  id: string;
  name: string;
  count: number;
  /** The fixed entries ("All scripts", the untagged ones) have no menu. */
  fixed?: boolean;
}

/** The Tag and Sequence sidebar (#53 to #58): 248px, a search, then one row per entry with its script count. */
function Sidebar({
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
function SequenceEmpty({ onCreate }: { onCreate: () => void }) {
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
function ScriptRow({
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
          <p className={cn("flex-1 text-sm whitespace-pre-wrap break-words", !open && "line-clamp-2")}>{r.text}</p>
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

/** The open name modal, as data: its props (and `onOk`) are built each render, so OK acts on the page as it is
 *  then, not as it was when the modal opened (a refetch in between may have given a new tag its first script). */
type NamePrompt =
  | { kind: "sequence" }
  | { kind: "tag"; ids?: number[] }
  | { kind: "rename"; entry: EntryKind; from: string };

export default function ScriptsPage() {
  const accounts = useActiveAccounts();
  const [accountId, setAccountId] = useScopedAccount();
  const {
    draft, setDraft, saveErr, saving,
    replyQ, replies, startNewReply, startEditReply, save,
  } = useSavedReplyEditor(accountId);
  const deleteM = useDeleteSavedReply(accountId);
  const relabelM = useRelabelSavedReplies(accountId);

  // The view, the open tag and sequence, the checked scripts and the page's new tags: `scriptsPageState.ts`.
  const [page, dispatch] = useReducer(scriptsPageReducer, INITIAL);
  const { view, checked } = page;
  const [expanded, setExpanded] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState<"recent" | "name">("recent");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [namePrompt, setNamePrompt] = useState<NamePrompt | null>(null);
  const [dialog, setDialog] = useState<
    { kind: "excel" } | { kind: "import" } | { kind: "share"; ids?: number[] } | null
  >(null);
  const clearSelection = () => dispatch({ type: "setChecked", ids: [] });
  // Another Creator: nothing of this one's (draft, selection, new tags, open tag or sequence) carries over.
  const pickCreator = (id: string) => {
    setAccountId(id);
    setDraft(null);
    dispatch({ type: "reset" });
  };

  // ── derived: tags and sequences ──
  const pending = useMemo(() => livePending(page.pendingTags, replies), [page.pendingTags, replies]);
  const tagCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of pending) m.set(t, 0);
    for (const r of replies) for (const t of r.tags ?? []) m.set(t, (m.get(t) ?? 0) + 1);
    return m;
  }, [replies, pending]);
  const tagNames = useMemo(() => [...tagCounts.keys()].sort(byName), [tagCounts]);
  const sequences = useMemo(() => {
    const m = new Map<string, SavedReply[]>();
    for (const r of replies) if (r.script_id) m.set(r.script_id, [...(m.get(r.script_id) ?? []), r]);
    return m;
  }, [replies]);
  const seqNames = useMemo(() => [...sequences.keys()].sort(byName), [sequences]);
  // The sidebars' order, as drawn: deleting the open entry opens its neighbour in it.
  const tagOrder = useMemo(() => [ALL, ...tagNames, UNCATEGORIZED], [tagNames]);
  const orderOf = (kind: EntryKind) => (kind === "tag" ? tagOrder : seqNames);
  const activeSeq = activeEntry(page.open.sequence, seqNames);
  const activeTag = activeEntry(page.open.tag, tagOrder) ?? ALL;

  // ── the list for the open view ──
  const matches = (r: SavedReply) => {
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return [r.title, r.text, r.notes, ...(r.tags ?? [])].some((v) => (v ?? "").toLowerCase().includes(needle));
  };
  const rows: Array<{ r: SavedReply; stepLabel?: string }> = useMemo(() => {
    if (view === "sequences") {
      return activeSeq ? sequenceSteps(sequences.get(activeSeq) ?? []).filter(({ r }) => matches(r)).map(
        ({ r, label }) => ({ r, stepLabel: label }),
      ) : [];
    }
    let list = replies.filter(matches);
    if (view === "tags") {
      if (activeTag === UNCATEGORIZED) list = list.filter((r) => !(r.tags ?? []).length);
      else if (activeTag !== ALL) list = list.filter((r) => (r.tags ?? []).includes(activeTag));
    } else {
      const dir = order === "asc" ? 1 : -1;
      list = [...list].sort((a, b) =>
        sortBy === "name"
          ? dir * byName(a.title ?? "", b.title ?? "")
          : dir * ((a.updated_at ?? "").localeCompare(b.updated_at ?? "") || a.id - b.id),
      );
    }
    return list.map((r) => ({ r }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, replies, sequences, activeSeq, activeTag, q, sortBy, order]);

  const inTag = view === "tags" && activeTag !== ALL && activeTag !== UNCATEGORIZED ? activeTag : null;
  const inSeq = view === "sequences" ? activeSeq : null;
  const removeLabel = inTag ? "Remove from tag" : inSeq ? "Remove from sequence" : undefined;

  const listIds = rows.map(({ r }) => r.id);
  const checkedInList = listIds.filter((id) => checked.has(id));
  const allChecked = listIds.length > 0 && checkedInList.length === listIds.length;
  /** A checked script still being removed / deleted: the selection bar waits for its answer (no second POST). */
  const selBusy = checkedInList.some((id) => busyIds.has(id));

  // ── actions ──
  async function run(ids: number[], fn: () => Promise<unknown>) {
    setActionErr(null);
    setBusyIds((b) => new Set([...b, ...ids]));
    try {
      await fn();
    } catch (e) {
      setActionErr(extractError(e));
    } finally {
      setBusyIds((b) => new Set([...b].filter((id) => !ids.includes(id))));
    }
  }

  function deleteScripts(ids: number[]) {
    const one = ids.length === 1;
    if (!confirm(`${one ? "Delete script?" : `Delete ${ids.length} scripts?`}\n\nThis script will also be deleted from sequences that utilized this script.`)) return;
    void run(ids, async () => {
      for (const id of ids) await deleteM.mutateAsync(id);
      dispatch({ type: "check", ids, on: false });
    });
  }

  function removeScripts(ids: number[]) {
    const from = inTag ?? inSeq;
    if (!from) return;
    const kind = inTag ? "tag" : "sequence";
    if (!confirm(kind === "tag"
      ? "Remove this script?\n\nThe script will be removed from this tag."
      : "Remove this script?\n\nRemove this script from this sequence. You can add the script back any time you want.")) return;
    // Unchecked once the server took it; a failed remove keeps the ticks for a retry.
    void run(ids, async () => {
      await relabelM.mutateAsync({ kind, from, ids });
      dispatch({ type: "check", ids, on: false });
    });
  }

  function nextStep(name: string): number {
    return Math.max(0, ...(sequences.get(name) ?? []).map((r) => r.script_step ?? 0)) + 1;
  }

  /** Add script, seeded with the open tag, or the open sequence's next step. */
  function addScript() {
    if (inTag) startNewReply({ tags: [inTag] });
    else if (inSeq) startNewReply({ scriptId: inSeq, scriptStep: String(nextStep(inSeq)) });
    else startNewReply();
  }

  /** A tag no script carries lives on this page only: renamed and deleted here, never on the server. */
  const pageOnly = (kind: EntryKind, name: string) => kind === "tag" && pending.includes(name);

  /** The open name modal's props, from the page as it is this render (see `NamePrompt`). */
  function promptProps(p: NamePrompt): Omit<ComponentProps<typeof NameModal>, "onClose"> {
    if (p.kind === "sequence") {
      return {
        title: "Add sequence", label: "Sequence name", maxLength: SCRIPT_NAME_MAX,
        onOk: (name) => {
          if (sequences.has(name)) throw new Error("Sequence name already exists. Please rename sequence.");
          dispatch({ type: "open", kind: "sequence", name });
          startNewReply({ scriptId: name, scriptStep: "1" });
        },
      };
    }
    if (p.kind === "tag") {
      const { ids } = p;
      return {
        title: "Add tag name", label: "Tag name", maxLength: SCRIPT_TAG_MAX,
        options: ids ? tagNames : undefined,
        onOk: async (name) => {
          if (ids?.length) await relabelM.mutateAsync({ kind: "tag", to: name, ids });
          dispatch({ type: "addTag", name, pending: !ids?.length && !tagCounts.has(name) });
        },
      };
    }
    const { entry: kind, from } = p;
    return {
      title: kind === "tag" ? "Modify tag name" : "Modify sequence name",
      label: kind === "tag" ? "Tag name" : "Sequence name",
      initial: from,
      maxLength: kind === "tag" ? SCRIPT_TAG_MAX : SCRIPT_NAME_MAX,
      onOk: async (to) => {
        if (to === from) return;
        if (!pageOnly(kind, from)) await relabelM.mutateAsync({ kind, from, to });
        dispatch({ type: "renameEntry", kind, from, to, order: orderOf(kind) });
      },
    };
  }

  function deleteEntry(kind: EntryKind, name: string) {
    const ok = kind === "tag"
      ? confirm("Delete tag?\n\nThis tag will be permanently removed from the script library. Its scripts stay.")
      : confirm("Delete the Sequence?\n\nAre you sure you want to delete this sequence? Its scripts stay in the library.");
    if (!ok) return;
    const done = () => dispatch({ type: "deleteEntry", kind, name, order: orderOf(kind) });
    // A page-only tag moves on at once; anything else once the server has dropped it.
    if (pageOnly(kind, name)) done();
    else void run([], async () => { await relabelM.mutateAsync({ kind, from: name }); done(); });
  }

  const sideKind = kindOf(view);

  // ── render ──
  const tagItems: SidebarItem[] = [
    { id: ALL, name: "All scripts", count: replies.length, fixed: true },
    ...tagNames.map((t) => ({ id: t, name: t, count: tagCounts.get(t) ?? 0 })),
    { id: UNCATEGORIZED, name: "Uncategorized", count: replies.filter((r) => !(r.tags ?? []).length).length, fixed: true },
  ];
  const seqItems: SidebarItem[] = seqNames.map((s) => ({ id: s, name: s, count: sequences.get(s)?.length ?? 0 }));
  const showEmptyPanel =
    !replyQ.isLoading && !replyQ.error &&
    ((view === "sequences" && seqNames.length === 0) || (view === "tags" && replies.length === 0 && tagNames.length === 0));

  const activeSeqRows = activeSeq ? sequences.get(activeSeq) ?? [] : [];
  const gap = view === "sequences" && activeSeq ? firstGap(activeSeqRows) : null;
  const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "--");
  const created = activeSeqRows.map((r) => r.created_at ?? "").filter(Boolean).sort()[0];
  const modified = activeSeqRows.map((r) => r.updated_at ?? "").filter(Boolean).sort().at(-1);

  const list = (
    <div className="flex-1 min-w-0">
      {view === "sequences" && activeSeq && (
        // The sequence header (#60, #61): name, then its meta; Add step adds the next step's script.
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 flex-wrap">
            <Workflow size={20} aria-hidden />
            <h2 className="text-base font-semibold">{activeSeq}</h2>
            <button
              type="button"
              onClick={() => startNewReply({ scriptId: activeSeq, scriptStep: String(nextStep(activeSeq)) })}
              className="ml-auto h-7 px-2 rounded text-sm text-accent bg-accent/15 inline-flex items-center gap-1"
            >
              <Plus size={14} aria-hidden /> Add step
            </button>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-fg-dim">
            <span>Created on{"："}{fmt(created)}</span>
            <span>Last modified on{"："}{fmt(modified)}</span>
          </div>
          {gap != null && (
            <div className="mt-1 text-xs text-warn">
              No script at step {gap}: the chat&apos;s next-step suggestion stops before it.
            </div>
          )}
        </div>
      )}

      {/* #34 to #36: a 32px bar, 0 16px padding; the select-all box, then the switch; the sort (#33) at the right,
          two 32px antd selects, so Manage scripts' bar grows by 4px either side. */}
      <div className={cn("h-8 px-4 flex items-center gap-2", view === "manage" && "h-10")}>
        <input
          type="checkbox"
          aria-label="Select all"
          checked={allChecked}
          disabled={listIds.length === 0}
          onChange={(e) => dispatch({ type: "setChecked", ids: e.target.checked ? listIds : [] })}
          className="accent-accent"
        />
        <button
          type="button"
          role="switch"
          aria-checked={expanded}
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-2 text-xs text-fg-dim"
        >
          Expand scripts
          <span
            aria-hidden
            className={cn("relative inline-block w-7 h-4 rounded-full transition-colors", expanded ? "bg-accent" : "bg-border")}
          >
            <span
              className={cn("absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all", expanded ? "left-3.5" : "left-0.5")}
            />
          </span>
        </button>
        {view === "manage" && (
          <div className="ml-auto flex items-center gap-2">
            <IfSelect aria-label="Sort by" value={sortBy} onChange={setSortBy} className="w-[120px]"
              options={[{ value: "recent", label: "Recent" }, { value: "name", label: "Name" }]} />
            {/* 120px clips "Descending" at antd's padding, so this one is 136px. */}
            <IfSelect aria-label="Sort order" value={order} onChange={setOrder} className="w-[136px]"
              options={[{ value: "asc", label: "Ascending" }, { value: "desc", label: "Descending" }]} />
          </div>
        )}
      </div>

      {/* #51: the selection bar. */}
      {checkedInList.length > 0 && (
        <div
          role="toolbar"
          aria-label="Selection"
          className="mx-4 mb-2 min-h-10 px-3 py-1 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-accent text-white text-sm whitespace-nowrap"
        >
          <span>Selected</span>
          <span className="font-semibold">{checkedInList.length}</span>
          <button type="button" aria-label="Clear selection" onClick={clearSelection} className="rounded bg-black/20 p-0.5">
            <X size={16} aria-hidden />
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
            <button type="button" onClick={() => setNamePrompt({ kind: "tag", ids: checkedInList })} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
              <List size={16} aria-hidden /> Add to tag
            </button>
            {removeLabel ? (
              <button type="button" onClick={() => removeScripts(checkedInList)} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
                <MinusCircle size={16} aria-hidden /> {removeLabel}
              </button>
            ) : (
              <button type="button" onClick={() => deleteScripts(checkedInList)} disabled={selBusy}
              className="inline-flex items-center gap-1 disabled:opacity-50">
                <Trash2 size={16} aria-hidden /> Delete
              </button>
            )}
          </div>
        </div>
      )}

      {actionErr && <div className="px-4 py-2 text-sm text-err">{actionErr}</div>}
      {/* The house state lines; the bundle's list has a spinner and no failure line, so they carry the label. */}
      {replyQ.error && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-err">
          Failed to load: {replyQ.error.message || "unknown"}
        </div>
      )}
      {replyQ.isLoading && replies.length === 0 && (
        <div title={EXTRA_LABEL} className="px-4 py-2 text-sm text-fg-dim">Loading…</div>
      )}
      {/* #50 */}
      {!replyQ.isLoading && !replyQ.error && rows.length === 0 && (
        <EmptyState size="sm" text="No data" />
      )}
      <ul aria-label="Scripts list">
        {rows.map(({ r, stepLabel }) => (
          <ScriptRow
            key={r.id}
            r={r}
            stepLabel={stepLabel}
            accountId={accountId}
            expanded={expanded}
            checked={checked.has(r.id)}
            onCheck={(on) => dispatch({ type: "check", ids: [r.id], on })}
            onEdit={() => startEditReply(r)}
            onShare={() => setDialog({ kind: "share", ids: [r.id] })}
            onDelete={() => (removeLabel ? removeScripts([r.id]) : deleteScripts([r.id]))}
            removeLabel={removeLabel}
            onOpenChip={(kind, name) => dispatch({ type: "open", kind, name })}
            busy={busyIds.has(r.id)}
          />
        ))}
      </ul>
    </div>
  );

  return (
    // The bundle's page frame: the header, the toolbar and the list run flush across the page, each band ruled off
    // by a 1px bottom border (#18), in no card.
    <div className="flex flex-col min-h-[calc(100dvh-var(--shell-top,3.5rem))]">
      {/* #3, #4: 16px, weight 600, 24px to the creator selector. #7: the tools 24px tall, 16px apart, at the right.
          #11: the bundle shows Share before the script tour has run (`localStorage` "ScriptTour") or to a role with
          ShareScript; ours shows it always (Role enforcement gates the Scripts page as a whole). On a phone the row
          wraps. */}
      <InflowwPageHeader
        title="Scripts"
        className="h-auto min-h-12 flex-wrap gap-y-2 px-3 py-2 sm:h-12 sm:flex-nowrap sm:px-6 sm:py-0"
        actions={
          <div className="flex items-center gap-4 h-6">
            <button type="button" disabled title={NOT_WIRED} className={HEADER_BOX}>
              <BookOpen size={18} className="mr-1" aria-hidden />
              Learn
            </button>
            <button
              type="button"
              disabled={replies.length === 0}
              onClick={() => setDialog({ kind: "share", ids: checkedInList.length ? checkedInList : undefined })}
              className={HEADER_BOX}
            >
              <Share2 size={18} className="mr-1" aria-hidden />
              Share
            </button>
            <MoreMenu
              onAddScript={addScript}
              onAddSequence={() => setNamePrompt({ kind: "sequence" })}
              onAddTag={() => setNamePrompt({ kind: "tag" })}
              onImportExcel={() => setDialog({ kind: "excel" })}
              onImportCreators={() => setDialog({ kind: "import" })}
            />
          </div>
        }
      />

      <CreatorRail creators={{ accounts, value: accountId, onChange: pickCreator }} className="flex flex-col">
        {/* #18: 56px tall, 0 24px padding, a 1px bottom border; on a phone 12px, wrapping the right box under the tabs. */}
        <div className="min-h-14 px-3 sm:px-6 py-2 sm:py-0 flex flex-wrap items-center gap-y-2 border-b border-border">
          {view === "manage" ? (
            // #31, #32: Manage scripts swaps the tabs for a back arrow and its title.
            <div className="flex items-center gap-4">
              <button type="button" aria-label="Back" onClick={() => dispatch({ type: "view", view: "tags" })} className="text-fg-dim hover:text-fg">
                <ArrowLeft size={20} aria-hidden />
              </button>
              <h2 className="text-base font-semibold">Manage scripts</h2>
            </div>
          ) : (
            <div role="tablist" aria-label="Scripts" className="flex items-center gap-4 sm:gap-6">
              {(
                [
                  ["tags", "Tag", List],
                  ["sequences", "Sequence", Workflow],
                ] as const
              ).map(([key, label, Icon]) => (
                // #21 to #25: 14px, weight 700, a 24px icon 8px from the text.
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={view === key}
                  onClick={() => dispatch({ type: "view", view: key })}
                  className={cn(
                    "h-14 flex items-center gap-2 text-sm font-bold border-b-2",
                    view === key ? "text-fg border-accent" : "text-fg border-transparent",
                  )}
                >
                  <Icon size={24} aria-hidden />
                  {label}
                </button>
              ))}
            </div>
          )}
          <div className="ml-auto flex items-center">
            {/* #26, #27: a 24px search icon, 16px, a 1px by 18px divider, 16px. */}
            {searchOpen && (
              <input
                type="search"
                autoFocus
                aria-label="Search scripts"
                placeholder="Search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="mr-2 w-36 sm:w-48 rounded-md border border-border bg-transparent px-2 py-1 text-sm"
              />
            )}
            <button
              type="button"
              aria-label="Search"
              aria-pressed={searchOpen}
              onClick={() => {
                if (searchOpen) setQ("");
                setSearchOpen((o) => !o);
              }}
              className="mr-4 text-fg-dim hover:text-fg"
            >
              <Search size={24} aria-hidden />
            </button>
            <span aria-hidden className="w-px h-[18px] bg-border mr-4" />
            {/* #28, #29: a 28px pill, 0 8px padding, 4px radius, 14px weight 400. */}
            <button
              type="button"
              aria-pressed={view === "manage"}
              onClick={() => dispatch({ type: "view", view: view === "manage" ? "tags" : "manage" })}
              className="h-7 px-2 whitespace-nowrap rounded text-sm font-normal text-accent bg-bg-elev-2 [html[data-theme=light]_&]:bg-[#eff4ff]"
            >
              Manage scripts
            </button>
          </div>
        </div>

        {showEmptyPanel ? (
          <SequenceEmpty onCreate={() => setNamePrompt({ kind: "sequence" })} />
        ) : sideKind === null ? (
          list
        ) : (
          <div className="flex flex-1 flex-col md:flex-row">
            <Sidebar
              kind={sideKind}
              items={sideKind === "tag" ? tagItems : seqItems}
              selected={sideKind === "tag" ? activeTag : activeSeq}
              onSelect={(id) => dispatch({ type: "open", kind: sideKind, name: id })}
              onRename={(i) => setNamePrompt({ kind: "rename", entry: sideKind, from: i.name })}
              onDelete={(i) => deleteEntry(sideKind, i.name)}
            />
            {list}
          </div>
        )}
      </CreatorRail>

      {draft?.kind === "reply" && (
        <ScriptEditModal
          title={draft.id != null ? "Edit script" : "Add script"}
          saving={saving}
          onClose={() => setDraft(null)}
        >
          <TemplateDraftEditor
            script
            draft={draft}
            setDraft={setDraft}
            accountId={accountId}
            saving={saving}
            saveErr={saveErr}
            onSave={save}
            tagOptions={tagNames}
            sequenceOptions={seqNames}
          />
        </ScriptEditModal>
      )}

      {namePrompt && <NameModal {...promptProps(namePrompt)} onClose={() => setNamePrompt(null)} />}
      {dialog?.kind === "excel" && <ExcelImportDialog accountId={accountId} onClose={() => setDialog(null)} />}
      {(dialog?.kind === "import" || dialog?.kind === "share") && (
        <CopyScriptsDialog
          mode={dialog.kind}
          accountId={accountId}
          accounts={accounts}
          ids={dialog.kind === "share" ? dialog.ids : undefined}
          onClose={() => setDialog(null)}
          onCopied={dialog.kind === "share" ? clearSelection : undefined}
        />
      )}
    </div>
  );
}
