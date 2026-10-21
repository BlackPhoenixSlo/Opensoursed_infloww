/**
 * The Audit log tab (roadmap W6 6.16): the server's readable label over the
 * raw method + path, and a from/to day filter sent as UTC bounds (`to` is the
 * next local midnight, so its day is included).
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/hooks/useRoster", () => ({ useRoster: () => ({ rows: [] }) }));

import { renderWithProviders } from "@/test-utils";
import { relay } from "@/lib/relay";
import AuditTab, { dayBound } from "@/components/settings/AuditTab";

const get = relay.get as unknown as Mock;
afterEach(() => { cleanup(); get.mockReset(); });

describe("AuditTab", () => {
  it("shows the label beside the raw action, and the raw action alone when unmapped", async () => {
    get.mockResolvedValue({ limit: 50, offset: 0, actions: [
      { id: 2, employee_id: null, account_id: null, action: "DELETE /admin/employees/4", label: "Deactivated an employee",
        target_type: null, target_id: null, payload: null, at: "2026-10-20T10:00:00" },
      { id: 1, employee_id: null, account_id: null, action: "POST /admin/zzz", label: null,
        target_type: null, target_id: null, payload: null, at: "2026-10-20T09:00:00" },
    ] });
    renderWithProviders(<AuditTab />);
    expect(await screen.findByText("Deactivated an employee")).toBeInTheDocument();
    expect(screen.getByText("DELETE /admin/employees/4")).toBeInTheDocument();
    expect(screen.getByText("POST /admin/zzz")).toBeInTheDocument();
  });

  it("sends the picked days as from/to bounds", async () => {
    get.mockResolvedValue({ limit: 50, offset: 0, actions: [] });
    renderWithProviders(<AuditTab />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-03" } });
    await waitFor(() => {
      const qs = new URLSearchParams(String(get.mock.lastCall?.[0]).split("?")[1]);
      expect(qs.get("from")).toBe(new Date(2026, 9, 1).toISOString());
      expect(qs.get("to")).toBe(new Date(2026, 9, 4).toISOString());
    });
  });

  it("dayBound ignores an empty or partial day", () => {
    expect(dayBound("", 0)).toBe("");
    expect(dayBound("2026-10", 1)).toBe("");
  });
});
