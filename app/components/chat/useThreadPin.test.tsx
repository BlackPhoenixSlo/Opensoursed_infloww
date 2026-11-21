/**
 * useThreadPin's timers and the top sentinel's observer, driven through the
 * real hook with a fake IntersectionObserver that, like the real one, reports
 * its target once (asynchronously) on observe().
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";

import type { OFMessage } from "@/lib/relay";

import { AUTO_PIN_BACKSTOP_MS, MAX_FILL_PAGES } from "./threadPin";
import { useThreadPin } from "./useThreadPin";

let sentinelVisible = true;
let observers = 0;
class FakeIO {
  private live = true;
  constructor(private cb: (entries: { isIntersecting: boolean }[]) => void) { observers++; }
  observe() { void Promise.resolve().then(() => { if (this.live) this.cb([{ isIntersecting: sentinelVisible }]); }); }
  unobserve() {}
  disconnect() { this.live = false; }
  takeRecords() { return []; }
}

const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: i + 1, text: "", media: [] }) as unknown as OFMessage);

interface Props {
  messages: OFMessage[]; hasOlder?: boolean; loadingOlder?: boolean; olderFailed?: boolean; headSettled?: boolean;
  onLoadOlder: () => void;
}
function Thread({ messages, hasOlder = true, loadingOlder = false, olderFailed = false, headSettled, onLoadOlder }: Props) {
  const { containerRef, topSentinelRef, autoPinActive } =
    useThreadPin({ messages, hasOlder, loadingOlder, olderFailed, headSettled, onLoadOlder });
  return (
    <div ref={containerRef} data-pinned={String(autoPinActive)}>
      <div ref={topSentinelRef} />
      {messages.map((m) => <div key={m.id}>{m.id}</div>)}
    </div>
  );
}

/** Advance fake time, then flush the observers' microtask deliveries. */
const advance = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("IntersectionObserver", FakeIO);
  sentinelVisible = true;
  observers = 0;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useThreadPin backstop", () => {
  it("releases the auto-pin 5 s after the first paint even when messages keep changing", async () => {
    const load = vi.fn();
    const { container, rerender } = render(<Thread messages={rows(2)} onLoadOlder={load} />);
    const pinned = () => (container.firstElementChild as HTMLElement).dataset.pinned;
    await advance(1000);
    rerender(<Thread messages={rows(3)} onLoadOlder={load} />); // the seed, then OF's head page
    await advance(1000);
    rerender(<Thread messages={rows(4)} onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS - 2000 - 1);
    expect(pinned()).toBe("true");
    await advance(1);
    expect(pinned()).toBe("false");
  });
});

describe("useThreadPin sentinel auto-load", () => {
  it("a short chat (sentinel in view, no scrollbar) auto-loads once the pin releases, with no gesture", async () => {
    const load = vi.fn();
    render(<Thread messages={rows(2)} onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS - 1);
    expect(load).not.toHaveBeenCalled(); // pinned: the first paint's trivially-visible sentinel is ignored
    await advance(1);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("a page settling re-checks a still-visible sentinel (keeps filling a short chat)", async () => {
    const load = vi.fn();
    const { rerender } = render(<Thread messages={rows(2)} onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS);
    expect(load).toHaveBeenCalledTimes(1);
    rerender(<Thread messages={rows(2)} loadingOlder onLoadOlder={load} />);
    await advance(10);
    rerender(<Thread messages={rows(5)} onLoadOlder={load} />);
    await advance(10);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("a new onLoadOlder identity (an inline arrow per parent render) neither re-observes nor re-fires", async () => {
    const calls: string[] = [];
    const { rerender } = render(<Thread messages={rows(2)} onLoadOlder={() => calls.push("a")} />);
    await advance(AUTO_PIN_BACKSTOP_MS);
    const made = observers;
    rerender(<Thread messages={rows(2)} onLoadOlder={() => calls.push("b")} />);
    rerender(<Thread messages={rows(2)} onLoadOlder={() => calls.push("c")} />);
    await advance(10);
    expect(observers).toBe(made);
    expect(calls).toEqual(["a"]);
  });

  it("after a failed page the sentinel stops: re-renders and settles never re-fire it", async () => {
    const load = vi.fn();
    const { rerender } = render(<Thread messages={rows(2)} onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS);
    expect(load).toHaveBeenCalledTimes(1);
    rerender(<Thread messages={rows(2)} loadingOlder onLoadOlder={load} />);
    rerender(<Thread messages={rows(2)} olderFailed onLoadOlder={() => load()} />);
    await advance(10);
    rerender(<Thread messages={rows(2)} olderFailed onLoadOlder={() => load()} />);
    await advance(10_000);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("an exhausted chat never observes", async () => {
    const load = vi.fn();
    render(<Thread messages={rows(2)} hasOlder={false} onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS * 2);
    expect(load).not.toHaveBeenCalled();
  });
});

describe("useThreadPin short-chat fill", () => {
  it("a sentinel still in view fills as soon as the head settles, before the backstop", async () => {
    const load = vi.fn();
    const { rerender } = render(<Thread messages={rows(3)} onLoadOlder={load} />); // the seed
    await advance(10);
    expect(load).not.toHaveBeenCalled(); // head not in yet: the seed's cursor is not OF's
    rerender(<Thread messages={rows(3)} headSettled onLoadOlder={load} />);
    await advance(10);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("keeps filling page by page while the sentinel stays in view, and stops once it leaves", async () => {
    const load = vi.fn();
    const { rerender } = render(<Thread messages={rows(3)} headSettled onLoadOlder={load} />);
    await advance(10);
    expect(load).toHaveBeenCalledTimes(1);
    rerender(<Thread messages={rows(3)} headSettled loadingOlder onLoadOlder={load} />);
    rerender(<Thread messages={rows(5)} headSettled onLoadOlder={load} />); // still short
    await advance(10);
    expect(load).toHaveBeenCalledTimes(2);
    rerender(<Thread messages={rows(5)} headSettled loadingOlder onLoadOlder={load} />);
    sentinelVisible = false; // the page pushed the sentinel out of its margin
    rerender(<Thread messages={rows(9)} headSettled onLoadOlder={load} />);
    await advance(10);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("stops at the fill cap while pinned, then the release lets the sentinel go on", async () => {
    const load = vi.fn();
    const { rerender } = render(<Thread messages={rows(3)} headSettled onLoadOlder={load} />);
    for (let i = 0; i < MAX_FILL_PAGES + 3; i++) {
      await advance(10);
      rerender(<Thread messages={rows(3)} headSettled loadingOlder onLoadOlder={load} />);
      rerender(<Thread messages={rows(3)} headSettled onLoadOlder={load} />);
    }
    await advance(10);
    expect(load).toHaveBeenCalledTimes(MAX_FILL_PAGES);
    await advance(AUTO_PIN_BACKSTOP_MS);
    expect(load).toHaveBeenCalledTimes(MAX_FILL_PAGES + 1);
  });

  it("a long head (sentinel out of view) never fills", async () => {
    sentinelVisible = false;
    const load = vi.fn();
    render(<Thread messages={rows(30)} headSettled onLoadOlder={load} />);
    await advance(AUTO_PIN_BACKSTOP_MS * 2);
    expect(load).not.toHaveBeenCalled();
  });
});

describe("useThreadPin load-older anchor (pre-commit snapshot)", () => {
  // jsdom lays nothing out: fake 100px rows in a 400px viewport.
  const fakeGeometry = (el: HTMLElement) => {
    let top = 0;
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => 400 });
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => (el.childElementCount - 1) * 100 });
    Object.defineProperty(el, "scrollTop", {
      configurable: true, get: () => top, set: (v: number) => { top = Math.max(0, Math.min(v, el.scrollHeight - 400)); },
    });
    return el;
  };
  const range = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, i) => ({ id: from + i, text: "", media: [] }) as unknown as OFMessage);

  it("an older page while at the top keeps the old top row in place; appends never move a scrolled-up view", async () => {
    sentinelVisible = false;
    const load = vi.fn();
    const { container, rerender } = render(<Thread messages={range(31, 60)} headSettled onLoadOlder={load} />);
    const c = fakeGeometry(container.firstElementChild as HTMLElement);
    await advance(AUTO_PIN_BACKSTOP_MS); // the auto-pin lets go
    c.scrollTop = 0; // the user wheeled to the top
    rerender(<Thread messages={range(1, 60)} headSettled onLoadOlder={load} />);
    expect(c.scrollTop).toBe(3000); // row 31 sits where it was: 30 rows × 100px further down
    rerender(<Thread messages={range(1, 61)} headSettled onLoadOlder={load} />);
    expect(c.scrollTop).toBe(3000); // an incoming message while scrolled up: none
    c.scrollTop = c.scrollHeight; // back at the bottom
    rerender(<Thread messages={range(1, 62)} headSettled onLoadOlder={load} />);
    expect(c.scrollTop).toBe(c.scrollHeight - 400); // pinned to the new bottom
  });
});
