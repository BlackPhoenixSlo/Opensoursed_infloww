import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, params, searchParams } = vi.hoisted(() => {
  const params = { search: "" };
  // Next keeps the same URLSearchParams per navigation; a fresh one per render re-runs the page's URL->state effect and resets the clicked tab.
  let cached = { key: "\u0000", value: new URLSearchParams() };
  return {
    relayGet: vi.fn(),
    params,
    searchParams: () => {
      if (cached.key !== params.search) {
        cached = { key: params.search, value: new URLSearchParams(params.search) };
      }
      return cached.value;
    },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/analytics/message-dashboard",
  useSearchParams: () => searchParams(),
  useParams: () => ({}),
}));

vi.mock("@/lib/relay", () => ({
  relay: {
    get: (...args: unknown[]) => relayGet(...args),
    post: vi.fn(async () => ({})),
  },
  proxyImage: () => "",
}));

vi.mock("@/contexts/UserContext", async (orig) => {
  const value = { user: { username: "owner" }, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: () => value, useOptionalUser: () => value };
});

vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({ isPending: false, data: { preferences: { report_tz: "UTC" } } }),
}));

vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));

vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [],
  useAccounts: () => ({ data: [], isLoading: false }),
}));

import { renderWithProviders } from "@/test-utils";
import MessagesPage from "./page";

const OWED = {
  marked: true,
  account_id: "100000001",
  account_name: "Test Creator",
  fan_id: 200000002,
  display_name: "Test Fan",
  tip_cents: 12000,
  tipped_at: "2026-08-26T00:02:46Z",
  lifetime_spend_cents: 22182,
  chat_href: "/messages-pro/100000001/200000002",
};

beforeEach(() => {
  params.search = "";
  relayGet.mockReset();
  relayGet.mockImplementation(async (path: string) => {
    if (String(path).startsWith("/admin/customs")) {
      return { customs: [OWED], untracked: [] };
    }
    return { rows: [], items: [], next_cursor: null };
  });
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  });
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the Message dashboard page", () => {
  it("is called Message dashboard and spans the shell width", () => {
    const { container } = renderWithProviders(<MessagesPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Message dashboard");
    expect(container.querySelector(".max-w-shell")).not.toBeNull();
  });

  it("opens on Direct messages, with Infloww's two tabs first and ours after the extra tag", () => {
    renderWithProviders(<MessagesPage />);
    const labels = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(labels).toEqual([
      "Direct messages", "OnlyFans mass messages",
      "PPV", "Tips", "All", "Customs", "Posts", "My Feed", "Top Posts",
    ]);
    expect(screen.getByRole("tab", { name: "Direct messages" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("form", { name: "Message filters" })).toBeInTheDocument();
    expect(screen.getByTitle("Inflowwww extra")).toBeInTheDocument();
  });

  it.each([
    ["mass", "OnlyFans mass messages"],
    ["ppv", "PPV"],
    ["tips", "Tips"],
    ["all", "All"],
    ["customs", "Customs"],
    ["posts", "Posts"],
    ["myfeed", "My Feed"],
    ["top", "Top Posts"],
  ])("?tab=%s opens %s", (key, label) => {
    params.search = `tab=${key}`;
    renderWithProviders(<MessagesPage />);
    expect(screen.getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Direct messages" })).toHaveAttribute("aria-selected", "false");
  });

  it("fills Sent to from ?fan_id= and reads that fan's direct messages", async () => {
    params.search = "fan_id=7";
    renderWithProviders(<MessagesPage />);
    expect(screen.getByRole("textbox", { name: "Sent to" })).toHaveValue("#7");
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith(expect.stringContaining("fan_id=7")));
    const path = relayGet.mock.calls.map(([p]) => String(p)).find((p) => p.includes("fan_id=7"));
    expect(path).toContain("kind=direct");
  });

  it("keeps the Top Tippers rail off Infloww's tabs and on Tips", () => {
    renderWithProviders(<MessagesPage />);
    expect(screen.queryByText("Top Tippers")).toBeNull();
    cleanup();
    params.search = "tab=tips";
    renderWithProviders(<MessagesPage />);
    expect(screen.getByText("Top Tippers")).toBeInTheDocument();
  });

  it("opens the owed-customs queue when the tab is clicked", async () => {
    renderWithProviders(<MessagesPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Customs" }));

    expect(await screen.findByText("Customs owed")).toBeInTheDocument();
    expect(await screen.findByText("Test Fan")).toBeInTheDocument();
    expect(relayGet).toHaveBeenCalledWith("/admin/customs");
  });

  it("deep-links straight into the queue, which is where /customs lands", async () => {
    params.search = "tab=customs";
    renderWithProviders(<MessagesPage />);
    await waitFor(() => expect(screen.getByText("Customs owed")).toBeInTheDocument());
  });

  it("exports the whole filtered Tips list and every top tipper as CSV, with no page limit (roadmap 1.16)", async () => {
    const hrefs: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      hrefs.push(this.getAttribute("href") ?? "");
    });
    params.search = "tab=tips";
    renderWithProviders(<MessagesPage />);
    await userEvent.click(await screen.findByTitle("Download the filtered tips as CSV (up to 50,000 rows)"));
    await userEvent.click(screen.getByTitle("Download every tipper in this window as CSV (up to 50,000 rows)"));

    const [tips, tippers] = hrefs.map((h) => new URL(h, "http://app.test"));
    expect(tips.pathname).toBe("/admin/tips-list");
    expect(tippers.pathname).toBe("/admin/top-tippers");
    for (const u of [tips, tippers]) {
      expect(u.searchParams.get("format")).toBe("csv");
      expect(u.searchParams.get("from")).toBeTruthy();
      expect(u.searchParams.get("to")).toBeTruthy();
      expect(u.searchParams.has("limit")).toBe(false);
    }
  });
});
