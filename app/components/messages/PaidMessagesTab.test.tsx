/**
 * Regression guard: after an error, recovery keeps PaidMessagesTab auto-loading (a Retry that brings rows back, and
 * a failed page seen again by the sentinel, both load the next page).
 * Every identifier is invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen } from "@testing-library/react";

const get = vi.fn();
vi.mock("@/lib/relay", () => ({ relay: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/components/messages/MessagesFilters", () => ({ default: () => null }));
vi.mock("@/components/messages/CsvExportButton", () => ({ default: () => null }));
vi.mock("@/components/messages/GroupMassButton", () => ({ default: () => null }));
vi.mock("@/components/messages/MessageRow", () => ({
  default: ({ row }: { row: { message_id: number } }) => <div>row {row.message_id}</div>,
}));

import { renderWithProviders } from "@/test-utils";
import PaidMessagesTab from "./PaidMessagesTab";

const page = (id: number, next: number | null) => ({
  rows: [{ account_id: "100000001", fan_id: 200000002, message_id: id }],
  next_before_id: next,
  next_before_sent_at: next == null ? null : "2026-10-19T15:04:00",
});

let observed: Element[] = [];
let fire: IntersectionObserverCallback = () => {};
const seeSentinel = () => {
  const live = observed.at(-1)!;
  expect(live.isConnected).toBe(true);
  act(() => fire([{ isIntersecting: true, target: live } as unknown as IntersectionObserverEntry], {} as IntersectionObserver));
};
const pageTwoCalls = () => get.mock.calls.filter(([url]) => String(url).includes("before_id=")).length;

beforeEach(() => {
  observed = [];
  get.mockReset();
  vi.stubGlobal("IntersectionObserver", class {
    constructor(cb: IntersectionObserverCallback) { fire = cb; }
    observe(el: Element) { observed.push(el); }
    disconnect() {}
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PaidMessagesTab infinite scroll after an error", () => {
  it("first page fails, Retry brings rows, the sentinel loads page 2", async () => {
    get.mockRejectedValueOnce(new Error("relay down")).mockResolvedValueOnce(page(9, 8)).mockResolvedValue(page(8, null));
    const { queryClient } = renderWithProviders(<PaidMessagesTab from="2026-10-01" to="2026-10-02" />);
    await screen.findByText(/Failed to load: relay down/);
    await act(() => queryClient.refetchQueries());
    await screen.findByText("row 9");
    seeSentinel();
    await screen.findByText("row 8");
    expect(pageTwoCalls()).toBe(1);
  });

  it("page 2 fails, the sentinel seen again loads it", async () => {
    get.mockResolvedValueOnce(page(9, 8)).mockRejectedValueOnce(new Error("relay down")).mockResolvedValue(page(8, null));
    renderWithProviders(<PaidMessagesTab from="2026-10-01" to="2026-10-02" />);
    await screen.findByText("row 9");
    seeSentinel();
    await screen.findByText(/Failed to load: relay down/);
    seeSentinel();
    await screen.findByText("row 8");
    expect(pageTwoCalls()).toBe(2);
  });
});
