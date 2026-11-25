import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatSortMode } from "@/hooks/useChatSortMode";
import { lastMessageFromFan } from "@/lib/fanId";
import type { OFChatItem } from "@/lib/relay";
import { attentionCount, attentionOf, chipCounts, chipCountsWithUnreadView, sortFanRows } from "./fanListSort";

const CREATOR = "100000001";
const NOW = Date.parse("2026-11-02T12:00:00Z");

type State = "unread" | "owed" | "idle";
function chat(name: string, cents: number, state: State, ago = 0, excluded = false) {
  return {
    __accountId: CREATOR,
    withUser: { id: name, name, badgeExcluded: excluded },
    lastMessage: {
      fromUser: { id: state === "idle" ? CREATOR : name },
      createdAt: new Date(NOW - ago * 3_600_000).toISOString(),
    },
    hasUnread: state === "unread",
    unreadMessagesCount: state === "unread" ? 1 : 0,
    cents,
  } as unknown as OFChatItem & { cents: number };
}

const isOwed = (c: OFChatItem) => lastMessageFromFan(c, CREATOR);
const deps = {
  spendOf: (c: OFChatItem) => (c as OFChatItem & { cents: number }).cents,
  isOwed,
};
const names = (rows: OFChatItem[]) => rows.map((c) => c.withUser.name);
const MODES: ChatSortMode[] = ["recent", "spend", "spend-unread", "hybrid"];

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(NOW); });
afterEach(() => { vi.useRealTimers(); });

describe("sortFanRows", () => {
  const cases: Array<{ case: string; rows: OFChatItem[]; want: Record<ChatSortMode, string[]> }> = [
    {
      case: "two $0 fans keep OF order",
      rows: [chat("A", 0, "idle"), chat("B", 0, "idle")],
      want: { recent: ["A", "B"], spend: ["A", "B"], "spend-unread": ["A", "B"], hybrid: ["A", "B"] },
    },
    {
      case: "two unread $0 fans keep OF order",
      rows: [chat("A", 0, "unread"), chat("B", 0, "unread")],
      want: { recent: ["A", "B"], spend: ["A", "B"], "spend-unread": ["A", "B"], hybrid: ["A", "B"] },
    },
    {
      case: "unread vs owed vs idle tiers",
      rows: [chat("Idle50", 5_000, "idle"), chat("Owed10", 1_000, "owed"), chat("Unread1", 100, "unread")],
      want: {
        recent: ["Idle50", "Owed10", "Unread1"],
        spend: ["Idle50", "Owed10", "Unread1"],
        "spend-unread": ["Unread1", "Owed10", "Idle50"],
        hybrid: ["Idle50", "Owed10", "Unread1"],
      },
    },
    {
      case: "spend breaks ties within a tier",
      rows: [chat("Owed1", 100, "owed"), chat("Owed9", 900, "owed"), chat("Idle0", 0, "idle")],
      want: {
        recent: ["Owed1", "Owed9", "Idle0"],
        spend: ["Owed9", "Owed1", "Idle0"],
        "spend-unread": ["Owed9", "Owed1", "Idle0"],
        hybrid: ["Owed9", "Owed1", "Idle0"],
      },
    },
    {
      case: "$48 fan after 1 h silence stays above an unread $2",
      rows: [chat("Unread2", 200, "unread"), chat("Idle48", 4_800, "idle", 1)],
      want: {
        recent: ["Unread2", "Idle48"],
        spend: ["Idle48", "Unread2"],
        "spend-unread": ["Unread2", "Idle48"],
        hybrid: ["Idle48", "Unread2"],
      },
    },
    {
      case: "$48 fan after 5 h silence drops below an unread $2",
      rows: [chat("Unread2", 200, "unread"), chat("Idle48", 4_800, "idle", 5)],
      want: {
        recent: ["Unread2", "Idle48"],
        spend: ["Idle48", "Unread2"],
        "spend-unread": ["Unread2", "Idle48"],
        hybrid: ["Unread2", "Idle48"],
      },
    },
    {
      case: "an unread $48 fan after 5 h decays slower (3 h half-life) and stays on top",
      rows: [chat("Unread2", 200, "unread"), chat("Unread48", 4_800, "unread", 5)],
      want: {
        recent: ["Unread2", "Unread48"],
        spend: ["Unread48", "Unread2"],
        "spend-unread": ["Unread48", "Unread2"],
        hybrid: ["Unread48", "Unread2"],
      },
    },
    {
      case: "a restricted fan is still listed",
      rows: [chat("Restricted", 0, "unread", 0, true), chat("Idle5", 500, "idle")],
      want: {
        recent: ["Restricted", "Idle5"],
        spend: ["Idle5", "Restricted"],
        "spend-unread": ["Restricted", "Idle5"],
        hybrid: ["Idle5", "Restricted"],
      },
    },
    {
      case: "empty list",
      rows: [],
      want: { recent: [], spend: [], "spend-unread": [], hybrid: [] },
    },
  ];

  for (const c of cases) {
    it.each(MODES)(`${c.case}: %s`, (mode) => {
      const before = names(c.rows);
      const out = sortFanRows(c.rows, mode, deps);
      expect(names(out)).toEqual(c.want[mode]);
      expect(names(out).slice().sort()).toEqual(before.slice().sort());
      expect(names(c.rows)).toEqual(before);
    });
  }

  it("recent returns the server's array itself", () => {
    const rows = [chat("A", 0, "idle")];
    expect(sortFanRows(rows, "recent", deps)).toBe(rows);
  });
});

describe("attentionOf", () => {
  it.each(["unread", "owed", "idle"] as const)("%s", (state) => {
    expect(attentionOf(chat("X", 0, state), isOwed)).toBe(state);
  });
});

describe("chipCounts", () => {
  it.each([
    { case: "empty list", rows: [], want: { allCount: 0, unreadCount: 0, oweReplyCount: 0 } },
    {
      case: "restricted never counted",
      rows: [chat("R", 0, "unread", 0, true), chat("U", 0, "unread"), chat("O", 0, "owed"), chat("I", 0, "idle")],
      want: { allCount: 2, unreadCount: 1, oweReplyCount: 2 },
    },
    {
      case: "isRestricted alone (no badgeExcluded stamp) counts",
      rows: [{ ...chat("R", 0, "unread"), withUser: { id: "R", name: "R", isRestricted: true } } as OFChatItem],
      want: { allCount: 1, unreadCount: 1, oweReplyCount: 1 },
    },
    {
      case: "a muted unread row is not in the Unread count",
      rows: [{ ...chat("M", 0, "unread"), isMutedNotifications: true } as OFChatItem, chat("U", 0, "unread")],
      want: { allCount: 2, unreadCount: 1, oweReplyCount: 2 },
    },
    {
      case: "muted unread, not owed → allCount 0",
      rows: [{ ...chat("M", 0, "unread"), isMutedNotifications: true } as OFChatItem],
      owed: () => false,
      want: { allCount: 0, unreadCount: 0, oweReplyCount: 0 },
    },
    {
      case: "an owed fan counts on All and Owe reply, not Unread",
      rows: [chat("O", 0, "owed"), chat("I", 0, "idle")],
      want: { allCount: 1, unreadCount: 0, oweReplyCount: 1 },
    },
  ] as Array<{ case: string; rows: OFChatItem[]; owed?: (c: OFChatItem) => boolean; want: ReturnType<typeof chipCounts> }>)(
    "$case", ({ rows, owed = isOwed, want }) => {
      expect(chipCounts(rows, { isOwed: owed })).toEqual(want);
      expect(attentionCount(rows, owed)).toBe(want.allCount);
    },
  );
});

describe("chipCountsWithUnreadView", () => {
  const asOf = NOW - 0.5 * 3_600_000;
  const read = (c: OFChatItem) => ({ ...c, hasUnread: false, unreadMessagesCount: 0 });
  it.each([
    { case: "no view: All's counts as before", all: [chat("U", 0, "unread", 1)], view: null,
      want: { allCount: 1, unreadCount: 1, oweReplyCount: 1 } },
    { case: "read elsewhere: unread in All, not in the complete view → no Unread badge, still owed",
      all: [chat("U", 0, "unread", 1)], view: [],
      want: { allCount: 1, unreadCount: 0, oweReplyCount: 1 } },
    { case: "still unread: in the view", all: [chat("U", 0, "unread", 1)], view: [chat("U", 0, "unread", 1)],
      want: { allCount: 1, unreadCount: 1, oweReplyCount: 1 } },
    { case: "turned unread after the view's read (live message): kept and counted",
      all: [chat("N", 0, "unread", 0)], view: [],
      want: { allCount: 1, unreadCount: 1, oweReplyCount: 1 } },
    { case: "the view holds chats beyond All's loaded pages: Unread counts them",
      all: [chat("I", 0, "idle", 2)], view: [chat("D", 0, "unread", 5), chat("E", 0, "unread", 6)],
      want: { allCount: 0, unreadCount: 2, oweReplyCount: 0 } },
    { case: "restricted in the view never counted",
      all: [], view: [chat("R", 0, "unread", 1, true)],
      want: { allCount: 0, unreadCount: 0, oweReplyCount: 0 } },
    { case: "a view row this browser marked read is not counted",
      all: [], view: [read(chat("U", 0, "unread", 1))],
      want: { allCount: 0, unreadCount: 0, oweReplyCount: 0 } },
  ])("$case", ({ all, view, want }) => {
    expect(chipCountsWithUnreadView(all, view && { rows: view, asOf }, { isOwed })).toEqual(want);
  });
});
