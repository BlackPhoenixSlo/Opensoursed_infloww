"use client";

/**
 * VaultFolderRail — the Vault manager's OnlyFans folder rail, laid out from Vault Pro's Layout capture
 * (`docs/infloww-layouts/growth-vault-pro.md`, #15 to #37; ticket 36).
 *
 * A 208px column: a 48px header row (the folder sort and its popover, search, add category), then "All media" and one
 * row per folder with its counts, its price chip and its Rename / Set price / Delete menu. The header turns into the search box or the Customize
 * order bar while either is on. Every write goes to the same Vault routes as before (`useVaultCache`); the parent
 * owns the folder list and the selected folder, and is told to refresh after a write.
 */

import { type DragEvent as ReactDragEvent, type ReactNode, useEffect, useReducer, useState } from "react";
import { useIsRestoring, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines, Check, Ellipsis, Image as ImageIcon, ImagePlay, ListFilter, Plus, Search, Video, X,
} from "lucide-react";

import { MENU_ITEM, MENU_PANEL, Menu, useOutsideClose } from "@/components/ui/Menu";
import { EmptyState, IfButton, IfModal, IfNativeSelect } from "@/components/ui/infloww";
import { useVaultAccountId } from "@/components/vault/VaultAccount";
import { downloadLabel, type DlGate } from "@/components/vault/vaultDownloadReducer";
import {
  buildPayload, canSave, folderPriceReducer, formatPrice, initForm,
} from "@/components/vault/folderPriceForm";
import { applyCustomOrder, customizeReducer } from "@/components/vault/vaultFolderOrder";
import {
  FOLDER_ORDERS, FOLDER_SORTS, loadFolderSort, type FolderSortState,
} from "@/components/vault/vaultFolderSort";
import { createOfFolder, deleteOfFolder, renameOfFolder, sortOfFolders } from "@/hooks/useVaultCache";
import { setFolderPrice, useFolderPrices } from "@/hooks/useFolderPrices";
import { vaultListsKey } from "@/hooks/useVaultMedia";
import { useVaultSettings } from "@/hooks/useVaultSettings";
import { invalidateVaultQueries } from "@/lib/vaultInvalidation";
import { type FanId } from "@/lib/fanId";
import { type VaultList, type VaultListsResp, type VaultTypeCounts } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";

/** The rail column (#16): 208px with a 1px L1 right rule on the page colour (B-nav); on a phone a bar over the grid
 *  (the folder select, `VaultFolderRail`). Exported so the page's no-Creator frame draws the same column. */
export const RAIL_CLASS =
  "w-full md:w-52 shrink-0 border-b md:border-b-0 md:border-r border-border bg-bg flex flex-col md:overflow-hidden";
/** The rail's sort row (#19): 48px tall, 0 16px, the sort left and the icons right. */
export const RAIL_HEAD_CLASS = "h-12 shrink-0 px-4 flex items-center justify-between";
export function railRowClass(selected: boolean): string {
  return cn(
    "w-full px-[10px] text-fg transition-colors",
    selected
      ? "bg-bg-elev-2 [html[data-theme=light]_&]:bg-[#eff4ff]"
      : "hover:bg-[#2f2f2f] [html[data-theme=light]_&]:hover:bg-bg-elev-1",
  );
}
export const RAIL_ROW_INNER = "py-[14px] pl-[10px] pr-1 border-b border-border flex flex-col gap-1.5";
export const RAIL_ICON_BOX =
  "w-[30px] min-w-[30px] h-[30px] grid place-items-center rounded-[20px] text-fg-dim hover:text-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-fg-dim";

const SORT_TITLE = "Sort — the name shown is saved in this browser, per Creator (OnlyFans' own sort is not read back)";

export function FolderCounts({ f }: { f: VaultTypeCounts }) {
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

function countsText(f: VaultTypeCounts): string {
  const parts = ([
    [f.photosCount, "photo"], [f.videosCount, "video"], [f.audiosCount, "audio"], [f.gifsCount, "GIF"],
  ] as const).filter(([n]) => (n ?? 0) > 0).map(([n, w]) => `${n} ${w}${n === 1 || w === "audio" ? "" : "s"}`);
  return parts.length ? parts.join(" · ") : "empty";
}

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

// Ours: an agency's folder price lives in our DB only, never written to OnlyFans.
export function FolderPriceModal({ name, priceRef: ref, current, onSave, onCancel }: {
  name: string;
  priceRef: string;
  current: number | null;
  onSave: (body: ReturnType<typeof buildPayload>) => Promise<void>;
  onCancel: () => void;
}) {
  const accountId = useVaultAccountId();
  const priceFinal = !!useVaultSettings(accountId).data?.folder_price_final;
  const [form, dispatch] = useReducer(folderPriceReducer, current, initForm);
  async function write(body: ReturnType<typeof buildPayload>) {
    dispatch({ type: "saving" });
    try {
      await onSave(body);
    } catch {
      dispatch({ type: "failed", error: "Couldn't save the price. Try again." });
    }
  }
  return (
    <RailModal
      title="Set price"
      onCancel={onCancel}
      confirm={
        <>
          {current != null && (
            <IfButton disabled={form.busy} onClick={() => write(buildPayload(accountId, ref, null))}>Clear</IfButton>
          )}
          <IfButton
            variant="primary"
            disabled={!canSave(form, current)}
            onClick={() => write(buildPayload(accountId, ref, form))}
          >
            Save
          </IfButton>
        </>
      }
    >
      {priceFinal ? (
        <>
          <p className="text-sm text-fg-dim">
            Paid sends from <span className="font-medium text-fg">{name}</span> use this saved price. AI pricing and haggling cannot change it.
          </p>
          <p className="text-xs text-fg-dim">If an item matches several priced folders, the highest price applies. Video bundles add their clip prices, up to $200.</p>
        </>
      ) : (
        <p className="text-sm text-fg-dim">
          Full AI Chat sells the items in <span className="font-medium text-fg">{name}</span> at this price.
        </p>
      )}
      <label className="block space-y-2">
        <span className="block text-sm font-medium">Price (USD, $10 to $200)</span>
        <input
          value={form.text}
          onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
          placeholder="25"
          inputMode="decimal"
          maxLength={8}
          autoFocus
          className="w-full h-8 px-[11px] rounded-md text-base md:text-sm bg-bg border border-border hover:border-accent focus:border-accent outline-none"
        />
      </label>
      {form.error && <p className="text-sm text-err">{form.error}</p>}
    </RailModal>
  );
}

function PriceChip({ cents }: { cents: number }) {
  return (
    <span
      title="Full AI Chat sells this folder at this price"
      className="shrink-0 rounded-full bg-accent/10 px-1.5 text-[11px] font-medium leading-[18px] text-accent"
    >
      {formatPrice(cents)}
    </span>
  );
}

// Removes the folder only; the bundle's also-delete-media option is deliberately not wired (a permanent media wipe is left to the owner).
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

export default function VaultFolderRail({
  folders, allCounts = null, loading, error, onRetry, selectedId, onSelect, onChanged, onDownloadFolder,
  downloadFolderGate,
  standardRows, standardMobile, standardSelected = false,
}: {
  folders: VaultList[];
  allCounts?: VaultTypeCounts | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  selectedId: FanId | null;
  onSelect: (id: FanId | null) => void;
  onChanged: () => void;
  onDownloadFolder: (f: VaultList) => void;
  downloadFolderGate: DlGate;
  standardRows?: ReactNode;
  standardMobile?: ReactNode;
  standardSelected?: boolean;
}) {
  const accountId = useVaultAccountId();
  const qc = useQueryClient();
  const [customize, dispatchCustomize] = useReducer(customizeReducer, null);
  const customizeOrder = customize !== null;
  const [folderSort, setFolderSort] = useState<FolderSortState>(() => loadFolderSort(accountId));
  const restoring = useIsRestoring();
  useEffect(() => {
    if (!restoring) void invalidateVaultQueries(qc, { queryKey: vaultListsKey(accountId) }, { cancelRefetch: false });
  }, [qc, accountId, restoring]);
  const { open: sortOpen, setOpen: setSortOpen, ref: sortRef } = useOutsideClose();
  const [railSearching, setRailSearching] = useState(false);
  const [railSearch, setRailSearch] = useState("");
  const [nameModal, setNameModal] = useState<{ folder: VaultList | null } | null>(null);
  const [deleteModal, setDeleteModal] = useState<VaultList | null>(null);
  const [priceModal, setPriceModal] = useState<VaultList | null>(null);
  // `of:<id>` -> cents; undefined while unread or refused (a folder-limited chatter): no chip, no "Set price".
  const prices = useFolderPrices(accountId).data;
  const priceOf = (f: VaultList): number | null => prices?.[`of:${f.id}`] ?? null;
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
  async function onSortFolders(next: FolderSortState) {
    setSortOpen(false);
    try {
      setFolderSort(await sortOfFolders(accountId, next));
    } catch {
    }
    onChanged();
  }
  function startCustomize() {
    setSortOpen(false);
    dispatchCustomize({ type: "start", ids: folders.map((f) => f.id) });
  }
  async function doneCustomize() {
    const order = customize?.order;
    dispatchCustomize({ type: "cancel" });
    if (!order) return;
    try {
      const saved = await sortOfFolders(accountId, { customOrder: order });
      qc.setQueryData<VaultListsResp>(vaultListsKey(accountId), (d) => d && { ...d, list: applyCustomOrder(d.list ?? [], order) });
      setFolderSort(saved);
    } catch {
    }
    onChanged();
  }
  function onDragOverFolder(e: ReactDragEvent, overId: FanId) {
    e.preventDefault();
    dispatchCustomize({ type: "over", id: overId });
  }

  const rowMenuItems = (f: VaultList) => [
    { label: "Rename", onClick: () => setNameModal({ folder: f }) },
    ...(prices ? [{ label: priceOf(f) == null ? "Set price" : "Edit price", onClick: () => setPriceModal(f) }] : []),
    { label: "Delete", onClick: () => setDeleteModal(f) },
    { label: downloadLabel(downloadFolderGate, "folder"),
      onClick: () => onDownloadFolder(f), disabled: !!downloadFolderGate.reason,
      title: downloadFolderGate.reason || undefined },
  ];
  const pickedFolder = selectedId == null ? null : folders.find((f) => f.id === selectedId) ?? null;

  const railQuery = railSearch.trim().toLowerCase();
  const displayFolders =
    customize
      ? (customize.order.map((id) => folders.find((f) => f.id === id)).filter(Boolean) as VaultList[])
      : railQuery
        ? folders.filter((f) => f.name.toLowerCase().includes(railQuery))
        : folders;

  return (
    <>
      {/* LEFT rail — OF folders (Layout capture #15 to #37): 208px with a right rule, a fixed 48px header row,
          then "All media" and the folders, which scroll on their own. */}
      <aside className={RAIL_CLASS}>
        <div className="md:hidden flex items-center gap-1 px-3 py-2">
          <IfNativeSelect
            aria-label="Folder"
            value={selectedId == null ? "" : String(selectedId)}
            onChange={(e) => onSelect(e.target.value === "" ? null : folders.find((f) => String(f.id) === e.target.value)?.id ?? null)}
            className="flex-1 min-w-0 text-base"
          >
            <option value="">{standardSelected ? "Original vault folders" : "All media"}{!standardSelected && allCounts ? ` · ${countsText(allCounts)}` : ""}</option>
            {folders.map((f) => (
              <option key={f.id} value={String(f.id)}>
                {f.name}{priceOf(f) != null ? ` · ${formatPrice(priceOf(f)!)}` : ""} · {countsText(f)}
              </option>
            ))}
          </IfNativeSelect>
          {pickedFolder && (
            <span className="shrink-0 grid h-[30px] w-[30px] place-items-center">
              <Menu link ariaLabel="Folder actions" label={<Ellipsis size={20} aria-hidden />} items={rowMenuItems(pickedFolder)} />
            </span>
          )}
          <button
            type="button"
            aria-label="New category"
            onClick={() => setNameModal({ folder: null })}
            className={RAIL_ICON_BOX}
          >
            <Plus size={16} aria-hidden />
          </button>
        </div>
        <div className="md:hidden">{standardMobile}</div>
        {error && (
          <p className="md:hidden flex items-center gap-2 px-3 pb-2 text-xs text-err">
            Couldn&apos;t load the folders.
            <IfButton variant="link" onClick={onRetry} className="h-auto text-xs">Refresh</IfButton>
          </p>
        )}
        <div data-rail-desk className="max-md:hidden flex flex-1 min-h-0 flex-col">
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
              <button
                type="button"
                aria-label="Cancel"
                onClick={() => dispatchCustomize({ type: "cancel" })}
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
              <div ref={sortRef} className="relative flex-1 flex items-center">
                <button
                  type="button"
                  title={SORT_TITLE}
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
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={cn(railRowClass(selectedId === null && !standardSelected), "text-left")}
          >
            <div className={RAIL_ROW_INNER}>
              <div className="text-sm font-medium">All media</div>
              {allCounts && <FolderCounts f={allCounts} />}
            </div>
          </button>
          {standardRows}
          {loading ? (
            <div className="space-y-2 px-3 py-3" aria-busy="true">
              {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : error ? (
            <EmptyState
              kind="error"
              size="sm"
              className="px-4"
              text="An error occurred when retrieving media. Please try refreshing."
              action={<IfButton variant="primary" onClick={onRetry}>Refresh</IfButton>}
            />
          ) : displayFolders.length === 0 ? (
            <EmptyState size="sm" />
          ) : (
            displayFolders.map((f) => (
              <div
                key={f.id}
                role="button"
                tabIndex={0}
                draggable={customizeOrder}
                onDragStart={customizeOrder ? () => dispatchCustomize({ type: "drag", id: f.id }) : undefined}
                onDragOver={customizeOrder ? (e) => onDragOverFolder(e, f.id) : undefined}
                onDrop={customizeOrder ? () => dispatchCustomize({ type: "drop" }) : undefined}
                onClick={() => {
                  if (!customizeOrder) onSelect(f.id);
                }}
                className={cn(
                  railRowClass(selectedId === f.id && !customizeOrder),
                  customizeOrder ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
                  customize?.dragged === f.id ? "opacity-50" : "",
                )}
              >
                <div className={RAIL_ROW_INNER}>

                  <div className="flex items-center justify-between">
                    {/* #29: 14px, weight 500, at most 145px with an ellipsis; the full name on hover. */}
                    <div className="flex min-w-0 items-center gap-1.5">
                      <div className="text-sm font-medium truncate max-w-[145px]" title={f.name}>
                        {f.name}
                      </div>
                      {priceOf(f) != null && <PriceChip cents={priceOf(f)!} />}
                    </div>
                    {customizeOrder ? (
                      <span className="text-fg-dim select-none text-base leading-none">⣿</span>
                    ) : (
                      <span className="shrink-0 flex items-center" onClick={(e) => e.stopPropagation()}>
                        <Menu link ariaLabel="More" label={<Ellipsis size={20} aria-hidden />} items={rowMenuItems(f)} />
                      </span>
                    )}
                  </div>
                  <FolderCounts f={f} />
                </div>
              </div>
            ))
          )}
        </div>
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
      {priceModal && (
        <FolderPriceModal
          key={priceModal.id}
          name={priceModal.name}
          priceRef={`of:${priceModal.id}`}
          current={priceOf(priceModal)}
          onSave={async (body) => {
            await setFolderPrice(qc, body);
            setPriceModal(null);
          }}
          onCancel={() => setPriceModal(null)}
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
