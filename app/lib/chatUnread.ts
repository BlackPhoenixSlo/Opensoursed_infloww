import type { OFChatItem } from "@/lib/relay";

/** The row shows an unread mark: OF's flag, or a nonzero unread count. */
export const isUnreadChat = (c: OFChatItem) => !!c.hasUnread || (c.unreadMessagesCount ?? 0) > 0;

/** Unread backlog: an unread chat with a Fan we did not restrict (a Fan we cut
 *  off on OF is not backlog). */
export const countsAsUnread = (c: OFChatItem) => isUnreadChat(c) && !c.withUser?.isRestricted;
