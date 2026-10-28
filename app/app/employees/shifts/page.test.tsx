/**
 * The `/employees/shifts` route module itself renders the Shift schedule
 * (docs/spec/phase-02-shifts-time-tracking.md, Testing Decisions, seam 2):
 * the week query fires, so the page cannot pass while it mounts nothing or
 * the "not built yet" placeholder. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { SIDEBAR, isDivider, visibleSidebar } from "@/lib/nav";

let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", () => { const v = () => ({ user: session.user, loading: false }); return { useUser: v, useOptionalUser: v }; });
vi.mock("@/contexts/ChatterContext", () => { const v = () => ({ chatter: session.chatter }); return { useChatter: v, useOptionalChatter: v }; });
// The Shift schedule reads the week start from the Applied settings (spec phase-04, story 20).
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

import Page from "@/app/employees/shifts/page";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
  fetchMock = vi.fn(async (url: string) => {
    const path = String(url).split("?")[0];
    if (path === "/admin/shifts") return jsonRes({ occurrences: [] });
    if (path === "/admin/employees") return jsonRes({ employees: [] });
    if (path === "/admin/accounts") return jsonRes({ accounts: [], active_account_id: null });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const weekQueries = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).split("?")[0] === "/admin/shifts");

describe("/employees/shifts", () => {
  it("renders the Shift schedule and its week query fires", async () => {
    renderWithProviders(<Page />);
    expect(screen.getByRole("heading", { name: "Shift schedule" })).toBeInTheDocument();
    await waitFor(() => expect(weekQueries()).toHaveLength(1));
    expect(screen.getByRole("button", { name: "This week" })).toBeInTheDocument();
    expect(screen.queryByText(/not built yet/i)).toBeNull();
  });

  it("shows a chatter the owner-only message", async () => {
    session = { user: null, chatter: { username: "chatter" } };
    renderWithProviders(<Page />);
    expect(screen.getByText("Only the agency owner manages the Shift schedule.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(weekQueries()).toEqual([]);
  });

  it("keeps the Employees group, and so the Shift schedule link, hidden from a chatter", () => {
    const labels = (chatterOnly: boolean) =>
      visibleSidebar(SIDEBAR, { chatterOnly, grantedPages: null }).flatMap((n) => (isDivider(n) ? [] : [n.label]));
    expect(labels(false)).toContain("Employees");
    expect(labels(true)).not.toContain("Employees");
  });
});
