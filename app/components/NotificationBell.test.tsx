/**
 * NotificationBell, top bar: the panel's "See all" opens the full
 * Notifications page, and the bell's own click still opens the panel
 * (docs/spec/phase-05-remaining-parity-gaps.md, stories 44, Testing Decisions).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));

vi.mock("@/lib/relay", () => ({ relay: { get: (...args: unknown[]) => relayGet(...args) } }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "acc-1", nickname: "Creator One" }] }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: "acc-1" }) }));

import { renderWithProviders } from "@/test-utils";
import { NOTIF_CLEARED_EVENT, appendNotifHistory, dispatchNotifArrived, markNotifHistoryResponded } from "@/lib/notifSettings";
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

  it("badges arrivals while closed, and each open clears it and sends the cleared event once", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const cleared = vi.fn();
    window.addEventListener(NOTIF_CLEARED_EVENT, cleared);
    try {
      const user = userEvent.setup();
      const { rerender } = renderWithProviders(<NotificationBell />);
      act(() => { dispatchNotifArrived(); dispatchNotifArrived(); });
      expect(screen.getByTestId("bell-count")).toHaveTextContent("2");

      const bell = screen.getByRole("button", { name: "Notifications" });
      await user.click(bell);
      expect(screen.queryByTestId("bell-count")).toBeNull();
      act(() => { dispatchNotifArrived(); });
      rerender(<NotificationBell />);
      expect(screen.queryByTestId("bell-count")).toBeNull();
      expect(cleared).toHaveBeenCalledTimes(1);

      await user.click(bell); // close: no event
      expect(cleared).toHaveBeenCalledTimes(1);
      await user.click(bell); // re-open, nothing new: one more
      expect(cleared).toHaveBeenCalledTimes(2);
    } finally {
      window.removeEventListener(NOTIF_CLEARED_EVENT, cleared);
    }
  });

  it("a row opens the Fan as a Fan tab in the Messages Pro window, not a browser tab", async () => {
    relayGet.mockResolvedValue({ list: [] });
    appendNotifHistory({
      id: "m9", accountId: "acc-1", type: "message", typeKey: "message",
      user: { id: 9, name: "Ann Lee" }, text: "hi there", createdAt: new Date().toISOString(),
    });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    try {
      renderWithProviders(<NotificationBell />);
      await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
      const row = (await screen.findByText("hi there")).closest("a")!;
      expect(row).toHaveAttribute("href", "/messages-pro/acc-1/9?fanTab=Ann+Lee");
      expect(row).not.toHaveAttribute("target");

      await userEvent.click(row);
      expect(open).toHaveBeenCalledWith("", "messages-pro", expect.any(String));
    } finally {
      open.mockRestore();
    }
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

describe("NotificationBell (Agency pane)", () => {
  it("closes when an Agency row's in-app link is followed", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(
      <NotificationBell agency={{ unread: 1, panel: <a href="/creators?relink=browserbase" onClick={(e) => e.preventDefault()}>Zoe needs a 2FA code</a> }} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
    await userEvent.click(await screen.findByRole("link", { name: "Zoe needs a 2FA code" }));

    expect(screen.queryByRole("link", { name: "Zoe needs a 2FA code" })).toBeNull();
  });

  it("OnlyFans arrivals while the panel shows the Agency tab badge the bell once it closes; on the OnlyFans tab they don't", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell agency={{ unread: 2, panel: <p>Agency feed</p> }} />);
    expect(await screen.findByTestId("bell-count")).toHaveTextContent("2");

    // Only Agency has news: the panel opens on it, and OnlyFans arrivals land meanwhile.
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Agency feed")).toBeInTheDocument();
    act(() => { dispatchNotifArrived(); });
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Agency feed")).toBeNull();
    expect(screen.getByTestId("bell-count")).toHaveTextContent("3");

    // Read on the OnlyFans tab, they are seen as they land.
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    act(() => { dispatchNotifArrived(); });
    await user.keyboard("{Escape}");
    expect(screen.getByTestId("bell-count")).toHaveTextContent("2");
  });

  it("the Agency tab going away while it is shown puts the OnlyFans list on screen", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<NotificationBell agency={{ unread: 2, panel: <p>Agency feed</p> }} />);
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Agency feed")).toBeInTheDocument();

    rerender(<NotificationBell />);
    expect(screen.queryByText("Agency feed")).toBeNull();
    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
  });
});
