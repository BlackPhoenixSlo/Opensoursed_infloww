import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import {
  applyReadFlip, applyReply, badgeUnreadView, bumpAfterSend, bumpChatPages, commitChatPages, completeUnreadView, decodeChatsKey,
  fanRowMatcher, freshestFanRow, isUnreadList, JOURNAL_MS, patchChatCaches, keyHoldsAccount, mayAddRow, UNREAD_VIEW_MAX_AGE_MS, parseReadFlip, parseReply, patchFanRows, readElsewhere, type ChatPage, type ChatPages,
  type Reply, type SentMessage,
} from "@/lib/chatsCache";
import type { FanId } from "@/lib/fanId";
import type { OFChatItem } from "@/lib/relay";

const row = (aid: string, fid: FanId, lastId = 1, at = "2026-10-01T00:00:00Z", unread = 0): OFChatItem => ({
  __accountId: aid,
  withUser: { id: fid },
  lastMessage: { id: lastId, createdAt: at, text: `m${lastId}` },
  unreadMessagesCount: unread,
} as OFChatItem);
const pagesOf = (...pages: OFChatItem[][]): ChatPage[] => pages.map((rows) => ({ rows, hasMore: true }));
const ids = (pages: ChatPage[]) => pages.map((p) => p.rows.map((r) => `${r.__accountId}:${r.withUser.id}`));

describe("decodeChatsKey / keyHoldsAccount / mayAddRow", () => {
  it.each([
    // key, unfiltered, holds "a1", holds "a2", new a1 row may enter, new a2 row may enter
    [["chats", "model", "a1", null, null, null, 30], true, true, false, true, false],
    [["chats", "model", "a1", "unread", null, null, 30], false, true, false, false, false],
    [["chats", "model", "a1", null, "list9", null, 30], false, true, false, false, false],
    [["chats", "model", "a1", null, null, "bob", 30], false, true, false, false, false],
    [["chats", "all", "a1,a2", null, null, null, 30, "oldest"], true, true, true, true, true],
    [["chats", "all", "a1,a2", "pinned", null, null, 30], false, true, true, false, false],
    [["chats", "all", "a2,a3", null, null, null, 30], true, false, true, false, true],
    [["chats", "all", "a11", null, null, null, 30], true, false, false, false, false],
    [["chats", "model", "a1"], true, true, false, true, false],
  ] as const)("%j → unfiltered %s, holds a1 %s / a2 %s, may add a1 %s / a2 %s",
    (key, unfiltered, a1, a2, add1, add2) => {
      const k = decodeChatsKey(key);
      expect(k.unfiltered).toBe(unfiltered);
      expect(keyHoldsAccount(k, "a1")).toBe(a1);
      expect(keyHoldsAccount(k, "a2")).toBe(a2);
      expect(mayAddRow(key, "a1")).toBe(add1);
      expect(mayAddRow(key, "a2")).toBe(add2);
    });
  it("reads every position", () => {
    expect(decodeChatsKey(["chats", "model", 7, "pinned", 3, "q", 30])).toEqual({
      scopeKind: "model", accountKey: "7", filter: "pinned", listId: 3, query: "q", unfiltered: false,
    });
  });
});

describe("fanRowMatcher", () => {
  it.each([
    ["number vs number", 123, 123, true],
    ["fanId '123' vs row 123", "123", 123, true],
    ["fanId 123 vs row '123'", 123, "123", true],
    ["other fan", 124, 123, false],
  ] as const)("%s", (_n, fanId, rowId, want) => {
    expect(fanRowMatcher("a1", fanId)(row("a1", rowId))).toBe(want);
    expect(fanRowMatcher("a2", fanId)(row("a1", rowId))).toBe(false);
  });
});

describe("bumpChatPages", () => {
  const add = (e: OFChatItem | null): OFChatItem =>
    ({ ...(e ?? row("a1", 9)), lastMessage: { id: 50, text: "new" } }) as OFChatItem;
  const onlyExisting = (e: OFChatItem | null) => (e ? add(e) : null);
  const never = () => null;
  // Fan 9 of a1 on page 1 (and a stale copy on page 2) behind fans 1, 2.
  const present = () => pagesOf([row("a1", 1), row("a1", 2)], [row("a1", 3), row("a1", 9, 5)], [row("a1", 9, 4)]);
  const absent = () => pagesOf([row("a1", 1), row("a1", 2)], [row("a1", 3)]);

  it.each([
    // name, pages, patch, inPlace, fanId, want ids (null = same reference)
    ["present, lifted, every copy stripped", present, add, false, 9,
      [["a1:9", "a1:1", "a1:2"], ["a1:3"], []]],
    ["present, fanId '9' vs row 9", present, add, false, "9",
      [["a1:9", "a1:1", "a1:2"], ["a1:3"], []]],
    ["present, in place (filtered send)", present, add, true, 9,
      [["a1:1", "a1:2"], ["a1:3", "a1:9"], ["a1:9"]]],
    ["present, patch → null (duplicate delivery)", present, never, false, 9, null],
    ["absent, patch → null (filtered / out of scope)", absent, onlyExisting, false, 9, null],
    ["absent, patch adds a row (unfiltered, in scope)", absent, add, false, 9,
      [["a1:9", "a1:1", "a1:2"], ["a1:3"]]],
  ] as const)("%s", (_n, make, patch, inPlace, fanId, want) => {
    const pages = make();
    const out = bumpChatPages(pages, fanRowMatcher("a1", fanId), patch, { inPlace });
    if (want === null) expect(out).toBe(pages);
    else expect(ids(out)).toEqual(want);
  });

  it("keeps the reference of every page that held no copy", () => {
    const pages = pagesOf([row("a1", 1)], [row("a1", 9)], [row("a1", 3)]);
    const out = bumpChatPages(pages, fanRowMatcher("a1", 9), add);
    expect(out).not.toBe(pages);
    expect(out[2]).toBe(pages[2]);
  });
  it("patches the first copy (the one the list shows)", () => {
    const seen: (number | undefined)[] = [];
    bumpChatPages(present(), fanRowMatcher("a1", 9), (e) => { seen.push(e?.lastMessage?.id); return add(e); });
    expect(seen).toEqual([5]);
  });
  it("empty pages: same ref even when patch would add a row", () => {
    const pages: ChatPage[] = [];
    expect(bumpChatPages(pages, fanRowMatcher("a1", 9), add)).toBe(pages);
  });
});

describe("freshestFanRow", () => {
  const a = row("a1", 9, 1, "2026-10-01T00:00:00Z");
  const b = row("a1", 9, 2, "2026-10-02T00:00:00Z");
  const undated = { ...row("a1", 9, 3), lastMessage: { id: 3 } } as OFChatItem;
  it.each([
    ["newest lastMessage wins across caches", [{ pages: pagesOf([a]) }, { pages: pagesOf([b]) }], 9, b],
    ["string fan id matches a number row", [{ pages: pagesOf([a]) }], "9", a],
    ["undated loses to dated", [{ pages: pagesOf([undated]) }, { pages: pagesOf([a]) }], 9, a],
    ["ties / undated keep the first seen", [{ pages: pagesOf([undated, { ...undated }]) }], 9, undated],
    ["absent → null", [undefined, { pages: pagesOf([row("a2", 9)]) }], 9, null],
  ] as const)("%s", (_n, caches, fanId, want) => {
    expect(freshestFanRow(caches as unknown as (ChatPages | undefined)[], "a1", fanId)).toBe(want);
  });
});

describe("bumpAfterSend", () => {
  const msg: SentMessage = { fromUserId: "a1", fromUserName: "Me", text: "hi", mediaCount: 0, price: 0 };
  const now = "2026-10-30T00:00:00.000Z";
  const data = (...pages: OFChatItem[][]): ChatPages => ({ pages: pagesOf(...pages), pageParams: [0] });
  const UNF = ["chats", "model", "a1", null, null, null, 30];
  const FIL = ["chats", "model", "a1", "unread", null, null, 30];
  const OTHER = ["chats", "model", "a2", null, null, null, 30];

  it.each([
    // name, key, rows, fanId, want ids (null = same reference)
    ["unfiltered: lifted to the top", UNF, [[row("a1", 1)], [row("a1", 9, 5, undefined, 3)]], 9,
      [["a1:9", "a1:1"], []]],
    ["unfiltered: fanId '123' vs row 123", UNF, [[row("a1", 1)], [row("a1", 123)]], "123",
      [["a1:123", "a1:1"], []]],
    ["unfiltered: fanId 123 vs row '123'", UNF, [[row("a1", 1)], [row("a1", "123")]], 123,
      [["a1:123", "a1:1"], []]],
    ["filtered: patched in place", FIL, [[row("a1", 1), row("a1", 9)]], 9, [["a1:1", "a1:9"]]],
    ["filtered: absent, untouched", FIL, [[row("a1", 1)]], 9, null],
    ["unfiltered: absent, never synthesized", UNF, [[row("a1", 1)]], 9, null],
    ["another model's list: untouched", OTHER, [[row("a2", 1), row("a2", 9)]], 9, null],
  ] as const)("%s", (_n, key, rows, fanId, want) => {
    const d = data(...(rows as unknown as OFChatItem[][]));
    const out = bumpAfterSend(key, d, "a1", fanId, msg, now);
    if (want === null) { expect(out).toBe(d); return; }
    expect(ids(out.pages)).toEqual(want);
    const r = out.pages.flatMap((p) => p.rows).find(fanRowMatcher("a1", fanId))!;
    expect(r).toMatchObject({ hasUnread: false, unreadMessagesCount: 0 });
    expect(r.lastMessage).toMatchObject({ text: "hi", createdAt: now, fromUser: { id: "a1", name: "Me" }, isFree: true });
  });

  it("drops the old message's lockedText / isTip (no 🔒/💰 on our free text)", () => {
    const old = { ...row("a1", 9), lastMessage: { id: 5, text: "😍", lockedText: true, isTip: true, isFree: true } };
    const out = bumpAfterSend(UNF, data([old]), "a1", 9, msg, now);
    const lm = out.pages[0].rows[0].lastMessage!;
    expect(lm).toEqual({ id: 5, text: "hi", fromUser: { id: "a1", name: "Me" }, createdAt: now, mediaCount: 0, isFree: true, price: 0 });
  });
});

describe("readElsewhere", () => {
  const asOf = Date.parse("2026-10-02T00:00:00Z");
  const OLD = "2026-10-01T00:00:00Z";
  const NEW = "2026-10-03T00:00:00Z";
  const unread = (aid: string, fid: FanId, at = OLD) => ({ ...row(aid, fid, 1, at, 1), hasUnread: true });
  it.each([
    // case, chat, view rows, read elsewhere
    ["unread, absent, older than the read", unread("a1", 1), [], true],
    ["unread by count alone", row("a1", 1, 1, OLD, 2), [], true],
    ["unread, in the view", unread("a1", 1), [unread("a1", 1)], false],
    ["in the view across the number/string id split", unread("a1", 1), [unread("a1", "1")], false],
    ["same fan of another Creator in the view", unread("a1", 1), [unread("a2", 1)], true],
    ["turned unread after the read", unread("a1", 1, NEW), [], false],
    ["no date", unread("a1", 1, ""), [], false],
    ["already read", row("a1", 1, 1, OLD, 0), [], false],
  ] as const)("%s → %s", (_case, chat, view, want) => {
    expect(readElsewhere({ rows: [...view], asOf })(chat)).toBe(want);
  });
});

describe("patchFanRows", () => {
  const mutedOf = (data: ChatPages) => data.pages.flatMap((p) => p.rows.map((r) => !!r.isMutedNotifications));
  const of = (...rows: OFChatItem[]): ChatPages => ({ pages: [{ rows, hasMore: false }], pageParams: [0] });
  it.each([
    ["every copy of the model's fan row", of(row("a", 1), row("a", 2), row("a", 1)), "a", 1, [true, false, true]],
    ["a string fan id against a number one", of(row("a", 1)), "a", "1", [true]],
    ["the same fan under another model is left alone", of(row("b", 1)), "a", 1, [false]],
  ] as const)("%s", (_n, data, aid, fid, muted) => {
    expect(mutedOf(patchFanRows(data, aid, fid, { isMutedNotifications: true }))).toEqual(muted);
  });

  it("the same object when the fan isn't there; no data passes through", () => {
    const data = of(row("b", 1));
    expect(patchFanRows(data, "a", 1, { hasUnread: false })).toBe(data);
    expect(patchFanRows(undefined, "a", 1, { hasUnread: false })).toBeUndefined();
  });
});

describe("completeUnreadView", () => {
  const S = "this-load";
  const u = (fid: FanId) => ({ ...row("a1", fid, 1, "2026-10-01T00:00:00Z", 1), hasUnread: true });
  const page = (rows: OFChatItem[], extra: Record<string, unknown> = {}) =>
    ({ rows, hasMore: false, session: S, askedAt: 2_000, ...extra });
  const of = (...pages: ReturnType<typeof page>[]) => ({ pages, pageParams: pages.map((_, i) => i) });
  it.each([
    ["no cache", undefined, null],
    ["no page", of(), null],
    ["a page left", of(page([u(1)], { hasMore: true })), null],
    ["read in another page load (disk)", of(page([u(1)], { session: "old" })), null],
    ["no stamp", of(page([u(1)], { askedAt: undefined })), null],
    ["a Creator missing", of(page([u(1)], { partial: true })), null],
    ["complete: rows de-duped, asOf the oldest page's ask",
      of(page([u(1), u(2)], { hasMore: true, askedAt: 3_000 }), page([u(2), u(3)], { askedAt: 1_000 })),
      { ids: ["1", "2", "3"], asOf: 1_000 }],
    ["complete and empty", of(page([])), { ids: [], asOf: 2_000 }],
  ] as const)("%s", (_case, data, want) => {
    const v = completeUnreadView(data as never, S);
    expect(v && { ids: v.rows.map((r) => String(r.withUser.id)), asOf: v.asOf }).toEqual(want);
  });
});

describe("parseReadFlip", () => {
  it.each([
    [{ fan_id: 7, unread: 0, at: 1 }, { fanId: 7, unread: false, at: 1 }],
    [{ fan_id: 7, unread: 1 }, { fanId: 7, unread: true, at: null }],
    [{ fan_id: 7, unread: 1, at: "x" }, { fanId: 7, unread: true, at: null }],
    [{ fan_id: "900604711209099264", unread: 1, at: 5 }, { fanId: "900604711209099264", unread: true, at: 5 }],
    [{ fan_id: "all", unread: 0, at: 5 }, { fanId: null, unread: false, at: 5 }],
    [{ fan_id: 7, unread: true }, null],
    [{ fan_id: "", unread: 0 }, null],
    [{ unread: 0 }, null],
    [undefined, null],
  ] as const)("%j → %j", (body, want) => {
    expect(parseReadFlip(body)).toEqual(want);
  });
});

describe("badgeUnreadView", () => {
  const view = { rows: [], asOf: 10_000 };
  const AGE = UNREAD_VIEW_MAX_AGE_MS;
  it.each([
    // case, view, on the Unread chip, now, kept
    ["no view", null, false, 10_000, false],
    ["off the chip, just read", view, false, 10_000, true],
    ["off the chip, 1 ms under the limit", view, false, 10_000 + AGE - 1, true],
    ["off the chip, at the limit", view, false, 10_000 + AGE, false],
    ["off the chip, long after", view, false, 10_000 + 10 * AGE, false],
    ["on the chip, past the limit: its own live list", view, true, 10_000 + 10 * AGE, true],
  ] as const)("%s", (_case, v, onChip, now, kept) => {
    expect(badgeUnreadView(v, onChip, now)).toBe(kept ? v : null);
  });
});

describe("isUnreadList", () => {
  it.each([
    [["chats", "model", "a", "unread", null, null, 25], true],
    [["chats", "all", "a,b", "unread", null, null, 25], true],
    [["chats", "model", "a", null, null, null, 25], false],
    [["chats", "model", "a", "unread_tips", null, null, 25], false],
    [["chats", "model", "a", "unread", "list1", null, 25], false],
    [["chats", "model", "a", "unread", null, "bob", 25], false],
    [["chats", "model", "a", "unread", null, null, 25, "old"], false],
  ] as const)("%j → %s", (key, want) => {
    expect(isUnreadList(key)).toBe(want);
  });
});

describe("applyReadFlip", () => {
  const T = (d: string) => `2026-10-0${d}T00:00:00Z`;
  const u = (aid: string, fid: FanId, d = "1", n = 2) => ({ ...row(aid, fid, 1, T(d), n), hasUnread: true });
  const r = (aid: string, fid: FanId, d = "1") => ({ ...row(aid, fid, 1, T(d)), hasUnread: false });
  const of = (...rows: OFChatItem[]): ChatPages => ({ pages: [{ rows, hasMore: false }], pageParams: [0] });
  const flags = (d: ChatPages) => d.pages.flatMap((p) => p.rows.map((c) =>
    `${c.__accountId}:${c.withUser.id}:${c.hasUnread ? "U" : "r"}${c.unreadMessagesCount}`));
  const f = (fanId: FanId | null, unread: boolean, at: number | null = null) => ({ fanId, unread, at });
  it.each([
    ["read: every copy of the fan, other Creator's same fan left",
      of(u("a", 1), u("b", 1), u("a", 1)), "a", f(1, false), {}, ["a:1:r0", "b:1:U2", "a:1:r0"]],
    ["read across the number/string id split", of(u("a", 1)), "a", f("1", false), {}, ["a:1:r0"]],
    ["unread: flags raised", of(r("a", 1), r("a", 2)), "a", f(2, true), {}, ["a:1:r0", "a:2:U1"]],
    ["mark all read: every row of the account only", of(u("a", 1), u("b", 2), u("a", 3)), "a",
      f(null, false), {}, ["a:1:r0", "b:2:U2", "a:3:r0"]],
    ["read: a message newer than the flip stays unread (a fan wrote during the write)",
      of(u("a", 1, "3"), u("a", 2, "1")), "a", f(null, false, Date.parse(T("2"))), {}, ["a:1:U2", "a:2:r0"]],
    ["Unread list, read: the row with the newer message stays", of(u("a", 1, "3")), "a",
      f(1, false, Date.parse(T("2"))), { unreadList: true }, ["a:1:U2"]],
    // Unread lists: rows enter and leave.
    ["Unread list, read: the row leaves", of(u("a", 1), u("a", 2)), "a", f(1, false), { unreadList: true }, ["a:2:U2"]],
    ["Unread list on screen, read: flags only, the open chat stays", of(u("a", 1)), "a", f(1, false),
      { unreadList: true, keepRows: true }, ["a:1:r0"]],
    ["Unread list, mark all read: the account's rows leave", of(u("a", 1), u("b", 2), u("a", 3)), "a",
      f(null, false), { unreadList: true }, ["b:2:U2"]],
    ["Unread list, unread: the copied row enters at its place (newest first)", of(u("a", 1, "3"), u("a", 2, "1")), "a",
      f(9, true), { unreadList: true, source: r("a", 9, "2") }, ["a:1:U2", "a:9:U1", "a:2:U2"]],
    ["Unread list, unread: oldest goes last when no page is left", of(u("a", 1, "3")), "a",
      f(9, true), { unreadList: true, source: r("a", 9, "1") }, ["a:1:U2", "a:9:U1"]],
    ["Unread list, unread: the source's count is kept", of(), "a",
      f(9, true), { unreadList: true, source: u("a", 9, "1", 4) }, ["a:9:U4"]],
    ["Unread list, unread, already there: flags only", of(r("a", 9)), "a",
      f(9, true), { unreadList: true, source: r("a", 9) }, ["a:9:U1"]],
    ["another list, unread, absent: never added", of(u("a", 1)), "a",
      f(9, true), { source: r("a", 9) }, ["a:1:U2"]],
  ] as const)("%s", (_case, data, aid, flip, opts, want) => {
    expect(flags(applyReadFlip(data, aid, flip, opts))).toEqual(want);
  });

  it("an Unread list with pages left: a row older than every loaded row is not added", () => {
    const data: ChatPages = { pages: [{ rows: [u("a", 1, "3")], hasMore: true }], pageParams: [0] };
    expect(applyReadFlip(data, "a", f(9, true), { unreadList: true, source: r("a", 9, "1") })).toBe(data);
  });

  it.each([
    ["an unknown fan", of(u("a", 1)), f(9, false), {}],
    ["a row already read", of(r("a", 1)), f(1, false), {}],
    ["a row already unread (count kept)", of(u("a", 1)), f(1, true), {}],
    ["mark all read with nothing unread", of(r("a", 1)), f(null, false), {}],
    ["an Unread list, unread, no cached copy anywhere", of(u("a", 1)), f(9, true), { unreadList: true, source: null }],
    ["an Unread list, read, fan absent", of(u("a", 1)), f(9, false), { unreadList: true }],
  ] as const)("the same object: %s", (_case, data, flip, opts) => {
    expect(applyReadFlip(data, "a", flip, opts)).toBe(data);
  });

  it("is idempotent: the HTTP answer and the event, either first, give one row", () => {
    const opts = { unreadList: true, source: r("a", 9, "2") };
    const once = applyReadFlip(of(u("a", 1, "3")), "a", f(9, true, 5), opts);
    expect(applyReadFlip(once, "a", f(9, true, 7), opts)).toBe(once);
    expect(flags(once)).toEqual(["a:1:U2", "a:9:U1"]);
  });

  describe("an event older than the page's read (askedAt) is skipped: the page already reflects it", () => {
    const stamped = (askedAt: number, ...rows: OFChatItem[]) =>
      ({ pages: [{ rows, hasMore: false, askedAt }], pageParams: [0] }) as unknown as ChatPages;
    const L = Date.parse(T("9"));   // later than every row's last message
    it.each([
      // case, page askedAt, event at, applied
      ["event after the read", L + 1_000, L + 2_000, true],
      ["event at the read", L + 1_000, L + 1_000, true],
      ["event before the read (a replay)", L + 2_000, L + 1_000, false],
      ["event with no at", L + 2_000, null, true],
    ] as const)("%s", (_case, askedAt, at, applied) => {
      const read = stamped(askedAt, u("a", 1));
      const outRead = applyReadFlip(read, "a", f(1, false, at), {});
      expect(outRead === read).toBe(!applied);
      const unreadList = stamped(askedAt, u("a", 1, "3"));
      const outIns = applyReadFlip(unreadList, "a", f(9, true, at), { unreadList: true, source: r("a", 9, "1") });
      expect(outIns === unreadList).toBe(!applied);
      const outDrop = applyReadFlip(unreadList, "a", f(1, false, at), { unreadList: true });
      expect(outDrop === unreadList).toBe(!applied);
    });
    it("a page with no stamp is always written", () => {
      expect(flags(applyReadFlip(of(u("a", 1)), "a", f(1, false, L), {}))).toEqual(["a:1:r0"]);
    });
  });

  it("no data passes through; untouched pages keep their reference", () => {
    expect(applyReadFlip(undefined, "a", f(1, false))).toBeUndefined();
    const data: ChatPages = { pages: [{ rows: [u("a", 1)], hasMore: true }, { rows: [u("a", 2)], hasMore: false }], pageParams: [0, 1] };
    const out = applyReadFlip(data, "a", f(2, false));
    expect(out.pages[0]).toBe(data.pages[0]);
    expect(out.pages[1]).not.toBe(data.pages[1]);
  });
});


describe("parseReply", () => {
  const m = { id: 7, text: "hi", createdAt: "2026-10-02T00:00:00Z", mediaCount: 1, price: 5 };
  it.each([
    ["full", { fan_id: 1, by: "K", at: 5, message: m },
      { fanId: 1, id: 7, createdAt: m.createdAt, text: "hi", mediaCount: 1, price: 5, at: 5 }],
    ["string ids, no at, bare message", { fan_id: "x9", message: { id: "77", createdAt: m.createdAt } },
      { fanId: "x9", id: "77", createdAt: m.createdAt, text: "", mediaCount: 0, price: 0, at: null }],
    ["older relay: no message", { fan_id: 1, by: "K" }, null],
    ["no fan", { message: m }, null],
    ["message without id", { fan_id: 1, message: { ...m, id: null } }, null],
    ["undated message", { fan_id: 1, message: { ...m, createdAt: null } }, null],
    ["garbage", "nope", null],
  ] as const)("%s", (_n, body, want) => {
    expect(parseReply(body)).toEqual(want);
  });
});

describe("applyReply", () => {
  const T = (d: string) => `2026-10-0${d}T00:00:00Z`;
  const u = (aid: string, fid: FanId, d = "1") => ({ ...row(aid, fid, 1, T(d), 2), hasUnread: true });
  const owe = (aid: string, fid: FanId, d = "1") => ({ ...row(aid, fid, 1, T(d)), lastMessage: {
    ...row(aid, fid, 1, T(d)).lastMessage!, fromUser: { id: fid } } } as OFChatItem);
  type P = { rows: OFChatItem[]; askedAt?: number };
  const of = (...pages: P[]): ChatPages => ({
    pages: pages.map((p) => ({ ...p, hasMore: true })), pageParams: pages.map((_, i) => i) });
  const pg = (rows: OFChatItem[], askedAt?: number): P => ({ rows, askedAt });
  const rep = (fanId: FanId, d = "2", at: number | null = Date.parse(T(d)), id: number | string = 50): Reply => ({
    fanId, id, createdAt: T(d), text: "yo", mediaCount: 0, price: 0, at });
  const show = (d: ChatPages) => d.pages.map((p) => p.rows.map((c) =>
    `${c.__accountId}:${c.withUser.id}:${c.lastMessage?.id}:${String(c.lastMessage?.fromUser?.id ?? "fan")}:${c.hasUnread ? "U" : "r"}${c.unreadMessagesCount ?? 0}`));
  const ALL = ["chats", "all", "a,b", null, null, null, 30];
  const UNREAD = ["chats", "all", "a,b", "unread", null, null, 30];
  const MODEL = ["chats", "model", "a", null, null, null, 30];
  it.each([
    ["All Models list: lifted to the top, preview ours, read; other Creator's same fan left",
      ALL, of(pg([owe("b", 1), u("a", 2)]), pg([u("a", 1), owe("a", 3)])), rep(1),
      [["a:1:50:a:r0", "b:1:1:1:r0", "a:2:1:fan:U2"], ["a:3:1:3:r0"]]],
    ["model list: the same", MODEL, of(pg([u("a", 2), owe("a", 1)])), rep(1),
      [["a:1:50:a:r0", "a:2:1:fan:U2"]]],
    ["Unread list: patched in place (not lifted), read", UNREAD, of(pg([u("a", 2), u("a", 1)])), rep(1),
      [["a:2:1:fan:U2", "a:1:50:a:r0"]]],
    ["string / number fan id split", ALL, of(pg([u("a", 2), owe("a", 1)])), rep("1"),
      [["a:1:50:a:r0", "a:2:1:fan:U2"]]],
  ] as const)("%s", (_n, key, data, reply, want) => {
    expect(show(applyReply(key, data, "a", reply))).toEqual(want);
  });

  it.each([
    ["fan not cached (never a new row)", ALL, of(pg([u("a", 2)])), rep(9)],
    ["a page holding him read after the reply (askedAt > at)", ALL,
      of(pg([u("a", 2)], 1), pg([owe("a", 1)], Date.parse(T("3")))), rep(1, "2")],
    ["his row already shows this message (repeat / own tab's echo)", ALL,
      of(pg([{ ...owe("a", 1), lastMessage: { ...owe("a", 1).lastMessage!, id: 50 } }])), rep(1)],
    ["his row shows a newer message (the fan wrote since)", ALL, of(pg([u("a", 1, "3")])), rep(1, "2")],
    ["empty cache", ALL, undefined, rep(1)],
  ] as const)("same data: %s", (_n, key, data, reply) => {
    expect(applyReply(key, data, "a", reply)).toBe(data);
  });

  it("an older page (askedAt before the reply) is patched", () => {
    const data = of(pg([u("a", 2), owe("a", 1)], Date.parse(T("1"))));
    expect(show(applyReply(ALL, data, "a", rep(1, "2")))).toEqual([["a:1:50:a:r0", "a:2:1:fan:U2"]]);
  });

  it("after this tab's own optimistic bump (its clock a little ahead), the event is a no-op", () => {
    const sent = bumpAfterSend(ALL, of(pg([u("a", 2), owe("a", 1)])), "a", 1,
      { fromUserId: "a", fromUserName: "me", text: "yo", mediaCount: 0, price: 0 }, "2026-10-02T00:00:01Z");
    expect(applyReply(ALL, sent, "a", rep(1, "2"))).toBe(sent);
  });

  it("a page without him keeps its reference", () => {
    const data = of(pg([u("a", 2)]), pg([owe("a", 1)]), pg([u("a", 3)]));
    const next = applyReply(ALL, data, "a", rep(1));
    expect(next.pages[2]).toBe(data.pages[2]);
    expect(show(next)).toEqual([["a:1:50:a:r0", "a:2:1:fan:U2"], [], ["a:3:1:fan:U2"]]);
  });
});

describe("the live-write journal (W30-mu #31)", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("a write older than JOURNAL_MS is not re-applied to a page with no askedSeq", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const KEY = ["chats", "model", "a1", null, null, null, 25];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const opts = {
      queryKey: KEY, initialPageParam: 0, getNextPageParam: () => undefined,
      queryFn: async () => ({ rows: [row("a1", 7, 1, undefined, 2)], hasMore: false }),
      structuralSharing: commitChatPages(client, KEY, (_p, n) => n),
    };
    await client.fetchInfiniteQuery(opts);
    patchChatCaches(client, "a1", (d) => patchFanRows(d, "a1", 7, { unreadMessagesCount: 0 }));
    expect(client.getQueryData<ChatPages>(KEY)!.pages[0].rows[0].unreadMessagesCount).toBe(0);
    vi.setSystemTime(Date.now() + JOURNAL_MS + 1);
    await client.refetchQueries({ queryKey: KEY });
    expect(client.getQueryData<ChatPages>(KEY)!.pages[0].rows[0].unreadMessagesCount).toBe(2);
  });
});
