import { describe, expect, it } from "vitest";

import {
  ROW_RENDER_STEP, initialPaging,
  pagingReducer, pagingView, type PagingAction, type PagingState,
} from "./fanListPaging";
import type { ActiveChip } from "./FanListFilters";

const ALL: ActiveChip = { kind: "builtin", key: "all" };
type View = Parameters<typeof pagingView>[0];
const base: View = { scopeKind: "model", accountKey: "1", active: ALL, query: "" };
const V0 = pagingView(base);
const run = (actions: PagingAction[], from = initialPaging(V0)): PagingState => actions.reduce(pagingReducer, from);
const used = run([
  { type: "scrolled" }, { type: "showMore" },
]);

describe("pagingReducer", () => {
  it("the used list really is used", () => {
    expect(used).toMatchObject({
      view: V0, userScrolled: true, renderCap: 2 * ROW_RENDER_STEP,
    });
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
  });

  it("the same list (the chip already on picked again) keeps its budget", () => {
    expect(pagingReducer(used, { type: "resetFor", view: pagingView({ ...base, active: { kind: "builtin", key: "all" } }) }))
      .toBe(used);
  });

  it("scrolled is idempotent", () => {
    const s = run([{ type: "scrolled" }]);
    expect(pagingReducer(s, { type: "scrolled" })).toBe(s);
  });

  it("a page taken on a scroll uses it up: the next page needs a fresh scroll", () => {
    const s = run([{ type: "scrolled" }, { type: "scrollUsed" }]);
    expect(s.userScrolled).toBe(false);
    expect(pagingReducer(s, { type: "scrollUsed" })).toBe(s);
    expect(pagingReducer(s, { type: "scrolled" }).userScrolled).toBe(true);
  });

  it("Show more renders one more step", () => {
    expect(run([{ type: "showMore" }, { type: "showMore" }]).renderCap).toBe(3 * ROW_RENDER_STEP);
  });
});
