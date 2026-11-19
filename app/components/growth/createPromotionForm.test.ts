import { describe, expect, it } from "vitest";

import {
  buildPayload, canSubmit, createPromotionReducer, INITIAL_CREATE, type Action, type CreatePromotionState,
} from "./createPromotionForm";

const run = (actions: Action[], from: CreatePromotionState = INITIAL_CREATE) => actions.reduce(createPromotionReducer, from);

describe("createPromotionReducer", () => {
  it("starts with Keep running on, OF's defaults, no name, no error", () => {
    expect(INITIAL_CREATE).toMatchObject({ name: "", keepRunning: true, err: null, form: { kind: "trial", limit: 10, expiration: 7 } });
  });

  it.each<[string, Action[], Partial<CreatePromotionState>]>([
    ["name", [{ type: "name", value: "Week" }], { name: "Week" }],
    ["keep running off", [{ type: "keepRunning", on: false }], { keepRunning: false }],
    ["keep running back on", [{ type: "keepRunning", on: false }, { type: "keepRunning", on: true }], { keepRunning: true }],
    ["failed sets the error", [{ type: "failed", err: "boom" }], { err: "boom" }],
    ["clear drops it", [{ type: "failed", err: "boom" }, { type: "clear" }], { err: null }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });

  it("edit merges into the OF fields and keeps the rest", () => {
    const s = run([{ type: "edit", patch: { kind: "discount", percent: 20 } }, { type: "edit", patch: { limit: 0 } }]);
    expect(s.form).toMatchObject({ kind: "discount", percent: 20, limit: 0, expiration: 7 });
  });

  it("clear with no error keeps the same state object", () => {
    expect(createPromotionReducer(INITIAL_CREATE, { type: "clear" })).toBe(INITIAL_CREATE);
  });
});

describe("canSubmit", () => {
  it.each<[string, boolean]>([["", false], ["   ", false], ["Week", true], ["  Week ", true]])("name %j -> %s", (name, want) => {
    expect(canSubmit({ ...INITIAL_CREATE, name })).toBe(want);
  });
});

describe("buildPayload", () => {
  it.each<[string, Action[], Record<string, unknown>]>([
    ["defaults: a 7-day free trial that keeps running", [{ type: "name", value: " Week " }],
      { name: "Week", discount: 100, subscribe_counts: 10, subscribe_days: 7, finish_days: 7, message: "", promo_type: ["all"], auto_reactivate: true }],
    ["keep running unticked", [{ type: "name", value: "W" }, { type: "keepRunning", on: false }], { auto_reactivate: false }],
    ["discount lasts its expiration; both audiences; message trimmed",
      [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount", percent: 30, expiration: 14, audience: "both", message: " hi " } }],
      { discount: 30, subscribe_days: 14, finish_days: 14, promo_type: ["all", "expired"], message: "hi" }],
  ])("%s", (_name, actions, want) => {
    expect(buildPayload(run(actions))).toMatchObject(want);
  });
});
