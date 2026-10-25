/**
 * ChattingStatsTable — Employee reports' "Chatting statistics" (roadmap W5 5.2).
 *
 * Rendered with the relay mocked at `fetch` by URL: `/admin/stats/chatting-stats` answers the rows, so the request,
 * the direct vs mass split and the formatted figures are assertions about the wire. Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

// The Export pop-up reads the role's denied actions; nothing is denied here.
vi.mock("@/lib/appliedSettings", () => ({ useAppliedSettings: () => ({ data: undefined }) }));

import ChattingStatsTable from "@/components/stats/ChattingStatsTable";
import { type ChattingStatsRow } from "@/hooks/useStats";
import { fmtReplyTime } from "@/lib/format";

const FROM = "2026-09-15T04:00:00.000Z";
const TO = "2026-10-15T03:59:59.999Z";

const ROW: ChattingStatsRow = {
  employee_id: 1, display_name: "Alpha One",
  per_account: [{ account_id: "11", account_nickname: "Creator Eleven" }],
  sales_cents: 150000, ppv_sales_cents: 120000, tip_sales_cents: 30000, direct_message_sales_cents: 90000,
  mass_message_sales_cents: 45000, priority_mass_message_sales_cents: 7500, direct_messages_sent: 400, direct_ppvs_sent: 40, golden_ratio: 10,
  ppvs_unlocked: 10, unlock_rate: 25, fans_chatted: 80, fans_who_spent: 8, fan_cvr: 10, avg_spend_per_fan_cents: 15000,
  character_count: 12000, replies: 30, avg_reply_seconds: 185, clocked_minutes: 480, sales_per_clocked_hour_cents: 15000,
  messages_per_clocked_hour: 50, fans_chatted_per_clocked_hour: 10,
};
const IDLE: ChattingStatsRow = {
  ...ROW, employee_id: 2, display_name: "Beta Two",
  per_account: [{ account_id: "11", account_nickname: "Creator Eleven" }, { account_id: "12", account_nickname: null }],
  sales_cents: 0, direct_message_sales_cents: 0, mass_message_sales_cents: 0, golden_ratio: null,
  avg_reply_seconds: null, clocked_minutes: 0, sales_per_clocked_hour_cents: null,
  messages_per_clocked_hour: null, fans_chatted_per_clocked_hour: null,
};

/** The 30 days before FROM..TO, as useReportRange gives them. */
const PRIOR_FROM = "2026-08-16T04:00:00.000Z";
const PRIOR_TO = "2026-09-15T03:59:59.999Z";

let fetchMock: ReturnType<typeof vi.fn>;
let employees: ChattingStatsRow[];
let priorEmployees: ChattingStatsRow[];

beforeEach(() => {
  employees = [IDLE, ROW];
  priorEmployees = [];
  fetchMock = vi.fn(async (url: string) => {
    if (String(url).split("?")[0] === "/admin/stats/chatting-stats") {
      const prior = new URL(String(url), "http://relay.test").searchParams.get("from") === PRIOR_FROM;
      return jsonRes({ employees: prior ? priorEmployees : employees, attribution_fallback: null });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ChattingStatsTable", () => {
  it("requests the report's range and shows each Employee's direct, mass and priority mass sales, highest sales first", async () => {
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} />);
    const table = await screen.findByRole("table");
    const url = new URL(String(fetchMock.mock.calls[0][0]), "http://relay.test");
    expect([url.searchParams.get("from"), url.searchParams.get("to")]).toEqual([FROM, TO]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["Alpha One", "Beta Two"]);
    const alpha = rows[0].textContent ?? "";
    for (const text of ["Creator Eleven", "$900", "$450", "$75", "10.00%", "25.00%", "3m 05s", "8h", "50.00"]) {
      expect(alpha).toContain(text);
    }
    expect(rows[1].textContent).toContain("2 creators");
    expect(within(table).getByText("OF mass messages sales").getAttribute("title"))
      .toBe("Sales generated from OF mass messages sent by employee");
  });

  it("sorts by a clicked column, and again the other way", async () => {
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(table).getByText("Employees"));
    const first = () => within(within(table).getAllByRole("row")[1]).getAllByRole("cell")[0].textContent;
    await waitFor(() => expect(first()).toBe("Alpha One"));
    fireEvent.click(within(table).getByText(/^Employees/));
    await waitFor(() => expect(first()).toBe("Beta Two"));
  });

  it("leaves out the clocked-time columns a chatter is not sent", async () => {
    employees = [{ ...ROW, clocked_minutes: null, sales_per_clocked_hour_cents: null, messages_per_clocked_hour: null,
      fans_chatted_per_clocked_hour: null }];
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} />);
    const table = await screen.findByRole("table");
    expect(within(table).queryByText("Clocked hours")).toBeNull();
    expect(within(table).queryByText("Sales per clocked hour")).toBeNull();
    expect(within(table).getByText("Response time")).toBeTruthy();
  });

  it("shows each figure's change against the window before, with one more read", async () => {
    employees = [ROW];
    priorEmployees = [{ ...ROW, sales_cents: 100000, ppv_sales_cents: 150000, tip_sales_cents: 0,
      avg_reply_seconds: 370, fans_chatted: 40 }];
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} priorFrom={PRIOR_FROM} priorTo={PRIOR_TO} />);
    const table = await screen.findByRole("table");
    await waitFor(() => expect(fetchMock.mock.calls.map(([u]) => {
      const q = new URL(String(u), "http://relay.test").searchParams;
      return `${q.get("from")} ${q.get("to")}`;
    }).sort()).toEqual([`${FROM} ${TO}`, `${PRIOR_FROM} ${PRIOR_TO}`].sort()));
    const cells = () => within(within(table).getAllByRole("row")[1]).getAllByRole("cell");
    // Sales $1,500 against $1,000: up 50%; PPV sales $1,200 against $1,500: down 20%; Tips with nothing before: "-";
    // the rest flat.
    await waitFor(() => expect(cells()[2].textContent).toBe("$1,500↑50.00%"));
    expect(within(cells()[2]).getByRole("img", { name: "rising" })).toBeTruthy();
    expect(cells()[3].textContent).toBe("$1,200↓20.00%");
    expect(within(cells()[3]).getByRole("img", { name: "falling" })).toBeTruthy();
    expect(cells()[4].textContent).toBe("$300-");
    expect(cells()[5].textContent).toBe("$9000.00%");
    // Fans chatted 80 against 40 rises in the good colour; Response time 3m 05s against 6m 10s falls, and with a
    // lower wait the better, the fall takes the good colour.
    const cell = (label: string) => {
      const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
      return cells()[heads.findIndex((h) => h?.startsWith(label))];
    };
    const change = (label: string) => cell(label).querySelector("div")!;
    expect(change("Fans chatted").textContent).toBe("↑100.00%");
    expect(change("Fans chatted")).toHaveClass("text-ok");
    expect(change("Response time").textContent).toBe("↓50.00%");
    expect(within(cell("Response time")).getByRole("img", { name: "falling" })).toBeTruthy();
    expect(change("Response time")).toHaveClass("text-ok");
    expect(change("PPV sales")).toHaveClass("text-pink");
  });

  it("makes no second read without the window before", async () => {
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} />);
    await screen.findByRole("table");
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("asks for the Chatter role's Employees only when told to, in both windows", async () => {
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} priorFrom={PRIOR_FROM} priorTo={PRIOR_TO} chatterOnly />);
    await screen.findByRole("table");
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(2));
    for (const [u] of fetchMock.mock.calls) {
      expect(new URL(String(u), "http://relay.test").searchParams.get("chatter_only")).toBe("true");
    }
  });

  it("exports the rows on screen in total, each Employee by day and by Creator, only the Employees shown", async () => {
    let blob: Blob | null = null;
    const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn((b: Blob) => { blob = b; return "blob:employee-reports"; });
    URL.revokeObjectURL = vi.fn();
    onTestFinished(() => { URL.createObjectURL = saved.create; URL.revokeObjectURL = saved.revoke; });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    employees = [ROW];
    const base = fetchMock.getMockImplementation() as (url: string) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string) => {
      const u = new URL(String(url), "http://relay.test");
      if (u.pathname === "/admin/stats/chatting-stats" && u.searchParams.get("bucket")) {
        const point = { sales_cents: 0, direct_messages_sent: 0, direct_ppvs_sent: 0, ppvs_unlocked: 0, fans_chatted: 0 };
        return jsonRes({ bucket: u.searchParams.get("bucket"), attribution_fallback: null,
          series: [{ ...point, start: "2026-09-15T00:00" }, { ...point, start: "2026-09-16T00:00" }],
          by_employee: { "1": [{ ...point, sales_cents: 12345, direct_messages_sent: 7 }, point], "9": [point, point] } });
      }
      if (u.pathname === "/admin/stats/per-employee") {
        const acct = { account_id: "11", account_nickname: "Creator Eleven", messages_sent: 400, ppv_conversions: 10,
          revenue_cents: 150000, revenue_by_kind: { ppv: 120000, tip: 30000 } };
        return jsonRes({ attribution_fallback: null, employees: [
          { employee_id: 1, display_name: "Alpha One", per_account: [acct] },
          { employee_id: null, display_name: "Unattributed", per_account: [{ ...acct, account_id: "12" }] }] });
      }
      return base(url);
    });
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} chatterOnly />);
    await screen.findByRole("table");
    const card = screen.getByLabelText("Chatting statistics");
    fireEvent.click(within(card).getByRole("button", { name: "Export" }));
    fireEvent.click(screen.getByLabelText("Display by day"));
    fireEvent.click(screen.getByLabelText("Display by creator"));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(blob).not.toBeNull());
    const lines = (await blob!.text()).split("\n");
    expect(lines[0]).toBe("Total");
    expect(lines[1]).toMatch(/^Employee,Creators,Sales,PPV sales,Tips,.*,Response time \(seconds\),Clocked hours,/);
    expect(lines[2]).toMatch(/^Alpha One,Creator Eleven,1500,1200,300,900,75,450,400,40,10,10,25,80,8,10,150,12000,185,8,150,50,10$/);
    expect(lines.slice(3)).toEqual([
      "", "By day", "Employee,Day,Sales,Direct messages sent,Direct PPVs sent,PPVs unlocked,Fans chatted",
      "Alpha One,2026-09-15,123.45,7,0,0,0", "Alpha One,2026-09-16,0,0,0,0,0",
      "", "By creator", "Employee,Creator,Sales,PPV sales,Tips,Messages sent,PPV conversions",
      "Alpha One,Creator Eleven,1500,1200,300,400,10",
    ]);
    const reads = fetchMock.mock.calls.map(([u]) => new URL(String(u), "http://relay.test"));
    const day = reads.find((u) => u.searchParams.get("bucket"))!;
    expect([day.searchParams.get("bucket"), day.searchParams.get("chatter_only"), day.searchParams.get("from")])
      .toEqual(["day", "true", FROM]);
    const per = reads.find((u) => u.pathname === "/admin/stats/per-employee")!;
    expect([per.searchParams.get("by_account"), per.searchParams.get("chatter_only")]).toEqual(["true", "true"]);
  });

  it("shows Infloww's five cards over the table, computed from the rows, pending sales in Total sales", async () => {
    // Beta Two's only sale is pending (uncleared): the Relay counts it in sales_cents, so Total sales does too.
    employees = [ROW, { ...IDLE, sales_cents: 2500, ppvs_unlocked: 2, direct_ppvs_sent: 10, replies: 10,
      avg_reply_seconds: 65 }];
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} />);
    await screen.findByRole("table");
    const card = (name: string) => screen.getByRole("group", { name });
    expect(within(card("Total sales")).getByText("$1,525")).toBeInTheDocument();
    // Pooled: (10 + 2) unlocked of (40 + 10) sent, not the mean of 25% and 20%.
    expect(within(card("Unlock rate")).getByText("24.00%")).toBeInTheDocument();
    // Weighted by replies: (185 × 30 + 65 × 10) / 40 = 155s.
    expect(within(card("Average response time (all replies)")).getByText("2m 35s")).toBeInTheDocument();
    for (const name of ["Average response time (based on scheduled hours)", "Total number of scheduled hours"]) {
      expect(card(name)).toHaveAttribute("title", "not wired");
      expect(within(card(name)).getByText("-")).toBeInTheDocument();
    }
    expect(screen.getByText(/^Percentage changes are calculated/)).toBeInTheDocument();
    // The legacy antd head: #353535 (bg-bg-elev-2), sentence-case labels.
    expect(within(screen.getByRole("table")).getByText("PPV sales")).toHaveClass("bg-bg-elev-2");
  });

  it("draws the chatter-role checkbox in its title row when the page owns it, and the empty state with no rows", async () => {
    employees = [];
    const onChatterOnly = vi.fn();
    renderWithProviders(<ChattingStatsTable from={FROM} to={TO} onChatterOnly={onChatterOnly} />);
    expect(await screen.findByText("No chatting in this window.")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Total sales" })).getByText("$0")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Unlock rate" })).getByText("-")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Show employees with chatter role only" }));
    expect(onChatterOnly).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("formats response times", () => {
    expect([fmtReplyTime(null), fmtReplyTime(45.4), fmtReplyTime(185), fmtReplyTime(7620)])
      .toEqual(["—", "45s", "3m 05s", "2h 07m"]);
  });
});
