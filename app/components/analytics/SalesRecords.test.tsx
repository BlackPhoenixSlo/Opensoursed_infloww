/**
 * SalesRecords — Analytics > Sales records (docs/spec/phase-05-remaining-parity-gaps.md, item 3; ticket 33,
 * stories 19-21, 25, 26 and 29; ticket 34, Reassign, stories 22 and 23).
 *
 * Rendered with the relay mocked at `fetch` by URL: `/admin/stats/sales-records` answers pages of Sales records,
 * `/admin/employees` the Agency's roster (the Employees filter's and the Reassign picker's options),
 * `/admin/employee-groups` its Employee groups (the Employees filter's groups, ticket 36) and
 * `/admin/ingest/transactions/{id}/attribute` a Reassign and `/admin/ingest/transactions/attribute` a batch one
 * (roadmap W6 6.5), so the columns, the filters, paging, the CSV export and Reassign are assertions about the wire. The clock is pinned to 2026-05-04 12:00 UTC and the report time zone is UTC,
 * so every date bound below is written out by hand. Every name is fake. The filters are `IfSelect`s (a combobox
 * button and a listbox), and the table's end is an IntersectionObserver sentinel, stubbed so a test can scroll to it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: { user_id: "owner-1", username: "owner" }, loading: false }),
}));
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({
    isPending: false,
    data: { preferences: { tz: null, report_tz: "UTC", week_start: "monday" } },
  }),
}));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({
    data: { accounts: [{ id: "3000001", nickname: "fixture_creator_one" }, { id: "3000002", nickname: "fixture_creator_two" }] },
  }),
}));

import SalesRecords, { type SalesRecord } from "@/components/analytics/SalesRecords";

const ROUTE = "/admin/stats/sales-records";

const MSG_ROW = {
  tx_id: 42, occurred_at: "2026-05-04T10:00:00Z", employee_id: 7, employee_name: "Alpha One", account_id: "3000001",
  fan_id: 11, fan_label: "Fixture Fan Eleven", earnings_cents: 1000, gross_cents: 1000, net_cents: 800,
  kind: "ppv_message", rule: "message", assigned_by: "Auto", status: "cleared",
};
const LOOSE_ROW = {
  tx_id: 41, occurred_at: "2026-05-03T23:05:00Z", employee_id: null, employee_name: null, account_id: "3000002",
  fan_id: 14, fan_label: null, earnings_cents: 300, gross_cents: 300, net_cents: null,
  kind: "tip", rule: "unassigned", assigned_by: "Auto", status: "pending",
};
const MANUAL_ROW = {
  tx_id: 40, occurred_at: "2026-05-02T08:30:00Z", employee_id: 8, employee_name: "Beta Two", account_id: "3000001",
  fan_id: 13, fan_label: "@fixture_fan_13", earnings_cents: 150, gross_cents: 150, net_cents: null,
  kind: "tip", rule: "manual", assigned_by: "Manual", status: "cleared",
};

let fetchMock: ReturnType<typeof vi.fn>;
/** When set, every Sales records read fails with this status. */
let failWith: number | null;
/** The sentinel observers, newest last. */
let observers: IntersectionObserverCallback[];
/** The first page's sale 42 as the Relay serves it now: a Reassign POST swaps it for the Relay's answer after. */
let saleFortyTwo: SalesRecord;
/** When set, the whole read is these rows, one page. */
let onePage: SalesRecord[] | null;
const REASSIGNED_42 = { ...MSG_ROW, employee_id: 9, employee_name: "Gamma Chatter", rule: "manual", assigned_by: "Owner" };
const CLEARED_42 = { ...MSG_ROW, employee_id: null, employee_name: null, rule: "unassigned", assigned_by: "Auto" };
const NO_ONE_42 = { ...MSG_ROW, employee_id: null, employee_name: null, rule: "manual", assigned_by: "Owner" };
const answerFor = (employeeId: unknown) =>
  employeeId === 9 ? REASSIGNED_42 : employeeId === "no_one" ? NO_ONE_42 : CLEARED_42;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-05-04T12:00:00Z"));
  saleFortyTwo = MSG_ROW;
  onePage = null;
  failWith = null;
  observers = [];
  vi.stubGlobal("IntersectionObserver", class {
    constructor(cb: IntersectionObserverCallback) { observers.push(cb); }
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(String(url), "http://relay.test");
    if (u.pathname === "/admin/employees") {
      // The Agency's roster, a chatter's Mirror Employee included.
      return jsonRes({ employees: [
        { id: 7, display_name: "Alpha One", is_active: true },
        { id: 8, display_name: "Beta Two", is_active: true },
        { id: 9, display_name: "Gamma Chatter", is_active: true, chatter_id: "chatter-1" },
      ] });
    }
    if (u.pathname === "/admin/employee-groups") {
      return jsonRes({ groups: [
        { id: 21, name: "Fixture Night Team", parent_id: null, employee_count: 2 },
        { id: 22, name: "Fixture Late Crew", parent_id: 21, employee_count: 0 },
      ] });
    }
    if (u.pathname === "/admin/ingest/transactions/42/attribute" && init?.method === "POST") {
      const { employee_id } = JSON.parse(String(init.body));
      saleFortyTwo = answerFor(employee_id);
      return jsonRes({ id: 42, account_id: "3000001", kind: "ppv_message", amount_cents: 1000,
        attributed_employee_id: employee_id });
    }
    if (u.pathname === "/admin/ingest/transactions/attribute" && init?.method === "POST") {
      const { employee_id, tx_ids } = JSON.parse(String(init.body));
      if (tx_ids.includes(42)) saleFortyTwo = answerFor(employee_id);
      return jsonRes({ updated: tx_ids.length, attributed_employee_id: employee_id === "no_one" ? 0 : employee_id,
        tx_ids });
    }
    if (u.pathname === ROUTE && failWith) return jsonRes({ detail: "fixture relay down" }, failWith);
    if (u.pathname === ROUTE && onePage) return jsonRes({ rows: onePage, next_before_id: null });
    if (u.pathname === ROUTE) {
      return u.searchParams.get("before_id") === "41"
        ? jsonRes({ rows: [MANUAL_ROW], next_before_id: null })
        : jsonRes({ rows: [saleFortyTwo, LOOSE_ROW], next_before_id: 41 });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Every Sales records request sent so far. */
function reads(): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === ROUTE)
    .map((u) => u.searchParams);
}

const last = () => reads().at(-1)!;

function cells(row: HTMLElement): string[] {
  return within(row).getAllByRole("cell").map((c) => c.textContent ?? "");
}

/** Opens the `IfSelect` named `name` and picks `option`. */
async function pick(name: string, option: string, root: HTMLElement = document.body) {
  fireEvent.click(within(root).getByRole("combobox", { name }));
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

/** The option texts of the `IfSelect` named `name` (opened, read, closed), once `until` is listed. */
async function optionsOf(name: string, until?: string): Promise<string[]> {
  const box = screen.getByRole("combobox", { name });
  fireEvent.click(box);
  const list = screen.getByRole("listbox", { name });
  if (until) await within(list).findByRole("option", { name: until });
  const texts = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
  fireEvent.click(box);
  return texts;
}

/** The end of the table comes into view. */
function scrollToEnd() {
  act(() => observers.at(-1)!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
}

describe("SalesRecords", () => {
  it("renders Infloww's columns and one row per sale, with its Rule, Assigned by and Status", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "", "Date & time", "Employee", "Creator", "Fan", "Earnings", "Gross revenue", "Net revenue", "Type", "Rule",
      "Assigned by", "Status", "Action",
    ]);
    const [, first, second] = within(table).getAllByRole("row");
    expect(cells(first)).toEqual([
      "", "May 4, 2026 10:00am", "Alpha One", "fixture_creator_one", "Fixture Fan Eleven", "$10.00", "$10.00", "$8.00",
      "PPV message", "Message sender", "Auto", "Complete", "Reassign",
    ]);
    expect(cells(second)).toEqual([
      "", "May 3, 2026 11:05pm", "Unassigned", "fixture_creator_two", "Fan #14", "$3.00", "$3.00", "—",
      "Tip", "Unassigned", "Auto", "Pending", "Reassign",
    ]);
  });

  it("labels every relay status as Infloww does: Complete, Pending, Reverse, Refunded", async () => {
    onePage = ["cleared", "pending", "chargedback", "refunded", "refund_pending"].map((status, i) => ({
      ...LOOSE_ROW, tx_id: 100 + i, status,
    }));
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row").slice(1).map((r) => cells(r)[11])).toEqual([
      "Complete", "Pending", "Reverse", "Refunded", "Refunded",
    ]);
  });

  it("a pending (uncleared) sale shows under the default filters and goes into the CSV's query unfiltered", async () => {
    const hrefs: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      hrefs.push(this.href);
    });
    onePage = [LOOSE_ROW];
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    expect(cells(within(table).getAllByRole("row")[1])[11]).toBe("Pending");
    expect(last().has("status")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(new URL(hrefs[0]).searchParams.has("status")).toBe(false);
  });

  it("asks for Month (the reports' 30d) by default, and each date preset and filter narrows the read", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    expect(reads()).toHaveLength(1);
    // Month is Employee reports' 30d window: 30 days before today through today.
    expect(last().get("from")).toBe("2026-04-05T00:00:00.000Z");
    expect(last().get("to")).toBe("2026-05-04T23:59:59.999Z");
    expect(last().has("account_id") || last().has("employee_id") || last().has("kind")).toBe(false);
    expect(last().has("assigned") || last().has("before_id")).toBe(false);

    // The presets and the dates live in the range box's popover (page-parity ticket 25).
    fireEvent.click(screen.getByRole("button", { name: /^Date range/ }));
    fireEvent.click(screen.getByRole("button", { name: "Day" }));
    await waitFor(() => expect(last().get("from")).toBe("2026-05-04T00:00:00.000Z"));
    expect(last().get("to")).toBe("2026-05-04T23:59:59.999Z");
    fireEvent.click(screen.getByRole("button", { name: "Week" }));
    await waitFor(() => expect(last().get("from")).toBe("2026-04-28T00:00:00.000Z"));
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    await waitFor(() => expect(last().get("from")).toBe("2026-04-05T00:00:00.000Z"));

    await pick("Creator", "fixture_creator_two");
    await waitFor(() => expect(last().getAll("account_id")).toEqual(["3000002"]));
    await pick("Sales types", "Tip");
    await waitFor(() => expect(last().getAll("kind")).toEqual(["tip"]));
    await pick("Assigned", "Unassigned sales only");
    await waitFor(() => expect(last().get("assigned")).toBe("unassigned"));
    // Unassigned sales have no Employee: the Employees filter waits (Infloww's rule).
    expect(screen.getByRole("combobox", { name: "Employees" })).toBeDisabled();
    await pick("Assigned", "Assigned sales only");
    await waitFor(() => expect(last().get("assigned")).toBe("assigned"));
    await pick("Employees", "Beta Two");
    await waitFor(() => expect(last().getAll("employee_id")).toEqual(["8"]));
    // ...and with an Employee picked, Unassigned sales only cannot be chosen.
    fireEvent.click(screen.getByRole("combobox", { name: "Assigned" }));
    expect(screen.getByRole("option", { name: "Unassigned sales only" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByRole("combobox", { name: "Assigned" }));

    // Typing either date switches the shared picker to Custom.
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-03-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-03-31" } });
    await waitFor(() => expect(last().get("from")).toBe("2026-03-01T00:00:00.000Z"));
    expect(last().get("to")).toBe("2026-03-31T23:59:59.999Z");
    expect(last().getAll("account_id")).toEqual(["3000002"]);
    expect(last().getAll("kind")).toEqual(["tip"]);
  });

  it("the assigned filter offers Infloww's three choices", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    expect(screen.getByRole("combobox", { name: "Assigned" })).toHaveTextContent("Assigned and unassigned sales");
    expect(await optionsOf("Assigned")).toEqual([
      "Assigned and unassigned sales", "Assigned sales only", "Unassigned sales only",
    ]);
  });

  it("Reset puts every filter and the range back, drops the selection and reads with no filter params", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    await pick("Creator", "fixture_creator_one");
    await pick("Employees", "Alpha One");
    await pick("Sales types", "PPV message");
    await pick("Assigned", "Assigned sales only");
    fireEvent.click(screen.getByRole("button", { name: /^Date range/ }));
    fireEvent.click(screen.getByRole("button", { name: "Day" }));
    await waitFor(() => expect(last().get("from")).toBe("2026-05-04T00:00:00.000Z"));
    expect(last().getAll("employee_id")).toEqual(["7"]);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select sale 42" }));
    expect(screen.getByRole("group", { name: "Batch reassign" })).toBeInTheDocument();

    const before = reads().length;
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(reads().length).toBeGreaterThan(before));
    expect([...last().keys()].sort()).toEqual(["from", "to"]);
    expect(last().get("from")).toBe("2026-04-05T00:00:00.000Z");
    expect(last().get("to")).toBe("2026-05-04T23:59:59.999Z");
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("All creators");
    expect(screen.getByRole("combobox", { name: "Employees" })).toHaveTextContent("All employees");
    expect(screen.getByRole("combobox", { name: "Sales types" })).toHaveTextContent("All sales types");
    expect(screen.getByRole("combobox", { name: "Assigned" })).toHaveTextContent("Assigned and unassigned sales");
    await screen.findByRole("table");
    expect(screen.queryByRole("group", { name: "Batch reassign" })).toBeNull();
  });

  it("the Employees filter accepts an Employee group, sent as group_id in place of employee_id", async () => {
    const hrefs: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      hrefs.push(this.href);
    });
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    expect(await optionsOf("Employees", "Group: Fixture Night Team")).toEqual([
      "All employees", "Alpha One", "Beta Two", "Gamma Chatter", "Group: Fixture Night Team", "Group: Fixture Late Crew",
    ]);

    await pick("Employees", "Group: Fixture Night Team");
    await waitFor(() => expect(last().getAll("group_id")).toEqual(["21"]));
    expect(last().has("employee_id")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(new URL(hrefs[0]).searchParams.getAll("group_id")).toEqual(["21"]);

    await pick("Employees", "Beta Two");
    await waitFor(() => expect(last().getAll("employee_id")).toEqual(["8"]));
    expect(last().has("group_id")).toBe(false);
  });

  it("shows the Creator tag filter Not wired", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    const tag = screen.getByRole("combobox", { name: "Creator tag" });
    expect(tag).toBeDisabled();
    expect(tag.closest("[title]")).toHaveAttribute("title", "not wired");
  });

  it("draws no native select, even with Reassign and the batch bar open", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", { name: "Reassign" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select sale 41" }));
    expect(screen.getByRole("group", { name: "Batch reassign" })).toBeInTheDocument();
    expect(document.querySelectorAll("select")).toHaveLength(0);
  });

  it("scrolling to the end asks for the next page by before_id and appends it, then says it is the end", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    expect(screen.queryByText("You have reached the end of the page")).toBeNull();
    scrollToEnd();
    await screen.findByText("Beta Two", { selector: "td" });
    expect(last().get("before_id")).toBe("41");
    expect(last().get("from")).toBe(reads()[0].get("from"));
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => cells(r)[2])).toEqual(["Alpha One", "Unassigned", "Beta Two"]);
    expect(cells(rows[2]).slice(8)).toEqual(["Tip", "Manual", "Manual", "Complete", "Reassign"]);
    expect(screen.getByText("You have reached the end of the page")).toBeInTheDocument();
  });

  it("an empty read shows No data, and no end line", async () => {
    onePage = [];
    renderWithProviders(<SalesRecords />);
    expect(await screen.findByText("No data")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("You have reached the end of the page")).toBeNull();
  });

  it("a failed read shows the Relay's message and Retry, which reads again", async () => {
    failWith = 503;
    renderWithProviders(<SalesRecords />);
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByText(/fixture relay down/)).toBeInTheDocument();
    const before = reads().length;
    failWith = null;
    fireEvent.click(retry);
    await screen.findByRole("table");
    expect(reads().length).toBe(before + 1);
  });

  it("Export downloads the Relay's CSV form of the filtered set, not one page", async () => {
    const hrefs: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      hrefs.push(this.href);
    });
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    await pick("Creator", "fixture_creator_one");
    await pick("Assigned", "Unassigned sales only");
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(hrefs).toHaveLength(1);
    const u = new URL(hrefs[0]);
    expect(u.pathname).toBe(ROUTE);
    expect(u.searchParams.get("format")).toBe("csv");
    expect(u.searchParams.getAll("account_id")).toEqual(["3000001"]);
    expect(u.searchParams.get("assigned")).toBe("unassigned");
    expect(u.searchParams.get("from")).toBe("2026-04-05T00:00:00.000Z");
    expect(u.searchParams.get("to")).toBe("2026-05-04T23:59:59.999Z");
    expect(u.searchParams.has("before_id") || u.searchParams.has("limit")).toBe(false);
  });

  it("is the tab's body alone: Employee reports' frame draws the header", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });

  it("draws a split sale's every share, one row per Employee and Rule", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    onePage = [
      { ...MSG_ROW, earnings_cents: 500 },
      { ...MSG_ROW, employee_id: 8, employee_name: "Beta Two", earnings_cents: 500 },
    ];
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row").slice(1).map((r) => cells(r)[2])).toEqual(["Alpha One", "Beta Two"]);
    expect(errors.mock.calls.some((c) => String(c[0]).includes("same key"))).toBe(false);
  });

  it("Reassign's picker lists only the Agency's Employees, from the roster, plus No one and Clear", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", { name: "Reassign" }));
    const picker = await screen.findByRole("combobox", { name: "Reassign to" });
    expect(picker).toHaveTextContent("Choose an employee");
    expect(await optionsOf("Reassign to", "Gamma Chatter")).toEqual([
      "Alpha One", "Beta Two", "Gamma Chatter", "No one", "Clear assignment",
    ]);
    // Nothing is sent until Save, and Save waits for a choice.
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("combobox", { name: "Reassign to" })).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("Save sends the existing attribute route's body, and the row's Employee, Rule and Assigned by update", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", { name: "Reassign" }));
    await pick("Reassign to", "Gamma Chatter");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(cells(within(table).getAllByRole("row")[1]).slice(9, 11)).toEqual(["Manual", "Owner"]));
    expect(cells(within(table).getAllByRole("row")[1])[2]).toBe("Gamma Chatter");
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(new URL(String(posts[0][0]), "http://relay.test").pathname).toBe("/admin/ingest/transactions/42/attribute");
    expect(JSON.parse(String((posts[0][1] as RequestInit).body))).toEqual({ employee_id: 9 });
    expect(screen.queryByRole("combobox", { name: "Reassign to" })).toBeNull();
  });

  it("Clear assignment sends a null Employee and the row falls back to its Rule", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", { name: "Reassign" }));
    await pick("Reassign to", "Clear assignment");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(cells(within(table).getAllByRole("row")[1]).slice(9, 11)).toEqual(["Unassigned", "Auto"]));
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts.map(([, init]) => JSON.parse(String((init as RequestInit).body)))).toEqual([{ employee_id: null }]);
  });

  it("No one sends \"no_one\" and the row reads No one, Manual, Owner", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(within(table).getAllByRole("row")[1]).getByRole("button", { name: "Reassign" }));
    await pick("Reassign to", "No one");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(cells(within(table).getAllByRole("row")[1]).slice(9, 11)).toEqual(["Manual", "Owner"]));
    expect(cells(within(table).getAllByRole("row")[1])[2]).toBe("No one");
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts.map(([, init]) => JSON.parse(String((init as RequestInit).body)))).toEqual([{ employee_id: "no_one" }]);
  });

  it("selected rows are reassigned in one batch call, and the selection then clears", async () => {
    renderWithProviders(<SalesRecords />);
    const table = await screen.findByRole("table");
    expect(screen.queryByRole("group", { name: "Batch reassign" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select sale 42" }));
    const bar = screen.getByRole("group", { name: "Batch reassign" });
    expect(bar).toHaveTextContent("1 sales record selected");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(bar).toHaveTextContent("2 sales records selected");
    expect(screen.getByRole("checkbox", { name: "Select sale 41" })).toBeChecked();

    expect(within(bar).getByRole("button", { name: "Reassign selected" })).toBeDisabled();
    await pick("Reassign selected to", "Gamma Chatter", bar);
    fireEvent.click(within(bar).getByRole("button", { name: "Reassign selected" }));

    await waitFor(() => expect(cells(within(table).getAllByRole("row")[1])[2]).toBe("Gamma Chatter"));
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(new URL(String(posts[0][0]), "http://relay.test").pathname).toBe("/admin/ingest/transactions/attribute");
    expect(JSON.parse(String((posts[0][1] as RequestInit).body))).toEqual({ employee_id: 9, tx_ids: [42, 41] });
    await waitFor(() => expect(screen.queryByRole("group", { name: "Batch reassign" })).toBeNull());
    expect(screen.getByRole("checkbox", { name: "Select sale 42" })).not.toBeChecked();
  });

  it("Select all takes at most 500 sales, the Relay's batch cap, and says so", async () => {
    onePage = Array.from({ length: 501 }, (_, i) => ({ ...LOOSE_ROW, tx_id: 2000 - i }));
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("checkbox", { name: "Select sale 1500" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    const bar = screen.getByRole("group", { name: "Batch reassign" });
    expect(bar).toHaveTextContent("500 sales records selected");
    expect(bar).toHaveTextContent("At most 500 sales per batch");
    expect(screen.getByRole("checkbox", { name: "Select all" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select sale 1501" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select sale 1500" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select sale 1501" }));
    expect(bar).toHaveTextContent("499 sales records selected");
    expect(bar).not.toHaveTextContent("At most 500");
    expect(screen.getByRole("checkbox", { name: "Select sale 1500" })).toBeEnabled();
  }, 30_000); // 501 rendered rows: several seconds in jsdom, past the 5 s default when the machine is loaded.

  it("a filter change drops the selection", async () => {
    renderWithProviders(<SalesRecords />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select sale 41" }));
    expect(screen.getByRole("group", { name: "Batch reassign" })).toBeInTheDocument();
    await pick("Sales types", "Tip");
    await waitFor(() => expect(screen.queryByRole("group", { name: "Batch reassign" })).toBeNull());
  });
});

