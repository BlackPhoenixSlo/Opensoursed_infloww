/**
 * ClockRecordsModal (w4-a): one Employee's Clock events from Employee reports' Clocked hours, as Infloww's
 * `ClockInModal` timeline in the Agency's zone, its CSV Export, and our Owner edit.
 *
 * Rendered with the relay mocked at `fetch` by URL (`/admin/shifts/clock-events`, the PATCH, and the Applied
 * settings answering America/New_York), so the times below are worked by hand in EDT (UTC-4). Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

vi.mock("@/contexts/UserContext", () => { const v = () => ({ user: { user_id: "owner-1", username: "owner" }, loading: false }); return { useUser: v, useOptionalUser: v }; });
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
let storedTz: string | null;

import ClockRecordsModal from "@/components/stats/ClockRecordsModal";

/** Midnight 1 Oct to the end of 15 Oct, New York: the report's range. */
const FROM = "2026-10-01T04:00:00.000Z";
const TO = "2026-10-16T03:59:59.999Z";

/** Newest first, as the Relay lists them: one open, one auto-closed, one edited. */
const RECORDS = [
  { clock_event_id: 4, employee_id: 41, account_id: null, shift_id: null, in_utc: "2026-10-15T12:00:00Z",
    out_utc: null, close_reason: null, minutes: null, edited: false },
  { clock_event_id: 3, employee_id: 41, account_id: null, shift_id: 9, in_utc: "2026-10-14T13:00:00Z",
    out_utc: "2026-10-14T15:05:30Z", close_reason: "auto", minutes: 126, edited: false },
  { clock_event_id: 2, employee_id: 41, account_id: "1000001", shift_id: null, in_utc: "2026-10-13T22:00:00Z",
    out_utc: "2026-10-13T23:00:00Z", close_reason: "manual", minutes: 60, edited: true },
];

let records: typeof RECORDS;
/** What the list answers instead of the records, or null. */
let listRefusal: { status: number; detail: string } | null;
/** What the PATCH answers instead of the event, or null. */
let patchRefusal: { status: number; detail: string } | null;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  storedTz = "America/New_York";
  records = RECORDS;
  listRefusal = null;
  patchRefusal = null;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0];
    const method = init?.method ?? "GET";
    if (method === "GET" && path === "/admin/shifts/clock-events") {
      return listRefusal ? jsonRes({ detail: listRefusal.detail }, listRefusal.status) : jsonRes({ clock_events: records });
    }
    if (method === "PATCH" && path.startsWith("/admin/shifts/clock-events/")) {
      return patchRefusal ? jsonRes({ detail: patchRefusal.detail }, patchRefusal.status) : jsonRes(RECORDS[1]);
    }
    if (method === "GET" && path === "/admin/settings/applied") {
      return jsonRes({
        preferences: { tz: storedTz, report_tz: null, week_start: "monday" },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all" },
      });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const listCalls = () => fetchMock.mock.calls
  .map(([url]) => new URL(String(url), "http://relay.test"))
  .filter((u) => u.pathname === "/admin/shifts/clock-events");
const patches = () => fetchMock.mock.calls
  .filter(([, init]) => init?.method === "PATCH")
  .map(([url, init]) => ({ path: String(url), body: JSON.parse(String(init.body)) }));

/** Renders the modal and waits until the records show in the Agency's zone. */
const render = async (from = FROM, to = TO) => {
  renderWithProviders(
    <ClockRecordsModal employeeId={41} employeeName="Alpha One" groupName="Night, team" from={from} to={to}
      onClose={() => {}} />,
  );
  if (storedTz) await screen.findByText(new RegExp(`^Times in ${storedTz}`));
};
/** Each record's Infloww lines, in order. */
const lines = () => screen.getAllByRole("listitem")
  .map((li) => within(li).getAllByText(/^Clock (in|out) at /).map((line) => line.textContent));
/** The record of event 2, 3 or 4, found by its clock in day. */
const IN_DAY: Record<number, string> = { 2: "Oct 13", 3: "Oct 14", 4: "Oct 15" };
const record = (id: number) => screen.getAllByRole("listitem")
  .find((li) => within(li).queryByText(new RegExp(`^Clock in at ${IN_DAY[id]}, 2026`)))!;

describe("ClockRecordsModal", () => {
  it("asks for the report's range at hour precision, its end hour included, and shows Infloww's lines in the zone", async () => {
    await render();
    const dialog = await screen.findByRole("dialog", { name: "Clocked hours" });
    await screen.findByText(/^Clock in at Oct 15, 2026/);
    const [req, ...more] = listCalls();
    expect(more).toHaveLength(0);
    // Until the user picks, the report's exact range.
    expect(Object.fromEntries(req.searchParams)).toEqual({ employee_id: "41", from: FROM, to: TO });
    expect((within(dialog).getByLabelText("From") as HTMLInputElement).value).toBe("2026-10-01T00:00");
    expect((within(dialog).getByLabelText("To") as HTMLInputElement).value).toBe("2026-10-15T23:00");
    expect(within(dialog).getByLabelText("From")).toHaveAttribute("step", "3600");
    expect(within(dialog).getByText(/^Times in /)).toHaveTextContent("Times in America/New_York (UTC-4)");
    expect(lines()).toEqual([
      ["Clock in at Oct 15, 2026 8:00:00 AM"],
      ["Clock out at Oct 14, 2026 11:05:30 AM (2h 6min) (auto clock out)", "Clock in at Oct 14, 2026 9:00:00 AM"],
      ["Clock out at Oct 13, 2026 7:00:00 PM (1h) (edited)", "Clock in at Oct 13, 2026 6:00:00 PM"],
    ]);
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("in a zone a half hour off the report's, the default still reads the report's exact range", async () => {
    storedTz = "Asia/Kolkata";
    await render();
    await screen.findByText(/^Clock in at Oct 15, 2026/);
    expect(listCalls().map((u) => [u.searchParams.get("from"), u.searchParams.get("to")])).toEqual([[FROM, TO]]);
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-10-01T09:00");
  });

  it("falls back to the browser's zone while the Agency stored none", async () => {
    storedTz = null;
    await render();
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(await screen.findByText(/^Times in /)).toHaveTextContent(new RegExp(`^Times in ${zone.replace("/", "\\/")}`));
  });

  it("a new range re-asks the Relay for it, its end hour included", async () => {
    await render();
    await screen.findByText(/^Clock in at Oct 15, 2026/);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-14T09:45" } });
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    expect(listCalls()[1].searchParams.get("from")).toBe("2026-10-14T13:00:00.000Z");
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-10-14T09:00");
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-15T22:00" } });
    await waitFor(() => expect(listCalls()).toHaveLength(3));
    expect(listCalls()[2].searchParams.get("to")).toBe("2026-10-16T03:00:00.000Z");
  });

  it("Export downloads Infloww's file name and five columns, with the group the card names and \"-\" while open", async () => {
    let blob: Blob | null = null;
    let fileName = "";
    const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn((b: Blob) => { blob = b; return "blob:clock-records"; });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      fileName = this.download;
    });
    onTestFinished(() => { URL.createObjectURL = saved.create; URL.revokeObjectURL = saved.revoke; click.mockRestore(); });

    await render();
    await screen.findByText(/^Clock in at Oct 15, 2026/);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    // The group comes from the card: no roster or groups read.
    expect(fetchMock.mock.calls.map(([u]) => String(u).split("?")[0]))
      .not.toEqual(expect.arrayContaining(["/admin/employees"]));

    expect(fileName).toBe("Clocked_Hours_Alpha_One_2026-10-01_to_2026-10-15.csv");
    expect(await blob!.text()).toBe([
      "Group,Employee,Clocked hours,Clock in date/time (America/New_York),Clock out date/time (America/New_York)",
      "\"Night, team\",Alpha One,-,2026-10-15 08:00:00,-",
      "\"Night, team\",Alpha One,2.10,2026-10-14 09:00:00,2026-10-14 11:05:30",
      "\"Night, team\",Alpha One,1.00,2026-10-13 18:00:00,2026-10-13 19:00:00",
    ].join("\n"));
  });

  it("Edit sends only the changed time and re-reads the records", async () => {
    await render();
    await screen.findByText(/^Clock in at Oct 14, 2026/);
    fireEvent.click(within(record(3)).getByRole("button", { name: "Edit" }));
    expect((within(record(3)).getByLabelText("Clock in") as HTMLInputElement).value).toBe("2026-10-14T09:00");
    expect((within(record(3)).getByLabelText("Clock out") as HTMLInputElement).value).toBe("2026-10-14T11:05");
    fireEvent.change(within(record(3)).getByLabelText("Clock in"), { target: { value: "2026-10-14T08:30" } });
    fireEvent.click(within(record(3)).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(within(record(3)).queryByLabelText("Clock in")).toBeNull());
    expect(patches()).toEqual([{ path: "/admin/shifts/clock-events/3", body: { in_utc: "2026-10-14T12:30:00.000Z" } }]);
    expect(listCalls().length).toBeGreaterThanOrEqual(2);
  });

  it("Save with nothing changed sends nothing", async () => {
    await render();
    await screen.findByText(/^Clock in at Oct 14, 2026/);
    fireEvent.click(within(record(2)).getByRole("button", { name: "Edit" }));
    fireEvent.click(within(record(2)).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(within(record(2)).queryByLabelText("Clock in")).toBeNull());
    expect(patches()).toEqual([]);
  });

  it("\"Clock out now…\" on an open record sends only out_utc, this minute", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-15T14:07:42Z"));
    await render();
    await screen.findByText(/^Clock in at Oct 15, 2026/);
    expect(within(record(3)).queryByRole("button", { name: "Clock out now…" })).toBeNull();
    fireEvent.click(within(record(4)).getByRole("button", { name: "Clock out now…" }));
    expect(within(record(4)).queryByLabelText("Clock in")).toBeNull();
    expect((within(record(4)).getByLabelText("Clock out") as HTMLInputElement).value).toBe("2026-10-15T10:07");
    fireEvent.click(within(record(4)).getByRole("button", { name: "Clock out" }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toEqual({ path: "/admin/shifts/clock-events/4", body: { out_utc: "2026-10-15T14:07:00.000Z" } });
  });

  it.each([
    [409, "overlaps this Employee's other Clock event(s) 2"],
    [422, "in_utc must be before out_utc"],
  ])("a %i on Save shows the Relay's text inline and keeps the inputs", async (status, detail) => {
    patchRefusal = { status, detail };
    await render();
    await screen.findByText(/^Clock in at Oct 14, 2026/);
    fireEvent.click(within(record(3)).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(record(3)).getByLabelText("Clock out"), { target: { value: "2026-10-14T12:00" } });
    fireEvent.click(within(record(3)).getByRole("button", { name: "Save" }));
    expect(await within(record(3)).findByRole("alert")).toHaveTextContent(detail);
    expect(within(record(3)).getByLabelText("Clock out")).toBeInTheDocument();
    expect(within(record(3)).getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("a clock out at or before the clock in is refused inline, nothing sent", async () => {
    await render();
    await screen.findByText(/^Clock in at Oct 14, 2026/);
    fireEvent.click(within(record(3)).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(record(3)).getByLabelText("Clock out"), { target: { value: "2026-10-14T08:00" } });
    fireEvent.click(within(record(3)).getByRole("button", { name: "Save" }));
    expect(await within(record(3)).findByRole("alert")).toHaveTextContent("Clock out must be after clock in.");
    expect(patches()).toEqual([]);
  });

  it("shows a loading line, then an error with Retry, and an empty line", async () => {
    listRefusal = { status: 500, detail: "boom" };
    void render();
    expect(screen.getByText("Loading clock records…")).toBeInTheDocument();
    expect(await screen.findByText("Couldn't load clock records: boom")).toBeInTheDocument();
    listRefusal = null;
    records = [];
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });
});
