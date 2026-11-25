"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import type { SendStatus } from "@/hooks/useSendMessage";
import { flipCachedReadState, optimisticRead } from "@/hooks/useAccountStateEvents";
import { relayNow } from "@/lib/ageClock";
import {
  patchChatCaches, patchFanRows,
} from "@/lib/chatsCache";
import { relay, type OFChatItem } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";

export function patchCachedChat(
  qc: ReturnType<typeof useQueryClient>, accountId: string, fanId: FanId, patch: Partial<OFChatItem>,
) {
  patchChatCaches(qc, accountId, (data) => patchFanRows(data, accountId, fanId, patch));
}

function markChatRead(
  qc: ReturnType<typeof useQueryClient>, accountId: string, fanId: FanId,
): void {
  const optimistic = optimisticRead(qc, accountId, fanId);
  relay
    .post(`/admin/messages/${accountId}/${fanId}/mark-read`, undefined)
    .catch((err) => console.warn("[mark-read local] failed", err));
  relay
    .post(`/api/of/v2/chats/${fanId}/mark-as-read`, undefined, { accountId })
    .catch((err) => {
      // OF refused the write (relay 502): put back the dot, unless the row was already read.
      console.warn("[mark-as-read] failed", err);
      if (optimistic.current() && optimistic.wasUnread) {
        flipCachedReadState(qc, accountId, { fanId, unread: true, at: relayNow() }, { own: true });
      }
    });
}

export function useMarkChatRead({ accountId, fanId, markRead }: {
  accountId: string;
  fanId: FanId;
  markRead: "onOpen" | "afterFirstSend";
}) {
  const qc = useQueryClient();

  const openKey = useRef<string | null>(null);
  useEffect(() => {
    if (markRead !== "onOpen") return;
    const key = `${accountId}:${fanId}`;
    // StrictMode re-runs this effect: one pair per open.
    if (openKey.current === key) return;
    openKey.current = key;
    // Local marker fires even when OF thinks it read (not gated on hasUnread); the OF marker fires on every open, a warm page can be stale.
    markChatRead(qc, accountId, fanId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, fanId]);

  const markedRef = useRef(markRead === "onOpen");
  return useCallback((status: SendStatus) => {
    if (status !== "sent" || markedRef.current) return;
    markedRef.current = true;
    markChatRead(qc, accountId, fanId);
  }, [qc, accountId, fanId]);
}
