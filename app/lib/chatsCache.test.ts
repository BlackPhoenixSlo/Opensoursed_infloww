import { describe, expect, it } from "vitest";

import {
  bumpAfterSend, bumpChatPages, decodeChatsKey, fanRowMatcher, freshestFanRow, keyHoldsAccount, mayAddRow,
  type ChatPage, type ChatPages, type SentMessage,
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
});
