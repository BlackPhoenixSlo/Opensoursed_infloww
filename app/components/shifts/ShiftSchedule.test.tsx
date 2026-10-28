/**
 * ShiftSchedule — the Shift schedule's week grid, its tabs and its Shifts window
 * (docs/spec/phase-02-shifts-time-tracking.md, Testing Decisions, seam 2; page-parity ticket 18).
 *
 * Rendered with `fetch` mocked by URL, so every assertion is about the wire or the rendered text. The browser's
 * timezone is pinned to Asia/Tokyo and the Agency's (Settings › Your Preferences, `preferences.tz`) to
 * America/New_York, so anything that reads in New York reads in the Agency's zone. The clock is Wednesday 14 Oct
 * 2026, 12:00 in New York, so each expected `from`/`to` below is a worked example: Monday 12 Oct 00:00 EDT is
 * 04:00Z, and the week that ends on Sunday 1 Nov (the fall-back day) ends at Monday 2 Nov 00:00 EST, which is 05:00Z.
 *
 * Fixture names and ids are invented.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

// The session: an Agency owner unless a case signs in a Chatter only.
let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", () => { const v = () => ({ user: session.user, loading: false }); return { useUser: v, useOptionalUser: v }; });
vi.mock("@/contexts/ChatterContext", () => { const v = () => ({ chatter: session.chatter }); return { useChatter: v, useOptionalChatter: v }; });
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
const downloadCsv = vi.fn();
vi.mock("@/lib/csv", () => ({ downloadCsv: (...args: unknown[]) => downloadCsv(...args) }));

import ShiftSchedule from "@/components/shifts/ShiftSchedule";
import SalesSettingsTab from "@/components/settings/SalesSettingsTab";

const NOW = "2026-10-14T16:00:00.000Z"; // Wed 14 Oct 2026, 12:00 EDT (Thu 01:00 in Tokyo)
const AGENCY_TZ = "America/New_York";

const ROSTER = {
  employees: [
    { id: 41, display_name: "Avery", color: null, is_active: true, chatter_id: null, group_id: 2 },
    { id: 42, display_name: "Blake", color: null, is_active: true, chatter_id: "c-1", group_id: null },
  ],
};
/** "Night shift" with "Weekend" under it; Avery is in the sub-group. */
const GROUPS = {
  groups: [
    { id: 1, name: "Night shift", parent_id: null, employee_count: 0 },
    { id: 2, name: "Weekend", parent_id: 1, employee_count: 1 },
  ],
};
const ACCOUNTS = {
  accounts: [{ id: "1000001", nickname: "creator_one" }, { id: "1000002", nickname: "creator_two" }],
  active_account_id: null,
};
/** Tue 13 Oct 09:00–17:00 EDT, Thu 15 Oct 04:00–08:00 EDT (a Ljubljana Shift,
 *  10:00–14:00 there) and Fri 16 Oct 22:00 → Sat 02:00 EDT. */
const WEEK = {
  occurrences: [
    {
      shift_id: 1, occurrence_start: "2026-10-13T13:00:00Z", occurrence_end: "2026-10-13T21:00:00Z",
      start_utc: "2026-10-13T13:00:00Z", end_utc: "2026-10-13T21:00:00Z",
      tz: "America/New_York", repeat_days: null, repeat_until: null,
      employees: [{ id: 41, display_name: "Avery" }, { id: 42, display_name: "Blake" }],
      accounts: [{ id: "1000001", display_name: "creator_one" }],
    },
    {
      // Every Thursday since 8 Oct, through 31 Dec: the edit starts from the
      // occurrence clicked and asks how far it reaches.
      shift_id: 3, occurrence_start: "2026-10-15T08:00:00Z", occurrence_end: "2026-10-15T12:00:00Z",
      start_utc: "2026-10-08T08:00:00Z", end_utc: "2026-10-08T12:00:00Z",
      tz: "Europe/Ljubljana", repeat_days: [4], repeat_until: "2026-12-31",
      employees: [{ id: 41, display_name: "Avery" }],
      accounts: [{ id: "1000002", display_name: "creator_two" }],
    },
    {
      shift_id: 2, occurrence_start: "2026-10-17T02:00:00Z", occurrence_end: "2026-10-17T06:00:00Z",
      start_utc: "2026-10-17T02:00:00Z", end_utc: "2026-10-17T06:00:00Z",
      tz: "America/New_York", repeat_days: null, repeat_until: null,
      employees: [{ id: 42, display_name: "Blake" }],
      accounts: [{ id: "1000002", display_name: "creator_two" }],
    },
  ],
};

/** The Timesheet of the week: Avery by Employee, the two Creators by Creator. */
const BY_EMPLOYEE = {
  rows: [
    { key: "41", display_name: "Avery", scheduled_shifts: 3, shifts_worked: 2, scheduled_minutes: 1200,
      worked_minutes: 270, recorded_earnings_cents: 17000, open_now: false },
    { key: "42", display_name: "Blake", scheduled_shifts: 1, shifts_worked: 1, scheduled_minutes: 240,
      worked_minutes: 65, recorded_earnings_cents: 250, open_now: true },
  ],
};
const BY_CREATOR = {
  rows: [
    { key: "1000001", display_name: "creator_one", scheduled_shifts: 3, shifts_worked: 2, scheduled_minutes: 1200,
      worked_minutes: 210, recorded_earnings_cents: 1000, open_now: false },
  ],
};

/** The week's Shift records (roadmap W6 6.6): Avery's closed shift on creator_one with two sales, and Blake on
 *  the agency-wide clock now, with none. */
const RECORDS = {
  records: [
    { clock_event_id: 7, employee_id: 41, account_id: "1000001", shift_id: 1, in_utc: "2026-10-13T13:00:00Z",
      out_utc: "2026-10-13T15:05:00Z", close_reason: "manual", minutes: 125, edited: false, sales: 2,
      sales_cents: 1500 },
    { clock_event_id: 8, employee_id: 42, account_id: null, shift_id: null, in_utc: "2026-10-14T15:00:00Z",
      out_utc: null, close_reason: null, minutes: null, edited: false, sales: 0, sales_cents: 0 },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
let weekReply: () => Response;
/** The Agency's week start, as `GET /admin/settings/applied` answers it (spec phase-04, story 20). */
let weekStartDay: "monday" | "sunday";
/** The Function permissions the same read says the role denies. */
let deniedActions: string[];
/** What GET /admin/settings/sales answers. */
let salesReply: () => Response;
/** The reply to every create, edit and cancel. */
let writeReply: (method: string, path: string, body: Record<string, unknown> | null) => Response;

beforeAll(() => {
  vi.stubEnv("TZ", "Asia/Tokyo");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(NOW));
  session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
  weekReply = () => jsonRes(WEEK);
  weekStartDay = "monday";
  deniedActions = [];
  salesReply = () => jsonRes({ tab: "sales", config: {} });
  writeReply = () => jsonRes({ shift_id: 99, status: "scheduled" });
  downloadCsv.mockClear();
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0];
    const method = init?.method ?? "GET";
    if (method !== "GET") return writeReply(method, path, init?.body ? JSON.parse(String(init.body)) : null);
    if (path === "/admin/shifts") return weekReply();
    if (path === "/admin/shifts/timesheet") {
      return jsonRes(new URL(String(url), "http://relay.test").searchParams.get("group") === "account"
        ? BY_CREATOR : BY_EMPLOYEE);
    }
    if (path === "/admin/shifts/records") return jsonRes(RECORDS);
    if (path === "/admin/employees") return jsonRes(ROSTER);
    if (path === "/admin/employee-groups") return jsonRes(GROUPS);
    if (path === "/admin/accounts") return jsonRes(ACCOUNTS);
    if (path === "/admin/settings/sales") return salesReply();
    if (path === "/admin/settings/applied") {
      return jsonRes({
        preferences: { tz: AGENCY_TZ, report_tz: null, week_start: weekStartDay },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all", denied_actions: deniedActions },
      });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

/** Every week query sent so far, as its query parameters. */
function weekQueries(): Record<string, string>[] {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/shifts")
    .map((u) => Object.fromEntries(u.searchParams.entries()));
}
const lastWeekQuery = () => weekQueries().at(-1);

/** The last Timesheet query sent, as its query parameters. */
function lastTimesheetQuery(): Record<string, string> | undefined {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/shifts/timesheet")
    .map((u) => Object.fromEntries(u.searchParams.entries()))
    .at(-1);
}

/** Every create, edit and cancel sent so far. */
function writes(): { method: string; path: string; body: unknown }[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init?.method ?? "GET") !== "GET")
    .map(([url, init]) => ({
      method: init.method,
      path: String(url).split("?")[0],
      body: init.body ? JSON.parse(String(init.body)) : null,
    }));
}

async function expectLastQuery(want: Record<string, string>) {
  await waitFor(() => expect(lastWeekQuery()).toEqual(want));
}

const THIS_WEEK = { from: "2026-10-12T04:00:00.000Z", to: "2026-10-19T04:00:00.000Z" };
const button = (name: string) => screen.getByRole("button", { name });
/** One Creator's day cell in the grid. */
const cell = (creator: string, day: string) => within(screen.getByRole("gridcell", { name: `${creator}, ${day}` }));
const dayHeads = () => screen.getAllByRole("columnheader").map((h) => h.getAttribute("aria-label"));
/** Renders and waits until the Agency's zone has moved the week to New York. */
async function renderAtAgencyWeek() {
  renderWithProviders(<ShiftSchedule />);
  await expectLastQuery(THIS_WEEK);
}
const openHistory = () => fireEvent.click(screen.getByRole("tab", { name: "Shift history" }));

describe("ShiftSchedule", () => {
  it("asks for this Monday-first week in the Agency's time zone, not the browser's", async () => {
    await renderAtAgencyWeek();
    expect(screen.getByText("12 Oct – 18 Oct 2026")).toBeInTheDocument();
    expect(dayHeads()).toEqual([
      "Mon 12 Oct", "Tue 13 Oct", "Wed 14 Oct", "Thu 15 Oct", "Fri 16 Oct", "Sat 17 Oct", "Sun 18 Oct",
    ]);
    // Already Thursday in Tokyo; Wednesday is today in New York.
    const wed = screen.getByRole("columnheader", { name: "Wed 14 Oct" });
    expect(wed).toHaveClass("text-accent");
    expect(screen.getByRole("columnheader", { name: "Thu 15 Oct" })).not.toHaveClass("text-accent");
    // The header names the zone the grid reads in.
    expect(screen.getByText("UTC-04:00")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /organization's time zone/ })).toBeInTheDocument();
  });

  it("starts the week, This week and the Shift history on Sunday for a Sunday-start Agency", async () => {
    weekStartDay = "sunday";
    // Sunday 11 Oct 00:00 EDT is 04:00Z.
    const SUNDAY_WEEK = { from: "2026-10-11T04:00:00.000Z", to: "2026-10-18T04:00:00.000Z" };
    renderWithProviders(<ShiftSchedule />);
    await expectLastQuery(SUNDAY_WEEK);
    expect(await screen.findByText("11 Oct – 17 Oct 2026")).toBeInTheDocument();
    expect(dayHeads()).toEqual([
      "Sun 11 Oct", "Mon 12 Oct", "Tue 13 Oct", "Wed 14 Oct", "Thu 15 Oct", "Fri 16 Oct", "Sat 17 Oct",
    ]);

    fireEvent.click(button("Next week"));
    await expectLastQuery({ from: "2026-10-18T04:00:00.000Z", to: "2026-10-25T04:00:00.000Z" });
    fireEvent.click(button("This week"));
    await expectLastQuery(SUNDAY_WEEK);
    openHistory();
    await waitFor(() => expect(lastTimesheetQuery()).toMatchObject(SUNDAY_WEEK));
  });

  it("moves a week at a time, across the fall-back week, and This week comes home", async () => {
    await renderAtAgencyWeek();

    fireEvent.click(button("Next week"));
    await expectLastQuery({ from: "2026-10-19T04:00:00.000Z", to: "2026-10-26T04:00:00.000Z" });
    // The grid header's chevrons step the same week.
    fireEvent.click(button("Show next week"));
    // Sunday 1 Nov falls back: the week is seven local days, 169 hours.
    await expectLastQuery({ from: "2026-10-26T04:00:00.000Z", to: "2026-11-02T05:00:00.000Z" });
    expect(screen.getByText("26 Oct – 1 Nov 2026")).toBeInTheDocument();

    fireEvent.click(button("This week"));
    await expectLastQuery(THIS_WEEK);
    fireEvent.click(button("Previous week"));
    await expectLastQuery({ from: "2026-10-05T04:00:00.000Z", to: "2026-10-12T04:00:00.000Z" });
    fireEvent.click(button("Show next week"));
    await expectLastQuery(THIS_WEEK);
  });

  it("adds the Employee and Creator filters to the query, and Reset clears them", async () => {
    await renderAtAgencyWeek();
    // A chatter's Mirror Employee is a choice too: it can be on a Shift.
    await waitFor(() => {
      fireEvent.click(screen.getByRole("combobox", { name: "Employee" }));
      expect(screen.getByRole("option", { name: "Blake" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("option", { name: "Blake" }));
    await expectLastQuery({ ...THIS_WEEK, employee_id: "42" });
    await waitFor(() => {
      fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
      expect(screen.getByRole("option", { name: "creator_two" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("option", { name: "creator_two" }));
    await expectLastQuery({ ...THIS_WEEK, employee_id: "42", account_id: "1000002" });
    // A filter survives week navigation.
    fireEvent.click(button("Next week"));
    await expectLastQuery({
      from: "2026-10-19T04:00:00.000Z", to: "2026-10-26T04:00:00.000Z", employee_id: "42", account_id: "1000002",
    });

    fireEvent.click(button("Reset"));
    await expectLastQuery({ from: "2026-10-19T04:00:00.000Z", to: "2026-10-26T04:00:00.000Z" });
    expect(screen.getByRole("combobox", { name: "Employee" })).toHaveTextContent("Employee");
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("Creator");
  });

  it("shows one row per Creator, each Shift under its day in the Agency's time", async () => {
    await renderAtAgencyWeek();
    await waitFor(() => expect(screen.getAllByRole("row", { name: /^creator_/ })).toHaveLength(2));
    expect(screen.getAllByRole("row", { name: /^creator_/ }).map((r) => r.getAttribute("aria-label")))
      .toEqual(["creator_one", "creator_two"]);
    const tue = cell("creator_one", "Tue 13 Oct");
    expect(tue.getByText("9:00 AM - 5:00 PM")).toBeInTheDocument();
    // Two Employees: the first, then how many more.
    expect(tue.getByText("Avery +1")).toBeInTheDocument();
    // 02:00Z on Saturday is Friday 22:00 in New York: it sits on Friday.
    const fri = cell("creator_two", "Fri 16 Oct");
    expect(fri.getByText("10:00 PM - 2:00 AM")).toBeInTheDocument();
    expect(fri.getByText("Blake")).toBeInTheDocument();
    expect(cell("creator_two", "Sat 17 Oct").queryAllByRole("button", { name: /AM|PM/ })).toEqual([]);
    expect(cell("creator_one", "Fri 16 Oct").queryByText("Blake")).toBeNull();
  });

  it("shows a Shift with two Creators in both rows, and colours its bar by Employee", async () => {
    weekReply = () => jsonRes({ occurrences: [{
      ...WEEK.occurrences[0],
      accounts: [{ id: "1000001", display_name: "creator_one" }, { id: "1000002", display_name: "creator_two" }],
    }] });
    await renderAtAgencyWeek();
    for (const creator of ["creator_one", "creator_two"]) {
      const tile = await waitFor(() => cell(creator, "Tue 13 Oct").getByRole("button", { name: /9:00 AM - 5:00 PM/ }));
      // Avery is the first Employee seen: Infloww's first colour. The 13 Oct Shift has ended by 14 Oct, so grey.
      expect(tile.querySelector("[data-bar]")).toHaveStyle({ background: "#D9D9D9" });
    }
  });

  it("colours a Shift still to come by its first Employee", async () => {
    await renderAtAgencyWeek();
    const thu = await waitFor(() => cell("creator_two", "Thu 15 Oct").getByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    // First seen order: Avery (#FF7875) on shift 1, then Blake (#FFC069).
    expect(thu.querySelector("[data-bar]")).toHaveStyle({ background: "#FF7875" });
    const fri = cell("creator_two", "Fri 16 Oct").getByRole("button", { name: /10:00 PM - 2:00 AM/ });
    expect(fri.querySelector("[data-bar]")).toHaveStyle({ background: "#FFC069" });
  });

  it("names a Shift's time zone in its details only when it is not the Agency's", async () => {
    await renderAtAgencyWeek();
    fireEvent.focus(await screen.findByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    const thu = within(screen.getByRole("dialog", { name: "Shift details" }));
    // Its own wall clock: 10:00–14:00 in Ljubljana.
    expect(thu.getByText("Thursday, October 15, 2026 (GMT+02:00, Europe/Ljubljana)")).toBeInTheDocument();
    expect(thu.getByText("10:00 AM - 2:00 PM")).toBeInTheDocument();
    expect(thu.getByText("Repeats: Weekly on Thu, until Dec. 31, 2026")).toBeInTheDocument();
    expect(thu.getByText("creator_two")).toBeInTheDocument();

    fireEvent.focus(screen.getByRole("button", { name: /9:00 AM - 5:00 PM/ }));
    const tue = within(screen.getByRole("dialog", { name: "Shift details" }));
    expect(tue.getByText("Tuesday, October 13, 2026 (GMT-04:00)")).toBeInTheDocument();
    expect(tue.queryByText(/America\/New_York/)).toBeNull();
    expect(tue.queryByText(/Repeats/)).toBeNull();
    expect(tue.getByText("Avery, Blake")).toBeInTheDocument();
    fireEvent.click(tue.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Shift details" })).toBeNull();
  });

  it("the details' Delete cancels the Shift after a confirmation, and Edit opens it", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderAtAgencyWeek();
    fireEvent.focus(await screen.findByRole("button", { name: /9:00 AM - 5:00 PM/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Shift details" })).getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledWith("Cancel this Shift? It leaves the calendar and stays in the history.");
    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/admin/shifts/1/cancel", body: null }]));

    fireEvent.focus(screen.getByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Shift details" })).getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("dialog", { name: "Edit shift" })).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("the Employee group filter hides a Shift whose Employees are all outside the group", async () => {
    await renderAtAgencyWeek();
    await screen.findByRole("button", { name: /10:00 PM - 2:00 AM/ });
    await waitFor(() => {
      fireEvent.click(screen.getByRole("combobox", { name: "Employee group" }));
      expect(screen.getByRole("option", { name: "Night shift" })).toBeInTheDocument();
    });
    // Avery is in "Weekend", under "Night shift"; Blake is in no group.
    fireEvent.click(screen.getByRole("option", { name: "Night shift" }));
    expect(screen.queryByRole("button", { name: /10:00 PM - 2:00 AM/ })).toBeNull();
    expect(screen.getByRole("button", { name: /9:00 AM - 5:00 PM/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /4:00 AM - 8:00 AM/ })).toBeInTheDocument();
    // Client-side: the query does not change.
    expect(lastWeekQuery()).toEqual(THIS_WEEK);
    fireEvent.click(button("Reset"));
    expect(screen.getByRole("button", { name: /10:00 PM - 2:00 AM/ })).toBeInTheDocument();
  });

  it("a click on an empty day cell opens Create shift(s) for that Creator and day", async () => {
    await renderAtAgencyWeek();
    fireEvent.click(await screen.findByRole("button", { name: "Create a shift for creator_one on Mon 12 Oct" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    const row = within(dialog.getByRole("group", { name: "Shift 1" }));
    expect((row.getByLabelText("Start") as HTMLInputElement).value).toBe("2026-10-12T09:00");
    expect((row.getByLabelText("End") as HTMLInputElement).value).toBe("2026-10-12T17:00");
    expect(row.getByText(AGENCY_TZ)).toBeInTheDocument();
    await waitFor(() => expect(row.getByRole("checkbox", { name: "creator_one" })).toBeChecked());
    expect(row.getByRole("checkbox", { name: "creator_two" })).not.toBeChecked();
  });

  it("a cell shows two Shifts, then +N more with the rest", async () => {
    const at = (id: number, start: string, end: string, who: string) => ({
      ...WEEK.occurrences[0], shift_id: id, occurrence_start: start, occurrence_end: end, start_utc: start, end_utc: end,
      employees: [{ id: 40 + id, display_name: who }],
    });
    weekReply = () => jsonRes({ occurrences: [
      at(1, "2026-10-13T12:00:00Z", "2026-10-13T14:00:00Z", "Avery"),
      at(2, "2026-10-13T15:00:00Z", "2026-10-13T17:00:00Z", "Blake"),
      at(3, "2026-10-13T18:00:00Z", "2026-10-13T20:00:00Z", "Casey"),
    ] });
    await renderAtAgencyWeek();
    const tue = await waitFor(() => cell("creator_one", "Tue 13 Oct"));
    await waitFor(() => expect(tue.getByText("Avery")).toBeInTheDocument());
    expect(tue.getByText("Blake")).toBeInTheDocument();
    expect(tue.queryByText("Casey")).toBeNull();
    fireEvent.click(tue.getByRole("button", { name: "+1 more" }));
    const more = within(screen.getByRole("dialog", { name: "More shifts on Tue 13 Oct" }));
    fireEvent.click(more.getByRole("button", { name: /Casey/ }));
    expect(await screen.findByRole("dialog", { name: "Edit shift" })).toBeInTheDocument();
  });

  it("says so when the week has no Shifts", async () => {
    weekReply = () => jsonRes({ occurrences: [] });
    await renderAtAgencyWeek();
    expect(await screen.findByText("No shifts this week")).toBeInTheDocument();
  });

  it("Create shift(s): one POST per row, the good rows saved, the bad row's reason on it alone", async () => {
    writeReply = (_m, _p, body) =>
      (body?.employee_ids as number[]).includes(42)
        ? jsonRes({ detail: "Blake (42) cannot access creator creator_two (1000002)" }, 422)
        : jsonRes({ shift_id: 99, status: "scheduled" });
    await renderAtAgencyWeek();
    const queriesBefore = weekQueries().length;

    fireEvent.click(button("Create shift(s)"));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    fireEvent.click(dialog.getByRole("button", { name: "+ Add Shift" }));
    fireEvent.click(dialog.getByRole("button", { name: "+ Add Shift" }));
    const rows = () => dialog.getAllByRole("group", { name: /^Shift \d+$/ });
    expect(rows()).toHaveLength(3);
    await waitFor(() => expect(within(rows()[0]).getByRole("checkbox", { name: "Blake" })).toBeInTheDocument());
    await waitFor(() => expect(within(rows()[0]).getByRole("checkbox", { name: "creator_two" })).toBeInTheDocument());

    const fill = (row: HTMLElement, start: string, end: string, employee: string, creator: string) => {
      const r = within(row);
      fireEvent.change(r.getByLabelText("Start"), { target: { value: start } });
      fireEvent.change(r.getByLabelText("End"), { target: { value: end } });
      fireEvent.click(r.getByRole("checkbox", { name: employee }));
      fireEvent.click(r.getByRole("checkbox", { name: creator }));
      // A new row's timezone is the Agency's, not the browser's Tokyo.
      expect(r.getByText("America/New_York")).toBeInTheDocument();
    };
    // Row 1: every Friday from 16 Oct, "Never".
    fill(rows()[0], "2026-10-16T09:00", "2026-10-16T17:00", "Avery", "creator_one");
    fireEvent.click(within(rows()[0]).getByRole("checkbox", { name: "Repeat weekly" }));
    fireEvent.click(within(rows()[0]).getByRole("checkbox", { name: "Fri" }));
    expect((within(rows()[0]).getByLabelText("Repeat Ends") as HTMLSelectElement).value).toBe("never");
    // Row 2: refused by the server.
    fill(rows()[1], "2026-10-17T10:00", "2026-10-17T12:00", "Blake", "creator_two");
    // Row 3: Mondays and Wednesdays through 31 Dec.
    fill(rows()[2], "2026-10-19T08:30", "2026-10-19T12:00", "Avery", "creator_two");
    const r3 = within(rows()[2]);
    fireEvent.click(r3.getByRole("checkbox", { name: "Repeat weekly" }));
    fireEvent.click(r3.getByRole("checkbox", { name: "Wed" }));
    fireEvent.click(r3.getByRole("checkbox", { name: "Mon" }));
    fireEvent.change(r3.getByLabelText("Repeat Ends"), { target: { value: "date" } });
    fireEvent.change(r3.getByLabelText("Repeat until"), { target: { value: "2026-12-31" } });

    fireEvent.click(dialog.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(writes()).toHaveLength(3));
    expect(writes()).toEqual([
      { method: "POST", path: "/admin/shifts", body: {
        start_utc: "2026-10-16T13:00:00.000Z", end_utc: "2026-10-16T21:00:00.000Z", tz: "America/New_York",
        repeat_days: [5], repeat_until: null, employee_ids: [41], account_ids: ["1000001"] } },
      { method: "POST", path: "/admin/shifts", body: {
        start_utc: "2026-10-17T14:00:00.000Z", end_utc: "2026-10-17T16:00:00.000Z", tz: "America/New_York",
        repeat_days: null, repeat_until: null, employee_ids: [42], account_ids: ["1000002"] } },
      { method: "POST", path: "/admin/shifts", body: {
        start_utc: "2026-10-19T12:30:00.000Z", end_utc: "2026-10-19T16:00:00.000Z", tz: "America/New_York",
        repeat_days: [1, 3], repeat_until: "2026-12-31", employee_ids: [41], account_ids: ["1000002"] } },
    ]);
    // Only the refused row stays, with its own reason; the window stays open.
    await waitFor(() => expect(rows()).toHaveLength(1));
    const left = within(rows()[0]);
    expect(left.getByText("Blake (42) cannot access creator creator_two (1000002)")).toBeInTheDocument();
    expect((left.getByLabelText("Start") as HTMLInputElement).value).toBe("2026-10-17T10:00");
    expect(left.getByRole("checkbox", { name: "Blake" })).toBeChecked();
    // The saved rows show up: the week is asked again.
    await waitFor(() => expect(weekQueries().length).toBeGreaterThan(queriesBefore));

    // Fixed and sent again, it saves and the window closes.
    writeReply = () => jsonRes({ shift_id: 100, status: "scheduled" });
    fireEvent.click(left.getByRole("checkbox", { name: "creator_two" }));
    fireEvent.click(left.getByRole("checkbox", { name: "creator_one" }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create shift(s)" })).toBeNull());
    expect(writes().at(-1)).toEqual({ method: "POST", path: "/admin/shifts", body: {
      start_utc: "2026-10-17T14:00:00.000Z", end_utc: "2026-10-17T16:00:00.000Z", tz: "America/New_York",
      repeat_days: null, repeat_until: null, employee_ids: [42], account_ids: ["1000001"] } });
  });

  it("an Employee lacking a Creator is asked about once per pair, and a confirmed grant resends with grant_access", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    writeReply = (_m, _p, body) => body?.grant_access
      ? jsonRes({ shift_id: 101, status: "scheduled" })
      : jsonRes({ detail: "Blake (42) cannot access creator creator_two (1000002)", grantable: [
        { employee_id: 42, employee_name: "Blake", account_id: "1000002", account_name: "creator_two" }] }, 422);
    await renderAtAgencyWeek();
    fireEvent.click(button("Create shift(s)"));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    fireEvent.click(dialog.getByRole("button", { name: "+ Add Shift" }));
    const rows = () => dialog.getAllByRole("group", { name: /^Shift \d+$/ }).map((r) => within(r));
    await waitFor(() => expect(rows()[1].getByRole("checkbox", { name: "Blake" })).toBeInTheDocument());
    // Two rows, the same Blake / creator_two pair.
    rows().forEach((row, i) => {
      fireEvent.change(row.getByLabelText("Start"), { target: { value: `2026-10-1${7 + i}T10:00` } });
      fireEvent.change(row.getByLabelText("End"), { target: { value: `2026-10-1${7 + i}T12:00` } });
      fireEvent.click(row.getByRole("checkbox", { name: "Blake" }));
      fireEvent.click(row.getByRole("checkbox", { name: "creator_two" }));
    });

    // Declined: asked once, nothing more is sent and both rows keep the Relay's reason.
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(dialog.getAllByText("Blake (42) cannot access creator creator_two (1000002)"))
      .toHaveLength(2));
    expect(confirm.mock.calls).toEqual([["Grant Blake access to creator_two?"]]);
    expect(writes()).toHaveLength(2);

    // Confirmed: asked once more, both rows again with grant_access, and the window closes.
    confirm.mockReturnValue(true);
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create shift(s)" })).toBeNull());
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(writes().slice(2).map((w) => (w.body as { grant_access?: boolean }).grant_access))
      .toEqual([undefined, undefined, true, true]);
    confirm.mockRestore();
  }, 15_000);

  it("a row with no start or end is stopped before it is sent", async () => {
    renderWithProviders(<ShiftSchedule />);
    fireEvent.click(button("Create shift(s)"));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    expect(await dialog.findByText("Set a start and an end.")).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("clicking a Shift opens that occurrence for editing, and OK asks how far a series' edit reaches", async () => {
    await renderAtAgencyWeek();
    fireEvent.click(await screen.findByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit shift" }));
    expect(dialog.queryByRole("button", { name: "+ Add Shift" })).toBeNull();
    const row = within(dialog.getByRole("group", { name: "Shift 1" }));
    // The occurrence clicked, in the Shift's own zone (not the Agency's New
    // York): Thu 15 Oct 10:00–14:00 CEST, the zone the repeats follow too.
    expect((row.getByLabelText("Start") as HTMLInputElement).value).toBe("2026-10-15T10:00");
    expect((row.getByLabelText("End") as HTMLInputElement).value).toBe("2026-10-15T14:00");
    expect(row.getByText("Europe/Ljubljana")).toBeInTheDocument();
    expect(row.getByRole("checkbox", { name: "Repeat weekly" })).toBeChecked();
    expect(row.getByRole("checkbox", { name: "Thu" })).toBeChecked();
    expect((row.getByLabelText("Repeat until") as HTMLInputElement).value).toBe("2026-12-31");
    await waitFor(() => expect(row.getByRole("checkbox", { name: "Avery" })).toBeChecked());
    expect(row.getByRole("checkbox", { name: "creator_two" })).toBeChecked();

    // 15:00 in Ljubljana (CEST, UTC+2) is 13:00Z.
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-10-15T15:00" } });
    fireEvent.change(row.getByLabelText("Repeat Ends"), { target: { value: "never" } });
    fireEvent.click(row.getByRole("checkbox", { name: "Blake" }));
    const queriesBefore = weekQueries().length;
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));

    // A weekly series asks how far the edit reaches; this and every later Thursday, none of them past.
    const scope = within(await screen.findByRole("dialog", { name: "Edit recurring shift" }));
    expect(scope.getByRole("radio", { name: "Only this shift" })).toBeChecked();
    expect(writes()).toEqual([]);
    fireEvent.click(scope.getByRole("radio", { name: "This and all future shifts" }));
    expect(scope.queryByText("Past shifts will also be modified")).toBeNull();
    fireEvent.click(scope.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit shift" })).toBeNull());
    expect(writes()).toEqual([{ method: "PATCH", path: "/admin/shifts/3", body: {
      start_utc: "2026-10-15T08:00:00.000Z", end_utc: "2026-10-15T13:00:00.000Z", tz: "Europe/Ljubljana",
      repeat_days: [4], repeat_until: null, employee_ids: [41, 42], account_ids: ["1000002"],
      scope: "following", occurrence_start: "2026-10-15T08:00:00Z" } }]);
    await waitFor(() => expect(weekQueries().length).toBeGreaterThan(queriesBefore));
  });

  it("a New York start in the spring-forward gap is sent as the server reads it", async () => {
    await renderAtAgencyWeek();
    fireEvent.click(button("Create shift(s)"));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    const row = within(dialog.getByRole("group", { name: "Shift 1" }));
    await waitFor(() => expect(row.getByRole("checkbox", { name: "Avery" })).toBeInTheDocument());
    await waitFor(() => expect(row.getByRole("checkbox", { name: "creator_one" })).toBeInTheDocument());
    // 02:30 on 8 Mar 2026 does not exist in New York; like the server's
    // _to_utc (fold=0) it reads as 02:30 EST, 07:30Z.
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-03-08T02:30" } });
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-03-08T10:00" } });
    fireEvent.click(row.getByRole("checkbox", { name: "Avery" }));
    fireEvent.click(row.getByRole("checkbox", { name: "creator_one" }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toMatchObject({ method: "POST", path: "/admin/shifts", body: {
      start_utc: "2026-03-08T07:30:00.000Z", tz: "America/New_York" } });
  });

  it("a Ljubljana start in the fall-back fold is sent as its first (CEST) reading", async () => {
    await renderAtAgencyWeek();
    fireEvent.click(await screen.findByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit shift" }));
    const row = within(dialog.getByRole("group", { name: "Shift 1" }));
    // 02:30 on 25 Oct 2026 happens twice in Ljubljana; fold=0 is CEST, 00:30Z.
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-10-25T02:30" } });
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-10-25T10:00" } });
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Edit recurring shift" }))
      .getByRole("button", { name: "OK" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toMatchObject({ method: "PATCH", path: "/admin/shifts/3", body: {
      start_utc: "2026-10-25T00:30:00.000Z", tz: "Europe/Ljubljana", scope: "this" } });
  });

  it("a refused edit shows the server's reason and keeps the window open", async () => {
    writeReply = () => jsonRes({ detail: "a cancelled Shift cannot be edited" }, 409);
    await renderAtAgencyWeek();
    fireEvent.click(await screen.findByRole("button", { name: /9:00 AM - 5:00 PM/ }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit shift" }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    expect(await dialog.findByText("a cancelled Shift cannot be edited")).toBeInTheDocument();
    expect(writes().map((w) => `${w.method} ${w.path}`)).toEqual(["PATCH /admin/shifts/1"]);
  });

  it("a 409 names each clash on the refused row, in the Agency's time and with Creator names", async () => {
    writeReply = () => jsonRes({
      detail: "Multiple employees per shift is off; this Shift clashes: ...",
      clashes: [
        { shift_id: null, occurrence_start: "2026-10-16T13:00:00Z", account_id: "1000001" },
        { shift_id: 1, occurrence_start: "2026-10-13T13:00:00Z", account_id: "1000001" },
        { shift_id: 3, occurrence_start: "2026-12-03T09:00:00Z", account_id: "1000009" },
      ],
    }, 409);
    await renderAtAgencyWeek();
    fireEvent.click(button("Create shift(s)"));
    const dialog = within(await screen.findByRole("dialog", { name: "Create shift(s)" }));
    const row = within(dialog.getByRole("group", { name: "Shift 1" }));
    await waitFor(() => expect(row.getByRole("checkbox", { name: "Blake" })).toBeInTheDocument());
    await waitFor(() => expect(row.getByRole("checkbox", { name: "creator_one" })).toBeInTheDocument());
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-10-16T09:00" } });
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-10-16T17:00" } });
    fireEvent.click(row.getByRole("checkbox", { name: "Avery" }));
    fireEvent.click(row.getByRole("checkbox", { name: "Blake" }));
    fireEvent.click(row.getByRole("checkbox", { name: "creator_one" }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));

    // 13:00Z on 13 Oct is 09:00 EDT; 09:00Z on 3 Dec is 04:00 EST; an id the
    // window has no name for is shown as the id.
    expect(await row.findByText(
      'Not saved: "Multiple employees per shift" is off (Shift Settings). ' +
      "creator_one: more than one Employee on this Shift; " +
      "creator_one: another Shift on Tue 13 Oct 09:00; " +
      "1000009: another Shift on Thu 3 Dec 04:00.",
    )).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Create shift(s)" })).toBeInTheDocument();
  });

  it("Shift Settings saves the whole sales blob with only multi_employee_shift changed, and the Sales Panel shows it", async () => {
    const stored = {
      exclude_welcome: true,
      exclude_of_fee: false,
      multi_employee_shift: false,
      attribution: { messages: "sender", posts_tips: "shift", subscriptions_chatter_opt_in: true },
      legacy_key: 7,
    };
    salesReply = () => jsonRes({ tab: "sales", config: stored });
    writeReply = (method, path, body) =>
      method === "PUT" && path === "/admin/settings/sales"
        ? jsonRes({ tab: "sales", config: body })
        : jsonRes({ detail: "unexpected write" }, 500);
    renderWithProviders(<><ShiftSchedule /><SalesSettingsTab /></>);
    const salesToggle = () => screen.getByRole("switch", { name: "Multiple employees per shift" });
    await waitFor(() => expect(salesToggle()).toHaveAttribute("aria-checked", "false"));

    fireEvent.click(button("Shift Settings"));
    const dialog = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    const allow = dialog.getByRole("switch", {
      name: "Allow multiple employees to work on the same shift for the assigned Creator",
    });
    await waitFor(() => expect(dialog.getByRole("button", { name: "OK" })).toBeEnabled());
    expect(allow).not.toBeChecked();
    fireEvent.click(allow);
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Shift Settings" })).toBeNull());
    expect(writes()).toEqual([
      { method: "PUT", path: "/admin/settings/sales", body: { ...stored, multi_employee_shift: true } },
    ]);
    await waitFor(() => expect(salesToggle()).toHaveAttribute("aria-checked", "true"));

    // Opened again, it shows the stored value.
    fireEvent.click(button("Shift Settings"));
    const again = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    expect(again.getByRole("switch", {
      name: "Allow multiple employees to work on the same shift for the assigned Creator",
    })).toBeChecked();
  });

  it("Shift Settings over an empty sales blob sends only the one key", async () => {
    writeReply = (_m, _p, body) => jsonRes({ tab: "sales", config: body });
    renderWithProviders(<ShiftSchedule />);
    fireEvent.click(button("Shift Settings"));
    const dialog = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    await waitFor(() => expect(dialog.getByRole("button", { name: "OK" })).toBeEnabled());
    fireEvent.click(dialog.getByRole("switch", {
      name: "Allow multiple employees to work on the same shift for the assigned Creator",
    }));
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "PUT", path: "/admin/settings/sales", body: { multi_employee_shift: true },
    });
  });

  it("Shift Settings sends nothing while the sales blob has not loaded (Load gate)", async () => {
    salesReply = () => jsonRes({ detail: "boom" }, 500);
    renderWithProviders(<ShiftSchedule />);
    fireEvent.click(button("Shift Settings"));
    const dialog = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    expect(await dialog.findByText(/never loaded/)).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "OK" })).toBeDisabled();
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
  });

  it("Delete on a weekly series asks how far it reaches, and warns when that reaches past shifts", async () => {
    const confirm = vi.spyOn(window, "confirm");
    await renderAtAgencyWeek();
    fireEvent.focus(await screen.findByRole("button", { name: /4:00 AM - 8:00 AM/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Shift details" })).getByRole("button", { name: "Delete" }));
    const scope = within(await screen.findByRole("dialog", { name: "Delete recurring shift" }));
    expect(scope.getAllByRole("radio").map((r) => r.closest("label")?.textContent))
      .toEqual(["This shift", "This shift and following", "All shifts"]);
    // The series began on 8 Oct, before now (14 Oct); this occurrence (15 Oct) has not.
    fireEvent.click(scope.getByRole("radio", { name: "All shifts" }));
    expect(scope.getByText("All records of past shifts will be permanently deleted")).toBeInTheDocument();
    fireEvent.click(scope.getByRole("radio", { name: "This shift" }));
    expect(scope.queryByText("All records of past shifts will be permanently deleted")).toBeNull();
    fireEvent.click(scope.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/admin/shifts/3/cancel",
      body: { scope: "this", occurrence_start: "2026-10-15T08:00:00Z" } }]));
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Delete recurring shift" })).toBeNull();
    confirm.mockRestore();
  });

  it("Delete in the Shifts window cancels a Shift only after a confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderAtAgencyWeek();
    fireEvent.click(await screen.findByRole("button", { name: /9:00 AM - 5:00 PM/ }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit shift" }));

    fireEvent.click(dialog.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
    expect(screen.getByRole("dialog", { name: "Edit shift" })).toBeInTheDocument();

    confirm.mockReturnValue(true);
    const queriesBefore = weekQueries().length;
    fireEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit shift" })).toBeNull());
    expect(writes()).toEqual([{ method: "POST", path: "/admin/shifts/1/cancel", body: null }]);
    await waitFor(() => expect(weekQueries().length).toBeGreaterThan(queriesBefore));
    confirm.mockRestore();
  });

  it("the Shift history tab shows the history and Export, and ?tab=history opens on it", async () => {
    window.history.replaceState(null, "", "/employees/shifts?tab=history");
    renderWithProviders(<ShiftSchedule />);
    expect(await screen.findByRole("tab", { name: "Shift history", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Shift history" })).toBeInTheDocument();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create shift(s)" })).toBeNull();
    const exportButton = button("Export");
    await waitFor(() => expect(exportButton).toBeEnabled());
    await waitFor(() => expect(lastTimesheetQuery()).toEqual({ ...THIS_WEEK, group: "employee" }));

    fireEvent.click(exportButton);
    expect(downloadCsv).toHaveBeenCalledWith("shift-history-2026-10-12.csv", [
      ["Employee", "Scheduled Shifts", "Shifts Worked", "Scheduled hours", "Worked hours", "Recorded earnings"],
      ["Avery", 3, 2, "20h 00m", "4h 30m", "$170"],
      ["Blake", 1, 1, "4h 00m", "1h 05m", "$2.50"], // the CSV keeps the cents (fmtPrice); the table shows "$3"
    ]);

    fireEvent.click(screen.getByRole("tab", { name: "Shift schedule" }));
    expect(screen.getByRole("grid", { name: "Shift schedule" })).toBeInTheDocument();
    expect(button("Create shift(s)")).toBeInTheDocument();
  });

  it("the Shift history tab offers no Export to a role denied Export CSV", async () => {
    deniedActions = ["/employees/shifts#export"];
    window.history.replaceState(null, "", "/employees/shifts?tab=history");
    renderWithProviders(<ShiftSchedule />);
    expect(await screen.findByRole("region", { name: "Shift history" })).toBeInTheDocument();
    await waitFor(() => expect(lastTimesheetQuery()).toEqual({ ...THIS_WEEK, group: "employee" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Export" })).toBeNull());
  });

  it("Shift history asks for the viewed week by Employee, and switches to Creator", async () => {
    await renderAtAgencyWeek();
    openHistory();
    await waitFor(() => expect(lastTimesheetQuery()).toEqual({ ...THIS_WEEK, group: "employee" }));
    const history = screen.getByRole("region", { name: "Shift history" });
    expect(await within(history).findByText("Avery")).toBeInTheDocument();
    expect(within(history).getByRole("columnheader", { name: "Employee" })).toBeInTheDocument();

    fireEvent.click(within(history).getByRole("radio", { name: "By creator" }));
    await waitFor(() => expect(lastTimesheetQuery()).toEqual({ ...THIS_WEEK, group: "account" }));
    expect(await within(history).findByText("creator_one")).toBeInTheDocument();
    expect(within(history).getByRole("columnheader", { name: "Creator" })).toBeInTheDocument();
    expect(within(history).queryByText("Avery")).toBeNull();

    fireEvent.click(button("Next week"));
    await waitFor(() => expect(lastTimesheetQuery()).toEqual({
      from: "2026-10-19T04:00:00.000Z", to: "2026-10-26T04:00:00.000Z", group: "account",
    }));
    fireEvent.click(within(history).getByRole("radio", { name: "By employee" }));
    await waitFor(() => expect(lastTimesheetQuery()?.group).toBe("employee"));
  });

  it("Shift history: Recorded earnings with its not-payroll tooltip, hours, counts and who is clocked in now", async () => {
    await renderAtAgencyWeek();
    openHistory();
    const history = screen.getByRole("region", { name: "Shift history" });
    await within(history).findByText("Avery");
    const headers = within(history).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Employee", "Scheduled Shifts", "Shifts Worked", "Scheduled hours", "Worked hours", "Recorded earnings",
    ]);
    expect(within(history).getByRole("columnheader", { name: "Recorded earnings" })).toHaveAttribute(
      "title", "Infloww calls this Total Earnings. Earnings already credited during worked time; not payroll.",
    );
    const avery = within(history).getByRole("row", { name: /Avery/ });
    expect(within(avery).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "Avery", "3", "2", "20h 00m", "4h 30m", "$170",
    ]);
    expect(within(avery).queryByLabelText("Clocked in now")).toBeNull();
    const blake = within(history).getByRole("row", { name: /Blake/ });
    expect(within(blake).getByLabelText("Clocked in now")).toBeInTheDocument();
    expect(within(blake).getAllByRole("cell").slice(3).map((c) => c.textContent)).toEqual([
      "4h 00m", "1h 05m", "$3",
    ]);
  });

  it("says so when the week cannot load, with a Retry", async () => {
    weekReply = () => jsonRes({ detail: "the range is at most 42 days" }, 422);
    renderWithProviders(<ShiftSchedule />);
    expect(await screen.findByText(/Couldn't load the Shift schedule/)).toBeInTheDocument();
    const before = weekQueries().length;
    fireEvent.click(button("Retry"));
    await waitFor(() => expect(weekQueries().length).toBeGreaterThan(before));
  });

  it("tells a chatter the owner manages it, and asks the Relay nothing", async () => {
    session = { user: null, chatter: { username: "chatter" } };
    renderWithProviders(<ShiftSchedule />);
    expect(screen.getByText("Only the agency owner manages the Shift schedule.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(weekQueries()).toEqual([]);
    expect(screen.queryByRole("button", { name: "Next week" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Shift Settings" })).toBeNull();
  });

  it("Shift history By shift lists each worked shift with its sales, exports them, deletes and reassigns", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    writeReply = (method, path) => path === "/admin/ingest/transactions/attribute"
      ? jsonRes({ updated: 1, attributed_employee_id: 0, tx_ids: [5], skipped_split: 1 })
      : jsonRes({ deleted: 7 });
    await renderAtAgencyWeek();
    openHistory();
    const history = screen.getByRole("region", { name: "Shift history" });
    fireEvent.click(within(history).getByRole("radio", { name: "By shift" }));
    const table = within(await within(history).findByRole("table", { name: "Shift records" }));
    const records = () => fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://relay.test"))
      .filter((u) => u.pathname === "/admin/shifts/records").map((u) => Object.fromEntries(u.searchParams.entries()));
    expect(records().at(-1)).toEqual(THIS_WEEK);
    expect(table.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Employee", "Creator", "Clock in (America/New_York)", "Clock out (America/New_York)", "Worked hours", "Sales",
      "Recorded earnings", "Action",
    ]);
    const [avery, blake] = table.getAllByRole("row").slice(1);
    expect(within(avery).getAllByRole("cell").slice(0, 7).map((c) => c.textContent)).toEqual([
      "Avery", "creator_one", "Oct 13, 2026 9:00:00 AM", "Oct 13, 2026 11:05:00 AM", "2h 05m", "2", "$15",
    ]);
    expect(within(blake).getAllByRole("cell").slice(0, 7).map((c) => c.textContent)).toEqual([
      "Blake", "All creators", "Oct 14, 2026 11:00:00 AM", "Clocked in", "-", "0", "$0",
    ]);
    expect(within(blake).getByRole("button", { name: "Reassign sales" })).toBeDisabled();

    fireEvent.click(button("Export"));
    expect(downloadCsv).toHaveBeenCalledWith("shift-records-2026-10-12.csv", [
      ["Employee", "Creator", "Clock in (America/New_York)", "Clock out (America/New_York)", "Worked hours", "Sales",
        "Recorded earnings"],
      ["Avery", "creator_one", "Oct 13, 2026 9:00:00 AM", "Oct 13, 2026 11:05:00 AM", "2h 05m", 2, "$15"],
      ["Blake", "All creators", "Oct 14, 2026 11:00:00 AM", "Clocked in", "-", 0, "$0"],
    ]);

    fireEvent.click(within(avery).getByRole("button", { name: "Reassign sales" }));
    const picker = within(avery).getByRole("combobox", { name: "Reassign sales to" });
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose an employee", "Avery", "Blake", "No one",
    ]);
    fireEvent.change(picker, { target: { value: "no_one" } });
    fireEvent.click(within(avery).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/admin/ingest/transactions/attribute",
      body: { employee_id: "no_one", clock_event_id: 7 } }]));
    // The sale shared with another Employee on the shift stays theirs, and the row says so.
    expect(await within(avery).findByRole("status")).toHaveTextContent(
      "1 split sale was left unchanged: shared with other employees on the shift.");

    await waitFor(() => expect(within(avery).getByRole("button", { name: "Delete" })).toBeInTheDocument());
    fireEvent.click(within(avery).getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(writes().at(-1)).toEqual({
      method: "DELETE", path: "/admin/shifts/clock-events/7", body: null,
    }));
    confirm.mockRestore();
  });
});
