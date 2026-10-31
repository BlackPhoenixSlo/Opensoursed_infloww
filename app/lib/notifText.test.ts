import { afterEach, describe, expect, it, vi } from "vitest";

import { MONEY_ROWS_CAP, MONEY_TYPES, fmtTime, isMoney, labelFor, moneyListKey, notifPath, parseList, renderText, stickerFor } from "@/lib/notifText";

describe("renderText", () => {
  const html = 'Hi <a href="x">{NAME}</a><b>sent</b>  you   a <i>$5</i> tip';
  const pairs = { "{NAME}": "Jim" };
  it.each([
    // [tagSep, expected] — the bell drops tags, the toaster and rail space them.
    ["", "Hi Jimsent you a $5 tip"],
    [" ", "Hi Jim sent you a $5 tip"],
  ])("tagSep %j", (sep, want) => {
    expect(renderText(html, pairs, sep)).toBe(want);
  });
  it("defaults to the spaced form", () => {
    expect(renderText(html, pairs)).toBe("Hi Jim sent you a $5 tip");
  });
  it("replaces every occurrence of a pair and trims", () => {
    expect(renderText("  {A} and {A} ", { "{A}": "x" })).toBe("x and x");
    expect(renderText("")).toBe("");
  });
});

describe("fmtTime", () => {
  afterEach(() => { vi.useRealTimers(); });
  const now = Date.parse("2026-10-31T12:00:00Z");
  it.each([
    [undefined, ""],
    ["not a date", ""],
    ["2026-10-31T11:59:30Z", "30s ago"],
    ["2026-10-31T11:55:00Z", "5m ago"],
    ["2026-10-31T09:00:00Z", "3h ago"],
    ["2026-10-02T12:00:00Z", "29d ago"],
  ])("%s → %j", (iso, want) => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
    expect(fmtTime(iso)).toBe(want);
  });
  it("past 30 days is the date", () => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
    const iso = "2026-09-01T12:00:00Z";
    expect(fmtTime(iso)).toBe(new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" }));
  });
});

describe("notifPath / parseList", () => {
  it.each([
    [null, 0, "/api/of/v2/users/notifications?limit=20&offset=0"],
    ["purchases", 0, "/api/of/v2/users/notifications?limit=20&offset=0&type=purchases"],
    ["tip", 40, "/api/of/v2/users/notifications?limit=20&offset=40&type=tip"],
  ])("notifPath(%j, %j)", (type, offset, want) => {
    expect(notifPath(type, offset)).toBe(want);
  });
  it.each([
    [[{ id: 1 }], [{ id: 1 }]],
    [{ list: [{ id: 2 }] }, [{ id: 2 }]],
    [{ list: "no" }, []],
    [null, []],
    ["x", []],
  ])("parseList(%j)", (raw, want) => {
    expect(parseList(raw)).toEqual(want);
  });
});

describe("stickerFor / labelFor", () => {
  it.each([
    ["message", "💬", "New message"],
    ["purchases", "💰", "Purchase"],
    ["tip", "💸", "Tip received"],
    ["subscribed", "⭐", "New subscriber"],
    ["mentioned", "@", "Mentioned you"],
    ["commented", "💭", "Commented"],
    ["favorited", "♡", "Liked"],
  ] as const)("%s", (k, sticker, label) => {
    expect(stickerFor(k)).toBe(sticker);
    expect(labelFor(k, "raw")).toBe(label);
  });
  it("an unknown type keeps OF's raw type, else a generic label", () => {
    expect(stickerFor(null)).toBe("🔔");
    expect(labelFor(null, "Shift reminder")).toBe("Shift reminder");
    expect(labelFor(null, "")).toBe("Notification");
  });
});

describe("money types", () => {
  it.each([
    ["tip", true, ["notif-list", "acc", "tip"]],
    ["purchases", true, ["notif-list", "acc", "purchases"]],
    ["message", false, null],
    [null, false, null],
  ] as const)("%s", (k, money, key) => {
    expect(isMoney(k)).toBe(money);
    expect(moneyListKey("acc", k)).toEqual(key);
  });
  it("MONEY_TYPES is exactly the money keys; the cap is 50", () => {
    expect([...MONEY_TYPES].sort()).toEqual(["purchases", "tip"]);
    expect(MONEY_ROWS_CAP).toBe(50);
  });
});
