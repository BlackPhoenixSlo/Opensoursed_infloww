"use client";


import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { decodeHtmlEntities } from "@/lib/utils";
import { proxyImage } from "@/lib/mediaUrl";

import { messagesPaintKey, useChatMessages } from "@/hooks/useChatMessages";
import { fetchOlderSeed, mergeSeedIntoMessages, useChatMessagesLocal } from "@/hooks/useChatMessagesLocal";
import { useChatAttribution } from "@/hooks/useChatAttribution";
import { useChatScreen } from "@/hooks/useChatScreen";
import { OPEN_DIALOG, OS_EDGE_PX, useSwipe } from "@/hooks/useSwipe";
import { useSendMessage, type SendStatus } from "@/hooks/useSendMessage";
import { useLikeMessage } from "@/hooks/useLikeMessage";
import { useTogglePinMessage } from "@/hooks/useTogglePinMessage";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useCan } from "@/hooks/useCan";
import { setVaultHistory, vaultHistoryKey, type FanVaultHistoryResp } from "@/hooks/useFanVaultHistory";
import { useUnsendMessage } from "@/hooks/useUnsendMessage";
import { useCreateSavedReply } from "@/hooks/useSavedReplies";
import { scriptDraftFromMessage } from "@/lib/messageScripts";
import { useFan } from "@/hooks/useFan";
import { ofUserNameKey, useCachedOFUser } from "@/hooks/useOFUser";
import { useRosterCountActions } from "@/hooks/useRosterCounts";
import { useViewLease } from "@/hooks/useViewLease";
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
import { errText } from "@/lib/errText";

import { MessageList, newestReadPointer } from "./MessageList";
import { Composer, type ComposerApi } from "./Composer";
import { FanDrawer } from "./FanDrawer";
import { ChatSearch } from "./ChatSearch";
import { ChatHeader } from "./ChatHeader";
import { PinnedBar, PinnedPopover } from "./PinnedPanel";
import { quoteFromMessage, type QuotedReply } from "./ReplyStrip";
import { useUnsendChoice } from "./UnsendChoice";
import { chatDrawerReducer, initialChatDrawer } from "./chatDrawer";
import { newBackfillKeys } from "./jumpAnchor";
import { attributionAsks, noteAsks, type Asked } from "./attributionRefresh";
import { useJumpToMessage } from "./useJumpToMessage";
import { useMarkChatRead } from "./useMarkChatRead";
import { ifAlert } from "@/components/ui/ifConfirm";

export type { QuotedReply };

interface MeResp {
  id: number;
  name?: string;
  username?: string;
  avatar?: string | null;
}

// No synchronous OF user-id source: cached so the next open starts with bubbles on the right side before meQ lands.
const ownerIdCacheKey = (accountId: string) => `of-owner:${accountId}`;

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
  markRead = "onOpen", prefetchWindowMs, onSendStart, onSendSettled, onAdvance, onHoldChange, enterAdvances,
}: {
  accountId: string;
  fanId: number | string;
  chat: OFChatItem;
  insightsOpenAtStart: boolean;
  onBack?: () => void;
  markRead?: "onOpen" | "afterFirstSend";
  prefetchWindowMs?: number;
  onSendStart?: () => void;
  onSendSettled?: (status: SendStatus) => void;
  onAdvance?: (dir: 1 | -1) => void;
  onHoldChange?: (held: boolean) => void;
  enterAdvances?: boolean;
}) {
  const { current: currentEmployee } = useEmployee();
  const qc = useQueryClient();
  useChatScreen(accountId, fanId);
  useViewLease(accountId ? [accountId] : [], "chat");
  const { refreshOne: refreshRosterOne } = useRosterCountActions();

  const [drawer, dispatchDrawer] = useReducer(
    chatDrawerReducer,
    insightsOpenAtStart,
    (atStart) => initialChatDrawer(atStart && !(typeof window !== "undefined"
      && window.matchMedia("(max-width: 1023px)").matches)),
  );
  const drawerOpen = drawer.open;
  const [quoted, setQuoted] = useState<QuotedReply | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [pinnedOpen, setPinnedOpen] = useState(false);
  const composerApiRef = useRef<ComposerApi | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  useSwipe(threadRef, {
    enabled: !!onBack && !drawerOpen, dir: "right", onSwipe: () => onBack?.(), sheet: { panel: threadRef },
    edgeGuard: OS_EDGE_PX, ignoreWhile: OPEN_DIALOG,
  });

  const meQ = useQuery<MeResp>({
    queryKey: ["of-me", accountId],
    queryFn: () => relay.get<MeResp>("/api/of/v2/users/me", { accountId }),
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const [cachedOwnerId, setCachedOwnerId] = useState<number | null>(
    () => readCachedOwnerId(accountId),
  );
  useEffect(() => {
    const id = meQ.data?.id;
    if (id == null) return;
    setCachedOwnerId(id);
    try {
      window.localStorage.setItem(ownerIdCacheKey(accountId), String(id));
    } catch { /* quota / privacy mode: async meQ still drives */ }
  }, [accountId, meQ.data?.id]);
  const ownerUserId = meQ.data?.id ?? cachedOwnerId;

  const handle = useChatMessages({
    accountId, fanId, enabled: true, prefetchWindowMs, peek: markRead === "afterFirstSend",
  });

  // Separate cache key from ["messages"]: two queryFns on one key would race. Not gated on isPending: the messages cache is persisted, so ledger-synthesized TIP rows (render only via this seed) would go missing.
  const seedQ = useChatMessagesLocal({
    enabled: true,
    accountId,
    fanId,
  });

  // Once per open; the merge only adds missing rows so the OF fetch / realtime patcher stay authoritative (not `initialData`: it fights the patcher).
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

  // Once OF supplies a cursor, deeper seed rows cannot move it into a gap.
  const loadOlderSeeded = useCallback(async () => {
    if (handle.isLoadingOlder) return handle.loadOlder();
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

  const { highlightId, jumpToMessage } = useJumpToMessage({
    accountId, fanId, handle, loadOlder: loadOlderSeeded, onJump: () => setSearchOpen(false),
  });

  useEffect(() => {
    if (!accountId || fanId == null) return;
    if ((handle.data?.length ?? 0) === 0) return;
    perfPaintOnce(messagesPaintKey(accountId, fanId), "chat.messages", {
      count: handle.data?.length ?? 0,
      ofSettled: handle.isSuccess,
      phase: "initial",
    });
  }, [accountId, fanId, handle.data, handle.isSuccess]);

  const fanQ = useFan(accountId, fanId);

  const profile = useCachedOFUser(accountId, fanId);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    if (!accountId || fanId == null) return;
    setIsRefreshing(true);
    try {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] }),
        qc.invalidateQueries({ queryKey: ofUserNameKey(accountId, fanId) }),
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
        refreshRosterOne(accountId),
        qc.invalidateQueries({ queryKey: ["chat-folders", accountId] }),
        // Inline rescrape (not the automation queue): lands in ~1-2s even while a bulk sweep hogs the lane.
        relay
          .post(
            `/admin/messages/${accountId}/${fanId}/rescrape-now`,
            undefined,
            { accountId },
          )
          .catch(() => { }),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  }, [qc, accountId, fanId, refreshRosterOne]);

  const noteSettled = useMarkChatRead({ accountId, fanId, markRead });
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

  const unsend = useUnsendChoice(unsender);

  const { mutateAsync: createScript } = useCreateSavedReply(accountId);
  const handleSaveAsScript = useCallback(async (msg: OFMessage) => {
    const draft = scriptDraftFromMessage(msg);
    const title = window.prompt("Save as script. Title:", draft.title ?? "");
    if (title === null) return;
    try {
      await createScript({ ...draft, title: title.trim() || null });
    } catch (err) {
      const reason = errText(err);
      await ifAlert(`Couldn't save the script: ${reason}`);
    }
  }, [createScript]);

  useEffect(() => {
    if (!accountId || fanId == null) return;
    const t = setTimeout(() => {
      relay
        .post<{ history?: Partial<FanVaultHistoryResp> | null } | undefined>(
          "/admin/vault/fan-history/sync",
          { account_id: accountId, fan_id: fanId },
          { accountId, priority: "background" },
        )
        .then((resp) => setVaultHistory(qc, accountId, fanId, resp?.history))
        .catch(() => {});
    }, 500);
    return () => clearTimeout(t);
  }, [accountId, fanId, qc]);

  const backfilledKeysRef = useRef<Set<string>>(new Set());
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
      sent_at: string | null;
    }> = [];
    for (const m of messages) {
      // Text key: a Fansly id is a snowflake past 2^53; Number() collapsed distinct messages.
      const mid = String(m.id ?? "");
      if (!/^\d+$/.test(mid) || /^0+$/.test(mid)) continue;
      if (!sameUserId(m.fromUser?.id, myId)) continue;
      const mediaIds = (m.media ?? [])
        .map((x) => (typeof x.id === "number" ? x.id : Number(x.id)))
        .filter((n) => Number.isFinite(n) && n > 0);
      if (mediaIds.length === 0) continue;
      candidates.push({
        message_id: mid,
        media_ids: mediaIds,
        price_cents: Math.max(0, Math.round((m.price || 0) * 100)),
        // OF also reports isOpened on free sends when the fan opens the chat: meaningless, so only PPV counts.
        was_purchased: (m.price ?? 0) > 0 ? !!m.isOpened : null,
        sent_at: m.createdAt || null,
      });
    }
    // Keyed by id + bought: a PPV the fan unlocks later is sent again so the backend flips its row.
    const keyOf = (c: (typeof candidates)[number]) => `${c.message_id}:${c.was_purchased ? 1 : 0}`;
    const firstByKey = new Map<string, (typeof candidates)[number]>();
    for (const c of candidates) if (!firstByKey.has(keyOf(c))) firstByKey.set(keyOf(c), c);
    const keys = newBackfillKeys(backfilledKeysRef.current, candidates.map(keyOf));
    const items = keys.map((k) => firstByKey.get(k)!);
    if (items.length === 0) return;
    for (const k of keys) backfilledKeysRef.current.add(k);

    relay
      .post<{ inserted?: number; updated?: number; history?: Partial<FanVaultHistoryResp> | null } | undefined>(
        "/admin/vault/sends/backfill", {
          account_id: accountId,
          fan_id: fanId,
          items,
        })
      .then(async (resp) => {
        if ((resp?.inserted ?? 0) === 0 && (resp?.updated ?? 0) === 0) return;
        if (!(await setVaultHistory(qc, accountId, fanId, resp?.history))) {
          qc.invalidateQueries({ queryKey: vaultHistoryKey(accountId, fanId) });
        }
      })
      .catch((err) => {
        for (const k of keys) backfilledKeysRef.current.delete(k);
        console.warn("[vault backfill] failed", err);
      });
  }, [accountId, fanId, handle.data, meQ.data?.id, qc]);

  const [chatsCacheTick, setChatsCacheTick] = useState(0);
  useEffect(() => {
    const unsubscribe = qc.getQueryCache().subscribe((event) => {
      if (event.type !== "added" && event.type !== "updated") return;
      const key = event.query.queryKey;
      if (Array.isArray(key) && key[0] === "chats") {
        // Deferred: observerAdded fires mid-render of ChatList; setState here trips React's warning.
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

  const lastReadByPeerId = useMemo<number | null>(
    () => newestReadPointer(chat.lastReadMessageId, liveChat?.lastReadMessageId),
    [chat.lastReadMessageId, liveChat],
  );

  function onQuoteReply(msg: OFMessage) {
    setQuoted(quoteFromMessage(msg));
  }

  const scheduledQ = useServerScheduledSends(accountId, fanId);
  const cancelScheduled = useCancelServerScheduled();
  const mergedMessages: OFMessage[] = useMemo(() => {
    const real = handle.data ?? [];
    const scheduled = scheduledQ.data ?? [];
    if (scheduled.length === 0) return real;
    return [...real, ...scheduled.map((s) => scheduledToPseudoMessage(s, ownerUserId))];
  }, [handle.data, scheduledQ.data, ownerUserId]);

  const lastReal = handle.data?.[handle.data.length - 1];
  const fanSpokeLastAt = lastReal && ownerUserId != null && !sameUserId(lastReal.fromUser?.id, ownerUserId)
    ? lastReal.createdAt ?? null
    : null;

  // Pinned slice asked of OF directly (one call, cached a minute), because
  // filtering the loaded backlog UNDERCOUNTS: a pin older than the first page
  // is invisible, so a thread holding two rendered "Pinned · 1" — verified live
  // on a thread whose only pin sat outside the head page and showed as none.
  // The backlog filter stays as the fallback for the moment before the fetch
  // resolves, and for any account where the call fails.
  const canPin = useCan(accountId, "pin_message");
  const pinnedQ = useChatPinned(accountId, fanId);
  const pinnedMessages = useMemo(
    () => (pinnedQ.data?.length ? pinnedQ.data
                                : (handle.data ?? []).filter((m) => m.isPinned)),
    [pinnedQ.data, handle.data],
  );

  const oldestVisibleId = useMemo(() => {
    const first = mergedMessages[0]?.id;
    if (first == null) return null;
    const n = typeof first === "number" ? first : Number(first);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [mergedMessages]);
  const attributionQ = useChatAttribution(accountId, fanId, oldestVisibleId);
  const attributionMap = attributionQ.data?.by_msg_id ?? null;

  const attributionAsked = useRef<Asked>(new Map());
  const attributionAt = attributionQ.dataUpdatedAt;
  const [attributionRecheck, setAttributionRecheck] = useState(0);
  useEffect(() => {
    if (!accountId || fanId == null || ownerUserId == null) return;
    if (!attributionMap) return;
    const now = Date.now();
    const { ask, recheckAt } = attributionAsks(
      mergedMessages, ownerUserId, attributionMap, attributionAt, attributionAsked.current, now,
    );
    if (ask.length > 0) {
      noteAsks(attributionAsked.current, ask, now);
      qc.invalidateQueries({ queryKey: ["msg-attribution", accountId, fanId] });
    }
    if (recheckAt == null) return;
    const t = setTimeout(() => setAttributionRecheck((n) => n + 1), recheckAt - now);
    return () => clearTimeout(t);
  }, [accountId, fanId, ownerUserId, mergedMessages, attributionMap, attributionAt, qc, attributionRecheck]);

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
          olderFailed={handle.olderFailed}
          onLoadOlder={() => loadOlderSeeded()}
          onPick={jumpToMessage}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {/* PinnedBar is hidden below md — it eats a row of vertical space
       *  and the popover overlays don't fit comfortably on a 360px screen.
       *  Pinned messages are still visible inline (📌 badges on bubbles)
       *  and the desktop bar is unchanged. */}
      {canPin && (
        <div className="hidden md:block">
          <PinnedBar
            pinned={pinnedMessages}
            open={pinnedOpen}
            onToggle={() => setPinnedOpen((v) => !v)}
          />
        </div>
      )}

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
        olderFailed={handle.olderFailed}
        headSettled={handle.headSettled}
        onLoadOlder={() => { void loadOlderSeeded().catch(() => {}); }}
        onRetry={sender.retry}
        onDiscard={sender.cancelOptimistic}
        onCancelScheduled={(jobId) => {
          if (accountId && fanId != null) {
            cancelScheduled.mutate({ jobId, accountId, fanId });
          }
        }}
        onToggleLike={(msg) => liker.toggle(msg)}
        onQuoteReply={onQuoteReply}
        onTogglePin={canPin ? (msg) => pinner.toggle(msg) : undefined}
        onUnsend={unsend.onUnsend}
        onSaveAsScript={handleSaveAsScript}
        highlightId={highlightId}
        lastReadByPeerId={lastReadByPeerId}
        attribution={attributionMap}
        currentEmployeeName={currentEmployee?.display_name ?? null}
        fanAvatar={proxyImage(chat.withUser.avatar || profile?.avatar || null, accountId) || null}
        creatorAvatar={proxyImage(meQ.data?.avatar ?? null, accountId) || null}
      />

      {unsend.dialog}

      {canPin && (
        <PinnedPopover
          pinned={pinnedMessages}
          ownerUserId={ownerUserId}
          open={pinnedOpen}
          onClose={() => setPinnedOpen(false)}
          onJumpTo={jumpToMessage}
        />
      )}

      <Composer
        accountId={accountId}
        fanId={fanId}
        fanSpokeLastAt={fanSpokeLastAt}
        fanName={headerName}
        composerApiRef={composerApiRef}
        quoted={quoted}
        onClearQuoted={() => setQuoted(null)}
        onAdvance={onAdvance}
        onHoldChange={onHoldChange}
        enterAdvances={enterAdvances}
        onSend={async (args) => {
          // Before the OF call so the panel closes even if the send errors.
          setPinnedOpen(false);
          const replyMsgId = quoted?.messageId;
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
          // canSend uses liveChat because the click-time prop can keep the composer locked after a scope switch.
          liveChat ? liveChat.canSendMessage !== false : true
        }
        cannotSendReason={liveChat?.canNotSendReason ?? null}
      />

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
