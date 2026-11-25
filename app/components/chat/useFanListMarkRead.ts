"use client";


import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { flipCachedReadState } from "@/hooks/useAccountStateEvents";
import { relayNow } from "@/lib/ageClock";
import { isUnreadChat } from "@/lib/chatUnread";
import { type FanId, sameUserId } from "@/lib/fanId";
import { ackedFanIds, relay, type OFChatItem } from "@/lib/relay";
import { ifAlert, ifConfirm } from "@/components/ui/ifConfirm";

export function useFanListMarkRead({ markable, wholeCreator }: {
  markable: OFChatItem[];
  wholeCreator: string | null;
}) {
  const qc = useQueryClient();
  const [markingAll, setMarkingAll] = useState(false);

  const markRowRead = useCallback((accountId: string, fanId: FanId) => {
    flipCachedReadState(qc, accountId, { fanId, unread: false, at: relayNow() }, { own: true });
  }, [qc]);

  // Unpaced: a read flip reaches no fan, so it must not hold the write slot ahead of fan sends.
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

  async function markCreatorRead(accountId: string, rows: OFChatItem[]): Promise<number> {
    try {
      await relay.post("/api/of/v2/chats/mark-as-read", undefined, { accountId });
      for (const c of rows) markRowRead(accountId, c.withUser.id);
      return 0;
    } catch (err) {
      console.warn("[mark-read] mark all failed for", accountId, err);
      const acked = ackedFanIds(err);
      const done = rows.filter((c) => acked.some((f) => sameUserId(f, c.withUser.id)));
      for (const c of done) markRowRead(accountId, c.withUser.id);
      return rows.length - done.length;
    } finally {
      invalidateReadState();
    }
  }

  async function markAllRead() {
    if (markingAll) return;
    const targets = markable.filter(isUnreadChat);
    if (targets.length === 0) return;
    if (!(await ifConfirm(`Mark ${targets.length} chat${targets.length === 1 ? "" : "s"} as read?`))) return;
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
      await ifAlert(`Marked ${targets.length - failed} of ${targets.length}; ${failed} failed.`);
    }
  }

  return { markChatsRead, markAllRead, markingAll };
}
