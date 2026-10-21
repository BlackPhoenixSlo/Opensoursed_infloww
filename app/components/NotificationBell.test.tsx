/**
 * NotificationBell, top bar: the panel's "See all" opens the full
 * Notifications page, and the bell's own click still opens the panel
 * (docs/spec/phase-05-remaining-parity-gaps.md, stories 44, Testing Decisions).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));

vi.mock("@/lib/relay", () => ({ relay: { get: (...args: unknown[]) => relayGet(...args) } }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "acc-1", nickname: "Creator One" }] }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: "acc-1" }) }));

import { renderWithProviders } from "@/test-utils";
import { appendNotifHistory, markNotifHistoryResponded } from "@/lib/notifSettings";
import { NotificationBell } from "./NotificationBell";

afterEach(() => {
  cleanup();
  relayGet.mockReset();
  localStorage.clear();
});

describe("NotificationBell (top bar)", () => {
  it("opens its panel on click, and the panel's \"See all\" links to /notifications", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationBell />);
    expect(screen.queryByRole("link", { name: "See all" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all" })).toHaveAttribute("href", "/notifications");
  });
});

describe("NotificationBell (Messages Pro)", () => {
  it("opens its signed-off panel with no \"See all\"", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(
      <NotificationBell variant="messages-pro" classNames={{ button: "", icon: "", badge: "", panel: "" }} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "See all" })).toBeNull();
  });
});

describe("NotificationBell (has responded)", () => {
  it("swaps Reply for \"<who> has responded\" on the answered fan's message rows only", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const at = new Date().toISOString();
    for (const [id, fan] of [["m1", 7], ["m2", 8]] as const) {
      appendNotifHistory({
        id, accountId: "acc-1", type: "message", typeKey: "message",
        user: { id: fan, name: `Fan ${fan}` }, text: "hi", createdAt: at,
      });
    }
    markNotifHistoryResponded("acc-1", 7, "Kingsley");
    renderWithProviders(
      <NotificationBell variant="messages-pro" classNames={{ button: "", icon: "", badge: "", panel: "" }} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("Kingsley")).toBeInTheDocument();
    expect(screen.getByText(/has responded/)).toBeInTheDocument();
    // Fan 8 is still unanswered: one Reply left.
    expect(screen.getAllByRole("button", { name: "Reply" })).toHaveLength(1);
  });
});
