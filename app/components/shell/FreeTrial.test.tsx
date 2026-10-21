/**
 * The top bar's free-trial days left, the "trial has started" banner (while
 * the trial runs, its close remembered per principal), and the expired-trial
 * nag: shown on mount (an app start), closable, never remembered across mounts.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let user: { user_id?: string; username: string; created_at?: string | null } | null = null;
let chatter: { chatter_id?: string; username: string; created_at?: string | null } | null = null;
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter }) }));

import { FreeTrialBadge, FreeTrialBanner, FreeTrialExpiredModal } from "@/components/shell/FreeTrial";

const DAY = 24 * 60 * 60 * 1000;
const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();

afterEach(() => {
  cleanup();
  user = null;
  chatter = null;
  localStorage.clear();
});

describe("FreeTrialBadge", () => {
  it("shows the days left from the owner's registration", () => {
    user = { username: "owner", created_at: daysAgo(2.5) };
    render(<FreeTrialBadge />);
    expect(screen.getByText("You’re on a free trial")).toBeInTheDocument();
    expect(screen.getByText("5 days left")).toBeInTheDocument();
  });

  it("counts a chatter's trial from the chatter's own registration", () => {
    chatter = { username: "tim", created_at: daysAgo(6.5) };
    render(<FreeTrialBadge />);
    expect(screen.getByText("1 day left")).toBeInTheDocument();
  });

  it("is hidden once the trial is over or with no registration time", () => {
    user = { username: "owner", created_at: daysAgo(8) };
    const { container, rerender } = render(<FreeTrialBadge />);
    expect(container).toBeEmptyDOMElement();
    user = { username: "owner" };
    rerender(<FreeTrialBadge />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("FreeTrialBanner", () => {
  const banner = () => screen.queryByText("Your 7-day free trial has started.");

  it("shows under the top bar while the trial runs, marked so the chrome grows", () => {
    user = { user_id: "u1", username: "owner", created_at: daysAgo(1) };
    render(<FreeTrialBanner />);
    expect(banner()).toBeInTheDocument();
    expect(document.querySelector("[data-trial-banner]")).not.toBeNull();
  });

  it("closes, and the close sticks for that principal only", () => {
    user = { user_id: "u1", username: "owner", created_at: daysAgo(1) };
    const first = render(<FreeTrialBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Close banner" }));
    expect(banner()).toBeNull();
    expect(document.querySelector("[data-trial-banner]")).toBeNull();
    first.unmount();

    render(<FreeTrialBanner />);
    expect(banner()).toBeNull();
    cleanup();

    user = null;
    chatter = { chatter_id: "c1", username: "tim", created_at: daysAgo(1) };
    render(<FreeTrialBanner />);
    expect(banner()).toBeInTheDocument();
  });

  it("is hidden once the trial is over", () => {
    user = { user_id: "u1", username: "owner", created_at: daysAgo(8) };
    const { container } = render(<FreeTrialBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("FreeTrialExpiredModal", () => {
  it("does not show while the trial runs", () => {
    user = { username: "owner", created_at: daysAgo(1) };
    render(<FreeTrialExpiredModal />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows on every start once expired, links to buy, and closes to carry on", () => {
    user = { username: "owner", created_at: daysAgo(10) };
    const first = render(<FreeTrialExpiredModal />);
    expect(screen.getByRole("dialog", { name: "Free trial exceeded" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "click here to buy" })).toHaveAttribute(
      "href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    );
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    first.unmount();

    // The next start nags again.
    render(<FreeTrialExpiredModal />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
