import { describe, expect, it } from "vitest";

import { canSaveCap, capError, centsToDollars, dollarsToCents, MAX_CAP_CENTS, providerName, spentText } from "./aiSpendCap";

describe("dollarsToCents", () => {
  it.each<[string, number | null]>([
    ["1", 100], ["1.5", 150], ["2.50", 250], ["0", 0], ["0.00", 0], [".5", 50], ["$3", 300],
    [" 12.34 ", 1234], ["100", 10_000], ["0.07", 7], ["1.", 100],
    ["1.234", null], ["", null], ["abc", null], ["-1", null], ["1e2", null], ["1,50", null], [".", null],
  ])("%j -> %j", (raw, want) => {
    expect(dollarsToCents(raw)).toBe(want);
  });
});

describe("centsToDollars", () => {
  it.each<[number, string]>([[100, "1.00"], [1250, "12.50"], [0, "0.00"], [7, "0.07"]])("%d -> %s", (c, want) => {
    expect(centsToDollars(c)).toBe(want);
  });
  it("round-trips through the box", () => {
    for (const c of [0, 1, 99, 100, 1234, MAX_CAP_CENTS]) expect(dollarsToCents(centsToDollars(c))).toBe(c);
  });
});

describe("capError / canSaveCap", () => {
  it.each<[string, number, string | null, boolean]>([
    ["5", 100, null, true],
    ["1.00", 100, null, false],                         // unchanged
    ["0", 100, null, true],                             // pause
    ["100", 100, null, true],                           // the bound itself
    ["100.01", 100, "At most $100.00 a day", false],
    ["500", 50_000, null, false],                       // a legacy cap echoed, unchanged
    ["499", 50_000, "At most $100.00 a day", false],    // an edit of it is bounded
    ["2.555", 100, "Enter a dollar amount, e.g. 5 or 2.50", false],
    ["", 100, "Enter a dollar amount, e.g. 5 or 2.50", false],
  ])("%j (stored %d)", (raw, stored, err, ok) => {
    expect(capError(raw, stored)).toBe(err);
    expect(canSaveCap(raw, stored)).toBe(ok);
  });
});

describe("spentText / providerName", () => {
  it.each<[number, string]>([[0, "$0.00"], [1, "<$0.01"], [99, "<$0.01"], [100, "$0.01"], [4200, "$0.42"],
    [10_000, "$1.00"]])("%d millicents -> %s", (mc, want) => {
    expect(spentText(mc)).toBe(want);
  });
  it("names known providers and keeps an unknown id", () => {
    expect(providerName("deepseek")).toBe("DeepSeek");
    expect(providerName("deepinfra")).toBe("DeepInfra");
    expect(providerName("newco")).toBe("newco");
  });
});
