"use client";

/**
 * A paged list's filters as a pure reducer: the filter fields `F` and the page.
 *
 *   • `set` patches any filter fields AND goes back to page 1 — one action, so
 *     no caller can change a filter and forget the page. A page size is a
 *     filter field too (it re-cuts the pages).
 *   • `page` moves the page only.
 *   • `clamp` pulls the stored page back inside `pages` when the list shrinks
 *     under it, so growing the list again does not jump back to the old page.
 *
 * `usePagedRows` cuts the rows into pages and runs the clamp, so a list only
 * renders `shown` and passes `current` to its pager.
 */

import { useCallback, useEffect, useReducer } from "react";

export type Paged<F> = F & { page: number };

export type PagedAction<F> =
  | { type: "set"; patch: Partial<F> }
  | { type: "page"; page: number }
  | { type: "clamp"; pages: number };

export function pagedReducer<F extends object>(s: Paged<F>, a: PagedAction<F>): Paged<F> {
  switch (a.type) {
    case "set":
      return { ...s, ...a.patch, page: 1 };
    case "page":
      return a.page === s.page ? s : { ...s, page: a.page };
    case "clamp": {
      const page = Math.min(s.page, Math.max(1, a.pages));
      return page === s.page ? s : { ...s, page };
    }
  }
}

export function usePagedFilters<F extends object>(init: F) {
  const [s, dispatch] = useReducer(pagedReducer<F>, init, (f): Paged<F> => ({ ...f, page: 1 }));
  const set = useCallback((patch: Partial<F>) => dispatch({ type: "set", patch }), []);
  const setPage = useCallback((page: number) => dispatch({ type: "page", page }), []);
  const clamp = useCallback((pages: number) => dispatch({ type: "clamp", pages }), []);
  return { ...s, set, setPage, clamp };
}

/** The page `size` of `rows` the list is on: renders the last page at once when the list shrinks under the stored
 *  page, and the effect then stores it (`clamp`). */
export function usePagedRows<T>(rows: readonly T[], size: number, paged: { page: number; clamp: (pages: number) => void }) {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const current = Math.min(paged.page, pages);
  const { clamp } = paged;
  useEffect(() => clamp(pages), [clamp, pages]);
  return { current, pages, shown: rows.slice((current - 1) * size, current * size) };
}
