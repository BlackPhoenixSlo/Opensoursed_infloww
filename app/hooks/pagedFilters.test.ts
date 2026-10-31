import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { pagedReducer, usePagedFilters, usePagedRows, type Paged, type PagedAction } from "./pagedFilters";

type F = { search: string; pageSize: number; on: boolean };
const S = (page: number, patch: Partial<F> = {}): Paged<F> => ({ search: "", pageSize: 50, on: false, ...patch, page });

describe("pagedReducer", () => {
  it.each<[string, Paged<F>, PagedAction<F>, Paged<F>]>([
    ["a filter goes back to page 1", S(3), { type: "set", patch: { search: "x" } }, S(1, { search: "x" })],
    ["a page size goes back to page 1", S(3), { type: "set", patch: { pageSize: 10 } }, S(1, { pageSize: 10 })],
    ["a switch goes back to page 1", S(2), { type: "set", patch: { on: true } }, S(1, { on: true })],
    ["several fields in one patch", S(4), { type: "set", patch: { search: "a", on: true } }, S(1, { search: "a", on: true })],
    ["the same value still goes back to page 1", S(2, { search: "x" }), { type: "set", patch: { search: "x" } }, S(1, { search: "x" })],
    ["page moves the page only", S(1, { search: "x" }), { type: "page", page: 5 }, S(5, { search: "x" })],
    ["clamp pulls a page past the end back to the last", S(5, { search: "x" }), { type: "clamp", pages: 2 }, S(2, { search: "x" })],
    ["clamp to no pages lands on page 1", S(3), { type: "clamp", pages: 0 }, S(1)],
  ])("%s", (_name, s, a, want) => {
    expect(pagedReducer(s, a)).toEqual(want);
  });

  it.each<[string, PagedAction<F>]>([
    ["the page it is on", { type: "page", page: 2 }],
    ["a clamp with the page in range", { type: "clamp", pages: 2 }],
    ["a clamp with more pages", { type: "clamp", pages: 9 }],
  ])("returns the same state for %s", (_name, a) => {
    const s = S(2);
    expect(pagedReducer(s, a)).toBe(s);
  });
});

describe("usePagedFilters", () => {
  it("starts on page 1; set resets the page, setPage moves it", () => {
    const { result } = renderHook(() => usePagedFilters<F>({ search: "", pageSize: 50, on: false }));
    expect(result.current.page).toBe(1);
    act(() => result.current.setPage(4));
    expect(result.current.page).toBe(4);
    act(() => result.current.set({ search: "x" }));
    expect(result.current).toMatchObject({ search: "x", page: 1 });
  });

  it("clamp keeps the stored page, so a shrink then grow stays on the last page", () => {
    const { result } = renderHook(() => usePagedFilters<F>({ search: "", pageSize: 50, on: false }));
    act(() => result.current.setPage(4));
    act(() => result.current.clamp(2));
    expect(result.current.page).toBe(2);
    act(() => result.current.clamp(6));
    expect(result.current.page).toBe(2);
  });

  it("keeps set, setPage and clamp stable across renders", () => {
    const { result } = renderHook(() => usePagedFilters<F>({ search: "", pageSize: 50, on: false }));
    const { set, setPage, clamp } = result.current;
    act(() => result.current.set({ search: "x" }));
    expect(result.current.set).toBe(set);
    expect(result.current.setPage).toBe(setPage);
    expect(result.current.clamp).toBe(clamp);
  });
});

describe("usePagedRows", () => {
  const rows = (n: number) => Array.from({ length: n }, (_, i) => i);
  const render = (n: number) => renderHook(({ n }) => {
    const f = usePagedFilters<{ pageSize: number }>({ pageSize: 2 });
    return { f, ...usePagedRows(rows(n), f.pageSize, f) };
  }, { initialProps: { n } });

  it.each<[string, number, number, { current: number; pages: number; shown: number[] }]>([
    ["no rows is one empty page", 0, 1, { current: 1, pages: 1, shown: [] }],
    ["the first page", 5, 1, { current: 1, pages: 3, shown: [0, 1] }],
    ["a short last page", 5, 3, { current: 3, pages: 3, shown: [4] }],
  ])("%s", (_name, n, page, want) => {
    const { result } = render(n);
    act(() => result.current.f.setPage(page));
    expect(result.current).toMatchObject(want);
  });

  it("a shrink renders the last page and stores it, so growing again stays there", () => {
    const { result, rerender } = render(10);
    act(() => result.current.f.setPage(5));
    rerender({ n: 4 });
    expect(result.current).toMatchObject({ current: 2, pages: 2, shown: [2, 3] });
    expect(result.current.f.page).toBe(2);
    rerender({ n: 10 });
    expect(result.current).toMatchObject({ current: 2, pages: 5, shown: [2, 3] });
  });
});
