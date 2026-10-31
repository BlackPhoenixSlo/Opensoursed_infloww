"use client";

/**
 * ChatSurface — the right pane: ChatHeader + MessageList + Composer.
 *
 * Owns the per-chat hook (useChatMessages) and the send hook
 * (useSendMessage) — keeping them here means the ChatList re-rendering
 * doesn't unmount the active chat, and switching chats unmounts/remounts
 * this subtree cleanly (we pass a `key` from the parent).
 *
 * Click the header (avatar/name) to open the FanDrawer with the
 * editable profile overlay.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { decodeHtmlEntities } from "@/lib/utils";
import { proxyImage } from "@/lib/mediaUrl";

import { messagesPaintKey, useChatMessages } from "@/hooks/useChatMessages";
import { fetchOlderSeed, mergeSeedIntoMessages, useChatMessagesLocal } from "@/hooks/useChatMessagesLocal";
import { useChatAttribution } from "@/hooks/useChatAttribution";
import { OPEN_DIALOG, OS_EDGE_PX, useSwipe } from "@/hooks/useSwipe";
import { useSendMessage, type SendStatus } from "@/hooks/useSendMessage";
import { useLikeMessage } from "@/hooks/useLikeMessage";
import { useTogglePinMessage } from "@/hooks/useTogglePinMessage";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useUnsendMessage } from "@/hooks/useUnsendMessage";
import { useCreateSavedReply } from "@/hooks/useSavedReplies";
import { scriptDraftFromMessage } from "@/lib/messageScripts";
import { useFan } from "@/hooks/useFan";
import { ofUserNameKey, useCachedOFUser } from "@/hooks/useOFUser";
import { useRosterCountActions } from "@/hooks/useRosterCounts";
import {
  useServerScheduledSends,
  scheduledToPseudoMessage,
  useCancelServerScheduled,
} from "@/hooks/useServerScheduledSends";
import { useEmployee } from "@/contexts/EmployeeContext";
import { relay, type OFChatItem, type OFMessage } from "@/lib/relay";
import { sameUserId } from "@/lib/fanId";
import { perfPaintOnce } from "@/lib/perfLog";
import { patchQueryData } from "@/lib/cacheWrite";

import { MessageList, newestReadPointer } from "./MessageList";
import { Composer, type ComposerApi } from "./Composer";
import { FanDrawer } from "./FanDrawer";
import { ChatSearch } from "./ChatSearch";
import { ChatHeader } from "./ChatHeader";
import { PinnedBar, PinnedPopover } from "./PinnedPanel";
import { quoteFromMessage, type QuotedReply } from "./ReplyStrip";
import { useUnsendChoice } from "./UnsendChoice";
import { chatDrawerReducer, initialChatDrawer } from "./chatDrawer";
import { newBackfillIds } from "./jumpAnchor";
import { useJumpToMessage } from "./useJumpToMessage";
import { useMarkChatRead } from "./useMarkChatRead";

export type { QuotedReply };

interface MeResp {
  id: number;
  name?: string;
  username?: string;
  avatar?: string | null;
}

/** Per-account localStorage key holding the model's OF user id. There is
 *  NO synchronous OF user-id source today — the Account model has no
 *  of_user_id column and `meQ` (/users/me) is async, null on first paint.
 *  Caching the resolved id under this key lets the NEXT chat-open hydrate
 *  it synchronously on mount, so bubbles start on the correct side instead
 *  of all-left-then-spread once meQ lands. */
const ownerIdCacheKey = (accountId: string) => `of-owner:${accountId}`;

/** Read the cached owner id synchronously (SSR-safe). Returns null when
 *  absent / unparseable so the caller falls back to the async meQ. */
export function readCachedOwnerId(accountId: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ownerIdCacheKey(accountId));
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

export function ChatSurface({
  accountId, fanId, chat, insightsOpenAtStart, onBack,
  markRead = "onOpen", prefetchWindowMs, onSendStart, onSendSettled, onAdvance, onHoldChange,
}: {
  accountId: string;
  /** Number on OnlyFans, a string snowflake on Fansly — the id is passed
   *  through as the wire sent it, never re-parsed (see `fanIdFromParam`). */
  fanId: number | string;
  chat: OFChatItem;
  /** Whether Fan insights start open at lg+. Below lg they always start
   *  closed (one pane at a time). Either way the "Fan insights" toggle
   *  closes and reopens them; nothing keeps them open. */
  insightsOpenAtStart: boolean;
  /** Optional mobile-only back arrow. When provided, the header gets a
   *  `<` button on the left (visible below lg) that runs this callback, and
   *  so does a swipe right on the Thread below lg (not from the OS's edge
   *  zones, the Composer, or while Fan insights or a dialog is open).
   *  /inbox uses it to clear the selected chat and reveal the ChatList
   *  again on small screens; popout / group don't pass it. */
  onBack?: () => void;
  /** When the chat is marked read (our marker, and OF's "seen"). A queue
   *  passes "afterFirstSend": opening (or skipping) a chat marks nothing; the
   *  first send that reaches OF (not a scheduled one, nor a failed one) does. */
  markRead?: "onOpen" | "afterFirstSend";
  /** A caller that prefetches threads: their fresh window (see useChatMessages). */
  prefetchWindowMs?: number;
  /** A send (or a Retry) began — before any await. */
  onSendStart?: () => void;
  /** How that send ended. */
  onSendSettled?: (status: SendStatus) => void;
  /** Move to the next/previous chat (Composer keys). */
  onAdvance?: (dir: 1 | -1) => void;
  /** The draft holds media, GIFs or a price (see Composer). */
  onHoldChange?: (held: boolean) => void;
}) {
  const { current: currentEmployee } = useEmployee();
  const qc = useQueryClient();
  const { refreshOne: refreshRosterOne } = useRosterCountActions();

  // Fan insights, and the header's Notes / Edit name focus requests (chatDrawer).
  const [drawer, dispatchDrawer] = useReducer(
    chatDrawerReducer,
    insightsOpenAtStart,
    // Below lg Fan insights start closed: Messages Pro is one pane at a
    // time there (list → thread → insights slide-over), and a deep-link
    // would bury the thread under the drawer. The user opens the overlay
    // from the header ("Fan insights").
    (atStart) => initialChatDrawer(atStart && !(typeof window !== "undefined"
      && window.matchMedia("(max-width: 1023px)").matches)),
  );
  const drawerOpen = drawer.open;
  const [quoted, setQuoted] = useState<QuotedReply | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [pinnedOpen, setPinnedOpen] = useState(false);
  // Imperative handle on Composer — lets FanDrawer's "Send to chat"
  // buttons (on unsold PPVs) preload the composer with that PPV's
  // text + media + price, identical to picking a saved template.
  const composerApiRef = useRef<ComposerApi | null>(null);
  // Below lg a swipe right on the Thread is its Back (`onBack`), as the header's
  // `<` is; never while Fan insights or a dialog is over it.
  const threadRef = useRef<HTMLDivElement>(null);
  useSwipe(threadRef, {
    enabled: !!onBack && !drawerOpen, dir: "right", onSwipe: () => onBack?.(), sheet: { panel: threadRef },
    edgeGuard: OS_EDGE_PX, ignoreWhile: OPEN_DIALOG,
  });

  // Resolve the model account's OF user id — needed to decide direction
  // (outgoing if message.fromUser.id === ownerUserId).
  const meQ = useQuery<MeResp>({
    queryKey: ["of-me", accountId],
    queryFn: () => relay.get<MeResp>("/api/of/v2/users/me", { accountId }),
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // Owner id, hydrated SYNCHRONOUSLY from localStorage on mount so the very
  // first paint already has it (no all-left-then-spread flash while meQ is
  // in flight). meQ is the source of truth once it lands; until then the
  // cached value from the previous visit stands in. The component is keyed
  // per-account by the parent, so this initializer re-reads when the
  // account changes. ownerUserId below prefers the fresh meQ id.
  const [cachedOwnerId, setCachedOwnerId] = useState<number | null>(
    () => readCachedOwnerId(accountId),
  );
  useEffect(() => {
    const id = meQ.data?.id;
    if (id == null) return;
    setCachedOwnerId(id);
    try {
      window.localStorage.setItem(ownerIdCacheKey(accountId), String(id));
    } catch { /* quota / privacy mode — the async meQ still drives this session */ }
  }, [accountId, meQ.data?.id]);
  const ownerUserId = meQ.data?.id ?? cachedOwnerId;

  const handle = useChatMessages({ accountId, fanId, enabled: true, prefetchWindowMs });

  // Cold-start seed: local SQLite via /admin/messages/{aid}/{fid}, mapped
  // to OFMessage shape. Lives in a SEPARATE cache key
  // (["messages-local-seed", ...]) so it never registers a competing
  // queryFn on ["messages", aid, fid] (two useQuery on one key would race
  // their fetches and the real OF call could be skipped). Fetches only
  // while `handle` has no data; once OF (or the patcher) populates the
  // real cache it's disabled and never read for rendering again — the
  // hydration effect below copies it across instead.
  // Always enabled — NOT gated on `handle.isPending`. The `"messages"` cache is
  // persisted to localStorage (see providers.tsx), so on a popout / repeat-open
  // isPending is already false and a pending-gated seed would never run — which
  // is exactly how ledger-synthesized TIP rows (their ONLY render path is this
  // seed) went missing from the thread. It's one cheap indexed sqlite query
  // (5-min staleTime, no refetch-on-mount/focus), and the one-time hydration
  // below only ADDS rows the cache is missing, so the OF fetch / SSE patcher
  // stay authoritative.
  const seedQ = useChatMessagesLocal({
    enabled: true,
    accountId,
    fanId,
  });

  // DB-as-render-source: copy the seed ONE-TIME into the real
  // ["messages", accountId, fanId] cache so DB history renders instantly
  // through the SAME query the realtime patcher (useInboxRealtime) and the
  // send-flow (appendLocal/reconcileLocal) write to. The OF fetch then
  // reconciles into that key in place — seed rows and OF rows share the
  // real `message_id`, so the MessageList keys (key={String(m.id)}) match
  // and the swap is a prop update, not a remount: no mid-session flash.
  //
  // Guards that keep the patcher the SOLE ongoing writer:
  //   • a ref so this fires at most once per chat-open (ChatSurface is
  //     keyed per accountId:fanId, so the ref resets on every switch);
  //   • a functional updater that NEVER clobbers an already-populated
  //     cache — if OF resolved first, or the patcher landed a live message
  //     in the cold-open window, we only fold in seed rows the cache is
  //     missing, leaving the richer existing rows authoritative.
  // Deliberately NOT `initialData` on useChatMessages: that re-applies on
  // every render and fights the patcher.
  const seedHydratedRef = useRef(false);
  useEffect(() => {
    if (seedHydratedRef.current) return;
    if (!accountId || fanId == null) return;
    if (seedQ.rows.length === 0) return;
    seedHydratedRef.current = true;
    patchQueryData<OFMessage[]>(
      qc, ["messages", accountId, fanId],
      (prev) => mergeSeedIntoMessages(prev, seedQ.rows),
    );
  }, [seedQ.rows, accountId, fanId, qc]);

  // Older pages get the head page's treatment: scrolling up used to sit on
  // a live OF round-trip (p50 ~1.5s) with nothing on screen, even though the
  // same history is already in the local mirror and answers in ~1ms. Fire
  // both, paint whichever lands first, let OF reconcile.
  //
  // The seed writes through mergeSeedIntoMessages — the SAME merge the head
  // seed uses — so it can only ADD rows the cache is missing and orders them
  // by created_at. What it deliberately does NOT touch is `oldestCursorRef`
  // or `hasOlder`: both stay owned by loadOlder's OF response, so a mirror
  // that runs deeper than OF's window can never move the cursor into a gap
  // or claim there is more history than OF will actually serve. A mirror
  // miss (or error) returns [] and the user simply waits on OF, as before.
  const loadOlderSeeded = useCallback(async () => {
    // The hook drops re-entrant calls; don't pay for a second seed fetch
    // that the merge would only dedupe away.
    if (handle.isLoadingOlder) return handle.loadOlder();
    // Read the cursor BEFORE loadOlder runs — it lowers the cursor when OF
    // answers, and the seed must page from the same boundary OF does.
    const cursor = handle.olderCursor();
    if (cursor != null && accountId && fanId != null) {
      void fetchOlderSeed(accountId, fanId, cursor).then((rows) => {
        if (rows.length === 0) return;
        patchQueryData<OFMessage[]>(
          qc, ["messages", accountId, fanId],
          (prev) => mergeSeedIntoMessages(prev, rows),
        );
      });
    }
    return handle.loadOlder();
  }, [handle, accountId, fanId, qc]);

  // Search / pinned / ?msg= jumps put a highlight ring on a rendered bubble.
  const { highlightId, jumpToMessage } = useJumpToMessage({
    accountId, fanId, handle, loadOlder: loadOlderSeeded, onJump: () => setSearchOpen(false),
  });

  // `painted` — the first commit that puts real bubbles on screen. This is
  // the number the thread should be judged on: `delivered` measures OF's
  // round-trip, but the seed above means the user is usually reading history
  // long before it lands. `ofSettled` separates the two populations in the
  // log (false = the seed carried this paint).
  //
  // Fires from an effect rather than a ref callback on the first bubble
  // because MessageList commits in the same pass as this component; the
  // extra prop would buy nothing but coupling.
  useEffect(() => {
    if (!accountId || fanId == null) return;
    if ((handle.data?.length ?? 0) === 0) return;
    perfPaintOnce(messagesPaintKey(accountId, fanId), "chat.messages", {
      count: handle.data?.length ?? 0,
      ofSettled: handle.isSuccess,
      phase: "initial",
    });
  }, [accountId, fanId, handle.data, handle.isSuccess]);

  // Prefetch the fan row so opening the drawer is instant. The hook
  // is cheap (one indexed sqlite lookup) and the data drives the
  // custom_nickname we want to show in the header.
  const fanQ = useFan(accountId, fanId);

  // Observe the per-fan profile cache that enrichWithUsers populates from
  // /users/list. ChatList already reads from this side channel so its rows
  // pick up nickname/name/avatar; the surface header needs the same path
  // because the `chat` prop is the slim row (enrichment writes to this
  // cache, not back into the chats list cache). Observe-only: see
  // useCachedOFUser.
  const profile = useCachedOFUser(accountId, fanId);

  // Header ↻ refresh: a full re-pull of this chat AND the fan, plus a
  // re-cache into the local SQLite mirror. The plain `handle.refresh()`
  // only re-fetched the message page, so a fan who just paid a tip / a PPV
  // could keep showing the stale "unseen"/locked state and the drawer's
  // sales/revenue lagged. This invalidates every cache the chat + fan panel
  // render from, then asks the server to re-scrape this fan's chat from OF
  // so anything the live pull alone misses lands in the persisted history.
  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    if (!accountId || fanId == null) return;
    setIsRefreshing(true);
    try {
      await Promise.all([
        // Live OF re-pull — messages, fan profile (nickname/notice/spend),
        // local fan row, the PPV gallery + ledger spine behind the drawer's
        // chart/Sales, and the roster unread badges.
        qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] }),
        qc.invalidateQueries({ queryKey: ofUserNameKey(accountId, fanId) }), // name + full
        qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] }),
        qc.invalidateQueries({
          queryKey: ["fan-chat-media", accountId, fanId],
          exact: false,
        }),
        qc.invalidateQueries({
          queryKey: ["fan-ppv-history", accountId, fanId],
          exact: false,
        }),
        qc.invalidateQueries({ queryKey: ["last-purchases", accountId] }),
        // Force this model's badge authoritative (busts its server cache + re-reads
        // only it); a plain invalidate would just refetch the stale cached count.
        refreshRosterOne(accountId, { force: true }),
        // #11: also refresh the account's list/folder membership view so Refresh
        // updates which lists the fan is in / can be added to — the folder chips
        // and counts — not just this fan's messages/profile. (of-user above
        // already refreshes the per-fan listsStates.)
        qc.invalidateQueries({ queryKey: ["chat-folders", accountId] }),
        // Re-cache into the local mirror: re-scrape this fan's chat from OF so
        // the persisted history catches a just-paid PPV/tip that the live UI
        // pull alone wouldn't reconcile. Runs INLINE (not the automation queue)
        // so it lands in ~1-2s even while a big background scrape sweep is
        // hogging the bulk lane — the queued path would wait behind it.
        // Best-effort — the UI already refreshed from OF above regardless.
        relay
          .post(
            `/admin/messages/${accountId}/${fanId}/rescrape-now`,
            undefined,
            { accountId },
          )
          .catch(() => { /* re-cache is best-effort; UI is already fresh */ }),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  }, [qc, accountId, fanId, refreshRosterOne]);

  const noteSettled = useMarkChatRead({ accountId, fanId, hasUnread: !!chat.hasUnread, markRead });
  const settleSend = useCallback((status: SendStatus) => {
    onSendSettled?.(status);
    noteSettled(status);
  }, [onSendSettled, noteSettled]);
  const sender = useSendMessage({
    accountId,
    fanId,
    fromUserId: meQ.data?.id,
    fromUserName: meQ.data?.name ?? meQ.data?.username ?? "you",
    hookHandle: handle,
    onStart: onSendStart,
    onSettled: settleSend,
  });
  const liker = useLikeMessage(accountId, fanId);
  const pinner = useTogglePinMessage(accountId, fanId);
  const unsender = useUnsendMessage(accountId, fanId);

  // A mass-sent bubble asks "this conversation" or "all recipients" first
  // (04-messages-pro.md P3); the calls are unchanged.
  const unsend = useUnsendChoice(unsender);

  // "Save as script" from our bubble's menu (roadmap W4 4.2): the message's
  // text, media and price become a saved reply, under a title the chatter
  // confirms. Cancel saves nothing. The menu hides it for a message that
  // would save empty (scriptDraftHasContent).
  const { mutateAsync: createScript } = useCreateSavedReply(accountId);
  const handleSaveAsScript = useCallback(async (msg: OFMessage) => {
    const draft = scriptDraftFromMessage(msg);
    const title = window.prompt("Save as script. Title:", draft.title ?? "");
    if (title === null) return;
    try {
      await createScript({ ...draft, title: title.trim() || null });
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      window.alert(`Couldn't save the script: ${reason}`);
    }
  }, [createScript]);

  // Pre-warm only the fan-specific cache here — the account-wide ones
  // (vault-lists, wall-media) are kicked off from the inbox page at app
  // start so they don't compete with the message fetch on chat-open.
  // Delay even this small query so the visible message list gets first
  // crack at the relay's request budget.
  useEffect(() => {
    if (!accountId || fanId == null) return;
    const t = setTimeout(() => {
      qc.prefetchQuery({
        queryKey: ["vault-history", accountId, fanId],
        queryFn: () =>
          relay.get(`/admin/vault/fan-history?account_id=${encodeURIComponent(accountId)}&fan_id=${fanId}`),
        staleTime: 60_000,
      }).catch(() => {});
    }, 500);
    return () => clearTimeout(t);
  }, [accountId, fanId, qc]);

  // Backfill historical vault-sends from chat messages already loaded.
  // We hooked the auto-record at send-time AFTER feature-ship, so any
  // chat that existed before that has no rows — meaning the picker's
  // sent/purchased rings stay empty. Walking the message stream and
  // batch-POSTing missing rows fills that gap lazily, scoped to the
  // chat the user is actually looking at.
  //
  // Idempotent on the backend (dupe-checks by message_id) so it's safe
  // to fire on every load — older pages picked up via loadOlder also
  // trigger this when handle.data changes.
  const backfilledMsgIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!accountId || fanId == null) return;
    const messages = handle.data ?? [];
    const myId = meQ.data?.id;
    if (!myId || messages.length === 0) return;

    const candidates: Array<{
      message_id: string;
      media_ids: number[];
      price_cents: number;
      was_purchased: boolean | null;
    }> = [];
    for (const m of messages) {
      // Keyed as TEXT: a Fansly message id is a snowflake past 2^53, so
      // Number() collapsed distinct messages onto one key and the dedupe set
      // below then skipped real sends as "already backfilled".
      const mid = String(m.id ?? "");
      if (!/^\d+$/.test(mid) || /^0+$/.test(mid)) continue;
      // Only outgoing messages count — incoming ones come from the fan,
      // not from us, so they have no business in vault_sends.
      if (!sameUserId(m.fromUser?.id, myId)) continue;
      const mediaIds = (m.media ?? [])
        .map((x) => (typeof x.id === "number" ? x.id : Number(x.id)))
        .filter((n) => Number.isFinite(n) && n > 0);
      if (mediaIds.length === 0) continue;
      candidates.push({
        message_id: mid,
        media_ids: mediaIds,
        price_cents: Math.max(0, Math.round((m.price || 0) * 100)),
        // PPV: isOpened flips true once the fan paid. For free sends OF
        // also reports isOpened=true when the fan opens the chat, which
        // is meaningless — leave was_purchased null in that case.
        was_purchased: (m.price ?? 0) > 0 ? !!m.isOpened : null,
      });
    }
    // Each id once (its first message), and never one already backfilled.
    const firstById = new Map<string, (typeof candidates)[number]>();
    for (const c of candidates) if (!firstById.has(c.message_id)) firstById.set(c.message_id, c);
    const ids = newBackfillIds(backfilledMsgIdsRef.current, candidates.map((c) => c.message_id));
    const items = ids.map((id) => firstById.get(id)!);
    for (const id of ids) backfilledMsgIdsRef.current.add(id);
    if (items.length === 0) return;

    relay
      .post("/admin/vault/sends/backfill", {
        account_id: accountId,
        fan_id: fanId,
        items,
      })
      .then((r) => {
        const resp = r as { inserted?: number } | undefined;
        if ((resp?.inserted ?? 0) > 0) {
          qc.invalidateQueries({ queryKey: ["vault-history", accountId, fanId] });
        }
      })
      .catch((err) => console.warn("[vault backfill] failed", err));
  }, [accountId, fanId, handle.data, meQ.data?.id, qc]);

  // #19: the vault "restock" — the SENT / PURCHASED / UNSEEN badges the picker
  // reads from ["vault-history"] — must refresh every time a chat is opened,
  // from ANY entry point (a Tips-tab row, a PPV-message row, a deep link). The
  // backfill effect above only invalidates when it *inserts* new rows, so a chat
  // whose sends were already backfilled on an earlier open (e.g. first reached
  // from Chat messages) never re-fetched its history when later opened from a
  // tip — the reported "restock doesn't trigger from a tip" bug. A plain
  // invalidate on open makes the restock entry-point-agnostic; it's a cheap,
  // idempotent read (a no-op while the picker isn't mounted).
  useEffect(() => {
    if (!accountId || fanId == null) return;
    qc.invalidateQueries({ queryKey: ["vault-history", accountId, fanId] });
  }, [accountId, fanId, qc]);

  // The `chat` prop is a snapshot captured at click time and never refreshed.
  // After a scope switch the ChatList serves placeholderData while the new
  // scope's /chats call is in flight, so the row the user clicks can carry
  // a stale `canSendMessage: false` from the previous scope. That stale
  // false latches the Composer's "Sending disabled" banner + disables Send
  // until the user re-mounts via a sibling chat click. Resolve gating
  // fields from the live chats cache instead, with a subscription that
  // re-renders when any ["chats", ...] entry updates so polling/SSE feeds
  // through here too.
  const [chatsCacheTick, setChatsCacheTick] = useState(0);
  useEffect(() => {
    const unsubscribe = qc.getQueryCache().subscribe((event) => {
      // Only react to the events that change a cached chat row's fields.
      // `observerResultsUpdated` fires on every dependent component render
      // and would loop us into useless re-renders.
      if (event.type !== "added" && event.type !== "updated") return;
      const key = event.query.queryKey;
      if (Array.isArray(key) && key[0] === "chats") {
        // Defer the setState past the current commit. React Query fires
        // `observerAdded` synchronously while a consumer component (e.g.
        // ChatList) is rendering — calling setState on ChatSurface from
        // inside that callback trips React's "setState while rendering
        // another component" warning. queueMicrotask lands the update
        // after the in-flight render finishes.
        queueMicrotask(() => setChatsCacheTick((t) => t + 1));
      }
    });
    return unsubscribe;
  }, [qc]);
  const liveChat = useMemo<OFChatItem | null>(() => {
    type Page = { rows: OFChatItem[]; hasMore: boolean };
    type Infinite = { pages: Page[]; pageParams: unknown[] };
    for (const q of qc.getQueryCache().findAll({ queryKey: ["chats"] })) {
      const data = q.state.data as Infinite | undefined;
      if (!data?.pages) continue;
      for (const p of data.pages) {
        for (const c of p.rows) {
          if ((c.__accountId ?? "") === accountId && sameUserId(c.withUser.id, fanId)) {
            return c;
          }
        }
      }
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, fanId, qc, chatsCacheTick]);

  // The chat-list row holds OF's `lastReadMessageId` — the highest msg id
  // the fan has marked read. The `chat` prop is the click-time snapshot, so
  // the newer of it and the live chat cache wins (spec F28): ✓ turns ✓✓
  // while the Thread is open, and the popout page shows ✓✓ too.
  const lastReadByPeerId = useMemo<number | null>(
    () => newestReadPointer(chat.lastReadMessageId, liveChat?.lastReadMessageId),
    [chat.lastReadMessageId, liveChat],
  );

  function onQuoteReply(msg: OFMessage) {
    setQuoted(quoteFromMessage(msg));
  }

  // Server-scheduled sends live in a separate query; merge them into
  // the message stream as pseudo-bubbles so the operator sees what's
  // about to go out (and can cancel) without leaving the chat. Memoize
  // so the MessageList's "did the array change" effect doesn't fire
  // every render — the auto-scroll-to-bottom depends on a stable ref.
  const scheduledQ = useServerScheduledSends(accountId, fanId);
  const cancelScheduled = useCancelServerScheduled();
  // The message stream always reads the real ["messages", ...] cache: DB
  // history is hydrated into it on open (seed-hydration effect above), the
  // OF fetch reconciles into it, and the realtime patcher + send-flow keep
  // it live. The seed is never read directly here — reading a different
  // array reference is what made the old seed-then-discard swap flash
  // mid-session. Server-scheduled sends (future-dated) are appended as
  // pseudo-rows so they sort to the bottom as "about to go out" ghosts.
  const mergedMessages: OFMessage[] = useMemo(() => {
    const real = handle.data ?? [];
    const scheduled = scheduledQ.data ?? [];
    if (scheduled.length === 0) return real;
    return [...real, ...scheduled.map((s) => scheduledToPseudoMessage(s, ownerUserId))];
  }, [handle.data, scheduledQ.data, ownerUserId]);

  // Pinned slice asked of OF directly (one call, cached a minute), because
  // filtering the loaded backlog UNDERCOUNTS: a pin older than the first page
  // is invisible, so a thread holding two rendered "Pinned · 1" — verified live
  // on a thread whose only pin sat outside the head page and showed as none.
  // The backlog filter stays as the fallback for the moment before the fetch
  // resolves, and for any account where the call fails.
  const pinnedQ = useChatPinned(accountId, fanId);
  const pinnedMessages = useMemo(
    () => (pinnedQ.data?.length ? pinnedQ.data
                                : (handle.data ?? []).filter((m) => m.isPinned)),
    [pinnedQ.data, handle.data],
  );

  // Outbound-bubble "Sent by {employee}" label data. Anchored at the
  // oldest visible message so loading older pages widens the window
  // without thrashing every render — react-query treats the new
  // oldestId as a separate key and serves the previous data while the
  // wider fetch resolves.
  const oldestVisibleId = useMemo(() => {
    const first = mergedMessages[0]?.id;
    if (first == null) return null;
    const n = typeof first === "number" ? first : Number(first);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [mergedMessages]);
  const attributionQ = useChatAttribution(accountId, fanId, oldestVisibleId);
  const attributionMap = attributionQ.data?.by_msg_id ?? null;

  // Cross-chatter freshness: when a teammate (Slovenia/Kenya/Nigeria/…)
  // sends from another machine, the WS pump lands the outbound row in
  // useChatMessages but our attribution map is still cached. Rather than
  // shortening staleTime (which would re-fetch even on idle chats), we
  // piggyback on the chat-message arrival itself — invalidate ONLY when
  // a new outbound id appears that isn't in the map. Idle chats pay
  // nothing; active chats pay one fetch per teammate-send observed.
  // (ownerUserId is hydrated synchronously above.)
  useEffect(() => {
    if (!accountId || fanId == null || ownerUserId == null) return;
    if (!attributionMap) return;
    let needsRefresh = false;
    for (const m of mergedMessages) {
      if (m.fromUser?.id !== ownerUserId) continue;
      if ((m._tempId ?? 0) < 0) continue;
      const idNum = typeof m.id === "number" ? m.id : Number(m.id);
      if (!Number.isFinite(idNum) || idNum <= 0) continue;
      if (!(String(idNum) in attributionMap)) { needsRefresh = true; break; }
    }
    if (needsRefresh) {
      qc.invalidateQueries({ queryKey: ["msg-attribution", accountId, fanId] });
    }
  }, [accountId, fanId, ownerUserId, mergedMessages, attributionMap, qc]);

  const fanUsername = chat.withUser.username || profile?.username || fanQ.data?.of_username;
  const headerName = decodeHtmlEntities(
    profile?.displayName ||
    chat.withUser.displayName ||
    fanQ.data?.custom_nickname ||
    profile?.customNickname ||
    chat.withUser.customNickname ||
    profile?.name ||
    chat.withUser.name ||
    profile?.username ||
    chat.withUser.username ||
    `fan ${chat.withUser.id}`,
  );

  return (
    <div className="relative flex flex-1 h-full min-h-0 min-w-0 bg-bg overflow-hidden">
      <div ref={threadRef} data-mp-pane="thread" className="@container relative flex flex-col flex-1 min-w-0 min-h-0">
      <ChatHeader
        accountId={accountId} fanId={fanId} chat={chat} onBack={onBack}
        name={headerName} username={fanUsername}
        findOpen={searchOpen} onToggleFind={() => setSearchOpen((v) => !v)}
        refreshing={isRefreshing || handle.isFetching} onRefresh={handleRefresh}
        onOpenNotes={() => dispatchDrawer({ type: "openNotes" })}
        onEditName={() => dispatchDrawer({ type: "editName" })}
        insightsOpen={drawerOpen} onToggleInsights={() => dispatchDrawer({ type: "toggle" })}
      />

      {searchOpen && (
        <ChatSearch
          accountId={accountId}
          fanId={fanId}
          messages={mergedMessages}
          ownerUserId={ownerUserId}
          hasOlder={handle.hasOlder}
          loadingOlder={handle.isLoadingOlder}
          onLoadOlder={() => loadOlderSeeded()}
          onPick={jumpToMessage}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {/* PinnedBar is hidden below md — it eats a row of vertical space
       *  and the popover overlays don't fit comfortably on a 360px screen.
       *  Pinned messages are still visible inline (📌 badges on bubbles)
       *  and the desktop bar is unchanged. */}
      <div className="hidden md:block">
        <PinnedBar
          pinned={pinnedMessages}
          open={pinnedOpen}
          onToggle={() => setPinnedOpen((v) => !v)}
        />
      </div>

      <MessageList
        messages={mergedMessages}
        ownerUserId={ownerUserId}
        accountId={accountId}
        fanId={fanId}
        isLoading={handle.isLoading}
        isError={handle.isError}
        error={handle.error as Error | null}
        hasOlder={handle.hasOlder}
        loadingOlder={handle.isLoadingOlder}
        onLoadOlder={() => loadOlderSeeded()}
        onRetry={sender.retry}
        onDiscard={sender.cancelOptimistic}
        onCancelScheduled={(jobId) => {
          if (accountId && fanId != null) {
            cancelScheduled.mutate({ jobId, accountId, fanId });
          }
        }}
        onToggleLike={(msg) => liker.toggle(msg)}
        onQuoteReply={onQuoteReply}
        onTogglePin={(msg) => pinner.toggle(msg)}
        onUnsend={unsend.onUnsend}
        onSaveAsScript={handleSaveAsScript}
        highlightId={highlightId}
        lastReadByPeerId={lastReadByPeerId}
        attribution={attributionMap}
        currentEmployeeName={currentEmployee?.display_name ?? null}
        // The run avatars (Phase 4 spec Contracts): the Fan's from the row and
        // profile cache the Fan List reads, ours from the `/me` query above,
        // so neither costs a relay call.
        fanAvatar={proxyImage(chat.withUser.avatar || profile?.avatar || null, accountId) || null}
        creatorAvatar={proxyImage(meQ.data?.avatar ?? null, accountId) || null}
      />

      {unsend.dialog}

      <PinnedPopover
        pinned={pinnedMessages}
        ownerUserId={ownerUserId}
        open={pinnedOpen}
        onClose={() => setPinnedOpen(false)}
        onJumpTo={jumpToMessage}
      />

      <Composer
        accountId={accountId}
        fanId={fanId}
        fanName={headerName}
        composerApiRef={composerApiRef}
        quoted={quoted}
        onClearQuoted={() => setQuoted(null)}
        onAdvance={onAdvance}
        onHoldChange={onHoldChange}
        onSend={async (args) => {
          // Closing the pinned popover on send is the second half of the
          // hide rule (the first half is click-out, owned by the popover
          // itself). Keep this before the OF call so the panel disappears
          // even if send returns an error.
          setPinnedOpen(false);
          // OF supports native quote-reply via `replyToMessageId`. Threading
          // it through the send body makes the fan's OF client render the
          // quoted message as a card above the reply — same UX as OF web.
          const replyMsgId = quoted?.messageId;
          // Capture the original message body for the optimistic bubble so
          // we render the quote card immediately, without waiting for OF
          // to echo `replyToMessage` back on the next refetch.
          const replySnapshot = quoted
            ? (() => {
                const orig = (handle.data ?? []).find(
                  (m) => sameUserId(m.id, quoted.messageId),
                );
                if (!orig) {
                  return {
                    id: quoted.messageId,
                    text: quoted.preview,
                    fromUser: { id: -1, name: quoted.authorName },
                  };
                }
                return {
                  id: orig.id,
                  text: orig.text,
                  fromUser: orig.fromUser,
                  createdAt: orig.createdAt,
                  mediaCount: orig.mediaCount,
                };
              })()
            : null;
          setQuoted(null);
          return sender.send({
            text: args.text,
            price: args.price,
            lockedText: args.lockedText,
            attached: args.attached,
            previews: args.previews,
            scheduledAt: args.scheduledAt,
            replyToMessageId: replyMsgId,
            replyToMessage: replySnapshot,
            taggedUsers: args.taggedUsers,
            giphyId: args.giphyId,
            uploads: args.uploads,
          });
        }}
        inflight={sender.inflight}
        canSend={
          // Trust the live chat cache; never the prop snapshot. A stale
          // `canSendMessage: false` from a pre-scope-switch click was
          // freezing the composer until the user clicked away and back.
          liveChat ? liveChat.canSendMessage !== false : true
        }
        cannotSendReason={liveChat?.canNotSendReason ?? null}
      />

      {/* Overlay drawer. Renders whenever the drawer is open — on mobile
       *  it's the only branch (the pinned column wouldn't fit at 360px).
       *  At lg+ FanDrawer hides the overlay itself (`lg:hidden`) so the
       *  in-flow pinned column below takes over. */}
      {drawerOpen && (
        <FanDrawer
          open={drawerOpen}
          onClose={() => dispatchDrawer({ type: "close" })}
          accountId={accountId}
          fanId={fanId}
          chat={chat}
          onComposeWith={(t) => composerApiRef.current?.applyTemplate(t)}
          focusNotesRequest={drawer.notesRequest}
          focusNicknameRequest={drawer.nicknameRequest}
        />
      )}
      </div>
      {/* Pinned drawer — the in-flow Fan insights column at lg+, a third
       *  column inside Messages Pro (list | chat | drawer), closable from
       *  its × and the header toggle. Hidden below lg by FanDrawer itself —
       *  see its pinned className. */}
      {drawerOpen && (
        <FanDrawer
          pinned
          open={drawerOpen}
          onClose={() => dispatchDrawer({ type: "close" })}
          accountId={accountId}
          fanId={fanId}
          chat={chat}
          onComposeWith={(t) => composerApiRef.current?.applyTemplate(t)}
          focusNotesRequest={drawer.notesRequest}
          focusNicknameRequest={drawer.nicknameRequest}
        />
      )}
    </div>
  );
}
