import { afterEach, describe, expect, it, vi } from "vitest";

import {
  GROUP_HEARTBEAT_TTL_MS, GROUP_SLOT_CAP, GROUP_TAB_KEY_PREFIX, cleanGroupMessage, cleanGroupTab, cleanSlots,
  isGroupSlot, openGroupTab, parseSlotsParam, readAllLiveGroupTabs,
} from "./groupChannel";

const SNOW = "900234567890123456";

describe("isGroupSlot", () => {
  it.each<[unknown, boolean]>([
    [{ accountId: "a", fanId: 1 }, true],
    [{ accountId: "a", fanId: "123" }, true],
    [{ accountId: "a", fanId: SNOW }, true],
    [{ accountId: "a", fanId: "" }, false],
    [{ accountId: "a", fanId: "abc" }, false],
    [{ accountId: "a", fanId: 0 }, false],
    [{ accountId: "a", fanId: -5 }, false],
    [{ accountId: "a", fanId: 1.5 }, false],
    [{ accountId: "", fanId: 1 }, false],
    [{ accountId: 7, fanId: 1 }, false],
    [{ fanId: 1 }, false],
    [null, false],
    ["a:1", false],
  ])("%j -> %s", (x, want) => {
    expect(isGroupSlot(x)).toBe(want);
  });
});

describe("cleanSlots", () => {
  it.each<[unknown, unknown[]]>([
    [undefined, []],
    ["a:1", []],
    [{ 0: { accountId: "a", fanId: 1 } }, []],
    [[{ accountId: "a", fanId: 1, extra: 1 }, null, { accountId: "a", fanId: "abc" }, { accountId: "a", fanId: SNOW }],
      [{ accountId: "a", fanId: 1 }, { accountId: "a", fanId: SNOW }]],
  ])("%j -> %j", (x, want) => {
    expect(cleanSlots(x)).toEqual(want);
  });
});

// The receive side of the channel: anything a same-origin page posts.
describe("cleanGroupMessage", () => {
  const T = { tabId: "t", reqId: "r" };
  it.each<[string, unknown, unknown]>([
    ["null", null, null],
    ["a string", "add", null],
    ["a number", 7, null],
    ["unknown type", { ...T, type: "nope" }, null],
    ["no tabId", { type: "focus" }, null],
    ["numeric tabId", { type: "focus", tabId: 1 }, null],
    ["focus", { type: "focus", tabId: "t", x: 1 }, { type: "focus", tabId: "t" }],
    ["add without reqId owes no ack: ignored", { type: "add", tabId: "t", accountId: "a", fanId: 1 }, null],
    ["add", { ...T, type: "add", accountId: "a", fanId: 1 }, { ...T, type: "add", accountId: "a", fanId: 1 }],
    ["add: Fansly snowflake stays the same string", { ...T, type: "add", accountId: "a", fanId: SNOW },
      { ...T, type: "add", accountId: "a", fanId: SNOW }],
    // Malformed slot: passed on as it came (only the envelope is judged here); slotsReducer refuses it, and the
    // tab still owes an ok:false.
    ["add: bad fan id passed on", { ...T, type: "add", accountId: "a", fanId: { n: 1 } },
      { ...T, type: "add", accountId: "a", fanId: { n: 1 } }],
    ["add: missing account passed on", { ...T, type: "add", fanId: 1 }, { ...T, type: "add", accountId: undefined, fanId: 1 }],
    ["replace without slots: none (refused)", { ...T, type: "replace" }, { ...T, type: "replace", slots: [] }],
    ["replace with non-list slots: none", { ...T, type: "replace", slots: "a:1" }, { ...T, type: "replace", slots: [] }],
    ["replace passes its entries on as they came", { ...T, type: "replace", slots: [{ accountId: "a", fanId: SNOW }, 5] },
      { ...T, type: "replace", slots: [{ accountId: "a", fanId: SNOW }, 5] }],
    ["replace without reqId", { type: "replace", tabId: "t", slots: [] }, null],
    ["add-ack", { ...T, type: "add-ack", ok: true }, { ...T, type: "add-ack", ok: true }],
    ["add-ack: a non-boolean ok is not ok", { ...T, type: "add-ack", ok: "yes" }, { ...T, type: "add-ack", ok: false }],
    ["claim", { type: "claim", tabId: "t", spawnToken: "s" }, { type: "claim", tabId: "t", spawnToken: "s" }],
    ["claim without token", { type: "claim", tabId: "t" }, null],
  ])("%s", (_name, x, want) => {
    expect(cleanGroupMessage(x)).toEqual(want);
  });
});

describe("cleanGroupTab", () => {
  const NOW = 1_000_000;
  const ok = { tabId: "t", heartbeat: NOW - 10, createdAt: 5, slots: [] };
  it.each<[string, unknown, unknown]>([
    ["garbage", "x", null],
    ["null", null, null],
    ["missing slots", { ...ok, slots: undefined }, null],
    ["non-array slots", { ...ok, slots: {} }, null],
    ["non-number heartbeat", { ...ok, heartbeat: "1" }, null],
    ["stale", { ...ok, heartbeat: NOW - GROUP_HEARTBEAT_TTL_MS - 1 }, null],
    ["live", ok, ok],
    ["non-number createdAt falls back to the heartbeat", { ...ok, createdAt: "5" }, { ...ok, createdAt: NOW - 10 }],
    ["missing createdAt falls back to the heartbeat", { ...ok, createdAt: undefined }, { ...ok, createdAt: NOW - 10 }],
    ["zero createdAt falls back to the heartbeat", { ...ok, createdAt: 0 }, { ...ok, createdAt: NOW - 10 }],
    ["Fansly slot stays a string, malformed dropped",
      { ...ok, slots: [{ accountId: "a", fanId: SNOW }, { accountId: "a", fanId: 1.5 }] },
      { ...ok, slots: [{ accountId: "a", fanId: SNOW }] }],
  ])("%s", (_name, x, want) => {
    expect(cleanGroupTab(x, NOW)).toEqual(want);
  });
});

describe("live group tab registry", () => {
  afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
  const register = (tabId: string, slots: unknown[]) => localStorage.setItem(GROUP_TAB_KEY_PREFIX + tabId,
    JSON.stringify({ tabId, createdAt: 1, heartbeat: Date.now(), slots }));

  it("keeps Fansly string slots and drops malformed ones", () => {
    register("t1", [{ accountId: "a", fanId: SNOW }, { accountId: "a", fanId: "abc" }, { accountId: "a", fanId: 5 }]);
    expect(readAllLiveGroupTabs()[0].slots).toEqual([{ accountId: "a", fanId: SNOW }, { accountId: "a", fanId: 5 }]);
  });

  // The fan is in a live tab under the other id shape: focus that tab, never
  // add him to a second one.
  it.each<[string, number | string, number | string]>([
    ["held as a string, clicked as a number", "123", 123],
    ["held as a number, clicked as a string", 123, "123"],
  ])("finds the owner tab across id shapes: %s", async (_name, held, clicked) => {
    register("owner", [{ accountId: "a", fanId: held }]);
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(await openGroupTab("a", clicked)).toEqual({ kind: "focused" });
    expect(window.open).not.toHaveBeenCalled();
  });
});

describe("parseSlotsParam", () => {
  it("parses acct:fan pairs in order", () => {
    expect(parseSlotsParam("acc1:123,acc2:456")).toEqual([
      { accountId: "acc1", fanId: 123 },
      { accountId: "acc2", fanId: 456 },
    ]);
  });

  it("keeps the newest slot when the same fan appears twice", () => {
    expect(parseSlotsParam("acc1:1,acc1:1,acc1:2")).toEqual([
      { accountId: "acc1", fanId: 1 },
      { accountId: "acc1", fanId: 2 },
    ]);
  });

  it("treats the same fan id on different accounts as distinct", () => {
    expect(parseSlotsParam("acc1:9,acc2:9")).toHaveLength(2);
  });

  it("caps at the group slot cap", () => {
    const raw = Array.from({ length: 20 }, (_, i) => `acc:${i + 1}`).join(",");
    expect(parseSlotsParam(raw)).toHaveLength(GROUP_SLOT_CAP);
  });

  it("drops malformed entries instead of throwing", () => {
    expect(parseSlotsParam("acc1:123,garbage,:5,acc2:0,acc3:-1,acc4:abc,acc5:7")).toEqual([
      { accountId: "acc1", fanId: 123 },
      { accountId: "acc5", fanId: 7 },
    ]);
  });

  it("round-trips an account id containing the separator", () => {
    // encodeSlots percent-encodes the account id, so a colon inside it must
    // survive — the parser splits on the LAST colon and decodes.
    expect(parseSlotsParam(`${encodeURIComponent("a:b")}:42`)).toEqual([
      { accountId: "a:b", fanId: 42 },
    ]);
  });

  it("returns nothing for an empty param", () => {
    expect(parseSlotsParam("")).toEqual([]);
  });
});
