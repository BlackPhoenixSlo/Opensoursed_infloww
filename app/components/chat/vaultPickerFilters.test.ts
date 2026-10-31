import { describe, expect, it } from "vitest";

import {
  fetchSort, initialFilters, vaultFiltersReducer, type VaultFilterAction, type VaultFilterState,
} from "./vaultPickerFilters";

const S = (p: Partial<VaultFilterState> = {}): VaultFilterState => ({ ...initialFilters, ...p });

describe("vaultFiltersReducer", () => {
  it.each<[string, VaultFilterState, VaultFilterAction, Partial<VaultFilterState>]>([
    ["setType", S(), { type: "setType", value: "video" }, { type: "video" }],
    ["setListId", S(), { type: "setListId", value: 4 }, { listId: 4 }],
    ["setListId null = All folders", S({ listId: 4 }), { type: "setListId", value: null }, { listId: null }],
    ["setSort", S(), { type: "setSort", value: "oldest" }, { sort: "oldest" }],
    ["setHideSeen", S(), { type: "setHideSeen", value: true }, { hideSeen: true }],
    ["setLengthRange", S(), { type: "setLengthRange", value: "1-5" }, { lengthRange: "1-5" }],
    ["setQueryInput leaves query until the debounce", S(), { type: "setQueryInput", value: " cat " }, { queryInput: " cat " }],
    ["commitQuery trims", S({ queryInput: " cat " }), { type: "commitQuery", value: " cat " }, { queryInput: " cat ", query: "cat" }],
    ["clearQuery", S({ queryInput: "x", query: "x" }), { type: "clearQuery" }, { queryInput: "", query: "" }],
    ["hydrate from saved state, search cleared, hide/length kept",
      S({ queryInput: "q", query: "q", hideSeen: true }),
      { type: "hydrate", saved: { listId: "s1", sort: "oldest", type: "gif" } },
      { listId: "s1", sort: "oldest", type: "gif", hideSeen: true }],
    ["hydrate on a fan with nothing saved resets to All / Newest / All-types",
      S({ listId: 3, sort: "oldest", type: "photo", queryInput: "q", query: "q" }),
      { type: "hydrate", saved: null },
      {}],
  ])("%s", (_n, state, action, want) => {
    expect(vaultFiltersReducer(state, action)).toEqual(S({ ...want }));
  });

  it("returns the same state on a no-op (React bails out like useState)", () => {
    const s = S({ type: "photo" });
    expect(vaultFiltersReducer(s, { type: "setType", value: "photo" })).toBe(s);
    expect(vaultFiltersReducer(s, { type: "commitQuery", value: "  " })).toBe(s);
    expect(vaultFiltersReducer(s, { type: "clearQuery" })).toBe(s);
  });

  it("does not mutate the input", () => {
    const s = S();
    vaultFiltersReducer(s, { type: "setSort", value: "oldest" });
    expect(s).toEqual(initialFilters);
  });
});

describe("fetchSort", () => {
  it.each([["newest", "newest"], ["oldest", "oldest"], ["sent", "newest"], ["unlock_rate", "newest"]] as const)("%s → %s", (sort, want) => {
    expect(fetchSort(sort as never)).toBe(want);
  });
});
