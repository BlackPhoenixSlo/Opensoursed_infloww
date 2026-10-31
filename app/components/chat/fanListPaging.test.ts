import { describe, expect, it } from "vitest";

import {
  AUTOFILL_MAX_BURSTS, ROW_RENDER_STEP, SCROLL_CAP_STEP, canAutofill, initialPaging, isCapped,
  pagingReducer, pagingView, type PagingAction, type PagingState,
} from "./fanListPaging";
import type { ActiveChip } from "./FanListFilters";

const ALL: ActiveChip = { kind: "builtin", key: "all" };
type View = Parameters<typeof pagingView>[0];
const base: View = { scopeKind: "model", accountKey: "1", active: ALL, query: "" };
const V0 = pagingView(base);
const run = (actions: PagingAction[], from = initialPaging(V0)): PagingState => actions.reduce(pagingReducer, from);
/** A list the user has paged through: scrolled, cap and render cap extended, autofill spent. */
const used = run([
  { type: "scrolled" }, { type: "extendCap", loaded: 200 }, { type: "showMore" },
  ...Array.from({ length: AUTOFILL_MAX_BURSTS }, () => ({ type: "autofilled" }) as const),
]);

describe("pagingReducer", () => {
  it("the used list really is used", () => {
    expect(used).toMatchObject({
      view: V0, userScrolled: true, capRows: 200 + SCROLL_CAP_STEP, renderCap: 2 * ROW_RENDER_STEP,
      autofillBursts: AUTOFILL_MAX_BURSTS,
    });
    expect(canAutofill(used)).toBe(false);
  });

  it.each<[string, Partial<View>]>([
    ["another Creator (scope)", { accountKey: "2" }],
    ["All Models (scope)", { scopeKind: "all", accountKey: "1,2" }],
    ["All Models: the model set changes", { scopeKind: "all", accountKey: "1,2,3" }],
    ["another chip (server filter)", { active: { kind: "builtin", key: "unread" } }],
    ["Owe reply (same server list, client filter)", { active: { kind: "builtin", key: "owe-reply" } }],
    ["a folder chip", { active: { kind: "folder", listId: "55" } }],
    ["a search", { query: "anna" }],
  ])("one resetFor gives a new list a fresh budget, every piece at once: %s", (_n, change) => {
    const view = pagingView({ ...base, ...change });
    const s = pagingReducer(used, { type: "resetFor", view });
    expect(s).toEqual(initialPaging(view));
    expect(canAutofill(s)).toBe(true);
  });

  it("the same list (the chip already on picked again) keeps its budget", () => {
    expect(pagingReducer(used, { type: "resetFor", view: pagingView({ ...base, active: { kind: "builtin", key: "all" } }) }))
      .toBe(used);
  });

  it("autofill stops at AUTOFILL_MAX_BURSTS per list", () => {
    const one = Array.from({ length: AUTOFILL_MAX_BURSTS - 1 }, () => ({ type: "autofilled" }) as const);
    expect(canAutofill(run(one))).toBe(true);
    expect(canAutofill(run([...one, { type: "autofilled" }]))).toBe(false);
  });

  it("scrolled is idempotent", () => {
    const s = run([{ type: "scrolled" }]);
    expect(pagingReducer(s, { type: "scrolled" })).toBe(s);
  });

  it("Show more renders one more step", () => {
    expect(run([{ type: "showMore" }, { type: "showMore" }]).renderCap).toBe(3 * ROW_RENDER_STEP);
  });

  it.each<[string, number, string, boolean]>([
    ["below the cap", SCROLL_CAP_STEP - 1, "", false],
    ["at the cap", SCROLL_CAP_STEP, "", true],
    ["a search bypasses the cap", SCROLL_CAP_STEP * 3, "anna", false],
  ])("isCapped: %s", (_n, loaded, query, want) => {
    expect(isCapped(initialPaging(V0), loaded, query)).toBe(want);
  });

  it("Load more at the cap extends it a step past what is loaded", () => {
    const s = run([{ type: "extendCap", loaded: 230 }]);
    expect(isCapped(s, 230, "")).toBe(false);
    expect(isCapped(s, 230 + SCROLL_CAP_STEP, "")).toBe(true);
  });
});
