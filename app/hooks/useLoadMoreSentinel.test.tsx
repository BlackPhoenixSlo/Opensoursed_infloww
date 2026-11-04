/**
 * useLoadMoreSentinel — how many next pages a foot in view asks for. The observer is a stand-in that, as a real one,
 * reports the element's visibility once after each `observe` (each re-subscribe); the list is a stand-in of React
 * Query's infinite query: `isError` set by a failed page, kept through a retry (Load more or refetch), cleared by a
 * page. A refetch flips the list's state (fetching, not a next page) while `isError` stays set.
 * Before the gate a failed page while the foot was in view was asked again on every fetch flip (13 in 5 s).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { useState } from "react";

import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";

let visible = true;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("IntersectionObserver", class {
    private live = true;
    constructor(private cb: IntersectionObserverCallback) {}
    observe(el: Element) {
      setTimeout(() => {
        if (this.live) this.cb([{ isIntersecting: visible, target: el } as unknown as IntersectionObserverEntry],
          this as unknown as IntersectionObserver);
      }, 0);
    }
    disconnect() { this.live = false; }
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const LAST_PAGE = 4;

/** A list with page 1 loaded; next pages answer after 10 ms, and the first `fails` of them fail; a refetch
 * (Refetch) runs 10 ms and fails again, asking no next page. */
function List({ fails, onRequest }: { fails: number; onRequest: () => number }) {
  const [s, setS] = useState({ pages: 1, fetching: false, refetching: false, error: false });
  const fetchNextPage = () => {
    const n = onRequest();
    setS((p) => ({ ...p, fetching: true }));
    setTimeout(() => setS((p) => (n <= fails
      ? { ...p, fetching: false, error: true }
      : { ...p, pages: p.pages + 1, fetching: false, error: false })), 10);
  };
  const refetch = () => {
    setS((p) => ({ ...p, refetching: true }));
    setTimeout(() => setS((p) => ({ ...p, refetching: false })), 10);
  };
  const ref = useLoadMoreSentinel(s.pages < LAST_PAGE, s.fetching, fetchNextPage, s.error);
  return (
    <>
      <div ref={ref} />
      <button type="button" onClick={fetchNextPage}>Retry</button>
      <button type="button" onClick={refetch}>Refetch</button>
      <span data-testid="refetching">{String(s.refetching)}</span>
      <span data-testid="pages">{s.pages}</span>
    </>
  );
}

async function settle() {
  for (let i = 0; i < 50; i++) await act(async () => { vi.advanceTimersByTime(100); });
}

describe("useLoadMoreSentinel", () => {
  it.each([
    // case,                                        in view, fails, Retry clicks, Refetch clicks, requests, pages
    ["auto-loads to the last page",                 true,    0,     0,            0,              3,        4],
    ["out of view asks for nothing",                false,   0,     0,            0,              0,        1],
    ["a failed page in view: one request",          true,    99,    0,            0,              1,        1],
    ["Retry that fails again: exactly one more",    true,    99,    1,            0,              2,        1],
    ["Retry that loads resumes auto-loading",       true,    1,     1,            0,              4,        4],
    ["a refetch while in error: no next page",      true,    99,    0,            2,              1,        1],
  ] as const)("%s", async (_case, inView, fails, clicks, refetches, requests, pages) => {
    visible = inView;
    let n = 0;
    render(<List fails={fails} onRequest={() => ++n} />);
    await settle();
    for (let i = 0; i < clicks; i++) {
      act(() => screen.getByRole("button", { name: "Retry" }).click());
      await settle();
    }
    for (let i = 0; i < refetches; i++) {
      act(() => screen.getByRole("button", { name: "Refetch" }).click());
      expect(screen.getByTestId("refetching").textContent).toBe("true");
      await settle();
    }
    expect(n).toBe(requests);
    expect(screen.getByTestId("pages").textContent).toBe(String(pages));
  });
});
