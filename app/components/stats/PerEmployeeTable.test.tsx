/**
 * PerEmployeeTable, an Inflowwww extra on Employee reports (page-parity ticket 27): the per-Creator breakdown with
 * its $0 and totals-only toggles. The sales settings notice moved to the page (EmployeeReport) and the table's own
 * Export went (README Phase 2, P2-3: Chatting statistics' Export, Display by creator, writes the same lines).
 *
 * Rendered with the relay mocked at `fetch` by URL. Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

import PerEmployeeTable from "@/components/stats/PerEmployeeTable";

const EMPLOYEES = [
  { employee_id: 1, display_name: "Alpha One", messages_sent: 40, ppv_conversions: 3, revenue_cents: 12345,
    revenue_by_kind: { ppv: 10000, tip: 2345 },
    per_account: [
      { account_id: "c1", account_nickname: "Creator, One", messages_sent: 30, ppv_conversions: 2, revenue_cents: 10000,
        revenue_by_kind: { ppv: 8000, tip: 2000 } },
    ] },
  { employee_id: null, display_name: "Unattributed", messages_sent: 0, ppv_conversions: 0, revenue_cents: 500,
    revenue_by_kind: { ppv: 0, tip: 500 }, per_account: [] },
  { employee_id: 2, display_name: "Beta", messages_sent: 5, ppv_conversions: 0, revenue_cents: 0,
    revenue_by_kind: { ppv: 0, tip: 0 }, per_account: [] },
];

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://relay.test");
    if (u.pathname !== "/admin/stats/per-employee") return jsonRes({ detail: "unmocked" }, 404);
    return jsonRes({ employees: EMPLOYEES, attribution_fallback: "Shift schedule needs Time tracking on." });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PerEmployeeTable", () => {
  it("lists the Employees with revenue and their total, with no notice and no Export of its own", async () => {
    renderWithProviders(<PerEmployeeTable from="2026-10-01T00:00:00.000Z" to="2026-10-31T23:59:59.999Z" />);
    await screen.findByText("Alpha One");
    const table = screen.getByRole("table");
    // Beta's $0 row is hidden ("Hide $0 rows" is on).
    expect(within(table).queryByText("Beta")).toBeNull();
    expect(within(table).getByText("Total (2)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(screen.queryByText(/based on your organization's sales settings/)).toBeNull();
    expect(screen.queryByText("Shift schedule needs Time tracking on.")).toBeNull();
  });

  it("shows the $0 rows when asked", async () => {
    renderWithProviders(<PerEmployeeTable from="2026-10-01T00:00:00.000Z" to="2026-10-31T23:59:59.999Z" />);
    await screen.findByText("Alpha One");
    fireEvent.click(screen.getByRole("checkbox", { name: "Hide $0 rows" }));
    await waitFor(() => expect(within(screen.getByRole("table")).getByText("Beta")).toBeInTheDocument());
  });
});
