/**
 * InfiniteListFooter — what the foot of a list shows in each paging state, and that its sentinel, once seen,
 * asks for the next page only when there is one and none is loading.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import InfiniteListFooter from "./InfiniteListFooter";

let observed: Element[] = [];
let fire: IntersectionObserverCallback = () => {};
let margin: string | undefined;

beforeEach(() => {
  observed = [];
  vi.stubGlobal("IntersectionObserver", class {
    constructor(cb: IntersectionObserverCallback, opts?: IntersectionObserverInit) { fire = cb; margin = opts?.rootMargin; }
    observe(el: Element) { observed.push(el); }
    disconnect() {}
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("InfiniteListFooter", () => {
  it.each([
    // state,                     hasNext, fetching, button,       disabled, end line,             fetches when seen
    ["more to load",              true,    false,    "Load more",  false,    null,                 1],
    ["loading the next page",     true,    true,     "Loading…",   true,     null,                 0],
    ["end of a report",           false,   false,    null,         false,    "· end of results ·", 0],
  ] as const)("%s", (_state, hasNextPage, isFetchingNextPage, button, disabled, end, fetches) => {
    const fetchNextPage = vi.fn();
    render(<InfiniteListFooter hasNextPage={hasNextPage} isFetchingNextPage={isFetchingNextPage}
      fetchNextPage={fetchNextPage} endLabel="end of results" />);

    if (button) {
      const b = screen.getByRole("button", { name: button });
      expect((b as HTMLButtonElement).disabled).toBe(disabled);
    } else {
      expect(screen.queryByRole("button")).toBeNull();
    }
    if (end) screen.getByText(end);
    else expect(screen.queryByText(/end of/)).toBeNull();

    if (observed.length) {
      expect(margin).toBe("200px");
      act(() => fire([{ isIntersecting: true, target: observed.at(-1)! } as unknown as IntersectionObserverEntry],
        {} as IntersectionObserver));
    }
    expect(fetchNextPage).toHaveBeenCalledTimes(fetches);
  });

  it("Load more asks for the next page", () => {
    const fetchNextPage = vi.fn();
    render(<InfiniteListFooter hasNextPage isFetchingNextPage={false} fetchNextPage={fetchNextPage} endLabel="end of feed" />);
    screen.getByRole("button", { name: "Load more" }).click();
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("says the feed's own end line", () => {
    render(<InfiniteListFooter hasNextPage={false} isFetchingNextPage={false} fetchNextPage={vi.fn()} endLabel="end of feed" />);
    screen.getByText("· end of feed ·");
  });
});
