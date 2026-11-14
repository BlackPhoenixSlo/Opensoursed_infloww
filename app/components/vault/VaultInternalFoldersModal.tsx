"use client";

/**
 * Inflowwww folders: our own vault folders (the `AI-…` script and lane folders, the Feet pack's rungs, the
 * operator's), opened and edited like the vault, whether or not they were ever published to OnlyFans. Opened from
 * the Extras drawer.
 *
 * Left, the folders in three sections (Yours / AI folders / Feet pack) with their counts, price and an "on OF"
 * mark, under "All media" (the whole vault, the source to add from). Right, the open folder as the vault's own tiles:
 * click one for the vault's viewer, or Select and remove, copy, move or reorder the ticks. A phone shows one pane at
 * a time (the list, then the folder with a back arrow).
 *
 * Every write changes our DB only (`service/vault_internal_folders.py`); nothing here is written to OnlyFans.
 * Two rules the relay keeps and the folder's header says first (`kindNote`): editing a generated folder makes it the
 * operator's, so Build AI folders no longer rewrites it; a Feet pack rung takes edits through the pack's own rules.
 * State and rules: `internalFoldersState.ts`.
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Folder, FolderPlus, Images, Pencil, Sparkles, Tag, Trash2, X } from "lucide-react";

import { VaultVideoPreview } from "@/components/chat/VaultPicker";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { useModalFocus } from "@/components/ui/ifModal";
import { IfButton, IfModal } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatPrice } from "@/components/vault/folderPriceForm";
import { FolderPriceModal } from "@/components/vault/VaultFolderRail";
import VaultItemModal from "@/components/vault/VaultItemModal";
import VaultTile from "@/components/vault/VaultTile";
import { type Tile } from "@/components/vault/vaultManageActions";
import { setFolderPrice, useFolderPrices } from "@/hooks/useFolderPrices";
import {
  internalFolders, invalidateInternalFolders, useInternalFolders, type InternalFolder,
} from "@/hooks/useInternalFolders";
import { useThumbAutoRefresh } from "@/hooks/useThumbAutoRefresh";
import { mirrorItemsKey, useMirrorItems } from "@/hooks/useVaultCache";
import { BRAND_NAME } from "@/lib/brand";
import { errText } from "@/lib/errText";
import { cn } from "@/lib/utils";

import {
  addedNote, ALL, barActions, buildAdd, buildRemove, buildReorder, countsText, errorNote, foldersReducer, INITIAL,
  kindNote, nameError, reorderTarget, sections, type Action, type FolderType, type OpenId, type ReorderDir,
} from "./internalFoldersState";

export const FOLDERS_TITLE = `${BRAND_NAME} folders`;

const TYPES: { value: FolderType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "photo", label: "Photos" },
  { value: "video", label: "Videos" },
];

const KIND_ICON = { own: Folder, ai: Sparkles, pack: Images } as const;

const BAR_BTN =
  "h-8 px-2.5 rounded-md text-[13px] border border-border bg-bg-elev-1 text-fg hover:border-fg-dim disabled:opacity-40 disabled:pointer-events-none";

/** "on OF" / "not on OF": whether the folder was ever published as an OnlyFans list. */
function OfMark({ on }: { on: boolean }) {
  return (
    <span
      title={on ? "Published to OnlyFans as a list. Edits here stay in " + BRAND_NAME + "." : `Only in ${BRAND_NAME}`}
      className={cn(
        "shrink-0 rounded-full px-1.5 text-[11px] leading-[18px]",
        on ? "bg-ok/10 text-ok" : "bg-bg-elev-2 text-fg-dim",
      )}
    >
      {on ? "on OF" : "not on OF"}
    </span>
  );
}

function PriceMark({ cents }: { cents: number }) {
  return (
    <span
      title="Full AI Chat sells this folder at this price"
      className="shrink-0 rounded-full bg-accent/10 px-1.5 text-[11px] font-medium leading-[18px] text-accent"
    >
      {formatPrice(cents)}
    </span>
  );
}

/** One folder in the list: name (two lines at most; the AI ones are long), counts, price, the OF mark. */
function FolderRow({ folder, price, open, onOpen }: {
  folder: InternalFolder; price: number | undefined; open: boolean; onOpen: () => void;
}) {
  const Icon = KIND_ICON[folder.kind];
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-current={open || undefined}
      data-testid={`if-folder-${folder.id}`}
      className={cn(
        "w-full flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
        open ? "bg-accent/10" : "hover:bg-bg-elev-1",
      )}
    >
      <Icon size={16} aria-hidden className={cn("mt-0.5 shrink-0", open ? "text-accent" : "text-fg-dim")} />
      <span className="min-w-0 flex-1">
        <span className={cn("block text-sm font-medium leading-snug line-clamp-2 break-words", open && "text-accent")}>
          {folder.name}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-dim">
          <span>{countsText(folder)}</span>
          {price != null && <PriceMark cents={price} />}
          <OfMark on={folder.of_list_id != null} />
        </span>
      </span>
    </button>
  );
}

/** "New folder" / "Rename folder": one field; Save is off while the name is blank, taken or unchanged. */
function NameDialog({ folder, list, busy, error, onSave, onCancel }: {
  folder: InternalFolder | null;
  list: readonly InternalFolder[];
  busy: boolean;
  /** The relay's refusal of the last Save (a rung's reserved name). */
  error: string;
  onSave: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(folder?.name ?? "");
  const trimmed = name.trim();
  const problem = nameError(name, list, folder?.id ?? null);
  const canSave = !problem && trimmed !== folder?.name && !busy;
  return (
    <IfModal
      title={folder ? "Rename folder" : "New folder"}
      width={480}
      onClose={onCancel}
      footer={
        <>
          <IfButton onClick={onCancel}>Cancel</IfButton>
          <IfButton variant="primary" disabled={!canSave} onClick={() => onSave(trimmed)}>
            {busy ? "Saving…" : "Save"}
          </IfButton>
        </>
      }
    >
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSave) onSave(trimmed);
        }}
      >
        <label className="block space-y-2">
          <span className="block text-sm font-medium">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            autoFocus
            placeholder="beach set"
            className="w-full h-9 px-[11px] rounded-md text-base md:text-sm bg-bg border border-border hover:border-accent focus:border-accent outline-none"
          />
        </label>
        {/* A blank field says nothing: the button is off. */}
        {trimmed && (problem || error) && <p className="text-sm text-err">{problem || error}</p>}
        <p className="text-xs text-fg-dim">Kept in {BRAND_NAME} only. Nothing is created on OnlyFans.</p>
      </form>
    </IfModal>
  );
}

/** Pick the folder the ticks go to. */
function TargetDialog({ title, folders, busy, error, onPick, onCancel }: {
  title: string;
  folders: readonly InternalFolder[];
  busy: boolean;
  /** Why the last pick was refused (a rung's rule): said here, the dialog stays for another pick. */
  error: string;
  onPick: (f: InternalFolder) => void;
  onCancel: () => void;
}) {
  return (
    <IfModal title={title} width={480} onClose={onCancel}>
      {error && <p role="alert" className="mb-3 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-sm text-err">{error}</p>}
      <div className="-my-2 max-h-[60vh] overflow-y-auto">
        {folders.map((f) => {
          const Icon = KIND_ICON[f.kind];
          return (
            <button
              key={f.id}
              type="button"
              disabled={busy}
              onClick={() => onPick(f)}
              className="w-full flex items-center gap-3 px-2 py-3 border-b border-border last:border-b-0 text-left hover:bg-bg-elev-2 disabled:opacity-50"
            >
              <Icon size={16} aria-hidden className="shrink-0 text-fg-dim" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium line-clamp-2 break-words">{f.name}</span>
                <span className="block text-xs text-fg-dim">{countsText(f)}</span>
              </span>
            </button>
          );
        })}
      </div>
    </IfModal>
  );
}

export default function VaultInternalFoldersModal({ accountId, onClose }: { accountId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(foldersReducer, INITIAL);
  const { openId, type, draft, query, selectMode, selected, dialog, busy, notice } = state;

  const foldersQ = useInternalFolders(accountId);
  const list = useMemo(() => foldersQ.data?.list ?? [], [foldersQ.data]);
  const prices = useFolderPrices(accountId).data ?? {};
  const folder = typeof openId === "number" ? list.find((f) => f.id === openId) ?? null : null;
  const total = useMemo(
    () => list.reduce((n, f) => n + f.items, 0),
    [list],
  );

  // The open folder was deleted elsewhere (another tab, a rebuild): back to the list.
  useEffect(() => {
    if (typeof openId === "number" && foldersQ.isSuccess && !foldersQ.isFetching && !folder) {
      dispatch({ type: "open", id: null });
    }
  }, [openId, folder, foldersQ.isSuccess, foldersQ.isFetching]);

  const src = useMirrorItems({
    accountId, type, query, sort: "newest",
    internalFolderId: typeof openId === "number" ? openId : null,
    enabled: openId !== null,
  });
  const items = src.items as Tile[];
  const thumbs = useThumbAutoRefresh(accountId, "mirror");
  const filtered = type !== "all" || !!query;
  const can = barActions(openId, list.length, filtered);
  const selectedIds = useMemo(() => new Set(selected.keys()), [selected]);

  // The search box: typed text settles into the view's query after a pause.
  useEffect(() => {
    const t = window.setTimeout(() => dispatch({ type: "query", value: draft.trim() }), 300);
    return () => window.clearTimeout(t);
  }, [draft]);

  // The viewer and the full-screen player over it.
  const [preview, setPreview] = useState<Tile | null>(null);
  const [playMedia, setPlayMedia] = useState<Tile | null>(null);
  const previewIdx = preview ? items.findIndex((m) => m.id === preview.id) : -1;

  const boxRef = useRef<HTMLDivElement>(null);
  // Escape steps back one view: the folder (on a phone that is the whole screen), then the editor.
  useModalFocus(boxRef, () => (selectMode ? dispatch({ type: "toggleSelectMode" }) : onClose()));

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [openId, type, query]);
  function onGridScroll() {
    const el = scrollRef.current;
    if (el && src.hasMore && !src.isFetchingNextPage && el.scrollHeight - el.scrollTop - el.clientHeight < 600) src.loadMore();
  }

  /** One write: busy, the call, every reader refetched, then the line it says (or why it failed). */
  async function write(label: string, call: () => Promise<Omit<Extract<Action, { type: "done" }>, "type">>) {
    if (busy) return;
    dispatch({ type: "start", busy: label });
    try {
      const done = await call();
      await invalidateInternalFolders(qc, accountId);
      dispatch({ type: "done", ...done });
    } catch (e) {
      dispatch({ type: "failed", text: errorNote(errText(e, "")) });
    }
  }

  const create = (name: string) =>
    write("Creating…", async () => {
      const r = await internalFolders.create(accountId, name);
      return { text: `Created ${r.name}`, openId: r.folder_id };
    });
  const rename = (f: InternalFolder, name: string) =>
    write("Renaming…", async () => {
      await internalFolders.rename(accountId, f.id, name);
      return { text: `Renamed to ${name}` };
    });
  async function remove(f: InternalFolder) {
    const ok = await ifConfirm(
      `Delete the folder "${f.name}"? Its ${f.items === 1 ? "item stays" : `${f.items} items stay`} in the vault.` +
        (f.of_list_id != null ? " The OnlyFans list it was published to is left as it is." : ""),
      { confirmLabel: "Delete folder", danger: true },
    );
    if (!ok) return;
    await write("Deleting…", async () => {
      await internalFolders.remove(qc, accountId, f.id);
      return { text: `Deleted ${f.name}`, openId: null as OpenId };
    });
  }
  const take = (f: InternalFolder) =>
    write("Removing…", async () => {
      const r = await internalFolders.take(f.id, buildRemove(accountId, selected));
      return { text: `Removed ${r.removed} from ${f.name}` };
    });
  const addTo = (target: InternalFolder, moveFrom: number | null) =>
    write(moveFrom === null ? "Adding…" : "Moving…", async () => {
      const r = await internalFolders.add(target.id, buildAdd(accountId, selected, moveFrom));
      return { text: addedNote(r, target.name, moveFrom !== null) };
    });
  function reorder(f: InternalFolder, dir: ReorderDir) {
    const target = reorderTarget(items, selectedIds, dir, src.hasMore);
    if (!target) return;
    void write("Reordering…", async () => {
      await internalFolders.reorder(f.id, buildReorder(accountId, target));
      return { text: "Order saved", keepSelection: true };
    });
  }

  const open = (id: OpenId) => dispatch({ type: "open", id });
  const title = openId === ALL ? "All media" : folder?.name ?? "";
  const note = folder ? kindNote(folder.kind) : "";
  const targets = list.filter((f) => f.id !== openId);
  const refusal = notice?.tone === "err" ? notice.text : "";

  return (
    <div
      className="fixed inset-x-0 top-[var(--vvt,0px)] z-50 h-[var(--vvh,100dvh)] flex items-center justify-center bg-black/70 md:p-6"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={FOLDERS_TITLE}
        tabIndex={-1}
        className="relative flex h-full w-full flex-col overflow-hidden bg-panel outline-none shadow-2xl pt-[env(safe-area-inset-top)] md:pt-0 md:h-[min(900px,100%)] md:max-w-[1360px] md:rounded-[10px] md:border md:border-border"
      >
        <header className="shrink-0 flex items-center gap-2 border-b border-border px-3 md:px-5 h-[52px]">
          {openId !== null && (
            <button
              type="button"
              aria-label="Back to folders"
              onClick={() => open(null)}
              className="md:hidden grid h-8 w-8 shrink-0 place-items-center rounded-md text-fg-dim hover:text-fg hover:bg-bg-elev-1"
            >
              <ArrowLeft size={18} aria-hidden />
            </button>
          )}
          <div className="min-w-0 flex-1">
            <h2 className={cn("text-[16px] font-semibold text-fg truncate", openId !== null && "max-md:hidden")}>
              {FOLDERS_TITLE}
            </h2>
            {openId !== null && <p className="md:hidden text-[15px] font-semibold text-fg truncate">{title}</p>}
          </div>
          <p className="hidden md:block text-xs text-fg-dim">Edits stay in {BRAND_NAME}. Nothing is written to OnlyFans.</p>
          <button
            type="button"
            aria-label="Close"
            title="Close (Esc)"
            onClick={onClose}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-fg-dim hover:text-fg hover:bg-bg-elev-1"
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        {notice && (
          <div
            role="status"
            data-testid="if-notice"
            className={cn(
              "shrink-0 flex items-start gap-2 px-3 md:px-5 py-2 text-sm border-b",
              notice.tone === "ok" ? "border-ok/30 bg-ok/10 text-ok" : "border-err/30 bg-err/10 text-err",
            )}
          >
            <span className="min-w-0 flex-1 break-words">{notice.text}</span>
            <button type="button" aria-label="Dismiss" onClick={() => dispatch({ type: "dismissNotice" })} className="shrink-0 opacity-70 hover:opacity-100">
              <X size={14} aria-hidden />
            </button>
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          {/* ── The folders ── */}
          <nav
            aria-label="Folders"
            className={cn(
              "min-h-0 w-full md:w-[320px] md:shrink-0 md:border-r md:border-border flex-col",
              openId === null ? "flex" : "hidden md:flex",
            )}
          >
            <div className="min-h-0 flex-1 overflow-y-auto p-2.5 space-y-4">
              <p className="md:hidden px-2.5 text-xs text-fg-dim">Edits stay in {BRAND_NAME}. Nothing is written to OnlyFans.</p>
              <button
                type="button"
                onClick={() => open(ALL)}
                aria-current={openId === ALL || undefined}
                data-testid="if-folder-all"
                className={cn(
                  "w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left",
                  openId === ALL ? "bg-accent/10 text-accent" : "hover:bg-bg-elev-1",
                )}
              >
                <Images size={16} aria-hidden className={openId === ALL ? "text-accent" : "text-fg-dim"} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">All media</span>
                  <span className="block text-xs text-fg-dim">The whole vault. Pick here, add to a folder.</span>
                </span>
              </button>

              {foldersQ.isPending ? (
                <div role="status" aria-label="Loading folders" className="space-y-2 px-2.5">
                  {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
                </div>
              ) : foldersQ.isError ? (
                <p className="px-2.5 text-sm text-err">Couldn&apos;t load the folders.</p>
              ) : list.length === 0 ? (
                <p className="px-2.5 text-sm text-fg-dim">
                  No folders yet. Make one below, or build them from the Extras drawer (Build AI folders, Feet pack).
                </p>
              ) : (
                sections(list).map((s) => (
                  <section key={s.kind} aria-label={s.title}>
                    <h3 title={s.hint} className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
                      {s.title} <span className="font-normal">· {s.folders.length}</span>
                    </h3>
                    <div className="space-y-0.5">
                      {s.folders.map((f) => (
                        <FolderRow key={f.id} folder={f} price={prices[`vf:${f.id}`]} open={f.id === openId} onOpen={() => open(f.id)} />
                      ))}
                    </div>
                  </section>
                ))
              )}
            </div>
            <div className="shrink-0 border-t border-border p-2.5 pb-[calc(env(safe-area-inset-bottom)+10px)] md:pb-2.5">
              <button
                type="button"
                disabled={!!busy}
                onClick={() => dispatch({ type: "dialog", dialog: { kind: "create" } })}
                className="w-full inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-accent/50 bg-accent/10 text-sm font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
              >
                <FolderPlus size={16} aria-hidden />
                New folder
              </button>
              {list.length > 0 && (
                <p className="mt-1.5 text-center text-[11px] text-fg-dim">
                  {list.length} {list.length === 1 ? "folder" : "folders"} · {total} filed
                </p>
              )}
            </div>
          </nav>

          {/* ── The open folder ── */}
          <section
            aria-label={title || "Folder"}
            className={cn("relative min-h-0 min-w-0 flex-1 flex-col", openId === null ? "hidden md:flex" : "flex")}
          >
            {openId === null ? (
              <div className="grid flex-1 place-items-center p-8 text-center">
                <div className="max-w-[340px] space-y-2">
                  <Folder size={28} aria-hidden className="mx-auto text-fg-dim" />
                  <p className="text-sm font-medium">Open a folder to see and edit what is in it</p>
                  <p className="text-xs text-fg-dim">
                    Or open All media, tick what you want and add it to a folder.
                  </p>
                </div>
              </div>
            ) : (
              <>
                <div className="shrink-0 space-y-2 border-b border-border px-3 md:px-5 py-2.5">
                  <div className="hidden md:flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <h3 className="text-[15px] font-semibold leading-snug break-words">{title}</h3>
                      {folder && (
                        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-dim">
                          <span>{countsText(folder)}</span>
                          {prices[`vf:${folder.id}`] != null && <PriceMark cents={prices[`vf:${folder.id}`]} />}
                          <OfMark on={folder.of_list_id != null} />
                        </p>
                      )}
                    </div>
                  </div>
                  {folder && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <p className="md:hidden mr-auto flex flex-wrap items-center gap-1.5 text-xs text-fg-dim">
                        <span>{countsText(folder)}</span>
                        {prices[`vf:${folder.id}`] != null && <PriceMark cents={prices[`vf:${folder.id}`]} />}
                        <OfMark on={folder.of_list_id != null} />
                      </p>
                      {folder.kind !== "pack" && (
                        <button type="button" disabled={!!busy} className={BAR_BTN}
                          onClick={() => dispatch({ type: "dialog", dialog: { kind: "rename", folderId: folder.id } })}>
                          <Pencil size={13} aria-hidden className="inline -mt-0.5 mr-1" />Rename
                        </button>
                      )}
                      <button type="button" disabled={!!busy} className={BAR_BTN}
                        onClick={() => dispatch({ type: "dialog", dialog: { kind: "price", folderId: folder.id } })}>
                        <Tag size={13} aria-hidden className="inline -mt-0.5 mr-1" />
                        {prices[`vf:${folder.id}`] != null ? "Change price" : "Set price"}
                      </button>
                      {folder.kind !== "pack" && (
                        <button type="button" disabled={!!busy} onClick={() => void remove(folder)}
                          className={cn(BAR_BTN, "border-err/40 text-err hover:border-err")}>
                          <Trash2 size={13} aria-hidden className="inline -mt-0.5 mr-1" />Delete
                        </button>
                      )}
                    </div>
                  )}
                  {note && <p data-testid="if-kind-note" className="text-xs text-fg-dim">{note}</p>}
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={draft}
                      onChange={(e) => dispatch({ type: "draft", value: e.target.value })}
                      placeholder="Search descriptions and tags"
                      aria-label="Search this folder"
                      className="h-8 min-w-0 flex-1 basis-[160px] px-[11px] rounded-md text-base md:text-sm bg-bg border border-border hover:border-accent focus:border-accent outline-none"
                    />
                    <div role="group" aria-label="Media type" className="inline-flex rounded-md border border-border p-0.5">
                      {TYPES.map((t) => (
                        <button
                          key={t.value}
                          type="button"
                          aria-pressed={type === t.value}
                          onClick={() => dispatch({ type: "mediaType", value: t.value })}
                          className={cn(
                            "h-7 px-2.5 rounded text-[13px]",
                            type === t.value ? "bg-accent/15 text-accent font-medium" : "text-fg-dim hover:text-fg",
                          )}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      aria-pressed={selectMode}
                      onClick={() => dispatch({ type: "toggleSelectMode" })}
                      className={cn(BAR_BTN, selectMode && "border-accent bg-accent/10 text-accent")}
                    >
                      <Check size={13} aria-hidden className="inline -mt-0.5 mr-1" />
                      {selectMode ? "Done" : "Select"}
                    </button>
                    {selectMode && items.length > 0 && (
                      <button type="button" className={BAR_BTN} onClick={() => dispatch({ type: "selectAll", media: items })}>
                        All {items.length}
                      </button>
                    )}
                  </div>
                </div>

                <div ref={scrollRef} onScroll={onGridScroll} className="min-h-0 flex-1 overflow-y-auto px-3 md:px-5 py-3 pb-28">
                  {src.isLoading ? (
                    <div role="status" aria-label="Loading" className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
                      {Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="aspect-square w-full rounded-lg" />)}
                    </div>
                  ) : src.error ? (
                    <p className="py-10 text-center text-sm text-err">Couldn&apos;t load this folder.</p>
                  ) : items.length === 0 ? (
                    <div className="py-14 text-center">
                      <p className="text-sm font-medium">{filtered ? "Nothing matches" : "This folder is empty"}</p>
                      {!filtered && folder && (
                        <p className="mt-1 text-xs text-fg-dim">
                          Open <button type="button" className="text-accent hover:underline" onClick={() => open(ALL)}>All media</button>, tick what belongs here and add it.
                        </p>
                      )}
                    </div>
                  ) : (
                    <>
                      <div data-testid="if-grid" className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
                        {items.map((m, i) => (
                          <div key={m.id} className="relative" data-testid={`if-tile-${m.id}`}>
                            <VaultTile
                              media={m}
                              accountId={accountId}
                              onClick={(x) => setPreview(x as Tile)}
                              onPlay={(x) => setPlayMedia(x as Tile)}
                              selectMode={selectMode}
                              checked={selected.has(m.id)}
                              onCheck={(x) => dispatch({ type: "toggle", media: x })}
                              thumbs={thumbs}
                            />
                            {/* The folder's order, 1-based, beside the tile's described dot; hidden under a filter (the numbers
                                would skip). */}
                            {folder && !filtered && (
                              <span className="pointer-events-none absolute top-1 left-[18px] min-w-[18px] rounded bg-black/65 px-1 text-center text-[10px] font-medium leading-[16px] text-white">
                                {i + 1}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                      <div className="pt-3 text-center text-xs text-fg-dim">
                        {src.isFetchingNextPage ? (
                          <Skeleton className="mx-auto h-3 w-16" />
                        ) : src.hasMore ? (
                          <button type="button" onClick={() => src.loadMore()} className="px-3 py-1.5 rounded-lg border border-border bg-bg-elev-1 hover:text-fg">
                            {items.length} shown · load more
                          </button>
                        ) : (
                          `${items.length} shown`
                        )}
                      </div>
                    </>
                  )}
                </div>

                {selected.size > 0 && (
                  <div
                    data-testid="if-selection-bar"
                    className="absolute bottom-3 left-3 right-3 md:left-5 md:right-5 z-10 rounded-lg border border-accent/40 bg-panel/95 backdrop-blur-sm px-3 py-2 mb-[env(safe-area-inset-bottom)] flex flex-wrap items-center gap-x-2 gap-y-1.5"
                  >
                    <span data-testid="if-selected-count" className="mr-1 text-sm font-medium">
                      {busy || `Selected ${selected.size}`}
                    </span>
                    {can.add && (
                      <button type="button" disabled={!!busy} className={cn(BAR_BTN, "border-accent/60 text-accent")}
                        onClick={() => dispatch({ type: "dialog", dialog: { kind: "target", mode: "copy" } })}>
                        Add to folder…
                      </button>
                    )}
                    {folder && can.remove && (
                      <button type="button" disabled={!!busy} className={BAR_BTN} onClick={() => void take(folder)}
                        title="Take them out of this folder. They stay in the vault.">
                        Remove
                      </button>
                    )}
                    {can.copy && (
                      <button type="button" disabled={!!busy} className={BAR_BTN}
                        onClick={() => dispatch({ type: "dialog", dialog: { kind: "target", mode: "copy" } })}>
                        Copy to…
                      </button>
                    )}
                    {can.move && (
                      <button type="button" disabled={!!busy} className={BAR_BTN}
                        onClick={() => dispatch({ type: "dialog", dialog: { kind: "target", mode: "move" } })}>
                        Move to…
                      </button>
                    )}
                    {folder && can.reorder && (
                      <span role="group" aria-label="Reorder" className="inline-flex items-center gap-1">
                        {(["first", "earlier", "later", "last"] as const).map((dir) => (
                          <button
                            key={dir}
                            type="button"
                            disabled={!!busy || !reorderTarget(items, selectedIds, dir, src.hasMore)}
                            onClick={() => reorder(folder, dir)}
                            className={BAR_BTN}
                          >
                            {dir === "first" ? "First" : dir === "earlier" ? "← Earlier" : dir === "later" ? "Later →" : "Last"}
                          </button>
                        ))}
                      </span>
                    )}
                    {folder && !can.reorder && <span className="text-xs text-fg-dim">Clear the filter to reorder</span>}
                    <button type="button" className="ml-auto h-8 px-2 text-[13px] text-fg-dim hover:text-fg"
                      onClick={() => dispatch({ type: "clearSelection" })}>
                      Clear
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {dialog?.kind === "create" && (
        <NameDialog folder={null} list={list} busy={!!busy} error={refusal} onSave={create} onCancel={() => dispatch({ type: "dialog", dialog: null })} />
      )}
      {dialog?.kind === "rename" && folder && (
        <NameDialog folder={folder} list={list} busy={!!busy} error={refusal} onSave={(name) => rename(folder, name)} onCancel={() => dispatch({ type: "dialog", dialog: null })} />
      )}
      {dialog?.kind === "price" && folder && (
        <FolderPriceModal
          key={folder.id}
          name={folder.name}
          priceRef={`vf:${folder.id}`}
          current={prices[`vf:${folder.id}`] ?? null}
          onSave={async (body) => {
            await setFolderPrice(qc, body);
            dispatch({ type: "dialog", dialog: null });
          }}
          onCancel={() => dispatch({ type: "dialog", dialog: null })}
        />
      )}
      {dialog?.kind === "target" && (
        <TargetDialog
          title={openId === ALL ? "Add to folder" : dialog.mode === "move" ? "Move to folder" : "Copy to folder"}
          folders={targets}
          busy={!!busy}
          error={refusal}
          onPick={(f) => addTo(f, dialog.mode === "move" && typeof openId === "number" ? openId : null)}
          onCancel={() => dispatch({ type: "dialog", dialog: null })}
        />
      )}

      {preview && !selectMode && (
        <VaultItemModal
          media={preview}
          accountId={accountId}
          prev={previewIdx > 0 ? items[previewIdx - 1] : null}
          next={previewIdx >= 0 && previewIdx < items.length - 1 ? items[previewIdx + 1] : null}
          onStep={setPreview}
          onClose={() => setPreview(null)}
          onEscape={() => (playMedia ? setPlayMedia(null) : setPreview(null))}
          keysOff={!!playMedia}
          onExpand={() => setPlayMedia(preview)}
          onSaved={(updated) => {
            setPreview((p) => (p ? { ...p, _ai: { ...(p._ai ?? {}), ...updated } } : p));
            void qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
          }}
          describeSlot={null}
        />
      )}
      {playMedia && <VaultVideoPreview media={playMedia} accountId={accountId} onClose={() => setPlayMedia(null)} />}
    </div>
  );
}
