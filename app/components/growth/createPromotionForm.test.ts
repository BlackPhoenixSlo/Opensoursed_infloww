import { describe, expect, it } from "vitest";

import {
  blockReason, buildPayload, canSubmit, createPromotionReducer, INITIAL_CREATE, keepRunningOn, movedTo, preemptOn,
  preemptUsable, takeoverNotice, type Action, type CreatePromotionState,
} from "./createPromotionForm";
import { unresolvedId } from "@/lib/ofMirrorWrites";

const run = (actions: Action[], from: CreatePromotionState = INITIAL_CREATE) => actions.reduce(createPromotionReducer, from);

describe("createPromotionReducer", () => {
  it("starts with Keep running untouched, Re-create at 90% filled ticked, a Re-create limit of 3, OF's defaults, no name, no error", () => {
    expect(INITIAL_CREATE).toMatchObject({
      name: "", keepRunning: null, preempt: true, recreateLimit: 3, takenFrom: null, err: null, form: { kind: "trial", limit: 10, expiration: 7 },
    });
  });

  it.each<[string, Action[], Partial<CreatePromotionState>]>([
    ["name", [{ type: "name", value: "Week" }], { name: "Week" }],
    ["keep running off", [{ type: "keepRunning", on: false }], { keepRunning: false }],
    ["keep running back on", [{ type: "keepRunning", on: false }, { type: "keepRunning", on: true }], { keepRunning: true }],
    ["recreate limit", [{ type: "recreateLimit", value: 7 }], { recreateLimit: 7 }],
    ["re-create at 90% filled off", [{ type: "preempt", on: false }], { preempt: false }],
    ["re-create at 90% filled back on", [{ type: "preempt", on: false }, { type: "preempt", on: true }], { preempt: true }],
    ["taken from loaded", [{ type: "takenFromLoaded", kept: { id: 4, name: "Old" } }], { takenFrom: { id: 4, name: "Old" } }],
    ["taken from cleared", [{ type: "takenFromLoaded", kept: { id: 4, name: "Old" } }, { type: "takenFromLoaded", kept: null }],
      { takenFrom: null }],
    ["failed sets the error", [{ type: "failed", err: "boom" }], { err: "boom" }],
    ["clear drops it", [{ type: "failed", err: "boom" }, { type: "clear" }], { err: null }],
    ["unresolved keeps the row id and the relay's line", [{ type: "unresolved", id: 7, err: "earlier create" }],
      { err: "earlier create", unresolved: 7 }],
    ["another failure drops the row id", [{ type: "unresolved", id: 7, err: "x" }, { type: "failed", err: "boom" }],
      { err: "boom", unresolved: null }],
    ["clear drops both", [{ type: "unresolved", id: 7, err: "x" }, { type: "clear" }], { err: null, unresolved: null }],
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

  it("the same Kept campaign loaded again keeps the same state object", () => {
    const s = run([{ type: "takenFromLoaded", kept: { id: 4, name: "Old" } }]);
    expect(createPromotionReducer(s, { type: "takenFromLoaded", kept: { id: 4, name: "Old" } })).toBe(s);
  });
});

describe("keepRunningOn", () => {
  it.each<[string, Action[], boolean]>([
    ["trial default keep off", [], false],
    ["discount default keep on", [{ type: "edit", patch: { kind: "discount" } }], true],
    ["trial ticked", [{ type: "keepRunning", on: true }], true],
    ["discount unticked", [{ type: "edit", patch: { kind: "discount" } }, { type: "keepRunning", on: false }], false],
    ["a touched tick survives the kind switch", [{ type: "keepRunning", on: true }, { type: "edit", patch: { kind: "discount" } },
      { type: "edit", patch: { kind: "trial" } }], true],
  ])("%s", (_name, actions, want) => {
    expect(keepRunningOn(run(actions))).toBe(want);
  });
});

describe("preemptUsable", () => {
  // A cap under 10 or unlimited (0) never pre-empts: it re-creates after it ends.
  it.each<[number, boolean]>([[0, false], [1, false], [9, false], [10, true], [11, true], [50, true], [100, true]])(
    "cap %i -> %s", (cap, want) => {
      expect(preemptUsable(cap)).toBe(want);
    });
});

describe("preemptOn", () => {
  const discount: Action = { type: "edit", patch: { kind: "discount" } };
  it.each<[string, Action[], boolean]>([
    ["discount kept, cap 10, ticked by default", [discount], true],
    ["discount kept, unticked", [discount, { type: "preempt", on: false }], false],
    ["discount not kept", [discount, { type: "keepRunning", on: false }], false],
    ["discount kept, cap 5", [discount, { type: "edit", patch: { limit: 5 } }], false],
    ["discount kept, unlimited", [discount, { type: "edit", patch: { limit: 0 } }], false],
    ["cap back to 50 keeps the tick", [discount, { type: "edit", patch: { limit: 5 } }, { type: "edit", patch: { limit: 50 } }], true],
    ["trial default: keep off", [], false],
    ["trial kept, cap 10", [{ type: "keepRunning", on: true }], true],
  ])("%s", (_name, actions, want) => {
    expect(preemptOn(run(actions))).toBe(want);
  });

  it("never blocks Create", () => {
    const s = run([{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount", limit: 5 } }, { type: "preempt", on: false }]);
    expect(canSubmit(s)).toBe(true);
  });
});

describe("canSubmit", () => {
  it.each<[string, boolean]>([["", false], ["   ", false], ["Week", true], ["  Week ", true]])("name %j -> %s", (name, want) => {
    expect(canSubmit({ ...INITIAL_CREATE, name })).toBe(want);
  });

  const named: Action = { type: "name", value: "W" };
  const keep: Action = { type: "keepRunning", on: true };
  it.each<[string, Action[], string | null]>([
    ["trial kept, cap 10, limit 3", [named, keep], null],
    ["trial kept, unlimited claims", [named, keep, { type: "edit", patch: { limit: 0 } }],
      "A free trial with unlimited claims can't keep running — set an Offer limit first."],
    ["trial kept, limit 0", [named, keep, { type: "recreateLimit", value: 0 }], "The Re-create limit is 1-10."],
    ["trial kept, limit 11", [named, keep, { type: "recreateLimit", value: 11 }], "The Re-create limit is 1-10."],
    ["trial kept, limit 10", [named, keep, { type: "recreateLimit", value: 10 }], null],
    ["trial not kept, unlimited claims", [named, { type: "edit", patch: { limit: 0 } }], null],
    ["discount kept, unlimited claims, limit 0",
      [named, { type: "edit", patch: { kind: "discount", limit: 0 } }, { type: "recreateLimit", value: 0 }], null],
  ])("%s", (_name, actions, want) => {
    const s = run(actions);
    expect(blockReason(s)).toBe(want);
    expect(canSubmit(s)).toBe(want === null);
  });
});

describe("takeoverNotice", () => {
  it.each<[string | null | undefined, string | null]>([
    ["Old week", "Keep running moves from “Old week” to this promotion."],
    [null, null],
    [undefined, null],
    ["", null],
  ])("%j -> %j", (name, want) => {
    expect(takeoverNotice(name)).toBe(want);
  });
});

describe("buildPayload", () => {
  it.each<[string, Action[], Record<string, unknown>]>([
    ["defaults: a 7-day free trial, Keep running off", [{ type: "name", value: " Week " }],
      { name: "Week", discount: 100, subscribe_counts: 10, subscribe_days: 7, finish_days: 7, message: "", promo_type: ["all"], auto_reactivate: false }],
    ["keep running unticked", [{ type: "name", value: "W" }, { type: "keepRunning", on: false }], { auto_reactivate: false }],
    ["a discount keeps running by default", [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount", percent: 30 } }],
      { auto_reactivate: true, expect_taken_from: null }],
    ["a trial ticked sends its Re-create limit and the Kept campaign shown",
      [{ type: "name", value: "W" }, { type: "keepRunning", on: true }, { type: "recreateLimit", value: 5 },
        { type: "takenFromLoaded", kept: { id: 4, name: "Old" } }],
      { auto_reactivate: true, recreate_limit: 5, expect_taken_from: 4 }],
    ["a discount kept sends Re-create at 90% filled on", [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount" } }],
      { auto_reactivate: true, preempt: true }],
    ["a discount kept, second tick off", [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount" } },
      { type: "preempt", on: false }], { auto_reactivate: true, preempt: false }],
    ["a discount kept, cap 5: never pre-empts", [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount", limit: 5 } }],
      { auto_reactivate: true, preempt: false }],
    ["discount lasts its expiration; both audiences; message trimmed",
      [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount", percent: 30, expiration: 14, audience: "both", message: " hi " } }],
      { discount: 30, subscribe_days: 14, finish_days: 14, promo_type: ["all", "expired"], message: "hi" }],
  ])("%s", (_name, actions, want) => {
    expect(buildPayload(run(actions))).toMatchObject(want);
  });

  it.each<[string, Action[], string[]]>([
    ["keep off: no limit, no expectation, no second tick",
      [{ type: "name", value: "W" }, { type: "takenFromLoaded", kept: { id: 4, name: "Old" } }],
      ["recreate_limit", "expect_taken_from", "preempt"]],
    ["a discount unticked: no second tick",
      [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount" } }, { type: "keepRunning", on: false }], ["preempt"]],
    ["a discount kept: no Re-create limit", [{ type: "name", value: "W" }, { type: "edit", patch: { kind: "discount" } }],
      ["recreate_limit"]],
  ])("%s", (_name, actions, absent) => {
    const body = buildPayload(run(actions));
    for (const k of absent) expect(body).not.toHaveProperty(k);
  });
});

describe("create anyway", () => {
  const open = run([{ type: "name", value: "W" }, { type: "unresolved", id: 7, err: "x" }]);
  it.each<[string, CreatePromotionState, boolean, number | undefined]>([
    ["a plain create never clears", open, false, undefined],
    ["create anyway names the row", open, true, 7],
    ["nothing unresolved: nothing to clear", run([{ type: "name", value: "W" }]), true, undefined],
  ])("%s", (_name, s, resolve, want) => {
    expect(buildPayload(s, resolve).resolve_open).toBe(want);
  });

  it.each<[string, unknown, number | null]>([
    ["create_unresolved", { detail: { reason: "create_unresolved", id: 7, message: "m" } }, 7],
    ["create_in_flight", { detail: { reason: "create_in_flight", message: "m" } }, null],
    ["a string detail", { detail: "boom" }, null],
    ["no body", null, null],
  ])("unresolvedId: %s", (_name, body, want) => {
    expect(unresolvedId(body)).toBe(want);
  });

  it.each<[string, unknown, ReturnType<typeof movedTo>]>([
    ["moved to another", { detail: { reason: "keep_running_moved", taken_from: { id: 5, name: "New" }, message: "m" } },
      { kept: { id: 5, name: "New" } }],
    ["moved to none", { detail: { reason: "keep_running_moved", taken_from: null, message: "m" } }, { kept: null }],
    ["another 409", { detail: { reason: "create_unresolved", id: 7 } }, undefined],
    ["no body", null, undefined],
  ])("movedTo: %s", (_name, body, want) => {
    expect(movedTo(body)).toEqual(want);
  });
});
