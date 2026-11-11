/**
 * The shift cards' seam (docs/spec/phase-02-shifts-time-tracking.md, Testing
 * Decisions, seam 2): the Dashboard's "My shifts" and "Current clocked-in
 * employees" cards for owner and chatter sessions, and Clock in and Clock out
 * from the "My shifts" card and through `ClockDialog`.
 *
 * Rewritten for w4-a: the avatar menu has no clock item any more (the top
 * bar's Clock button, ClockButton.test.tsx, replaced it), so its clock cases
 * now render `ClockDialog` itself, which opens only for a chatter in two
 * Agencies; the card clocks in one click on the agency-wide clock (body `{}`)
 * while `GET /admin/shifts/clock-status` allows it, and the clocked-in rows
 * carry the linked Shift's Creators.
 *
 * Page-parity ticket 01: both cards' empty states are ticket 00's `EmptyState`
 * (the art over the text), and the owner's "My shifts" has no owner sentence.
 *
 * Rendered with `fetch` mocked by URL, so every assertion is about the wire or
 * the rendered text. The Relay double keeps the chatter's open Clock event, so
 * the dialog's switch from Clock in to Clock out comes from a re-read of
 * `GET /admin/shifts/me`, as in the app. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { onNotice } from "@/lib/notices";

// The session: a Chatter only, unless a case signs in an owner.
let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", () => { const v = () => ({ user: session.user, loading: false, logout: vi.fn() }); return { useUser: v, useOptionalUser: v }; });
vi.mock("@/contexts/ChatterContext", () => { const v = () => ({ chatter: session.chatter, logout: vi.fn() }); return { useChatter: v, useOptionalChatter: v }; });
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null, clear: vi.fn() }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

import { AvatarMenu } from "@/components/shell/TopBar";
import { MyShiftsCard } from "@/components/home/ShiftCards";
import ClockDialog from "@/components/shifts/ClockDialog";

const MENU_ITEM = "Clock in and out";
const OFF = "Time tracking is off for your agency";
/** The capture's My shifts tooltip (dashboard#66) and its empty line (#73). */
const MY_SHIFTS_TIP = "Your scheduled shifts during this period";
const NO_DATA = "No data";

/** Creator one's Agency has time tracking on; creator two's (another Agency) has it off. */
const ACCOUNTS = [
  { account_id: "1000001", display_name: "creator_one", time_tracking_enabled: true, clock_in_reminder: false },
  { account_id: "1000002", display_name: "creator_two", time_tracking_enabled: false, clock_in_reminder: false },
];
const OPEN = {
  clock_event_id: 7, employee_id: 41, account_id: "1000001", shift_id: null,
  in_utc: "2026-10-14T16:00:00Z", out_utc: null, close_reason: null,
};

/** Two of the chatter's occurrences, as `GET /admin/shifts/me` lists them. */
const OCCURRENCES = [
  { shift_id: 3, occurrence_start: "2026-10-14T15:00:00Z", occurrence_end: "2026-10-14T19:00:00Z",
    tz: "UTC", account_id: "1000001" },
  { shift_id: 4, occurrence_start: "2026-10-20T09:00:00Z", occurrence_end: "2026-10-20T13:00:00Z",
    tz: "UTC", account_id: "1000002" },
];
/** The owner's `GET /admin/shifts/clocked-in`: one event in a Shift, one in none. */
const CLOCKED_IN = {
  time_tracking_enabled: true,
  clocked_in: [
    { clock_event_id: 7, employee: { id: 41, display_name: "chatter_one" },
      account: { id: "1000001", display_name: "creator_one" }, in_utc: "2026-10-14T16:00:00Z", shift_id: 3,
      shift: { shift_id: 3, occurrence_start: "2026-10-14T15:00:00Z", occurrence_end: "2026-10-14T19:00:00Z",
        accounts: [{ id: "1000001", display_name: "creator_one" }] } },
    { clock_event_id: 8, employee: { id: 42, display_name: "chatter_two" },
      account: { id: "1000002", display_name: "creator_two" }, in_utc: "2026-10-14T16:30:00Z", shift_id: null,
      shift: null },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
/** The chatter's open Clock event in the Relay double, or null. */
let openClock: typeof OPEN | null;
/** What the Relay double lists: the chatter's Creators and occurrences, and the owner's read. */
let accounts: typeof ACCOUNTS;
let occurrences: typeof OCCURRENCES;
let clockedIn: typeof CLOCKED_IN;
/** Reads of these paths fail once with 500, then answer. */
let failOnce: Set<string>;
/** The Agency's week start, as `GET /admin/settings/applied` answers it (spec phase-04, story 20). */
let weekStartDay: "monday" | "sunday";
/** ClockStatus' `can_clock` and `reason`; `open` follows `openClock`. */
let clockGate: { can_clock: boolean; reason: string | null };

function writes(): { path: string; body: unknown }[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init?.method ?? "GET") === "POST")
    .map(([url, init]) => ({ path: String(url).split("?")[0], body: JSON.parse(String(init.body)) }));
}

beforeEach(() => {
  session = { user: null, chatter: { username: "chatter_one" } };
  openClock = null;
  accounts = ACCOUNTS;
  occurrences = [];
  clockedIn = CLOCKED_IN;
  failOnce = new Set();
  weekStartDay = "monday";
  clockGate = { can_clock: true, reason: null };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0];
    const method = init?.method ?? "GET";
    if (method === "GET" && failOnce.delete(path)) return jsonRes({ detail: "relay down" }, 500);
    if (method === "GET" && path === "/admin/shifts") return jsonRes({ occurrences: occurrences.map((o) => ({ ...o, employees: [{ id: 7, display_name: "Jane Lee" }, { id: 8, display_name: "John Smith" }], accounts: [] })) });
    if (method === "GET" && path === "/admin/shifts/me") {
      return jsonRes({ accounts, occurrences, open_clocks: openClock ? [openClock] : [], reminder: null });
    }
    if (method === "GET" && path === "/admin/shifts/clocked-in") return jsonRes(clockedIn);
    if (method === "GET" && path === "/admin/shifts/clock-status") {
      return jsonRes({ ...clockGate, open: openClock, last_closed: null, auto_clock_out_minutes: 10,
        server_now: "2026-10-14T17:00:00Z" });
    }
    if (method === "GET" && path === "/admin/settings/applied") {
      return jsonRes({
        preferences: { tz: null, report_tz: null, week_start: weekStartDay },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all" },
      });
    }
    if (method === "POST" && path === "/admin/shifts/clock-in") {
      openClock = { ...OPEN, account_id: JSON.parse(String(init?.body)).account_id ?? null };
      return jsonRes(openClock);
    }
    if (method === "POST" && path === "/admin/shifts/clock-out") {
      const closed = { ...openClock, out_utc: "2026-10-14T17:00:00Z", close_reason: "manual" };
      openClock = null;
      return jsonRes(closed);
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

const signInOwner = () => {
  session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
};
const reads = () => fetchMock.mock.calls.map(([url]) => String(url).split("?")[0]);
const OWNER_TEXT = /owner sessions act as the agency/i;

const openMenu = () => fireEvent.click(screen.getByRole("button", { name: "Account menu" }));

describe("The avatar menu", () => {
  it.each([
    ["a chatter", { user: null, chatter: { username: "chatter_one" } }],
    ["an owner", { user: { user_id: "owner-1", username: "owner" }, chatter: null }],
  ])("has no clock item for %s: clocking is the top bar's Clock button", (_name, who) => {
    session = who;
    renderWithProviders(<AvatarMenu />);
    openMenu();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: MENU_ITEM })).toBeNull();
    expect(screen.queryByRole("button", { name: /Clock (in|out)/ })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("ClockDialog, for a chatter who names a Creator", () => {
  async function openClockDialog() {
    renderWithProviders(<ClockDialog onClose={() => {}} />);
    await screen.findByRole("dialog", { name: MENU_ITEM });
  }

  it("picks a Creator, clocks in, then sees the open event and clocks out", async () => {
    await openClockDialog();
    const picker = await screen.findByRole("combobox", { name: "Creator" });
    expect(Array.from((picker as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(["creator_one", "creator_two"]);
    expect(screen.queryByText(OFF)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
    await screen.findByRole("button", { name: "Clock out" });
    expect(writes()).toEqual([{ path: "/admin/shifts/clock-in", body: { account_id: "1000001" } }]);
    expect(screen.getByText(/^Clocked in on creator_one since /)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clock in" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clock out" }));
    await screen.findByRole("button", { name: "Clock in" });
    expect(writes()).toEqual([
      { path: "/admin/shifts/clock-in", body: { account_id: "1000001" } },
      { path: "/admin/shifts/clock-out", body: { clock_event_id: 7 } },
    ]);
    expect(screen.queryByText(/^Clocked in on /)).toBeNull();
  });

  it("a Creator whose agency has time tracking off shows the off message and cannot be clocked in on", async () => {
    await openClockDialog();
    fireEvent.change(await screen.findByRole("combobox", { name: "Creator" }), { target: { value: "1000002" } });
    expect(screen.getByText(OFF)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clock in" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
    expect(writes()).toEqual([]);
  });

  it("a refused clock-in says the Relay's reason as the clock's notice", async () => {
    const answer = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => (url === "/admin/shifts/clock-in"
      ? jsonRes({ detail: { error: "inactive", message: "this employee is inactive" } }, 403)
      : answer(url, init)));
    const notices: string[] = [];
    const unsubscribe = onNotice((n) => notices.push(n.text));
    await openClockDialog();
    await screen.findByRole("combobox", { name: "Creator" });
    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
    await waitFor(() => expect(notices).toEqual(["this employee is inactive"]));
    unsubscribe();
  });
});

describe("My shifts, for a chatter", () => {
  it("lists the occurrences the Relay returns and the open event with its elapsed time", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-14T17:05:00Z"));
    occurrences = OCCURRENCES;
    openClock = OPEN;
    renderWithProviders(<MyShiftsCard />);
    const card = await screen.findByRole("region", { name: "My shifts" });
    const open = await screen.findByText("Clocked in on creator_one · 1h 05m");
    // The capture's shift row (#69 to #72): the date, the times in a pill tinted by now / upcoming / past, and the
    // Creator's 24px avatar, in the Shift's own zone.
    const rows = Array.from(card.querySelectorAll("li")).map((li) => ({
      date: li.querySelector("[data-date]")?.textContent,
      time: li.querySelector("[data-time]")?.textContent,
      state: li.querySelector("[data-time]")?.getAttribute("data-state"),
      avatars: Array.from(li.querySelectorAll("[data-avatar]"), (a) => a.getAttribute("title")),
    }));
    expect(rows).toEqual([
      { date: "Wednesday, Oct. 14, 2026", time: "03:00 PM–07:00 PM", state: "now", avatars: ["creator_one"] },
      { date: "Tuesday, Oct. 20, 2026", time: "09:00 AM–01:00 PM", state: "after", avatars: ["creator_two"] },
    ]);
    // The open Clock event and Clock in / out are ours, so they carry the label.
    expect(open.closest(`[title="${EXTRA_LABEL}"]`)).not.toBeNull();
    expect(screen.getByRole("button", { name: "Clock out" }).closest(`[title="${EXTRA_LABEL}"]`)).not.toBeNull();
    expect(screen.queryByText(OWNER_TEXT)).toBeNull();
    expect(reads()).not.toContain("/admin/shifts/clocked-in");
  });

  describe("splits the list at the Agency's week start", () => {
    // Wed 14 Oct 2026, 12:00 EDT; three occurrences at 10:00 EDT on Sat 17,
    // Sun 18 and Tue 20 Oct.
    const AROUND_THE_WEEKEND = ["2026-10-17T14:00:00Z", "2026-10-18T14:00:00Z", "2026-10-20T14:00:00Z"]
      .map((start, i) => ({ shift_id: 10 + i, occurrence_start: start,
        occurrence_end: start.replace("T14", "T18"), tz: "America/New_York", account_id: "1000001" }));

    /** Renders the card and waits until its two week groups list `want`. */
    async function expectWeeks(want: Record<string, string[]>) {
      vi.stubEnv("TZ", "America/New_York");
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date("2026-10-14T16:00:00Z"));
      occurrences = AROUND_THE_WEEKEND;
      renderWithProviders(<MyShiftsCard />);
      const listed = (name: string) => {
        const group = screen.queryByRole("group", { name });
        return group
          ? within(group).getAllByRole("listitem").map((li) =>
            `${li.querySelector("[data-date]")?.textContent} ${li.querySelector("[data-time]")?.textContent?.slice(0, 8)}`)
          : [];
      };
      await waitFor(() => expect({ "This week": listed("This week"), "Next week": listed("Next week") })
        .toEqual(want));
      // The week split is ours (phase-04, story 20), so each heading carries the label.
      for (const name of Object.keys(want).filter((k) => want[k].length > 0)) {
        expect(within(screen.getByRole("group", { name })).getByRole("heading")).toHaveAttribute("title", EXTRA_LABEL);
      }
    }

    it("on Sunday for a Sunday-start Agency", async () => {
      weekStartDay = "sunday";
      await expectWeeks({
        "This week": ["Saturday, Oct. 17, 2026 10:00 AM"],
        "Next week": ["Sunday, Oct. 18, 2026 10:00 AM", "Tuesday, Oct. 20, 2026 10:00 AM"],
      });
    });

    it("on Monday for an Agency that never saved Preferences", async () => {
      await expectWeeks({
        "This week": ["Saturday, Oct. 17, 2026 10:00 AM", "Sunday, Oct. 18, 2026 10:00 AM"],
        "Next week": ["Tuesday, Oct. 20, 2026 10:00 AM"],
      });
    });
  });

  it("shows the empty art and \"No data\" when there is no Shift, under the capture's tooltip (#66, #73)", async () => {
    renderWithProviders(<MyShiftsCard />);
    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "My shifts" }).querySelector('[data-empty-art="data"]')).not.toBeNull();
    expect(screen.getByRole("img", { name: MY_SHIFTS_TIP })).toHaveAttribute("data-info-tip");
  });

  it("clocks in and out from the card in one click, on the agency-wide clock, with no dialog", async () => {
    renderWithProviders(<MyShiftsCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Clock in" }));
    expect(await screen.findByText(/^Clocked in · /)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([{ path: "/admin/shifts/clock-in", body: {} }]);
    fireEvent.click(await screen.findByRole("button", { name: "Clock out" }));
    await screen.findByRole("button", { name: "Clock in" });
    expect(writes()[1]).toEqual({ path: "/admin/shifts/clock-out", body: { clock_event_id: 7 } });
    expect(screen.queryByText(/^Clocked in/)).toBeNull();
  });

  it("opens the clock dialog for a chatter in two Agencies, who names the Creator", async () => {
    clockGate = { can_clock: true, reason: "pick_creator" };
    renderWithProviders(<MyShiftsCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Clock in" }));
    const dialog = await screen.findByRole("dialog", { name: MENU_ITEM });
    await within(dialog).findByRole("combobox", { name: "Creator" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Clock in" }));
    await within(dialog).findByRole("button", { name: "Clock out" });
    expect(writes()).toEqual([{ path: "/admin/shifts/clock-in", body: { account_id: "1000001" } }]);
    // The card re-reads the same query, so it shows the open event too.
    expect(await screen.findByText(/^Clocked in on creator_one · /)).toBeInTheDocument();
  });

  it("has no clock button while ClockStatus says the chatter's role may not clock in", async () => {
    clockGate = { can_clock: false, reason: "role_not_enabled" };
    occurrences = OCCURRENCES;
    renderWithProviders(<MyShiftsCard />);
    await screen.findByRole("region", { name: "My shifts" });
    await waitFor(() => expect(reads()).toContain("/admin/shifts/clock-status"));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button", { name: /Clock (in|out)/ })).toBeNull();
  });

  it("says time tracking is off, labelled ours, with no Settings link and no clock button, when every Creator has it off", async () => {
    accounts = ACCOUNTS.map((a) => ({ ...a, time_tracking_enabled: false }));
    occurrences = OCCURRENCES;
    renderWithProviders(<MyShiftsCard />);
    const off = await screen.findByText("Time tracking is off");
    expect(off.closest(`[title="${EXTRA_LABEL}"]`)).not.toBeNull();
    expect(screen.queryByRole("link", { name: "Settings › Time tracking" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Clock (in|out)/ })).toBeNull();
    // The Shifts still list, as the bundle's card lists them whatever the clock-in setting.
    expect(screen.getByRole("region", { name: "My shifts" }).querySelectorAll("li")).toHaveLength(2);
  });

  it("shows a loading line, then an error line whose Retry refetches", async () => {
    failOnce.add("/admin/shifts/me");
    renderWithProviders(<MyShiftsCard />);
    expect(screen.getByText("Loading your shifts…")).toBeInTheDocument();
    expect(await screen.findByText(/^Couldn't load your shifts: /)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
    expect(reads().filter((p) => p === "/admin/shifts/me")).toHaveLength(2);
  });
});

describe("Scheduled shifts, for an owner", () => {
  it("shows empty only when the schedule is empty", async () => {
    signInOwner();
    renderWithProviders(<MyShiftsCard />);
    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scheduled shifts" })).toHaveClass("max-h-[720px]");
    expect(screen.getByRole("group", { name: "Scheduled shifts list" })).toHaveClass("min-h-0", "overflow-y-auto");
    expect(reads()).toContain("/admin/shifts");
    expect(reads()).not.toContain("/admin/shifts/me");
  });

  it("lists dated shifts, 24-hour times, and all assigned employees for the selected period", async () => {
    signInOwner();
    occurrences = [...OCCURRENCES, { ...OCCURRENCES[0], shift_id: 99 }];
    renderWithProviders(<MyShiftsCard from="2026-10-14T00:00:00Z" to="2026-10-20T23:59:59.999Z" />);
    expect(await screen.findByText("Wednesday, 14.10.2026")).toBeInTheDocument();
    expect(screen.getAllByText("15:00-19:00")).toHaveLength(1);
    expect(screen.getAllByTitle("Jane Lee")).toHaveLength(2);
    expect(screen.getAllByTitle("John Smith")).toHaveLength(2);
    const url = fetchMock.mock.calls.map(([u]) => String(u)).find((u) => u.startsWith("/admin/shifts?"))!;
    expect(new URL(url, "http://localhost").searchParams.get("to")).toBe("2026-10-21T00:00:00.000Z");
  });

  it("shows an error whose Retry refetches the schedule", async () => {
    signInOwner();
    failOnce.add("/admin/shifts");
    renderWithProviders(<MyShiftsCard />);
    expect(await screen.findByText(/^Couldn't load scheduled shifts: /)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
  });
});
