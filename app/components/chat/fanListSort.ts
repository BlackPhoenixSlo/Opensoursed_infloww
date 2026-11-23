/**
 * fanListSort — the Fan List's row order for each sort mode and its chip
 * counts, pure, no React. FanList passes the owe-reply test and the spend
 * lookup it already holds.
 */

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
  /** The Fan's spend in cents, 0 when unknown. */
  spendOf: (c: OFChatItem) => number;
  /** The Fan sent the latest message: we owe a reply. */
  isOwed: (c: OFChatItem) => boolean;
}

/** Hybrid: below this decayed score (cents), unread rows go first. */
const LOW_SCORE_CENTS = 300;

/** A chat's attention state: unread (blue badge, `isUnreadChat`), owed (read
 *  but the Fan sent last: yellow dot, owe reply) or idle (we sent last, or no
 *  messages yet). */
export type Attention = "unread" | "owed" | "idle";

export function attentionOf(c: OFChatItem, isOwed: FanSortDeps["isOwed"]): Attention {
  if (isUnreadChat(c)) return "unread";
  if (isOwed(c)) return "owed";
  return "idle";
}

/** Spend + unread on top's tier, highest first. */
const TIER: Record<Attention, number> = { unread: 2, owed: 1, idle: 0 };

/** Hybrid's half-life: idle 1h, owe-reply 2h, unread 3h. */
const HALF_LIFE: Record<Attention, number> = {
  unread: HALF_LIFE_UNREAD,
  owed: HALF_LIFE_UNRESPONDED,
  idle: HALF_LIFE_IDLE,
};

/** The rows in `mode`'s order. "recent" returns the server order untouched
 *  (the same array). "spend" and "hybrid" rely on the deferred spend — until
 *  it lands the sort no-ops, then re-orders once data arrives. Stable sort
 *  (Array.prototype.sort is stable in all modern engines), so ties (e.g. two
 *  $0 fans) preserve OF's lastActivity ordering. */
export function sortFanRows(rows: OFChatItem[], mode: ChatSortMode, deps: FanSortDeps): OFChatItem[] {
  const { spendOf, isOwed } = deps;
  if (mode === "recent") return rows;
  const arr = rows.slice();
  if (mode === "spend") {
    arr.sort((a, b) => spendOf(b) - spendOf(a));
    return arr;
  }
  if (mode === "spend-unread") {
    // Three-tier bucket (`TIER`), then spend desc within each.
    arr.sort((a, b) => {
      const ta = TIER[attentionOf(a, isOwed)];
      const tb = TIER[attentionOf(b, isOwed)];
      if (ta !== tb) return tb - ta;
      return spendOf(b) - spendOf(a);
    });
    return arr;
  }
  // hybrid — threshold applies to the DECAYED score, not raw spend.
  // So a $48 fan starts well above the $3 cutoff, but after ~5h of
  // silence their score halves down past it and unread rows start
  // winning. Tiered half-lives keep attention-needing chats up
  // longer: idle 1h, owe-reply 2h, unread 3h. Within the low-value
  // bucket, ties between unread rows fall through to raw spend.
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
      // Both unread (or both read) at low value: raw spend desc.
      if (aSpend !== bSpend) return bSpend - aSpend;
    }
    return bScore - aScore;
  });
  return arr;
}

export function attentionCount(rows: OFChatItem[], isOwed: FanSortDeps["isOwed"]): number {
  return rows.filter((c) => countsAsUnread(c) || (isOwed(c) && !excludedFromBadges(c))).length;
}

/** The chip counts over `rows`, badge-excluded chats never counted (still
 *  listed): All (needs attention: unread or owed), Unread, Owe reply. */
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

/** `chipCounts` over the All set, with the Unread chip's complete live view
 *  (`UnreadView`, or null) as the truth for the Unread badge alone: the
 *  view's rows plus All's chats that turned unread after the view was read
 *  (or carry no date). A chat read elsewhere drops out of the badge; All's
 *  own rows and the other counts are left as they are. */
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
