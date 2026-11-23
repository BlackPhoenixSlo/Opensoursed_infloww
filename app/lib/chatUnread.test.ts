import { describe, expect, it } from "vitest";

import { countsAsUnread, excludedFromBadges, isUnreadChat } from "@/lib/chatUnread";
import type { OFChatItem } from "@/lib/relay";

const row = (withUser: Record<string, unknown>, extra: Record<string, unknown> = {}) =>
  ({ withUser: { id: 1, ...withUser }, hasUnread: true, unreadMessagesCount: 1, ...extra }) as unknown as OFChatItem;

describe("excludedFromBadges / countsAsUnread", () => {
  it.each([
    { case: "badgeExcluded stamp", c: row({ badgeExcluded: true }), excluded: true, counts: false },
    { case: "isRestricted alone", c: row({ isRestricted: true }), excluded: false, counts: true },
    { case: "canSendMessage false without stamp: the app holds no rule",
      c: row({}, { canSendMessage: false, canNotSendReason: "only_friends" }), excluded: false, counts: true },
    { case: "both stamps", c: row({ isRestricted: true, badgeExcluded: true }), excluded: true, counts: false },
    { case: "muted", c: row({}, { isMutedNotifications: true }), excluded: false, counts: false },
    { case: "muted and badgeExcluded", c: row({ badgeExcluded: true }, { isMutedNotifications: true }),
      excluded: true, counts: false },
    { case: "neither", c: row({}), excluded: false, counts: true },
  ])("$case", ({ c, excluded, counts }) => {
    expect(excludedFromBadges(c)).toBe(excluded);
    expect(countsAsUnread(c)).toBe(counts);
  });

  it("a read row never counts", () => {
    expect(countsAsUnread(row({}, { hasUnread: false, unreadMessagesCount: 0 }))).toBe(false);
  });

  it("a muted unread row is still unread for mark-read and sorting", () => {
    expect(isUnreadChat(row({}, { isMutedNotifications: true }))).toBe(true);
  });
});
