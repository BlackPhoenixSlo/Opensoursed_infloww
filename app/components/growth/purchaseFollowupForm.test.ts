import { describe, expect, it } from "vitest";

import type { PurchaseFollowupConfig } from "@/hooks/usePurchaseFollowupConfig";

import {
  buildPayload, canSubmit, initPurchase, purchaseIssues, purchaseReducer, type PurchaseAction,
} from "./purchaseFollowupForm";

const TEMPLATE = "Thanks!";
const CONFIG: PurchaseFollowupConfig = {
  enabled: false, text: "", media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0,
  frequency: "once", delay_range: [3, 7],
};
const run = (actions: PurchaseAction[], over: Partial<PurchaseFollowupConfig> = {}) =>
  actions.reduce(purchaseReducer, initPurchase({ ...CONFIG, ...over }, TEMPLATE));
const EXTRAS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0, frequency: "once" };

// Same input → the body the old inline onSubmit built (HEAD PurchaseFollowupEditor.tsx):
// { enabled, text: text.trim(), ...collectExtras(extras, { delay: true, frequency: true, initial: opened }) }.
describe("buildPayload pins the old inline save", () => {
  it.each<[string, PurchaseAction[], Partial<PurchaseFollowupConfig>, unknown]>([
    ["untouched: the template, the delay row left out (the Relay keeps it)", [], {},
      { enabled: false, text: TEMPLATE, ...EXTRAS }],
    ["saved text, trimmed; on", [{ type: "setText", text: "  hi {name} " }, { type: "setEnabled", on: true }], { text: "old" },
      { enabled: true, text: "hi {name}", ...EXTRAS }],
    ["a new delay range is sent", [{ type: "patchExtras", patch: { delayA: "10", delayB: "20" } }], {},
      { enabled: false, text: TEMPLATE, ...EXTRAS, delay_range: [10, 20] }],
    ["delay switched to immediately: null", [{ type: "patchExtras", patch: { delayOn: false } }], {},
      { enabled: false, text: TEMPLATE, ...EXTRAS, delay_range: null }],
    ["off with no text still saves", [{ type: "setText", text: "  " }], {},
      { enabled: false, text: "", ...EXTRAS }],
  ])("%s", (_, actions, over, body) => {
    const s = run(actions, over);
    expect(canSubmit(s)).toBe(true);
    expect(buildPayload(s)).toEqual(body);
  });
});

describe("one gate: purchaseIssues / canSubmit / buildPayload agree", () => {
  it.each<[string, PurchaseAction[], Partial<ReturnType<typeof purchaseIssues>>]>([
    ["on with no text", [{ type: "setEnabled", on: true }, { type: "setText", text: " " }], { missingText: true }],
    ["a price without media", [{ type: "patchExtras", patch: { price: "5" } }], { problem: "Add media to set a price" }],
  ])("%s", (_, actions, flagged) => {
    const s = run(actions);
    expect(purchaseIssues(s)).toMatchObject(flagged);
    expect(canSubmit(s)).toBe(false);
    expect(buildPayload(s)).toBeNull();
  });
  it("opened never moves with an edit", () => {
    const s = run([{ type: "patchExtras", patch: { delayA: "9" } }]);
    expect(s.opened.delayA).toBe("3");
  });
});
