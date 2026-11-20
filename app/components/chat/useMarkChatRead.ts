"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { useRosterCountActions } from "@/hooks/useRosterCounts";
import type { SendStatus } from "@/hooks/useSendMessage";
import { patchFanRows, type ChatPages } from "@/lib/chatsCache";
import { relay, type OFChatItem } from "@/lib/relay";
import { sameUserId, type FanId } from "@/lib/fanId";

/** Patch the fan's row in every cached chat list (`["chats", …]`) at once. */
export function patchCachedChat(
  qc: ReturnType<typeof useQueryClient>, accountId: string, fanId: FanId, patch: Partial<OFChatItem>,
) {
  qc.getQueryCache().findAll({ queryKey: ["chats"] }).forEach((q) => {
    const data = q.state.data as ChatPages | undefined;
    const next = patchFanRows(data, accountId, fanId, patch);
    if (next !== data) qc.setQueryData(q.queryKey, next);
  });
}

/** Mark a chat read: our local marker (zeroes chats.unread_count; resolves
 *  whether it cleared one), OF's — a "seen" receipt — only when OF still shows
 *  it unread, and the blue dot off every cached chat list at once. */
async function markChatRead(
  qc: ReturnType<typeof useQueryClient>, accountId: string, fanId: FanId, ofUnread: boolean,
): Promise<boolean> {
  const local = relay
    .post<{ cleared?: boolean }>(`/admin/messages/${accountId}/${fanId}/mark-read`, undefined)
    .then((res) => !!res?.cleared)
    .catch((err) => {
      console.warn("[mark-read local] failed", err);
      return false;
    });
  if (ofUnread) {
    relay
      .post(`/api/of/v2/chats/${fanId}/mark-as-read`, undefined, { accountId })
      .catch((err) => console.warn("[mark-as-read] failed", err));
  }
  // A chat-list read in flight (a Refresh, a loadMore) predates this mark: drop
  // it, or it lands after the patch and paints the dot back. Lists with no data
  // yet keep theirs (cancelling would leave them empty until the next poll).
  // Only when a cached row still shows the dot: an already-read chat changes
  // nothing, and opening it must not cancel a Refresh or a loadMore.
  const dotted = qc.getQueryCache().findAll({ queryKey: ["chats"] }).some((q) =>
    (q.state.data as ChatPages | undefined)?.pages?.some((p) => p.rows.some((c) =>
      (c.hasUnread || !!c.unreadMessagesCount) && (c.__accountId ?? "") === accountId && sameUserId(c.withUser.id, fanId))));
  if (!dotted) return local;
  await qc.cancelQueries({ queryKey: ["chats"], predicate: (q) => q.state.data !== undefined });
  patchCachedChat(qc, accountId, fanId, { hasUnread: false, unreadMessagesCount: 0 });
  return local;
}

/** Marks the chat read on open ("onOpen") or on the first send that reaches OF
 *  ("afterFirstSend"). Returns `noteSettled`, for each send's
 *  settled status. */
export function useMarkChatRead({ accountId, fanId, hasUnread, markRead }: {
  accountId: string;
  fanId: FanId;
  /** OF still shows the chat unread (the `chat` prop's snapshot). */
  hasUnread: boolean;
  markRead: "onOpen" | "afterFirstSend";
}) {
  const qc = useQueryClient();
  const { patchLocal: patchRosterLocal } = useRosterCountActions();

  // Mark the chat read on open. Patches the inbox cache locally so the
  // blue dot disappears immediately, then fires the server POST in the
  // background (fire-and-forget — OF will catch up on its next poll
  // even if our request 5xxs).
  useEffect(() => {
    if (markRead !== "onOpen") return;
    let cancelled = false;
    // (1) LOCAL read-marker — zero our chats.unread_count regardless of OF's
    //     state. Opening a chat we DON'T reply to must move it off the roster's
    //     blue (unread) count and onto orange (owe reply). Fires even when OF
    //     already considered it read (chat.hasUnread === false), so it can't be
    //     gated on hasUnread. Refresh the roster badge only when it cleared.
    // (2) OF read-marker — only when OF still shows it unread (avoids a needless
    //     upstream call + "seen" receipt on an already-read chat).
    void markChatRead(qc, accountId, fanId, hasUnread).then((cleared) => {
      if (cleared && !cancelled) {
        // Opening an unread chat moves it off the roster's BLUE (unread) and
        // onto ORANGE (read, fan spoke last) in the same tick — patch the cached
        // badge optimistically so it drops instantly. We deliberately DON'T
        // re-read OF here: the mark-read POST already busts the server-side
        // roster cache, and the badge is OF-truth, so an immediate re-read could
        // race OF's own read-processing and flicker the count back up. The 60s
        // poll (now reading a busted cache) reconciles to OF-truth cleanly.
        patchRosterLocal(accountId, (c) => ({
          ...c, // keeps `unread_capped`: a "25+" badge stays "24+", not a plain 24
          unread: Math.max(0, c.unread - 1),
          owe_reply: c.owe_reply + 1,
        }));
      }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, fanId, patchRosterLocal]);

  // "afterFirstSend": the first send that reaches OF marks the chat read (OF
  // "seen" too) — once, even if it settles after the chatter moved on. The
  // send already took the roster badge down, so it isn't patched again.
  const markedRef = useRef(markRead === "onOpen");
  return useCallback((status: SendStatus) => {
    if (status !== "sent" || markedRef.current) return;
    markedRef.current = true;
    void markChatRead(qc, accountId, fanId, hasUnread);
  }, [qc, accountId, fanId, hasUnread]);
}
