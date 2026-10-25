/**
 * "Earnings by channel" is one of Infloww's Overview sections (Inventory §3.4, C[H276166]; the Layout capture
 * docs/infloww-layouts/analytics-creator-reports.md, analytics-creator-reports#42 and #70), so the Creator Reports
 * card renders it among them, after Earnings trends and beside Earnings breakdown, with no "Inflowwww extra"
 * title (docs/spec/infloww-parity-round-2/phase-03-creator-reports.md, ticket 21).
 *
 * Ticket 60: the page lies flush (#41) while the Dashboard's embed keeps its card; it opens with "Show net earnings"
 * on (#33) and on its own range, the last 7 days through today, with the bundle's presets and bounds (#21 to #24);
 * with no Creator the tiles print "$0", and the loading and error texts are labelled; the statistics header stays
 * in view (#108); Creator performance has its own bar and donut geometry (#161, #164, #167), its growth rows the count
 * (#166); and the letter tracking is applied (#53, #165). The clock is pinned to Fri 16 Oct 2026 12:00Z, the report
 * time zone UTC. jsdom does no layout, so the geometry is read off the SVG and the styles.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});
// The card's window reads the Applied settings for the Creator in scope.
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

import CompetitorReports from "@/components/home/CompetitorReports";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;
const APPLIED = { preferences: { tz: null, report_tz: "UTC", week_start: "monday" } };
const CREATOR = {
  account_id: "acc-1", display_name: "Creator A",
  revenue_by_kind: { subscription: 15000, tip: 10000 }, pending_by_kind: {},
  total_revenue_cents: 25000, total_net_revenue_cents: 20000, net_missing_count: 0,
  pending_revenue_cents: 0, pending_clears_by: null, messages_sent: 0, ppv_conversions: 0,
  new_subs_count: 0, active_subs_count: 0, ltv_cents: null, arpu_cents: null,
};
const KIND_ROWS = [
  { kind: "subscription", total_cents: 15000, count: 1, net_cents: 12000 },
  { kind: "tip", total_cents: 10000, count: 1, net_cents: 8000 },
];

/** The Relay by path: the Applied settings, the per-model read's `creators`, and the revenue reads' rows. */
function relayWith(creators: unknown[], kindRows = KIND_ROWS, applied: unknown = APPLIED) {
  get.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/settings/applied")) return applied;
    if (path.startsWith("/admin/stats/per-model")) return { per_model: creators };
    if (path.startsWith("/admin/stats/revenue")) {
      const q = new URLSearchParams(path.split("?")[1]);
      if (q.get("group_by") === "day") return { rows: [{ day: "2026-10-12", total_cents: 25000, count: 2, net_cents: 20000, by_kind: kindRows }] };
      if (q.get("group_by") === "hour_of_week") return { rows: [{ weekday: 1, hour: 21, total_cents: 25000, count: 2, net_cents: 20000 }] };
      return { rows: kindRows };
    }
    return { rows: [] };
  });
}
function renderCard(ui = <CompetitorReports />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
/** The revenue reads sent so far, as their query parameters. */
const revenueReads = () => get.mock.calls
  .map(([p]) => String(p))
  .filter((p) => p.startsWith("/admin/stats/revenue"))
  .map((p) => new URLSearchParams(p.split("?")[1]));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-16T12:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  get.mockReset();
  window.history.replaceState(null, "", "/");
});

describe("CompetitorReports labels", () => {
  it("renders Earnings by channel among the Overview sections, with no Inflowwww extra title", async () => {
    get.mockImplementation(async (path: string) =>
      path.startsWith("/admin/settings/applied")
        ? { preferences: { tz: null, report_tz: null, week_start: "monday" } }
        : { rows: [], per_model: [] });
    renderCard();
    // analytics-creator-reports#61, #70, #77: Earnings trends, then the channel row's two cards.
    const channel = await screen.findByRole("heading", { name: "Earnings by channel" });
    const trends = screen.getByRole("heading", { name: "Earnings trends" });
    const breakdown = screen.getByRole("heading", { name: "Earnings breakdown" });
    expect(trends.compareDocumentPosition(channel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(channel.compareDocumentPosition(breakdown) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(channel.closest('[title="Inflowwww extra"]')).toBeNull();
  });
});

describe("CompetitorReports frame (#41)", () => {
  it("lies flush on the page with frame=page, and keeps the bordered card for the Dashboard's embed", async () => {
    relayWith([]);
    const page = renderCard(<CompetitorReports frame="page" />);
    await screen.findByRole("heading", { name: "Creator reports" });
    const pageRoot = page.container.firstElementChild as HTMLElement;
    expect(pageRoot.className).not.toMatch(/\bborder\b/);
    expect(pageRoot.style.background).toBe("");
    cleanup();

    const card = renderCard();
    await screen.findByRole("heading", { name: "Creator reports" });
    const cardRoot = card.container.firstElementChild as HTMLElement;
    expect(cardRoot.className).toMatch(/\bborder\b/);
    expect(cardRoot.style.background).toBe("var(--color-panel)");
    // overflow-hidden would trap the statistics header's sticky top; the card clips instead.
    expect(cardRoot.className).not.toMatch(/overflow-hidden/);
  });
});

describe("CompetitorReports defaults (#21 to #24, #33)", () => {
  it("opens with Show net earnings on, the net read asked for", async () => {
    relayWith([CREATOR]);
    renderCard();
    expect(await screen.findByRole("switch", { name: "Show net earnings" })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(revenueReads().length).toBeGreaterThan(0));
    expect(revenueReads().every((q) => q.get("include_net") === "true")).toBe(true);
  });

  it("opens on the last 7 days through today, in the report time zone", async () => {
    relayWith([CREATOR]);
    renderCard();
    const pill = await screen.findByRole("button", { name: "Date range" });
    expect(pill).toHaveTextContent("Oct 10, 2026");
    expect(pill).toHaveTextContent("Oct 16, 2026");
    await waitFor(() => expect(revenueReads().length).toBeGreaterThan(0));
    const window = revenueReads().find((q) => q.get("group_by") === "day")!;
    expect(window.get("from")).toBe("2026-10-10T00:00:00.000Z");
    expect(window.get("to")).toBe("2026-10-16T23:59:59.999Z");
  });

  it("offers the bundle's presets and bounds, and Reset goes back to the last 7 days", async () => {
    relayWith([CREATOR]);
    renderCard();
    const pill = await screen.findByRole("button", { name: "Date range" });
    fireEvent.click(pill);
    const presets = screen.getByRole("group", { name: "Date presets" });
    expect(within(presets).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Custom", "Last 7 days", "Last 30 days", "Last 90 days", "Last 365 days", "2026",
      "October", "September", "August", "July", "June", "May",
    ]);
    // #22: a year back to two days ahead.
    expect(screen.getByLabelText("From date")).toHaveAttribute("min", "2025-10-16");
    expect(screen.getByLabelText("To date")).toHaveAttribute("max", "2026-10-18");

    const pick = (name: string) => fireEvent.click(within(presets).getByRole("button", { name }));
    pick("Last 30 days");
    expect(pill).toHaveTextContent("Sep 17, 2026");
    expect(pill).toHaveTextContent("Oct 16, 2026");
    pick("2026");
    expect(pill).toHaveTextContent("Jan 1, 2026");
    expect(pill).toHaveTextContent("Oct 16, 2026");
    // This month runs through today; an earlier month is whole.
    pick("October");
    expect(pill).toHaveTextContent("Oct 1, 2026");
    expect(pill).toHaveTextContent("Oct 16, 2026");
    pick("September");
    expect(pill).toHaveTextContent("Sep 1, 2026");
    expect(pill).toHaveTextContent("Sep 30, 2026");
    expect(within(presets).getByRole("button", { name: "September" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(pill).toHaveTextContent("Oct 10, 2026");
    expect(pill).toHaveTextContent("Oct 16, 2026");
  });
});

describe("CompetitorReports states (#58)", () => {
  it("prints $0 tiles with no Creator, and no Clone wording", async () => {
    get.mockImplementation(async (path: string) =>
      path.startsWith("/admin/settings/applied") ? APPLIED : { rows: [], per_model: [] });
    renderCard();
    // The tile comes before the Creator statistics card of the same name.
    const [total] = await screen.findAllByRole("group", { name: "Total earnings" });
    await waitFor(() => expect(total).toHaveTextContent("$0"));
    expect(screen.getByRole("group", { name: "Subscriptions" })).toHaveTextContent("$0");
    expect(screen.queryByText("No creators in this selection")).toBeNull();
  });

  it("labels the loading and error texts as ours", async () => {
    get.mockImplementation((path: string) =>
      path.startsWith("/admin/settings/applied") ? Promise.resolve(APPLIED) : new Promise(() => {}));
    renderCard();
    const loading = await screen.findByText("Loading…", { selector: "p" });
    expect(loading).toHaveAttribute("title", "Inflowwww extra");
    expect(screen.getByText("Loading earnings trend…").closest('[title="Inflowwww extra"]')).not.toBeNull();
    cleanup();

    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/admin/settings/applied")) return APPLIED;
      throw new Error("boom");
    });
    renderCard();
    const error = await screen.findByText("Earnings data unavailable");
    expect(error).toHaveAttribute("title", "Inflowwww extra");
    expect(screen.getByText("Earnings trend unavailable").closest('[title="Inflowwww extra"]')).not.toBeNull();
    expect(screen.getByText("Creator statistics unavailable").closest('[title="Inflowwww extra"]')).not.toBeNull();
  });
});

describe("CompetitorReports statistics header (#108)", () => {
  it("keeps the header in view under the top bar, scrolled with the body", async () => {
    relayWith([CREATOR]);
    renderCard();
    const table = await screen.findByRole("table");
    await within(table).findByRole("cell", { name: "Creator A" });
    const [head, body] = within(table).getAllByRole("rowgroup");
    expect(within(head).getByRole("columnheader", { name: "Creator" })).toBeInTheDocument();
    expect(head.style.position).toBe("sticky");
    expect(head.style.top).toBe("var(--shell-top, 3.5rem)");
    body.scrollLeft = 120;
    fireEvent.scroll(body);
    expect(head.scrollLeft).toBe(120);
  });
});

describe("CompetitorReports Creator performance (#161, #164, #166, #167)", () => {
  async function openPerformance() {
    relayWith([CREATOR]);
    renderCard();
    fireEvent.click(await screen.findByRole("tab", { name: "Creator performance" }));
  }

  it("draws 25px bars with their labels 16px off the axis", async () => {
    await openPerformance();
    const section = screen.getByRole("heading", { name: "Earnings", level: 3 }).closest("section")!;
    const bar = await within(section).findByRole("img", { name: /^Oct 12: / });
    const d = bar.getAttribute("d")!;
    const left = Number(/^M([\d.]+),/.exec(d)![1]);
    const right = Number(/Q([\d.]+),[\d.]+ [\d.]+,[\d.]+V[\d.]+Z$/.exec(d)![1]);
    expect(right - left).toBeCloseTo(25, 5);
    // The plot's bottom is 30px above the 336px chart's: the label's 11px baseline sits 16px under it.
    const label = within(section).getByText("Oct 12", { selector: "text" });
    expect(Number(label.getAttribute("y"))).toBe(306 + 16 + 11);
  });

  it("draws the donut 180px high, 35px down, its ring 69% to 80%, in the bundle's slice colours", async () => {
    await openPerformance();
    const section = screen.getByRole("heading", { name: "Earnings breakdown", level: 3 }).closest("section")!;
    const donut = await within(section).findByRole("img", { name: "Earnings breakdown chart" });
    expect(donut.getAttribute("class")).toContain("h-[180px]");
    expect(donut.getAttribute("class")).toContain("mt-[35px]");
    const rings = donut.querySelectorAll("circle");
    // The ring's middle at 74.5% of 90px, 11% of it wide.
    expect(Number(rings[0].getAttribute("r"))).toBeCloseTo(67.05, 5);
    expect(Number(rings[0].getAttribute("stroke-width"))).toBeCloseTo(9.9, 5);
    expect([...rings].slice(1).map((c) => c.getAttribute("stroke"))).toEqual(["#3467ff", "#2ad4ac"]);
    const legend = within(section).getByRole("list", { name: "Earnings breakdown legend" });
    const title = within(legend).getByText("Subscription");
    expect(title.className).toContain("tracking-[0.15px]");
    expect((title.firstElementChild as HTMLElement).style.background).toBe("rgb(52, 103, 255)");
  });

  it("shows each growth row's count before its change", async () => {
    await openPerformance();
    const growth = await screen.findByRole("list", { name: "Earnings growth" });
    const subs = await within(growth).findByText("Subscription");
    // Net is on: the count is the channel's net.
    await waitFor(() => expect(subs.closest("li")).toHaveTextContent(/^\$120(?!\.)/));
  });
});

describe("CompetitorReports tracking (#53)", () => {
  it("applies Text$5's letter spacing to the tiles and the stat cards", async () => {
    relayWith([CREATOR]);
    renderCard();
    const [total] = await screen.findAllByRole("group", { name: "Total earnings" });
    await waitFor(() => expect(total).toHaveTextContent("$200"));
    const [title, value, growth] = [...total.children] as HTMLElement[];
    expect(title.className).toContain("tracking-[0.034px]");
    expect(value.className).toContain("tracking-[0.128px]");
    expect(growth.className).toContain("tracking-[0.034px]");
    const [sTitle, sValue] = [...screen.getByRole("group", { name: "Subscriptions" }).children] as HTMLElement[];
    expect(sTitle.className).toContain("tracking-[0.032px]");
    expect(sValue.className).toContain("tracking-[0.098px]");
    const cards = screen.getByRole("list", { name: "Creator statistics cards" });
    const [label, card] = [...within(cards).getByRole("group", { name: "Creators" }).children] as HTMLElement[];
    expect(label.className).toContain("tracking-[0.032px]");
    expect(card.className).toContain("tracking-[0.128px]");
  });
});

describe("CompetitorReports growth against a window with unknown days", () => {
  it("shows - when the window before holds days the relay has no figure for, else the change", async () => {
    relayWith([CREATOR]);
    const base = get.getMockImplementation()!;
    const half = KIND_ROWS.map((r) => ({ ...r, total_cents: r.total_cents / 2, net_cents: r.net_cents / 2 }));
    let missing = 3;
    // The window before Oct 10-16 is Oct 3-9: half the earnings, and (first) 3 Creator-days with no figure.
    get.mockImplementation(async (path: string) => {
      const q = new URLSearchParams(path.split("?")[1] ?? "");
      if (path.startsWith("/admin/stats/revenue") && q.get("group_by") === "kind" && q.get("from")?.startsWith("2026-10-03"))
        return { rows: half, history_missing_days: missing };
      return base(path);
    });
    const growthOfTotal = async () => {
      const [total] = await screen.findAllByRole("group", { name: "Total earnings" });
      await waitFor(() => expect(total).toHaveTextContent("$200"));
      return total.children[2] as HTMLElement;
    };
    renderCard();
    await waitFor(async () => expect(await growthOfTotal()).toHaveTextContent(/^-$/));
    cleanup();
    missing = 0;
    renderCard();
    await waitFor(async () => expect(await growthOfTotal()).toHaveTextContent("100.00%"));
  });
});

describe("CompetitorReports referrals (#50, #75)", () => {
  it("adds OnlyFans' referrals as a channel, into Total, and names the Creators it could not read", async () => {
    relayWith([CREATOR]);
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (path: string) => path.startsWith("/admin/stats/referrals")
      ? { rows: [{ account_id: "acc-1", total_cents: 1000, by_day: [{ day: "2026-10-12", cents: 1000 }] }], unavailable: ["acc-2"] }
      : base(path));
    renderCard();
    const summary = await screen.findByRole("heading", { name: "Earnings summary" });
    const card = summary.closest("section")!;
    // Net is on: $200.00 of sales and $10.00 of referrals, the same in net.
    await waitFor(() => expect(within(card).getByRole("group", { name: "Total earnings" })).toHaveTextContent("$210"));
    expect(within(card).getByRole("group", { name: "Referrals" })).toHaveTextContent("$10");
    expect(screen.getByText(/Referrals from OnlyFans are unavailable for 1 creator/)).toHaveAttribute("title", "Inflowwww extra");
    const read = get.mock.calls.map(([p]) => String(p)).find((p) => p.startsWith("/admin/stats/referrals"))!;
    expect(Object.fromEntries(new URLSearchParams(read.split("?")[1]))).toEqual({ from: "2026-10-10", to: "2026-10-16" });
  });
});

describe("CompetitorReports reversals (#101, #122, #170)", () => {
  it("sums the per-model read's refunds into Refunded and the ledger, net while net is on", async () => {
    relayWith([{ ...CREATOR, refunded_cents: 5000, refunded_net_cents: 4000 }]);
    renderCard();
    const cards = await screen.findByRole("list", { name: "Creator statistics cards" });
    await waitFor(() => expect(within(cards).getByRole("group", { name: "Refunded" })).toHaveTextContent("$40"));
    // The ledger's Refunds row is gross, beside Gross earnings.
    await waitFor(() => expect(screen.getByRole("group", { name: "Refunds" })).toHaveTextContent("$50"));
  });

  it("charts the picked Creator's reversed days under Chargebacks", async () => {
    relayWith([CREATOR]);
    renderCard();
    fireEvent.click(await screen.findByRole("tab", { name: "Creator performance" }));
    await waitFor(() => expect(revenueReads().some((q) => q.get("status") === "reversed" && q.get("account_id") === "acc-1")).toBe(true));
    const chart = await screen.findByRole("img", { name: "Chargebacks chart" });
    expect(await within(chart).findByRole("img", { name: /^Oct 12: \$/ })).toBeInTheDocument();
  });

  it("draws the Earnings heatmap from the weekday x hour read, its hottest slot #3467FF", async () => {
    relayWith([CREATOR]);
    renderCard();
    fireEvent.click(await screen.findByRole("tab", { name: "Creator performance" }));
    const chart = await screen.findByRole("img", { name: "Earnings heatmap chart" });
    // Net is on: the slot holds its net.
    const hot = await within(chart).findByRole("img", { name: "Mon 9 PM: $200" });
    expect(hot.getAttribute("fill")).toBe("rgb(52,103,255)");
    expect(within(chart).getByRole("img", { name: "Sun 12 AM: $0" }).getAttribute("fill")).toBe("rgb(239,244,255)");
    expect(within(chart).getAllByRole("img")).toHaveLength(7 * 24);
  });
});

describe("CompetitorReports page-parity 26 (#7, #148, #172)", () => {
  it("prints the report time zone as its UTC offset, the zone's name on hover", async () => {
    relayWith([CREATOR], KIND_ROWS, { preferences: { tz: null, report_tz: "Europe/Ljubljana", week_start: "monday" } });
    renderCard();
    // 16 Oct 2026 is summer time in Ljubljana.
    const label = await screen.findByText("UTC+02:00");
    expect(label).toHaveAttribute("title", "Europe/Ljubljana");
    expect(screen.queryByText("Europe/Ljubljana")).toBeNull();
  });

  it("shows a failed Creator performance block as Request failed with a Retry that reads again", async () => {
    let fail = true;
    relayWith([CREATOR]);
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (path: string) => {
      if (fail && path.startsWith("/admin/stats/per-model")) throw new Error("boom");
      return base(path);
    });
    renderCard();
    fireEvent.click(await screen.findByRole("tab", { name: "Creator performance" }));
    const failed = await screen.findAllByText("Request failed");
    expect(failed).toHaveLength(4);
    expect(failed[0].parentElement!.querySelector('svg[data-empty-art="error"]')).not.toBeNull();
    const perModelReads = () => get.mock.calls.filter(([p]) => String(p).startsWith("/admin/stats/per-model")).length;
    const before = perModelReads();
    fail = false;
    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() => expect(perModelReads()).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByText("Request failed")).toBeNull());
  });

  it("shows No data under the illustration when the range has no Creator", async () => {
    relayWith([]);
    renderCard();
    const table = await screen.findByRole("table", { name: "Creator statistics" });
    const empty = await within(table).findByText("No data");
    expect(empty.parentElement!.querySelector('svg[data-empty-art="data"]')).not.toBeNull();
  });

  it("counts a pending (uncleared) sale in Total earnings, the reads never narrowed to cleared", async () => {
    // The relay's default status counts cleared and pending sales (service/stats.py); the $30.00 tip here is pending.
    const pendingTip = { kind: "tip", total_cents: 3000, count: 1, net_cents: 2400 };
    relayWith(
      [{ ...CREATOR, revenue_by_kind: { subscription: 15000, tip: 3000 }, pending_revenue_cents: 3000, total_revenue_cents: 18000 }],
      [KIND_ROWS[0], pendingTip],
    );
    renderCard();
    const summary = await screen.findByRole("heading", { name: "Earnings summary" });
    const card = summary.closest("section")!;
    // Net is on: $120.00 cleared plus the pending tip's $24.00.
    await waitFor(() => expect(within(card).getByRole("group", { name: "Total earnings" })).toHaveTextContent("$144"));
    expect(within(card).getByRole("group", { name: "Tips" })).toHaveTextContent("$24");
    expect(revenueReads().filter((q) => q.has("status")).every((q) => q.get("status") === "reversed")).toBe(true);
  });
});
