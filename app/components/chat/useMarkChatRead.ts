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

/** Patch the fan's row in every cached chat list (`["chats", …]`) at once (a mute). */
export function patchCachedChat(
  qc: ReturnType<typeof useQueryClient>, accountId: string, fanId: FanId, patch: Partial<OFChatItem>,
) {
  patchChatCaches(qc, accountId, (data) => patchFanRows(data, accountId, fanId, patch));
}

/** Mark a chat read: our local marker (zeroes chats.unread_count), OF's
 *  ("seen" receipt), and the blue dot off every cached chat list at once (a
 *  read flip: a chat-list read in flight, a Refresh or a loadMore, gets it at
 *  its commit). OF refusing the write (the relay answers 502 when it did not
 *  land) puts back the dot the row had: a row that was already read stays read. */
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
      console.warn("[mark-as-read] failed", err);
      if (optimistic.current() && optimistic.wasUnread) {
        flipCachedReadState(qc, accountId, { fanId, unread: true, at: relayNow() }, { own: true });
      }
    });
}

/** Marks the chat read on open ("onOpen") or on the first send that reaches OF
 *  ("afterFirstSend"). Returns `noteSettled`, for each send's
 *  settled status. */
export function useMarkChatRead({ accountId, fanId, markRead }: {
  accountId: string;
  fanId: FanId;
  markRead: "onOpen" | "afterFirstSend";
}) {
  const qc = useQueryClient();

  // Mark the chat read on open. Patches the inbox cache locally so the
  // blue dot disappears immediately, then fires the server POST in the
  // background (fire-and-forget — OF will catch up on its next poll
  // even if our request 5xxs).
  const openKey = useRef<string | null>(null);
  useEffect(() => {
    if (markRead !== "onOpen") return;
    // One pair per open: StrictMode (next dev) re-runs this effect.
    const key = `${accountId}:${fanId}`;
    if (openKey.current === key) return;
    openKey.current = key;
    // (1) LOCAL read-marker — zero our chats.unread_count regardless of OF's
    //     state. Opening a chat we DON'T reply to must move it off the roster's
    //     blue (unread) count and onto orange (owe reply). Fires even when OF
    //     already considered it read (chat.hasUnread === false), so it can't be
    //     gated on hasUnread. The Red circle drops through the Relay's Click
    //     read (its Write intent and counter frame), not here.
    // (2) OF read-marker — on every open (a Click read), whatever the row
    //     snapshot says: a warm page served by a peek or a stale row would
    //     otherwise leave the clicked chat unread on OF.
    markChatRead(qc, accountId, fanId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, fanId]);

  // "afterFirstSend": the first send that reaches OF marks the chat read (OF
  // "seen" too) — once, even if it settles after the chatter moved on.
  const markedRef = useRef(markRead === "onOpen");
  return useCallback((status: SendStatus) => {
    if (status !== "sent" || markedRef.current) return;
    markedRef.current = true;
    markChatRead(qc, accountId, fanId);
  }, [qc, accountId, fanId]);
}
