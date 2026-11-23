import type { OFChatItem } from "@/lib/relay";

/** The row shows an unread mark: OF's flag, or a nonzero unread count. */
export const isUnreadChat = (c: OFChatItem) => !!c.hasUnread || (c.unreadMessagesCount ?? 0) > 0;

/** The Relay's `withUser.badgeExcluded` stamp (`excluded_from_badges`), the one
 *  Restricted-for-counting rule; the app keeps no copy of it. */
export const excludedFromBadges = (c: OFChatItem) => !!c.withUser?.badgeExcluded;

/** Unread as OF's own badge counts it: Muted chats left out. */
export const countsAsUnread = (c: OFChatItem) =>
  isUnreadChat(c) && !c.isMutedNotifications && !excludedFromBadges(c);
