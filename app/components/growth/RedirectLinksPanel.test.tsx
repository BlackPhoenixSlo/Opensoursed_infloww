import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const growth = vi.hoisted(() => ({
  botAvailable: false,
  create: vi.fn(),
}));

vi.mock("@/hooks/useGrowth", () => ({
  useTrackingLinks: () => ({
    data: {
      links: [{ id: 1, account_id: "a1", name: "Bio", slug: "bio", target_url: "https://x.test", click_count: 3,
        bot_check: true, path: "/t/bio", created_at: null }],
      bot_check_available: growth.botAvailable,
    },
    isLoading: false,
  }),
  useTrackingSummary: () => ({ data: undefined, isError: false }),
  useDeleteTrackingLink: () => ({ mutateAsync: vi.fn() }),
  useUpdateTrackingLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useCreateTrackingLink: () => ({ mutateAsync: growth.create, isPending: false }),
}));
vi.mock("@/hooks/useAccounts", () => ({ useGrowthCreator: () => ({ accountId: "a1", setAccountId: vi.fn() }) }));
vi.mock("@/components/growth/LinksListFrame", () => ({
  CreatorFilter: () => null,
  GrowthHbFrame: ({ children }: { children: React.ReactNode }) => children,
  RowMenu: () => null,
}));
vi.mock("@/components/growth/RedirectLinkStats", () => ({ LinkStats: () => null, ClickSparkline: () => null }));

import { RedirectLinksPanel } from "./RedirectLinksPanel";

beforeEach(() => {
  growth.botAvailable = false;
  growth.create.mockReset();
});
afterEach(cleanup);

const clicksTip = () => screen.getByLabelText(/^Clicks on the Creator's redirect links/);

describe("RedirectLinksPanel", () => {
  it("no Turnstile keys: the Clicks tip makes no passed-checks claim", () => {
    render(<RedirectLinksPanel accountId="a1" onAccountChange={() => {}} />);
    expect(clicksTip().getAttribute("aria-label")).not.toMatch(/passed checks/);
  });

  it("bot check available: passed checks only, since it was turned on", () => {
    growth.botAvailable = true;
    render(<RedirectLinksPanel accountId="a1" onAccountChange={() => {}} />);
    expect(clicksTip().getAttribute("aria-label")).toMatch(/passed checks only since the bot check was turned on/);
  });

  it("Enter pressed again while Create is in flight sends one link", async () => {
    growth.create.mockReturnValue(new Promise(() => {}));
    render(<RedirectLinksPanel accountId="a1" onAccountChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Create redirect link/ }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Tree" } });
    fireEvent.change(screen.getByLabelText("Target URL"), { target: { value: "linktr.ee/x" } });
    const form = screen.getByLabelText("Name").closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(growth.create).toHaveBeenCalledTimes(1);
  });
});
