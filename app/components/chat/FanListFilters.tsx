"use client";

/**
 * FanListFilters — the Fan List's filter row (the "All inboxes" selector,
 * the gear with the list settings, and the sort line's sort control and
 * refresh icon) and chip row (the OF lists among the chips). Stateless: the parent
 * (FanList) owns the active filter, counts, folders, sort and gear settings
 * and passes them in with their callbacks
 * (docs/spec/phase-02-fan-list-pane.md, Interfaces).
 */

import { useId } from "react";
import { ChevronDown, ListFilter, Mail, RotateCw, Settings } from "lucide-react";
import type { BlurMode } from "@/hooks/useBlurMode";
import type { ChatFolder } from "@/hooks/useChatFolders";
import type { ChatSortMode } from "@/hooks/useChatSortMode";
import { MP } from "@/lib/messagesPro";
import { EXTRAS_OVERFLOW_LABEL, extraTitle } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import { ExtraMenuRow } from "./ExtraMenuRow";
import { FocusModeSettings } from "./FocusModeSettings";
import { MENU, MENU_ITEM } from "./MenuParts";
import type { FocusModeSettings as FocusModeSettingsValue } from "./useFocusModeSettings";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.fanList;
const O = MP.ours.FanListFilters;

/** A settings checkbox row. */
const SETTINGS_ROW = cn(MENU_ITEM, "cursor-pointer select-none");

/** A menu row's sub-line under its name: a sort order's explanation, Focus
 *  mode's hint. */
const MENU_SUB_LINE = cn(O.menuSubLine, "text-fg-dim");

/** A chip scroller: the chips sideways, with no scrollbar instead of
 *  wrapping (mh:141-142). The chip row's and the folder row's. */
const CHIP_SCROLLER = cn(O.chipScroller, "flex min-w-0 items-center overflow-x-auto no-scrollbar");

/** A Fan List menu divider, `.pop .pdiv` (mh:371). The New menu's too. */
export function MenuDivider() {
  return <div role="separator" className={cn(MP.menu.divider, "bg-border")} />;
}

/** The Fan List's sort orders. "Newest first" is Infloww's and the sort
 *  control offers it; the others are Inflowwww's and the "+" Extras
 *  overflow offers them (spec, Filters). `sub` explains an order under its
 *  name; `old` is the old gear option's tooltip, its extra tooltip's second
 *  line. */
const SORT_ORDERS: Record<ChatSortMode, { label: string; sub?: string; old?: string }> = {
  recent: { label: "Newest first" },
  spend: { label: "Amount spent" },
  "spend-unread": {
    label: "Spend + unread on top", sub: "unread → owe reply → idle",
    old: "Unread → owe-reply → idle, spend desc within each tier",
  },
  hybrid: {
    label: "Spend + recency", sub: "spend × time-decay",
    old: "Spend × decay. Half-life: idle 1h, owe-reply 2h, unread 3h. Below $3 effective, unread wins.",
  },
};
/** Infloww's order, the only one the sort control offers. */
const NEWEST_FIRST: ChatSortMode = "recent";
/** Inflowwww's orders, in the "+" overflow, in this order. */
const EXTRA_SORT_ORDERS = (["spend", "spend-unread", "hybrid"] as const)
  .map((key) => ({ key, ...SORT_ORDERS[key] }));

/** The order in force and its callback. */
type SortChoice = {
  sortMode: ChatSortMode;
  onSortModeChange: (next: ChatSortMode) => void;
};

/** Built-in OF chat filters — most are server-side filters supported
 *  by /chats. `owe-reply` is chosen from the Extras overflow and is CLIENT-SIDE only: there's no OF filter for
 *  "fan sent last and we haven't replied," so FanList fetches ALL and
 *  filters locally.
 */
type BuiltinFilter = "all" | "unread" | "pinned" | "who_tipped" | "unread_tips" | "priority" | "owe-reply";

/** Active selection: either a built-in filter or a custom folder by id. */
export type ActiveChip =
  | { kind: "builtin"; key: BuiltinFilter }
  | { kind: "folder"; listId: string };

/** Focus mode works only on the All chip, so with no Chat folder and no Owe
 *  reply, and with "Newest first" (spec, Focus mode), and not while a search
 *  narrows the rows. The Split Inbox group does not matter.
 *  ASSUMPTION: an active search suspends Focus mode, as leaving All does, so
 *  typing narrows the rows and clearing the search freezes again at the live
 *  order. Rung 5 (the spec names only All and Newest first); overturned if
 *  the human wants search to filter the frozen rows instead. */
export function focusModeAvailable(active: ActiveChip, sortMode: ChatSortMode, searching: boolean): boolean {
  return active.kind === "builtin" && active.key === "all" && sortMode === NEWEST_FIRST && !searching;
}

/** Why Focus mode is unavailable, under its disabled checkbox (story 48). */
const FOCUS_MODE_HINT = "Only in All · Newest first";

/** The gear's list settings and their callbacks. */
type GearSettings = {
  markingAll: boolean;
  /** Some loaded chat is unread, so "Mark all as read" has work to do. */
  hasUnread: boolean;
  onMarkAllRead: () => void;
  keepDrawerOpen: boolean;
  onKeepDrawerOpenChange: (next: boolean) => void;
  blurMode: BlurMode;
  onBlurModeChange: (next: BlurMode) => void;
  compactMedia: boolean;
  onCompactMediaChange: (next: boolean) => void;
  /** Focus mode is on; it freezes the list only while available. */
  focusMode: boolean;
  /** A search query narrows the rows, which suspends Focus mode. */
  searching: boolean;
  onFocusModeChange: (next: boolean) => void;
  /** Focus mode's settings, shown under it while it is on. */
  focusSettings: FocusModeSettingsValue;
  onFocusSettingsChange: (next: FocusModeSettingsValue) => void;
  /** Enter the Fan List's select mode (`FanListBulkBar`). */
  onSelectChats: () => void;
};

export function FanListFilters({
  active, onActiveChange, unreadCount, activeCount, oweReplyCount,
  pinnedFolders, hasLists, onOpenFolderPicker,
  showInboxSelector, groupCount, group, onGroupChange, onOpenSplitInbox,
  fetching, onRefresh, sortMode, onSortModeChange, tipsEnabled, ...gear
}: {
  active: ActiveChip;
  onActiveChange: (next: ActiveChip) => void;
  /** Unread chats in the cached All set; the Unread chip always shows it. */
  unreadCount: number;
  /** Chats needing attention in the active filter's rows. */
  activeCount: number;
  oweReplyCount: number;
  pinnedFolders: ChatFolder[];
  /** The Creator has an OF list, so "✎ Lists" shows (Gap row 16, mj:3067).
   *  Lists are per Creator, so All Models has none. */
  hasLists: boolean;
  onOpenFolderPicker: () => void;
  /** The "All inboxes" selector is per Creator, so All Models hides it. */
  showInboxSelector: boolean;
  /** The Creator's Split Inbox group count; above 1 the selector offers
   *  "Inbox 1" to "Inbox N". */
  groupCount: number;
  /** The chosen group, or null for "All inboxes". */
  group: number | null;
  onGroupChange: (group: number | null) => void;
  /** Open the Split Inbox dialog, offered as "Split Inbox settings". Null
   *  for a chatter-only session, which is not offered it (the relay refuses
   *  a chatter's save anyway). */
  onOpenSplitInbox: (() => void) | null;
  /** The chat list is fetching: the refresh icon spins, disabled. */
  fetching: boolean;
  /** Fetch a fresh list past the relay cache. */
  onRefresh: () => void;
  /** The scoped Creator has tips on (users/me `tipsEnabled`): "Unread with
   *  tips" shows, as OF offers that filter only then. */
  tipsEnabled: boolean;
} & SortChoice & GearSettings) {
  return (
    <>
      {/* The filter row (Gap row 7): selector, gear, spacer, sort line. */}
      <div role="group" aria-label="Inbox, settings and sort" className={cn(G.filters, "flex flex-wrap items-center")}>
        {showInboxSelector && (
          <InboxSelector
            groupCount={groupCount}
            group={group}
            onGroupChange={onGroupChange}
            onOpenSettings={onOpenSplitInbox}
          />
        )}
        <GearMenu {...gear} focusAvailable={focusModeAvailable(active, sortMode, gear.searching)} />
        <div className="flex-1" />
        {/* The sort line (Gap row 10): the sort control, then refresh. */}
        <div className={cn(G.sort, "flex items-center text-fg-dim")}>
          <SortControl sortMode={sortMode} onSortModeChange={onSortModeChange} />
          <button
            type="button"
            onClick={onRefresh}
            disabled={fetching}
            className={cn(O.sortButton, "grid place-items-center hover:text-fg disabled:opacity-50")}
            title="Refresh inbox"
            aria-label="Refresh inbox"
          >
            <RotateCw className={cn(G.sortIcon, fetching && "animate-spin")} />
          </button>
        </div>
      </div>
      {/* The chip row, Infloww's order in one sideways scroller (2026-10-18
       *  capture): All, Pinned, Unread, With Tips (then OF's "Unread with
       *  tips" while the Creator has tips on), then the Creator's pinned
       *  OF lists as plain chips and "✎ Lists" (Gap rows 15-16,
       *  mj:3056-3067), then Priority, an Inflowwww extra; the "+" Extras
       *  overflow is pinned after the scroller. All carries no badge: the
       *  attention count lives in the tab title. */}
      <div role="group" aria-label="Fan List filters" className={cn(G.chips, O.rowPull, "flex items-center")}>
        <div className={CHIP_SCROLLER}>
          <BuiltinChip filter="all" active={active} onActiveChange={onActiveChange}>All</BuiltinChip>
          <BuiltinChip filter="pinned" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>Pinned</BuiltinChip>
          <BuiltinChip filter="unread" active={active} onActiveChange={onActiveChange} count={unreadCount}>Unread</BuiltinChip>
          <BuiltinChip filter="who_tipped" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>With Tips</BuiltinChip>
          {tipsEnabled && (
            <BuiltinChip filter="unread_tips" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>Unread with tips</BuiltinChip>
          )}
          {pinnedFolders.map((f) => {
            const id = String(f.id);
            const isActive = active.kind === "folder" && active.listId === id;
            return (
              <FilterChip
                key={id}
                active={isActive}
                // Re-clicking the active folder clears it (mj:3076).
                onClick={() => onActiveChange(isActive ? { kind: "builtin", key: "all" } : { kind: "folder", listId: id })}
                title={f.name || `List #${id}`}
                count={isActive ? activeCount : null}
              >
                {/* Reads "Folder <name>"; Infloww's list chip shows the name only. */}
                <span className="sr-only">Folder</span>{" "}{f.name || `List #${id}`}
              </FilterChip>
            );
          })}
          {hasLists && (
            <FilterChip folder onClick={onOpenFolderPicker} title="Pick folders to pin as chips">
              ✎ Lists
            </FilterChip>
          )}
          <BuiltinChip
            filter="priority" active={active} onActiveChange={onActiveChange} activeCount={activeCount}
            title={extraTitle("Priority chip")}
          >Priority</BuiltinChip>
        </div>
        <ExtrasOverflow
          oweReplyActive={active.kind === "builtin" && active.key === "owe-reply"}
          oweReplyCount={oweReplyCount}
          onOweReply={() => onActiveChange({ kind: "builtin", key: "owe-reply" })}
          onSortModeChange={onSortModeChange}
        />
      </div>
    </>
  );
}

/** The "All inboxes" selector (Gap row 8). With no Split Inbox it offers
 *  only "All inboxes" as a group (story 10); a split Creator adds "Inbox 1"
 *  to "Inbox N", and the label shows the chosen entry (story 9). Owners also
 *  get "Split Inbox settings" after the groups (story 49); `onOpenSettings`
 *  is null for a chatter-only session. */
function InboxSelector({
  groupCount, group, onGroupChange, onOpenSettings,
}: {
  groupCount: number;
  group: number | null;
  onGroupChange: (group: number | null) => void;
  onOpenSettings: (() => void) | null;
}) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const groups = groupCount > 1 ? Array.from({ length: groupCount }, (_, i) => i + 1) : [];
  const choose = (next: number | null) => { setOpen(false); onGroupChange(next); };
  return (
    <div ref={ref} className="relative flex-1">
      <button
        type="button"
        {...triggerProps}
        className={cn(G.inbox, "w-full flex items-center text-left border-border text-fg hover:border-border-light")}
      >
        <Mail className={cn(G.inboxIcon, "shrink-0 text-fg-dim")} />
        <span className="truncate">{group == null ? "All inboxes" : `Inbox ${group}`}</span>
        <ChevronDown className="size-3.5 shrink-0 ml-auto text-fg-dim" />
      </button>
      {open && (
        <section {...menuProps} aria-label="Inboxes" className={cn(MENU, O.menuPlaceStart)}>
          <div role="group" aria-label="Inbox groups">
            <button type="button" onClick={() => choose(null)} className={MENU_ITEM}>
              All inboxes
            </button>
            {groups.map((g) => (
              <button key={g} type="button" onClick={() => choose(g)} className={MENU_ITEM}>
                Inbox {g}
              </button>
            ))}
          </div>
          {onOpenSettings && (
            <>
              <MenuDivider />
              <button
                type="button"
                onClick={() => { setOpen(false); onOpenSettings(); }}
                className={MENU_ITEM}
              >
                Split Inbox settings
              </button>
            </>
          )}
        </section>
      )}
    </div>
  );
}

/** The icon-only gear (Gap row 9) and its list settings menu. */
function GearMenu({
  markingAll, hasUnread, onMarkAllRead,
  keepDrawerOpen, onKeepDrawerOpenChange, blurMode, onBlurModeChange,
  compactMedia, onCompactMediaChange, focusMode, onFocusModeChange, focusAvailable,
  focusSettings, onFocusSettingsChange, onSelectChats,
}: GearSettings & { focusAvailable: boolean }) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const focusId = useId();
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        {...triggerProps}
        className={cn(G.gear, O.gear, "grid place-items-center border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
        title="Inbox settings"
        aria-label="Inbox settings"
      >
        <Settings className={G.gearIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="Inbox settings" className={cn(MENU, O.menuPlace)}>
          <button
            type="button"
            onClick={() => { setOpen(false); onMarkAllRead(); }}
            disabled={markingAll || !hasUnread}
            className={cn(MENU_ITEM, "disabled:opacity-50")}
          >
            <span className="w-4 text-center">✓</span>
            <span>{markingAll ? "Marking…" : "Mark all as read"}</span>
          </button>
          <button type="button" onClick={() => { setOpen(false); onSelectChats(); }} className={MENU_ITEM}>
            <span className="w-4 text-center">☑</span>
            <span>Select chats</span>
          </button>
          <MenuDivider />
          <label className={SETTINGS_ROW}>
            <input
              type="checkbox"
              checked={keepDrawerOpen}
              onChange={(e) => onKeepDrawerOpenChange(e.target.checked)}
              className="shrink-0"
            />
            <span>Keep fan info panel open</span>
          </label>
          <MenuDivider />
          {/* Image-blur mode. Two checkboxes for the two non-default
           *  modes; checking one unchecks the other so the user
           *  always sees the live state. Applied to chat media tiles
           *  + vault thumbnails via the useBlurMode hook. */}
          <label className={cn(SETTINGS_ROW, "hidden md:flex")}>
            <input
              type="checkbox"
              checked={blurMode === "hover"}
              onChange={(e) => onBlurModeChange(e.target.checked ? "hover" : "off")}
              className="shrink-0"
            />
            <span>Blur images till hover</span>
          </label>
          <label className={SETTINGS_ROW}>
            <input
              type="checkbox"
              checked={blurMode === "constant"}
              onChange={(e) => onBlurModeChange(e.target.checked ? "constant" : "off")}
              className="shrink-0"
            />
            <span>Blur images constant</span>
          </label>
          <MenuDivider />
          <label className={SETTINGS_ROW}>
            <input
              type="checkbox"
              checked={compactMedia}
              onChange={(e) => onCompactMediaChange(e.target.checked)}
              className="shrink-0"
            />
            <span>Compact media previews</span>
          </label>
          <MenuDivider />
          <label className={cn(SETTINGS_ROW, !focusAvailable && "cursor-default")}>
            <input
              type="checkbox"
              checked={focusMode}
              disabled={!focusAvailable}
              // Named by its name alone; the hint is its description.
              aria-labelledby={`${focusId}-name`}
              aria-describedby={focusAvailable ? undefined : `${focusId}-hint`}
              onChange={(e) => onFocusModeChange(e.target.checked)}
              className="shrink-0"
            />
            {/* The hint sits under the name, as a sort order's sub-line
             *  does in the "+" overflow. */}
            <span className="flex flex-col">
              <span id={`${focusId}-name`}>Focus mode</span>
              {!focusAvailable && (
                <span id={`${focusId}-hint`} className={MENU_SUB_LINE}>{FOCUS_MODE_HINT}</span>
              )}
            </span>
          </label>
          {focusMode && focusAvailable && (
            <FocusModeSettings settings={focusSettings} onChange={onFocusSettingsChange} />
          )}
        </section>
      )}
    </div>
  );
}

/** The sort control (Gap row 10): the order in force, then the sort icon.
 *  Its menu offers only Infloww's "Newest first"; the extra orders are in
 *  the "+" Extras overflow (spec, Filters). */
function SortControl({ sortMode, onSortModeChange }: SortChoice) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const label = SORT_ORDERS[sortMode].label;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        {...triggerProps}
        className={cn(G.sort, O.sortButton, "flex items-center whitespace-nowrap hover:text-fg")}
      >
        <span className="text-fg">{label}</span>
        <ListFilter className={G.sortIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="Sort" className={cn(MENU, O.menuPlace)}>
          <button
            type="button"
            onClick={() => { setOpen(false); onSortModeChange(NEWEST_FIRST); }}
            className={MENU_ITEM}
          >
            {SORT_ORDERS[NEWEST_FIRST].label}
          </button>
        </section>
      )}
    </div>
  );
}

/** The "+" that ends the chip row and the Fan List's Extras overflow
 *  (ADR-0003; spec, Filters). "↩ Owe reply" and the extra sort orders are
 *  Inflowwww's, so they are chosen here rather than among Infloww's chips
 *  or in the sort control. While Owe reply is the active filter the "+"
 *  looks active and carries its count in the amber corner badge (Gap row
 *  14). */
function ExtrasOverflow({
  oweReplyActive, oweReplyCount, onOweReply, onSortModeChange,
}: {
  oweReplyActive: boolean;
  oweReplyCount: number;
  onOweReply: () => void;
  onSortModeChange: SortChoice["onSortModeChange"];
}) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  return (
    <div ref={ref} className={cn(O.extrasAnchor, "relative shrink-0")}>
      <FilterChip
        {...triggerProps}
        active={oweReplyActive}
        aria-label={EXTRAS_OVERFLOW_LABEL}
        title={EXTRAS_OVERFLOW_LABEL}
        count={oweReplyActive ? oweReplyCount : null}
        amber
      >+</FilterChip>
      {open && (
        <section {...menuProps} aria-label={EXTRAS_OVERFLOW_LABEL} className={cn(MENU, O.menuPlace)}>
          <ExtraMenuRow
            name="Owe reply"
            detail="Chats where the fan sent the last message and we haven't replied"
            onClick={() => { setOpen(false); onOweReply(); }}
          >
            <span>↩ Owe reply</span>
            {" "}
            <span className="ml-auto text-warn tabular-nums">{oweReplyCount}</span>
          </ExtraMenuRow>
          <MenuDivider />
          <div className={cn(MP.menu.head, "uppercase text-fg-dim")}>Sort by</div>
          {EXTRA_SORT_ORDERS.map((opt) => (
            <ExtraMenuRow
              key={opt.key}
              name="Extra sort orders"
              detail={opt.old}
              onClick={() => { setOpen(false); onSortModeChange(opt.key); }}
            >
              {/* The sub-line explains the order; the space reads it apart
               *  from the name and adds no width in the flex column. */}
              <span className="flex flex-col">
                <span>{opt.label}</span>
                {opt.sub && " "}
                {opt.sub && <span className={MENU_SUB_LINE}>{opt.sub}</span>}
              </span>
            </ExtraMenuRow>
          ))}
        </section>
      )}
    </div>
  );
}

/** A built-in OF filter's chip. `count` is shown always (Unread's);
 *  `activeCount` only while the chip is the active filter. */
function BuiltinChip({
  filter, active, onActiveChange, count, activeCount, title, children,
}: {
  filter: BuiltinFilter;
  active: ActiveChip;
  onActiveChange: (next: ActiveChip) => void;
  count?: number;
  activeCount?: number;
  title?: string;
  children: React.ReactNode;
}) {
  const isActive = active.kind === "builtin" && active.key === filter;
  return (
    <FilterChip
      active={isActive}
      onClick={() => onActiveChange({ kind: "builtin", key: filter })}
      count={count ?? (isActive ? activeCount : null)}
      title={title}
    >{children}</FilterChip>
  );
}

function FilterChip({
  active, onClick, children, title, count, amber, folder,
  "aria-label": ariaLabel, "aria-expanded": ariaExpanded, "aria-controls": ariaControls,
}: {
  /** Absent on a chip that only opens something ("✎ Lists"). */
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
  count?: number | null;
  /** The Clone's `.cbadge.amber` (mh:146): the owe-reply count. */
  amber?: boolean;
  /** A folder row chip, `.fchip` (mh:148, Gap rows 15-16). */
  folder?: boolean;
  /** The chip's accessible name, where its text is not it (the "+"). */
  "aria-label"?: string;
  /** The chip opens a menu: `useFanListMenu`'s `triggerProps`. */
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
}) {
  const showCount = count != null && count > 0;
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      aria-pressed={active}
      aria-expanded={ariaExpanded}
      aria-controls={ariaControls}
      className={cn(
        folder ? cn(G.folderChip, O.folderChip, "border-transparent") : cn(G.chip, O.chip),
        "relative shrink-0 inline-flex items-center whitespace-nowrap transition-colors",
        active ? "bg-accent text-white" : "bg-[var(--inf-chip,var(--color-bg-elev-2))] text-fg hover:bg-[var(--inf-chip-hover,var(--color-border-light))]",
      )}
    >
      {children}
      {/* The space makes the name read "Unread 4"; a flex container
       *  drops whitespace-only text, so it adds no width. */}
      {showCount && " "}
      {showCount && (
        // Unread is `info` like every unread count; owe stays `warn` (spec D6).
        <span className={cn(G.chipBadge, O.chipBadge, "absolute grid place-items-center", amber ? "bg-warn text-bg" : "bg-err text-white")}>
          {count}
        </span>
      )}
    </button>
  );
}
