import { beforeEach, describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import type { GroupSlot } from "@/lib/groupChannel";
import type { OFChatItem } from "@/lib/relay";
import {
  CREATED_AT_KEY, LAST_BEAT_KEY, SLOTS_KEY, TAB_ID_KEY, countUnresponded, isStaleReload, olderTabs, parseSeedParams,
  readLastBeat, readSlots, resolveCreatedAt, resolveTabId, takeSeedParams, writeLastBeat, writeSlots,
} from "./groupTabStorage";
import { GROUP_HEARTBEAT_TTL_MS } from "@/lib/groupChannel";

const A = "100000001";
const SNOW = "900234567890123456"; // a Fansly snowflake: past 2^53, string only
const s = (fanId: number | string, accountId = A): GroupSlot => ({ accountId, fanId });

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/group");
});

describe("parseSeedParams", () => {
  it.each<[string, GroupSlot[], string | null, string | null]>([
    ["/group", [], null, null],
    ["/group?x=1#h", [], null, null],
    [`/group?add=${A}:5`, [s(5)], null, "/group"],
    [`/group?add=${A}:${SNOW}&spawn=tok`, [s(SNOW)], "tok", "/group"],
    [`/group?slots=${A}:1,${A}:2&x=1#h`, [s(1), s(2)], null, "/group?x=1#h"],
    [`/group?add=${A}:abc`, [], null, "/group"],
    ["/group?add=:5", [], null, "/group"],
    ["/group?spawn=tok", [], "tok", "/group"],
  ])("%s", (path, seeds, spawnToken, rest) => {
    expect(parseSeedParams(`http://x${path}`)).toEqual({ seeds, spawnToken, rest });
  });
});

describe("takeSeedParams: consumed once", () => {
  it.each<[string, GroupSlot[], string]>([
    [`/group?add=${A}:7&spawn=t`, [s(7)], "/group"],
    [`/group?slots=${A}:1,${A}:${SNOW}&keep=1`, [s(1), s(SNOW)], "/group?keep=1"],
  ])("%s", (path, seeds, after) => {
    window.history.replaceState(null, "", path);
    expect(takeSeedParams().seeds).toEqual(seeds);
    expect(window.location.pathname + window.location.search).toBe(after);
    // A reload (or StrictMode's second mount) sees no params: nothing re-seeds.
    expect(takeSeedParams()).toEqual({ seeds: [], spawnToken: null, fresh: false });
  });
});

describe("resolveTabId", () => {
  it("is stable across a reload and kept in sessionStorage", () => {
    const id = resolveTabId(false);
    expect(id).not.toBe("");
    expect(resolveTabId(false)).toBe(id);
    expect(sessionStorage.getItem(TAB_ID_KEY)).toBe(id);
  });
  it.each<[string, string | null, boolean, boolean]>([
    ["a reload re-uses the stored id", "t1", false, true],
    ["a fresh tab (seed params) mints a new id over a copied one", "t1", true, false],
    ["a fresh tab with nothing stored mints one", null, true, false],
  ])("%s", (_name, stored, fresh, same) => {
    if (stored !== null) sessionStorage.setItem(TAB_ID_KEY, stored);
    const id = resolveTabId(fresh);
    expect(id === stored).toBe(same);
    expect(id).not.toBe("");
    // Whatever it answered is what the next reload answers.
    expect(resolveTabId(false)).toBe(id);
  });
});

describe("olderTabs: who a shared fan stays with", () => {
  const me = { tabId: "m", createdAt: 2000 };
  it.each<[string, { tabId: string; createdAt: number }[], string[]]>([
    ["none live", [], []],
    ["an older tab", [{ tabId: "o", createdAt: 1000 }], ["o"]],
    ["a younger tab", [{ tabId: "y", createdAt: 3000 }], []],
    ["itself", [{ tabId: "m", createdAt: 1000 }], []],
    ["a tie: the smaller tab id is older", [{ tabId: "a", createdAt: 2000 }, { tabId: "z", createdAt: 2000 }], ["a"]],
    ["mixed, order kept", [{ tabId: "o2", createdAt: 1500 }, { tabId: "y", createdAt: 9000 }, { tabId: "o1", createdAt: 1 }],
      ["o2", "o1"]],
  ])("%s", (_name, tabs, want) => {
    expect(olderTabs(tabs, me).map((t) => t.tabId)).toEqual(want);
  });
  it("is one-sided: of two tabs, exactly one is older", () => {
    for (const [a, b] of [[1, 2], [2, 2], [3, 2]]) {
      const x = { tabId: "x", createdAt: a }, y = { tabId: "y", createdAt: b };
      expect(olderTabs([y], x).length + olderTabs([x], y).length).toBe(1);
    }
  });
});

describe("resolveCreatedAt", () => {
  it.each<[string, string | null, boolean, number]>([
    ["first mount stamps now", null, false, 2000],
    ["a reload keeps the stored age", "1000", false, 1000],
    ["a fresh tab (seed params) is newer even over a copied value", "1000", true, 2000],
    ["garbage stored value stamps now", "abc", false, 2000],
    ["zero stamps now", "0", false, 2000],
    ["negative stamps now", "-5", false, 2000],
  ])("%s", (_name, stored, fresh, want) => {
    if (stored !== null) sessionStorage.setItem(CREATED_AT_KEY, stored);
    expect(resolveCreatedAt(fresh, 2000)).toBe(want);
    // Whatever it answered is what the next reload answers.
    expect(resolveCreatedAt(false, 3000)).toBe(want);
  });
});

describe("isStaleReload: a reload past the registry TTL since the last beat", () => {
  const now = 100_000;
  it.each<[string, number | null, boolean]>([
    ["no beat recorded keeps the age", null, false],
    ["a quick reload keeps the age", now - 1000, false],
    ["exactly the TTL keeps the age", now - GROUP_HEARTBEAT_TTL_MS, false],
    ["past the TTL is reborn young", now - GROUP_HEARTBEAT_TTL_MS - 1, true],
    ["a minute hidden is reborn young", now - 60_000, true],
  ])("%s", (_name, lastBeat, want) => {
    expect(isStaleReload(lastBeat, now)).toBe(want);
  });
});

describe("readLastBeat / writeLastBeat", () => {
  it.each<[string, string | null, number | null]>([
    ["nothing stored", null, null],
    ["a beat", "5000", 5000],
    ["garbage", "abc", null],
    ["zero", "0", null],
    ["negative", "-5", null],
  ])("%s", (_name, stored, want) => {
    if (stored !== null) sessionStorage.setItem(LAST_BEAT_KEY, stored);
    expect(readLastBeat()).toBe(want);
  });
  it("round-trips", () => {
    writeLastBeat(7000);
    expect(readLastBeat()).toBe(7000);
  });
});

describe("readSlots / writeSlots", () => {
  it.each<[string, string | null, GroupSlot[]]>([
    ["nothing stored", null, []],
    ["garbage", "{nope", []],
    ["not an array", JSON.stringify({ a: 1 }), []],
    ["keeps Fansly strings, drops malformed and extra fields",
      JSON.stringify([{ accountId: A, fanId: 1, x: 2 }, { accountId: A, fanId: SNOW }, { accountId: A, fanId: "abc" }, null]),
      [s(1), s(SNOW)]],
  ])("%s", (_name, raw, want) => {
    if (raw !== null) sessionStorage.setItem(SLOTS_KEY, raw);
    expect(readSlots()).toEqual(want);
  });
  it("round-trips", () => {
    writeSlots([s(1), s(SNOW)]);
    expect(readSlots()).toEqual([s(1), s(SNOW)]);
  });
});

describe("countUnresponded", () => {
  const row = (fanId: number | string, fromId: number | string | null, accountId = A) => ({
    withUser: { id: fanId }, __accountId: accountId,
    lastMessage: fromId === null ? undefined : { id: 1, fromUser: { id: fromId } },
  }) as unknown as OFChatItem;
  it.each<[string, GroupSlot[], OFChatItem[][], number]>([
    ["no slots", [], [[row(1, 1)]], 0],
    ["the fan wrote last", [s(1)], [[row(1, 1)]], 1],
    ["the Creator answered", [s(1)], [[row(1, A)]], 0],
    ["the Creator answered as a number id", [s(1)], [[row(1, Number(A))]], 0],
    ["no cached row", [s(2)], [[row(1, 1)]], 0],
    ["no last message", [s(1)], [[row(1, null)]], 0],
    ["another account's row does not count", [s(1)], [[row(1, 1, "999")]], 0],
    ["Fansly string ids", [s(SNOW)], [[row(SNOW, SNOW)]], 1],
    ["the first cached copy wins", [s(1)], [[row(1, A)], [row(1, 1)]], 0],
    ["two of three", [s(1), s(2), s(3)], [[row(1, 1), row(2, A), row(3, 3)]], 2],
  ])("%s", (_name, slots, caches, want) => {
    const qc = new QueryClient();
    caches.forEach((rows, i) => qc.setQueryData(["chats", "k", i], { pages: [{ rows }], pageParams: [0] }));
    expect(countUnresponded(qc, slots)).toBe(want);
  });
});
