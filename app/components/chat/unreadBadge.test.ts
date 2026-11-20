import { describe, expect, it, vi } from "vitest";

import { chipCountsWithUnreadView } from "./fanListSort";
import type { CreatorFreshnessState, Freshness, HeldFreshness } from "@/lib/creatorFreshness";
import type { UnreadView } from "@/lib/chatsCache";
import type { OFChatItem } from "@/lib/relay";
import {
  badgeReady, badgeUnread, totalsOn, todaysUnread, unreadBadgeSources, type AccountsAnswer, type Fallback,
} from "./unreadBadge";

const snap = (aid: string, values: Freshness["values"], over: Partial<Freshness> = {}): HeldFreshness => ({
  account_id: aid, boot: 1000, seq: 1, now: 5_000, at: 4_000, cycle_s: 600, live: "up", live_since: 3_000,
  values, receivedAt: 50, ...over,
});
const total = (n: number, at = 4_500) => ({ unread_total: { n, at } });
const store = (...held: HeldFreshness[]): CreatorFreshnessState =>
  Object.fromEntries(held.map((h) => [h.account_id, h]));
const row = (freshness?: Freshness | null) => ({ freshness });

describe("totalsOn", () => {
  it.each<[string, Array<{ freshness?: Freshness | null }> | null | undefined, boolean | null]>([
    ["a row holds the key", [row(snap("a", total(3)))], true],
    ["a null value still says on", [row(snap("a", { unread_total: null }))], true],
    ["one row of several holds it", [row(snap("a", {})), row(snap("b", total(1)))], true],
    ["rows with freshness but no key: off", [row(snap("a", {})), row(snap("b", { notif_count: 2 }))], false],
    ["rows with no freshness (refresher off): off", [row(), row(null)], false],
    ["no rows: unknown", [], null],
    ["no answer at all: unknown", undefined, null],
  ])("%s", (_name, rows, want) => {
    expect(totalsOn(rows)).toBe(want);
  });
});

describe("badgeReady (first paint, rule 3)", () => {
  it.each<[string, boolean | null, AccountsAnswer, boolean, boolean]>([
    ["off in the persisted copy: today's number at once", false, "none", false, true],
    ["on in the persisted copy: no number before the network answer", true, "none", false, false],
    ["on, even with a store already held (not this answer's)", true, "none", true, false],
    ["unknown (fresh session): no number before the network answer", null, "none", false, false],
    ["network says on, seed not in the store yet: still none", true, "network", false, false],
    ["network says on, seeded: a number", true, "network", true, true],
    ["network says off: a number", false, "network", false, true],
    ["network has no rows: a number", null, "network", false, true],
    ["the answer failed: a number", true, "error", false, true],
  ])("%s", (_name, on, answer, seeded, want) => {
    expect(badgeReady(on, answer, seeded)).toBe(want);
  });
});

describe("badgeUnread", () => {
  const go = { ready: true, search: false };
  // Today's rule as the Fan List hands it: 2 over every row, 1 per Creator asked for.
  const fallback = () => vi.fn<Fallback>((creators) => (creators === null ? 2 : creators.size));

  it("before the network answer: no number, nothing counted", () => {
    const f = fallback();
    expect(badgeUnread(store(snap("a", total(7))), ["a"], f, { ready: false, search: false }))
      .toEqual({ n: null, fromTotal: [], fallback: [] });
    expect(f).not.toHaveBeenCalled();
  });

  it("under a search: today's rule over every row, held totals ignored", () => {
    const f = fallback();
    expect(badgeUnread(store(snap("a", total(7))), ["a", "b"], f, { ready: true, search: true }))
      .toEqual({ n: 2, fromTotal: [], fallback: ["a", "b"] });
    expect(f).toHaveBeenCalledWith(null);
  });

  it("no Creator holds a total (Knob off): today's number exactly, over every row", () => {
    const f = fallback();
    expect(badgeUnread(store(snap("a", {}), snap("b", { unread_total: null })), ["a", "b"], f, go))
      .toEqual({ n: 2, fromTotal: [], fallback: ["a", "b"] });
    expect(f).toHaveBeenCalledWith(null);
  });

  it.each<[string, CreatorFreshnessState, string[], { n: number; fromTotal: string[]; fallback: string[] }]>([
    ["every shown Creator held: Σ totals, no row counted", store(snap("a", total(7)), snap("b", total(3))), ["a", "b"],
      { n: 10, fromTotal: ["a", "b"], fallback: [] }],
    ["mixed: held totals plus today's rule over the others' rows", store(snap("a", total(7))), ["a", "b", "c"],
      { n: 9, fromTotal: ["a"], fallback: ["b", "c"] }],
    ["a null total counts by today's rule", store(snap("a", total(7)), snap("b", { unread_total: null })), ["a", "b"],
      { n: 8, fromTotal: ["a"], fallback: ["b"] }],
    ["a held Creator not shown is not counted", store(snap("a", total(7)), snap("z", total(50))), ["a"],
      { n: 7, fromTotal: ["a"], fallback: [] }],
    ["a Dead-session Creator's frozen total still counts", store(snap("a", total(4), { live: "dead" })), ["a"],
      { n: 4, fromTotal: ["a"], fallback: [] }],
    ["a zero total is a total", store(snap("a", total(0))), ["a", "b"], { n: 1, fromTotal: ["a"], fallback: ["b"] }],
    ["a malformed total counts by today's rule", store(snap("a", { unread_total: { n: "7", at: 1 } as never })), ["a"],
      { n: 2, fromTotal: [], fallback: ["a"] }],
  ])("%s", (_name, state, shown, want) => {
    expect(badgeUnread(state, shown, fallback(), go)).toEqual(want);
  });

  it("asks today's rule only for the Creators without a total", () => {
    const f = fallback();
    badgeUnread(store(snap("a", total(7))), ["a", "b"], f, go);
    expect(f).toHaveBeenCalledTimes(1);
    expect([...f.mock.calls[0][0]!]).toEqual(["b"]);
  });
});

describe("unreadBadgeSources (Phase 3's input: each Creator's confirmation time)", () => {
  it.each<[string, CreatorFreshnessState, string[], Array<{ account_id: string; at: number | null }>]>([
    ["the total's at later than Last refresh → the total's", store(snap("a", total(3, 4_500), { at: 4_000 })), ["a"],
      [{ account_id: "a", at: 4_500 }]],
    ["Last refresh later than the total's at → Last refresh", store(snap("a", total(3, 2_000), { at: 4_000 })), ["a"],
      [{ account_id: "a", at: 4_000 }]],
    ["no Last refresh yet → the total's at", store(snap("a", total(3, 2_000), { at: null })), ["a"],
      [{ account_id: "a", at: 2_000 }]],
    // A reused warm republishes `creator_warmed` with `at` = now and no read: never a confirmation.
    ["a fresh creator_warmed slot never counts", store(snap("a", { ...total(3, 2_000), creator_warmed: { at: 9_999 } },
      { at: 1_000 })), ["a"], [{ account_id: "a", at: 2_000 }]],
    ["order of the ids asked, every id", store(snap("a", total(1, 10)), snap("b", total(2, 20))), ["b", "a"],
      [{ account_id: "b", at: 4_000 }, { account_id: "a", at: 4_000 }]],
    ["an id not held → at null", store(), ["x"], [{ account_id: "x", at: null }]],
    ["no total held and no Last refresh → at null", store(snap("a", {}, { at: null })), ["a"],
      [{ account_id: "a", at: null }]],
  ])("%s", (_name, state, ids, want) => {
    expect(unreadBadgeSources(state, ids)).toEqual(want);
  });
});

describe("todaysUnread", () => {
  const isOwed = () => false;
  const chat = (aid: string, fan: number, unread: boolean, minAgo = 60): OFChatItem => ({
    __accountId: aid,
    withUser: { id: fan, name: `Fan ${fan}`, username: `fan${fan}`, avatar: null },
    lastMessage: { id: fan, text: "hi", createdAt: new Date(Date.now() - minAgo * 60_000).toISOString() },
    hasUnread: unread, unreadMessagesCount: unread ? 1 : 0,
  } as OFChatItem);
  const rows = [chat("a", 1, true), chat("a", 2, true), chat("b", 3, true), chat("b", 4, false)];
  const accountOf = (c: OFChatItem) => c.__accountId ?? "";

  it("null: today's number over every row, the same as chipCountsWithUnreadView", () => {
    const view: UnreadView = { rows: [rows[0]], asOf: Date.now() };
    for (const v of [null, view]) {
      expect(todaysUnread(rows, v, { isOwed }, null, accountOf))
        .toBe(chipCountsWithUnreadView(rows, v, { isOwed }).unreadCount);
    }
  });

  it("a set: today's rule over those Creators' rows and their part of #881's view only", () => {
    expect(todaysUnread(rows, null, { isOwed }, new Set(["b"]), accountOf)).toBe(1);
    expect(todaysUnread(rows, null, { isOwed }, new Set(["a"]), accountOf)).toBe(2);
    // #881's view (read now) holds only Fan 1: Fan 2 was read elsewhere, so a's rule counts 1.
    const view: UnreadView = { rows: [rows[0]], asOf: Date.now() };
    expect(todaysUnread(rows, view, { isOwed }, new Set(["a"]), accountOf)).toBe(1);
    expect(todaysUnread(rows, view, { isOwed }, new Set(["b"]), accountOf)).toBe(0);
  });
});
