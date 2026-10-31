"use client";

/**
 * VaultManagePanel — the Vault manager.
 *
 * OF-style two-panel layout. Folders ARE OnlyFans folders (unified — no separate
 * internal folders): the rail lists OF's real vault folders, served from the
 * local mirror (instant, exact counts) and reorderable per-folder. The rail is
 * `VaultFolderRail`, laid out from Vault Pro's Layout capture; this panel keeps
 * the grid and the Extras drawer. "Add to folder" writes to OF for real. Search is
 * AI vision tags ∪ OF's own search. Collect / Describe-all / Harvest run in the
 * background, in the one Extras drawer (they are ours, not Infloww's), which the
 * page header's overflow button opens (`extrasOpen`).
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { Square } from "lucide-react";

import { EmptyState, IfModal } from "@/components/ui/infloww";
import { VaultVideoPreview } from "@/components/chat/VaultPicker";
import { useVaultAccountId } from "@/components/vault/VaultAccount";
import VaultAiFoldersModal from "@/components/vault/VaultAiFoldersModal";
import VaultDisputesModal from "@/components/vault/VaultDisputesModal";
import VaultFlagsReviewModal from "@/components/vault/VaultFlagsReviewModal";
import VaultDuplicatesModal from "@/components/vault/VaultDuplicatesModal";
import VaultPreviewMedia from "@/components/vault/VaultPreviewMedia";
import VaultPackPickerModal from "@/components/vault/VaultPackPickerModal";
import VaultExtrasTools, { type ExtrasModal } from "@/components/vault/VaultExtrasTools";
import VaultSelectionBar, { VaultDeleteButton } from "@/components/vault/VaultSelectionBar";
import { VaultItemEditor } from "@/components/vault/VaultItemEditor";
import {
  DESCRIBING,
  addSelectedToFolder,
  describeOne,
  describeSelected,
  newFolderWithSelection,
  onCollect,
  onDescribeAll,
  setOrder,
  type ManageDeps,
  type Tile,
} from "@/components/vault/vaultManageActions";
import VaultFolderRail, { FolderCounts } from "@/components/vault/VaultFolderRail";
import VaultMediaToolbar, { type MediaSort, type TypeCounts } from "@/components/vault/VaultMediaToolbar";
import VaultTile from "@/components/vault/VaultTile";
import { useVaultLists, useVaultMedia } from "@/hooks/useVaultMedia";
import {
  useOfFoldersMirror,
  searchOf,
  useDescribePlan,
  useMirrorItems,
  useVaultCacheSummary,
  invalidateVaultGrid,
  mirrorItemsKey,
} from "@/hooks/useVaultCache";
import { describeSweepText, sweepAbortedNote, useVaultSweep } from "@/hooks/useVaultSweep";
import { type VaultList, type VaultMedia } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import { initialBrowseState, vaultBrowseReducer } from "@/components/vault/vaultBrowseReducer";

/** The rail-and-grid row (#15). Exported for the page's no-Creator frame. */
export const VAULT_PANES_CLASS =
  "flex flex-col md:flex-row items-stretch overflow-hidden h-[70vh] md:h-auto md:flex-1 md:min-h-0";
/** The grid's scroll box (#70). */
export const VAULT_GRID_CLASS = "px-3 md:px-6 flex-1 min-h-0 overflow-y-auto";

export default function VaultManagePanel({ extrasOpen = false, onCloseExtras = () => {} }: {
  /** The Extras drawer is open (the page header's overflow button). */
  extrasOpen?: boolean;
  onCloseExtras?: () => void;
}) {
  // Shared with the importer — see `VaultAccount`. Local
  // state here meant the panel's own chips moved the grid and nothing else.
  // A plain string, never null: the page does not mount this panel until a
  // model is chosen, and remounts it when the choice changes.
  const accountId = useVaultAccountId();
  const qc = useQueryClient();
  // Folder / type / search and the ticked files — see `vaultBrowseReducer`.
  // FanId, not number: Fansly album ids are snowflakes above 2^53, and a
  // narrowed one selects a DIFFERENT album. Media ids below stay number[].
  const [browse, dispatchBrowse] = useReducer(vaultBrowseReducer, initialBrowseState);
  const { type, folderId: ofFolderId, query, selectMode, selected } = browse;
  const [sort, setSort] = useState<MediaSort>("newest");
  const [searchRaw, setSearchRaw] = useState("");
  const [preview, setPreview] = useState<Tile | null>(null);
  // Full-screen playback target — hands off to the picker's VaultVideoPreview.
  const [playMedia, setPlayMedia] = useState<VaultMedia | null>(null);
  // The one modal the Extras drawer opened, if any — they never stack.
  const [open, setOpen] = useState<ExtrasModal | null>(null);
  const [needsReview, setNeedsReview] = useState(0);
  const [busy, setBusyLine] = useState<string>("");
  // The same line, read synchronously by the actions — see `Busy`.
  const busyRef = useRef("");
  // The selection bar's move opens the "Add to category" modal (#77).
  const [moving, setMoving] = useState(false);
  const [promptVersion, setPromptVersion] = useState<"v1" | "v2">("v2");
  const drawerRef = useRef<HTMLElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<() => void>(() => {});
  const canLoadRef = useRef(false);

  // The capture's trigger (#44): a search runs at 3 characters or more, or when cleared; in between the last one
  // stands.
  useEffect(() => {
    const q = searchRaw.trim();
    if (q.length > 0 && q.length < 3) return;
    const t = setTimeout(() => dispatchBrowse({ type: "query", value: q }), 250);
    return () => clearTimeout(t);
  }, [searchRaw]);

  // Esc closes the full-screen player first, then the details drawer.
  useEffect(() => {
    if (!preview && !playMedia) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (playMedia) setPlayMedia(null);
      else setPreview(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview, playMedia]);

  // Clicking anywhere outside the drawer closes it, same as the ✕. Tile clicks
  // still read as a SWAP rather than a close: this fires first, then the tile's
  // own onClick sets the new preview in the same React batch. Skipped while the
  // full-screen player is up, so clicking the player can't close the drawer
  // underneath it.
  useEffect(() => {
    if (!preview || selectMode || playMedia) return;
    // Phone only: the drawer is a full-screen sheet there, so there is no
    // "outside" to click — and a thumb brushing the edge would close it.
    if (!window.matchMedia("(min-width: 768px)").matches) return;
    const onDown = (e: MouseEvent) => {
      const el = drawerRef.current;
      if (el && !el.contains(e.target as Node)) setPreview(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [preview, selectMode, playMedia]);

  // On a search, harvest OF's own results in the BACKGROUND and merge them in.
  useEffect(() => {
    if (!query) return;
    let cancelled = false;
    searchOf(accountId, query)
      .then(() => {
        if (!cancelled) qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [query, accountId, qc]);

  const summary = useVaultCacheSummary(accountId);
  const plan = useDescribePlan(accountId, promptVersion);
  // Both sweeps are the same object — see `useVaultSweep`. Polling, the start
  // call, the running→idle edge and the mid-sweep grid refresh all live there,
  // so this stays about what the buttons say.
  const describeSweep = useVaultSweep({
    kind: "describe-all",
    accountId,
    liveKeys: [mirrorItemsKey(accountId)],
    settleKeys: [
      ["vault-describe-plan", accountId],
      ["vault-flags-review"],
      ["vault-flags-accuracy"],
      ["vault-ai-folder-plan"],
    ],
    // Offer the manual pass rather than relying on anyone remembering it
    // exists. Describing writes what the model BELIEVES; every wrong answer
    // this system has had was invisible to every automatic check and obvious
    // to a human in seconds, so the end of a sweep is exactly when to ask.
    onSettled: (s) => {
      const n = s.progress?.needs_review ?? 0;
      if (n > 0) setNeedsReview(n);
    },
  });
  const harvestSweep = useVaultSweep({
    kind: "harvest-keywords",
    accountId,
    liveKeys: [mirrorItemsKey(accountId)],
  });
  const cachedCount = summary.data?.count ?? 0;
  const isCollecting = !!summary.data?.running;
  const run = summary.data?.last_run;
  // The plan's counts come from the DB, so they stand in when the relay's
  // in-memory counter isn't there — mid-startup, or after a restart took it out.
  const describeText = describeSweepText(describeSweep.progress, {
    done: Math.max(0, (plan.data?.total ?? 0) - (plan.data?.undescribed ?? 0)),
    total: plan.data?.total ?? 0,
  });
  const describeStopped = sweepAbortedNote(describeSweep.progress);

  // Out of AI budget for today. The server refuses the start either way (429),
  // but a refusal you can only discover by pressing is what made this look
  // broken rather than spent: the sweep ended, the button said "Describe all
  // (1777)" again, and pressing it fetched another batch of frames to have
  // every LLM call refused. Grey, with the reason on it, is the whole fix.
  // The sentence is the server's — see `VisionCapState.blocked_reason`.
  const capped = !!plan.data?.cap?.capped;
  const capReason = plan.data?.cap?.blocked_reason ?? "";

  // includeEmpty: the manage rail shows ALL custom folders (even empty ones) so
  // you can add media to / rename / delete them — unlike the picker which hides
  // empty folders. Both share the same paginated fetch cache; only the filter differs.
  const lists = useVaultLists(accountId, true, true);
  // Mirror-derived OF folders (accurate counts; recovers folders OF's live list
  // drops, e.g. "nowfolder"). Only meaningful once collected.
  const ofFoldersMirror = useOfFoldersMirror(accountId, cachedCount > 0);
  // Union: start from the live custom folders (they include EMPTY folders the
  // mirror can't see), override counts from the mirror where it has them, then
  // append any mirror-only custom folder the live list omitted.
  const folders = useMemo<VaultList[]>(() => {
    const live = (lists.data?.list ?? []) as VaultList[];
    const mir = (ofFoldersMirror.data?.list ?? []).filter((f) => !f.builtin);
    if (mir.length === 0) return live;
    const liveIds = new Set(live.map((f) => f.id));
    const mirById = new Map(mir.map((f) => [f.id, f]));
    const merged: VaultList[] = live.map((f) => {
      const mm = mirById.get(f.id);
      return mm
        ? {
            ...f,
            hasMedia: true,
            photosCount: mm.photosCount,
            videosCount: mm.videosCount,
            gifsCount: mm.gifsCount,
            audiosCount: mm.audiosCount,
          }
        : f;
    });
    for (const mm of mir) {
      if (liveIds.has(mm.id)) continue;
      merged.push({
        id: mm.id,
        name: mm.name,
        type: "custom",
        hasMedia: true,
        photosCount: mm.photosCount,
        videosCount: mm.videosCount,
        gifsCount: mm.gifsCount,
        audiosCount: mm.audiosCount,
      });
    }
    return merged;
  }, [lists.data, ofFoldersMirror.data]);

  // Everything is served from the mirror once collected (instant, incl. OF
  // folders + reorder). Before the first collect, fall back to live OF all-media.
  // IMPORTANT: don't kick off the SLOW live-OF fetch until the (fast, local)
  // summary has resolved — otherwise every mount/account-switch treats the
  // brief "summary still loading" window as "no cache", fires a live OF round
  // trip ("Loading…"), and only later swaps to the instant mirror. Wait first.
  const summaryReady = !summary.isLoading;
  const useLocal = cachedCount > 0;
  const usingFolder = ofFolderId != null;
  // `listId` is the selected folder, NOT null: the live path is what serves an
  // account with no mirror yet, and pinning it to null meant picking a folder
  // filtered nothing away — the grid showed the WHOLE library under that
  // folder's heading. The mirror path below has always scoped itself by
  // `ofFolderId`; this gives the live one the same scope.
  const live = useVaultMedia({
    accountId, type, listId: ofFolderId, sort, query, enabled: summaryReady && !useLocal,
  });
  const mirror = useMirrorItems({
    accountId, type, query, sort, ofFolderId, enabled: useLocal,
  });
  const src = useLocal ? mirror : live;
  // Show the spinner while we're still deciding (summary pending) OR the chosen
  // source is fetching — never flash an empty state during the swap.
  const showLoading = summary.isLoading || src.isLoading;
  const items = src.items as Tile[];
  const pageFetching = src.isFetchingNextPage;
  const pageError = !!src.error && !pageFetching;
  loadMoreRef.current = src.loadMore;
  // Gate on isFetchingNextPage, NOT isFetching: any background refetch of the
  // pages we already hold (invalidate after a describe/edit, stale revalidate)
  // flips isFetching, and gating on it wedges the trigger permanently.
  canLoadRef.current = src.hasMore && !pageFetching;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    // Observe scroll INSIDE the media pane (scrollRef), not the page viewport —
    // the grid is its own scroll container now. `items.length` in the deps
    // re-attaches the observer once the sentinel mounts after the first load
    // (it doesn't exist while isLoading), otherwise nothing fires at the bottom.
    //
    // `pageFetching` is a dep too, so the observer is RE-ARMED every time a page
    // fetch settles. Without it, a user already parked at the bottom sees the
    // sentinel stay continuously intersecting: the callback fired once (or fired
    // while a fetch was in flight, or the fetch failed and items.length never
    // moved) and IO never fires again without a state change. Re-observing
    // re-delivers the current intersection, so loading resumes on its own.
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && canLoadRef.current) loadMoreRef.current();
      },
      { root: scrollRef.current, rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [accountId, ofFolderId, type, query, sort, items.length, pageFetching]);

  // Belt-and-braces: a plain scroll listener on the pane. The observer covers
  // the normal case, but it is one silent failure (root not yet mounted, a
  // dropped page) away from stranding the grid — and the user is then stuck
  // with no way to ask for more. This never wedges: it re-evaluates on every
  // scroll event.
  function onGridScroll() {
    const el = scrollRef.current;
    if (!el || !canLoadRef.current) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 600) loadMoreRef.current();
  }

  const activeFolder = folders.find((f) => f.id === ofFolderId);
  // #58: the chosen folder's per-type counts switch its empty types off; All media has none to go by.
  const typeCounts: TypeCounts = activeFolder
    ? {
        photo: activeFolder.photosCount,
        video: activeFolder.videosCount,
        gif: activeFolder.gifsCount,
        audio: activeFolder.audiosCount,
      }
    : null;

  /** Everything that answers "what is in this vault" — the SAME list the import
   *  card uses, from `useVaultCache`, rather than a second hand-written copy.
   *  The copy that used to live here was missing `vault-of-folders-mirror` and
   *  (before that) the grid's own `vault-media` key, which made an add-to-folder
   *  move the sidebar count to "2" while the tiles underneath kept showing the
   *  pre-add page — the one thing the user is actually looking at was the one
   *  thing that never refetched. */
  function refreshAll() {
    invalidateVaultGrid(qc, accountId);
  }

  const deps: ManageDeps = {
    accountId,
    qc,
    busy: {
      get: () => busyRef.current,
      set: (s) => {
        busyRef.current = s;
        setBusyLine(s);
      },
    },
    selected,
    clearSelection: () => dispatchBrowse({ type: "clearSelection" }),
    refreshAll,
    capReason,
    refetchPlan: () => plan.refetch(),
  };

  // After an edit save, merge the returned (effective-value) fields back into the
  // open preview so the editor reflects the override immediately, and refresh the
  // grid so the S9 overlay picks up the new description/tags.
  function onSavedItem(updated: Record<string, unknown>) {
    setPreview((prev) => (prev ? { ...prev, _ai: { ...(prev._ai ?? {}), ...updated } } : prev));
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Our tools, which the bundle does not have, in one Extras drawer (ADR-0003). Closed by default and one click
          away (the header's overflow button), so the rail starts right under the header rule, as in the capture. */}
      {extrasOpen && (
        <VaultExtrasTools
          accountId={accountId}
          onClose={onCloseExtras}
          isCollecting={isCollecting}
          totalSeen={run?.total_seen ?? 0}
          cachedCount={cachedCount}
          onCollect={() => onCollect({ accountId, qc, refreshAll, isCollecting })}
          onDescribeAll={(mode) => onDescribeAll(mode, { ...deps, describeSweep, capped, plan: plan.data, promptVersion })}
          describeSweep={describeSweep}
          describeText={describeText}
          describeStopped={describeStopped}
          harvestSweep={harvestSweep}
          plan={plan.data}
          capped={capped}
          capReason={capReason}
          promptVersion={promptVersion}
          setPromptVersion={setPromptVersion}
          needsReview={needsReview}
          setNeedsReview={setNeedsReview}
          flagsReviewOpen={open === "flagsReview"}
          onOpen={setOpen}
        />
      )}

      {/* Two-pane, flush under the header (#15): each side scrolls on its OWN, so only the media grid moves (with
          its own bottom-of-list infinite load) and the folder rail stays put. From `md` up it fills the rest of the
          page; below, a fixed 70vh. */}
      <div className={VAULT_PANES_CLASS}>
        <VaultFolderRail
          folders={folders}
          loading={lists.isLoading}
          error={lists.isError}
          onRetry={() => lists.refetch()}
          selectedId={ofFolderId}
          onSelect={(id) => dispatchBrowse({ type: "folder", id })}
          onChanged={refreshAll}
        />

        {/* RIGHT grid */}
        {/* `relative`: the selection bar floats over the grid's foot (#75). */}
        <section className="relative flex-1 min-w-0 min-h-0 flex flex-col">
          {/* #38 to #68: the search and sort row, then the media tabs and tools. The folder's name is the rail's
              selected row, as in the bundle, so the content has no heading of its own. */}
          <VaultMediaToolbar
            search={searchRaw}
            onSearch={setSearchRaw}
            sort={sort}
            onSort={setSort}
            type={type}
            onType={(value) => dispatchBrowse({ type: "mediaType", value })}
            typeCounts={typeCounts}
            loadedCount={items.length}
            onRefresh={refreshAll}
            onSelectAll={() => dispatchBrowse({ type: "selectAll", ids: items.map((m) => m.id) })}
            selectMode={selectMode}
            onToggleSelect={() => dispatchBrowse({ type: "toggleSelectMode" })}
          />

          <div
            ref={scrollRef}
            onScroll={onGridScroll}
            className={cn(VAULT_GRID_CLASS, selectMode && selected.size > 0 && "pb-20")}

          >
            {showLoading ? (
              // The bundle spins (`Spin`) while the grid loads; ours draws the grid's tiles as placeholders.
              <div role="status" aria-label="Loading" className="grid grid-cols-3 md:grid-cols-6 gap-2 py-4">
                {Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="aspect-square w-full rounded-md" />)}
              </div>
            ) : items.length === 0 && pageError ? (
              // #72: the grid's error, which Refresh above answers.
              <EmptyState
                kind="error"
                className="py-10"
                text={
                  <>
                    <span className="block font-medium text-fg">Connectivity</span>
                    <span className="block">Please try refreshing.</span>
                  </>
                }
              />
            ) : items.length === 0 ? (
              // #71
              <EmptyState className="py-10" />
            ) : (
              <>
                {/* #70: four per row, 5px around each (10px apart); fewer on a narrow screen. */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2.5">
                  {items.map((m) => (
                    <VaultTile
                      key={m.id}
                      media={m}
                      accountId={accountId}
                      onClick={setPreview}
                      onPlay={setPlayMedia}
                      selected={preview?.id === m.id}
                      selectMode={selectMode}
                      checked={selected.has(m.id)}
                      onCheck={() => dispatchBrowse({ type: "toggle", id: m.id })}
                      showOrder={usingFolder}
                      onOrder={(m, value) => setOrder(m, value, { accountId, qc, ofFolderId })}
                    />
                  ))}
                </div>
                <div ref={sentinelRef} className="h-8" />
                {/* Ours: the bundle scrolls with no count and no load-more fallback. */}
                <div title={EXTRA_LABEL} className="text-center text-xs text-fg-dim pt-1 pb-2">
                  {pageFetching ? (
                    <Skeleton className="mx-auto h-3 w-16" />
                  ) : src.hasMore ? (
                    // Always clickable — auto-load is the happy path, but the
                    // user must never be stranded staring at a dead hint line.
                    <button
                      type="button"
                      onClick={() => src.loadMore()}
                      className="px-3 py-1.5 rounded-lg border border-border bg-bg-elev-1 text-fg-dim hover:text-fg hover:border-fg-dim transition-colors"
                    >
                      {pageError ? "Couldn’t load more · retry" : `${items.length} shown · load more`}
                    </button>
                  ) : (
                    `${items.length} shown`
                  )}
                </div>
              </>
            )}
          </div>

          {selectMode && selected.size > 0 && (
            <VaultSelectionBar
              count={selected.size}
              hasFolders={folders.length > 0}
              busy={busy}
              capped={capped}
              capReason={capReason}
              onMove={() => setMoving(true)}
              onNewFolder={() => newFolderWithSelection(deps)}
              onDescribe={() => describeSelected(deps)}
              onClear={() => dispatchBrowse({ type: "clearSelection" })}
            />
          )}
        </section>
      </div>

      {moving && (
        // #77: "Add to category", centred, 480px wide, one row per folder with its name and counts
        // (`MoveModalItem`, index.9f50f370.js @6789722). A row adds the selected files to that folder. The
        // bundle's row check also says whether the files are in it already, and unticking removes them; the
        // grid's media read carries no folder membership, so that check is Not wired.
        <IfModal title="Add to category" width={480} onClose={() => setMoving(false)}>
            <div className="-my-2 max-h-[60vh] overflow-y-auto">
              {folders.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  disabled={!!busy}
                  onClick={async () => {
                    setMoving(false);
                    // The album id stays EXACTLY as it came off the wire: a Fansly album id is an 18-digit
                    // snowflake past 2^53, and `Number()` on it names a different album.
                    await addSelectedToFolder(f.id, deps);
                  }}
                  className="w-full flex items-center gap-3 px-2 py-3 border-b border-border text-left hover:bg-bg-elev-2"
                >
                  <span title="not wired" className="text-fg-dim"><Square size={16} aria-hidden /></span>
                  <span className="flex flex-col gap-1 min-w-0">
                    <span className="text-sm font-medium truncate">{f.name}</span>
                    <FolderCounts f={f} />
                  </span>
                </button>
              ))}
            </div>
        </IfModal>
      )}

      {preview && !selectMode && (
        // Right-side slide-over, deliberately WITHOUT a dimming backdrop so the
        // grid stays visible AND clickable behind it — click another tile and the
        // drawer just swaps to that item.
        <aside
          ref={drawerRef}
          className="fixed inset-0 md:inset-y-0 md:left-auto md:right-0 z-40 h-full w-full md:w-[430px] flex flex-col border-l border-border bg-panel/95 backdrop-blur-sm shadow-2xl pt-[env(safe-area-inset-top)] md:pt-0 pb-[env(safe-area-inset-bottom)] md:pb-0"
        >
          <header className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
            <div className="text-sm font-medium truncate">
              #{preview.id} · {preview.type}
              {preview.duration ? ` · ${Math.round(preview.duration)}s` : ""}
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => describeOne(preview, { ...deps, setPreview })}
                disabled={!!busy || capped}
                title={capped ? `${EXTRA_LABEL}\n${capReason}` : EXTRA_LABEL}
                className="px-2.5 py-1 rounded-md text-xs border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {busy === DESCRIBING
                  ? "Describing…"
                  : capped
                  ? "Cap reached"
                  : (preview._ai as { describe_status?: string } | undefined)?.describe_status === "described"
                  ? "Re-describe"
                  : "Describe"}
              </button>
              <button
                type="button"
                onClick={() => setPreview(null)}
                aria-label="Close details"
                title="Close (Esc)"
                className="w-9 h-9 md:w-7 md:h-7 grid place-items-center rounded-md border border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1"
              >
                ✕
              </button>
            </div>
          </header>
          {/* The editor owns the order — action bar (sticky) → media → the
              fields you act on → the rest below the fold. */}
          <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
            <VaultItemEditor
              key={preview.id}
              media={preview}
              accountId={accountId}
              onSaved={onSavedItem}
              mediaSlot={
                <VaultPreviewMedia
                  key={`pv-${preview.id}`}
                  media={preview}
                  accountId={accountId}
                  onExpand={() => setPlayMedia(preview)}
                />
              }
              deleteSlot={
                <VaultDeleteButton
                  key={`del-${preview.id}`}
                  media={preview}
                  accountId={accountId}
                  onDeleted={() => {
                    setPreview(null);
                    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
                  }}
                />
              }
            />
          </div>
        </aside>
      )}
      {playMedia && (
        <VaultVideoPreview
          media={playMedia}
          accountId={accountId}
          onClose={() => setPlayMedia(null)}
        />
      )}
      {open === "dupes" && (
        <VaultDuplicatesModal accountId={accountId} onClose={() => setOpen(null)} />
      )}
      {open === "packPicker" && (
        <VaultPackPickerModal
          accountId={accountId}
          category="feet"
          onClose={() => setOpen(null)}
        />
      )}
      {open === "flagsReview" && (
        <VaultFlagsReviewModal
          accountId={accountId}
          onClose={() => setOpen(null)}
        />
      )}

      {open === "disputes" && (
        <VaultDisputesModal accountId={accountId} onClose={() => setOpen(null)} />
      )}

      {open === "aiFolders" && (
        <VaultAiFoldersModal accountId={accountId} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
