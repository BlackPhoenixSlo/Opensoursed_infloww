"use client";

/**
 * FanList — the left rail of /inbox (formerly ChatList).
 *
 * Rows display fan avatar, name, last message preview, unread dot, and
 * (in Unified mode) a colored dot identifying the model account. The
 * dot color comes from AccountMeta.color, which Setup lets the user set.
 *
 * Click a row → notify parent with (accountId, fanId). Parent owns the
 * "which chat is selected" state because that state also drives the
 * right-pane MessageList.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { chatListAccountKey, chatRowKey, useChatList, listPaintKey } from "@/hooks/useChatList";
import { useUnreadMessagesPrefetch } from "@/hooks/useUnreadMessagesPrefetch";
import { useTrailingDebounce } from "@/hooks/useTrailingDebounce";
import { prefetchChatMessages } from "@/hooks/useChatMessages";
import { fetchAllVaultLists } from "@/hooks/useVaultMedia";
import { ofUserNameKey, useOFUserNameMap, type OFUserName } from "@/hooks/useOFUser";
import { useRecentChatsLocal } from "@/hooks/useRecentChatsLocal";
import { perfPaintOnce } from "@/lib/perfLog";
import { useAccountLabel, usePlatformAccounts } from "@/hooks/useAccounts";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useFanSpend } from "@/hooks/useFanSpend";
import { useFanDrawerDefault } from "@/hooks/useFanDrawerDefault";
import { useBlurMode } from "@/hooks/useBlurMode";
import { useCompactMedia } from "@/hooks/useCompactMedia";
import {
  useChatSortMode,
  hybridScore,
  HALF_LIFE_IDLE,
  HALF_LIFE_UNRESPONDED,
  HALF_LIFE_UNREAD,
} from "@/hooks/useChatSortMode";
import { useDeferredMount } from "@/hooks/useDeferredMount";
import { useFanActivity } from "@/hooks/useLastPurchases";
import { useAllChatFolders, useChatFolders } from "@/hooks/useChatFolders";
import { useScope } from "@/contexts/ScopeContext";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { MP } from "@/lib/messagesPro";
import { ofMeQuery } from "@/lib/ofMe";
import { cn } from "@/lib/utils";
import { describeLoadError, relay, type OFChatItem } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId, lastMessageFromFan, sameUserId } from "@/lib/fanId";
import { isUnreadChat } from "@/lib/chatUnread";
import { FanListBulkBar } from "./FanListBulkBar";
import { FanListFilters, type ActiveChip } from "./FanListFilters";
import { FanListHeader } from "./FanListHeader";
import { FanListEmpty, FanListSkeleton, LoadMoreConversations, ShowMoreRows } from "./FanListStates";
import { FanRow, fanNameOf } from "./FanRow";
import {
  canAutofill, initialPaging, isCapped, pagingReducer, pagingView,
} from "./fanListPaging";
import { FolderPicker } from "./FolderPicker";
import { SplitInbox } from "./SplitInbox";
import { isFanOnline } from "./isFanOnline";
import { totalSpendOf } from "./totalSpend";
import { useInboxGroup } from "./useInboxGroup";
import { BRAND_NAME } from "@/lib/brand";

/** Owe reply auto-paginates until OWE_REPLY_TARGET rows are filled or
 *  OWE_REPLY_SCAN_CAP rows have been scanned (whichever comes first). */
const OWE_REPLY_TARGET = 8;       // stop early once we have this many on screen
const OWE_REPLY_SCAN_CAP = 100;   // and never scan more than this many chats deep

// The search box is sent as OF's `query` once typing pauses this long: each
// live search takes seconds (measured 6.8-8.3 s on a live deployment), so a name typed fast is
// one search, not one per letter. 250 ms, as the PPV fan search, the GIF and
// tag pickers and the in-thread search debounce.
export const SEARCH_DEBOUNCE_MS = 250;

if (typeof window !== "undefined" && !(window as unknown as { __chatlistBuildLogged?: boolean }).__chatlistBuildLogged) {
  console.info("[ChatList] build chats-scroll-cap-v6 (rt-row-bubble) loaded");
  (window as unknown as { __chatlistBuildLogged?: boolean }).__chatlistBuildLogged = true;
}

export interface FanListSelection {
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
}

export function FanList({
  selected, onSelect, setTabTitle = true, actions, onlineOnly = false, onlineIds,
}: {
  selected: FanListSelection | null;
  onSelect: (sel: FanListSelection) => void;
  /** When true (default) ChatList writes "(N) Inflowwww" into document.title
   *  based on the All-set attention count. Pages that want a different
   *  tab-title format (e.g. /group) opt out and set their own. */
  setTabTitle?: boolean;
  /** Rendered between the Fan List header and its filters: Messages Pro's
   *  Fan List buttons. */
  actions?: ReactNode;
  /** Show only the Fans `isFanOnline` counts as online, on top of the
   *  active filter chip (Messages Pro's "Online Fans"). */
  onlineOnly?: boolean;
  /** Fan ids (as text) on the scoped Creator's OnlyFans online list: each
   *  counts as online alongside the row rule. */
  onlineIds?: ReadonlySet<string>;
}) {
  const { scope } = useScope();
  const accounts = usePlatformAccounts();
  const creatorName = useAccountLabel(scope.kind === "model" ? scope.accountId : null);
  const qc = useQueryClient();
  const [active, setActive] = useState<ActiveChip>({ kind: "builtin", key: "all" });
  // `typed` is the search box; `query` is the search the list runs, `typed`
  // trimmed once it rests SEARCH_DEBOUNCE_MS. Clearing the box applies at once.
  const [typed, setTyped] = useState("");
  const query = useTrailingDebounce(typed.trim(), SEARCH_DEBOUNCE_MS, (q) => !q);
  const [markingAll, setMarkingAll] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [splitInboxOpen, setSplitInboxOpen] = useState(false);
  const chatterOnly = useIsChatterOnly();
  const [keepDrawerOpen, setKeepDrawerOpen] = useFanDrawerDefault();
  const [blurMode, setBlurMode] = useBlurMode();
  const [compactMedia, setCompactMedia] = useCompactMedia();
  const [sortMode, setSortMode] = useChatSortMode();
  // The list on screen; a new one gets a fresh paging budget (one action).
  // `accountKey` is useChatList's: the Creator, or in All Models the set.
  const accountKey = chatListAccountKey(scope, accounts);
  const view = pagingView({ scopeKind: scope.kind, accountKey, active, query });
  const [paging, dispatchPaging] = useReducer(pagingReducer, view, initialPaging);
  // Reset during render, not in an effect: the new list's first render must
  // not draw or page with the old list's budget. `view` is a string: settles.
  if (paging.view !== view) dispatchPaging({ type: "resetFor", view });
  // Select mode (`FanListBulkBar`): the picked rows' keys, or null outside it.
  const [picks, setPicks] = useState<ReadonlySet<string> | null>(null);

  // Hover-prefetch for chat messages. When the pointer rests on a row
  // for ~120ms we warm its thread (`prefetchChatMessages`: useChatMessages'
  // own head page, merged over what is cached, so a paged history or a live
  // message survives it), so by the time the user actually clicks the first
  // page is already in cache and the chat opens instantly. The 120ms dwell
  // prevents brushing past 30 rows from firing 30 requests.
  //
  // Background priority is required, not cosmetic: an untagged relay.get
  // defaults to 'user' ([relay.ts:78]), so sweeping the pointer down the
  // list would spend the per-account lane's reserved user slots on rows
  // nobody opened — and the click that follows would queue behind the
  // hovers that preceded it. Only a click waits on 'user'
  // ([useChatList.ts:260-264]). A click landing mid-prefetch joins it
  // (`yieldOnOpen: false`) and so inherits the background lane; that is the
  // accepted trade — it is the same request either way, already in flight.
  const prefetchTimerRef = useRef<number | null>(null);
  // The selection whose row was last scrolled into view. A selection's row
  // scrolls (nearest edge) the first time it renders, then never again for
  // that selection, so the list doesn't jump on every render.
  const scrolledSelectionRef = useRef<string | null>(null);
  const PREFETCH_DWELL_MS = 120;
  const prefetchMessages = useCallback((aid: string, fid: FanId) => {
    if (!aid || !fid) return;
    void prefetchChatMessages(qc, aid, fid, { yieldOnOpen: false });
  }, [qc]);
  // Vault prefetch on hover. TanStack treats prefetchQuery as a no-op
  // when the query is still fresh (staleTime), so this is cheap to fire
  // on every hover — if the inbox-wide warmer already populated this
  // account's caches we just hit the in-memory hit and bail. When the
  // user hovers a row faster than the warmer reaches that account, this
  // covers the gap. Tagged background-priority so a concurrent vault
  // open still jumps the lane. Keys mirror useVaultLists/useVaultMedia.
  const prefetchVault = useCallback((aid: string) => {
    if (!aid) return;
    qc.prefetchQuery({
      queryKey: ["vault-lists", aid],
      // Shared paginating fetcher — a bare limit=50 fetch here would poison
      // the picker's cache with a truncated folder list (see fetchAllVaultLists).
      queryFn: () => fetchAllVaultLists({ accountId: aid, priority: "background" }),
      staleTime: 5 * 60 * 1000,
    }).catch(() => {});
    qc.prefetchInfiniteQuery({
      queryKey: ["vault-media", aid, "all", null],
      initialPageParam: 0,
      queryFn: () =>
        relay.get(
          "/api/of/v2/vault/media?limit=24&offset=0&type=all",
          { accountId: aid, priority: "background" },
        ),
      staleTime: 60_000,
    }).catch(() => {});
  }, [qc]);
  // Warm one Fan: the thread and the Vault. A press calls it at once (the
  // tap IS the intent, so no dwell); hover and focus call it after the dwell.
  const prefetchRowNow = useCallback((aid: string, fid: FanId) => {
    prefetchMessages(aid, fid);
    prefetchVault(aid);
  }, [prefetchMessages, prefetchVault]);
  const scheduleRowPrefetch = useCallback((aid: string, fid: FanId) => {
    if (prefetchTimerRef.current != null) window.clearTimeout(prefetchTimerRef.current);
    prefetchTimerRef.current = window.setTimeout(() => {
      prefetchTimerRef.current = null;
      prefetchRowNow(aid, fid);
    }, PREFETCH_DWELL_MS);
  }, [prefetchRowNow]);
  const cancelRowPrefetch = useCallback(() => {
    if (prefetchTimerRef.current != null) {
      window.clearTimeout(prefetchTimerRef.current);
      prefetchTimerRef.current = null;
    }
  }, []);
  // Ref for the selected row only. React calls it whenever that row mounts;
  // scrolledSelectionRef keeps it to one scroll per selection.
  // Stable (it reads the selection through a ref), so a memoized row is not
  // re-rendered for a selection that is not its own.
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const revealSelectedRow = useCallback((el: HTMLButtonElement | null) => {
    const sel = selectedRef.current;
    if (!el || !sel) return;
    const key = `${sel.accountId}:${sel.fanId}`;
    if (scrolledSelectionRef.current === key) return;
    scrolledSelectionRef.current = key;
    el.scrollIntoView({ block: "nearest" });
  }, []);
  // The parent's onSelect, made stable for the memoized rows (callers pass
  // inline arrows).
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selectRow = useCallback((sel: FanListSelection) => onSelectRef.current(sel), []);
  // Unmount cleanup: a pending prefetch timer would otherwise fire after
  // the component is gone (cheap but pointless network).
  useEffect(() => () => {
    if (prefetchTimerRef.current != null) {
      window.clearTimeout(prefetchTimerRef.current);
      prefetchTimerRef.current = null;
    }
  }, []);

  // Defer non-critical decoration queries (spend, last purchase, folders)
  // so they don't compete with /chats + enrichWithUsers for OF bandwidth
  // and the relay thread pool on cold load. Two tiers so chips don't all
  // pop in at once:
  //   • foldersReady  (~2.5s) — folder list + activity (cheap, local DB)
  //   • spendReady    (~5.5s) — /users/list view=x spend chips
  //                              (heaviest OF call, lands last)
  const foldersReady = useDeferredMount(2500);
  const spendReady = useDeferredMount(5500);

  // Pinned chat-folders (per single account). Unified mode hides them
  // because pinning is per-account on OF's side.
  const singleAcctId = scope.kind === "model" ? scope.accountId : null;
  // The Split Inbox group chosen in "All inboxes"; session state per Creator.
  const inbox = useInboxGroup(singleAcctId);
  const pinnedFolders = useChatFolders(foldersReady ? singleAcctId : null).data ?? [];
  // The pencil ("Pin lists as chips") shows once the Creator has any OF list (mj:3067); same fetch.
  const hasLists = !!useAllChatFolders(foldersReady ? singleAcctId : null).data?.length;
  // "Unread with tips" is OF's per-Creator filter, offered only while the
  // Creator has tips on (as OF's own chats list gates it, ofMirrorChats.ts).
  const tipsEnabled = useQuery({
    ...ofMeQuery(foldersReady ? singleAcctId : null),
    select: (me) => me.tipsEnabled === true,
  }).data ?? false;

  // If the active folder chip got unpinned (or we switched into unified
  // scope), fall back to "All" so we don't hold a phantom selection.
  useEffect(() => {
    if (active.kind !== "folder") return;
    const stillPinned = pinnedFolders.some((f) => String(f.id) === active.listId);
    if (!stillPinned) setActive({ kind: "builtin", key: "all" });
  }, [active, pinnedFolders]);
  // Likewise when "Unread with tips" leaves the chip row.
  useEffect(() => {
    if (!tipsEnabled && active.kind === "builtin" && active.key === "unread_tips") {
      setActive({ kind: "builtin", key: "all" });
    }
  }, [active, tipsEnabled]);

  // Server-side filter to send to /chats. The standard built-ins map 1:1
  // (with "all" → null). `owe-reply` is client-side only — we still pull
  // the full list. Folder selections map to filter=null + list_id.
  const serverFilter =
    active.kind === "builtin"
      ? (active.key === "all" || active.key === "owe-reply" ? null : active.key)
      : null;
  const serverListId =
    active.kind === "folder" ? active.listId : null;

  const q = useChatList({
    filter: serverFilter,
    listId: serverListId,
    query: query || null,
  });

  // useChatList returns a fresh object literal (with a fresh `loadMore`
  // arrow) every render, so depending on the whole `q` in effects would
  // tear down + rebuild the IntersectionObserver and re-run the owe-reply /
  // autofill loaders on every re-render (SSE patches, spend/activity
  // arrivals, sort recomputes). Keep a ref to the latest `q` and expose a
  // STABLE loadMore that reads through it, so those effects can depend on
  // the specific primitives they use (q.hasMore / q.isFetchingMore) plus a
  // stable callback instead of the unstable object.
  const qRef = useRef(q);
  qRef.current = q;
  const loadMore = useCallback(() => qRef.current.loadMore(), []);

  const accountById = useMemo(() => {
    const m = new Map<string, { color?: string | null; nickname?: string | null }>();
    for (const a of accounts) m.set(a.id, { color: a.color, nickname: a.nickname });
    return m;
  }, [accounts]);

  const allRows = q.data ?? [];

  // Cold-start placeholder: while the real `/chats` fetch is still in
  // flight and we have no rows yet, render the local SQLite seed
  // (sub-50ms) so the panel has clickable rows immediately. When the
  // real query lands the seed dissolves on the next render — `q.data`
  // takes over because `displayRows` reads from it first. Filter the
  // seed by accountId in single-model scope so we don't briefly flash
  // other accounts' chats. Enabled only while pending so the seed
  // query doesn't keep running once the real list is in cache.
  const seedAccountId = scope.kind === "model" ? scope.accountId : null;
  const seedQ = useRecentChatsLocal({
    enabled: q.isPending,
    limit: 25,
    accountId: seedAccountId,
  });

  // Owe-reply: client-side filter on `lastFromFan`. Same logic as the
  // yellow-dot pill in the row — fan sent the latest message, ball in
  // our court — but extended to include unread chats (which also imply
  // they sent last).
  const oweReplyActive = active.kind === "builtin" && active.key === "owe-reply";
  // The row's owe dot belongs to the Owe reply extra (ADR-0003; spec, Rows):
  // it shows only while that filter is on.
  const showOweDots = oweReplyActive;
  const isUnresponded = useCallback((c: OFChatItem) => {
    const accountId = c.__accountId ?? (scope.kind === "model" ? scope.accountId : "");
    return lastMessageFromFan(c, accountId);
  }, [scope]);
  // Creators WE restricted on OF (relay stamps withUser.isRestricted off its
  // durable of_restricted registry) never count as unread/owe-reply — we cut
  // them off on purpose, their threads aren't backlog. Mirrors the server-side
  // roster-badge fold exactly, so chips and badges can't disagree over them.
  const notRestricted = useCallback(
    (c: OFChatItem) => !c.withUser?.isRestricted, []);
  const chipRows = useMemo(() => {
    if (!oweReplyActive) return allRows;
    return allRows.filter((c) => isUnresponded(c) && notRestricted(c));
  }, [allRows, oweReplyActive, isUnresponded, notRestricted]);
  // The Split Inbox group ANDs with the chip or folder and the search; chip
  // counts are not narrowed by it (spec, Split Inbox).
  const rows = useMemo(
    () => (inbox.inGroup ? chipRows.filter(inbox.inGroup) : chipRows),
    [chipRows, inbox.inGroup],
  );
  // Owe reply and a group narrow the loaded rows client-side, so each pages
  // on until OWE_REPLY_TARGET rows match, OWE_REPLY_SCAN_CAP rows are
  // scanned, or no pages remain (story 61), or a load failed, so a failing
  // page is not retried in a loop; see the fill effect below.
  const fillActive = oweReplyActive || inbox.group != null;
  const fillDone = !fillActive || rows.length >= OWE_REPLY_TARGET ||
    allRows.length >= OWE_REPLY_SCAN_CAP || !q.hasMore || q.isError;
  // The fill has finished its bounded walk: no other loader pages past it.
  const fillExhausted = fillActive && fillDone;
  // A group still filling is not an empty group.
  const groupFilling = inbox.group != null && !fillDone;

  // True only when we're rendering local-DB seed in place of real data.
  // Used to (a) display seed rows in the list, and (b) prevent Work
  // Unit B's autofill effect from terminating against the seed's
  // visual overflow — otherwise loadMore would never fire even when
  // the real list is empty and `hasMore` is true.
  const isFromSeed = q.isPending && allRows.length === 0 && seedQ.rows.length > 0;
  const displayRows: OFChatItem[] = useMemo(() => {
    if (!isFromSeed) return rows;
    const seed = oweReplyActive ? seedQ.rows.filter(isUnresponded) : seedQ.rows;
    return inbox.inGroup ? seed.filter(inbox.inGroup) : seed;
  }, [isFromSeed, rows, oweReplyActive, seedQ.rows, isUnresponded, inbox.inGroup]);

  // The rail on screen. Paint attribution is keyed by it.
  const listKey = listPaintKey(scope, serverFilter, serverListId, query || null);

  // `painted` — the first commit with clickable rows in the rail, seed or
  // real. Pairs with the `requested` that fetchPage logged for page 0, so
  // the log finally carries the number the user experiences instead of only
  // OF's round-trip. `fromSeed` keeps the two populations separable.
  useEffect(() => {
    if (displayRows.length === 0) return;
    perfPaintOnce(listKey, "chat.list", {
      count: displayRows.length,
      fromSeed: isFromSeed,
    });
  }, [displayRows, isFromSeed, listKey]);

  // Chip counts — derived from already-cached data, zero new fetches.
  // useChatList re-renders ChatList whenever SSE patches the chats cache
  // (useInboxRealtime patches EVERY ["chats", ...] cache, including the
  // active one we subscribe to), so reading qc.getQueryData at render
  // time picks up fresh values without an extra subscription.
  // 25 = useChatList's PAGE_SIZE default; mirror it so the cache key matches.
  const allFilterKey = useMemo(
    () => ["chats", scope.kind, accountKey, null, null, query || null, 25] as const,
    [scope.kind, accountKey, query],
  );
  const allChipBase = useMemo<OFChatItem[]>(() => {
    // When the All filter is the active query, the live rows ARE the all set.
    if (active.kind === "builtin" && active.key === "all") return allRows;
    const cached = qc.getQueryData<{ pages: { rows: OFChatItem[] }[] }>(allFilterKey);
    if (!cached?.pages) return [];
    const out: OFChatItem[] = [];
    const seen = new Set<string>();
    for (const p of cached.pages) for (const c of p.rows) {
      const k = `${c.__accountId ?? ""}:${c.withUser.id}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(c);
    }
    return out;
  }, [active, allRows, qc, allFilterKey]);
  const activeCount = useMemo(
    () => chipRows.filter((c) => notRestricted(c) && (c.hasUnread || isUnresponded(c))).length,
    [chipRows, isUnresponded, notRestricted],
  );
  const { allCount, unreadCount, oweReplyCount } = useMemo(() => {
    const counted = allChipBase.filter(notRestricted);
    return {
      allCount: counted.filter((c) => c.hasUnread || isUnresponded(c)).length,
      unreadCount: counted.filter((c) => c.hasUnread).length,
      oweReplyCount: counted.filter((c) => isUnresponded(c)).length,
    };
  }, [allChipBase, isUnresponded, notRestricted]);

  const inboxTabTitle = allCount > 0
    ? `(${allCount}) Inbox · ${BRAND_NAME}`
    : `Inbox · ${BRAND_NAME}`;
  useDocumentTitle(inboxTabTitle, setTabTitle);

  // Deferred: pass empty inputs until the staggered ready flags flip,
  // which short-circuits the inner useQueries fan-out and keeps the cold
  // load free of these chip-population calls. Spend uses the later flag
  // (5.5s) because it issues the heaviest OF call (/users/list view=x);
  // activity uses the earlier flag (2.5s) — payouts is cheap and cached
  // forever after first session.
  const { spend: spendMap, loaded } = useFanSpend(spendReady ? rows : []);
  // Spend has landed, not just the empty input the deferral passes.
  const spendLoaded = spendReady && loaded;
  // One transactions feed per active account in scope. Memoized to avoid
  // re-triggering useQueries when row order changes but account set doesn't.
  const purchaseAccountIds = useMemo(() => {
    if (!foldersReady) return [];
    const set = new Set<string>();
    for (const r of rows) if (r.__accountId) set.add(r.__accountId);
    return Array.from(set).sort();
  }, [rows, foldersReady]);
  const activity = useFanActivity(purchaseAccountIds);
  const activityLoaded = foldersReady && activity.loaded;
  const lastPurchaseMap = activity.lastPurchase;
  const recentSpendMap = activity.recentSpend;

  // Apply sort mode. "recent" returns the server order untouched. "spend"
  // and "hybrid" both rely on the deferred spendMap — until it lands the
  // sort no-ops, then re-orders in place once data arrives. We sort the
  // *display* set rather than the raw paginated `rows` so chip counts
  // and pagination math stay anchored to the canonical OF order; only
  // visual placement reflects the user's choice. Stable sort is required
  // because Array.prototype.sort is stable in all modern engines, so
  // ties (e.g. two $0 fans) preserve OF's lastActivity ordering.
  // A Fan with no spend-batch entry is unknown to the row, but the sort
  // still ranks them by their ledger sum, as it did before; otherwise an
  // unknown spend sorts with the zeros.
  const spendForRow = useCallback((c: OFChatItem) => {
    const key = `${c.__accountId ?? ""}:${c.withUser.id}`;
    return totalSpendOf(spendMap.get(key), recentSpendMap.get(key)) ?? recentSpendMap.get(key) ?? 0;
  }, [spendMap, recentSpendMap]);
  const sortKey = `${sortMode}|${spendMap.size}|${recentSpendMap.size}`;
  const sortedDisplayRows = useMemo<OFChatItem[]>(() => {
    if (sortMode === "recent") return displayRows;
    const arr = displayRows.slice();
    if (sortMode === "spend") {
      arr.sort((a, b) => spendForRow(b) - spendForRow(a));
      return arr;
    }
    if (sortMode === "spend-unread") {
      // Three-tier bucket, then spend desc within each:
      //   2 = unread (blue badge)
      //   1 = read but fan sent last (yellow dot — owe reply)
      //   0 = idle (we sent last, or no messages yet)
      const tierOf = (c: OFChatItem): number => {
        if (isUnreadChat(c)) return 2;
        if (isUnresponded(c)) return 1;
        return 0;
      };
      arr.sort((a, b) => {
        const ta = tierOf(a);
        const tb = tierOf(b);
        if (ta !== tb) return tb - ta;
        return spendForRow(b) - spendForRow(a);
      });
      return arr;
    }
    // hybrid — threshold applies to the DECAYED score, not raw spend.
    // So a $48 fan starts well above the $3 cutoff, but after ~5h of
    // silence their score halves down past it and unread rows start
    // winning. Tiered half-lives keep attention-needing chats up
    // longer: idle 1h, owe-reply 2h, unread 3h. Within the low-value
    // bucket, ties between unread rows fall through to raw spend.
    const LOW_SCORE_CENTS = 300;
    const halfLifeFor = (c: OFChatItem): number => {
      if (isUnreadChat(c)) return HALF_LIFE_UNREAD;
      if (isUnresponded(c)) return HALF_LIFE_UNRESPONDED;
      return HALF_LIFE_IDLE;
    };
    arr.sort((a, b) => {
      const aSpend = spendForRow(a);
      const bSpend = spendForRow(b);
      const aLast = a.lastMessage?.createdAt ?? null;
      const bLast = b.lastMessage?.createdAt ?? null;
      const aScore = hybridScore(aSpend, aLast, halfLifeFor(a));
      const bScore = hybridScore(bSpend, bLast, halfLifeFor(b));
      if (aScore < LOW_SCORE_CENTS && bScore < LOW_SCORE_CENTS) {
        const ua = isUnreadChat(a) ? 1 : 0;
        const ub = isUnreadChat(b) ? 1 : 0;
        if (ua !== ub) return ub - ua;
        // Both unread (or both read) at low value: raw spend desc.
        if (aSpend !== bSpend) return bSpend - aSpend;
      }
      return bScore - aScore;
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayRows, sortMode, sortKey, spendForRow, isUnresponded]);

  // Per-fan profile cache, keyed "<accountId>:<fanId>". `enrichWithUsers`
  // writes each fan's {name, username, avatar, customNickname} to
  // ["of-user", aid, fid]; one cache listener reads them all, without
  // triggering fetches. The chats cache only carries the slim ids/lastMessage
  // shape — names come from this side cache, so refetches / SSE patches on the
  // chats cache can't make the row revert to "fan {id}". It covers every Fan
  // (the Split Inbox dialog names Fans outside the chip's or group's rows).
  // The name key holds the presence a full read leaves there (`lastSeen`,
  // `useOFUser.ts` NAME_FIELDS) for the online rule. An unchanged Fan keeps
  // the same object, so only the rows whose name key changed re-render.
  const profileMap = useOFUserNameMap();
  // Every loaded Fan, for the Split Inbox dialog's reassign list, named as their rows are.
  const splitFans = useMemo(() => (q.data ?? []).map((c) => ({
    id: c.withUser.id, name: fanNameOf(c, profileMap.get(`${c.__accountId ?? ""}:${c.withUser.id}`)),
  })), [q.data, profileMap]);

  // The rows on screen: the sorted rows, narrowed to online Fans while
  // `onlineOnly` is on.
  const shownRows = useMemo(() => {
    if (!onlineOnly) return sortedDisplayRows;
    return sortedDisplayRows.filter((c) => isFanOnline(c, profileMap.get(`${c.__accountId ?? ""}:${c.withUser.id}`), onlineIds));
  }, [onlineOnly, sortedDisplayRows, profileMap, onlineIds]);
  // Warm the top unread threads in the order on screen (sort mode, Online
  // Fans). A spend sort re-orders as spend and activity land: warm the
  // order once both have landed, not each step on the way (a refetch does not
  // hold it again; new Fans' spend does). Online Fans may still re-cut the top
  // as `lastSeen` fills in, or as `onlineIds` (model scope) arrive after the
  // toggle; nothing says when either is done, so it is accepted.
  const sortLoaded = sortMode === "recent" || (spendLoaded && activityLoaded);
  useUnreadMessagesPrefetch(shownRows, q.fetchedLive && sortLoaded);
  // Online Fans has narrowed a loaded list to nothing: one line says so, in
  // place of the rows and of "End of inbox.".
  const noneOnline = onlineOnly && rows.length > 0 && shownRows.length === 0;
  // The rows drawn: the first `renderCap` (ROW_RENDER_STEP).
  const renderedRows = shownRows.length > paging.renderCap ? shownRows.slice(0, paging.renderCap) : shownRows;
  const hiddenRows = shownRows.length - renderedRows.length;
  const hiddenRowsRef = useRef(hiddenRows);
  hiddenRowsRef.current = hiddenRows;
  // The picks still on screen: a pick that left the list is not acted on.
  const pickedRows = useMemo(
    () => (picks ? shownRows.filter((c) => picks.has(chatRowKey(c))) : []),
    [picks, shownRows],
  );

  // Per-success optimistic patch: clear the unread badge on this fan's row
  // across every cached ["chats"] view so the UI only shows "read" for chats
  // that actually got marked. Mirrors useInboxRealtime's cache-shape walk
  // (InfiniteData { pages: [{ rows, hasMore }] }); skips caches that don't
  // hold the row. The trailing invalidate reconciles against OF either way.
  const markRowRead = useCallback((accountId: string, fanId: FanId) => {
    type Page = { rows: OFChatItem[]; hasMore: boolean };
    type Infinite = { pages: Page[]; pageParams: unknown[] };
    qc.getQueryCache().findAll({ queryKey: ["chats"] }).forEach((cq) => {
      const data = cq.state.data as Infinite | undefined;
      if (!data?.pages?.length) return;
      let touched = false;
      const newPages: Page[] = data.pages.map((p) => ({
        ...p,
        rows: p.rows.map((c) => {
          if ((c.__accountId ?? "") !== accountId || !sameUserId(c.withUser.id, fanId)) return c;
          if (!isUnreadChat(c)) return c;
          touched = true;
          return { ...c, hasUnread: false, unreadMessagesCount: 0 };
        }),
      }));
      if (touched) qc.setQueryData(cq.queryKey, { ...data, pages: newPages });
    });
  }, [qc]);

  // "Mark all as read" acts on the chosen group's loaded chats, or on every
  // loaded chat in "All inboxes" (rung 4; NEEDS HUMAN in ticket 103).
  const markable = inbox.inGroup ? allRows.filter(inbox.inGroup) : allRows;

  function refreshInbox() {
    const targets =
      scope.kind === "model" ? [scope.accountId] : accounts.map((a) => a.id);
    for (const aid of targets) {
      qc.removeQueries({ queryKey: ["vault-media", aid] });
      qc.removeQueries({ queryKey: ["vault-lists", aid] });
      qc.removeQueries({ queryKey: ["wall-media", aid] });
    }
    // Use `refresh()` (not `refetch()`) so the next /chats
    // call carries `?refresh=1` and bypasses the Stage C
    // backend `list_chats` cache. Without this, a recently-
    // cached inbox would survive the button press.
    q.refresh();
  }

  /** Mark `rows` read on OF, one at a time. Unpaced: a read flip reaches no
   *  fan, so it must not hold the account's write slot ahead of fan sends.
   *  Callers pass the unread rows (`isUnreadChat`). Each success clears that
   *  row's badge at once; the trailing refetch reconciles the rest. Returns
   *  the rows that failed, a row with no Creator among them. "Mark all as
   *  read" and the select bar both mark through here. */
  async function markChatsRead(rows: OFChatItem[]): Promise<OFChatItem[]> {
    const failed: OFChatItem[] = [];
    for (const c of rows) {
      try {
        if (!c.__accountId) throw new Error("row has no Creator");
        await relay.post(
          `/api/of/v2/chats/${c.withUser.id}/mark-as-read`,
          undefined,
          { accountId: c.__accountId },
        );
        markRowRead(c.__accountId, c.withUser.id);
      } catch (err) {
        failed.push(c);
        console.warn("[mark-read] failed for", c.withUser.id, err);
      }
    }
    invalidateReadState();
    return failed;
  }

  function invalidateReadState() {
    qc.invalidateQueries({ queryKey: ["chats"] });
    qc.invalidateQueries({ queryKey: ["roster-counts"] });
  }

  // The Creator whose every unread chat is loaded: one Creator in scope, no
  // group, search or list narrowing the rows, the All or Unread filter, and
  // no page left. Marking all of them is then OF's one "mark every chat
  // read" write instead of one write per chat.
  const wholeCreator =
    scope.kind === "model" && !inbox.inGroup && !query && !serverListId &&
    (serverFilter === null || serverFilter === "unread") && !q.hasMore
      ? scope.accountId
      : null;

  /** POST /chats/mark-as-read for `accountId`; `rows` are its unread chats.
   *  Returns how many failed (all or none). */
  async function markCreatorRead(accountId: string, rows: OFChatItem[]): Promise<number> {
    try {
      await relay.post("/api/of/v2/chats/mark-as-read", undefined, { accountId });
      for (const c of rows) markRowRead(accountId, c.withUser.id);
      return 0;
    } catch (err) {
      console.warn("[mark-read] mark all failed for", accountId, err);
      return rows.length;
    } finally {
      invalidateReadState();
    }
  }

  async function markAllRead() {
    if (markingAll) return;
    const targets = markable.filter(isUnreadChat);
    if (targets.length === 0) return;
    if (!confirm(`Mark ${targets.length} chat${targets.length === 1 ? "" : "s"} as read?`)) return;
    setMarkingAll(true);
    let failed = 0;
    try {
      failed = wholeCreator
        ? await markCreatorRead(wholeCreator, targets)
        : (await markChatsRead(targets)).length;
    } finally {
      setMarkingAll(false);
    }
    if (failed > 0) {
      alert(`Marked ${targets.length - failed} of ${targets.length}; ${failed} failed.`);
    }
  }

  // Pre-warm the SW image cache for the top rows so the OF signed-URL
  // refresh round-trip happens once per fan-session rather than each time
  // a row's <img> mounts. `Image()` rides the browser's image pipeline,
  // which the same-origin SW intercepts → cached for later mounts/popouts.
  // Ref-deduped so a re-sort never re-fires the same URL.
  const preWarmedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (typeof window === "undefined") return;
    for (const c of sortedDisplayRows.slice(0, 30)) {
      const aid = c.__accountId ?? null;
      if (!aid) continue;
      const cached = qc.getQueryData<OFUserName | null>(ofUserNameKey(aid, c.withUser.id));
      const raw = c.withUser.avatar || cached?.avatar || null;
      if (!raw) continue;
      const url = proxyImage(raw, aid);
      if (!url || preWarmedRef.current.has(url)) continue;
      preWarmedRef.current.add(url);
      const img = new Image();
      img.src = url;
    }
  }, [sortedDisplayRows, qc]);

  // True when we've paginated up to the cap with no active search.
  const capped = isCapped(paging, allRows.length, query);

  // Owe-reply and a Split Inbox group: keep loading more pages until we
  // either fill the target (5–8 filtered rows on screen) or scan-cap hits
  // (100 raw rows). OF has no native "fan sent last" or group filter, so we
  // have to walk the chat list ourselves; the cap keeps that walk bounded.
  const oweReplyScanned = oweReplyActive ? allRows.length : 0;
  const oweReplyMatches = oweReplyActive ? rows.length : 0;
  useEffect(() => {
    if (fillDone) return;
    if (q.isFetchingMore) return;
    loadMore();
  }, [fillDone, rows.length, allRows.length, q.isFetchingMore, loadMore]);

  // Auto-load more pages only after the user has actually scrolled the
  // panel. Without this gate, an empty/short panel keeps the sentinel in
  // view from the start, so the IntersectionObserver chains loadMore()
  // calls before the user has done anything — burning quota and pulling
  // hundreds of /users/list batches for fans they may never see.
  // Page 1 (~25 rows) loads automatically via useInfiniteQuery; further
  // pages only auto-load once the user starts scrolling.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const { userScrolled } = paging;
  // Bounded auto-fill: if first paint doesn't overflow the scroller (small
  // inbox, or unified mode where one account returns few rows), the IO
  // sentinel sits inside the viewport forever but `userScrolled` never
  // flips, so load-more never fires. `canAutofill` caps the bursts per list
  // (reset with the rest of the paging budget).
  const autofillLeft = canAutofill(paging);
  useEffect(() => {
    const el = sentinelRef.current;
    const root = el?.parentElement;
    if (!root) return;
    const onScroll = () => {
      if (root.scrollTop > 0) dispatchPaging({ type: "scrolled" });
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        if (!qRef.current.hasMore || qRef.current.isFetchingMore) return;
        if (capped) return;
        // Loaded rows still wait behind "Show N more": no page past them.
        if (hiddenRowsRef.current > 0) return;
        // Owe-reply and a group have their own bounded walk and intentionally
        // pre-scan without waiting for user scroll. Search also bypasses the
        // gate — typing a name implies "keep scanning for matches." Default
        // mode requires an explicit scroll signal before chaining pages.
        if (fillExhausted) return;
        if (!fillActive && !query && !userScrolled) return;
        loadMore();
      },
      // rootMargin: 0 means "only fire when the sentinel is actually in
      // the viewport," not 200px before. Combined with the userScrolled
      // gate above, this confines auto-load to real bottom-touches.
      { root: el.parentElement, rootMargin: "0px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore, capped, fillExhausted, fillActive, userScrolled, query]);

  // Auto-fill until the panel overflows. Pairs with the userScrolled gate
  // on the IO observer: once content is taller than the viewport, scroll
  // takes over and this effect stops firing. Hard-capped at 10 bursts so
  // a truly small inbox or a stuck `hasMore` can't burn quota.
  // Gated on `q.isSuccess && !isFromSeed`: while the cold-start seed is
  // visible, the scroller may already overflow with placeholder rows
  // which would falsely terminate the autofill check, OR — worse — the
  // real query could land with hasMore=true and 0 real rows and we'd
  // loop loadMore against an empty result. Re-runs once seed dissolves.
  useEffect(() => {
    if (!q.isSuccess || isFromSeed) return;
    if (!q.hasMore || q.isFetchingMore) return;
    if (capped) return;
    if (fillExhausted) return;
    if (!autofillLeft) return;
    const scroller = sentinelRef.current?.parentElement;
    if (!scroller) return;
    // Tab not visible or panel not mounted yet — clientHeight will be 0
    // and we'd burst forever. Wait for it to actually layout.
    if (scroller.offsetParent === null || scroller.clientHeight === 0) return;
    const id = requestAnimationFrame(() => {
      if (scroller.scrollHeight > scroller.clientHeight + 80) return;
      dispatchPaging({ type: "autofilled" });
      loadMore();
    });
    return () => cancelAnimationFrame(id);
  }, [rows.length, q.hasMore, q.isFetchingMore, q.isSuccess, isFromSeed, capped, fillExhausted, autofillLeft, loadMore]);

  // The rows' time column is measured from this render, to the minute: the
  // column and the badges read no finer, and a clock that moved every render
  // would re-render every memoized row on every render.
  const now = Math.floor(Date.now() / 60_000) * 60_000;
  // All Models: one {color, name} per Creator, the same object every render.
  const accountChips = useMemo(() => {
    const m = new Map<string, { color: string; name: string }>();
    for (const [id, acc] of accountById) m.set(id, { color: acc.color || "#666", name: acc.nickname || id });
    return m;
  }, [accountById]);
  const togglePick = useCallback((c: OFChatItem) => setPicks((prev) => {
    const next = new Set(prev);
    if (!next.delete(chatRowKey(c))) next.add(chatRowKey(c));
    return next;
  }), []);

  // "Load more conversations" ends the list while more chats exist and
  // nothing is loading. At the cap a click extends the cap by a step;
  // below it, more chats exist but the panel isn't tall enough to scroll
  // (small/minimized window, few rows, or the autofill burst cap was hit),
  // so the IO sentinel never re-fires, and a click pulls the next page so
  // the tail is always reachable without a scrollbar. Owe reply keeps its
  // own scan line.
  const loadMoreClick =
    oweReplyActive || q.isFetchingMore || (q.isFetching && rows.length > 0) || !q.hasMore
      ? null
      : capped
        ? () => dispatchPaging({ type: "extendCap", loaded: allRows.length })
        : () => q.loadMore();

  return (
    <div className="flex flex-col h-full min-h-0 bg-[var(--inf-pane,var(--color-panel))]">
      <div>
        <FanListHeader
          title={scope.kind === "all" ? "All Models" : creatorName}
          creatorId={singleAcctId}
          query={typed}
          onQueryChange={setTyped}
          galleryFan={selected}
        />
        {actions}
        <FanListFilters
          showInboxSelector={scope.kind === "model"}
          groupCount={inbox.groupCount}
          group={inbox.group}
          onGroupChange={inbox.setGroup}
          onOpenSplitInbox={chatterOnly ? null : () => setSplitInboxOpen(true)}
          fetching={q.isFetching}
          onRefresh={refreshInbox}
          markingAll={markingAll}
          hasUnread={markable.some(isUnreadChat)}
          onMarkAllRead={markAllRead}
          keepDrawerOpen={keepDrawerOpen}
          onKeepDrawerOpenChange={setKeepDrawerOpen}
          blurMode={blurMode}
          onBlurModeChange={setBlurMode}
          compactMedia={compactMedia}
          onCompactMediaChange={setCompactMedia}
          onSelectChats={() => setPicks(new Set())}
          sortMode={sortMode}
          onSortModeChange={setSortMode}
          active={active}
          onActiveChange={setActive}
          unreadCount={unreadCount}
          activeCount={activeCount}
          oweReplyCount={oweReplyCount}
          pinnedFolders={pinnedFolders}
          hasLists={hasLists}
          tipsEnabled={tipsEnabled}
          onOpenFolderPicker={() => setPickerOpen(true)}
        />
        {picks && (
          <FanListBulkBar
            picked={pickedRows}
            shownCount={shownRows.length}
            listsAccountId={singleAcctId}
            onSelectAll={() => setPicks(new Set(shownRows.map(chatRowKey)))}
            onPickOnly={(rows) => setPicks(new Set(rows.map(chatRowKey)))}
            onDone={() => setPicks(null)}
            markChatsRead={markChatsRead}
          />
        )}
      </div>
      {singleAcctId && (
        <SplitInbox
          accountId={singleAcctId} open={splitInboxOpen} onClose={() => setSplitInboxOpen(false)} fans={splitFans}
        />
      )}
      {pickerOpen && singleAcctId && (
        <FolderPicker
          accountId={singleAcctId}
          onClose={() => setPickerOpen(false)}
        />
      )}

      <div
        className={cn(
          "flex-1 min-h-0 overflow-y-auto overscroll-y-contain transition-opacity",
          q.isFetching && q.isPlaceholderData && "opacity-60",
        )}
      >
        {q.isError && (
          <div className="p-4 text-xs text-err">
            {describeLoadError(q.error as Error)}
          </div>
        )}
        {!q.isError && rows.length === 0 && q.isFetched && !groupFilling && <FanListEmpty />}
        {!q.isError && noneOnline && <FanListEmpty text="No Fans online now" />}
        {/* Skeleton rows during the cold first fetch — only when we have
         *  NO seed rows to render in their place. With the local-DB seed
         *  populated, `displayRows` already paints clickable placeholders
         *  and skeletons would just flash in front of them. */}
        {!q.isError && rows.length === 0 && !q.isFetched && !isFromSeed && <FanListSkeleton />}
        {renderedRows.map((c) => {
          const accountId = c.__accountId ?? (scope.kind === "model" ? scope.accountId : "");
          const key = `${accountId}:${c.withUser.id}`;
          const spend = spendMap.get(key);
          return (
            <FanRow
              key={key}
              chat={c}
              accountId={accountId}
              profile={profileMap.get(key)}
              // The larger of the lifetime total and the ledger sum, so OF
              // cache lag on the lifetime figure shows no phantom $0 next to
              // a populated last-buy time; null while spend is unknown.
              totalSpendCents={totalSpendOf(spend, recentSpendMap.get(key))}
              subscriptionStatus={spend?.subscription_status ?? null}
              expiredAt={spend?.expired_at ?? null}
              lastPurchase={lastPurchaseMap.get(key) ?? null}
              lastPpvPurchase={activity.lastPpvPurchase.get(key) ?? null}
              selected={selected?.accountId === accountId && selected?.fanId === c.withUser.id}
              oweDot={showOweDots && lastMessageFromFan(c, accountId)}
              account={scope.kind === "all"
                ? accountChips.get(accountId) ?? { color: "#666", name: accountId }
                : null}
              now={now}
              onSelect={selectRow}
              schedulePrefetch={scheduleRowPrefetch}
              cancelPrefetch={cancelRowPrefetch}
              prefetchNow={prefetchRowNow}
              selectedRowRef={revealSelectedRow}
              picked={picks?.has(chatRowKey(c))}
              onTogglePick={picks ? togglePick : undefined}
            />
          );
        })}
        <div
          ref={sentinelRef}
          className={cn(!loadMoreClick && hiddenRows === 0 && cn(MP.ours.FanList.sentinel, "flex items-center justify-center text-fg-dim text-center"))}
        >
          {hiddenRows > 0
            ? <ShowMoreRows count={hiddenRows} onClick={() => dispatchPaging({ type: "showMore" })} />
            : loadMoreClick
            ? <LoadMoreConversations loaded={allRows.length} onClick={loadMoreClick} />
            : oweReplyActive
            ? (q.isFetchingMore
                ? `Scanning… ${oweReplyMatches} found in ${oweReplyScanned}`
                : oweReplyMatches === 0
                  ? `No replies needed in last ${oweReplyScanned} chats.`
                  : oweReplyScanned >= OWE_REPLY_SCAN_CAP && q.hasMore
                    ? (
                      <button
                        type="button"
                        onClick={() => q.loadMore()}
                        className={cn(MP.ours.FanList.keepScanning, "text-[var(--inf-accent-text,var(--color-accent))] underline underline-offset-2 md:no-underline md:underline-offset-auto md:hover:underline inline-flex items-center")}
                      >
                        scanned {oweReplyScanned} · {oweReplyMatches} owed · keep scanning
                      </button>
                    )
                    : !q.hasMore
                      ? `${oweReplyMatches} owed · scanned all ${oweReplyScanned}`
                      : "")
            : q.isFetchingMore
              ? "Loading more…"
              : q.isFetching && rows.length > 0
                ? "Refreshing…"
                : rows.length > 0 && !noneOnline
                  ? "End of inbox."
                  : ""}
        </div>
      </div>
    </div>
  );
}
