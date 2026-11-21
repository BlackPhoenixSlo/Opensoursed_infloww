/**
 * MessageList — memoized bubbles: a thread update re-renders only the bubbles
 * whose props changed, not all of them (a 4,800-row thread paid ~1.2 s per
 * incoming message re-rendering every bubble). Bubble renders are counted off
 * `useCompactMedia`, which a text bubble calls once per render.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
const renders = vi.hoisted(() => ({ n: 0 }));
vi.mock("@/hooks/useCompactMedia", () => ({
  readCompactMedia: () => true,
  useCompactMedia: () => { renders.n += 1; return [true, () => {}] as const; },
}));

import { renderWithProviders } from "@/test-utils";
import { MessageList } from "@/components/chat/MessageList";
import type { OFMessage } from "@/lib/relay";
import { baseProps, bubbleBox, msg } from "./messageListTestHarness";

const N = 40;
// The Fan's messages, a minute apart on one day, each its own run of one.
const rows = (n: number): OFMessage[] => Array.from({ length: n }, (_, i) => msg({
  id: i + 1, text: `m${i + 1}`, fromUser: { id: 42 },
  createdAt: `2026-06-04T12:${String(i % 60).padStart(2, "0")}:00.000Z`,
  replyToMessageId: i === 5 ? 2 : undefined,
}));

beforeEach(() => {
  window.localStorage.clear();
  renders.n = 0;
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The parent as ChatSurface writes it: fresh inline handlers every render. */
function list(messages: OFMessage[], onToggleLike = vi.fn()) {
  return (
    <MessageList
      {...baseProps} messages={messages} ownerUserId={7}
      onRetry={() => {}} onToggleLike={(m) => onToggleLike(m)} onQuoteReply={() => {}}
      onTogglePin={() => {}} onUnsend={() => {}} onLoadOlder={() => {}}
    />
  );
}

describe("MessageList memoized bubbles", () => {
  it("appending one message re-renders ~1 bubble, not all of them", () => {
    const base = rows(N + 1);
    const { rerender } = renderWithProviders(list(base.slice(0, N)));
    expect(renders.n).toBeGreaterThanOrEqual(N);
    renders.n = 0;
    rerender(list(base));
    // The new bubble; the row before it keeps its props (runs of one).
    expect(renders.n).toBeGreaterThanOrEqual(1);
    expect(renders.n).toBeLessThanOrEqual(2);
  });

  it("a parent re-render with the same rows and fresh inline handlers re-renders no bubble", () => {
    const messages = rows(N);
    const { rerender } = renderWithProviders(list(messages));
    renders.n = 0;
    rerender(list(messages));
    expect(renders.n).toBe(0);
  });

  it("a bubble's stable handler still calls the parent's latest one", () => {
    const messages = rows(3);
    const first = vi.fn(), latest = vi.fn();
    const { container, rerender } = renderWithProviders(list(messages, first));
    rerender(list(messages, latest));
    fireEvent.doubleClick(bubbleBox(container, 2));
    expect(first).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledWith(messages[1]);
  });
});
