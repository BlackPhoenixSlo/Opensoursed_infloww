import { describe, expect, it } from "vitest";

import { attributionAsks, LAG_MS, noteAsks, SKEW_MS, type Asked } from "./attributionRefresh";

const T = Date.parse("2026-11-06T12:00:00Z");
const iso = (ms: number) => new Date(ms).toISOString();
const me = 7;
const out = (id: unknown, at: number, extra: object = {}) => ({ id, fromUser: { id: me }, createdAt: iso(at), ...extra });
const none: Asked = new Map();
const once = (firstAt: number): Asked => new Map([["10", { firstAt, times: 1 }]]);

describe("attributionAsks", () => {
  it.each([
    ["teammate send after the map", [out(10, T + 1000)], {}, none, ["10"]],
    ["in the map", [out(10, T + 1000)], { 10: {} }, none, []],
    ["old OF-only outbound (never recorded)", [out(10, T - SKEW_MS - 1)], {}, none, []],
    ["inside the skew margin", [out(10, T - SKEW_MS + 1)], {}, none, ["10"]],
    ["asked once, its re-read long after the send", [out(10, T - LAG_MS - 1)], {}, once(T - 10), []],
    ["inbound", [{ id: 10, fromUser: { id: 8 }, createdAt: iso(T + 1000) }], {}, none, []],
    ["optimistic temp", [out(10, T + 1000, { _tempId: -1 })], {}, none, []],
    ["no/zero id", [out(null, T + 1000), out("0", T + 1000)], {}, none, []],
    ["no createdAt", [{ id: 10, fromUser: { id: me } }], {}, none, []],
    ["Fansly snowflake text id", [out("731234567890123456789", T + 1000)], {}, none, ["731234567890123456789"]],
  ])("%s", (_name, msgs, map, asked, want) => {
    expect(attributionAsks(msgs, me, map, T, asked, T + 60_000).ask).toEqual(want);
  });

  // The relay may not have written a just-sent message's attribution when the first re-read lands.
  describe("a second ask, when the first re-read landed too soon", () => {
    const sent = T - 1000; // the map (fetchedAt T) landed 1 s after the send
    it("not before LAG_MS after the send: look again then", () => {
      expect(attributionAsks([out(10, sent)], me, {}, T, once(T - 50), T + 100)).toEqual({ ask: [], recheckAt: sent + LAG_MS });
    });
    it("once LAG_MS passed: asked again", () => {
      expect(attributionAsks([out(10, sent)], me, {}, T, once(T - 50), sent + LAG_MS)).toEqual({ ask: ["10"], recheckAt: null });
    });
    it("not while the first re-read is still out (the map predates the ask)", () => {
      expect(attributionAsks([out(10, sent)], me, {}, T, once(T + 10), sent + LAG_MS).ask).toEqual([]);
    });
    it("never a third time", () => {
      const asked: Asked = new Map([["10", { firstAt: T - 50, times: 2 }]]);
      expect(attributionAsks([out(10, sent)], me, {}, T, asked, sent + LAG_MS)).toEqual({ ask: [], recheckAt: null });
    });
  });
});

describe("noteAsks", () => {
  it("keeps the first ask's time and counts", () => {
    const asked: Asked = new Map();
    noteAsks(asked, ["10"], 1);
    noteAsks(asked, ["10"], 2);
    expect(asked.get("10")).toEqual({ firstAt: 1, times: 2 });
  });
});
