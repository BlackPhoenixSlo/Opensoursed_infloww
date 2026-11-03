/**
 * fanListSort — the Fan List's row order for each sort mode and its chip
 * counts, pure, no React. FanList passes the owe-reply test and the spend
 * lookup it already holds.
 */

import { isUnreadChat } from "@/lib/chatUnread";
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

/** Not a Fan we restricted on OF: those are never counted on a chip, still listed. */
export function notRestricted(c: OFChatItem): boolean {
  return !c.withUser?.isRestricted;
}

/** All's count over `rows`: not restricted, and unread or owed. Chip counts
 *  read the raw `hasUnread` flag, not `isUnreadChat` (base behaviour, kept). */
export function attentionCount(rows: OFChatItem[], isOwed: FanSortDeps["isOwed"]): number {
  return rows.filter((c) => notRestricted(c) && (c.hasUnread || isOwed(c))).length;
}

/** The chip counts over `rows`, Fans we restricted never counted: All (needs
 *  attention: unread or owed), Unread, Owe reply. */
export function chipCounts(
  rows: OFChatItem[],
  { isOwed }: Pick<FanSortDeps, "isOwed">,
): { allCount: number; unreadCount: number; oweReplyCount: number } {
  const counted = rows.filter(notRestricted);
  return {
    allCount: attentionCount(counted, isOwed),
    unreadCount: counted.filter((c) => c.hasUnread).length,
    oweReplyCount: counted.filter((c) => isOwed(c)).length,
  };
}
