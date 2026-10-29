/**
 * BootSkeleton — the page's frame a signed-in session sees before the app knows its principal: the route's layout
 * with labels and placeholder bars, never a figure (no "$0.00" standing in for a number).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import BootSkeleton from "@/components/shell/BootSkeleton";
import { control, PERIOD_TABS } from "@/components/home/dashboardControls";

afterEach(cleanup);

const route = () => document.querySelector("[data-boot-skeleton]")?.getAttribute("data-boot-skeleton");

describe("BootSkeleton", () => {
  it("the Dashboard: the period tabs and the earnings card's labels from the Dashboard's catalogue, a bar per figure", () => {
    render(<BootSkeleton pathname="/" />);
    expect(route()).toBe("dashboard");
    for (const k of ["title", "total", "subscriptions", "tips", "posts", "referrals", "messages", "streams"] as const) {
      expect(screen.getByText(control(k).labels[0])).toBeTruthy();
    }
    for (const t of PERIOD_TABS) expect(screen.getByText(t.labels[0])).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/\$|\d/);
    // Total earnings and the six channel tiles each hold a placeholder bar.
    expect(document.querySelectorAll("[data-loading]").length).toBeGreaterThanOrEqual(7);
    expect(screen.getByRole("status").textContent).toBe("Loading");
  });

  it("Messages Pro: its own window (no top bar), the Fan List's skeleton rows", () => {
    render(<BootSkeleton pathname="/messages-pro" />);
    expect(route()).toBe("messages-pro");
    expect(screen.getByRole("list", { name: "Loading conversations" }).children.length).toBe(6);
    expect(document.querySelector(".sticky.top-0")).toBeNull();
  });

  it("a Deep link is Messages Pro too", () => {
    render(<BootSkeleton pathname="/messages-pro/123/456" />);
    expect(route()).toBe("messages-pro");
  });

  it("any other page: the shell's top bar, its sidebar label as the header, table rows", () => {
    render(<BootSkeleton pathname="/creators" />);
    expect(route()).toBe("page");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Manage creators");
    expect(document.querySelectorAll("[data-loading]").length).toBeGreaterThan(20);
  });

  it("a page with no sidebar label holds a bar in the title's place", () => {
    render(<BootSkeleton pathname="/no-such-page" />);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(route()).toBe("page");
  });
});
