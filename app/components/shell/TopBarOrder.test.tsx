/**
 * The top bar's right-hand order follows Infloww's header (bundle @11162567, `index$c`): the static "Operational"
 * pill, then our error triage badge (two items, not one), … SFW, the bell, the Clock button (`HeaderSignButton`),
 * then the avatar (`HeaderSetting`). There is no model filter, and one bell (the agency centre is a tab of its
 * panel, AgencyNotifications.test). The items are Infloww's borderless filled tiles: the time zone a tile with
 * the globe and ⓘ that opens Your Preferences, SFW a bare caption over its switch. Checked against the live
 * app in w5-a. The neighbours are stubbed so only TopBar's own order and look are under test.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/shifts/ClockButton", () => ({ default: () => <button type="button">Clock in</button> }));
vi.mock("@/components/NotificationBell", () => ({ NotificationBell: () => <button type="button">Notifications</button> }));
vi.mock("@/components/AgencyNotifications", () => ({ useAgencyUnread: () => null, AgencyFeed: () => null }));
vi.mock("@/components/ErrorBadge", () => ({ ErrorBadge: () => <button type="button" aria-label="Recent errors" /> }));
vi.mock("@/components/shell/FreeTrial", () => ({ FreeTrialBadge: () => null, FreeTrialBanner: () => null }));
vi.mock("@/hooks/useBlurMode", () => ({ useSfw: () => [false, () => {}] }));
vi.mock("@/hooks/useTheme", () => ({ useTheme: () => ({ theme: "dark", toggle: () => {} }) }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { username: "owner" }, logout: async () => {} }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null, logout: async () => {} }) }));
vi.mock("@/lib/appliedSettings", () => ({ useAgencyTimeZone: () => "UTC" }));

import TopBar from "@/components/shell/TopBar";

describe("TopBar order", () => {
  it("puts the Clock button after the bell and before the avatar, as Infloww's header", () => {
    render(<TopBar onToggleSidebar={() => {}} sidebarExpanded sidebarId="sidebar" />);
    const names = screen.getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent);
    const at = (n: string) => names.indexOf(n);
    expect(at("SFW")).toBeGreaterThan(-1);
    expect([at("SFW") < at("Notifications"), at("Notifications") < at("Clock in"), at("Clock in") < at("Account menu")])
      .toEqual([true, true, true]);
  });

  it("splits the Operational pill from the error triage badge, and has no model filter", () => {
    render(<TopBar onToggleSidebar={() => {}} sidebarExpanded sidebarId="sidebar" />);
    const pill = screen.getByText("Operational");
    const badge = screen.getByRole("button", { name: "Recent errors" });
    expect(pill.closest("button")).toBeNull();
    expect(pill.compareDocumentPosition(badge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTitle(/All models/)).toBeNull();
    expect(screen.queryByText("All")).toBeNull();
  });

  it("draws one bell and borderless filled tiles: the time zone with its globe and info icons, SFW as caption over switch", () => {
    const { container } = render(<TopBar onToggleSidebar={() => {}} sidebarExpanded sidebarId="sidebar" />);
    expect(screen.getAllByRole("button", { name: /notifications/i })).toHaveLength(1);
    const tz = screen.getByTitle("Your time zone");
    expect(tz).toHaveAttribute("href", "/settings/preferences");
    expect(tz).toHaveTextContent("UTC+00:00");
    expect(tz).toHaveClass("bg-nav-surface", "rounded-lg", "h-9");
    expect(tz.querySelectorAll("svg")).toHaveLength(2);
    expect(screen.getByTitle("The regular time zone you selected in Settings")).toBeInTheDocument();
    const sfw = screen.getByRole("button", { name: "SFW" });
    expect(sfw).toHaveClass("flex-col");
    expect(sfw).toHaveTextContent("SFW");
    expect(container.querySelector("header [class~='border']")).toBeNull();
  });
});
