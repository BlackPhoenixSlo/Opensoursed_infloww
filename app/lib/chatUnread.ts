import type { OFChatItem } from "@/lib/relay";

export const isUnreadChat = (c: OFChatItem) => !!c.hasUnread || (c.unreadMessagesCount ?? 0) > 0;

export const excludedFromBadges = (c: OFChatItem) => !!c.withUser?.badgeExcluded;

export const countsAsUnread = (c: OFChatItem) =>
  isUnreadChat(c) && !c.isMutedNotifications && !excludedFromBadges(c);
