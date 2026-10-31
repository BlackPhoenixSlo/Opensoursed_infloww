/**
 * Below lg the sidebar is an off-canvas drawer: the top bar's toggle opens
 * it, Escape closes it, and so does navigating to another route.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { username: "owner" }, logout: vi.fn() }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null, logout: vi.fn() }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null, clear: vi.fn() }) }));
vi.mock("@/components/NotificationBell", () => ({ NotificationBell: () => null }));
vi.mock("@/components/AgencyNotifications", () => ({ useAgencyUnread: () => null, AgencyFeed: () => null }));
vi.mock("@/components/ErrorBadge", () => ({ ErrorBadge: () => null }));
vi.mock("@/components/shifts/ClockButton", () => ({
  default: () => null,
  // A marker: ClockButton.test covers what the heartbeat sends.
  ClockHeartbeat: () => <span data-testid="clock-heartbeat" />,
}));
// The time-zone label's Applied settings read: nothing stored, so the browser's zone.
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({ data: undefined }),
  useAgencyTimeZone: () => Intl.DateTimeFormat().resolvedOptions().timeZone,
}));
// The platform selector and gate read accounts and roster counts (PlatformSwitcher.test covers them).
vi.mock("@/components/shell/PlatformSwitcher", () => ({
  default: () => null,
  usePlatformUnread: () => ({ onlyfans: 0, fansly: 0 }),
  unreadLabel: String,
}));
vi.mock("@/components/shell/PlatformGate", () => ({ default: () => null, PlatformSync: () => null }));

import AppShell from "@/components/shell/AppShell";
import { settled } from "@/test-utils";

beforeEach(() => {
  pathname = "/";
  // Phone width: (min-width: 1024px) never matches.
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

// While the modal drawer is open Radix aria-hides the rest of the page.
const toggle = () => screen.getByRole("button", { name: "Toggle sidebar", hidden: true });

describe("AppShell drawer below lg", () => {
  it("opens from the top bar toggle and closes on Escape", () => {
    render(<AppShell>page</AppShell>);
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(toggle()).toHaveAttribute("aria-controls", "app-sidebar-drawer");

    fireEvent.click(toggle());
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    expect(dialog).toHaveAttribute("id", "app-sidebar-drawer");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on a swipe left on the drawer or its backdrop, not on a swipe right", async () => {
    // A 160px drawer (the test DOM has no layout): a 150px drag carries it past 75%.
    const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(160);
    render(<AppShell>page</AppShell>);
    const pt = (x: number) => ({ clientX: x, clientY: 300 });
    const swipe = (el: Element, x0: number, x1: number) => {
      fireEvent.touchStart(el, { touches: [pt(x0)], changedTouches: [pt(x0)] });
      fireEvent.touchMove(el, { touches: [pt(x1)], changedTouches: [pt(x1)] });
      fireEvent.touchEnd(el, { touches: [], changedTouches: [pt(x1)] });
    };
    fireEvent.click(toggle());
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    swipe(dialog, 100, 250);
    await settled();
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
    swipe(dialog, 250, 100);
    await settled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");

    // The backdrop (the page beside the drawer) closes it too.
    fireEvent.click(toggle());
    swipe(document.querySelector("[data-state='open'].fixed.inset-0")!, 350, 200);
    await settled();
    expect(screen.queryByRole("dialog")).toBeNull();
    width.mockRestore();
  });

  it("opens on a swipe right from mid-screen; not from the OS edge zone, a scroll, a field, or over a dialog", () => {
    render(<AppShell><input aria-label="field" /></AppShell>);
    const swipe = (el: Element, x0: number, x1: number, y1 = 300) => {
      fireEvent.touchStart(el, { touches: [{ clientX: x0, clientY: 300 }], changedTouches: [{ clientX: x0, clientY: 300 }] });
      fireEvent.touchMove(el, { touches: [{ clientX: x1, clientY: y1 }], changedTouches: [{ clientX: x1, clientY: y1 }] });
      fireEvent.touchEnd(el, { touches: [], changedTouches: [{ clientX: x1, clientY: y1 }] });
    };
    const page = main();
    swipe(page, 10, 200);                      // iOS / Android back zone
    swipe(page, 150, 160, 600);                // a vertical scroll
    swipe(screen.getByLabelText("field"), 150, 300);
    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    document.body.appendChild(modal);
    swipe(page, 150, 300);
    modal.remove();
    expect(screen.queryByRole("dialog")).toBeNull();

    swipe(page, 150, 300);
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
  });

  it("closes when the route changes", () => {
    const { rerender } = render(<AppShell>page</AppShell>);
    fireEvent.click(toggle());
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();

    pathname = "/analytics/fan-reports";
    act(() => rerender(<AppShell>page</AppShell>));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

/** Desktop width: (min-width: 1024px) matches. */
const desktop = () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
};

const main = () => document.querySelector("main")!;

describe("AppShell swipe to open, off a phone", () => {
  it("no swipe opens the drawer at desktop width or on Messages Pro", () => {
    const swipe = () => {
      fireEvent.touchStart(main(), { touches: [{ clientX: 150, clientY: 300 }], changedTouches: [{ clientX: 150, clientY: 300 }] });
      fireEvent.touchMove(main(), { touches: [{ clientX: 300, clientY: 300 }], changedTouches: [{ clientX: 300, clientY: 300 }] });
      fireEvent.touchEnd(main(), { touches: [], changedTouches: [{ clientX: 300, clientY: 300 }] });
    };
    pathname = "/messages-pro";
    const { unmount } = render(<AppShell>page</AppShell>);
    swipe();
    expect(screen.queryByRole("dialog")).toBeNull();
    unmount();

    pathname = "/";
    desktop();
    render(<AppShell>page</AppShell>);
    swipe();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("AppShell on Messages Pro: a window of its own (ADR-0002)", () => {
  for (const [width, setWidth] of [["desktop", desktop], ["phone", () => {}]] as const) {
    for (const path of ["/messages-pro", "/messages-pro/acc1/123"]) {
      it(`on ${path} at ${width} width only the page renders: no Top bar, sidebar or toggle, and --shell-top is 0`, () => {
        setWidth();
        pathname = path;
        const { container } = render(<AppShell>page</AppShell>);
        expect(screen.queryByRole("banner")).toBeNull();
        expect(container.querySelector("#app-sidebar")).toBeNull();
        expect(screen.queryByRole("button", { name: "Toggle sidebar" })).toBeNull();
        expect(main().style.getPropertyValue("--shell-top")).toBe("0px");
        expect(main()).toHaveTextContent("page");
        // No Clock button here, so the clock's heartbeat runs headless (w4-a).
        expect(screen.getByTestId("clock-heartbeat")).toBeInTheDocument();
      });
    }
  }

  it("the sidebar's Messages Pro row and rail icon open the one named Messages Pro window, and this page stays put", () => {
    desktop();
    const popup = { location: { pathname: "blank", search: "", href: "about:blank" }, focus: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    const { container } = render(<AppShell>page</AppShell>);
    const sidebar = container.querySelector("#app-sidebar") as HTMLElement;
    // No separate pop-out arrow: the row itself opens the window.
    expect(sidebar.querySelector('a[aria-label="Open Messages Pro in a new tab"]')).toBeNull();
    const row = [...sidebar.querySelectorAll("a")].find((a) => a.textContent === "Messages Pro")!;
    expect(row).toHaveAttribute("href", "/messages-pro");

    fireEvent.click(row);
    expect(open).toHaveBeenCalledWith("", "messages-pro", expect.stringContaining("popup"));
    expect(popup.location.href).toBe("/messages-pro");
    expect(popup.focus).toHaveBeenCalled();
    expect(screen.getByRole("banner")).toBeInTheDocument();

    // A second click finds the window showing Messages Pro: focus it, no reload.
    popup.location = { pathname: "/messages-pro/acc1/123", search: "", href: "kept" };
    fireEvent.click(row);
    expect(open).toHaveBeenCalledTimes(2);
    expect(popup.location.href).toBe("kept");

    // The collapsed rail's icon does the same.
    fireEvent.click(toggle());
    fireEvent.click(sidebar.querySelector('a[aria-label="Messages Pro"]')!);
    expect(open).toHaveBeenCalledTimes(3);
    expect(popup.location.href).toBe("kept");
    open.mockRestore();
  });

  it("the Messages Pro row carries the platform's unread chip, at 0 too, and a button opening one more window", () => {
    desktop();
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { container } = render(<AppShell>page</AppShell>);
    const sidebar = container.querySelector("#app-sidebar") as HTMLElement;
    expect(sidebar.querySelector('[aria-label="0 unread"]')).toHaveTextContent("0");
    const extra = screen.getByRole("button", { name: "Open another Messages Pro window" });
    // A sibling of the row's link, never nested in it.
    expect(extra.closest("a")).toBeNull();
    fireEvent.click(extra);
    expect(open).toHaveBeenCalledWith("/messages-pro", "_blank", expect.stringContaining("popup"));
    open.mockRestore();
  });

  describe("in the desktop app's main window (no opener, not named messages-pro)", () => {
    const realLocation = window.location;
    const replace = vi.fn();
    const popup = { location: { pathname: "blank", search: "", href: "about:blank" }, focus: vi.fn() };
    let open: ReturnType<typeof vi.spyOn>;
    const at = (path: string, search = "") => {
      pathname = path;
      Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, search, replace } });
    };
    beforeEach(() => {
      replace.mockClear();
      popup.location.href = "about:blank";
      open = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
      window.fasttShell = { isDesktop: true };
    });
    afterEach(() => {
      open.mockRestore();
      delete window.fasttShell;
      window.name = "";
      Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    });

    it("Messages Pro (the shell's old /inbox start, a restored route) goes to the Dashboard and opens no window", () => {
      at("/messages-pro");
      render(<AppShell>page</AppShell>);
      expect(replace).toHaveBeenCalledWith("/");
      expect(open).not.toHaveBeenCalled();
    });

    it("a Deep link (a notification, an app link) opens in the Messages Pro window, then the Dashboard loads", () => {
      at("/messages-pro/acc1/123", "?x=1");
      render(<AppShell>page</AppShell>);
      expect(open).toHaveBeenCalledWith("", "messages-pro", expect.stringContaining("popup"));
      expect(popup.location.href).toBe("/messages-pro/acc1/123?x=1");
      expect(replace).toHaveBeenCalledWith("/");
    });

    it("the Messages Pro window itself, and Messages Pro on the web, stay put", () => {
      at("/messages-pro/acc1/123");
      window.name = "messages-pro";
      const { unmount } = render(<AppShell>page</AppShell>);
      unmount();
      window.name = "";
      delete window.fasttShell;
      render(<AppShell>page</AppShell>);
      expect(replace).not.toHaveBeenCalled();
      expect(open).not.toHaveBeenCalled();
    });
  });

  // The error triage badge beside the pill (ErrorBadge, mocked here) has its own test.
  it("the top bar keeps the Inflowwww wordmark, shows the Operational pill, and the content sits in the rounded panel", () => {
    desktop();
    render(<AppShell>page</AppShell>);
    expect(screen.getByRole("link", { name: "Inflowwww" })).toHaveAttribute("href", "/");
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(main()).toHaveClass("bg-bg", "rounded-tl-xl", "overflow-clip");
  });

  it("on / the toggle still collapses the docked sidebar", () => {
    desktop();
    const { container } = render(<AppShell>page</AppShell>);
    expect(container.querySelector("#app-sidebar")).toHaveClass("lg:flex");
    expect(toggle()).toHaveAttribute("aria-controls", "app-sidebar");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(toggle());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    // Collapsed is Infloww's icon rail, not gone: still shown, 60px, icons named for screen readers.
    const rail = container.querySelector("#app-sidebar") as HTMLElement;
    expect(rail).toHaveClass("lg:flex", "w-[60px]");
    expect(rail.querySelector('a[aria-label="Dashboard"]')).not.toBeNull();
    expect(rail.textContent).not.toContain("Dashboard");
  });
});

describe("AppShell on OF Manager from lg up: Infloww's icon rail", () => {
  it("docks the sidebar as the 60px rail, locked: the toggle is disabled", () => {
    desktop();
    pathname = "/of-manager/home";
    const { container } = render(<AppShell>page</AppShell>);
    const rail = container.querySelector("#app-sidebar")!;
    expect(rail).toHaveClass("lg:flex", "w-[60px]");
    // Icons only: the labels are names, not text, and the version line is gone.
    expect(rail).not.toHaveTextContent("Dashboard");
    expect(rail).not.toHaveTextContent(/Version/);
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(toggle()).toBeDisabled();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle());
    expect(rail).toHaveClass("w-[60px]");
  });

  it("opens a group's pages in a flyout on hover, marks the current one, and closes on Escape", () => {
    vi.useFakeTimers();
    try {
      desktop();
      pathname = "/of-manager/home";
      render(<AppShell>page</AppShell>);
      const group = screen.getByRole("button", { name: "OF Manager" });
      expect(group).toHaveAttribute("aria-expanded", "false");

      fireEvent.mouseEnter(group);
      act(() => vi.advanceTimersByTime(100));
      const flyout = screen.getByRole("menu", { name: "OF Manager" });
      expect(group).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("menuitem", { name: "Home" })).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("menuitem", { name: "Vault" })).toHaveAttribute("href", "/of-manager/vault");

      fireEvent.keyDown(flyout, { key: "Escape" });
      expect(screen.queryByRole("menu")).toBeNull();

      // Leaving closes it after the same delay.
      fireEvent.click(group);
      expect(screen.getByRole("menu")).toBeInTheDocument();
      fireEvent.mouseLeave(group);
      act(() => vi.advanceTimersByTime(100));
      expect(screen.queryByRole("menu")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("below lg OF Manager keeps the full sidebar in the drawer", () => {
    pathname = "/of-manager/home";
    render(<AppShell>page</AppShell>);
    expect(toggle()).not.toBeDisabled();
    fireEvent.click(toggle());
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    expect(dialog.querySelector(".w-\\[60px\\]")).toBeNull();
    expect(dialog).toHaveTextContent("Dashboard");
  });

  it("Settings docks the same locked rail", () => {
    desktop();
    pathname = "/settings/account";
    const { container } = render(<AppShell>page</AppShell>);
    const rail = container.querySelector("#app-sidebar")!;
    expect(rail).toHaveClass("lg:flex", "w-[60px]");
    expect(rail).not.toHaveTextContent("Dashboard");
    expect(toggle()).toBeDisabled();
  });

  it("other pages keep the full sidebar", () => {
    desktop();
    pathname = "/analytics/fan-reports";
    const { container } = render(<AppShell>page</AppShell>);
    const sidebar = container.querySelector("#app-sidebar")!;
    expect(sidebar).toHaveClass("w-64");
    expect(sidebar).toHaveTextContent("Dashboard");
    expect(toggle()).not.toBeDisabled();
    // The user's own collapse still folds it to the rail, as on main.
    fireEvent.click(toggle());
    expect(sidebar).toHaveClass("w-[60px]");
  });
});
