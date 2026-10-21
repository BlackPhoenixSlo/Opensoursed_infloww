/**
 * EmployeeReport's frame (page-parity ticket 27; live `.scratch/infloww-live/08-employee-reports.png`): the
 * sales-settings bar once above the page-level tabs, the tabs Overview / Sales records / Employee performance by the
 * role's pages, `?tab=performance`, and Sales records as its own route.
 *
 * Rendered with `fetch` mocked by URL (unmocked reads answer 404, which each card shows as its error); the router's
 * `push` and the role's granted pages are mocked. Sales records' body is a stub: ticket 28 owns it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/analytics/employee-reports",
  // The URL as it stands: a test moves it with `history` and rerenders, as Back does.
  useSearchParams: () => new URLSearchParams(window.location.search),
  useParams: () => ({}),
}));
/** The role's granted pages (`useGrantedPages`); null is every page. */
const role = vi.hoisted(() => ({ pages: null as Set<string> | null }));
vi.mock("@/components/shell/useGrantedPages", () => ({
  useGrantedPages: () => role.pages,
  useActionAllowed: () => true,
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: { user_id: "o", username: "owner" }, loading: false }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null }) }));
vi.mock("@/components/analytics/SalesRecords", () => ({ default: () => <p>Sales records body</p> }));

import EmployeeReport from "@/components/stats/EmployeeReport";

const EMPLOYEE_PAGE = "/analytics/employee-reports";
const SALES_PAGE = "/analytics/sales-records";
const NOTICE = "The sales data is based on your organization's sales settings.";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  role.pages = null;
  fetchMock = vi.fn(async (url: string) => {
    const path = String(url).split("?")[0];
    if (path === "/admin/settings/applied") {
      return jsonRes({ preferences: { tz: null, report_tz: null, week_start: "monday" },
        messaging: { ai_translation: true }, permissions: { enforced: false, pages: null, scope: "all" } });
    }
    if (path === "/admin/stats/chatting-stats") {
      return jsonRes({ employees: [], attribution_fallback: null, series: [], by_employee: {} });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  push.mockReset();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const tabNames = () => within(screen.getByRole("tablist", { name: "Employee reports" })).getAllByRole("tab")
  .map((t) => t.textContent);

describe("EmployeeReport frame", () => {
  it("shows the sales-settings bar once, above the three tabs, linking to the sales settings", async () => {
    renderWithProviders(<EmployeeReport />);
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    const link = screen.getByRole("link", { name: "View sales settings" });
    expect(link).toHaveAttribute("href", "/settings/sales");
    const tablist = screen.getByRole("tablist", { name: "Employee reports" });
    expect(screen.getByText(NOTICE).compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tabNames()).toEqual(["Overview", "Sales records", "Employee performance"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    // Overview's body: the charts, Chatting statistics with its cards, and the one extras heading.
    expect(await screen.findByRole("region", { name: "Employee sales" })).toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "Total sales" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Inflowwww extras" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Date range/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Shown by" })).toBeInTheDocument();
  });

  it("leaves Sales records out for a role without its page", () => {
    role.pages = new Set([EMPLOYEE_PAGE]);
    renderWithProviders(<EmployeeReport />);
    expect(tabNames()).toEqual(["Overview", "Employee performance"]);
  });

  it("gives a role with Sales records alone the frame with that one tab", () => {
    role.pages = new Set([SALES_PAGE]);
    renderWithProviders(<EmployeeReport tab="sales" />);
    expect(tabNames()).toEqual(["Sales records"]);
    expect(screen.getByText("Sales records body")).toBeInTheDocument();
    // Sales records brings its own toolbar: no range box or Shown by in the tab bar.
    expect(screen.queryByRole("combobox", { name: "Shown by" })).toBeNull();
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });

  it("opens Employee performance from ?tab=performance", async () => {
    window.history.replaceState(null, "", `${EMPLOYEE_PAGE}?tab=performance`);
    renderWithProviders(<EmployeeReport />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "Employee performance" }))
      .toHaveAttribute("aria-selected", "true"));
    expect(await screen.findByText("No chatting in this window.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Inflowwww extras" })).toBeNull();
  });

  it("pushes each tab's URL: Sales records to its own route", () => {
    renderWithProviders(<EmployeeReport />);
    fireEvent.click(screen.getByRole("tab", { name: "Sales records" }));
    expect(push).toHaveBeenLastCalledWith(SALES_PAGE);
    fireEvent.click(screen.getByRole("tab", { name: "Employee performance" }));
    expect(push).toHaveBeenLastCalledWith(`${EMPLOYEE_PAGE}?tab=performance`);
    cleanup();
    window.history.replaceState(null, "", `${EMPLOYEE_PAGE}?tab=performance`);
    renderWithProviders(<EmployeeReport />);
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(push).toHaveBeenLastCalledWith(EMPLOYEE_PAGE);
  });

  it("follows the URL back from Employee performance to Overview (the Back button)", async () => {
    window.history.replaceState(null, "", `${EMPLOYEE_PAGE}?tab=performance`);
    const { rerender } = renderWithProviders(<EmployeeReport />);
    expect(screen.getByRole("tab", { name: "Employee performance" })).toHaveAttribute("aria-selected", "true");
    act(() => window.history.replaceState(null, "", EMPLOYEE_PAGE));
    rerender(<EmployeeReport />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("region", { name: "Inflowwww extras" })).toBeInTheDocument();
  });

  it("sends no Chatting statistics read on Sales records", async () => {
    role.pages = new Set([SALES_PAGE]);
    renderWithProviders(<EmployeeReport tab="sales" />);
    expect(screen.getByText("Sales records body")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/settings/applied")))
      .toBe(true));
    // Past the Applied settings answer, when the range is ready and a read would go out.
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/stats/chatting-stats"))).toBe(false);
  });

  it("asks for the Chatter role's Employees from the checkbox in Chatting statistics' title row", async () => {
    renderWithProviders(<EmployeeReport />);
    const card = await screen.findByRole("region", { name: "Chatting statistics" });
    fireEvent.click(within(card).getByRole("checkbox", { name: "Show employees with chatter role only" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => {
      const q = new URL(String(u), "http://relay.test");
      return q.pathname === "/admin/stats/per-employee" && q.searchParams.get("chatter_only") === "true";
    })).toBe(true));
  });
});
