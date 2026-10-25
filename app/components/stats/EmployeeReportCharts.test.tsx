/**
 * EmployeeReportCharts — Employee reports' Overview and Employee performance charts (roadmap W5 5.10), and the shared
 * chart rule they read (`components/stats/chart`).
 *
 * Rendered with the relay mocked at `fetch` by URL: `/admin/stats/chatting-stats` answers the Chatting statistics rows
 * without `bucket`, and the summed and per-Employee series with it, so the requests are assertions about the wire.
 * Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

import {
  EmployeeOverviewCharts, EmployeePerformance, bucketLabel, useEmployeeCharts,
} from "@/components/stats/EmployeeReportCharts";
import { type Gran, granAllowed, rangeDays } from "@/components/stats/chart";
import { type ChattingSeriesResp, type ChattingStatsRow } from "@/hooks/useStats";

const FROM = "2026-09-15T04:00:00.000Z";
const TO = "2026-10-15T03:59:59.999Z";

const row = (id: number, name: string, sales: number) => ({
  employee_id: id, display_name: name, per_account: [], sales_cents: sales,
}) as unknown as ChattingStatsRow;
const ROWS = [row(1, "Alpha One", 5000), row(2, "Beta Two", 90000), row(3, "Gamma Three", 100)];
const fig = (sales: number, sent: number) => ({
  sales_cents: sales, direct_messages_sent: sent, direct_ppvs_sent: 1, ppvs_unlocked: 1, fans_chatted: 2,
});

/** A tab's body over the shared reads, as EmployeeReport mounts it (the page owns the tabs and the bucket). */
function Tab({ tab, bucket = "day" }: { tab: "overview" | "performance"; bucket?: Gran }) {
  const props = useEmployeeCharts(FROM, TO, bucket);
  return tab === "overview" ? <EmployeeOverviewCharts {...props} /> : <EmployeePerformance {...props} />;
}

let fetchMock: ReturnType<typeof vi.fn>;
const seriesCalls = () => fetchMock.mock.calls.map((c) => new URL(String(c[0]), "http://relay.test"))
  .filter((u) => u.searchParams.has("bucket"));

beforeEach(() => {
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://relay.test");
    if (u.pathname !== "/admin/stats/chatting-stats") return jsonRes({ detail: "unmocked" }, 404);
    if (!u.searchParams.has("bucket")) return jsonRes({ employees: ROWS, attribution_fallback: null });
    return jsonRes({
      bucket: u.searchParams.get("bucket"),
      series: [{ start: "2026-09-15T00:00", ...fig(1200, 4) }, { start: "2026-09-16T00:00", ...fig(0, 0) }],
      by_employee: { 1: [fig(200, 1), fig(0, 0)], 2: [fig(1000, 3), fig(0, 0)] },
      attribution_fallback: null,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("chart rule", () => {
  it("allows Infloww's granularities over a range's calendar days, a daylight-saving hour rounded off", () => {
    const allowed = (days: number) => (["hour", "day", "week", "month"] as const).filter((g) => granAllowed(g, days));
    expect(allowed(2)).toEqual(["hour", "day"]);
    expect(allowed(13)).toEqual(["day"]);
    expect(allowed(31)).toEqual(["day", "week"]);
    expect(allowed(62)).toEqual(["week"]);
    expect(allowed(365)).toEqual(["week", "month"]);
    expect(allowed(366)).toEqual(["month"]);
    // October in Berlin: 745 hours from its first midnight to its last day's end.
    expect(rangeDays("2026-09-30T22:00:00.000Z", "2026-10-31T22:59:59.999Z")).toBe(31);
    expect(rangeDays(FROM, TO)).toBe(30);
  });
});

describe("EmployeeReportCharts", () => {
  it("labels points in the report zone's wall time", () => {
    expect(bucketLabel("2026-10-12T00:00", "day")).toBe("Oct 12");
    expect(bucketLabel("2026-10-12T15:00", "hour")).toBe("Oct 12 3 PM");
    expect(bucketLabel("2026-10-01T00:00", "month")).toBe("Oct 2026");
  });

  it("charts every Employee's sales by day, with a hover column per point, and ranks Employees either way", async () => {
    renderWithProviders(<Tab tab="overview" />);
    const ranking = await screen.findByRole("region", { name: "Sales ranking" });
    await waitFor(() => expect(within(ranking).getAllByRole("listitem")).toHaveLength(3));
    const names = () => within(ranking).getAllByRole("listitem").map((li) => li.textContent);
    expect(names()[0]).toContain("Beta Two");
    expect(names()[0]).toMatch(/\$900$/);
    fireEvent.click(within(ranking).getByText(/Descending/));
    await waitFor(() => expect(names()[0]).toContain("Gamma Three"));
    const sales = screen.getByRole("region", { name: "Employee sales" });
    await waitFor(() => expect(within(sales).getAllByTestId("chart-hover")).toHaveLength(2));
    expect(within(sales).getAllByTestId("chart-hover")[0].textContent).toBe("Sep 15\nEmployee sales: $12");
    const [call] = seriesCalls();
    expect([call.searchParams.get("bucket"), call.searchParams.get("from"), call.searchParams.get("to")])
      .toEqual(["day", FROM, TO]);
    expect(screen.getByText("Select up to three employees to compare")).toBeTruthy();
  });

  it("charts the top seller on Employee performance from the same read", async () => {
    renderWithProviders(<Tab tab="performance" />);
    const sales = await screen.findByRole("region", { name: "Sales" });
    await waitFor(() => expect(within(sales).getAllByTestId("chart-hover")[0].textContent)
      .toBe("Sep 15\nEmployee sales: $10"));
    const stats = screen.getByRole("region", { name: "Message statistics" });
    expect(within(stats).getAllByTestId("chart-hover")[0].textContent)
      .toBe("Sep 15\nDirect messages sent: 3\nDirect PPVs sent: 1\nPPVs unlocked: 1\nFans chatted: 2");
    expect(seriesCalls()).toHaveLength(1);
  });

  it("draws empty charts and No data from an answer with no series, rows or by_employee, without throwing", async () => {
    fetchMock.mockImplementation(async () => jsonRes({}));
    renderWithProviders(<Tab tab="overview" />);
    const ranking = await screen.findByRole("region", { name: "Sales ranking" });
    await waitFor(() => expect(seriesCalls()).toHaveLength(1));
    expect(within(ranking).getByText("No data")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Employee sales" })).toBeInTheDocument();
  });

  it("renders both tabs from props alone: a by_employee-less answer charts zeros, a failed read offers Retry", () => {
    const data = { bucket: "day", series: [{ start: "2026-09-15T00:00", ...fig(700, 2) }],
      attribution_fallback: null } as unknown as ChattingSeriesResp;
    renderWithProviders(<EmployeePerformance data={data} error={false} bucket="day" rows={ROWS} />);
    // The top seller is picked: Beta Two, shown as the tag and in the select; it has no points of its own.
    expect(screen.getAllByText("Beta Two").length).toBeGreaterThan(0);
    const sales = screen.getByRole("region", { name: "Sales" });
    expect(within(sales).getAllByTestId("chart-hover")[0].textContent).toBe("Sep 15\nEmployee sales: $0");
    cleanup();
    const onRetry = vi.fn();
    renderWithProviders(<EmployeeOverviewCharts data={null} error bucket="day" rows={[]} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.queryByRole("region", { name: "Employee sales" })).toBeNull();
  });

  it("says so on Employee performance when no Employee chatted in the window", () => {
    renderWithProviders(<EmployeePerformance data={null} error={false} bucket="day" rows={[]} />);
    expect(screen.getByText("No chatting in this window.")).toBeInTheDocument();
  });
});
