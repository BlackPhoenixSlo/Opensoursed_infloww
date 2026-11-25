"use client";


import { useEffect, useMemo, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Square } from "lucide-react";

import { EmptyState, IfModal } from "@/components/ui/infloww";
import { VaultVideoPreview } from "@/components/chat/VaultPicker";
import { useVaultAccount, useVaultAccountId } from "@/components/vault/VaultAccount";
import { useVaultDownloadContext } from "@/components/vault/VaultDownloadPanel";
import {
  creatorDir, dlAccess, downloadGate, downloadLabel, type DlGate, type DlMode,
} from "@/components/vault/vaultDownloadReducer";
import { useAccounts } from "@/hooks/useAccounts";
import { useCan } from "@/hooks/useCan";
import VaultAiFoldersModal from "@/components/vault/VaultAiFoldersModal";
import VaultFlagsReviewModal from "@/components/vault/VaultFlagsReviewModal";
import VaultInternalFoldersModal from "@/components/vault/VaultInternalFoldersModal";
import VaultDuplicatesModal from "@/components/vault/VaultDuplicatesModal";
import VaultPackPickerModal from "@/components/vault/VaultPackPickerModal";
import VaultExtrasTools, { type ExtrasModal } from "@/components/vault/VaultExtrasTools";
import VaultSelectionBar from "@/components/vault/VaultSelectionBar";
import VaultItemModal from "@/components/vault/VaultItemModal";
import {
  DESCRIBING,
  addSelectedToFolder,
  describeOne,
  describeSelected,
  newFolderWithSelection,
  onCollect,
  onCollectAnswer,
  onDescribeAll,
  setOrder,
  type ManageDeps,
  type Tile,
} from "@/components/vault/vaultManageActions";
import VaultFolderRail, { FolderCounts } from "@/components/vault/VaultFolderRail";
import VaultMediaToolbar, { type MediaSort, type TypeCounts } from "@/components/vault/VaultMediaToolbar";
import VaultTagChips from "@/components/vault/VaultTagChips";
import VaultSettingsSwitches from "@/components/vault/VaultSettingsSwitches";
import VaultStandardFolders from "@/components/vault/VaultStandardFolders";
import { useStandardFolders, standardFoldersKey, type StandardFolder } from "@/hooks/useStandardFolders";
import { useVaultSettings } from "@/hooks/useVaultSettings";
import VaultTile from "@/components/vault/VaultTile";
import { useChatterFolderAccess, useVaultLists, useVaultMedia } from "@/hooks/useVaultMedia";
import {
  useOfFoldersMirror,
  useOfSearch,
  useDescribePlan,
  useMirrorItems,
  useVaultCacheSummary,
  invalidateVaultGrid,
  mirrorItemsKey,
} from "@/hooks/useVaultCache";
import { useOfRefresh, vaultBrowseSource, vaultWholeSource } from "@/hooks/vaultRefresh";
import { type FanId } from "@/lib/fanId";
import { useThumbAutoRefresh } from "@/hooks/useThumbAutoRefresh";
import { describeSweepText, sweepAbortedNote, useVaultSweep } from "@/hooks/useVaultSweep";
import { type VaultList, type VaultMedia } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import { useVaultBrowse } from "@/components/vault/VaultBrowseMemory";
import { hiddenByFilter } from "@/components/vault/vaultBrowseReducer";

export const VAULT_PANES_CLASS =
  "flex flex-col md:flex-row items-stretch overflow-hidden h-[70vh] md:h-auto md:flex-1 md:min-h-0";
export const VAULT_GRID_CLASS = "px-3 md:px-6 flex-1 min-h-0 overflow-y-auto";
export const FOLDER_LOADING = "The folder list is still loading";
const scopeOff = (reason: string): DlGate => ({ reason, desktopOnly: false, queues: false });

export default function VaultManagePanel({ extrasOpen = false, onCloseExtras = () => {} }: {
  extrasOpen?: boolean;
  onCloseExtras?: () => void;
}) {
  const accountId = useVaultAccountId();
  const canRemove = useCan(accountId, "vault_remove");
  const { account } = useVaultAccount();
  const qc = useQueryClient();
  const dl = useVaultDownloadContext();
  const registry = useAccounts().data?.accounts;
  const who = { accountId, creator: creatorDir(accountId, account, registry) };
  const access = dlAccess(useChatterFolderAccess(accountId));
  const dlGate = (mode: DlMode, count = 0) => downloadGate(dl.state, dl.sink, mode, count, access);
  const [browse, dispatchBrowse] = useVaultBrowse(accountId);
  // FanId, not number: Fansly album ids are snowflakes above 2^53; narrowing one selects a different album.
  const { type, folderId: ofFolderId, standardFolderId, query, tags, selectMode, selected } = browse;
  const settings = useVaultSettings(accountId, access === "all");
  const standardOn = access === "all" && !!settings.data?.standard_folders;
  const standard = useStandardFolders(accountId, standardOn);
  const standardFolder = standard.data?.list.find((f) => f.id === standardFolderId);
  const selectStandard = (folder: StandardFolder | null) => dispatchBrowse(folder
    ? { type: "standardFolder", id: folder.id, kind: folder.kind } : { type: "folder", id: null });
  const standardRail = (mobile = false) => standardOn && <VaultStandardFolders
    accountId={accountId} folders={standard.data?.list ?? []} selectedId={standardFolderId}
    pending={standard.data?.pending ?? 0} syncing={standard.syncing}
    error={standard.isError || standard.syncError} onSelect={selectStandard} onRefresh={standard.refresh} mobile={mobile} />;
  const selectedIds = useMemo(() => new Set(selected.keys()), [selected]);
  const [sort, setSort] = useState<MediaSort>("newest");
  const [searchRaw, setSearchRaw] = useState(query);
  const [preview, setPreview] = useState<Tile | null>(null);
  const [playMedia, setPlayMedia] = useState<VaultMedia | null>(null);
  const [open, setOpen] = useState<ExtrasModal | null>(null);
  const [needsReview, setNeedsReview] = useState(0);
  const [busy, setBusyLine] = useState<string>("");
  const busyRef = useRef("");
  const [moving, setMoving] = useState(false);
  const promptVersion = "v2" as const;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<() => void>(() => {});
  const canLoadRef = useRef(false);

  useEffect(() => {
    const q = searchRaw.trim();
    if (q.length > 0 && q.length < 3) return;
    const t = setTimeout(() => dispatchBrowse({ type: "query", value: q }), 250);
    return () => clearTimeout(t);
  }, [searchRaw, dispatchBrowse]);

  useEffect(() => {
    if (!playMedia || (preview && !selectMode)) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPlayMedia(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playMedia, preview, selectMode]);

  const summary = useVaultCacheSummary(accountId);
  const plan = useDescribePlan(accountId, promptVersion);
  const describeSweep = useVaultSweep({
    kind: "describe-all",
    accountId,
    liveKeys: [mirrorItemsKey(accountId), standardFoldersKey(accountId)],
    settleKeys: [
      ["vault-describe-plan", accountId],
      ["vault-flags-review"],
      ["vault-flags-accuracy"],
      ["vault-ai-folder-plan"],
    ],
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
  const source = vaultBrowseSource(summary.data);
  // wholeSource: a partial mirror would download part.
  const wholeSource = vaultWholeSource(summary.data);
  const scopeArgs = (f: { id: FanId; name: string } | null) => (f
    ? { ...who, mode: "folder" as const, label: `folder ${f.name}`, folder: { id: f.id, name: f.name }, source: wholeSource }
    : { ...who, mode: "vault" as const, label: "whole vault", folder: null, source: wholeSource });
  const useLocal = standardFolderId != null || source === "mirror";
  const ofSearch = useOfSearch(accountId, query, useLocal && standardFolderId == null);
  const searchingOf = ofSearch.searching;
  const isCollecting = !!summary.data?.running;
  const run = summary.data?.last_run;
  const describeText = describeSweepText(describeSweep.progress, {
    done: Math.max(0, (plan.data?.total ?? 0) - (plan.data?.undescribed ?? 0)),
    total: plan.data?.total ?? 0,
  });
  const describeStopped = sweepAbortedNote(describeSweep.progress);

  const capped = !!plan.data?.cap?.capped;
  const capReason = plan.data?.cap?.blocked_reason ?? "";

  const lists = useVaultLists(accountId, true, true);
  const ofFoldersMirror = useOfFoldersMirror(accountId, useLocal);
  // OF's live folder list drops some folders and miscounts: mirror counts win and its extra folders are added.
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
  const selectedFolder = ofFolderId == null ? null : folders.find((f) => f.id === ofFolderId) ?? null;
  const fullScope = standardFolderId != null || (ofFolderId != null && !selectedFolder) ? null : scopeArgs(selectedFolder);
  const fullGate = fullScope ? dlGate(fullScope.mode)
    : scopeOff(standardFolderId != null ? "Select media to download from this category" : FOLDER_LOADING);
  const selGate = !fullScope && !standardFolder ? scopeOff(FOLDER_LOADING) : dlGate("selection", selected.size);

  // Don't start the slow live-OF fetch until the local summary resolves, or every mount fires a live round trip first.
  const summaryReady = !summary.isLoading;
  const usingFolder = ofFolderId != null;
  // listId is the selected folder, not null: the live path serves accounts with no mirror, and null showed the whole library under a folder heading.
  const live = useVaultMedia({
    accountId, type, listId: ofFolderId, sort, query, enabled: summaryReady && !useLocal,
  });
  const mirror = useMirrorItems({
    accountId, type, query, sort, ofFolderId, internalFolderId: standardFolderId, tags, enabled: useLocal,
  });
  const src = useLocal ? mirror : live;
  const showLoading = summary.isLoading || src.isLoading;
  const items = src.items as Tile[];
  const gridStale = !useLocal && !!live.isPlaceholderData;
  const previewIdx = preview ? items.findIndex((m) => m.id === preview.id) : -1;
  // Gate on isFetchingNextPage, not isFetching: background refetches flip isFetching and wedge the trigger.
  const pageFetching = src.isFetchingNextPage;
  const pageError = !!src.error && !pageFetching;
  loadMoreRef.current = src.loadMore;
  canLoadRef.current = src.hasMore && !pageFetching;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    // pageFetching is a dep so the observer re-arms after each page settles; a user parked at the bottom gets no new callback otherwise.
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && canLoadRef.current) loadMoreRef.current();
      },
      { root: scrollRef.current, rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [accountId, ofFolderId, standardFolderId, type, query, tags, sort, items.length, pageFetching]);

  function onGridScroll() {
    const el = scrollRef.current;
    if (!el || !canLoadRef.current) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 600) loadMoreRef.current();
  }

  const allCounts = lists.data?.all ?? null;
  const shownCounts = standardFolderId != null
    ? { photosCount: standardFolder?.kind === "photo" ? standardFolder.items : 0,
        videosCount: standardFolder?.kind === "video" ? standardFolder.items : 0, gifsCount: 0, audiosCount: 0 }
    : ofFolderId == null ? allCounts : selectedFolder;
  const typeCounts: TypeCounts = shownCounts
    ? {
        photo: shownCounts.photosCount,
        video: shownCounts.videosCount,
        gif: shownCounts.gifsCount,
        audio: shownCounts.audiosCount,
      }
    : null;

  function refreshAll() {
    invalidateVaultGrid(qc, accountId);
    void qc.invalidateQueries({ queryKey: standardFoldersKey(accountId) });
  }

  const thumbs = useThumbAutoRefresh(accountId, source);
  const ofRefresh = useOfRefresh(accountId, thumbs);

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
    selected: selectedIds,
    clearSelection: () => dispatchBrowse({ type: "clearSelection" }),
    refreshAll,
    capReason,
    refetchPlan: () => plan.refetch(),
  };

  function onSavedItem(updated: Record<string, unknown>) {
    setPreview((prev) => (prev ? { ...prev, _ai: { ...(prev._ai ?? {}), ...updated } } : prev));
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {extrasOpen && (
        <VaultExtrasTools
          accountId={accountId}
          onClose={onCloseExtras}
          isCollecting={isCollecting}
          collectPaused={run?.status === "paused"}
          totalSeen={run?.total_seen ?? null}
          cachedCount={cachedCount}
          onCollect={() => onCollect({ accountId, qc, refreshAll, isCollecting })}
          onCollectAnswer={(answer) => void onCollectAnswer(answer, { accountId, qc })}
          onDescribeAll={(mode, limit) => onDescribeAll(mode, { ...deps, describeSweep, capped, plan: plan.data, promptVersion, limit })}
          describeSweep={describeSweep}
          describeText={describeText}
          describeStopped={describeStopped}
          harvestSweep={harvestSweep}
          plan={plan.data}
          capped={capped}
          capReason={capReason}
          needsReview={needsReview}
          setNeedsReview={setNeedsReview}
          flagsReviewOpen={open === "flagsReview"}
          onOpen={setOpen}
          foldersAllowed={access === "all"}
          removeAllowed={canRemove}
          settings={access === "all" && <VaultSettingsSwitches accountId={accountId} />}
          download={{
            label: downloadLabel(fullGate, `full ${fullScope?.mode === "vault" ? "vault" : "folder"}`),
            reason: fullGate.reason,
            onStart: () => {
              if (!fullScope) return;
              void dl.start(fullScope);
              onCloseExtras();
            },
          }}
        />
      )}

      <div className={VAULT_PANES_CLASS}>
        <VaultFolderRail
          standardRows={standardRail()} standardMobile={standardRail(true)} standardSelected={standardFolderId != null}
          folders={folders}
          allCounts={allCounts}
          loading={lists.isLoading}
          error={lists.isError}
          onRetry={() => lists.refetch()}
          selectedId={ofFolderId}
          onSelect={(id) => dispatchBrowse({ type: "folder", id })}
          onChanged={refreshAll}
          onDownloadFolder={(f) => void dl.start(scopeArgs(f))}
          downloadFolderGate={dlGate("folder")}
        />

        <section className="relative flex-1 min-w-0 min-h-0 flex flex-col">
          <VaultMediaToolbar
            search={searchRaw}
            onSearch={setSearchRaw}
            sort={sort}
            onSort={setSort}
            type={type}
            onType={(value) => dispatchBrowse({ type: "mediaType", value })}
            typeCounts={typeCounts}
            loadedCount={items.length}
            onRefresh={() => { if (standardOn) standard.refresh(); if (standardFolderId == null) ofRefresh.mutate(ofFolderId); }}
            refreshing={ofRefresh.isPending || standard.syncing}
            refreshNote={ofRefresh.note}
            onSelectAll={() => dispatchBrowse({ type: "selectAll", media: items })}
            selectAllOff={gridStale}
            selectMode={selectMode}
            onToggleSelect={() => dispatchBrowse({ type: "toggleSelectMode" })}
          />
          <VaultTagChips
            accountId={accountId}
            enabled={useLocal && standardFolderId == null}
            type={type}
            query={query}
            ofFolderId={ofFolderId}
            tags={tags}
            onToggle={(tag) => dispatchBrowse({ type: "toggleTag", tag })}
            onClear={() => dispatchBrowse({ type: "clearTags" })}
          />

          <div
            ref={scrollRef}
            onScroll={onGridScroll}
            className={cn(VAULT_GRID_CLASS, selectMode && selected.size > 0 && "pb-20")}

          >
            {showLoading ? (
              <div role="status" aria-label="Loading" className="grid grid-cols-3 md:grid-cols-6 gap-2 py-4">
                {Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="aspect-square w-full rounded-md" />)}
              </div>
            ) : items.length === 0 && searchingOf ? (
              <div role="status" className="flex flex-col items-center justify-center gap-2 py-16 text-[14px] text-muted">
                <Loader2 className="h-6 w-6 animate-spin text-[#2d74ff]" />
                Searching OnlyFans…
              </div>
            ) : items.length === 0 && ofSearch.failed ? (
              <div role="alert" className="flex flex-col items-center justify-center gap-2 py-16 text-[14px] text-muted">
                OnlyFans search failed
                <button type="button" onClick={ofSearch.retry} className="text-[#2d74ff] hover:underline">Retry</button>
              </div>
            ) : items.length === 0 && pageError ? (
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
              <EmptyState className="py-10" />
            ) : (
              <>
                {searchingOf && (
                  <div role="status" title={EXTRA_LABEL}
                    className="flex items-center justify-center gap-1.5 pb-2 text-xs text-fg-dim">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[#2d74ff]" />
                    Searching OnlyFans for more…
                  </div>
                )}
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
                      onCheck={() => { if (!gridStale) dispatchBrowse({ type: "toggle", media: m }); }}
                      showOrder={usingFolder}
                      onOrder={(m, value) => setOrder(m, value, { accountId, qc, ofFolderId })}
                      thumbs={thumbs}
                    />
                  ))}
                </div>
                <div ref={sentinelRef} className="h-8" />
                <div title={EXTRA_LABEL} className="text-center text-xs text-fg-dim pt-1 pb-2">
                  {pageFetching ? (
                    <Skeleton className="mx-auto h-3 w-16" />
                  ) : src.hasMore ? (
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
              hidden={hiddenByFilter(browse)}
              hasFolders={folders.length > 0}
              canRemove={canRemove}
              busy={busy}
              capped={capped}
              capReason={capReason}
              onMove={() => setMoving(true)}
              onNewFolder={() => newFolderWithSelection(deps)}
              onDescribe={() => describeSelected(deps)}
              onClear={() => dispatchBrowse({ type: "clearSelection" })}
              onDownload={() => {
                void dl.start({
                  ...who, mode: "selection", label: `${selected.size} selected`,
                  media: [...selected.values()], source,
                  folder: selectedFolder ? { id: selectedFolder.id, name: selectedFolder.name } : null,
                }).then((ok) => { if (ok) dispatchBrowse({ type: "clearSelection" }); });
              }}
              downloadOff={selGate.reason}
              downloadLabel={downloadLabel(selGate, "selected")}
            />
          )}
        </section>
      </div>

      {moving && (
        <IfModal title="Add to category" width={480} onClose={() => setMoving(false)}>
            <div className="-my-2 max-h-[60vh] overflow-y-auto">
              {folders.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  disabled={!!busy}
                  onClick={async () => {
                    setMoving(false);
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
          onSaved={onSavedItem}
          onDeleted={canRemove ? () => {
            setPreview(null);
            qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
          } : undefined}
          describeSlot={
            <button
              type="button"
              onClick={() => describeOne(preview, { ...deps, setPreview })}
              disabled={!!busy || capped}
              title={capped ? `${EXTRA_LABEL}\n${capReason}` : EXTRA_LABEL}
              className="px-3 py-1.5 rounded-md text-sm border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
            >
              {busy === DESCRIBING
                ? "Describing…"
                : capped
                ? "Cap reached"
                : (preview._ai as { describe_status?: string } | undefined)?.describe_status === "described"
                ? "Re-describe"
                : "Describe"}
            </button>
          }
        />
      )}
      {playMedia && (
        <VaultVideoPreview
          media={playMedia}
          accountId={accountId}
          onClose={() => setPlayMedia(null)}
        />
      )}
      {open === "dupes" && canRemove && (
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

      {open === "aiFolders" && (
        <VaultAiFoldersModal accountId={accountId} onClose={() => setOpen(null)} />
      )}
      {open === "folders" && (
        <VaultInternalFoldersModal accountId={accountId} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
