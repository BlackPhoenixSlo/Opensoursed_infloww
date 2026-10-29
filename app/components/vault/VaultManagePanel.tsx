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

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { FolderInput, Square, Trash2, X } from "lucide-react";

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { EmptyState, IfModal } from "@/components/ui/infloww";
import { VaultVideoPreview } from "@/components/chat/VaultPicker";
import { useVaultAccountId } from "@/components/vault/VaultAccount";
import VaultAiFoldersModal from "@/components/vault/VaultAiFoldersModal";
import VaultDisputesModal from "@/components/vault/VaultDisputesModal";
import VaultFlagsReviewModal from "@/components/vault/VaultFlagsReviewModal";
import VaultDuplicatesModal from "@/components/vault/VaultDuplicatesModal";
import VaultPreviewMedia from "@/components/vault/VaultPreviewMedia";
import VaultPackPickerModal from "@/components/vault/VaultPackPickerModal";
import VaultFolderRail, { FolderCounts } from "@/components/vault/VaultFolderRail";
import VaultMediaToolbar, { type MediaSort, type MediaType, type TypeCounts } from "@/components/vault/VaultMediaToolbar";
import VaultTile from "@/components/vault/VaultTile";
import { useVaultLists, useVaultMedia } from "@/hooks/useVaultMedia";
import {
  addToOfFolder,
  createOfFolder,
  describeAllBody,
  describeMedia,
  useOfFoldersMirror,
  fetchCollectStatus,
  reorderItems,
  searchOf,
  startCollect,
  useDescribePlan,
  useMirrorItems,
  useVaultCacheSummary,
  cacheSummaryKey,
  invalidateVaultGrid,
  mirrorItemsKey,
} from "@/hooks/useVaultCache";
import {
  describeSweepText,
  harvestSweepLabel,
  sweepAbortedNote,
  useVaultSweep,
} from "@/hooks/useVaultSweep";
import { ApiKeyError, relay, type VaultList, type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { Skeleton } from "@/components/ui/Skeleton";

type Tile = VaultMedia & { _ai?: Record<string, unknown> };

/** The rail-and-grid row (#15). Exported for the page's no-Creator frame. */
export const VAULT_PANES_CLASS =
  "flex flex-col md:flex-row items-stretch overflow-hidden h-[70vh] md:h-auto md:flex-1 md:min-h-0";
/** The grid's scroll box (#70). */
export const VAULT_GRID_CLASS = "px-3 md:px-6 flex-1 min-h-0 overflow-y-auto";

// explicitness tiers the pricing bands key off (contract §1 bands_by_tier).
/** The three answers the flags pass gives per region. Must match
 *  `vault_ai_brief.VIS_STATES` — the server rejects anything else with a 400
 *  rather than storing a value no lane knows how to read. */
const VIS_OPTIONS = ["bare", "covered", "not_in_frame"];

const TIER_OPTIONS = ["safe", "suggestive", "explicit", "graphic", "unknown"];

/** PATCH /admin/vault-ai/items/{id} — override + lock the operator-edited fields
 *  (contract §6c). `fields` carries only the changed keys so only those lock. */
async function saveVaultItem(
  accountId: string,
  mediaId: number,
  fields: Record<string, unknown>,
): Promise<{ item: Record<string, unknown>; locked: string[] }> {
  return relay.patch(
    `/admin/vault-ai/items/${mediaId}`,
    { account_id: accountId, fields },
    { accountId },
  );
}

/** POST /admin/vault-ai/items/{id}/hide — OF's own "Remove from vault" (the same
 *  call the duplicates sweep uses). The media is HIDDEN on OF, not destroyed, so
 *  already-sent PPVs and live posts keep working — but OF exposes no unhide,
 *  which is why the UI confirms first. */
async function hideVaultItem(accountId: string, mediaId: number): Promise<void> {
  await relay.post(
    `/admin/vault-ai/items/${mediaId}/hide`,
    { account_id: accountId },
    { accountId },
  );
}

function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** The Extras drawer: the page's own tools, which the bundle does not have, one click from the header (ADR-0003).
 *  A right sheet over the page; Esc or × closes it, unless a modal above it took the Escape first. */
function ExtrasDrawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside
      role="dialog"
      aria-label={EXTRAS_OVERFLOW_LABEL}
      className="fixed inset-y-0 right-0 z-40 w-[420px] max-w-full flex flex-col border-l border-border bg-panel shadow-2xl"
    >
      <header className="h-12 shrink-0 px-4 flex items-center justify-between border-b border-border">
        <h2 title={EXTRA_LABEL} className="text-[16px] font-semibold text-fg">{EXTRAS_OVERFLOW_LABEL}</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="grid h-6 w-6 place-items-center rounded text-muted hover:text-fg">
          <X size={16} aria-hidden />
        </button>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">{children}</div>
    </aside>
  );
}

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
  const [type, setType] = useState<MediaType>("all");
  // FanId, not number: Fansly album ids are snowflakes above 2^53, and a
  // narrowed one selects a DIFFERENT album. Media ids below stay number[].
  const [ofFolderId, setOfFolderId] = useState<FanId | null>(null); // OF folder (list id)
  const [sort, setSort] = useState<MediaSort>("newest");
  const [searchRaw, setSearchRaw] = useState("");
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Tile | null>(null);
  // Full-screen playback target — hands off to the picker's VaultVideoPreview.
  const [playMedia, setPlayMedia] = useState<VaultMedia | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [showDupes, setShowDupes] = useState(false);
  const [showPackPicker, setShowPackPicker] = useState(false);
  const [showAiFolders, setShowAiFolders] = useState(false);
  const [showDisputes, setShowDisputes] = useState(false);
  const [showFlagsReview, setShowFlagsReview] = useState(false);
  const [needsReview, setNeedsReview] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<string>("");
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
    const t = setTimeout(() => setQuery(q), 250);
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

  async function onCollect() {
    if (isCollecting) return;
    try {
      await startCollect(accountId);
    } catch {
      /* already running */
    }
    qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
    for (let i = 0; i < 4; i++) {
      await new Promise((r) => setTimeout(r, 2500));
      qc.invalidateQueries({ queryKey: cacheSummaryKey(accountId) });
      const st = await fetchCollectStatus(accountId).catch(() => null);
      if (st?.run && (st.run.total_seen ?? 0) > 0) {
        refreshAll();
        break;
      }
    }
  }

  async function onDescribeAll(mode: "new" | "restage" | "force" = "new") {
    if (describeSweep.busy) return;
    if (capped) {
      // Reachable with a plan up to 30s stale (its staleTime) — the button is
      // already grey once the refetch lands. Say it rather than no-op.
      window.alert(capReason);
      plan.refetch();
      return;
    }
    if (mode !== "new") {
      const n = mode === "force" ? (plan.data?.total ?? 0) : (plan.data?.restage ?? 0);
      // Cents per item, MEASURED 2026-08-05 on 18 real stills at DeepInfra's
      // live rates — not the bake-off's original figures. Those were taken when
      // A sent 3 frames and B sent 9; the duration ladder now applies to BOTH,
      // so A sends exactly as many images as B and saves only on the shorter
      // output. A was quoted at 0.011 and really costs ~0.05 — a 5x under-count
      // that made the cheap option look free.
      const est = ((promptVersion === "v2" ? 0.052 : 0.046) * n) / 100;
      const what =
        mode === "force"
          ? `Re-describe ALL ${n} items`
          : `Re-scan ${n} items still on the other prompt`;
      if (!window.confirm(`${what} with prompt ${promptVersion.toUpperCase()}?\n\n` +
          `Estimated ~$${est.toFixed(2)} of LLM spend against today's cap.`)) {
        return;
      }
    }
    await describeSweep.start(describeAllBody({
      force: mode === "force",
      restage: mode === "restage",
      promptVersion,
    }));
  }

  function toggleSel(m: VaultMedia) {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(m.id)) n.delete(m.id);
      else n.add(m.id);
      return n;
    });
  }

  async function addSelectedToFolder(listId: FanId) {
    if (selected.size === 0) return;
    setBusy("adding to OF…");
    try {
      await addToOfFolder(accountId, listId, [...selected]);
      setSelected(new Set());
      refreshAll();
    } finally {
      setBusy("");
    }
  }

  async function newFolderWithSelection() {
    const name = window.prompt("New OF folder name:");
    if (!name?.trim()) return;
    setBusy("creating OF folder…");
    try {
      await createOfFolder(accountId, name.trim(), [...selected]);
      setSelected(new Set());
      refreshAll();
    } finally {
      setBusy("");
    }
  }

  async function describeSelected() {
    if (selected.size === 0) return;
    const ids = [...selected];
    // STOPS on the cap rather than grinding through the rest: every remaining
    // call would be refused before it fires, so continuing only keeps the
    // operator watching a counter that describes nothing. One exit either way.
    let stopped = "";
    for (let i = 0; i < ids.length && !stopped; i++) {
      setBusy(`describing ${i}/${ids.length}`);
      const r = await describeMedia(accountId, ids[i]).catch((e) => {
        if (e instanceof ApiKeyError) stopped = "key"; // toasted by relay.ts; stop, don't repeat it per item
        return null;
      });
      if (r?.status === "capped") {
        // `detail` and `capReason` are the same sentence from the same author
        // (the relay's `_vision_budget`) — this only picks whichever arrived.
        stopped = `${r.detail ?? capReason}\n\n` +
          `Described ${i} of ${ids.length} before the cap.`;
      }
    }
    setBusy("");
    setSelected(new Set());
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
    if (stopped) {
      plan.refetch();
      if (stopped !== "key") window.alert(stopped);
    }
  }

  async function describeOne(m: Tile) {
    setBusy("describing");
    try {
      const r = await describeMedia(accountId, m.id);
      if (r.status === "capped") {
        plan.refetch();
        window.alert(r.detail ?? capReason);
        return;
      }
      setPreview({ ...m, _ai: { ...(m._ai ?? {}), ...r } });
      qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
    } catch (e) {
      if (!(e instanceof ApiKeyError)) throw e; // the key toast already says why
    } finally {
      setBusy("");
    }
  }

  // After an edit save, merge the returned (effective-value) fields back into the
  // open preview so the editor reflects the override immediately, and refresh the
  // grid so the S9 overlay picks up the new description/tags.
  function onSavedItem(updated: Record<string, unknown>) {
    setPreview((prev) => (prev ? { ...prev, _ai: { ...(prev._ai ?? {}), ...updated } } : prev));
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  }

  async function setOrder(m: VaultMedia, value: number | null) {
    if (ofFolderId == null) return;
    await reorderItems(accountId, ofFolderId, [{ media_id: m.id, manual_order: value }]).catch(
      () => {},
    );
    qc.invalidateQueries({ queryKey: mirrorItemsKey(accountId) });
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Our tools, which the bundle does not have, in one Extras drawer (ADR-0003): the mirror collect, the
          describe sweep and its prompt, the keyword harvest, the duplicates, pack, AI-folder and disagreement
          reviews and the flags review. Closed by default and one click away (the header's overflow button), so the
          rail starts right under the header rule, as in the capture. */}
      {extrasOpen && (
        <ExtrasDrawer onClose={onCloseExtras}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-fg-dim">
              {isCollecting ? (
                <>
                  <span className="text-warn">●</span> collecting… {run?.total_seen ?? 0}
                </>
              ) : cachedCount > 0 ? (
                <>
                  <span className="text-ok">●</span> {cachedCount} cached
                </>
              ) : (
                "not collected"
              )}
            </span>
            {/* Desk-only batch sweeps. `md:contents` keeps every button a direct
                flex child at md, so the desktop row is untouched. */}
            <div className="hidden md:contents">
              <button
                type="button"
                onClick={onCollect}
                disabled={isCollecting}
                className="px-3 py-1.5 rounded-lg text-sm border border-accent bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
              >
                {isCollecting ? "Collecting…" : cachedCount > 0 ? "Re-collect" : "Collect all"}
              </button>
            </div>
            <div className="hidden md:contents">
              <button
                type="button"
                onClick={() => onDescribeAll("new")}
                disabled={describeSweep.busy || cachedCount === 0 || capped}
                className={cx(
                  "px-3 py-1.5 rounded-lg text-sm border disabled:opacity-50",
                  capped && !describeSweep.busy
                    ? "border-warn/50 bg-warn/10 text-warn"
                    : "border-ok/50 bg-ok/10 text-ok hover:bg-ok/20",
                )}
                title={
                  describeSweep.busy
                    ? describeText.title
                    : capped
                      ? capReason
                      : "Describe every un-described item (background)"
                }
              >
                {describeSweep.busy
                  ? `Describing ${describeText.label}`
                  : capped
                    ? "Daily AI cap reached"
                    : `Describe all${plan.data?.undescribed ? ` (${plan.data.undescribed})` : ""}`}
              </button>
              {/* Which bake-off prompt the sweep runs. B is the default and the only
                  one that emits the structured taxonomy auto-foldering needs; A is
                  ~4× cheaper for a rough first pass over a huge vault. */}
              <select
                value={promptVersion}
                onChange={(e) => setPromptVersion(e.target.value as "v1" | "v2")}
                disabled={describeSweep.busy}
                title="Describe prompt variant"
                className="px-2 py-1.5 rounded-lg text-sm bg-bg-elev-1 border border-border text-fg-dim"
              >
                <option value="v2">B · rich</option>
                <option value="v1">A · fast</option>
              </select>
              {!!plan.data?.restage && !describeSweep.busy && !capped && (
                <button
                  type="button"
                  onClick={() => onDescribeAll("restage")}
                  disabled={cachedCount === 0}
                  className="px-3 py-1.5 rounded-lg text-sm border border-warn/50 bg-warn/10 text-warn hover:bg-warn/20 disabled:opacity-50"
                  title="Re-describe items that were described with the OTHER prompt version. Resumable — already-current rows are skipped."
                >
                  Re-scan old ({plan.data.restage})
                </button>
              )}
              <button
                type="button"
                onClick={() => harvestSweep.start()}
                disabled={harvestSweep.busy || cachedCount === 0}
                className="px-3 py-1.5 rounded-lg text-sm border border-info/50 bg-info/10 text-info hover:bg-info/20 disabled:opacity-50"
                title="Run OF's own search across ~50 selling keywords and fold into local search"
              >
                {harvestSweep.busy
                  ? `Harvesting ${harvestSweepLabel(harvestSweep.progress)}`
                  : "Harvest OF (50)"}
              </button>
              <button
                type="button"
                onClick={() => setShowDupes(true)}
                disabled={cachedCount === 0}
                className="px-3 py-1.5 rounded-lg text-sm border border-err/50 bg-err/10 text-err hover:bg-err/20 disabled:opacity-50"
                title="Find re-uploaded copies and remove them from the OF vault (review + confirm first)"
              >
                Duplicates
              </button>
              <button
                type="button"
                onClick={() => setShowPackPicker(true)}
                disabled={cachedCount === 0}
                className="px-3 py-1.5 rounded-lg text-sm border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
                title="Triage every feet candidate into rungs, then publish the rungs to the OF vault"
              >
                Feet pack
              </button>
              <button
                type="button"
                onClick={() => setShowAiFolders(true)}
                disabled={cachedCount === 0}
                className="px-3 py-1.5 rounded-lg text-sm border border-accent/50 bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
                title="Group the vault into shoots and send lanes — preview first, nothing is created until you confirm"
              >
                Build AI folders
              </button>
              <button
                type="button"
                onClick={() => setShowDisputes(true)}
                disabled={cachedCount === 0}
                className="px-3 py-1.5 rounded-lg text-sm border border-warn/50 bg-warn/10 text-warn hover:bg-warn/20 disabled:opacity-50"
                title="Items where the two vision passes disagree — pick the reading that matches the picture. Your choice is locked against re-runs."
              >
                Fix disagreements
              </button>
            </div>
          </div>

          {/* A describe pass that DIED rather than finished. Only meaningful once it
              stops — while it runs the button carries the count — and it survives a
              reload, because the snapshot lives on the server. */}
          <AiKeyNotice accountId={accountId} kinds={["describe_media"]} />
          {!describeSweep.busy && describeStopped && (
            <div className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
              {describeStopped.text}
              <span className="block text-warn/70 mt-0.5">{describeStopped.detail}</span>
            </div>
          )}

          {/* The flags review, offered when a describe sweep ends with items worth a human's eye. */}
          {needsReview > 0 && !showFlagsReview && (
            <div className="rounded-lg border border-ok/50 bg-ok/10 px-3 py-2 flex items-center justify-between gap-3">
              <p className="text-[11px] text-ok">
                Described and flagged. <b>{needsReview}</b>{" "}
                {needsReview === 1 ? "item looks" : "items look"} worth your eye — the
                model disagrees with itself on them, or cannot say what is covering the body.
              </p>
              <div className="flex gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setShowFlagsReview(true)}
                  className="px-2.5 py-1 rounded-md text-[11px] font-medium border border-ok/60 text-ok hover:bg-ok/20"
                >
                  Check them
                </button>
                <button
                  type="button"
                  onClick={() => setNeedsReview(0)}
                  className="px-2 py-1 rounded-md text-[11px] text-fg-dim hover:text-fg"
                >
                  Later
                </button>
              </div>
            </div>
          )}
        </ExtrasDrawer>
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
          onSelect={setOfFolderId}
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
            onType={setType}
            typeCounts={typeCounts}
            loadedCount={items.length}
            onRefresh={refreshAll}
            onSelectAll={() => {
              setSelectMode(true);
              setSelected(new Set(items.map((m) => m.id)));
            }}
            selectMode={selectMode}
            onToggleSelect={() => {
              setSelectMode((v) => !v);
              setSelected(new Set());
            }}
          />

          <div
            ref={scrollRef}
            onScroll={onGridScroll}
            className={cx(VAULT_GRID_CLASS, selectMode && selected.size > 0 && "pb-20")}

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
                      onCheck={toggleSel}
                      showOrder={usingFolder}
                      onOrder={setOrder}
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

          {/* #74, #75: the selection bar, 38px tall, 16px above the grid's foot, 20px left and 24px right: "Selected"
              and the count, then move (#77, "Add to category") and delete (#76). Ours follow, each titled as one. */}
          {selectMode && selected.size > 0 && (
            <div className="absolute bottom-4 left-3 right-3 md:left-5 md:right-6 z-10 min-h-[38px] px-3 md:px-6 py-1 rounded-lg border border-accent/40 bg-panel/95 backdrop-blur-sm flex flex-wrap items-center gap-x-6 gap-y-1">
              <div className="flex items-center gap-1.5 text-sm font-medium">
                <span>Selected</span>
                <span>{selected.size}</span>
              </div>
              {folders.length > 0 && (
                // #74, #77: the move icon opens the "Add to category" modal.
                <button
                  type="button"
                  aria-label="Add to category"
                  title="Add to category"
                  onClick={() => setMoving(true)}
                  disabled={!!busy}
                  className="text-fg-dim hover:text-fg disabled:opacity-50"
                >
                  <FolderInput size={18} aria-hidden />
                </button>
              )}
              {/* #76: OF's remove is one file at a time here (the drawer's "Remove from vault", which OF cannot
                  undo); a batch of them is not built. */}
              <button
                type="button"
                aria-label="Delete"
                disabled
                title="not wired"
                className="text-fg-dim disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Trash2 size={18} aria-hidden />
              </button>
              <button
                type="button"
                onClick={newFolderWithSelection}
                disabled={!!busy}
                title={EXTRA_LABEL}
                className="px-2.5 py-1 rounded-md text-xs border border-border bg-bg-elev-1 hover:text-fg"
              >
                New OF folder with these
              </button>
              <button
                type="button"
                onClick={describeSelected}
                disabled={!!busy || capped}
                title={capped ? `${EXTRA_LABEL}\n${capReason}` : EXTRA_LABEL}
                className="px-2.5 py-1 rounded-md text-xs border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {capped ? "Daily AI cap reached" : "Describe selected"}
              </button>
              {busy && <span className="text-xs text-fg-dim">{busy}</span>}
              <button
                type="button"
                onClick={() => setSelected(new Set())}
                title={EXTRA_LABEL}
                className="px-2 py-1 rounded-md text-xs text-fg-dim hover:text-fg"
              >
                Clear
              </button>
            </div>
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
                    await addSelectedToFolder(f.id);
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
                onClick={() => describeOne(preview)}
                disabled={!!busy || capped}
                title={capped ? `${EXTRA_LABEL}\n${capReason}` : EXTRA_LABEL}
                className="px-2.5 py-1 rounded-md text-xs border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
              >
                {busy === "describing"
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
      {showDupes && (
        <VaultDuplicatesModal accountId={accountId} onClose={() => setShowDupes(false)} />
      )}
      {showPackPicker && (
        <VaultPackPickerModal
          accountId={accountId}
          category="feet"
          onClose={() => setShowPackPicker(false)}
        />
      )}
      {showFlagsReview && (
        <VaultFlagsReviewModal
          accountId={accountId}
          onClose={() => setShowFlagsReview(false)}
        />
      )}

      {showDisputes && (
        <VaultDisputesModal accountId={accountId} onClose={() => setShowDisputes(false)} />
      )}

      {showAiFolders && (
        <VaultAiFoldersModal accountId={accountId} onClose={() => setShowAiFolders(false)} />
      )}
    </div>
  );
}

/** Remove-from-vault control. Two-step by design: this calls OF's own "Remove
 *  from vault", and OF exposes NO unhide — so a stray click must never be able
 *  to take media off the vault. The copy says exactly what happens (hidden, not
 *  destroyed; sent PPVs keep working) so the confirm is an informed one. */
function VaultDeleteButton({
  media,
  accountId,
  onDeleted,
}: {
  media: VaultMedia;
  accountId: string;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function doDelete() {
    setBusy(true);
    setErr("");
    try {
      await hideVaultItem(accountId, media.id);
      onDeleted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "remove failed");
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="px-3 py-1.5 rounded-md text-sm border border-err/50 bg-err/10 text-err hover:bg-err/20"
      >
        Remove from vault
      </button>
    );
  }
  return (
    <div className="w-full rounded-md border border-err/50 bg-err/10 p-2.5 space-y-2">
      <div className="text-xs text-err leading-snug">
        Remove <b>#{media.id}</b> from the OnlyFans vault? This uses OF&rsquo;s own
        “Remove from vault”, so it is <b>hidden, not destroyed</b> — already-sent
        PPVs and live posts keep working. <b>OnlyFans offers no undo.</b>
      </div>
      {err && <div className="text-xs text-err">{err}</div>}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={doDelete}
          className="flex-1 px-3 py-1.5 rounded-md text-sm border border-err/60 bg-err/20 text-err hover:bg-err/30 disabled:opacity-50"
        >
          {busy ? "Removing…" : "Yes, remove"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="px-3 py-1.5 rounded-md text-sm border border-border hover:bg-bg-elev-1 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Click-to-edit detail/editor for one tile: the FULL description, short tags,
 *  explicitness tier, and suggested caption/script — all editable. Save writes
 *  ONLY the changed fields through the override+lock endpoint (contract §6c), so
 *  a later Describe rerun can't clobber what the operator touched. */
/** Read-only view of the V2 describe taxonomy (`_ai.fields`, projected straight
 *  from `ai_fields_json`). These 20-odd fields have always been STORED — acts,
 *  clothing_state, beats, primary_folder, penetration, camera, confidence — but
 *  until now nothing rendered them, so a described item looked like it only had
 *  a sentence and some tags. `beats` is the clip's ordered progression and is
 *  the reason a long video is worth describing at all, so it leads.
 *
 *  Not editable: the editable, lockable fields are the real columns above. This
 *  is the raw AI read-out, shown so you can see what the model actually found. */
// What the model found, ranked by what an operator actually acts on. PRIMARY is
// shown expanded; everything else sits below the fold behind a toggle. `beats`
// leads because it's the clip's ordered progression — the whole reason a long
// video is worth describing.
const AI_PRIMARY = [
  "acts",
  "clothing_state",
  "penetration",
  "position",
  "primary_folder",
  "explicitness",
] as const;
// Internal bookkeeping stamps, not model output.
const AI_HIDE = new Set(["beats", "description", "tags", "_prompt_version", "_frames"]);

function fmtAi(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (v === true) return "yes";
  if (v === false) return "no";
  return String(v);
}

function AiRows({ entries }: { entries: [string, unknown][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px] m-0">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg-dim whitespace-nowrap">{k.replace(/_/g, " ")}</dt>
          <dd className="m-0 text-fg break-words">{fmtAi(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The V2 describe taxonomy (`_ai.fields`, projected from `ai_fields_json`).
 *  These ~20 fields have always been STORED; until now nothing rendered them,
 *  so a described item looked like it only had a sentence and some tags.
 *  Read-only — the editable, lockable fields are the real columns. */
function AiFieldsPanel({ fields }: { fields?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  if (!fields || Object.keys(fields).length === 0) return null;

  const beats = Array.isArray(fields.beats) ? (fields.beats as unknown[]) : [];
  const live = Object.entries(fields).filter(
    ([k, v]) =>
      !AI_HIDE.has(k) && v !== null && v !== "" && v !== "none" &&
      !(Array.isArray(v) && v.length === 0),
  );
  const primary = live.filter(([k]) => (AI_PRIMARY as readonly string[]).includes(k));
  const rest = live.filter(([k]) => !(AI_PRIMARY as readonly string[]).includes(k));

  return (
    <div className="space-y-2">
      {beats.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-fg-dim mb-1">
            What happens ({beats.length} steps)
          </div>
          <ol className="list-decimal pl-4 text-[12.5px] text-fg space-y-0.5 m-0">
            {beats.map((b, i) => (
              <li key={i}>{String(b)}</li>
            ))}
          </ol>
        </div>
      )}
      {primary.length > 0 && <AiRows entries={primary} />}
      {rest.length > 0 && (
        <div className="rounded-lg border border-border bg-bg-elev-1/40">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[11px] uppercase tracking-wide text-fg-dim hover:text-fg"
          >
            <span>{open ? "▾" : "▸"}</span>
            <span>More AI detail</span>
            <span className="text-fg-dim/70 normal-case tracking-normal">
              {rest.length} fields
            </span>
          </button>
          {open && (
            <div className="px-2.5 pb-2.5">
              <AiRows entries={rest} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function VaultItemEditor({
  media,
  accountId,
  onSaved,
  mediaSlot,
  deleteSlot,
}: {
  media: Tile;
  accountId: string;
  onSaved: (updated: Record<string, unknown>) => void;
  /** The preview image/player. Rendered BELOW the action bar so Save and Remove
   *  are reachable without scrolling past a tall video. */
  mediaSlot?: React.ReactNode;
  deleteSlot?: React.ReactNode;
}) {
  const ai = (media._ai ?? {}) as Record<string, unknown>;
  const described =
    !!ai.description || !!ai.video_description || !!(ai.tags as unknown[] | undefined)?.length;

  const priceCents = ai.suggested_price_cents as number | undefined;

  const init = {
    desc: (ai.description || ai.video_description || "") as string,
    tags: (((ai.tags as string[] | undefined) ?? []) as string[]).join(", "),
    tier: (ai.explicitness_tier as string | undefined) ?? "",
    cap: (ai.suggested_caption as string | undefined) ?? "",
    script: (ai.suggested_script as string | undefined) ?? "",
    price: typeof priceCents === "number" ? (priceCents / 100).toFixed(2) : "",
    // The exposure flags. They decide the folder, the price band and whether
    // an item may be mass-sent, so an operator who spots a wrong one while
    // editing a caption should be able to fix it here rather than hunting for
    // the review modal.
    breasts: (ai.breasts_vis as string | undefined) ?? "",
    vulva: (ai.vulva_vis as string | undefined) ?? "",
    anus: (ai.anus_vis as string | undefined) ?? "",
  };

  const [desc, setDesc] = useState(init.desc);
  const [tags, setTags] = useState(init.tags);
  const [tier, setTier] = useState(init.tier);
  const [cap, setCap] = useState(init.cap);
  const [script, setScript] = useState(init.script);
  const [priceStr, setPriceStr] = useState(init.price);
  const [breasts, setBreasts] = useState(init.breasts);
  const [vulva, setVulva] = useState(init.vulva);
  const [anus, setAnus] = useState(init.anus);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string[] | null>(null);
  const [err, setErr] = useState("");
  const [locked, setLocked] = useState<Set<string>>(new Set());

  // Only fields whose value actually changed are sent (and thus locked).
  const changed: Record<string, unknown> = {};
  if (desc !== init.desc) changed.description = desc;
  if (tags !== init.tags) changed.tags = tags;
  if (tier !== init.tier) changed.explicitness_tier = tier;
  if (cap !== init.cap) changed.suggested_caption = cap;
  if (script !== init.script) changed.suggested_script = script;
  // Dollars in the input → cents on the wire. Blank clears the price; garbage is
  // simply not sent, so a typo can't wipe a real price.
  if (breasts !== init.breasts) changed.breasts_vis = breasts;
  if (vulva !== init.vulva) changed.vulva_vis = vulva;
  if (anus !== init.anus) changed.anus_vis = anus;
  const priceTrimmed = priceStr.trim();
  if (priceTrimmed !== init.price) {
    if (priceTrimmed === "") {
      changed.suggested_price_cents = null;
    } else {
      const n = Number(priceTrimmed.replace(/[^0-9.]/g, ""));
      if (Number.isFinite(n)) changed.suggested_price_cents = Math.round(n * 100);
    }
  }
  const dirty = Object.keys(changed).length > 0;

  async function onSave() {
    if (!dirty || saving) return;
    setSaving(true);
    setErr("");
    setSaved(null);
    try {
      const res = await saveVaultItem(accountId, media.id, changed);
      setLocked(new Set(res.locked ?? []));
      setSaved(Object.keys(changed));
      onSaved(res.item ?? {});
    } catch (e) {
      setErr(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  const lockBadge = (field: string) =>
    locked.has(field) ? <span className="ml-1 text-[10px] text-warn" title="Locked — a Describe rerun won't overwrite this">🔒</span> : null;

  const label = "text-[11px] uppercase tracking-wide text-fg-dim";
  const inputCls =
    "w-full px-2 py-1.5 rounded-md text-base md:text-sm bg-bg-elev-1 border border-border focus:border-accent outline-none";

  return (
    <div className="space-y-2.5">
      {/* Actions first, and sticky: Save and Remove stay reachable no matter how
          far down the fields you've scrolled, and you never have to scroll PAST
          a tall video to reach them. */}
      <div className="sticky top-0 z-10 -mx-3 px-3 py-2 bg-panel/95 backdrop-blur-sm border-b border-border flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={!dirty || saving}
          className="px-3 py-1.5 rounded-lg text-sm border border-accent bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save & lock"}
        </button>
        {deleteSlot}
        <span className="ml-auto text-right">
          {saved && !err && (
            <span className="text-xs text-ok">
              Saved — locked {saved.length} field{saved.length === 1 ? "" : "s"}
            </span>
          )}
          {err && <span className="text-xs text-err">{err}</span>}
        </span>
      </div>
      {mediaSlot}
      {!described && (
        <div className="text-xs text-fg-dim">Not described yet — click Describe, or write fields below.</div>
      )}
      <div>
        <div className={label}>Description{lockBadge("description")}</div>
        <textarea
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          rows={3}
          placeholder="Full description…"
          className={cx(inputCls, "mt-1 resize-y")}
        />
      </div>
      {/* The AI read-out sits directly under the description — it's what you
          check the description against, and it drives foldering. */}
      <AiFieldsPanel fields={ai.fields as Record<string, unknown> | undefined} />
      <div>
        <div className={label}>Tags{lockBadge("tags")}</div>
        <input
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="comma, separated, tags"
          className={cx(inputCls, "mt-1")}
        />
      </div>
      <div>
        <div className={label}>
          What is on show — decides the folder, the price and whether it can be
          mass-sent
        </div>
        <div className="flex gap-2 mt-1">
          {(
            [
              ["breasts", breasts, setBreasts, "breasts_vis"],
              ["vulva", vulva, setVulva, "vulva_vis"],
              ["anus", anus, setAnus, "anus_vis"],
            ] as const
          ).map(([name, val, set, field]) => (
            <div key={name} className="flex-1">
              <div className="text-[10px] text-fg-dim">
                {name}
                {lockBadge(field)}
              </div>
              <select
                value={VIS_OPTIONS.includes(val) ? val : ""}
                onChange={(e) => set(e.target.value)}
                className={cx(inputCls, "mt-0.5")}
              >
                <option value="">—</option>
                {VIS_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v === "not_in_frame" ? "not in frame" : v}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <div className="flex-1">
          <div className={label}>Tier{lockBadge("explicitness_tier")}</div>
          <select
            value={TIER_OPTIONS.includes(tier) ? tier : ""}
            onChange={(e) => setTier(e.target.value)}
            className={cx(inputCls, "mt-1")}
          >
            <option value="">—</option>
            {TIER_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <div className={label}>Price{lockBadge("suggested_price_cents")}</div>
          <div className="relative mt-1">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-base md:text-sm text-fg-dim pointer-events-none">
              $
            </span>
            <input
              value={priceStr}
              onChange={(e) => setPriceStr(e.target.value)}
              inputMode="decimal"
              placeholder="—"
              title="Your price for this media. Attaching media in chat prices the message at the HIGHEST price among the selected items."
              className={cx(inputCls, "pl-5")}
            />
          </div>
        </div>
      </div>
      <div>
        <div className={label}>Suggested caption{lockBadge("suggested_caption")}</div>
        <input
          value={cap}
          onChange={(e) => setCap(e.target.value)}
          placeholder="One-line PPV/DM caption…"
          className={cx(inputCls, "mt-1")}
        />
      </div>
      <div>
        <div className={label}>Suggested script{lockBadge("suggested_script")}</div>
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={2}
          placeholder="Longer sell copy for this item…"
          className={cx(inputCls, "mt-1 resize-y")}
        />
      </div>
      {!dirty && !saved && !err && (
        <div className="text-xs text-fg-dim pt-0.5">Edit a field to enable save.</div>
      )}
    </div>
  );
}
