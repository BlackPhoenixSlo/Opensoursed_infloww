/**
 * NotificationsPage: the full page at /notifications reached from the bell's
 * "See all" (docs/spec/phase-05-remaining-parity-gaps.md, stories 40-44,
 * Testing Decisions): the eight tabs, Tips / Mark all read / gear Not wired,
 * the same request (path and Creator scope) as the bell for the same tab, and
 * "Load more" advancing the offset on a single-type tab.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, scope, accounts, router, accountsQ } = vi.hoisted(() => ({
  relayGet: vi.fn(),
  accountsQ: { isLoading: false },
  router: { push: vi.fn(), back: vi.fn() },
  scope: { accountId: "acc-1" as string | null },
  accounts: [
    { id: "acc-1", nickname: "Creator One" },
    { id: "acc-2", nickname: "Creator Two" },
  ],
}));

vi.mock("@/lib/relay", () => ({ relay: { get: (...args: unknown[]) => relayGet(...args) } }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => accounts, useAccounts: () => accountsQ }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/notifications",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

import { renderWithProviders } from "@/test-utils";
import { NotificationBell } from "./NotificationBell";
import NotificationsPage from "./NotificationsPage";

const FEED = "/api/of/v2/users/notifications?";

afterEach(() => {
  cleanup();
  relayGet.mockReset();
  router.push.mockReset();
  router.back.mockReset();
  scope.accountId = "acc-1";
  localStorage.clear();
});

/** The feed reads made so far, as [path, accountId]. */
const feedReads = () => relayGet.mock.calls
  .filter(([path]) => String(path).startsWith(FEED))
  .map(([path, ctx]) => [String(path), (ctx as { accountId?: string } | undefined)?.accountId]);

/** `n` rows of one type, newest first, about placeholder Fans. */
const rows = (n: number, from = 0) => Array.from({ length: n }, (_, i) => ({
  id: from + i + 1,
  type: "subscribed",
  text: "subscribed to you",
  createdAt: new Date(Date.UTC(2026, 9, 1) - (from + i) * 60_000).toISOString(),
  user: { id: 9000 + from + i, name: `Fan ${from + i + 1}` },
}));

const WIRED = ["All", "Subscriptions", "Purchases", "Comments", "Mentions", "Likes", "Messages"];

/** Clicks each wired tab of the bell's open panel and returns its feed reads. */
async function bellReads(): Promise<string[][]> {
  renderWithProviders(<NotificationBell />);
  await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
  for (const label of WIRED) await userEvent.click(screen.getByRole("button", { name: label }));
  await screen.findByText("No notifications.");
  const reads = feedReads();
  cleanup();
  relayGet.mockClear();
  return reads as string[][];
}

async function pageReads(): Promise<string[][]> {
  renderWithProviders(<NotificationsPage />);
  for (const label of WIRED) await userEvent.click(screen.getByRole("tab", { name: label }));
  await screen.findByText("No notifications");
  return feedReads() as string[][];
}

describe("NotificationsPage", () => {
  it("shows Back, the title, the OnlyFans notifications section and the eight tabs in Infloww's order", () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationsPage />);

    expect(screen.getByLabelText("Back")).toHaveAttribute("aria-label", "Back");
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OnlyFans notifications" })).toBeInTheDocument();
    expect(within(screen.getByRole("tablist")).getAllByRole("tab").map((t) => t.textContent)).toEqual(
      ["All", "Subscriptions", "Purchases", "Tips", "Comments", "Mentions", "Likes", "Messages"],
    );
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  });

  it("Tips, Mark all read and the gear are Not wired: disabled, titled \"not wired\", and Tips reads nothing", async () => {
    relayGet.mockResolvedValue({ list: [] });
    renderWithProviders(<NotificationsPage />);
    await screen.findByText("No notifications");

    for (const el of [
      screen.getByRole("tab", { name: "Tips" }),
      screen.getByRole("button", { name: "Mark all read" }),
      screen.getByRole("button", { name: "Notification settings" }),
    ]) {
      expect(el).toBeDisabled();
      expect(el).toHaveAttribute("title", "not wired");
    }
    expect(screen.getByRole("tab", { name: "Tips" })).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Tips" }));
    expect(feedReads().some(([path]) => String(path).includes("type=tip"))).toBe(false);
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  });

  it("issues the bell's request (path and Creator scope) for every wired tab, for one Creator", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const bell = await bellReads();
    const page = await pageReads();

    expect(page).toContainEqual([`${FEED}limit=20&offset=0`, "acc-1"]);
    expect(page).toContainEqual([`${FEED}limit=20&offset=0&type=commented`, "acc-1"]);
    expect(new Set(page.map((r) => r.join(" ")))).toEqual(new Set(bell.map((r) => r.join(" "))));
  });

  it("issues the bell's request for each active Creator under All Creators", async () => {
    scope.accountId = null;
    relayGet.mockResolvedValue({ list: [] });
    const bell = await bellReads();
    const page = await pageReads();

    expect(page).toContainEqual([`${FEED}limit=20&offset=0&type=favorited`, "acc-2"]);
    expect(new Set(page.map((r) => r.join(" ")))).toEqual(new Set(bell.map((r) => r.join(" "))));
  });

  it("\"Load more\" on a single-type tab reads the next 20 by offset and appends them", async () => {
    relayGet.mockImplementation(async (path: string) =>
      path.includes("type=subscribed")
        ? { list: path.includes("offset=20") ? rows(5, 20) : rows(20) }
        : { list: [] });
    renderWithProviders(<NotificationsPage />);
    await screen.findByText("No notifications");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    expect(await screen.findByText("Fan 20")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Fan 25")).toBeInTheDocument();
    expect(screen.getByText("Fan 1")).toBeInTheDocument();
    expect(feedReads()).toContainEqual([`${FEED}limit=20&offset=20&type=subscribed`, "acc-1"]);
    // A short page is the end of the feed.
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("\"Load more\" under All Creators reads the next 20 only for a Creator whose last page was full", async () => {
    scope.accountId = null;
    relayGet.mockImplementation(async (path: string, ctx?: { accountId?: string }) => {
      if (!path.includes("type=subscribed")) return { list: [] };
      if (ctx?.accountId === "acc-2") return { list: path.includes("offset=0") ? rows(3, 100) : [] };
      return { list: path.includes("offset=20") ? rows(5, 20) : rows(20) };
    });
    renderWithProviders(<NotificationsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    expect(await screen.findByText("Fan 101")).toBeInTheDocument();
    expect(await screen.findByText("Fan 20")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Fan 25")).toBeInTheDocument();
    expect(screen.getByText("Fan 103")).toBeInTheDocument();
    expect(feedReads()).toContainEqual([`${FEED}limit=20&offset=20&type=subscribed`, "acc-1"]);
    // acc-2's first page was short: its feed has ended, so it is not read again.
    expect(feedReads().filter(([path, aid]) => aid === "acc-2" && String(path).includes("offset=20"))).toEqual([]);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("shows the error state when the feed fails, and Retry reads the feed again", async () => {
    relayGet.mockRejectedValue(new Error("Relay unreachable"));
    renderWithProviders(<NotificationsPage />);
    expect(await screen.findByText("Relay unreachable")).toBeInTheDocument();

    relayGet.mockResolvedValue({ list: rows(1) });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Fan 1")).toBeInTheDocument();
  });

  it("shows the no-session state, with a link to Manage creators, when no Creator has a session", () => {
    scope.accountId = null;
    accounts.splice(0, accounts.length);
    try {
      renderWithProviders(<NotificationsPage />);
      expect(screen.getByText("No active sessions. Capture one in Manage creators to see notifications.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Manage creators" })).toHaveAttribute("href", "/creators");
      expect(relayGet).not.toHaveBeenCalled();
    } finally {
      accounts.push({ id: "acc-1", nickname: "Creator One" }, { id: "acc-2", nickname: "Creator Two" });
    }
  });

  it("while the Creators load: the rows' placeholder bars, not the no-session state", () => {
    scope.accountId = null;
    accounts.splice(0, accounts.length);
    accountsQ.isLoading = true;
    try {
      renderWithProviders(<NotificationsPage />);
      expect(screen.queryByText(/No active sessions/)).toBeNull();
      expect(screen.getByRole("status", { name: "Loading notifications" }).querySelectorAll("[data-loading]").length).toBe(3);
    } finally {
      accountsQ.isLoading = false;
      accounts.push({ id: "acc-1", nickname: "Creator One" }, { id: "acc-2", nickname: "Creator Two" });
    }
  });

  it("Back goes back in history, or to / when the page has no history", async () => {
    relayGet.mockResolvedValue({ list: [] });
    const historyLength = (n: number) =>
      Object.defineProperty(window.history, "length", { configurable: true, get: () => n });
    try {
      renderWithProviders(<NotificationsPage />);
      historyLength(3);
      await userEvent.click(screen.getByLabelText("Back"));
      expect(router.back).toHaveBeenCalledTimes(1);
      expect(router.push).not.toHaveBeenCalled();

      historyLength(1);
      await userEvent.click(screen.getByLabelText("Back"));
      expect(router.push).toHaveBeenCalledWith("/");
      expect(router.back).toHaveBeenCalledTimes(1);
    } finally {
      delete (window.history as { length?: number }).length;
    }
  });
});
