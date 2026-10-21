/**
 * The top bar's error triage badge (ErrorBadge), apart from the static "Operational" pill: the last 24h of
 * /admin/errors. None is a dim badge without a count; any is red with the count. A click opens the recent
 * errors either way.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), delete: vi.fn() } }));
// The first read is deferred ~1s on the real hook.
vi.mock("@/hooks/useDeferredMount", () => ({ useDeferredMount: () => true }));

import { renderWithProviders } from "@/test-utils";
import { relay } from "@/lib/relay";
import { ErrorBadge } from "@/components/ErrorBadge";

const relayGet = relay.get as unknown as Mock;
afterEach(() => {
  cleanup();
  relayGet.mockReset();
});

describe("ErrorBadge triage badge", () => {
  it("stays as a dim badge with no errors, never the Operational pill, and opens the recent errors on click", async () => {
    relayGet.mockResolvedValue({ count: 0, since_hours: 24, list: [] });
    renderWithProviders(<ErrorBadge />);
    const badge = screen.getByRole("button", { name: "Recent errors" });
    await waitFor(() => expect(badge).toHaveAttribute("title", "0 errors in last 24h"));
    expect(badge).toHaveClass("text-fg-dim");
    expect(badge).not.toHaveTextContent(/\d|Operational/);
    fireEvent.click(badge);
    expect(await screen.findByText("Recent errors")).toBeInTheDocument();
  });

  it("turns red with the error count once any error landed", async () => {
    relayGet.mockResolvedValue({ count: 3, since_hours: 24, list: [] });
    renderWithProviders(<ErrorBadge />);
    const badge = screen.getByRole("button", { name: "Recent errors" });
    await waitFor(() => expect(badge).toHaveTextContent("3"));
    expect(badge).toHaveAttribute("title", "3 errors in last 24h");
    expect(badge).toHaveClass("text-err");
  });
});
