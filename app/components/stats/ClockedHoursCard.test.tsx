/**
 * ClockedHoursCard — Employee reports' "Clocked hours" (docs/spec/phase-05-remaining-parity-gaps.md, item 2,
 * stories 14-18).
 *
 * Rendered with the relay mocked at `fetch` by URL: `/admin/shifts/clocked-in` answers the Agency's
 * time-tracking flag and `/admin/shifts/timesheet` Phase 2's rollup, so the request, the rows, the empty states
 * and the Export CSV are assertions about the wire. The expected hours and CSV text are worked by hand from the
 * fixture's minutes and cents. Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

let principal: "owner" | "master" | "chatter";
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({
    user: principal === "owner" ? { user_id: "owner-1", username: "owner" }
      : principal === "master" ? { user_id: "master-1", username: "master", is_admin: true }
      : null,
    loading: false,
  }),
}));

// The Clocked hours modal (w4-a) reads the Agency's zone.
vi.mock("@/lib/appliedSettings", () => ({ useAgencyTimeZone: () => "UTC" }));
/** Function permissions the role denies (`useActionAllowed`); none unless a case adds one. */
const denied = vi.hoisted(() => new Set<string>());
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: (action: string) => !denied.has(action) }));

import ClockedHoursCard from "@/components/stats/ClockedHoursCard";

const FROM = "2026-09-15T04:00:00.000Z";
const TO = "2026-10-15T03:59:59.999Z";

/** 450 minutes is 7h 30min (7.50 h); 61 minutes is 1h 1min (1.02 h, 1.0166… rounded). */
const ROWS = [
  { key: "1", display_name: "Alpha One", scheduled_shifts: 4, shifts_worked: 3, scheduled_minutes: 960,
    worked_minutes: 450, recorded_earnings_cents: 12345, open_now: false, employee_id: 1, group_name: null },
  { key: "2", display_name: "Beta, Night", scheduled_shifts: 2, shifts_worked: 1, scheduled_minutes: 480,
    worked_minutes: 61, recorded_earnings_cents: 0, open_now: true, employee_id: 2, group_name: "Night" },
];

let tracking: boolean;
let rows: typeof ROWS;
/** A Timesheet refusal to answer instead of the rows, or null for the rows. */
let refusal: { status: number; detail: string } | null;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  principal = "owner";
  tracking = true;
  rows = ROWS;
  refusal = null;
  fetchMock = vi.fn(async (url: string) => {
    const path = String(url).split("?")[0];
    if (path === "/admin/shifts/clocked-in") return jsonRes({ time_tracking_enabled: tracking, clocked_in: [] });
    if (path === "/admin/shifts/clock-events") return jsonRes({ clock_events: [] });
    if (path === "/admin/shifts/timesheet") {
      return refusal ? jsonRes({ detail: refusal.detail }, refusal.status) : jsonRes({ rows });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  denied.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Every Timesheet request sent so far. */
function timesheetCalls(): URL[] {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/shifts/timesheet");
}

const render = () => renderWithProviders(<ClockedHoursCard from={FROM} to={TO} />);

describe("ClockedHoursCard", () => {
  it("requests the Timesheet by employee for the chosen range and shows one row per Employee", async () => {
    render();
    const table = await screen.findByRole("table");
    const [req, ...more] = timesheetCalls();
    expect(more).toHaveLength(0);
    expect(req.searchParams.get("group")).toBe("employee");
    expect(req.searchParams.get("from")).toBe(FROM);
    expect(req.searchParams.get("to")).toBe(TO);

    const body = within(table).getAllByRole("row").slice(1);
    expect(body.map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["Alpha One", "4", "3", "7h 30min", "$123"],
      ["Beta, Night", "2", "1", "1h 1min", "$0"],
    ]);
    expect(within(table).getByText("Recorded earnings")).toHaveAttribute(
      "title",
      "Infloww calls this Total Earnings. Earnings already credited during worked time; not payroll.",
    );
  });

  it("puts Infloww's rounding tooltip on the Clocked hours header (w4-a)", async () => {
    render();
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Clocked hours" })).toHaveAttribute(
      "title", "Number of hours worked based on clocked time, rounded up to the nearest minute",
    );
  });

  it("opens that Employee's Clocked hours modal from its Clocked hours cell, over the report's range (w4-a)", async () => {
    render();
    const table = await screen.findByRole("table");
    fireEvent.click(within(table).getByRole("button", { name: "1h 1min" }));
    const dialog = await screen.findByRole("dialog", { name: "Clocked hours" });
    expect(within(dialog).getByText("Beta, Night")).toBeInTheDocument();
    expect(await within(dialog).findByText("No data")).toBeInTheDocument();
    const req = fetchMock.mock.calls
      .map(([url]) => new URL(String(url), "http://relay.test"))
      .find((u) => u.pathname === "/admin/shifts/clock-events")!;
    expect(req.searchParams.get("employee_id")).toBe("2");
    expect(req.searchParams.get("from")).toBe("2026-09-15T04:00:00.000Z");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows Total by employee as the working view and the other three views Not wired", async () => {
    render();
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: "Total by employee" })).toHaveAttribute("aria-pressed", "true");
    for (const name of [
      "Total creators by day (daily) by employee",
      "Total by creator by employee",
      "By creator by day by employee",
    ]) {
      const b = screen.getByRole("button", { name });
      expect(b).toBeDisabled();
      expect(b).toHaveAttribute("title", "not wired");
    }
  });

  it("shows the platform notice above the table", async () => {
    render();
    const table = await screen.findByRole("table");
    const notice = screen.getByText("Clocked hours are not differentiated by platform.");
    expect(notice.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("exports the visible rows as CSV text", async () => {
    let blob: Blob | null = null;
    // jsdom has no object URLs: lend them for this test and put the originals back after.
    const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn((b: Blob) => { blob = b; return "blob:clocked-hours"; });
    URL.revokeObjectURL = vi.fn();
    onTestFinished(() => { URL.createObjectURL = saved.create; URL.revokeObjectURL = saved.revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render();
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Export" }));

    expect(click).toHaveBeenCalledTimes(1);
    expect(blob).not.toBeNull();
    expect(blob!.type).toBe("text/csv;charset=utf-8");
    expect(await blob!.text()).toBe(
      "Employee,Scheduled shifts,Shifts worked,Clocked hours,Recorded earnings (USD)\n" +
      "Alpha One,4,3,7.50,123.45\n" +
      "\"Beta, Night\",2,1,1.02,0.00",
    );
  });

  it("offers no Export to a role denied Export CSV", async () => {
    denied.add("export");
    render();
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("says time tracking is off instead of showing zeros, and asks for no Timesheet", async () => {
    tracking = false;
    render();
    expect(await screen.findByText("Time tracking is off")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(timesheetCalls()).toHaveLength(0);
  });

  it("says nothing was scheduled or clocked when the rollup is empty", async () => {
    rows = [];
    render();
    expect(await screen.findByText("No Shifts or clock time in this range.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("hides Export once a Timesheet re-read fails, even with the earlier rows still cached", async () => {
    const { queryClient } = render();
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();

    refusal = { status: 500, detail: "boom" };
    await queryClient.refetchQueries({ queryKey: ["shifts", "timesheet"] });
    expect(await screen.findByText("Couldn't load Clocked hours: boom")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("shows the Relay's own refusal of a range longer than the Timesheet allows, as a note rather than an error", async () => {
    refusal = { status: 422, detail: "the range is at most 42 days" };
    render();
    const note = await screen.findByText("the range is at most 42 days");
    expect(note).toHaveClass("text-fg-dim");
    expect(note).not.toHaveClass("text-err");
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("shows the table to the Master, which signs in as a user row like an owner", async () => {
    principal = "master";
    render();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(timesheetCalls()).toHaveLength(1);
  });

  it("renders nothing for a chatter session, which the owner-only Timesheet would refuse", async () => {
    principal = "chatter";
    const { container } = render();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
