import { countsAsUnread, excludedFromBadges, isUnreadChat } from "@/lib/chatUnread";
import { readElsewhere, unreadOutsideView, type UnreadView } from "@/lib/chatsCache";
import type { OFChatItem } from "@/lib/relay";
import {
  hybridScore,
  HALF_LIFE_IDLE,
  HALF_LIFE_UNRESPONDED,
  HALF_LIFE_UNREAD,
  type ChatSortMode,
} from "@/hooks/useChatSortMode";

export interface FanSortDeps {
  spendOf: (c: OFChatItem) => number;
  isOwed: (c: OFChatItem) => boolean;
}

const LOW_SCORE_CENTS = 300;

export type Attention = "unread" | "owed" | "idle";

export function attentionOf(c: OFChatItem, isOwed: FanSortDeps["isOwed"]): Attention {
  if (isUnreadChat(c)) return "unread";
  if (isOwed(c)) return "owed";
  return "idle";
}

const TIER: Record<Attention, number> = { unread: 2, owed: 1, idle: 0 };

const HALF_LIFE: Record<Attention, number> = {
  unread: HALF_LIFE_UNREAD,
  owed: HALF_LIFE_UNRESPONDED,
  idle: HALF_LIFE_IDLE,
};

export function sortFanRows(rows: OFChatItem[], mode: ChatSortMode, deps: FanSortDeps): OFChatItem[] {
  const { spendOf, isOwed } = deps;
  if (mode === "recent") return rows;
  // Stable sort: ties (e.g. two $0 fans) keep OF's lastActivity order.
  const arr = rows.slice();
  if (mode === "spend") {
    arr.sort((a, b) => spendOf(b) - spendOf(a));
    return arr;
  }
  if (mode === "spend-unread") {
    arr.sort((a, b) => {
      const ta = TIER[attentionOf(a, isOwed)];
      const tb = TIER[attentionOf(b, isOwed)];
      if (ta !== tb) return tb - ta;
      return spendOf(b) - spendOf(a);
    });
    return arr;
  }
  arr.sort((a, b) => {
    const aSpend = spendOf(a);
    const bSpend = spendOf(b);
    const aLast = a.lastMessage?.createdAt ?? null;
    const bLast = b.lastMessage?.createdAt ?? null;
    const aScore = hybridScore(aSpend, aLast, HALF_LIFE[attentionOf(a, isOwed)]);
    const bScore = hybridScore(bSpend, bLast, HALF_LIFE[attentionOf(b, isOwed)]);
    if (aScore < LOW_SCORE_CENTS && bScore < LOW_SCORE_CENTS) {
      const ua = isUnreadChat(a) ? 1 : 0;
      const ub = isUnreadChat(b) ? 1 : 0;
      if (ua !== ub) return ub - ua;
      if (aSpend !== bSpend) return bSpend - aSpend;
    }
    return bScore - aScore;
  });
  return arr;
}

export function attentionCount(rows: OFChatItem[], isOwed: FanSortDeps["isOwed"]): number {
  return rows.filter((c) => countsAsUnread(c) || (isOwed(c) && !excludedFromBadges(c))).length;
}

export function chipCounts(
  rows: OFChatItem[],
  { isOwed }: Pick<FanSortDeps, "isOwed">,
): { allCount: number; unreadCount: number; oweReplyCount: number } {
  const counted = rows.filter((c) => !excludedFromBadges(c));
  return {
    allCount: attentionCount(counted, isOwed),
    unreadCount: counted.filter(countsAsUnread).length,
    oweReplyCount: counted.filter((c) => isOwed(c)).length,
  };
}

export function chipCountsWithUnreadView(
  allRows: OFChatItem[],
  view: UnreadView | null,
  deps: Pick<FanSortDeps, "isOwed">,
): { allCount: number; unreadCount: number; oweReplyCount: number } {
  const counts = chipCounts(allRows, deps);
  if (!view) return counts;
  const outside = unreadOutsideView(view);
  const stale = readElsewhere(view);
  const later = allRows.filter((c) => outside(c) && !stale(c));
  return { ...counts, unreadCount: chipCounts([...view.rows, ...later], deps).unreadCount };
}
