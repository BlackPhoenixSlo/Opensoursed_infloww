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
// lib/webPush at its interface (its HTTP is webPush.test.ts's).
const wp = vi.hoisted(() => {
  const state = { id: null as string | null, failed: null as string | null };
  return {
    state,
    supported: true,
    ios: false,
    subscribePush: vi.fn(async () => { state.id = "sub-1"; return "sub-1"; }),
    unsubscribePush: vi.fn(async () => { state.id = null; }),
    showViaWorker: vi.fn(async () => undefined),
    testPush: vi.fn(async () => ({ status: 201 })),
  };
});
vi.mock("@/lib/webPush", () => ({
  pushSupported: () => wp.supported,
  iosTab: () => wp.ios,
  subscribePush: wp.subscribePush,
  unsubscribePush: wp.unsubscribePush,
  showViaWorker: wp.showViaWorker,
  testPush: wp.testPush,
  usePushState: () => ({ ...wp.state }),
  why: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { renderWithProviders } from "@/test-utils";
import { NOTIF_CLEARED_EVENT, appendNotifHistory, dispatchNotifArrived, markNotifHistoryResponded } from "@/lib/notifSettings";
import { NotificationBell } from "./NotificationBell";
import { DENIED_MSG, IOS_TAB_MSG } from "./OsPingSettings";

afterEach(() => {
  cleanup();
  relayGet.mockReset();
  localStorage.clear();
  vi.clearAllMocks();
  Object.assign(wp.state, { id: null, failed: null });
  wp.supported = true;
  wp.ios = false;
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

describe("NotificationBell (OS notifications: Web Push)", () => {
  async function openSettings() {
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    await user.click(await screen.findByRole("button", { name: "Toast settings" }));
    return user;
  }

  it("Test with push: subscribes from the tap, shows through the service worker, then offers the delayed push", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default", requestPermission: vi.fn() }));
    try {
      const user = await openSettings();
      await user.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText(/✓ Push on: lock screen alerts active/)).toBeInTheDocument();
      expect(wp.subscribePush).toHaveBeenCalledTimes(1); // it asks the permission itself
      expect(Notification.requestPermission).not.toHaveBeenCalled();
      expect(wp.showViaWorker).toHaveBeenCalledWith("Inflowwww test", expect.objectContaining({ tag: "chatterly-test" }));
      expect(Notification).not.toHaveBeenCalled(); // no in-page notification

      await user.click(screen.getByRole("button", { name: "Send push in 8 s, lock your phone" }));
      expect(wp.testPush).toHaveBeenCalledWith(8);
      expect(await screen.findByText(/Push in 8 s: lock your phone now/)).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("Test when push fails: the relay's reason, alerts only while open", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default" }));
    wp.subscribePush.mockRejectedValueOnce(new Error("push disabled: no VAPID subject"));
    try {
      const user = await openSettings();
      await user.click(screen.getByRole("button", { name: "Test" }));
      expect(await screen.findByText("✗ push unavailable: push disabled: no VAPID subject, alerts only while open")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Send push in 8 s/ })).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("Test without push support: the in-page notification, as before", async () => {
    wp.supported = false;
    const N = Object.assign(vi.fn(), { permission: "granted" });
    vi.stubGlobal("Notification", N);
    try {
      const user = await openSettings();
      await user.click(screen.getByRole("button", { name: "Test" }));
      expect(await screen.findByText("✓ Fired — check your OS tray.")).toBeInTheDocument();
      expect(N).toHaveBeenCalledWith("Inflowwww test", expect.objectContaining({ tag: "chatterly-test" }));
      expect(wp.subscribePush).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("the OS checkbox: off drops the relay's row; on subscribes from the tap", async () => {
    const user = await openSettings();
    const box = screen.getByRole("checkbox", { name: "OS notification when tab is unfocused" });
    expect(box).toBeChecked();
    await user.click(box);
    expect(wp.unsubscribePush).toHaveBeenCalledTimes(1);
    expect(wp.subscribePush).not.toHaveBeenCalled();
    await user.click(box);
    expect(wp.subscribePush).toHaveBeenCalledWith(expect.objectContaining({ osPing: true }));
  });

  it("permission denied: says alerts are blocked and where to allow them, not the generic failure", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "denied" }));
    wp.subscribePush.mockRejectedValueOnce(new DOMException("Registration failed - permission denied", "NotAllowedError"));
    try {
      const user = await openSettings();
      await user.click(screen.getByRole("button", { name: "Test" }));
      expect(await screen.findByText(DENIED_MSG)).toBeInTheDocument();
      expect(DENIED_MSG).toMatch(/site settings.*Settings > Notifications/);
      expect(Notification).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("an iPhone / iPad Safari tab (not installed): Add to Home Screen first, no subscribe", async () => {
    wp.ios = true;
    wp.supported = false; // a tab there has no PushManager
    const user = await openSettings();
    await user.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText(IOS_TAB_MSG)).toBeInTheDocument();
    expect(IOS_TAB_MSG).toMatch(/Add to Home Screen/);
    expect(wp.subscribePush).not.toHaveBeenCalled();
  });

  it("push wanted, never asked (permission default), not live: the panel says to tap Test", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default" }));
    try {
      relayGet.mockResolvedValue({ list: [] });
      renderWithProviders(<NotificationBell />);
      await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
      expect(await screen.findByRole("button", { name: "Tap Test to enable lock-screen alerts" })).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("granted, live: no hint", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "granted" }));
    wp.state.id = "sub-1";
    try {
      relayGet.mockResolvedValue({ list: [] });
      renderWithProviders(<NotificationBell />);
      await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
      await screen.findByText("No notifications.");
      expect(screen.queryByRole("button", { name: "Tap Test to enable lock-screen alerts" })).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("a lazy subscribe that failed: the panel says to tap Test", async () => {
    wp.state.failed = "Registration failed - permission denied";
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
    await userEvent.click(await screen.findByRole("button", { name: "Tap Test to enable lock-screen alerts" }));
    expect(screen.getByRole("button", { name: "Test" })).toBeInTheDocument();
  });
});
