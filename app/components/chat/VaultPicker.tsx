"use client";


import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ComponentProps, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Captions, Library, Loader2, RefreshCw, Star, X, Zap } from "lucide-react";

import { IfButton, IfSegmented, IfSwitch } from "@/components/ui/infloww";
import { useModalFocus } from "@/components/ui/ifModal";
import { IF_FIELD, IfNativeSelect } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";


import { useQueryClient } from "@tanstack/react-query";
import { revalidateVaultLists, revalidateVaultMediaFirstPage, useChatterFolderAccess, useVaultLists, useVaultMedia } from "@/hooks/useVaultMedia";
import { useThumbAutoRefresh } from "@/hooks/useThumbAutoRefresh";
import { SUMMARY_WAIT_MS, useOfRefresh, vaultPickerSource } from "@/hooks/vaultRefresh";
import { useMirrorItems, useOfSearch, useVaultCacheSummary } from "@/hooks/useVaultCache";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { useVaultMediaStats } from "@/hooks/useVaultMediaStats";
import { useWallMedia } from "@/hooks/useWallMedia";
import { useBlurMode, blurImageClass } from "@/hooks/useBlurMode";
import { type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { perfLog, perfOpId, perfPainted } from "@/lib/perfLog";
import { useInflowwPalette } from "./InflowwPalette";
import { VaultMediaDetails } from "./VaultMediaDetails";
import { DURATION_RANGES, inDurationRange, type DurationRange } from "./vaultDurationFilter";
import { buildPicked, pickedInit, pickedReducer } from "./vaultPickerPicked";
import { VAULT_SHEET } from "./vaultPickerSheet";
import { HOVER_DELAY_MS, useHoverPreview } from "@/hooks/useHoverPreview";
import { KEYBOARD_HINT, PhotoHoverPanel, useGridSelection, usePhotoHover } from "./vaultPickerSelection";
import { STATS_SORTS, isStatsSort, seenByFan, sortByStats } from "./vaultPickerStats";
import { aiCaptionFor, useCaptionOverlay } from "./vaultAiCaption";
import { TILE_HINT, VaultPickerTile } from "./VaultPickerTile";
import { VaultVideoPreview } from "./VaultVideoPreview";
import { resolveStatus } from "./vaultTileStatus";
import { firstUsableFolderId, folderChips, folderSelectItems } from "./vaultPickerFolders";
import { bumpAccountCount, loadAccountCounts, loadFanMru, loadFanState, MRU_CAP, nextMru, saveFanMru, saveFanState } from "./vaultPickerPersist";
import { fetchSort, initialFilters, vaultFiltersReducer, type MediaType, type Sort } from "./vaultPickerFilters";
import { mediaReady, revalidateDue, revalidateInit, revalidateReducer } from "./vaultPickerRevalidate";

export { progressiveVideoSrc, gifClipSrc, videoPosterFrames, isDrmVideo, isDrmOnlyVideo, VaultVideoPreview } from "./VaultVideoPreview";
export { evenFrameIndex } from "./vaultTilePreview";
export { aiCaptionFor, VaultAiCaptionOverlay, useCaptionOverlay, type CaptionSurface } from "./vaultAiCaption";

const TYPE_CHIPS: Array<{ value: MediaType; label: string }> = [
  { value: "all",   label: "All"    },
  { value: "photo", label: "Photos" },
  { value: "video", label: "Videos" },
  { value: "gif",   label: "GIFs"   },
];

export interface VaultPickerSheetClassNames {
  panel: string;
  pickerHead: string;
  pickerTitle: string;
  pickerGrid: string;
  pickerTile: string;
}

interface VaultPickerBaseProps {
  open: boolean;
  onClose: () => void;
  accountId: string | null;
  fanId?: FanId | null;
  initialSelectedIds: number[];
  onConfirm: (picked: VaultMedia[]) => void;
}

export type VaultPickerProps = VaultPickerBaseProps & (
  | { messagesPro?: false }
  | { messagesPro: true; sheet: VaultPickerSheetClassNames }
);

function PickerDialog({ rootRef, onEscape, className, ...rest }: ComponentProps<"div"> & {
  rootRef: RefObject<HTMLDivElement | null>; onEscape: () => void;
}) {
  useModalFocus(rootRef, onEscape);
  return <div ref={rootRef} role="dialog" aria-modal="true" tabIndex={-1} className={cn(className, "outline-none")} {...rest} />;
}

export function VaultPicker(props: VaultPickerProps) {
  const { open, onClose, accountId, fanId = null, initialSelectedIds, onConfirm } = props;
  const rootRef = useRef<HTMLDivElement>(null);
  const sheet = props.messagesPro ? props.sheet : null;
  const messagesPro = sheet !== null;
  const palette = useInflowwPalette();
  const [filters, dispatch] = useReducer(vaultFiltersReducer, initialFilters);
  const { type, listId, sort, hideSeen, lengthRange, queryInput, query } = filters;
  const ofSort = fetchSort(sort);
  useEffect(() => {
    const t = setTimeout(() => dispatch({ type: "commitQuery", value: queryInput }), 300);
    return () => clearTimeout(t);
  }, [queryInput]);
  const [folderMru, setFolderMru] = useState<FanId[]>([]);
  const [picked, pick] = useReducer(pickedReducer, initialSelectedIds, pickedInit);
  const selectedIds = picked.ids;
  const [revalidation, revalidate] = useReducer(revalidateReducer, revalidateInit);

  const listsQ = useVaultLists(accountId, open);
  const folderAccessQ = useChatterFolderAccess(accountId, open);
  const restricted = !!folderAccessQ.data?.restricted;

  const qc = useQueryClient();
  const cacheSummary = useVaultCacheSummary(open ? accountId : null);
  const summaryPending = open && vaultPickerSource(cacheSummary) === "pending";
  const [stalledFor, setStalledFor] = useState<string | null>(null);
  useEffect(() => {
    if (!summaryPending) return;
    const t = setTimeout(() => setStalledFor(accountId), SUMMARY_WAIT_MS);
    return () => clearTimeout(t);
  }, [summaryPending, accountId]);
  const pickerSource = open ? vaultPickerSource(cacheSummary, accountId !== null && stalledFor === accountId) : "live";
  const source = pickerSource === "pending" ? "live" : pickerSource;
  const useLocalVault = pickerSource === "mirror";
  const vaultLive = useVaultMedia({
    accountId, type, listId, sort: ofSort, query,
    enabled: open && pickerSource === "live",
  });
  const vaultMirror = useMirrorItems({
    accountId, type, query, sort: ofSort, ofFolderId: listId, enabled: useLocalVault,
  });
  const vaultShown = useLocalVault ? vaultMirror : vaultLive;
  const vault = pickerSource === "pending" ? { ...vaultShown, isLoading: true } : vaultShown;

  const thumbs = useThumbAutoRefresh(open ? accountId : null, source);

  const ofRefresh = useOfRefresh(open ? accountId : null, thumbs);

  const ofSearch = useOfSearch(accountId, query, useLocalVault);
  const searchingOf = ofSearch.searching;

  const allowedFolders = useMemo(
    () => folderAccessQ.data?.folders ?? [],
    [folderAccessQ.data],
  );
  const allowedFolderIds = useMemo(
    () => new Set(allowedFolders.map((f) => f.folder_id)),
    [allowedFolders],
  );
  const folderItems = useMemo(
    () => folderSelectItems(restricted, allowedFolders, listsQ.data?.list ?? []),
    [restricted, allowedFolders, listsQ.data],
  );

  const deliveredRef = useRef(false);
  useEffect(() => {
    if (!open) {
      deliveredRef.current = false;
      return;
    }
    if (deliveredRef.current) return;
    if (vault.isLoading) return;
    const id = openOpIdRef.current;
    if (!id) return;
    deliveredRef.current = true;
    perfLog(id, "vault.open", "delivered", {
      itemCount: vault.items.length,
      hadError: !!vault.error,
    });
  }, [open, vault.isLoading, vault.items.length, vault.error]);
  const [cosmeticReady, setCosmeticReady] = useState(false);
  useEffect(() => {
    if (!open) {
      setCosmeticReady(false);
      return;
    }
    if (cosmeticReady) return;
    if (vault.isLoading) return;
    setCosmeticReady(true);
  }, [open, vault.isLoading, cosmeticReady]);
  const historyQ = useFanVaultHistory(accountId, fanId ?? null, open && cosmeticReady);
  const historyMap = historyQ.data?.by_media ?? {};
  const statsQ = useVaultMediaStats(accountId, open && (cosmeticReady || isStatsSort(sort)));
  const statsMap = statsQ.data?.by_media;
  const wall = useWallMedia(accountId, open && cosmeticReady);
  const [blurMode] = useBlurMode();
  const blurCls = blurImageClass(blurMode);
  const [captionOn, setCaptionOn] = useCaptionOverlay("picker");
  const hover = useHoverPreview(HOVER_DELAY_MS);
  const [previewMedia, setPreviewMedia] = useState<VaultMedia | null>(null);
  const photoHover = usePhotoHover();
  const { shown: hoverPhoto, close: closePhoto } = photoHover;
  const [details, setDetails] = useState<{ media: VaultMedia; atHistory: boolean } | null>(null);

  const openOpIdRef = useRef<string | null>(null);
  const paintedRef = useRef(false);
  const markFirstTilePainted = (el: HTMLButtonElement | null, firstTileId: number) => {
    if (!el || paintedRef.current) return;
    const id = openOpIdRef.current;
    if (!id) return;
    paintedRef.current = true;
    perfPainted(id, "vault.open", { firstTileId });
  };

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      const id = perfOpId("vault.open");
      openOpIdRef.current = id;
      paintedRef.current = false;
      perfLog(id, "vault.open", "requested", { accountId, fanId });
      pick({ type: "reset", ids: initialSelectedIds });
      revalidate({ type: "open" });
      dispatch({ type: "hydrate", saved: loadFanState(accountId, fanId) });
      setFolderMru(loadFanMru(accountId, fanId));
    }
    wasOpenRef.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const firstUsable = useMemo<FanId | null>(
    () => firstUsableFolderId(allowedFolders, listsQ.data?.list ?? []),
    [allowedFolders, listsQ.data],
  );

  useEffect(() => {
    if (!open || !restricted) return;
    if (listId != null && allowedFolderIds.has(listId)) return;
    if (firstUsable != null) dispatch({ type: "setListId", value: firstUsable });
  }, [open, restricted, listId, allowedFolderIds, firstUsable]);

  const listsPainted = listsQ.data !== undefined && !listsQ.isFetching;
  const mediaPainted = mediaReady({
    source,
    sourceSettled: cacheSummary.data !== undefined || cacheSummary.isError,
    folderSettled: !folderAccessQ.isLoading && (!restricted || (listId != null && allowedFolderIds.has(listId))),
    painted: !vaultLive.isLoading && !vaultLive.isFetching && !vaultLive.isPlaceholderData && !vaultLive.error,
  });
  useEffect(() => {
    if (!open || !accountId) return;
    for (const target of revalidateDue(revalidation, { lists: listsPainted, media: mediaPainted })) {
      revalidate({ type: "sent", target });
      const read = target === "lists"
        ? revalidateVaultLists(qc, accountId)
        : revalidateVaultMediaFirstPage(qc, { accountId, type, listId, sort: ofSort, query });
      read.catch(() => {});
    }
  }, [open, accountId, revalidation, listsPainted, mediaPainted, qc, type, listId, ofSort, query]);

  useEffect(() => {
    if (!open) return;
    saveFanState(accountId, fanId, { listId, sort, type });
  }, [open, listId, sort, type, accountId, fanId]);

  useEffect(() => {
    if (!open || listId == null) return;
    bumpAccountCount(accountId, listId);
    setFolderMru((prev) => {
      const next = nextMru(prev, listId);
      saveFanMru(accountId, fanId, next);
      return next;
    });
  }, [open, listId, accountId, fanId]);

  const accountCounts = useMemo(
    () => (open ? loadAccountCounts(accountId) : {}),
    [open, accountId],
  );

  const onEscape = () => {
    if (hoverPhoto) {
      closePhoto();
      return;
    }
    if (previewMedia) {
      setPreviewMedia(null);
      return;
    }
    if (details) {
      setDetails(null);
      return;
    }
    onClose();
  };

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef(vault.loadMore);
  loadMoreRef.current = vault.loadMore;
  useEffect(() => {
    if (!open) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && vault.hasMore && !vault.isFetchingNextPage) {
          loadMoreRef.current();
        }
      },
      { root: null, rootMargin: "800px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [open, vault.hasMore, vault.isFetchingNextPage]);

  const addMany = (ms: VaultMedia[]) => pick({ type: "addMany", media: ms });
  const toggle = (m: VaultMedia) => pick({ type: "toggle", media: m });

  const confirmWith = useCallback(
    (extra?: VaultMedia) => {
      onConfirm(buildPicked(picked, vault.items, extra));
      onClose();
    },
    [vault.items, picked, onConfirm, onClose],
  );
  const confirm = useCallback(() => confirmWith(), [confirmWith]);

  const historyByMedia = historyQ.data?.by_media;
  // Order is server-side (OF honors sort=asc|desc); a client reverse would put new pages at the top under infinite scroll.
  const visibleItems = useMemo(() => {
    // OF repeats items across adjacent pages; keep the first occurrence.
    const seen = new Set<number>();
    const out: VaultMedia[] = [];
    for (const m of vault.items) {
      if (seen.has(m.id)) continue;
      seen.add(m.id);
      if (!inDurationRange(m, lengthRange)) continue;
      if (hideSeen && fanId != null
        && seenByFan(resolveStatus(historyByMedia?.[String(m.id)], wall.set.has(m.id)))) continue;
      out.push(m);
    }
    return isStatsSort(sort) && statsMap ? sortByStats(out, statsMap, sort) : out;
  }, [vault.items, lengthRange, hideSeen, fanId, historyByMedia, wall.set, sort, statsMap]);
  const { stop: stopHover } = hover;
  const hoveredId = hover.state.id;
  useEffect(() => {
    if (!open || (hoveredId != null && !visibleItems.some((m) => m.id === hoveredId))) stopHover();
  }, [open, hoveredId, visibleItems, stopHover]);
  const grid = useGridSelection({
    items: visibleItems, toggle, addMany,
    attach: (focused) => (selectedIds.size > 0 ? confirm() : focused && confirmWith(focused)),
  });

  const quickChips = useMemo(
    () => folderChips(listsQ.data?.list ?? [], folderMru, accountCounts, MRU_CAP),
    [listsQ.data, folderMru, accountCounts],
  );

  if (!open) return null;
  if (typeof document === "undefined") return null;

  // Portal to body: ancestor containing blocks / modal grid cells squash a fixed picker.
  return createPortal(
    <PickerDialog
      rootRef={rootRef}
      onEscape={onEscape}
      aria-label="Vault picker"
      className={cn("fixed inset-0 z-[60] flex items-stretch", messagesPro && VAULT_SHEET.backdrop)}
      style={palette}
      // React bubbles portal events to the parent composer, whose onClick closes it.
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close vault picker"
        className="absolute inset-0 bg-black/70 cursor-default"
      />
      <div className={cn("relative bg-panel border-border flex flex-col shadow-2xl", sheet ? cn(VAULT_SHEET.panel, sheet.panel) : "ml-auto w-full max-w-3xl border-l")}>
        <header className={cn("flex items-center justify-between px-6 py-4 border-b border-border", sheet?.pickerHead)}>
          <div>
            <h2 className={cn("text-[16px] font-semibold inline-flex items-center gap-1.5", sheet?.pickerTitle)}>
              <Library size={16} aria-hidden />
              Vault
              {useLocalVault && (
                <span
                  className="text-[12px] font-medium text-ok inline-flex items-center gap-0.5"
                  title="Served instantly from the local cache (Collect in the Vault manager)"
                >
                  <Zap className="h-3 w-3" aria-hidden />
                  cached
                </span>
              )}
            </h2>
            <p className="text-[12px] text-muted">
              <span className="hidden md:inline">{TILE_HINT} · {KEYBOARD_HINT}.</span>
              <span className="md:hidden">Tap to select, then Attach.</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted hover:text-fg w-11 h-11 md:w-6 md:h-6 inline-grid place-items-center rounded"
            title="Close (Esc)"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="flex items-center gap-1 px-6 py-2 border-b border-border bg-bg/40 flex-nowrap overflow-x-auto md:flex-wrap md:overflow-visible">
          <IfSegmented
            aria-label="Media type"
            className="shrink-0"
            value={type}
            onChange={(value) => dispatch({ type: "setType", value })}
            options={TYPE_CHIPS}
          />

          {folderItems.length > 0 && (
            <IfNativeSelect
              value={listId ?? ""}
              onChange={(e) => dispatch({ type: "setListId", value: e.target.value ? Number(e.target.value) : null })}
              className="shrink-0 ml-2 max-w-[9rem] md:max-w-none"
              title="Filter by folder"
            >
              {!restricted && <option value="">All folders</option>}
              {folderItems.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </IfNativeSelect>
          )}

          <IfNativeSelect
            value={sort}
            onChange={(e) => dispatch({ type: "setSort", value: e.target.value as Sort })}
            className="shrink-0 ml-2"
            title="Sort order. Newest / Oldest are OF's; the stats sorts rank the loaded media by our send records."
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            {STATS_SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </IfNativeSelect>

          {fanId != null && (
            <span className="shrink-0 ml-2" title="Hide content viewed or unlocked by fan, or posted on Creator's feed">
              <IfSwitch
                checked={hideSeen}
                onChange={(value) => dispatch({ type: "setHideSeen", value })}
                label="Hide seen"
                className="gap-2"
              />
            </span>
          )}

          {fanId != null && (
            <IfNativeSelect
              value={lengthRange}
              onChange={(e) => dispatch({ type: "setLengthRange", value: e.target.value as DurationRange })}
              className="shrink-0 ml-2"
              title="Filter by length"
            >
              {DURATION_RANGES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </IfNativeSelect>
          )}

          <div className="relative shrink-0 ml-2">
            <input
              type="search"
              value={queryInput}
              onChange={(e) => dispatch({ type: "setQueryInput", value: e.target.value })}
              placeholder={fanId != null ? "Search hashtag, note or caption" : "Search vault…"}
              title="Search your vault (OnlineFans-native full-text search)"
              className={cn(IF_FIELD, "h-8 w-40 md:w-60 pl-[11px] pr-7 text-base md:text-[14px] outline-none focus:border-accent placeholder:text-muted")}
            />
            {queryInput && (
              <button
                type="button"
                onClick={() => dispatch({ type: "clearQuery" })}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
                aria-label="Clear search"
                title="Clear search"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            )}
          </div>

          <div className="shrink-0 ml-auto flex items-center gap-3">
            <IfButton
              icon={Captions}
              onClick={() => setCaptionOn(!captionOn)}
              aria-pressed={captionOn}
              title={captionOn ? "Hide AI descriptions on thumbs" : "Show AI descriptions on thumbs"}
              className={cn(
                "gap-1.5 px-[11px]",
                captionOn && "border-accent/60 bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))]",
              )}
            >
              captions
            </IfButton>
            {wall.hasMore && (
              <span
                className="hidden md:inline text-[12px] text-muted"
                title="The 'posted on wall' ring is being filled in across vault opens. Older posts will get marked on subsequent picker opens."
              >
                {wall.isFetching ? "scanning wall…" : "wall scan incomplete"}
              </span>
            )}
            {ofRefresh.note && <span role="status" className="text-[12px] text-warn">{ofRefresh.note}</span>}
            <IfButton
              variant="link"
              disabled={!accountId || ofRefresh.isPending}
              aria-busy={ofRefresh.isPending}
              // Reads what OF holds now: mirror urls carry the old Collect's signature and proxy IP.
              onClick={() => { ofRefresh.mutate(listId); wall.refresh(); }}
              className="gap-1.5"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", (ofRefresh.isPending || vault.isFetching || wall.isFetching) && "animate-spin")} aria-hidden />
              refresh
            </IfButton>
          </div>
        </div>

        {quickChips.length > 0 && (
          <div className="flex items-center gap-1 px-6 py-1.5 border-b border-border bg-bg/30 flex-wrap text-[12px]">
            <span className="text-muted mr-1">Folders</span>
            {!restricted && <button
              type="button"
              onClick={() => dispatch({ type: "setListId", value: null })}
              className={cn(
                "px-2 py-0.5 rounded-full border transition-colors",
                listId == null
                  ? "bg-info/15 border-info/40 text-info"
                  : "bg-transparent border-border text-fg-dim hover:text-fg",
              )}
              title="All vault items, regardless of folder"
            >
              All
            </button>}
            {quickChips.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => dispatch({ type: "setListId", value: f.id })}
                title={
                  f.source === "mru"
                    ? `Switch to '${f.name}' · last-used for this fan`
                    : f.source === "global"
                    ? `Switch to '${f.name}' · most-used across all your fans`
                    : `Switch to '${f.name}'`
                }
                className={cn(
                  "px-2 py-0.5 rounded-full border transition-colors max-w-[10rem] truncate",
                  listId === f.id
                    ? "bg-info/15 border-info/40 text-info"
                    : "bg-transparent border-border text-fg-dim hover:text-fg",
                )}
              >
                {f.source === "mru" && <Star className="mr-0.5 inline h-3 w-3 align-[-2px] opacity-60" aria-hidden />}
                {f.source === "global" && <span className="opacity-50 mr-0.5">•</span>}
                {f.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-3" onScroll={closePhoto}>
          {vault.isLoading && vault.items.length === 0 && (
            <div className="text-sm text-fg-dim text-center py-12">Loading vault…</div>
          )}
          {vault.error && !vault.isFetching && vault.items.length === 0 && (
            <div className="text-sm text-err text-center py-6">
              Failed: {(vault.error as Error).message || "unknown"}
            </div>
          )}
          {!vault.isLoading && searchingOf && visibleItems.length === 0 && (
            <div role="status" className="flex items-center justify-center gap-2 text-sm text-fg-dim py-12">
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
              Searching OnlyFans…
            </div>
          )}
          {!vault.isLoading && !searchingOf && ofSearch.failed && visibleItems.length === 0 && (
            <div role="alert" className="flex items-center justify-center gap-2 text-sm text-fg-dim py-12">
              OnlyFans search failed
              <button type="button" onClick={ofSearch.retry} className="text-accent hover:underline">Retry</button>
            </div>
          )}
          {!vault.isLoading && !vault.isFetching && !searchingOf && !ofSearch.failed && visibleItems.length === 0
            && !vault.error && (
            <div className="text-sm text-fg-dim text-center py-12">
              No media in this filter.
            </div>
          )}

          <div
            ref={grid.gridRef}
            onKeyDown={grid.onGridKeyDown}
            onKeyUp={grid.onGridKeyUp}
            className={cn(
              "grid grid-cols-3 sm:grid-cols-4 gap-2 transition-opacity",
              sheet ? sheet.pickerGrid : "md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7",
              !useLocalVault && vaultLive.isFetching && vaultLive.isPlaceholderData && "opacity-60",
            )}
          >
            {visibleItems.map((m, tileIdx) => (
              <VaultPickerTile
                key={m.id}
                m={m}
                selected={selectedIds.has(m.id)}
                accountId={accountId}
                fanId={fanId}
                sheetTile={sheet?.pickerTile}
                useLocalVault={useLocalVault}
                blurCls={blurCls}
                captionOn={captionOn}
                fanEntry={fanId != null ? historyMap[String(m.id)] : undefined}
                stat={statsMap?.[String(m.id)]}
                onWall={wall.set.has(m.id)}
                wallCents={wall.priceById.get(m.id) ?? 0}
                hover={hover}
                photoHover={photoHover}
                firstTileRef={tileIdx === 0 ? (el) => markFirstTilePainted(el, m.id) : undefined}
                onTileClick={grid.onTileClick}
                onAttach={confirmWith}
                onPreview={setPreviewMedia}
                onDetails={setDetails}
                thumbs={thumbs}
              />
            ))}
          </div>

          <div ref={sentinelRef} className="h-8 flex items-center justify-center text-[12px] text-muted">
            {vault.isFetchingNextPage ? "Loading more…" : vault.hasMore ? "" : (vault.items.length > 0 ? "End of vault." : "")}
          </div>
        </div>

        <footer className="border-t border-border px-6 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] flex items-center gap-3 bg-panel">
          <span className="text-[12px] text-fg-dim">
            {selectedIds.size === 0
              ? "No items selected"
              : `${selectedIds.size} item${selectedIds.size === 1 ? "" : "s"} selected`}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <IfButton onClick={onClose}>Cancel</IfButton>
            <IfButton variant="primary" disabled={selectedIds.size === 0} onClick={confirm}>
              Attach
            </IfButton>
          </div>
        </footer>
        {details && (
          <VaultMediaDetails
            media={details.media}
            accountId={accountId}
            entry={historyQ.isSuccess ? (historyMap[String(details.media.id)] ?? null) : undefined}
            onWall={wall.set.has(details.media.id)}
            wallCents={wall.priceById.get(details.media.id) ?? 0}
            tags={aiCaptionFor(details.media)?.tags ?? []}
            atHistory={details.atHistory}
            onExpand={() => setPreviewMedia(details.media)}
            onClose={() => setDetails(null)}
          />
        )}
      </div>
      {hoverPhoto && <PhotoHoverPanel {...hoverPhoto} accountId={accountId} blurCls={blurCls} />}
      {previewMedia && (
        <VaultVideoPreview
          media={previewMedia}
          accountId={accountId}
          onClose={() => setPreviewMedia(null)}
        />
      )}
    </PickerDialog>,
    document.body,
  );
}
