/**
 * EmployeesTab paging: ten a page, and a filter change from page 2 lands on page 1 in one action (usePagedFilters).
 * The relay is mocked at `fetch` by URL, as ManageEmployees.test.tsx does; every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import { ChatterProvider } from "@/contexts/ChatterContext";
import EmployeesTab from "@/components/settings/EmployeesTab";

vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

/** 24 logins: "Staff 00" to "Staff 11" active, "Temp 00" to "Temp 11" deactivated, so By status keeps 12 (two pages). */
const ROSTER = [
  ...Array.from({ length: 12 }, (_, k) => ({ name: `Staff ${String(k).padStart(2, "0")}`, active: true })),
  ...Array.from({ length: 12 }, (_, k) => ({ name: `Temp ${String(k).padStart(2, "0")}`, active: false })),
].map(({ name, active }, i) => ({
  id: i + 1, display_name: name, color: "#777777", is_active: active, chatter_id: `c${i + 1}`,
  username: `u${i + 1}`, account_ids: null, group_id: null,
}));

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "ownerone" });
    if (url === "/chatter/me") return jsonRes({ detail: "no" }, 401);
    if (url === "/admin/employees?include_disabled=true") return jsonRes({ employees: ROSTER });
    if (url === "/admin/accounts") return jsonRes({ accounts: [], active_account_id: null });
    if (url === "/admin/settings/roles") return jsonRes({ tab: "roles", config: { roles: [] } });
    if (url === "/admin/chatters/invites") return jsonRes([]);
    if (url === "/admin/employee-groups") return jsonRes({ groups: [] });
    return jsonRes({ detail: "unmocked" }, 404);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const names = () => [...document.querySelectorAll("tr[data-employee]")].map((r) => r.getAttribute("data-employee"));
const pager = () => screen.getByRole("navigation", { name: "Pagination" });
const currentPage = () =>
  within(pager()).getAllByRole("button").find((b) => b.getAttribute("aria-current") === "page")?.textContent;

describe("EmployeesTab paging", () => {
  it("a filter change on page 2 goes back to page 1", async () => {
    renderWithProviders(<UserProvider><ChatterProvider><EmployeesTab /></ChatterProvider></UserProvider>);
    await waitFor(() => expect(names()).toHaveLength(10));
    expect(pager()).toHaveTextContent("Total: 24 employees");

    fireEvent.click(within(pager()).getByRole("button", { name: "Page 2" }));
    expect(currentPage()).toBe("2");
    expect(names()[0]).toBe("Staff 10");

    // By status: Activated keeps 12, so page 2 still exists; the filter alone moves the page.
    const status = screen.getByRole("combobox", { name: "By status" });
    fireEvent.click(status);
    fireEvent.click(within(document.getElementById(status.getAttribute("aria-controls")!)!).getByRole("option", { name: "Activated" }));

    expect(pager()).toHaveTextContent("Total: 12 employees");
    expect(currentPage()).toBe("1");
    expect(names()).toEqual(Array.from({ length: 10 }, (_, k) => `Staff ${String(k).padStart(2, "0")}`));
  });
});
