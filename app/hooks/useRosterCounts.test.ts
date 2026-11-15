/**
 * Roster badge math — the pure core of the optimistic-badge path.
 *
 * The realtime handler (and useSendMessage) derive a per-model badge delta from
 * the fan conversation's PRIOR state + message direction, instead of firing an
 * extra OF `?bust` re-read. These are the CONVERSATION-count semantics (a chat
 * contributes at most 1 to unread OR owe_reply) plus the poll-merge guard that
 * stops the 60s poll from clobbering an optimistic patch.
 */
import { describe, it, expect } from "vitest";

import {
  rosterDelta,
  applyRosterDelta,
  rosterPriorFromRow,
  mergeRosterCounts,
  type RosterCountsResp,
} from "./useRosterCounts";
import type { OFChatItem } from "@/lib/relay";

describe("rosterDelta", () => {
  // INBOUND — the fan spoke.
  it("inbound to a caught-up chat → +1 blue", () => {
    expect(rosterDelta(false, { wasUnread: false, fanSpokeLast: false })).toEqual({ dUnread: 1, dOwe: 0 });
  });
  it("inbound to an owe-reply (orange) chat → +1 blue, -1 orange", () => {
    expect(rosterDelta(false, { wasUnread: false, fanSpokeLast: true })).toEqual({ dUnread: 1, dOwe: -1 });
  });
  it("inbound to an ALREADY-unread chat → no change (dedupe: no triple-count)", () => {
    expect(rosterDelta(false, { wasUnread: true, fanSpokeLast: false })).toEqual({ dUnread: 0, dOwe: 0 });
  });

  // OUTBOUND — we replied.
  it("outbound to an owe-reply chat → -1 orange", () => {
    expect(rosterDelta(true, { wasUnread: false, fanSpokeLast: true })).toEqual({ dUnread: 0, dOwe: -1 });
  });
  it("outbound to a caught-up chat → no change", () => {
    expect(rosterDelta(true, { wasUnread: false, fanSpokeLast: false })).toEqual({ dUnread: 0, dOwe: 0 });
  });
  it("outbound to a still-unread chat → -1 blue (kill stale blue)", () => {
    expect(rosterDelta(true, { wasUnread: true, fanSpokeLast: false })).toEqual({ dUnread: -1, dOwe: 0 });
  });
});

describe("applyRosterDelta", () => {
  it("adds and subtracts", () => {
    expect(applyRosterDelta({ unread: 2, owe_reply: 3 }, { dUnread: 1, dOwe: -1 })).toEqual({ unread: 3, owe_reply: 2 });
  });
  it("clamps at zero — a stale/duplicate event can never drive a badge negative", () => {
    expect(applyRosterDelta({ unread: 0, owe_reply: 0 }, { dUnread: -1, dOwe: -1 })).toEqual({ unread: 0, owe_reply: 0 });
  });
});

describe("rosterPriorFromRow", () => {
  const row = (o: Partial<OFChatItem>): OFChatItem =>
    ({ withUser: { id: 5, name: "f" }, ...o }) as OFChatItem;

  it("null row → null (caller falls back to an authoritative re-read)", () => {
    expect(rosterPriorFromRow(null)).toBeNull();
  });
  it("unreadMessagesCount>0 → wasUnread", () => {
    expect(rosterPriorFromRow(row({ unreadMessagesCount: 2 }))).toMatchObject({ wasUnread: true });
  });
  it("hasUnread flag → wasUnread", () => {
    expect(rosterPriorFromRow(row({ hasUnread: true }))).toMatchObject({ wasUnread: true });
  });
  it("fan spoke last (lastMessage.fromUser.id === fan) → fanSpokeLast", () => {
    expect(
      rosterPriorFromRow(row({ withUser: { id: 5, name: "f" }, lastMessage: { id: 1, fromUser: { id: 5 } } })),
    ).toEqual({ wasUnread: false, fanSpokeLast: true });
  });
  it("we spoke last (lastMessage.fromUser.id !== fan) → !fanSpokeLast", () => {
    expect(
      rosterPriorFromRow(row({ withUser: { id: 5, name: "f" }, lastMessage: { id: 1, fromUser: { id: 999 } } })),
    ).toEqual({ wasUnread: false, fanSpokeLast: false });
  });
});

describe("mergeRosterCounts (60s-poll vs optimistic-patch race — codex FM2)", () => {
  const resp = (c: Record<string, { unread: number; owe_reply: number }>): RosterCountsResp => ({ counts: c });

  it("no prev cache → server response as-is", () => {
    expect(mergeRosterCounts(resp({ a: { unread: 1, owe_reply: 0 } }), undefined, 100, () => 0)).toEqual({
      counts: { a: { unread: 1, owe_reply: 0 } },
    });
  });
  it("KEEPS the local value for an account patched WHILE the poll was in flight", () => {
    const server = resp({ a: { unread: 0, owe_reply: 0 } }); // stale server snapshot
    const prev = resp({ a: { unread: 1, owe_reply: 0 } }); // optimistic value
    // patchedAt(a)=150 > fetchStartedAt=100 → the server predates the patch → keep local
    expect(mergeRosterCounts(server, prev, 100, () => 150)).toEqual({ counts: { a: { unread: 1, owe_reply: 0 } } });
  });
  it("takes the SERVER value when the last patch predates the poll", () => {
    const server = resp({ a: { unread: 5, owe_reply: 0 } });
    const prev = resp({ a: { unread: 1, owe_reply: 0 } });
    expect(mergeRosterCounts(server, prev, 100, () => 50)).toEqual({ counts: { a: { unread: 5, owe_reply: 0 } } });
  });
  it.each([
    ["patched", 150],
    ["never patched", 0],
  ])("an account missing from the server response keeps its cached value (%s)", (_n, at) => {
    const server = resp({}); // an Idle Creator the server holds nothing for (e.g. after a Relay restart)
    const prev = resp({ a: { unread: 1, owe_reply: 0 } });
    expect(mergeRosterCounts(server, prev, 100, () => at)).toEqual({ counts: { a: { unread: 1, owe_reply: 0 } } });
  });
});

describe("mergeRosterCounts as_of (an Idle Creator's held count never jumps back, ADR-0031)", () => {
  const resp = (c: RosterCountsResp["counts"]): RosterCountsResp => ({ counts: c });
  const local = { unread: 2, owe_reply: 1 };
  const held = (as_of?: number) => ({ unread: 0, owe_reply: 0, ...(as_of === undefined ? {} : { as_of }) });
  it.each([
    // [case, server as_of, patchedAt, fetchStartedAt, want]
    ["a patch newer than as_of wins, though the poll started after it", 50, 60, 100, "local"],
    ["a patch older than as_of loses", 50, 40, 100, "server"],
    ["a patch at as_of loses", 50, 50, 100, "server"],
    ["as_of 0 (unknown): the poll start decides, newer patch wins", 0, 150, 100, "local"],
    ["as_of 0 (unknown): the poll start decides, older patch loses", 0, 60, 100, "server"],
    ["no as_of: the poll start decides", undefined, 60, 100, "server"],
  ] as const)("%s", (_n, asOf, patched, started, want) => {
    const out = mergeRosterCounts(resp({ a: held(asOf) }), resp({ a: local }), started, () => patched);
    expect(out.counts.a).toEqual(want === "local" ? local : held(asOf));
  });
});
