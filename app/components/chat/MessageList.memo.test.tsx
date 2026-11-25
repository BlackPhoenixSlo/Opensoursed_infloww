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
