/**
 * HelpCenterPage — /help-center is the help bot in Infloww's bare frame: no
 * page title, no "not built" card, and the same conversation as the dock.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayPost, nav } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  nav: { pathname: "/help-center" },
}));

vi.mock("@/lib/relay", () => ({
  RelayError: class extends Error {},
  relay: {
    post: (...a: unknown[]) => relayPost(...a),
    get: async () => ({ count: 0, since_hours: 24, list: [] }),
  },
}));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: "1001" }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "1001", nickname: "Blake1" }] }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";
import HelpCenterPage from "./HelpCenterPage";

beforeEach(() => {
  relayPost.mockReset();
  nav.pathname = "/help-center";
  window.localStorage.clear();
});
afterEach(cleanup);

describe("HelpCenterPage", () => {
  it("is the messenger itself: greeting, Ask card, composer; no title, no placeholder", () => {
    renderWithProviders(<AssistantProvider><HelpCenterPage /></AssistantProvider>);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("How can we help?");
    expect(screen.getByRole("button", { name: /Ask a question/ })).toBeTruthy();
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Help center" })).toBeNull();
    expect(screen.queryByText(/not built yet/)).toBeNull();
    // Nothing to close on a page.
    expect(screen.queryByRole("button", { name: "Close help" })).toBeNull();
  });

  it("shares the conversation with the dock", async () => {
    relayPost.mockResolvedValue({ answer: "Growth → 📣 Promotion.", error: null });
    const { rerender } = renderWithProviders(
      <AssistantProvider><HelpCenterPage /><AssistantWidget /></AssistantProvider>,
    );
    await userEvent.type(screen.getByPlaceholderText("Ask a question…"), "how do I set up auto posts?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));

    // Leave the page: the dock's launcher returns, and its panel holds the same turn.
    nav.pathname = "/";
    rerender(<AssistantProvider><AssistantWidget /></AssistantProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    expect(await screen.findByText("how do I set up auto posts?")).toBeTruthy();
  });
});
