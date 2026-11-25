"use client";


import { useEffect, useMemo, useRef } from "react";
import { hashKey, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { vaultHistoryKey } from "@/hooks/useFanVaultHistory";
import { eventBus, type EventEnvelope } from "@/lib/events";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { ofUserFullKey } from "@/hooks/useOFUser";
import { patchQueryData } from "@/lib/cacheWrite";
import { scheduledSendsKey } from "@/hooks/useServerScheduledSends";
import type { OFChatItem, OFMessage } from "@/lib/relay";
import { isValidFanId, sameUserId, type FanId } from "@/lib/fanId";
import {
  applyReply, bumpChatPages, fanRowMatcher, freshestFanRow, decodeChatsKey, viewAdmits, parseReply, patchChatCaches, rowNewerThan,
  type ChatPages,
  type Reply,
} from "@/lib/chatsCache";
import { insertByCreatedAt, insertMsg, toUtcIso } from "@/lib/threadCache";

interface ChatMessagePayload {
  id: number;
  text?: string;
  fromUser?: { id: number; name?: string; username?: string; avatar?: string };
  toUser?: { id: number };
  chatUserId?: number;
  isFromQueue?: boolean;
  createdAt?: string;
  mediaCount?: number;
  media?: OFMessage["media"];
  price?: number;
  isFree?: boolean;
  isTip?: boolean;
  tipAmount?: number;
  isOpened?: boolean;
}

export interface ChatMessageEvent {
  api2_chat_message?: ChatMessagePayload;
  __account_id?: string;
  __fan_id?: FanId;
}

export interface ChatTarget {
  accountId: string;
  fanId: FanId;
  isOutbound: boolean;
  msg: ChatMessagePayload;
  fromId: number;
}

export function resolveChatTarget(e: ChatMessageEvent): ChatTarget | null {
  const accountId = e.__account_id ?? null;
  const msg = e.api2_chat_message ?? null;
  if (!accountId || !msg) return null;
  if (!msg.fromUser) {
    const fanId = msg.chatUserId;
    // Only the Creator's own account id is numeric here; fan ids stay opaque (a Fansly snowflake truncates through Number).
    const fromId = Number(accountId);
    if (msg.isFromQueue || !isValidFanId(fanId) || !Number.isSafeInteger(fromId)) return null;
    return { accountId, fanId, isOutbound: true, msg: { ...msg, fromUser: { id: fromId } }, fromId };
  }
  const fromUser = msg.fromUser;
  const fromId = fromUser.id;
  if (!isValidFanId(fromId)) return null;
  const isOutbound = sameUserId(fromId, accountId);
  const fanId = isOutbound ? (e.__fan_id ?? msg.toUser?.id ?? null) : fromId;
  if (!isValidFanId(fanId)) return null;
  return { accountId, fanId, isOutbound, msg, fromId };
}

export function findFanChatRow(
  qc: QueryClient,
  accountId: string,
  fanId: FanId,
): OFChatItem | null {
  const caches = qc.getQueryCache().findAll({ queryKey: ["chats"] })
    .map((q) => q.state.data as ChatPages | undefined);
  return freshestFanRow(caches, accountId, fanId);
}

// Prefix-matched so trailing key parts are covered; pinned/popout drawers never remount, so only an active refetch updates them.
function invalidateFanRevenue(qc: QueryClient, accountId: string, fanId: FanId) {
  void qc.invalidateQueries({ queryKey: ["fan-ppv-history", accountId, fanId] });
  void qc.invalidateQueries({ queryKey: ["fan-insights", accountId, fanId] });
  void qc.invalidateQueries({ queryKey: ["fan-chat-media", accountId, fanId] });
  void qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
  void qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] });
  void qc.invalidateQueries({ queryKey: ["last-purchases", accountId] });
  void qc.invalidateQueries({ queryKey: vaultHistoryKey(accountId, fanId) });
  void qc.invalidateQueries({
    queryKey: ["fan-spend", accountId],
    predicate: (q) => String(q.queryKey[2] ?? "").split(",").includes(String(fanId)),
  });
}

export function applyCachedReply(qc: QueryClient, accountId: string, reply: Reply): void {
  patchChatCaches(qc, accountId, (data, { key }) => applyReply(key, data, accountId, reply));
}

export { insertByCreatedAt, toUtcIso };

export function useInboxRealtime() {
  const qc = useQueryClient();

  const accounts = useActiveAccounts();
  const allowedAccountIds = useMemo(
    () => new Set(accounts.map((a) => String(a.id))),
    [accounts],
  );
  const allowedRef = useRef(allowedAccountIds);
  allowedRef.current = allowedAccountIds;

  useEffect(() => {
    const offMsg = eventBus.on("api2_chat_message", (env: EventEnvelope) => {
      const target = resolveChatTarget(env as unknown as ChatMessageEvent);
      if (!target) return;
      const { accountId, fanId, isOutbound, msg, fromId } = target;
      const fromUser = msg.fromUser!;

      // The SSE all-scope carries other owners' models; drop them once the roster is known (empty = still loading).
      const allowed = allowedRef.current;
      if (allowed.size > 0 && !allowed.has(accountId)) return;

      const owned = allowedRef.current.has(accountId);
      const priorRow = owned ? findFanChatRow(qc, accountId, fanId) : null;
      const eventAt = toUtcIso(msg.createdAt);
      const evtMs = Date.parse(eventAt);
      // An event older than the cached last message is a replay: it must not reorder, bump unread or become `prior`.
      const isStale = rowNewerThan(priorRow, evtMs);

      if (isOutbound) {
        void qc.invalidateQueries({ queryKey: scheduledSendsKey(accountId, fanId) });
      }

      const candidate: OFMessage = {
        id: msg.id,
        text: msg.text ?? "",
        fromUser: { id: fromId, name: fromUser.name ?? fromUser.username ?? "" },
        createdAt: eventAt,
        media: msg.media ?? [],
        mediaCount: msg.mediaCount ?? 0,
        price: msg.price ?? 0,
      };

      // A tip arrives as a normal inbound DM (isTip, price>0); the ledger ingest reconciles the amount later.
      if (!isOutbound && msg.isTip && (msg.price ?? 0) > 0) {
        invalidateFanRevenue(qc, accountId, fanId);
      }

      const threadKey = ["messages", accountId, fanId];
      const thread = qc.getQueryCache().get<OFMessage[]>(hashKey(threadKey));
      const onScreen = !!thread?.isActive() && !(typeof document !== "undefined" && document.hidden);
      if (thread && (thread.state.data !== undefined || thread.state.fetchStatus === "fetching"
          || thread.isActive())) {
        patchQueryData<OFMessage[]>(qc, threadKey, (prev = []) => insertMsg(prev, candidate));
      }

      if (isStale) return;
      const isFanRow = fanRowMatcher(accountId, fanId);
      const bumpRow = (existing: OFChatItem | null): OFChatItem | null => {
        const lastId = existing?.lastMessage?.id;
        if (lastId != null && String(lastId) === String(candidate.id)) return null;
        const base: OFChatItem = existing ?? ({
          __accountId: accountId,
          withUser: {
            id: fanId,
            name: isOutbound ? "" : (fromUser.name ?? fromUser.username ?? ""),
          },
        } as OFChatItem);
        const keepUnread = isOutbound || onScreen;
        return {
          ...base,
          hasUnread: keepUnread ? (base.hasUnread ?? false) : true,
          unreadMessagesCount: keepUnread
            ? (base.unreadMessagesCount ?? 0)
            : (base.unreadMessagesCount ?? 0) + 1,
          lastMessage: {
            id: candidate.id as number,
            text: candidate.text,
            createdAt: candidate.createdAt,
            mediaCount: candidate.mediaCount ?? 0,
            fromUser: candidate.fromUser,
          },
        };
      };

      qc.getQueryCache().findAll({ queryKey: ["chats-local-seed"] }).forEach((q) => {
        const data = q.state.data as { list?: OFChatItem[] } | undefined;
        if (!data?.list) return;
        const seedAccount = q.queryKey[2];
        if (seedAccount != null && String(seedAccount) !== accountId) return;
        const existing = data.list.find(isFanRow) ?? null;
        if (rowNewerThan(existing, evtMs)) return;
        const row = bumpRow(existing);
        if (!row) return;
        qc.setQueryData(q.queryKey, { ...data, list: [row, ...data.list.filter((c) => !isFanRow(c))] });
      });

      patchChatCaches(qc, accountId, (data, { key, replay }) => {
        const view = decodeChatsKey(key);
        const pages = bumpChatPages(data.pages, isFanRow, (existing) => {
          if (existing) return replay && rowNewerThan(existing, evtMs) ? null : bumpRow(existing);
          if (replay || (isOutbound && view.filter === "unread")) return null;
          const inserted = bumpRow(priorRow) ?? priorRow;
          return inserted && viewAdmits(view, inserted) ? inserted : null;
        });
        return pages === data.pages ? data : { ...data, pages };
      });
    });

    const offReply = eventBus.on("chat_responded", (env: EventEnvelope) => {
      const accountId = env.__account_id ?? null;
      const reply = parseReply(env.chat_responded);
      if (!accountId || !reply) return;
      const allowed = allowedRef.current;
      if (allowed.size > 0 && !allowed.has(accountId)) return;
      applyCachedReply(qc, accountId, reply);
    });

    const offTx = eventBus.on("transaction_recorded", (env: EventEnvelope) => {
      const accountId = env.__account_id ?? null;
      const tx = env.transaction_recorded as { fan_id?: FanId } | undefined;
      const fanId = tx?.fan_id ?? null;
      if (!accountId || !isValidFanId(fanId)) return;
      const allowed = allowedRef.current;
      if (allowed.size > 0 && !allowed.has(accountId)) return;
      invalidateFanRevenue(qc, accountId, fanId);
      void qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] });
    });

    const offVault = eventBus.on("vault_history_changed", (env: EventEnvelope) => {
      const accountId = env.__account_id ?? null;
      const fanId = (env.vault_history_changed as { fan_id?: FanId } | undefined)?.fan_id ?? null;
      if (!accountId || !isValidFanId(fanId)) return;
      const allowed = allowedRef.current;
      if (allowed.size > 0 && !allowed.has(accountId)) return;
      void qc.invalidateQueries({ queryKey: vaultHistoryKey(accountId, fanId) });
    });


    return () => { offMsg(); offReply(); offTx(); offVault(); };
  }, [qc]);
}
