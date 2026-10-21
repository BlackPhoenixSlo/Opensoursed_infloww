/**
 * Fan reports (roadmap W5 5.6, page-parity 29): the card reads /admin/stats/fan-report for the page's window, the
 * Creator it is given and the ranking; it renders New fans as a three-line chart, Total fans as Not wired, Traffic
 * earnings and Top fans; Gross / Net switches Top fans' Total spend, and "Download report" is the same query as CSV.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "7", nickname: "Mia" }] }));
vi.mock("@/lib/appliedSettings", () => ({ useWeekStart: () => "monday" }));
// The download's Export CSV Function permission (the Applied settings read) is CsvExportButton's own test.
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));
vi.mock("@/components/stats/chart", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/components/stats/chart")>();
  return { ...mod, LineChart: vi.fn(() => null) };
});

import { LineChart } from "@/components/stats/chart";
import FanReportsCard, { growthSeries } from "@/components/stats/FanReportsCard";
import { relay } from "@/lib/relay";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const FROM = "2026-03-01T00:00:00Z";
const TO = "2026-03-07T23:59:59Z";
const WINDOW = "from=2026-03-01T00%3A00%3A00Z&to=2026-03-07T23%3A59%3A59Z";

// The fan's $6,500 total holds a $5 pending tip: the relay counts uncleared sales (test_fan_reports.py), and the
// card shows the read's total as is.
const BODY = {
  top_fans: [{
    account_id: "7", fan_id: 1, fan_name: "Whale", username: "whale1", total_cents: 650000, net_or_80_cents: 520000,
    tips_cents: 50000, ppv_cents: 500000, subs_cents: 100000, subscribed_at: null,
  }],
  traffic: [
    { account_id: "7", kind: "trial", of_id: 71, name: "Reddit trial", source: "Reddit", fans: 1, total_cents: 1500 },
    { account_id: "7", kind: null, of_id: null, name: null, source: null, fans: 3, total_cents: 900 },
  ],
  growth: [{ day: "2026-03-05", new_fans: 2, renewed_fans: 1 }],
};

function renderCard(accountId: string) {
  const get = relay.get as unknown as Mock;
  get.mockResolvedValue(BODY);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FanReportsCard from={FROM} to={TO} fromDay="2026-03-01" toDay="2026-03-07" accountId={accountId} timeZone="UTC" />
    </QueryClientProvider>,
  );
  return get;
}

const pick = (select: string, option: string) => {
  fireEvent.click(screen.getByRole("combobox", { name: select }));
  fireEvent.click(screen.getByRole("option", { name: option }));
};

describe("FanReportsCard", () => {
  it("reads the Creator from its props and renders the cards in Infloww's order", async () => {
    const get = renderCard("7");
    expect(await screen.findByText("Whale")).toBeTruthy();
    expect(get.mock.calls[0][0]).toBe(`/admin/stats/fan-report?${WINDOW}&account_id=7&sort=total`);
    const cards = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(cards.map((c) => c?.replace(/UTC.*$/, "").trim())).toEqual(
      ["New fans (growth & trends)", "Total fans (growth & trends)", "Traffic earnings", "Top fans"]);
    // One Creator at a time: no Creator column.
    expect(screen.queryByRole("columnheader", { name: "Creator" })).toBeNull();
    expect(screen.getByText("$6,500")).toBeTruthy();
    expect(screen.getByText("Reddit trial")).toBeTruthy();
    expect(screen.getByText("No link")).toBeTruthy();
  });

  it("ranks and downloads with the same query", async () => {
    const get = renderCard("7");
    await screen.findByText("Whale");
    pick("Rank by", "Rank by tips");
    await waitFor(() => expect(get.mock.calls.at(-1)?.[0]).toBe(`/admin/stats/fan-report?${WINDOW}&account_id=7&sort=tips`));

    const hrefs: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      hrefs.push(this.getAttribute("href") ?? "");
    });
    fireEvent.click(screen.getByRole("button", { name: "Download report" }));
    expect(hrefs).toEqual([`/admin/stats/fan-report?${WINDOW}&account_id=7&sort=tips&format=csv`]);
    click.mockRestore();
  });

  it("switches Total spend to net under Net earnings, labels the per-kind columns gross, and Traffic shows no net", async () => {
    renderCard("7");
    await screen.findByText("Whale");
    const heads = () => screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(screen.getByTestId("total-spend").textContent).toBe("$6,500");
    // No Net column of its own: Net earnings is the switch.
    expect(heads()).not.toContain("Net");
    expect(heads()).toEqual(expect.arrayContaining(["Tips", "PPV sales", "Subscriptions"]));
    pick("Earnings", "Net earnings");
    expect(screen.getByTestId("total-spend").textContent).toBe("$5,200");
    // The read has no net per kind: those columns stay gross and say so.
    expect(heads()).toEqual(expect.arrayContaining(["Tips (gross)", "PPV sales (gross)", "Subscriptions (gross)"]));
    expect(screen.getByRole("columnheader", { name: "Tips (gross)" })).toHaveAttribute("title",
      expect.stringContaining("Gross"));
    const traffic = within(screen.getByRole("region", { name: "Traffic earnings" }));
    expect(traffic.getAllByText("-")).toHaveLength(2);
    expect(traffic.queryByText("$15")).toBeNull();
  });

  it("draws New fans as All, Renews and New subscribers over the window's days", async () => {
    renderCard("7");
    await screen.findByText("Whale");
    const props = (LineChart as unknown as Mock).mock.calls.at(-1)?.[0];
    expect(props.labels).toEqual(["Mar 1", "Mar 2", "Mar 3", "Mar 4", "Mar 5", "Mar 6", "Mar 7"]);
    expect(props.lines.map((l: { name: string; values: number[] }) => [l.name, l.values])).toEqual([
      ["All", [0, 0, 0, 0, 3, 0, 0]],
      ["Renews", [0, 0, 0, 0, 1, 0, 0]],
      ["New subscribers", [0, 0, 0, 0, 2, 0, 0]],
    ]);
  });

  it("marks Total fans Not wired", async () => {
    renderCard("7");
    await screen.findByText("Whale");
    const card = within(screen.getByRole("region", { name: "Total fans (growth & trends)" }));
    expect(card.getByTestId("total-fans-not-wired").getAttribute("title")).toBe("not wired");
    expect(card.getByText("No data")).toBeTruthy();
  });

  it("shows the error art with Retry when the read fails", async () => {
    const get = relay.get as unknown as Mock;
    get.mockRejectedValue(new Error("boom"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <FanReportsCard from={FROM} to={TO} accountId="7" />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("growthSeries", () => {
  const rows = [
    { day: "2026-03-02", new_fans: 1, renewed_fans: 0 },
    { day: "2026-03-08", new_fans: 2, renewed_fans: 1 },
    { day: "2026-03-09", new_fans: 0, renewed_fans: 4 },
  ];

  it("sums days into weeks from the Agency's week start", () => {
    const monday = growthSeries(rows, "week", "monday", "2026-03-01", "2026-03-10");
    expect(monday.labels).toEqual(["Feb 23", "Mar 2", "Mar 9"]);
    expect(monday.lines[0].values).toEqual([0, 4, 4]);
    const sunday = growthSeries(rows, "week", "sunday", "2026-03-01", "2026-03-10");
    expect(sunday.labels).toEqual(["Mar 1", "Mar 8"]);
    expect(sunday.lines[0].values).toEqual([1, 7]);
  });

  it("sums days into months, and spans the rows when the window has no days", () => {
    const month = growthSeries(rows, "month", "monday");
    expect(month.labels).toEqual(["Mar 2026"]);
    expect(month.lines.map((l) => l.values)).toEqual([[8], [5], [3]]);
  });
});
