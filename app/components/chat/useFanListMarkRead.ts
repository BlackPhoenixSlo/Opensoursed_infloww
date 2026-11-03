"use client";

/**
 * useFanListMarkRead — the Fan List's read writes: "Mark all as read" (the
 * gear), the select bar's per-chat loop (`markChatsRead`) and the optimistic
 * badge clear per success. FanList passes what they act on.
 */

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { isUnreadChat } from "@/lib/chatUnread";
import { type FanId, sameUserId } from "@/lib/fanId";
import { relay, type OFChatItem } from "@/lib/relay";

export function useFanListMarkRead({ markable, wholeCreator }: {
  /** The loaded chats "Mark all as read" acts on. */
  markable: OFChatItem[];
  /** The Creator whose every unread chat is loaded (one OF write marks them
   *  all), or null. */
  wholeCreator: string | null;
}) {
  const qc = useQueryClient();
  const [markingAll, setMarkingAll] = useState(false);

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

  return { markChatsRead, markAllRead, markingAll };
}
