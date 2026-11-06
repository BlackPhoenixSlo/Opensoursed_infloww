import { describe, expect, it } from "vitest";

import { attributionAsks, SKEW_MS } from "./attributionRefresh";

const T = Date.parse("2026-11-06T12:00:00Z");
const iso = (ms: number) => new Date(ms).toISOString();
const me = 7;
const out = (id: unknown, at: number, extra: object = {}) => ({ id, fromUser: { id: me }, createdAt: iso(at), ...extra });

describe("attributionAsks", () => {
  it.each([
    ["teammate send after the map", [out(10, T + 1000)], {}, new Set<string>(), ["10"]],
    ["in the map", [out(10, T + 1000)], { 10: {} }, new Set<string>(), []],
    ["old OF-only outbound (never recorded)", [out(10, T - SKEW_MS - 1)], {}, new Set<string>(), []],
    ["inside the skew margin", [out(10, T - SKEW_MS + 1)], {}, new Set<string>(), ["10"]],
    ["asked once already", [out(10, T + 1000)], {}, new Set(["10"]), []],
    ["inbound", [{ id: 10, fromUser: { id: 8 }, createdAt: iso(T + 1000) }], {}, new Set<string>(), []],
    ["optimistic temp", [out(10, T + 1000, { _tempId: -1 })], {}, new Set<string>(), []],
    ["no/zero id", [out(null, T + 1000), out("0", T + 1000)], {}, new Set<string>(), []],
    ["no createdAt", [{ id: 10, fromUser: { id: me } }], {}, new Set<string>(), []],
    ["Fansly snowflake text id", [out("731234567890123456789", T + 1000)], {}, new Set<string>(), ["731234567890123456789"]],
  ])("%s", (_name, msgs, map, asked, want) => {
    expect(attributionAsks(msgs, me, map, T, asked)).toEqual(want);
  });
});
