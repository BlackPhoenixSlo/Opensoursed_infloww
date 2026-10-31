"use client";

/**
 * VaultPicker — modal dialog over the chat surface for picking vault
 * media to attach to an outgoing message.
 *
 * Multi-select. Tap a tile to toggle; the selected count + Attach button
 * live in the footer. Type filter chips (all / photo / video / gif)
 * reset pagination. Infinite scroll via IntersectionObserver on the
 * sentinel at the bottom.
 *
 * Returns the chosen media as VaultMedia[] so the caller can render
 * preview chips immediately without re-fetching. The Composer keeps
 * only their ids in send-payload form.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Library } from "lucide-react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

import { useQueryClient } from "@tanstack/react-query";

import { useChatterFolderAccess, useVaultLists, useVaultMedia } from "@/hooks/useVaultMedia";
import { searchOf, useMirrorItems, useVaultCacheSummary } from "@/hooks/useVaultCache";
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
import { VAULT_SHEET, VAULT_TOOLBAR_SELECT } from "./vaultPickerSheet";
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

// Moved out of this file; re-exported so every existing importer keeps working.
export { progressiveVideoSrc, videoPosterFrames, isDrmVideo, isDrmOnlyVideo, VaultVideoPreview } from "./VaultVideoPreview";
// Kept only for VaultTile + the drm test importers (review O1); delete when VaultTile moves to tilePreview.
export { evenFrameIndex } from "./vaultTilePreview";
export { aiCaptionFor, VaultAiCaptionOverlay, useCaptionOverlay, type CaptionSurface } from "./vaultAiCaption";

const TYPE_CHIPS: Array<{ value: MediaType; label: string }> = [
  { value: "all",   label: "All"    },
  { value: "photo", label: "Photos" },
  { value: "video", label: "Videos" },
  { value: "gif",   label: "GIFs"   },
];

/** The Messages Pro sheet's Geometry, from its one caller (the Composer,
 *  which passes `MP.sheet`): the panel, and from md up the head row, the
 *  title, the grid and a tile, so below md the picker keeps its full-screen
 *  pane. Colours, layout and the picker's own numbers stay here. */
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
  /** When provided, we fetch per-fan send/purchase history and show a
   *  status badge on each tile + enable the fan-aware filter chips.
   *  Leave null for mass-message or post-builder usages where there's
   *  no single fan in scope. */
  fanId?: FanId | null;
  /** Already-attached ids from the Composer so we can pre-select them. */
  initialSelectedIds: number[];
  /** Caller receives the full media objects so it can render previews. */
  onConfirm: (picked: VaultMedia[]) => void;
}

/** Everywhere else, the right-hand slide-over; in Messages Pro, the Clone's
 *  centred sheet and grid, which always come with their Geometry. Only the
 *  Composer passes `messagesPro`. */
export type VaultPickerProps = VaultPickerBaseProps & (
  | { messagesPro?: false }
  | { messagesPro: true; sheet: VaultPickerSheetClassNames }
);

export function VaultPicker(props: VaultPickerProps) {
  const { open, onClose, accountId, fanId = null, initialSelectedIds, onConfirm } = props;
  /** The Messages Pro sheet's Geometry, or null for the slide-over. */
  const sheet = props.messagesPro ? props.sheet : null;
  const messagesPro = sheet !== null;
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  // Filter bar: type, folder, sort, hide-seen, length, search (vaultPickerFilters).
  const [filters, dispatch] = useReducer(vaultFiltersReducer, initialFilters);
  const { type, listId, sort, hideSeen, lengthRange, queryInput, query } = filters;
  // The stats sorts reorder the newest-first pages OF serves.
  const ofSort = fetchSort(sort);
  // Vault search — OF-native (verified live: wire param `query`). Debounced
  // so we fire one OF fetch after the user pauses typing, not per keystroke.
  useEffect(() => {
    const t = setTimeout(() => dispatch({ type: "commitQuery", value: queryInput }), 300);
    return () => clearTimeout(t);
  }, [queryInput]);
  // Per-fan folder MRU (last 3 used). Lives in localStorage so it
  // survives reloads + transfers between tabs.
  const [folderMru, setFolderMru] = useState<FanId[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set(initialSelectedIds));
  // Cache of media metadata for ids the user picked across filter switches
  // so we can return the full VaultMedia[] on confirm even if the user
  // selects from one filter then jumps to another.
  const [selectedMeta, setSelectedMeta] = useState<Map<number, VaultMedia>>(
    () => new Map(),
  );

  const listsQ = useVaultLists(accountId, open);
  // Chatter Access (folders): for a RESTRICTED chatter session this is the
  // authoritative folder menu (DA-3). Owners get `restricted: false` (the
  // hook disables itself off-session), so all of the gating below is inert
  // for them. The backend soft-denies disallowed/None list_id regardless —
  // this only shapes the picker's folder UI so it opens to a usable folder.
  const folderAccessQ = useChatterFolderAccess(accountId, open);
  const restricted = !!folderAccessQ.data?.restricted;

  // ── Cache-first vault source (ADDITION — normal live search is preserved) ──
  // Once an OWNER has "Collect"-ed this account's vault into the local mirror,
  // serve the grid + search straight from it: instant open, infinite-scroll
  // FROM CACHE, and local (of_terms-aware) search. Falls back to the normal
  // live-OF path when there's no cache — or for a restricted chatter, whose
  // /admin/vault-ai/* endpoints are owner-gated anyway (so the summary 403s →
  // cachedCount 0 → live path). Both hooks always mount; only the enabled one
  // fetches, so this adds a fast path without touching the live one.
  const qc = useQueryClient();
  const cacheSummary = useVaultCacheSummary(open ? accountId : null);
  const cachedCount = cacheSummary.data?.count ?? 0;
  const useLocalVault = open && !restricted && cachedCount > 0;
  const vaultLive = useVaultMedia({
    accountId, type, listId, sort: ofSort, query,
    // Fire the live OF path immediately whenever we're NOT on the cache path.
    // (Deliberately NOT gated on the summary call: under relay load a slow
    // summary would leave the live query disabled → items:[] → a false
    // "No media in this filter". For a cached account useLocalVault flips true
    // within a few ms and the mirror — 8ms — wins the race anyway, so the
    // worst case is one throwaway OF fetch on the very first cold open.)
    enabled: open && !useLocalVault,
  });
  const vaultMirror = useMirrorItems({
    accountId, type, query, sort: ofSort, ofFolderId: listId, enabled: useLocalVault,
  });
  const vault = useLocalVault
    ? ({
        items: vaultMirror.items,
        hasMore: vaultMirror.hasMore,
        isLoading: cacheSummary.isLoading || vaultMirror.isLoading,
        isFetching: vaultMirror.isFetching,
        isFetchingNextPage: vaultMirror.isFetchingNextPage,
        isPlaceholderData: false,
        error: null,
        loadMore: vaultMirror.loadMore,
        refresh: vaultMirror.refetch,
      } as typeof vaultLive)
    : vaultLive;

  // Harvest OF's own vault search for the current query and fold it into the
  // mirror index (of_terms) so cache search ⊇ OF search — same as the manager.
  useEffect(() => {
    if (!useLocalVault || !accountId || !query) return;
    let cancelled = false;
    searchOf(accountId, query)
      .then(() => {
        if (!cancelled) qc.invalidateQueries({ queryKey: ["vault-mirror-items", accountId] });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [useLocalVault, query, accountId, qc]);

  const allowedFolders = useMemo(
    () => folderAccessQ.data?.folders ?? [],
    [folderAccessQ.data],
  );
  const allowedFolderIds = useMemo(
    () => new Set(allowedFolders.map((f) => f.folder_id)),
    [allowedFolders],
  );
  // Folder dropdown source (vaultPickerFolders): OF's full list, or a
  // restricted chatter's authoritative allowlist (DA-3).
  const folderItems = useMemo(
    () => folderSelectItems(restricted, allowedFolders, listsQ.data?.list ?? []),
    [restricted, allowedFolders, listsQ.data],
  );

  // Log vault.open `delivered` the first time the initial fetch lands this
  // open-session. Subsequent loads (filter switch, infinite scroll) are
  // tracked independently by useVaultMedia / useVaultLists.
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
  // `cosmeticReady` flips true once the initial vault.media has landed
  // for this open. It gates both the wall-media post-walk AND the per-fan
  // history fetch — both are pure decoration (status ring color, corner
  // price pill) and must NOT compete with the user-blocking vault page
  // load. Once we flip to ready, we stay ready for the rest of this open
  // so the cosmetics fill in naturally as filters change. (Tearing down
  // a half-finished wall-media on every folder switch / background
  // refetch was the original bug — the walk never got to finish before
  // being cancelled again, so the rings would never appear.)
  // Closing the picker resets so the next open re-gates on its own
  // initial vault load.
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
  // Per-fan history paints the status ring + corner pill — defer until
  // cosmeticReady so it doesn't queue alongside the initial vault page.
  const historyQ = useFanVaultHistory(accountId, fanId ?? null, open && cosmeticReady);
  const historyMap = historyQ.data?.by_media ?? {};
  // Account-wide Sent / Unlock / rate per media: decoration too, unless a
  // stats sort needs it now.
  const statsQ = useVaultMediaStats(accountId, open && (cosmeticReady || isStatsSort(sort)));
  const statsMap = statsQ.data?.by_media;
  const wall = useWallMedia(accountId, open && cosmeticReady);
  const [blurMode] = useBlurMode();
  const blurCls = blurImageClass(blurMode);
  // AI caption overlay — default OFF in the picker so it doesn't crowd the
  // send flow; the chatter can flip it on from the toolbar toggle.
  const [captionOn, setCaptionOn] = useCaptionOverlay("picker");
  // Hover-to-preview is a 12-frame slideshow served by the relay's
  // /img/scrub endpoint. The previous implementation streamed the actual
  // mp4 through two <video> elements + a canvas scrub pipeline, which
  // pinned uvicorn threadpool slots and deadlocked the relay when users
  // browsed a lot of video tiles. The storyboard approach replaces all
  // that with 12 small JPGs (~20KB each, served from a disk cache the
  // relay populates on first hit), so a hover is at most 12 lightweight
  // image GETs — no streams to stop on switch because there are no
  // streams at all. Dwell, session id, slideshow cursor, countdowns and
  // the cancel POST live in useHoverPreview; what a tile shows is
  // tilePreview's read of it.
  const hover = useHoverPreview(HOVER_DELAY_MS);
  // Click-to-open full preview. Storing the whole VaultMedia so the modal
  // has access to videoSources + thumb without re-finding it in the list.
  const [previewMedia, setPreviewMedia] = useState<VaultMedia | null>(null);
  // Photo hover-enlarge: same dwell as the video preview, in a floating panel.
  const photoHover = usePhotoHover();
  const { shown: hoverPhoto, close: closePhoto } = photoHover;
  // "Media details" (ⓘ, or the price pill at the price history). Opening and
  // closing it never touches the selection.
  const [details, setDetails] = useState<{ media: VaultMedia; atHistory: boolean } | null>(null);

  // Perf instrumentation. We mint a fresh open-op id every time the picker
  // transitions closed→open and stamp it onto the vault-media + vault-lists
  // hooks so their requested/delivered phases share the same id as the
  // user-visible "vault open" event. The first-tile painted milestone is
  // logged from the first tile <button> below via a render-once ref.
  const openOpIdRef = useRef<string | null>(null);
  const paintedRef = useRef(false);
  const markFirstTilePainted = (el: HTMLButtonElement | null, firstTileId: number) => {
    if (!el || paintedRef.current) return;
    const id = openOpIdRef.current;
    if (!id) return;
    paintedRef.current = true;
    // Fires the moment the first tile <button> is mounted —
    // this is "first tab open" in the user's terms: the
    // picker has data on screen and is clickable.
    perfPainted(id, "vault.open", { firstTileId });
  };

  // Reset selection state when the picker transitions from closed → open.
  // Parent passes a fresh `initialSelectedIds` array on every render, so
  // depending on its identity would clobber in-picker selections on every
  // upstream re-render.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      const id = perfOpId("vault.open");
      openOpIdRef.current = id;
      paintedRef.current = false;
      perfLog(id, "vault.open", "requested", { accountId, fanId });
      setSelectedIds(new Set(initialSelectedIds));
      setSelectedMeta(new Map());
      // Restore the whole picker position for this fan: folder, sort,
      // type. If the chatter has never opened the picker for this fan,
      // fall back to All / Newest / All-types. Crucially we DON'T force
      // listId to the MRU head — that would override the user's last
      // explicit "All folders" choice every time.
      // Search is transient — start each open clean.
      dispatch({ type: "hydrate", saved: loadFanState(accountId, fanId) });
      setFolderMru(loadFanMru(accountId, fanId));
    }
    wasOpenRef.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Chatter Access (folders): a restricted chatter has NO "All folders"
  // view (the backend soft-denies list_id=None to an empty payload). Once
  // the authoritative menu lands, force the selection onto an allowed
  // folder if the restored/empty selection isn't one. We pick the first
  // allowed folder that OF still reports as having media (listsQ is
  // backend-filtered to the allowed set), which transparently falls
  // through past a folder that was deleted/emptied on OF (per DA-3).
  const firstUsable = useMemo<FanId | null>(
    () => firstUsableFolderId(allowedFolders, listsQ.data?.list ?? []),
    [allowedFolders, listsQ.data],
  );

  useEffect(() => {
    if (!open || !restricted) return;
    if (listId != null && allowedFolderIds.has(listId)) return;
    if (firstUsable != null) dispatch({ type: "setListId", value: firstUsable });
  }, [open, restricted, listId, allowedFolderIds, firstUsable]);

  // Persist the full picker state on every change so reopening the
  // picker (same tab, popout, or restart) lands on the exact same view.
  useEffect(() => {
    if (!open) return;
    saveFanState(accountId, fanId, { listId, sort, type });
  }, [open, listId, sort, type, accountId, fanId]);

  // Whenever the user picks a real folder (not "All"), bump it to the
  // head of the per-fan MRU AND the account-wide counter. We do this on
  // listId change (not on confirm) so even a browse counts. The
  // account-wide counter is what the account-wide fallback below ranks
  // by when the current fan has no MRU yet.
  useEffect(() => {
    if (!open || listId == null) return;
    bumpAccountCount(accountId, listId);
    setFolderMru((prev) => {
      const next = nextMru(prev, listId);
      saveFanMru(accountId, fanId, next);
      return next;
    });
  }, [open, listId, accountId, fanId]);

  // Snapshot the account-wide counter once per open so the chip row's
  // tie-break stays stable while the user clicks around (otherwise the
  // act of clicking a chip would re-rank it mid-render).
  const accountCounts = useMemo(
    () => (open ? loadAccountCounts(accountId) : {}),
    [open, accountId],
  );

  // Esc closes. When the preview modal is open, swallow Esc to close just
  // the preview — the second press then closes the whole picker.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
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
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose, previewMedia, details, hoverPhoto, closePhoto]);

  // Infinite scroll sentinel.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // `loadMore` is recreated on every useVaultMedia render, so we read the
  // latest via a ref inside the observer callback. Depending on it directly
  // (or on the whole `vault` object) would tear down and rebuild the
  // IntersectionObserver on every render; the ref lets us create it once
  // per open while still invoking the freshest loadMore.
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
      // 800px ≈ 1.5 viewport heights at typical picker sizing — gives a
      // fast scroll a head start, so the next page is in-flight well
      // before the user reaches the spinner.
      { root: null, rootMargin: "800px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [open, vault.hasMore, vault.isFetchingNextPage]);

  function addMany(ms: VaultMedia[]) {
    setSelectedIds((prev) => new Set([...prev, ...ms.map((m) => m.id)]));
    setSelectedMeta((prev) => new Map([...prev, ...ms.map((m) => [m.id, m] as const)]));
  }

  function toggle(m: VaultMedia) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(m.id)) next.delete(m.id);
      else next.add(m.id);
      return next;
    });
    setSelectedMeta((prev) => {
      const next = new Map(prev);
      next.set(m.id, m);
      return next;
    });
  }

  // `extra` lets the double-click "insta add" path force-include the
  // double-clicked tile regardless of how the click sequence left
  // selectedIds (the two onClicks of a dblclick toggle the tile twice,
  // so the net selection state depends on parity).
  const confirmWith = useCallback(
    (extra?: VaultMedia) => {
      const picked: VaultMedia[] = [];
      const seenInList = new Map(vault.items.map((m) => [m.id, m]));
      const ids = new Set(selectedIds);
      if (extra) ids.add(extra.id);
      for (const id of ids) {
        const m =
          (extra && extra.id === id ? extra : undefined) ??
          seenInList.get(id) ??
          selectedMeta.get(id);
        if (m) picked.push(m);
        else picked.push({ id, type: "photo" } as VaultMedia);
      }
      onConfirm(picked);
      onClose();
    },
    [vault.items, selectedIds, selectedMeta, onConfirm, onClose],
  );
  const confirm = useCallback(() => confirmWith(), [confirmWith]);

  // Ordering is now server-side (`sort=asc|desc` — OF honors both, verified
  // live), so we render `vault.items` in the exact order OF paginated them.
  // A client reverse would be WRONG under infinite scroll: newly loaded
  // pages would land at the top instead of the bottom.
  //
  // Still dedup by id — OF's vault pagination occasionally returns the same
  // item across adjacent pages (race between a vault edit and our offset-
  // based reads), and React would warn about duplicate keys on the tile
  // <button>s. Keep the FIRST occurrence so the position the user already
  // sees stays stable when a re-fetch overlaps.
  //
  // A stats sort (Send count, Unlock count, Unlock rate, Recently used) is the
  // one client reorder: it ranks what has loaded, unsent media last in OF's
  // order. Hide-seen drops what the Fan already has or saw on the feed.
  const historyByMedia = historyQ.data?.by_media;
  const visibleItems = useMemo(() => {
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
  // End the hover when no mouseleave will: the picker closes (Esc, attach;
  // it stays mounted) or the hovered card drops out of the grid (a late
  // hide-seen). Stops the slideshow, sends the cancel, and disarms the dwell.
  const { stop: stopHover } = hover;
  const hoveredId = hover.state.id;
  useEffect(() => {
    if (!open || (hoveredId != null && !visibleItems.some((m) => m.id === hoveredId))) stopHover();
  }, [open, hoveredId, visibleItems, stopHover]);
  // Shift-click ranges and the grid keyboard run over the cards as displayed.
  const grid = useGridSelection({
    items: visibleItems, toggle, addMany,
    attach: (focused) => (selectedIds.size > 0 ? confirm() : focused && confirmWith(focused)),
  });

  // Folder quick-chips: per-fan MRU ★, then account-wide most-used •, then
  // OF's first folders; capped at MRU_CAP (vaultPickerFolders).
  const quickChips = useMemo(
    () => folderChips(listsQ.data?.list ?? [], folderMru, accountCounts, MRU_CAP),
    [listsQ.data, folderMru, accountCounts],
  );

  if (!open) return null;
  if (typeof document === "undefined") return null;

  // Portal to document.body so the picker is never trapped by an ancestor
  // that creates a containing block (transform / filter / contain) or by a
  // modal's overflow / z-index ceiling. The chat composer always rendered
  // fine because its ancestor chain was clean; the post and mass-message
  // composers wrap the picker in a `fixed inset-0 grid place-items-center`
  // modal where the picker was being squashed into the modal's grid cell
  // instead of covering the viewport. Portal+`fixed` sidesteps both.
  return createPortal(
    // stopPropagation on every pointer event: even though the picker is
    // portaled into <body>, React still bubbles its events up through the
    // React parent tree — so a tile click inside the picker would hit the
    // PostComposer / MassMessageComposer outer `onClick` that closes them.
    // Containing the events here keeps single-chat behavior identical and
    // fixes the "click a tile and the whole composer disappears" bug.
    <div
      className={cn("fixed inset-0 z-[60] flex items-stretch", messagesPro && VAULT_SHEET.backdrop)}
      style={palette}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close vault picker"
        className="absolute inset-0 bg-black/40 cursor-default"
      />
      <div className={cn("relative bg-panel border-border flex flex-col shadow-2xl", sheet ? cn(VAULT_SHEET.panel, sheet.panel) : "ml-auto w-full max-w-3xl border-l")}>
        <header className={cn("flex items-center justify-between px-4 py-3 border-b border-border", sheet?.pickerHead)}>
          <div>
            <h2 className={cn("text-base font-semibold inline-flex items-center gap-1.5", sheet?.pickerTitle)}>
              <Library size={16} aria-hidden />
              Vault
              {useLocalVault && (
                <span
                  className="text-[10px] font-medium text-ok inline-flex items-center gap-0.5"
                  title="Served instantly from the local cache (Collect in the Vault manager)"
                >
                  ⚡ cached
                </span>
              )}
            </h2>
            <p className="text-[11px] text-fg-dim">
              {/* Double-click has no touch equivalent; the phone copy points
               *  at the Attach button in the footer instead. */}
              <span className="hidden md:inline">{TILE_HINT} · {KEYBOARD_HINT}.</span>
              <span className="md:hidden">Tap to select, then Attach.</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            // At phone width the pane covers the whole backdrop, so this ✕ is
            // the only exit — it needs a real 44px box. inline-grid (not grid)
            // keeps the desktop header flex row measuring exactly as before.
            className="text-fg-dim hover:text-fg text-base md:text-sm w-11 h-11 md:w-auto md:h-auto inline-grid place-items-center md:px-2 md:py-1"
            title="Close (Esc)"
          >
            ✕
          </button>
        </header>

        {/* Phone: one horizontally-scrollable row instead of a 4-line wrapped
         *  tower. md: restores the original wrap + visible overflow exactly. */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-border bg-bg/40 flex-nowrap overflow-x-auto md:flex-wrap md:overflow-visible">
          {TYPE_CHIPS.map((c) => (
            <button
              key={c.value}
              type="button"
              onClick={() => dispatch({ type: "setType", value: c.value })}
              className={cn(
                "shrink-0 px-3 py-1 rounded-full text-xs border transition-colors",
                type === c.value
                  ? "bg-accent/15 border-accent/40 text-[var(--inf-accent-text,var(--color-accent))]"
                  : "bg-transparent border-border text-fg-dim hover:text-fg",
              )}
            >
              {c.label}
            </button>
          ))}

          {folderItems.length > 0 && (
            <select
              value={listId ?? ""}
              onChange={(e) => dispatch({ type: "setListId", value: e.target.value ? Number(e.target.value) : null })}
              className={cn(VAULT_TOOLBAR_SELECT, "max-w-[9rem] md:max-w-none")}
              title="Filter by folder"
            >
              {/* Restricted chatters have no "All folders" view — the
               *  backend soft-denies list_id=None for them (DA-2). */}
              {!restricted && <option value="">All folders</option>}
              {folderItems.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          )}

          <select
            value={sort}
            onChange={(e) => dispatch({ type: "setSort", value: e.target.value as Sort })}
            className={VAULT_TOOLBAR_SELECT}
            title="Sort order. Newest / Oldest are OF's; the stats sorts rank the loaded media by our send records."
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            {STATS_SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>

          {fanId != null && (
            <label
              className="shrink-0 ml-2 inline-flex items-center gap-1 text-[11px] text-fg-dim cursor-pointer select-none"
              title="Hide content viewed or unlocked by fan, or posted on Creator's feed"
            >
              <input type="checkbox" checked={hideSeen} onChange={(e) => dispatch({ type: "setHideSeen", value: e.target.checked })} />
              Hide seen
            </label>
          )}

          {fanId != null && (
            <select
              value={lengthRange}
              onChange={(e) => dispatch({ type: "setLengthRange", value: e.target.value as DurationRange })}
              className={VAULT_TOOLBAR_SELECT}
              title="Filter by length"
            >
              {DURATION_RANGES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          )}

          <div className="relative shrink-0 ml-2">
            <input
              type="search"
              value={queryInput}
              onChange={(e) => dispatch({ type: "setQueryInput", value: e.target.value })}
              placeholder={fanId != null ? "Search hashtag, note or caption" : "Search vault…"}
              title="Search your vault (OnlineFans-native full-text search)"
              className="w-32 md:w-40 bg-bg border border-border rounded-md pl-2 pr-6 py-1 text-base md:text-xs focus:outline-none focus:border-accent"
            />
            {queryInput && (
              <button
                type="button"
                onClick={() => dispatch({ type: "clearQuery" })}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-fg-dim hover:text-fg leading-none"
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>

          <div className="shrink-0 ml-auto flex items-center gap-3">
            {/* AI caption toggle — shows the mirror description + tags as a
             *  blurred bottom-half overlay on each thumb. Off by default here. */}
            <button
              type="button"
              onClick={() => setCaptionOn(!captionOn)}
              aria-pressed={captionOn}
              title={captionOn ? "Hide AI descriptions on thumbs" : "Show AI descriptions on thumbs"}
              className={cn(
                "inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border transition-colors",
                captionOn
                  ? "bg-accent/15 border-accent/40 text-[var(--inf-accent-text,var(--color-accent))]"
                  : "bg-transparent border-border text-fg-dim hover:text-fg",
              )}
            >
              <span aria-hidden>📝</span>
              <span>captions</span>
            </button>
            {/* Wall-scan indicator: only render while coverage is
             *  incomplete so the user understands the blue "posted on
             *  wall" ring is still filling in. Once `fullyBackfilled`
             *  flips, we stay silent — no point shouting a steady
             *  state. */}
            {wall.hasMore && (
              <span
                // Desk-only diagnostic prose; it costs the phone a whole
                // scroll-row of the filter bar. md:inline restores it.
                className="hidden md:inline text-[11px] text-fg-dim italic"
                title="The 'posted on wall' ring is being filled in across vault opens. Older posts will get marked on subsequent picker opens."
              >
                {wall.isFetching ? "scanning wall…" : "wall scan incomplete"}
              </span>
            )}
            <button
              type="button"
              onClick={() => { vault.refresh(); wall.refresh(); }}
              className="inline-flex items-center gap-1 text-[11px] text-fg-dim hover:text-fg underline underline-offset-2"
            >
              <span className={cn("inline-block no-underline", (vault.isFetching || wall.isFetching) && "animate-spin")}>↻</span>
              <span>refresh</span>
            </button>
          </div>
        </div>

        {quickChips.length > 0 && (
          <div className="flex items-center gap-1 px-4 py-1.5 border-b border-border bg-bg/30 flex-wrap text-[11px]">
            <span className="text-fg-dim mr-1">Folders:</span>
            {/* Restricted chatters have no "All" — soft-denied by the backend. */}
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
                {f.source === "mru" && <span className="opacity-60 mr-0.5">★</span>}
                {f.source === "global" && <span className="opacity-50 mr-0.5">•</span>}
                {f.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3" onScroll={closePhoto}>
          {vault.isLoading && vault.items.length === 0 && (
            <div className="text-sm text-fg-dim text-center py-12">Loading vault…</div>
          )}
          {/* Only surface an error when (a) we're not actively retrying
           *  and (b) we have nothing cached to show. Otherwise React Query
           *  will keep `vault.error` set from a stale attempt during the
           *  retry backoff window, which used to flash a "Failed: …" line
           *  for ~1s on first open before the retry succeeded. */}
          {vault.error && !vault.isFetching && vault.items.length === 0 && (
            <div className="text-sm text-err text-center py-6">
              Failed: {(vault.error as Error).message || "unknown"}
            </div>
          )}
          {!vault.isLoading && !vault.isFetching && visibleItems.length === 0 && !vault.error && (
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
              vault.isFetching && vault.isPlaceholderData && "opacity-60",
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
              />
            ))}
          </div>

          <div ref={sentinelRef} className="h-8 flex items-center justify-center text-[11px] text-fg-dim">
            {vault.isFetchingNextPage ? "Loading more…" : vault.hasMore ? "" : (vault.items.length > 0 ? "End of vault." : "")}
          </div>
        </div>

        {/* pb safe-area: Attach/Cancel sit under the iOS home indicator on this
         *  `fixed inset-0` pane (viewportFit: cover). max() keeps the desktop
         *  0.75rem, since env() resolves to 0 there. Composer.tsx:469 precedent. */}
        <footer className="border-t border-border px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] flex items-center gap-3 bg-panel">
          <span className="text-xs text-fg-dim">
            {selectedIds.size === 0
              ? "No items selected"
              : `${selectedIds.size} item${selectedIds.size === 1 ? "" : "s"} selected`}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button size="sm" disabled={selectedIds.size === 0} onClick={confirm}>
              Attach
            </Button>
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
    </div>,
    document.body,
  );
}
