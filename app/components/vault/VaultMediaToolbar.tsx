"use client";

/**
 * The Vault grid's toolbar, laid out from Vault Pro's Layout capture (`docs/infloww-layouts/growth-vault-pro.md`,
 * #38 to #68; ticket 37): the search box (type select, input, icon) and the sort box with its popover, then the
 * "Media:" tabs, with the media tools (Refresh, Select all, the Grid / Table switch) on the right.
 *
 * What a read backs is wired to the grid's existing state: the Caption search is the grid's search, the tabs are its
 * type filter, "Recent" with Ascending / Descending is its newest / oldest sort, Refresh reloads it and Select all
 * selects what is loaded. The rest is shown with the house marker (disabled, `title="not wired"`, no handler): the
 * Note and Hashtag searches, the date filter, every sort field but Recent, the hide switch, the video length picker
 * and the table view, since no Vault read answers them.
 *
 * `disabled` greys every control (the page's no-Creator frame, where there is no vault to search).
 */

import { CheckSquare, LayoutGrid, List, ListFilter, RotateCw, Search } from "lucide-react";

import { MENU_ITEM, MENU_PANEL, useOutsideClose } from "@/components/ui/Menu";
import { IfSelect, type IfOption } from "@/components/ui/infloww";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

export type MediaType = "all" | "photo" | "video" | "gif" | "audio";
export type MediaSort = "newest" | "oldest";
/** Per-type file counts of the chosen folder; `null` for All media, which has none. */
export type TypeCounts = Partial<Record<Exclude<MediaType, "all">, number>> | null;

/** #57: the capture's tabs, in its order and spelling (`defaultViewTypes`). */
const TYPE_TABS: { key: MediaType; label: string }[] = [
  { key: "all", label: "All" },
  { key: "photo", label: "Photo" },
  { key: "video", label: "Video" },
  { key: "gif", label: "GIF" },
  { key: "audio", label: "Audio" },
];

/** #51: the sort fields. Only Recent has a read (the grid's date order); the statistics fields are listed too. */
const SORT_FIELDS: { label: string; wired: boolean }[] = [
  { label: "Recent", wired: true },
  { label: "Most liked", wired: false },
  { label: "Highest tips", wired: false },
  { label: "Send count", wired: false },
  { label: "Unlock count", wired: false },
  { label: "Revenue", wired: false },
];

/** #52: the directions, over the grid's newest / oldest. */
const DIRECTIONS: { label: string; sort: MediaSort }[] = [
  { label: "Ascending", sort: "oldest" },
  { label: "Descending", sort: "newest" },
];

const SWITCH_TEXT = "Hide content viewed or unlocked by fan, or posted on Creator's feed";

const NOT_WIRED = "not wired";

/** A select option no read backs: listed, off, and titled not wired. */
const notWiredOption = (value: string, label: string): IfOption => ({
  value,
  text: label,
  disabled: true,
  label: <span title={NOT_WIRED}>{label}</span>,
});

/** #41: the search types. Only Caption is the grid's search. */
const SEARCH_TYPES: IfOption[] = [
  { value: "caption", label: "Caption" },
  notWiredOption("note", "Note"),
  notWiredOption("hashtag", "Hashtag"),
];

/** #62: the video length options, on the Video tab only. Only "All" is the grid's read. */
const VIDEO_LENGTHS: IfOption[] = [
  { value: "All", label: "All" },
  ...["< 1 min", "1 - 5 mins", "5 - 10 mins", "> 10 mins"].map((l) => notWiredOption(l, l)),
];

/** The toolbar's 40px boxes (#39, #47): 1px L1 on the page colour (B-nav), radius 8. Exported for the page's
 *  no-Creator frame. */
export const TOOLBAR_BOX = "h-10 rounded-lg border border-border bg-bg";

/** #47 to #53: the sort box, which keeps the field's name ("Recent") and opens the popover. */
function SortBox({ sort, onSort, disabled }: { sort: MediaSort; onSort: (s: MediaSort) => void; disabled?: boolean }) {
  const { open, setOpen, ref } = useOutsideClose();
  const direction = DIRECTIONS.find((d) => d.sort === sort)!.label;
  const radio = (label: string, checked: boolean, onClick?: () => void) => (
    <button
      key={label}
      type="button"
      role="menuitemradio"
      aria-checked={checked}
      disabled={!onClick}
      title={onClick ? undefined : NOT_WIRED}
      onClick={onClick}
      className={cn(
        MENU_ITEM,
        !onClick ? "text-fg-dim cursor-not-allowed" : "hover:bg-bg-elev-1",
        checked && "text-accent",
      )}
    >
      {label}
    </button>
  );
  const close = () => setOpen(false);
  return (
    <div ref={ref} className="relative shrink-0 md:ml-4">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        title={direction}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          TOOLBAR_BOX,
          "inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium hover:border-fg-dim disabled:opacity-50 disabled:cursor-not-allowed",
        )}
      >
        Recent
        <ListFilter size={16} aria-hidden className="text-fg-dim" />
      </button>

      {open && (
        // antd's dropdown: #1f1f1f (white in light), radius 8, no border.
        <div
          role="menu"
          className={cn(
            MENU_PANEL,
            "right-0 top-full w-64 z-20 rounded-lg border-0 bg-[#1f1f1f] [html[data-theme=light]_&]:bg-white max-md:max-h-72 max-md:overflow-y-auto",
          )}
        >
          {/* #50: dates. All time is the grid's only range; Go to date has no read. */}
          {radio("All time", true, close)}
          {radio("Go to date", false)}
          <div className="my-1 border-t border-border" />
          {SORT_FIELDS.map((f) => radio(f.label, f.wired, f.wired ? close : undefined))}
          <div className="my-1 border-t border-border" />
          {DIRECTIONS.map((d) => radio(d.label, d.sort === sort, () => { onSort(d.sort); close(); }))}
          <div className="my-1 border-t border-border" />
          {/* #53: no read reports what a fan viewed or unlocked. */}
          <button
            type="button"
            role="menuitemcheckbox"
            aria-checked={false}
            disabled
            title={NOT_WIRED}
            className={cn(MENU_ITEM, "flex items-center justify-between gap-2 text-fg-dim cursor-not-allowed")}
          >
            <span className="w-[188px]">{SWITCH_TEXT}</span>
            <span aria-hidden className="w-7 h-4 rounded-full bg-bg-elev-1 border border-border shrink-0" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function VaultMediaToolbar({
  search,
  onSearch,
  sort,
  onSort,
  type,
  onType,
  typeCounts,
  loadedCount,
  onRefresh,
  onSelectAll,
  selectMode,
  onToggleSelect,
  disabled = false,
}: {
  search: string;
  onSearch: (s: string) => void;
  sort: MediaSort;
  onSort: (s: MediaSort) => void;
  type: MediaType;
  onType: (t: MediaType) => void;
  typeCounts: TypeCounts;
  /** Files loaded in the grid; Select all shows while at most 40 are (#65). */
  loadedCount: number;
  onRefresh: () => void;
  onSelectAll: () => void;
  selectMode: boolean;
  onToggleSelect: () => void;
  /** Every control off (the no-Creator frame). */
  disabled?: boolean;
}) {
  const iconBox =
    "w-7 h-7 mx-1.5 grid place-items-center rounded-[20px] text-fg-dim hover:text-fg hover:bg-bg-elev-1 disabled:opacity-50 disabled:cursor-not-allowed";
  return (
    <>
      {/* #38: 16px 24px, search left and the sort box right; on a phone the sort box wraps under the search. */}
      <div className="px-3 md:px-6 py-4 flex flex-wrap md:flex-nowrap items-center gap-2 md:gap-0">
        {/* #39 to #46: one bordered box holding the type select, the input and the icon. */}
        <div className={cn(TOOLBAR_BOX, "flex-1 min-w-0 flex items-center")}>
          {/* #41, #42: antd's borderless select, 111px with a right rule, its text M1. */}
          <IfSelect
            aria-label="Search type"
            value="caption"
            options={SEARCH_TYPES}
            onChange={() => {}}
            disabled={disabled}
            className={cn(
              "w-[111px] shrink-0 h-full border-r border-border",
              "[&>button]:h-full [&>button]:rounded-none [&>button]:border-0 [&>button]:bg-transparent",
              "[&>button]:text-[16px] [&>button]:text-accent",
            )}
          />
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            maxLength={100}
            disabled={disabled}
            placeholder="Search media by PPV caption"
            title={`${EXTRA_LABEL}\nAlso matches the AI descriptions and tags of the local mirror`}
            className="flex-1 min-w-0 h-full px-[11px] bg-transparent text-base outline-none placeholder:text-muted disabled:cursor-not-allowed"
          />
          <span aria-hidden className="w-6 h-6 mr-2 shrink-0 grid place-items-center text-accent">
            <Search size={20} />
          </span>
        </div>
        <SortBox sort={sort} onSort={onSort} disabled={disabled} />
      </div>

      {/* #54: 0 24px 16px, the tabs left (scrolling sideways) and the tools right. */}
      <div className="px-3 md:px-6 pb-4 flex flex-wrap md:flex-nowrap items-center justify-between gap-2">
        <div className="md:flex-1 flex items-center min-w-0 max-w-full overflow-x-auto">
          <span className="text-sm mr-2 shrink-0">Media:</span>
          {TYPE_TABS.map((t) => {
            // #58: a type with no files in the chosen folder is off. All media has no per-type count.
            const off = disabled || (t.key !== "all" && typeCounts?.[t.key] === 0);
            const on = type === t.key;
            return (
              <button
                key={t.key}
                type="button"
                aria-pressed={on}
                disabled={off}
                onClick={() => onType(t.key)}
                className={cn(
                  "shrink-0 mr-3 last:mr-0 px-4 py-[3px] rounded-[20px] text-sm leading-5 border transition-colors",
                  off
                    ? "bg-bg-elev-1 text-muted border-transparent cursor-no-drop"
                    : on
                      ? "border-accent text-accent"
                      : "border-border text-fg hover:border-fg-dim",
                )}
              >
                {t.label}
              </button>
            );
          })}
          {type === "video" && (
            <div className="ml-4 shrink-0 flex items-center gap-2 text-sm">
              <span>Video length:</span>
              <IfSelect
                aria-label="Video length"
                value="All"
                options={VIDEO_LENGTHS}
                onChange={() => {}}
                disabled={disabled}
                className="w-[120px]"
              />
            </div>
          )}
        </div>
        {/* #63 to #68: the media tools, 32px tall; icons in 28px boxes. */}
        <div className="h-8 shrink-0 flex items-center">
          <button type="button" aria-label="Refresh" title="Refresh" onClick={onRefresh} disabled={disabled} className={iconBox}>
            <RotateCw size={18} aria-hidden />
          </button>
          {loadedCount <= 40 && (
            <button
              type="button"
              aria-label="Select all"
              title="Select all"
              onClick={onSelectAll}
              disabled={disabled || loadedCount === 0}
              className={iconBox}
            >
              <CheckSquare size={18} aria-hidden />
            </button>
          )}
          <div className="ml-1.5 flex">
            <button
              type="button"
              aria-label="Grid view"
              title="Grid view"
              aria-pressed
              disabled={disabled}
              className="px-1.5 py-0.5 border border-border rounded-l bg-[#666] text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <LayoutGrid size={16} aria-hidden />
            </button>
            {/* #67, #73: no read fills the table's columns (tagged Creators, uploader, notes). */}
            <button
              type="button"
              aria-label="Table view"
              disabled
              title={NOT_WIRED}
              className="px-1.5 py-0.5 border border-l-0 border-border rounded-r text-fg-dim disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <List size={16} aria-hidden />
            </button>
          </div>
          {/* Ours: picking files one by one, which the capture records no control for. */}
          <button
            type="button"
            onClick={onToggleSelect}
            disabled={disabled}
            title={EXTRA_LABEL}
            className={cn(
              "ml-3 px-3 py-1 rounded-lg text-sm border transition-colors disabled:opacity-50 disabled:cursor-not-allowed",

              selectMode ? "bg-accent text-white border-accent" : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg",
            )}
          >
            {selectMode ? "Selecting" : "Select"}
          </button>
        </div>
      </div>
    </>
  );
}
