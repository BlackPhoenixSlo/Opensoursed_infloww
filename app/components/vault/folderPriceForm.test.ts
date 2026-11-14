import { describe, expect, it } from "vitest";

import {
  buildPayload, canSave, folderPriceReducer, formatPrice, initForm, parseDollars,
} from "@/components/vault/folderPriceForm";

describe("parseDollars", () => {
  it.each([
    ["25", 2500], ["$25", 2500], [" 25 ", 2500], ["24.99", 2499], ["24.5", 2450], ["10", 1000], ["200", 20000],
    ["$ 70", 7000], ["9.99", null], ["200.01", null], ["0", null], ["", null], ["abc", null], ["25.999", null],
    ["-25", null], ["1e3", null], ["25,00", null], ["1000", null],
  ])("%j -> %j", (text, want) => {
    expect(parseDollars(text)).toBe(want);
  });
});

describe("formatPrice / initForm", () => {
  it.each([[2500, "$25"], [2499, "$24.99"], [2450, "$24.50"]])("%j -> %j", (c, want) => {
    expect(formatPrice(c)).toBe(want);
  });
  it("prefills the stored price, empty when unpriced", () => {
    expect(initForm(2450).text).toBe("24.50");
    expect(initForm(null)).toEqual({ text: "", busy: false, error: null });
  });
});

describe("folderPriceReducer + canSave", () => {
  it.each([
    // [current stored cents, typed text, canSave, why]
    [null, "25", true, "new price"],
    [null, "", false, "blank"],
    [null, "5", false, "under $10"],
    [2500, "25", false, "unchanged"],
    [2500, "25.00", false, "unchanged, other spelling"],
    [2500, "30", true, "changed"],
  ] as [number | null, string, boolean, string][])("%j %j -> %j (%s)", (current, text, want) => {
    const s = folderPriceReducer(initForm(current), { type: "edit", text });
    expect(canSave(s, current)).toBe(want);
  });
  it("saving locks Save; a failure unlocks and shows the error; typing clears it", () => {
    let s = folderPriceReducer(initForm(null), { type: "edit", text: "25" });
    s = folderPriceReducer(s, { type: "saving" });
    expect(s.busy).toBe(true);
    expect(canSave(s, null)).toBe(false);
    s = folderPriceReducer(s, { type: "failed", error: "Couldn't save" });
    expect(s).toEqual({ text: "25", busy: false, error: "Couldn't save" });
    expect(canSave(s, null)).toBe(true);
    expect(folderPriceReducer(s, { type: "edit", text: "26" }).error).toBeNull();
  });
});

describe("buildPayload", () => {
  it("Save posts the parsed cents; Clear posts null", () => {
    const s = folderPriceReducer(initForm(null), { type: "edit", text: "$24.99" });
    expect(buildPayload("a1", "of:7", s)).toEqual({ account_id: "a1", ref: "of:7", price_cents: 2499 });
    expect(buildPayload("a1", "of:7", null)).toEqual({ account_id: "a1", ref: "of:7", price_cents: null });
  });
});
