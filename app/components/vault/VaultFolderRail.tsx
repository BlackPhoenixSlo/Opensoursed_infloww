"use client";

/**
 * VaultFolderRail — the Vault manager's OnlyFans folder rail, laid out from Vault Pro's Layout capture
 * (`docs/infloww-layouts/growth-vault-pro.md`, #15 to #37; ticket 36).
 *
 * A 208px column: a 48px header row (the folder sort and its popover, search, add category), then "All media" and one
 * row per folder with its counts and its Rename / Delete menu. The header turns into the search box or the Customize
 * order bar while either is on. Every write goes to the same Vault routes as before (`useVaultCache`); the parent
 * owns the folder list and the selected folder, and is told to refresh after a write.
 */

import { type DragEvent as ReactDragEvent, type ReactNode, useState } from "react";
import {
  AudioLines, Check, Coins, Ellipsis, Image as ImageIcon, ImagePlay, ListFilter, LockOpen, Plus, Search, Send, Video, X,
} from "lucide-react";

import { MENU_ITEM, MENU_PANEL, Menu, useOutsideClose } from "@/components/ui/Menu";
import { EmptyState, IfButton, IfModal } from "@/components/ui/infloww";
import { useVaultAccountId } from "@/components/vault/VaultAccount";
import { createOfFolder, deleteOfFolder, renameOfFolder, sortOfFolders } from "@/hooks/useVaultCache";
import { type FanId } from "@/lib/fanId";
import { type VaultList } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";

/** The rail column (#16): 208px with a 1px L1 right rule on the page colour (B-nav), stacked over the grid on a
 *  phone. Exported so the page's no-Creator frame draws the same column. */
export const RAIL_CLASS =
  "w-full md:w-52 shrink-0 max-h-44 md:max-h-none border-b md:border-b-0 md:border-r border-border bg-bg flex flex-col overflow-hidden";
/** The rail's sort row (#19): 48px tall, 0 16px, the sort left and the icons right. */
export const RAIL_HEAD_CLASS = "h-12 shrink-0 px-4 flex items-center justify-between";
/** A rail row's outer box (#27, #28): 10px either side; the selected row `--tc-M-B` (#353535 dark, #eff4ff light),
 *  the others T1 with `--tc-M-B1` on hover. */
export function railRowClass(selected: boolean): string {
  return cn(
    "w-full px-[10px] text-fg transition-colors",
    selected
      ? "bg-bg-elev-2 [html[data-theme=light]_&]:bg-[#eff4ff]"
      : "hover:bg-[#2f2f2f] [html[data-theme=light]_&]:hover:bg-bg-elev-1",
  );
}
/** A rail row's inner box (#27): 14px 4px 14px 10px, a 6px gap, a 1px L1 rule under it. */
export const RAIL_ROW_INNER = "py-[14px] pl-[10px] pr-1 border-b border-border flex flex-col gap-1.5";
/** The rail's 30px round icon boxes (#23 to #25). */
export const RAIL_ICON_BOX =
  "w-[30px] min-w-[30px] h-[30px] grid place-items-center rounded-[20px] text-fg-dim hover:text-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-fg-dim";

/** The rail's folder sort (Layout capture growth-vault-pro#20, #22): the OF folder-list sort the relay's
 *  `/admin/vault-ai/of-folders/sort` sets. "Default" ascending until one is picked: no read reports OF's current
 *  folder sort, so the label is the last sort set from this page. */
type FolderSort = "default" | "name" | "recent" | "media" | "custom";
type FolderOrder = "asc" | "desc";
const FOLDER_SORTS: { value: FolderSort; label: string }[] = [
  { value: "default", label: "Default" },
  { value: "name", label: "Name" },
  { value: "recent", label: "Recent" },
  { value: "media", label: "Media" },
  { value: "custom", label: "Custom" },
];
const SORT_READ_NOT_WIRED = "The sort last set here. Reading back the sort OnlyFans has stored: not wired";
const FOLDER_ORDERS:{ value: FolderOrder; label: string }[] = [
  { value: "asc", label: "Ascending" },
  { value: "desc", label: "Descending" },
];

/** A folder's counts (#30, #31): photo, video, audio and GIF, each behind its icon (20px, audio 16px), split by
 *  "·" with a 2px gap; "empty" when all are 0. Also the "Add to category" modal's rows (`MoveModalItem`). */
export function FolderCounts({ f }: { f: VaultList }) {
  const parts: [string, ReactNode, number][] = [
    ["photo", <ImageIcon key="i" size={20} aria-hidden />, f.photosCount ?? 0],
    ["video", <Video key="i" size={20} aria-hidden />, f.videosCount ?? 0],
    ["audio", <AudioLines key="i" size={16} aria-hidden />, f.audiosCount ?? 0],
    ["gif", <ImagePlay key="i" size={20} aria-hidden />, f.gifsCount ?? 0],
  ];
  const shown = parts.filter(([, , n]) => n > 0);
  return (
    <div className="flex items-center gap-0.5 text-xs text-muted">
      {shown.length === 0
        ? "empty"
        : shown.map(([kind, icon, n], i) => (
            <span key={kind} className="flex items-center gap-0.5">
              {i > 0 && <span aria-hidden>·</span>}
              <span className="flex items-center" title={kind}>
                {icon}
                {n}
              </span>
            </span>
          ))}
    </div>
  );
}

/** A folder's statistics (#33): send count, unlock rate and revenue, each behind a 12px icon. No read reports a
 *  folder's sends, unlocks or revenue, so the line is Not wired and shows no figure. */
function FolderStats() {
  return (
    <div aria-label="Statistics" title="not wired" className="flex items-center gap-3 text-xs text-muted">
      <span className="flex items-center gap-1"><Send size={12} aria-hidden />—</span>
      <span className="flex items-center gap-1"><LockOpen size={12} aria-hidden />—</span>
      <span className="flex items-center gap-1"><Coins size={12} aria-hidden />—</span>
    </div>
  );
}

/** The rail's two modals (#36, #37): antd's modal at 480px, "Cancel" then the confirm. */
function RailModal({ title, children, confirm, onCancel }: {
  title: string;
  children: ReactNode;
  confirm: ReactNode;
  onCancel: () => void;
}) {
  return (
    <IfModal
      title={title}
      width={480}
      onClose={onCancel}
      footer={
        <>
          <IfButton onClick={onCancel}>Cancel</IfButton>
          {confirm}
        </>
      }
    >
      <div className="space-y-3">{children}</div>
    </IfModal>
  );
}

/** "New category" or, given a folder, "Rename category" (#36): field "Category", `maxLength:64`, "Save". Save is
 *  off while the name is blank or unchanged. */
function FolderNameModal({ folder, onSave, onCancel }: {
  folder: VaultList | null;
  onSave: (name: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(folder?.name ?? "");
  const [saving, setSaving] = useState(false);
  const trimmed = name.trim();
  const canSave = !!trimmed && trimmed !== folder?.name && !saving;
  return (
    <RailModal
      title={folder ? "Rename category" : "New category"}
      onCancel={onCancel}
      confirm={
        <IfButton
          variant="primary"
          disabled={!canSave}
          onClick={async () => {
            setSaving(true);
            await onSave(trimmed);
          }}
        >
          Save
        </IfButton>
      }
    >
      <label className="block space-y-2">
        <span className="block text-sm font-medium">Category</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Enter category name"
          maxLength={64}
          autoFocus
          className="w-full h-8 px-[11px] rounded-md text-base md:text-sm bg-bg border border-border hover:border-accent focus:border-accent outline-none"
        />
      </label>
    </RailModal>
  );
}

/** "Delete category" (#37). It removes the folder only. The bundle's option to also remove the folder's media from
 *  the vault (shown only for a folder with media, index.9f50f370.js @6836258) is Not wired: a permanent media wipe
 *  from one box is left to the owner (see the recheck record). */
function FolderDeleteModal({ folder, onDelete, onCancel }: {
  folder: VaultList;
  onDelete: () => Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const total = (folder.photosCount ?? 0) + (folder.videosCount ?? 0) + (folder.gifsCount ?? 0) + (folder.audiosCount ?? 0);
  return (
    <RailModal
      title="Delete category"
      onCancel={onCancel}
      confirm={
        <IfButton
          variant="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await onDelete();
          }}
          className="bg-err hover:bg-err/90"
        >
          Delete
        </IfButton>
      }
    >
      <p className="text-sm">
        This will permanently remove the category from the vault. This action cannot be undone.
      </p>
      {total > 0 && (
        <label className="flex items-center gap-2 text-sm text-fg-dim">
          <input type="checkbox" disabled title="not wired" />
          Permanently remove all media from the vault
        </label>
      )}
    </RailModal>
  );
}

export default function VaultFolderRail({ folders, loading, error, onRetry, selectedId, onSelect, onChanged }: {
  /** The folders to list, in OF's order. */
  folders: VaultList[];
  loading: boolean;
  /** The folder read failed: the rail shows #35's error and its Refresh (`onRetry`). */
  error: boolean;
  onRetry: () => void;
  /** The folder the grid shows; `null` is "All media". */
  selectedId: FanId | null;
  onSelect: (id: FanId | null) => void;
  /** Called after every folder write, so the parent refetches. */
  onChanged: () => void;
}) {
  const accountId = useVaultAccountId();
  const [customizeOrder, setCustomizeOrder] = useState(false);
  // Folder ids (the drag reorders FOLDERS), so FanId.
  const [localOrder, setLocalOrder] = useState<FanId[] | null>(null);
  const [draggedId, setDraggedId] = useState<FanId | null>(null);
  // The rail's header (#19 to #25): the folder sort and its popover, the folder search, the add icon.
  const [folderSort, setFolderSort] = useState<{ sort: FolderSort; order: FolderOrder }>({
    sort: "default",
    order: "asc",
  });
  const { open: sortOpen, setOpen: setSortOpen, ref: sortRef } = useOutsideClose();
  const [railSearching, setRailSearching] = useState(false);
  const [railSearch, setRailSearch] = useState("");
  // The open rail modal: a new folder (`folder: null`), a rename, or a delete.
  const [nameModal, setNameModal] = useState<{ folder: VaultList | null } | null>(null);
  const [deleteModal, setDeleteModal] = useState<VaultList | null>(null);
  async function onSaveFolderName(name: string) {
    const f = nameModal?.folder;
    if (f) await renameOfFolder(accountId, f.id, name).catch(() => {});
    else await createOfFolder(accountId, name, []).catch(() => {});
    setNameModal(null);
    onChanged();
  }
  async function onDeleteFolder(f: VaultList) {
    await deleteOfFolder(accountId, f.id).catch(() => {});
    if (selectedId === f.id) onSelect(null);
    setDeleteModal(null);
    onChanged();
  }
  /** Set OF's folder-list sort; the label follows only once OF has taken it. */
  async function onSortFolders(next: { sort: FolderSort; order: FolderOrder }) {
    setSortOpen(false);
    try {
      await sortOfFolders(accountId, next);
      setFolderSort(next);
    } catch {
      /* the label stays on the sort OF still has */
    }
    onChanged();
  }
  // ── Customize (drag) folder order → OF customOrder ──────────────
  function startCustomize() {
    setSortOpen(false);
    setLocalOrder(folders.map((f) => f.id));
    setCustomizeOrder(true);
  }
  /** Leave the mode with nothing written: the bundle's close icon (`customize-close`). */
  function cancelCustomize() {
    setCustomizeOrder(false);
    setLocalOrder(null);
    setDraggedId(null);
  }
  /** The bundle's check (`customize-ok`, index.9f50f370.js @6820751): writes the dragged order as OF's custom order
   *  once (`customOrder`, @5094572), and the sort label then reads "Custom". */
  async function doneCustomize() {
    const order = localOrder;
    cancelCustomize();
    if (!order) return;
    try {
      await sortOfFolders(accountId, { customOrder: order });
      setFolderSort((s) => ({ ...s, sort: "custom" }));
    } catch {
      /* OF kept its own order, and the refresh below shows it */
    }
    onChanged();
  }
  function onDragOverFolder(e: ReactDragEvent, overId: FanId) {
    e.preventDefault();
    if (draggedId == null || draggedId === overId || !localOrder) return;
    const arr = [...localOrder];
    const from = arr.indexOf(draggedId);
    const to = arr.indexOf(overId);
    if (from < 0 || to < 0) return;
    arr.splice(from, 1);
    arr.splice(to, 0, draggedId);
    setLocalOrder(arr);
  }
  /** A drop only moves the row on screen; the order is written by the check (`doneCustomize`). */
  function onDropFolder() {
    setDraggedId(null);
  }

  const railQuery = railSearch.trim().toLowerCase();
  const displayFolders =
    customizeOrder && localOrder
      ? (localOrder.map((id) => folders.find((f) => f.id === id)).filter(Boolean) as VaultList[])
      : railQuery
        ? folders.filter((f) => f.name.toLowerCase().includes(railQuery))
        : folders;

  return (
    <>
      {/* LEFT rail — OF folders (Layout capture #15 to #37): 208px with a right rule, a fixed 48px header row,
          then "All media" and the folders, which scroll on their own. */}
      <aside className={RAIL_CLASS}>
        {/* #19: 48px tall, 0 16px, the sort left and the icons right. It turns into the search box (#23) or the
            Customize order bar (#22) while either is on. */}
        <div className={RAIL_HEAD_CLASS}>
          {railSearching ? (
            <>
              <button
                type="button"
                aria-label="Close search"
                onClick={() => {
                  setRailSearch("");
                  setRailSearching(false);
                }}
                className={RAIL_ICON_BOX}
              >
                <X size={20} aria-hidden />
              </button>
              <input
                value={railSearch}
                onChange={(e) => setRailSearch(e.target.value)}
                placeholder="Search"
                maxLength={100}
                autoFocus
                className="mx-1 w-full px-2 py-1 rounded-lg text-base md:text-sm bg-bg border border-border focus:border-accent outline-none"
              />
            </>
          ) : customizeOrder ? (
            <>
              {/* #22's Customize order bar (index.9f50f370.js @6820132): a 20px close that drops the drag, the text,
                  and an 18px check that writes it. */}
              <button
                type="button"
                aria-label="Cancel"
                onClick={cancelCustomize}
                className={RAIL_ICON_BOX}
              >
                <X size={20} aria-hidden />
              </button>
              <span className="flex-1 text-[13px] font-medium text-fg">Customize order</span>
              <button
                type="button"
                aria-label="Done"
                onClick={doneCustomize}
                className="w-[30px] h-[30px] grid place-items-center text-accent"
              >
                <Check size={18} aria-hidden />
              </button>
            </>
          ) : (
            <>
              {/* #20 to #22: the current sort's name and its icon open the sort popover. "Default" at first, as
                  in the capture; the bundle then shows the sort OnlyFans has stored, from its list read
                  (`jn.sort||Lt`, index.9f50f370.js @5087418), which ours does not carry, so the title says so. */}
              <div ref={sortRef} className="relative flex-1 flex items-center">
                <button
                  type="button"
                  title={SORT_READ_NOT_WIRED}
                  aria-haspopup="menu"
                  aria-expanded={sortOpen}
                  onClick={() => setSortOpen((o) => !o)}
                  className="group flex items-center"
                >
                  <span className="text-[13px] font-medium text-fg group-hover:text-accent">
                    {FOLDER_SORTS.find((o) => o.value === folderSort.sort)?.label}
                  </span>
                  <span className="ml-2 w-6 h-6 grid place-items-center rounded-[20px] text-fg-dim group-hover:text-accent group-hover:bg-accent/10">
                    <ListFilter size="1em" aria-hidden />
                  </span>
                </button>
                {sortOpen && (
                  <div role="menu" className={cn(MENU_PANEL, "left-0 top-full w-40")}>
                    {FOLDER_SORTS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        role="menuitemradio"
                        aria-checked={folderSort.sort === o.value}
                        onClick={() => onSortFolders({ sort: o.value, order: folderSort.order })}
                        className={cn(MENU_ITEM, "hover:bg-bg-elev-1", folderSort.sort === o.value && "text-accent")}
                      >
                        {o.label}
                      </button>
                    ))}
                    <div className="my-1 border-t border-border" />
                    {FOLDER_ORDERS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        role="menuitemradio"
                        aria-checked={folderSort.order === o.value}
                        onClick={() => onSortFolders({ sort: folderSort.sort, order: o.value })}
                        className={cn(MENU_ITEM, "hover:bg-bg-elev-1", folderSort.order === o.value && "text-accent")}
                      >
                        {o.label}
                      </button>
                    ))}
                    <div className="my-1 border-t border-border" />
                    {/* HTML5 drag never fires on touch, and while the mode is on a folder tap stops opening the
                        folder — so the item is desk-only. Off while the rail is filtered, as the bundle has it. */}
                    <button
                      type="button"
                      role="menuitem"
                      onClick={startCustomize}
                      disabled={!!railQuery}
                      className={cn(MENU_ITEM, "hidden md:block", railQuery ? "text-fg-dim cursor-not-allowed" : "hover:bg-bg-elev-1")}
                    >
                      Customize order
                    </button>
                  </div>
                )}
              </div>
              {/* #23 to #25: search (20px icon) and add category (16px icon) in 30px boxes. */}
              <div className="flex items-center">
                <button
                  type="button"
                  aria-label="Search"
                  onClick={() => setRailSearching(true)}
                  className={RAIL_ICON_BOX}
                >
                  <Search size={20} aria-hidden />
                </button>
                <button
                  type="button"
                  aria-label="New category"
                  onClick={() => setNameModal({ folder: null })}
                  className={RAIL_ICON_BOX}
                >
                  <Plus size={16} aria-hidden />
                </button>
              </div>
            </>
          )}
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          {/* #26, #27: "All media", then one row per folder: 10px outer padding, 14px 4px 14px 10px inside, a
              6px gap and a rule under each. #28: the selected row is tinted. */}
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={cn(railRowClass(selectedId === null), "text-left")}
          >
            <div className={RAIL_ROW_INNER}>
              <div className="text-sm font-medium">All media</div>
              {/* The bundle's "All media" counts are the vault-wide type totals (#30, #58; `classifyListsAll`,
                  index.9f50f370.js @5087418). No read reports them, so the row says Not wired, and the media tabs
                  stay on under All media. */}
              <div className="text-xs text-muted" title="not wired">—</div>
            </div>
          </button>
          {loading ? (
            <div className="space-y-2 px-3 py-3" aria-busy="true">
              {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : error ? (
            /* #35: the rail's error and its Refresh. */
            <EmptyState
              kind="error"
              size="sm"
              className="px-4"
              text="An error occurred when retrieving media. Please try refreshing."
              action={<IfButton variant="primary" onClick={onRetry}>Refresh</IfButton>}
            />
          ) : displayFolders.length === 0 ? (
            /* #35: no folders (or none matching the rail's search). */
            <EmptyState size="sm" />
          ) : (
            displayFolders.map((f) => (
              <div
                key={f.id}
                role="button"
                tabIndex={0}
                draggable={customizeOrder}
                onDragStart={customizeOrder ? () => setDraggedId(f.id) : undefined}
                onDragOver={customizeOrder ? (e) => onDragOverFolder(e, f.id) : undefined}
                onDrop={customizeOrder ? onDropFolder : undefined}
                onClick={() => {
                  if (!customizeOrder) onSelect(f.id);
                }}
                className={cn(
                  railRowClass(selectedId === f.id && !customizeOrder),
                  customizeOrder ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
                  draggedId === f.id ? "opacity-50" : "",
                )}
              >
                <div className={RAIL_ROW_INNER}>

                  <div className="flex items-center justify-between">
                    {/* #29: 14px, weight 500, at most 145px with an ellipsis; the full name on hover. */}
                    <div className="text-sm font-medium truncate max-w-[145px]" title={f.name}>
                      {f.name}
                    </div>
                    {customizeOrder ? (
                      <span className="text-fg-dim select-none text-base leading-none">⣿</span>
                    ) : (
                      // #34. The house Menu behind the bundle's 20px icon (`STpMessageMore,{size:20`,
                      // index.9f50f370.js @6802706); its clicks stay inside, so they never select the row.
                      <span className="shrink-0 flex items-center" onClick={(e) => e.stopPropagation()}>
                        <Menu
                          link
                          ariaLabel="More"
                          label={<Ellipsis size={20} aria-hidden />}
                          items={[
                            { label: "Rename", onClick: () => setNameModal({ folder: f }) },
                            { label: "Delete", onClick: () => setDeleteModal(f) },
                          ]}
                        />
                      </span>
                    )}
                  </div>
                  <FolderCounts f={f} />
                  <FolderStats />
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      {nameModal && (
        <FolderNameModal
          key={nameModal.folder?.id ?? "new"}
          folder={nameModal.folder}
          onSave={onSaveFolderName}
          onCancel={() => setNameModal(null)}
        />
      )}
      {deleteModal && (
        <FolderDeleteModal
          folder={deleteModal}
          onDelete={() => onDeleteFolder(deleteModal)}
          onCancel={() => setDeleteModal(null)}
        />
      )}
    </>
  );
}
