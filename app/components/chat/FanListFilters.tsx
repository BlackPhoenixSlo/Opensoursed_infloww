"use client";


import { ChevronDown, ListFilter, Mail, Pencil, RotateCw, Settings } from "lucide-react";
import type { BlurMode } from "@/hooks/useBlurMode";
import type { ChatFolder } from "@/hooks/useChatFolders";
import type { ChatSortMode } from "@/hooks/useChatSortMode";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import { ExtraMenuRow } from "./ExtraMenuRow";
import type { FanListChipSet } from "./fanListChips";
import { MENU, MENU_ITEM } from "./MenuParts";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.fanList;
const O = MP.ours.FanListFilters;

const SETTINGS_ROW = cn(MENU_ITEM, "cursor-pointer select-none");

const MENU_SUB_LINE = cn(O.menuSubLine, "text-fg-dim");

const CHIP_SCROLLER = cn(O.chipScroller, "flex min-w-0 items-center overflow-x-auto no-scrollbar");

const ICON_BUTTON = cn(G.gear, O.gear, "grid place-items-center border-border");
const ICON_IDLE = "text-fg-dim hover:text-fg hover:bg-bg-elev-1";
const ICON_ACTIVE = "bg-accent text-white border-accent";

const PIN_LISTS = "Pin lists as chips";

export function MenuDivider() {
  return <div role="separator" className={cn(MP.menu.divider, "bg-border")} />;
}

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
const NEWEST_FIRST: ChatSortMode = "recent";
const EXTRA_SORT_ORDERS = (["spend", "spend-unread", "hybrid"] as const)
  .map((key) => ({ key, ...SORT_ORDERS[key] }));

type SortChoice = {
  sortMode: ChatSortMode;
  onSortModeChange: (next: ChatSortMode) => void;
};

// `owe-reply` is client-side only: OF has no filter for "fan sent last, we haven't replied", so FanList fetches all and filters locally.
type BuiltinFilter = "all" | "unread" | "pinned" | "who_tipped" | "unread_tips" | "priority" | "owe-reply";

export type ActiveChip =
  | { kind: "builtin"; key: BuiltinFilter }
  | { kind: "folder"; listId: string };

type GearSettings = {
  markingAll: boolean;
  hasUnread: boolean;
  onMarkAllRead: () => void;
  keepDrawerOpen: boolean;
  onKeepDrawerOpenChange: (next: boolean) => void;
  blurMode: BlurMode;
  onBlurModeChange: (next: BlurMode) => void;
  compactMedia: boolean;
  onCompactMediaChange: (next: boolean) => void;
  onSelectChats: () => void;
};

export function FanListFilters({
  active, onActiveChange, unreadCount, unreadAge, activeCount, oweReplyCount,
  pinnedFolders, hasLists, onOpenFolderPicker,
  showInboxSelector, groupCount, group, groupLocked = false, onGroupChange, onOpenSplitInbox,
  fetching, onRefresh, sortMode, onSortModeChange, chips, ...gear
}: {
  active: ActiveChip;
  onActiveChange: (next: ActiveChip) => void;
  unreadCount: number;
  unreadAge?: ChipAge | null;
  activeCount: number;
  oweReplyCount: number;
  pinnedFolders: ChatFolder[];
  hasLists: boolean;
  onOpenFolderPicker: () => void;
  showInboxSelector: boolean;
  groupCount: number;
  group: number | null;
  groupLocked?: boolean;
  onGroupChange: (group: number | null) => void;
  onOpenSplitInbox: (() => void) | null;
  fetching: boolean;
  onRefresh: () => void;
  chips: FanListChipSet;
} & SortChoice & GearSettings) {
  return (
    <>
      <div role="group" aria-label="Inbox, settings and sort" className={cn(G.filters, "relative flex flex-wrap items-center")}>
        {showInboxSelector && (
          <InboxSelector
            groupCount={groupCount}
            group={group}
            locked={groupLocked}
            onGroupChange={onGroupChange}
            onOpenSettings={onOpenSplitInbox}
          />
        )}
        <GearMenu {...gear} />
        <SortControl sortMode={sortMode} onSortModeChange={onSortModeChange} />
        {hasLists && (
          <button
            type="button"
            onClick={onOpenFolderPicker}
            className={cn(ICON_BUTTON, ICON_IDLE)}
            title={PIN_LISTS}
            aria-label={PIN_LISTS}
          >
            <Pencil className={G.gearIcon} />
          </button>
        )}
        <div className="flex-1" />
        <div className={cn(G.sort, "flex items-center text-fg-dim")}>
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
      <div role="group" aria-label="Fan List filters" className={cn(G.chips, O.rowPull, "flex items-center")}>
        <div className={CHIP_SCROLLER}>
          <BuiltinChip filter="all" active={active} onActiveChange={onActiveChange}>All</BuiltinChip>
          <BuiltinChip
            filter="owe-reply" active={active} onActiveChange={onActiveChange} count={oweReplyCount} amber
            title={extraTitle("Owe reply", "Chats where the fan sent the last message and we haven't replied")}
          >Owe reply</BuiltinChip>
          {chips.pinned && (
            <BuiltinChip filter="pinned" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>Pinned</BuiltinChip>
          )}
          <BuiltinChip filter="unread" active={active} onActiveChange={onActiveChange} count={unreadCount} age={unreadAge}>Unread</BuiltinChip>
          {chips.who_tipped && (
            <BuiltinChip filter="who_tipped" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>With Tips</BuiltinChip>
          )}
          {chips.unread_tips && (
            <BuiltinChip filter="unread_tips" active={active} onActiveChange={onActiveChange} activeCount={activeCount}>Unread with tips</BuiltinChip>
          )}
          {pinnedFolders.map((f) => {
            const id = String(f.id);
            const isActive = active.kind === "folder" && active.listId === id;
            return (
              <FilterChip
                key={id}
                active={isActive}
                onClick={() => onActiveChange(isActive ? { kind: "builtin", key: "all" } : { kind: "folder", listId: id })}
                title={f.name || `List #${id}`}
                count={isActive ? activeCount : null}
              >
                <span className="sr-only">Folder</span>{" "}{f.name || `List #${id}`}
              </FilterChip>
            );
          })}
          {chips.priority && (
            <BuiltinChip
              filter="priority" active={active} onActiveChange={onActiveChange} activeCount={activeCount}
              title={extraTitle("Priority chip")}
            >Priority</BuiltinChip>
          )}
        </div>
      </div>
    </>
  );
}

function InboxSelector({
  groupCount, group, locked, onGroupChange, onOpenSettings,
}: {
  groupCount: number;
  group: number | null;
  locked: boolean;
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
        disabled={locked}
        title={locked ? "Your inbox, set by the owner (Split Inbox)" : "Choose which inbox to show (Split Inbox)"}
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

function GearMenu({
  markingAll, hasUnread, onMarkAllRead,
  keepDrawerOpen, onKeepDrawerOpenChange, blurMode, onBlurModeChange,
  compactMedia, onCompactMediaChange, onSelectChats,
}: GearSettings) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  return (
    <div ref={ref} className="md:relative">
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
        <section {...menuProps} aria-label="Inbox settings" className={cn(MENU, O.gearMenuPlace)}>
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
        </section>
      )}
    </div>
  );
}

function SortControl({ sortMode, onSortModeChange }: SortChoice) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const label = `Sort: ${SORT_ORDERS[sortMode].label}`;
  const extra = sortMode !== NEWEST_FIRST;
  const choose = (next: ChatSortMode) => { setOpen(false); onSortModeChange(next); };
  const mark = (key: ChatSortMode) => (
    <span aria-hidden className="w-4 shrink-0 text-center">{sortMode === key ? "✓" : ""}</span>
  );
  return (
    <div ref={ref}>
      <button
        type="button"
        {...triggerProps}
        aria-pressed={extra}
        className={cn(ICON_BUTTON, extra ? ICON_ACTIVE : ICON_IDLE)}
        title={label}
        aria-label={label}
      >
        <ListFilter className={G.gearIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="Sort" className={cn(MENU, O.sortMenuPlace)}>
          <div className={cn(MP.menu.head, "uppercase text-fg-dim")}>Sort by</div>
          <button
            type="button"
            onClick={() => choose(NEWEST_FIRST)}
            aria-pressed={sortMode === NEWEST_FIRST}
            className={MENU_ITEM}
          >
            {mark(NEWEST_FIRST)}
            <span>{SORT_ORDERS[NEWEST_FIRST].label}</span>
          </button>
          {EXTRA_SORT_ORDERS.map((opt) => (
            <ExtraMenuRow
              key={opt.key}
              name="Extra sort orders"
              detail={opt.old}
              pressed={sortMode === opt.key}
              onClick={() => choose(opt.key)}
            >
              {mark(opt.key)}
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

function BuiltinChip({
  filter, active, onActiveChange, count, activeCount, title, amber, age, children,
}: {
  filter: BuiltinFilter;
  active: ActiveChip;
  onActiveChange: (next: ActiveChip) => void;
  count?: number;
  activeCount?: number;
  title?: string;
  amber?: boolean;
  age?: ChipAge | null;
  children: React.ReactNode;
}) {
  const isActive = active.kind === "builtin" && active.key === filter;
  return (
    <FilterChip
      active={isActive}
      onClick={() => onActiveChange({ kind: "builtin", key: filter })}
      count={count ?? (isActive ? activeCount : null)}
      title={title}
      amber={amber}
      age={age}
    >{children}</FilterChip>
  );
}

type ChipAge = { text: string; title: string };

function FilterChip({
  active, onClick, children, title, count, amber, age,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
  count?: number | null;
  amber?: boolean;
  age?: ChipAge | null;
}) {
  const showCount = count != null && count > 0;
  return (
    <button
      type="button"
      onClick={onClick}
      title={age?.title ?? title}
      aria-pressed={active}
      className={cn(
        G.chip, O.chip,
        "relative shrink-0 inline-flex items-center whitespace-nowrap transition-colors",
        active ? "bg-accent text-white" : "bg-[var(--inf-chip,var(--color-bg-elev-2))] text-fg hover:bg-[var(--inf-chip-hover,var(--color-border-light))]",
      )}
    >
      {children}
      {showCount && " "}
      {showCount && (
        <span className={cn(G.chipBadge, O.chipBadge, "absolute grid place-items-center", amber ? "bg-warn text-bg" : "bg-err text-white")}>
          {count}
        </span>
      )}
      {age && " "}
      {age && (
        <span className={cn(O.chipAge, active ? "text-white/80" : "text-fg-dim")}>
          {age.text}
        </span>
      )}
    </button>
  );
}
