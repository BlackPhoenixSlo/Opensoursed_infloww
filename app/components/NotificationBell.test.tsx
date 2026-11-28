import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, relayPost } = vi.hoisted(() => ({
  relayGet: vi.fn(),
  relayPost: vi.fn(async (..._args: unknown[]): Promise<unknown> => ({ counters: { all: 0 } })),
}));

vi.mock("@/lib/relay", () => ({
  relay: { get: (...args: unknown[]) => relayGet(...args), post: (...args: unknown[]) => relayPost(...args) },
}));
type Acc = { id: string; nickname: string; session_dead_at?: string; platform?: string };
const ONE: Acc[] = [{ id: "acc-1", nickname: "Creator One" }];
const scope = vi.hoisted(() => ({ accountId: "acc-1" as string | null, accounts: [] as Acc[] }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => scope.accounts }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: scope.accountId }) }));
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
vi.mock("./NotificationQuickReply", async () => {
  const { useState } = await import("react");
  return {
    QuickReplyField: ({ name }: { name: string }) => {
      const [text, setText] = useState("");
      return <input aria-label={`Reply to ${name}`} value={text} onChange={(e) => setText(e.target.value)} />;
    },
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

import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { NOTIF_CLEARED_EVENT, appendNotifHistory, dispatchNotifArrived, markNotifHistoryResponded } from "@/lib/notifSettings";
import { armRead, resetReadGate } from "@/lib/ofReadGate";
import { NotificationBell, Row } from "./NotificationBell";
import { DENIED_MSG, IOS_TAB_MSG } from "./OsPingSettings";

beforeEach(() => {
  scope.accountId = "acc-1";
  scope.accounts = ONE;
  resetReadGate();
  armRead("acc-1");
});

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

  it("a Creator not armed yet: nothing read while closed; opening reads it once, a reopen serves the cache", async () => {
    resetReadGate();
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    expect(relayGet).not.toHaveBeenCalled();
    const bell = screen.getByRole("button", { name: "Notifications" });

    await user.click(bell);
    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    const reads = () => relayGet.mock.calls.filter(([p]) => String(p).startsWith("/api/of/v2/users/notifications")).length;
    expect(reads()).toBe(1);

    await user.click(bell);
    await user.click(bell);
    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    expect(reads()).toBe(1);
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

      await user.click(bell);
      expect(cleared).toHaveBeenCalledTimes(1);
      await user.click(bell);
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

describe("NotificationBell (OF mark-read)", () => {
  const PRO = { button: "", icon: "", badge: "", panel: "" };
  const READ = "/api/of/v2/users/notifications/read";
  const countSeven = () => relayGet.mockImplementation(async (path: string) =>
    String(path).startsWith("/api/of/v2/users/notifications/count") ? { all: 7 } : { list: [] });
  const posts = () => relayPost.mock.calls.filter(([p]) => p === READ);
  const button = () => screen.getByRole("button", { name: /^Notifications/ });

  it("open sends exactly one mark-read for the scoped Creator; the badge drops to OF's counters", async () => {
    countSeven();
    relayPost.mockResolvedValueOnce({ counters: { all: 2, tip: 2 } });
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    expect(await screen.findByText("7")).toBeInTheDocument();

    await userEvent.click(button());
    await screen.findByText("No notifications.");
    await userEvent.click(screen.getByRole("button", { name: "Tips" }));

    expect(posts()).toEqual([[READ, undefined, { accountId: "acc-1" }]]);
    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(screen.queryByText("7")).toBeNull();
  });

  it("each open sends one more; none while closed", async () => {
    countSeven();
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    await userEvent.click(button());
    await userEvent.keyboard("{Escape}");
    expect(posts()).toHaveLength(1);
    await userEvent.click(button());
    expect(posts()).toHaveLength(2);
  });

  it("a failed mark-read leaves the badge", async () => {
    countSeven();
    relayPost.mockRejectedValueOnce(new Error("502"));
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    expect(await screen.findByText("7")).toBeInTheDocument();
    await userEvent.click(button());
    await screen.findByText("No notifications.");
    expect(posts()).toHaveLength(1);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("a list read that failed sends no mark-read: nothing was shown to be read", async () => {
    relayGet.mockImplementation(async (path: string) => {
      if (String(path).startsWith("/api/of/v2/users/notifications/count")) return { all: 7 };
      throw new Error("OF 502");
    });
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    expect(await screen.findByText("7")).toBeInTheDocument();
    await userEvent.click(button());
    await screen.findByText(/OF 502/);
    expect(posts()).toHaveLength(0);
  });

  it("closed while its list is still loading: no mark-read, then or after the list lands (W30-mu #48)", async () => {
    let answer!: (v: unknown) => void;
    relayGet.mockImplementation(async (path: string) => {
      if (String(path).startsWith("/api/of/v2/users/notifications/count")) return { all: 7 };
      return new Promise((r) => { answer = r; });
    });
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    expect(await screen.findByText("7")).toBeInTheDocument();
    await userEvent.click(button());
    await waitFor(() => expect(answer).toBeTypeOf("function"));
    await userEvent.keyboard("{Escape}");
    await act(async () => { answer({ list: [] }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(posts()).toHaveLength(0);
  });

  it("the top bar opening on Agency sends nothing until the OnlyFans tab shows", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationBell agency={{ unread: 2, settings: null, panel: <p>Agency feed</p> }} />);
    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
    await screen.findByText("Agency feed");
    expect(posts()).toHaveLength(0);
    await userEvent.click(screen.getByRole("tab", { name: "OnlyFans" }));
    expect(posts()).toHaveLength(1);
  });
});

describe("NotificationBell (Messages Pro, All Models)", () => {
  const PRO = { button: "", icon: "", badge: "", panel: "" };
  const READ = "/api/of/v2/users/notifications/read";
  const posted = () => relayPost.mock.calls.filter(([p]) => p === READ)
    .map(([, , ctx]) => (ctx as { accountId: string }).accountId);
  const button = () => screen.getByRole("button", { name: /^Notifications/ });
  const badge = () => button().querySelector("span")?.textContent ?? null;

  const ACCOUNTS: Acc[] = [
    { id: "acc-1", nickname: "One" }, { id: "acc-2", nickname: "Two" }, { id: "acc-3", nickname: "Three" },
    { id: "acc-4", nickname: "Four" }, { id: "acc-dead", nickname: "Dead", session_dead_at: "2026-11-01" },
  ];
  const COUNTS: [string, number][] = [["acc-1", 3], ["acc-2", 0], ["acc-3", 4], ["acc-dead", 9]];

  function setup(accounts: Acc[] = ACCOUNTS, counts: [string, number][] = COUNTS) {
    scope.accountId = null;
    scope.accounts = accounts;
    relayGet.mockResolvedValue({ list: [] });
    const client = makeTestQueryClient();
    for (const [id, n] of counts) client.setQueryData(["of-notif-count", id], n);
    return renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />, client);
  }

  it("badge = the live Creators' cached counts; follows the cache; opening sends no write", async () => {
    const { queryClient } = setup();
    expect(badge()).toBe("7");
    act(() => { queryClient.setQueryData(["of-notif-count", "acc-4"], 5); });
    await waitFor(() => expect(badge()).toBe("12"));

    await userEvent.click(button());
    await screen.findByText("No notifications.");
    expect(posted()).toEqual([]);
    expect(relayGet.mock.calls.some(([p]) => String(p).includes("/notifications/count"))).toBe(false);
  });

  it("Mark all read: one write per live Creator not at 0, serially; busy meanwhile; the badge drops per write", async () => {
    setup();
    const pending: (() => void)[] = [];
    relayPost.mockImplementation(() => new Promise((res) => pending.push(() => res({ counters: { all: 0 } }))));
    await userEvent.click(button());
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));

    const busy = screen.getByRole("button", { name: "Marking…" });
    expect(busy).toBeDisabled();
    await userEvent.click(busy);
    expect(posted()).toEqual(["acc-1"]);

    await act(async () => { pending.shift()!(); });
    expect(posted()).toEqual(["acc-1", "acc-3"]);
    await waitFor(() => expect(badge()).toBe("4"));
    await act(async () => { pending.shift()!(); });
    expect(posted()).toEqual(["acc-1", "acc-3", "acc-4"]);
    await act(async () => { pending.shift()!(); });

    await waitFor(() => expect(badge()).toBeNull());
    expect(posted()).toEqual(["acc-1", "acc-3", "acc-4"]);
    expect(await screen.findByRole("button", { name: "Mark all read" })).toBeEnabled();
  });

  it("a failed write leaves that Creator's count and the run goes on", async () => {
    setup();
    relayPost.mockImplementation(async (_p, _b, ctx) => {
      if ((ctx as { accountId: string }).accountId === "acc-3") throw new Error("502");
      return { counters: { all: 0 } };
    });
    await userEvent.click(button());
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));

    expect(await screen.findByRole("button", { name: "Mark all read" })).toBeEnabled();
    expect(posted()).toEqual(["acc-1", "acc-3", "acc-4"]);
    await waitFor(() => expect(badge()).toBe("4"));
    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 Creators failed");
  });

  it("a cached 0 read before the last arrival is written too (it may be stale)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.setSystemTime(Date.now() + 60_000);
      setup();
      act(() => { vi.setSystemTime(Date.now() + 1_000); dispatchNotifArrived(); });
      relayPost.mockResolvedValue({ counters: { all: 0 } });
      await userEvent.click(button());
      await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
      await waitFor(() => expect(posted()).toEqual(["acc-1", "acc-2", "acc-3", "acc-4"]));
    } finally {
      vi.useRealTimers();
    }
  });

  it("a Fansly Creator: opening sends no mark-read", async () => {
    scope.accountId = "acc-f";
    scope.accounts = [{ id: "acc-f", nickname: "Fansly One", platform: "fansly" }];
    armRead("acc-f");
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationBell variant="messages-pro" classNames={PRO} />);
    await userEvent.click(button());
    await screen.findByText("No notifications.");
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(posted()).toEqual([]);
  });

  it("mixed scope: Mark all read writes only the OnlyFans Creators and reports no failure", async () => {
    setup(
      [{ id: "acc-1", nickname: "One", platform: "onlyfans" }, { id: "acc-f", nickname: "Fan", platform: "fansly" }],
      [["acc-1", 3], ["acc-f", 5]],
    );
    relayPost.mockResolvedValue({ counters: { all: 0 } });
    expect(badge()).toBe("8");
    await userEvent.click(button());
    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    expect(await screen.findByRole("button", { name: "Mark all read" })).toBeEnabled();
    expect(posted()).toEqual(["acc-1"]);
    await waitFor(() => expect(badge()).toBe("5"));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("Fansly-only scope: no Mark all read button", async () => {
    setup(
      [{ id: "acc-f", nickname: "Fan", platform: "fansly" }, { id: "acc-g", nickname: "Gan", platform: "fansly" }],
      [["acc-f", 5]],
    );
    await userEvent.click(button());
    await screen.findByText("No notifications.");
    expect(screen.queryByRole("button", { name: "Mark all read" })).toBeNull();
    expect(posted()).toEqual([]);
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
    expect(screen.getAllByRole("button", { name: "Reply" })).toHaveLength(1);
  });
});

describe("NotificationBell (quick reply)", () => {
  it("a row whose props move to another Fan (an id-less row arrived above) never carries the typed line over", async () => {
    const msg = (fan: number) => ({ type: "message", user: { id: fan, name: `Fan ${fan}` }, text: "hi" });
    const { rerender } = renderWithProviders(<Row n={msg(7)} accountId="acc-1" accountLabel={null} reply />);
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    await userEvent.type(await screen.findByLabelText("Reply to Fan 7"), "for seven");
    rerender(<Row n={msg(8)} accountId="acc-1" accountLabel={null} reply />);
    const other = screen.queryByLabelText("Reply to Fan 8") as HTMLInputElement | null;
    expect(other?.value ?? "").toBe("");
  });
});

describe("NotificationBell (Agency pane)", () => {
  it("closes when an Agency row's in-app link is followed", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(
      <NotificationBell agency={{ unread: 1, settings: null, panel: <a href="/creators?relink=browserbase" onClick={(e) => e.preventDefault()}>Zoe needs a 2FA code</a> }} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
    await userEvent.click(await screen.findByRole("link", { name: "Zoe needs a 2FA code" }));

    expect(screen.queryByRole("link", { name: "Zoe needs a 2FA code" })).toBeNull();
  });

  it("OnlyFans arrivals while the panel shows the Agency tab badge the bell once it closes; on the OnlyFans tab they don't", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell agency={{ unread: 2, settings: null, panel: <p>Agency feed</p> }} />);
    expect(await screen.findByTestId("bell-count")).toHaveTextContent("2");

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Agency feed")).toBeInTheDocument();
    act(() => { dispatchNotifArrived(); });
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Agency feed")).toBeNull();
    expect(screen.getByTestId("bell-count")).toHaveTextContent("3");

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("No notifications.")).toBeInTheDocument();
    act(() => { dispatchNotifArrived(); });
    await user.keyboard("{Escape}");
    expect(screen.getByTestId("bell-count")).toHaveTextContent("2");
  });

  it("the Agency tab going away while it is shown puts the OnlyFans list on screen", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<NotificationBell agency={{ unread: 2, settings: null, panel: <p>Agency feed</p> }} />);
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
    await user.click(await screen.findByRole("tab", { name: "Settings" }));
    return user;
  }

  it("Test with push: subscribes from the tap, shows through the service worker, then offers the delayed push", async () => {
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default", requestPermission: vi.fn() }));
    try {
      const user = await openSettings();
      await user.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText(/✓ Push on: lock screen alerts active/)).toBeInTheDocument();
      expect(wp.subscribePush).toHaveBeenCalledTimes(1);
      expect(Notification.requestPermission).not.toHaveBeenCalled();
      expect(wp.showViaWorker).toHaveBeenCalledWith("Inflowwww test", expect.objectContaining({ tag: "chatterly-test" }));
      expect(Notification).not.toHaveBeenCalled();

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
    wp.supported = false;
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
