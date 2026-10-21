/**
 * StatsReport and its DateRangePicker under the Agency's report time zone
 * (docs/spec/phase-04-apply-stored-settings.md, stories 18, 21 and 22).
 *
 * The report sends its window as UTC instants, the midnights (and 23:59:59.999
 * ends) of its dates in the report time zone, and the presets count days from
 * today in that zone. With none (never saved) it sends the browser's local
 * midnights. No report fires before the Applied settings answer. The presets
 * are Custom and Last 7, 30, 90 and 365 days: no "This week".
 *
 * The browser's timezone is pinned to UTC and the clock to Thu 15 Oct 2026
 * 02:00Z, which is still Wed 14 Oct (22:00) in New York, so each expected
 * instant is a worked example: New York is UTC-4 (EDT) until Sun 1 Nov 2026,
 * then UTC-5 (EST). Rendered with `fetch` mocked by URL.
 *
 * Employee reports also show Infloww's sales settings notice and the Relay's
 * Shift schedule fallback line (stories 46 and 54).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
// An owner session by default; a test may switch to a chatter session (no user).
const OWNER = { user_id: "owner-1", username: "owner" };
const session = vi.hoisted(() => ({
  user: null as { user_id: string; username: string } | null,
  chatter: null as { chatter_id: string; name: string } | null,
}));
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: session.user, loading: false }),
  // Fan reports' creator column reads the roster counts, which take the optional forms.
  useOptionalUser: () => ({ user: session.user, loading: false }),
}));
vi.mock("@/contexts/ChatterContext", () => ({
  useChatter: () => ({ chatter: session.chatter }),
  useOptionalChatter: () => ({ chatter: session.chatter }),
}));

import StatsReport from "@/components/stats/StatsReport";

let reportTz: string | null;
let fallback: string | null;
let creators: Record<string, unknown>[];
let ingestRows: Record<string, unknown>[];
/** The revenue read's answer to one request, by its query parameters. */
let revenueFor: (q: URLSearchParams) => Promise<Response> | Response;
let fetchMock: ReturnType<typeof vi.fn>;

beforeAll(() => {
  vi.stubEnv("TZ", "UTC");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T02:00:00Z"));
  session.user = OWNER;
  session.chatter = null;
  reportTz = null;
  fallback = null;
  creators = [];
  ingestRows = [];
  revenueFor = () => jsonRes({ rows: [] });
  fetchMock = vi.fn(async (url: string) => {
    const path = String(url).split("?")[0];
    if (path === "/admin/stats/per-employee") {
      return jsonRes({ employees: [], attribution_fallback: fallback });
    }
    // The page's notice reads the fallback line from the Chatting statistics read (page-parity ticket 27).
    if (path === "/admin/stats/chatting-stats") {
      return jsonRes({ employees: [], attribution_fallback: fallback, series: [], by_employee: {} });
    }
    if (path === "/admin/settings/applied") {
      return jsonRes({
        preferences: { tz: null, report_tz: reportTz, week_start: "monday" },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all" },
      });
    }
    if (path === "/admin/stats/per-model") {
      return jsonRes({ from: null, to: null, active_subs_source: "unavailable", per_model: creators });
    }
    if (path === "/admin/stats/revenue") return revenueFor(new URL(String(url), "http://relay.test").searchParams);
    if (path === "/admin/stats/referrals") return jsonRes({ rows: [], unavailable: [] });
    if (path === "/admin/ingest/transactions/health") {
      return jsonRes({ overall_status: "green", as_of: "2026-10-15T01:00:00Z", accounts: ingestRows });
    }
    if (/^\/admin\/ingest\/transactions\/[^/]+\/(run|pause|resume)$/.test(path)) return jsonRes({ ok: true });
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

/** Every query to `path` sent so far, as its `from` and `to`: the Employee report's per-employee read by default. */
function ranges(path = "/admin/stats/per-employee"): Record<string, string>[] {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === path)
    .map((u) => ({ from: u.searchParams.get("from") ?? "", to: u.searchParams.get("to") ?? "" }));
}
const lastRange = (path?: string) => ranges(path).at(-1);
/** Creator reports open with "Show net earnings" on (analytics-creator-reports#33, ticket 60); a test written against
 *  the gross figures turns it off first. */
async function showGross() {
  const net = await screen.findByRole("switch", { name: "Show net earnings" });
  if (net.getAttribute("aria-checked") === "true") fireEvent.click(net);
}

/** Opens the range box's popover (page-parity ticket 25): the presets, From / To and the hours live in it. */
function openRange() {
  fireEvent.click(screen.getByRole("button", { name: /^Date range/ }));
}
/** Picks hour `label` ("3 PM") in the range popover's `name` hour select. */
function pickHour(name: string, label: string) {
  fireEvent.click(screen.getByRole("combobox", { name }));
  fireEvent.click(screen.getByRole("option", { name: label }));
}

// Infloww's legacy header (page-parity ticket 25): the title, the report time zone's UTC offset, the icon Refresh.
describe("StatsReport report header", () => {
  it.each([["employee", "Employee reports"], ["fan", "Fan reports"]] as const)(
    "%s: the title, the report time zone's offset and the icon Refresh", async (view, title) => {
      reportTz = "America/New_York";
      renderWithProviders(<StatsReport view={view} />);
      const header = screen.getByRole("heading", { level: 1, name: title }).closest("header")!;
      await waitFor(() => expect(within(header).getByText("UTC-04:00")).toBeInTheDocument());
      const refresh = within(header).getByRole("button", { name: "Refresh" });
      expect(refresh).toHaveAttribute("title", "Re-fetch all stats now");
      expect(refresh).not.toHaveTextContent("Refresh");
    });
});

// The shared range rides on Employee reports: Creator reports' body is the Creator Reports card (ticket 20), which
// reads the same `useReportRange` and has its own report-zone case below.
describe("StatsReport date range", () => {
  it("sends the report time zone's midnights as instants, counted from today there", async () => {
    reportTz = "America/New_York";
    renderWithProviders(<StatsReport view="employee" />);
    // 30d, thirty calendar days through today: Tue 15 Sep 00:00 EDT through Wed 14 Oct 23:59:59.999 EDT.
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-09-15T04:00:00.000Z", to: "2026-10-15T03:59:59.999Z" }));
    // None went out first with the browser's (UTC) days.
    expect(ranges().every((r) => r.from === "2026-09-15T04:00:00.000Z")).toBe(true);
    openRange();
    expect(screen.getByLabelText("To date")).toHaveValue("2026-10-14");

    fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-10-08T04:00:00.000Z", to: "2026-10-15T03:59:59.999Z" }));

    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-10-01T04:00:00.000Z", to: "2026-10-15T03:59:59.999Z" }));

    // Past the daylight-saving change, Mon 2 Nov ends at 23:59:59.999 EST.
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-11-02" } });
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-10-01T04:00:00.000Z", to: "2026-11-03T04:59:59.999Z" }));
  });

  it("starts and ends each day where the report time zone's day does, across a change at midnight", async () => {
    // Santiago (UTC-3 in summer, UTC-4 in winter) changes its clocks at
    // midnight. Sat 4 Apr 2026: at 24:00 UTC-3 (05 Apr 03:00Z) the clock goes
    // back to 23:00 UTC-4, so 23:00-24:00 happens twice and Sun 5 Apr starts at
    // 00:00 UTC-4 = 04:00Z; 4 Apr ends 1 ms before that. Sun 6 Sep 2026: at
    // 00:00 UTC-4 (04:00Z) the clock jumps to 01:00 UTC-3, so 6 Sep's first
    // instant is 04:00Z (03:00Z is still 23:00 on 5 Sep).
    reportTz = "America/Santiago";
    renderWithProviders(<StatsReport view="employee" />);
    // Today there is Wed 14 Oct (02:00Z is 23:00 UTC-3); it ends 1 ms before
    // 15 Oct 00:00 UTC-3 = 03:00Z.
    await waitFor(() => expect(lastRange()?.to).toBe("2026-10-15T02:59:59.999Z"));

    openRange();
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-09-06" } });
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-09-06T04:00:00.000Z", to: "2026-10-15T02:59:59.999Z" }));

    // Wed 1 Apr 00:00 UTC-3 is 03:00Z.
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-04-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-04-04" } });
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-04-01T03:00:00.000Z", to: "2026-04-05T03:59:59.999Z" }));
  });

  it("keeps the browser's local midnights when the Agency has no report time zone", async () => {
    renderWithProviders(<StatsReport view="employee" />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/settings/applied")))
      .toBe(true));
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-09-16T00:00:00.000Z", to: "2026-10-15T23:59:59.999Z" }));
  });

  it("narrows a custom range to the hour in the report time zone, and keeps the hour as the date changes", async () => {
    reportTz = "America/New_York";
    renderWithProviders(<StatsReport view="employee" />);
    await waitFor(() => expect(lastRange()?.from).toBe("2026-09-15T04:00:00.000Z"));
    // Whole days by default: From 12 AM, To 11 PM.
    openRange();
    expect(screen.getByRole("combobox", { name: "From hour" })).toHaveTextContent("12 AM");
    expect(screen.getByRole("combobox", { name: "To hour" })).toHaveTextContent("11 PM");

    // From Thu 1 Oct 3 PM EDT (19:00Z) to Wed 14 Oct 9 AM EDT, which ends 1 ms before 10 AM (14:00Z).
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-10-01" } });
    pickHour("From hour", "3 PM");
    pickHour("To hour", "9 AM");
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-10-01T19:00:00.000Z", to: "2026-10-14T13:59:59.999Z" }));
    expect(screen.getByLabelText("From date")).toHaveValue("2026-10-01");

    // A new To date keeps 9 AM; past the daylight-saving change that is 9 AM EST, ending 1 ms before 15:00Z.
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-11-02" } });
    await waitFor(() => expect(lastRange())
      .toEqual({ from: "2026-10-01T19:00:00.000Z", to: "2026-11-02T14:59:59.999Z" }));
    expect(screen.getByRole("combobox", { name: "To hour" })).toHaveTextContent("9 AM");
  });

  it("offers Custom and the Last 7, 30, 90 and 365 days presets only, with no This week", () => {
    renderWithProviders(<StatsReport view="employee" />);
    openRange();
    const presets = screen.getByRole("group", { name: "Date presets" });
    expect(within(presets).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Custom", "Last 7 days", "Last 30 days", "Last 90 days", "Last 365 days"]);
    expect(screen.queryByRole("button", { name: /this week/i })).toBeNull();
  });
});

describe("StatsReport Employee reports notice", () => {
  const NOTICE = "The sales data is based on your organization's sales settings.";
  const FALLBACK = "Shift schedule needs Time tracking on; credited by Converters.";

  it("names the sales settings and links to them, with no fallback line when none is reported", async () => {
    renderWithProviders(<StatsReport view="employee" />);
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View sales settings" })).toHaveAttribute("href", "/settings/sales");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/stats/per-employee")))
      .toBe(true));
    expect(screen.queryByText(FALLBACK)).toBeNull();
  });

  it("shows the Relay's fallback line while Shift schedule is credited by Converters", async () => {
    fallback = FALLBACK;
    renderWithProviders(<StatsReport view="employee" />);
    expect(await screen.findByText(FALLBACK)).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
  });

  it("asks for the Chatter role's Employees only once the toggle is on", async () => {
    renderWithProviders(<StatsReport view="employee" />);
    const only = (path: string) => fetchMock.mock.calls
      .map(([u]) => new URL(String(u), "http://relay.test"))
      .filter((u) => u.pathname === path)
      .map((u) => u.searchParams.get("chatter_only"));
    await waitFor(() => expect(only("/admin/stats/per-employee").length).toBeGreaterThan(0));
    expect(only("/admin/stats/per-employee").every((v) => v === null)).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show employees with chatter role only" }));
    await waitFor(() => expect(only("/admin/stats/per-employee").at(-1)).toBe("true"));
    await waitFor(() => expect(only("/admin/stats/chatting-stats").at(-1)).toBe("true"));
  });

  it("shows no notice on Creator reports", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    await waitFor(() => expect(lastRange("/admin/stats/per-model")).toBeDefined());
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe("StatsReport Employee reports, Sales needing attribution", () => {
  // Its assign controls send the manual attribute route, which refuses a chatter 403 (ticket 34).
  const sent = () => fetchMock.mock.calls
    .some(([u]) => String(u).startsWith("/admin/ingest/transactions/sales-needing-attribution"));

  it("shows the card to an owner session", async () => {
    renderWithProviders(<StatsReport view="employee" />);
    expect(await screen.findByRole("heading", { name: /Sales needing attribution/ })).toBeInTheDocument();
    await waitFor(() => expect(sent()).toBe(true));
  });

  it("leaves it out of a chatter session's page and never asks for it", async () => {
    session.user = null;
    session.chatter = { chatter_id: "chatter-1", name: "Chatter" };
    renderWithProviders(<StatsReport view="employee" />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/stats/per-employee")))
      .toBe(true));
    expect(screen.queryByRole("heading", { name: /Sales needing attribution/ })).toBeNull();
    expect(sent()).toBe(false);
  });
});

/**
 * Creator reports opens on the Layout capture's frame (docs/infloww-layouts/analytics-creator-reports.md, ticket 20):
 * the page header, the two tabs, the filter bar, then the Creator Reports card as the body. Each expectation cites
 * the capture's Item ID.
 */
describe("StatsReport Creator reports frame", () => {
  const ZERO_KIND = { ppv: 0, post: 0, tip: 0, subscription: 0, rebill: 0, custom: 0 };
  const creator = (id: string, name: string, cents: number) => ({
    account_id: id, display_name: name,
    revenue_by_kind: { ...ZERO_KIND, ppv: cents }, pending_by_kind: ZERO_KIND,
    total_revenue_cents: cents, pending_revenue_cents: 0, pending_clears_by: null,
    messages_sent: 0, ppv_conversions: 0, new_subs_count: 0, active_subs_count: null, ltv_cents: null, arpu_cents: null,
  });
  /** Every revenue read sent so far, as its query parameters. */
  const revenue = () => fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/stats/revenue")
    .map((u) => Object.fromEntries(u.searchParams));
  const posted = () => fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([url]) => String(url));
  const before = (a: HTMLElement, b: HTMLElement) =>
    expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  it("opens on the capture's header, its two tabs with Overview selected, and the filter bar in order", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    // analytics-creator-reports#3: the page title.
    const title = await screen.findByRole("heading", { level: 1, name: "Creator reports" });
    // analytics-creator-reports#10: the header's icon-only Refresh, "Refresh page".
    const refresh = screen.getByRole("button", { name: "Refresh page" });
    before(title, refresh);
    // analytics-creator-reports#14: "Overview" / "Creator performance", in that order; Overview is the default.
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Creator performance"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
    before(refresh, tabs[0]);
    // analytics-creator-reports#18: the filter bar after the tabs.
    const bar = screen.getByRole("group", { name: "Filters" });
    before(tabs[1], bar);
    const controls = [
      within(bar).getByRole("button", { name: "Date range" }), // analytics-creator-reports#21
      within(bar).getByRole("button", { name: "Creator tag" }), // analytics-creator-reports#25
      within(bar).getByRole("button", { name: "Creator" }), // analytics-creator-reports#26
      within(bar).getByRole("switch", { name: "Show net earnings" }), // analytics-creator-reports#30, #33
      within(bar).getByRole("button", { name: "Reset" }), // analytics-creator-reports#37
    ];
    for (let i = 1; i < controls.length; i++) before(controls[i - 1], controls[i]);
    // The body is the Creator Reports card's Overview.
    expect(screen.getByText("Earnings summary")).toBeInTheDocument();
  });

  it("marks Creator tag Not wired, and leaves Show net earnings a working switch, on", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    const bar = await screen.findByRole("group", { name: "Filters" });
    const tag = within(bar).getByRole("button", { name: "Creator tag" }); // analytics-creator-reports#25
    expect(tag).toBeDisabled();
    expect(tag).toHaveAttribute("title", "not wired");
    const net = within(bar).getByRole("switch", { name: "Show net earnings" }); // analytics-creator-reports#33
    expect(net).toBeEnabled();
    expect(net).not.toHaveAttribute("title", "not wired");
    expect(net).toHaveAttribute("aria-checked", "true");
  });

  it("opens Creator performance from ?tab=performance", async () => {
    window.history.replaceState(null, "", "/analytics/creator-reports?tab=performance");
    renderWithProviders(<StatsReport view="creator" />);
    const perf = await screen.findByRole("tab", { name: "Creator performance" });
    await waitFor(() => expect(perf).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
  });

  it("opens Overview from a bogus ?tab=, and a tab click writes ?tab= back", async () => {
    window.history.replaceState(null, "", "/analytics/creator-reports?tab=bogus");
    renderWithProviders(<StatsReport view="creator" />);
    const overview = await screen.findByRole("tab", { name: "Overview" });
    expect(overview).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: "Creator performance" }));
    expect(screen.getByRole("tab", { name: "Creator performance" })).toHaveAttribute("aria-selected", "true");
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("performance");
    expect(window.location.pathname).toBe("/analytics/creator-reports");

    fireEvent.click(overview);
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("overview");
  });

  it("sends the report time zone's midnights on the revenue and per-model reads", async () => {
    reportTz = "America/New_York";
    renderWithProviders(<StatsReport view="creator" />);
    // The page's own default (analytics-creator-reports#21), the last 7 days through today there: Thu 8 Oct 00:00 EDT
    // through Wed 14 Oct 23:59:59.999 EDT (it is still Wed 14 Oct in New York).
    const want = { from: "2026-10-08T04:00:00.000Z", to: "2026-10-15T03:59:59.999Z" };
    await waitFor(() => expect(lastRange("/admin/stats/per-model")).toEqual(want));
    // The window's day and kind reads, and the kind read over the 7 days just before it for each tile's growth
    // (analytics-creator-reports#58): Thu 1 Oct 00:00 EDT through Wed 7 Oct 23:59:59.999 EDT. None went out
    // first with the browser's (UTC) days.
    const prior = { from: "2026-10-01T04:00:00.000Z", to: "2026-10-08T03:59:59.999Z" };
    const sent = () => [...new Set(revenue().map((r) => `${r.group_by} ${r.from} ${r.to}`))].sort();
    await waitFor(() => expect(sent()).toEqual([
      `day ${want.from} ${want.to}`, `kind ${prior.from} ${prior.to}`, `kind ${want.from} ${want.to}`,
    ]));
    expect(ranges("/admin/stats/per-model").every((r) => r.from === want.from)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Date range" }));
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(revenue().some((r) => r.group_by === "day"
      && r.from === "2026-10-01T04:00:00.000Z" && r.to === want.to)).toBe(true));
    await waitFor(() => expect(lastRange("/admin/stats/per-model"))
      .toEqual({ from: "2026-10-01T04:00:00.000Z", to: want.to }));
  });

  it("lists the Agency's Creators, narrows the reads to the picked one, and Reset restores every default", async () => {
    creators = [creator("acct-a", "Creator A", 1200), creator("acct-b", "Creator B", 3400)];
    renderWithProviders(<StatsReport view="creator" />);
    const bar = await screen.findByRole("group", { name: "Filters" });
    // Both Creators in the statistics table.
    expect(await screen.findByText("Creator B")).toBeInTheDocument();
    expect(screen.getByText("Creator A")).toBeInTheDocument();
    const rangeLabel = within(bar).getByRole("button", { name: "Date range" }).textContent;

    // analytics-creator-reports#26: the Creator pop lists the per-model read's Creators; untick Creator B.
    fireEvent.click(within(bar).getByRole("button", { name: "Creator" }));
    expect(screen.getByRole("checkbox", { name: "Creator A" })).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Creator B" }));
    await waitFor(() => expect(revenue().some((r) => r.account_id === "acct-a")).toBe(true));
    expect(revenue().some((r) => r.account_id === "acct-b")).toBe(false);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Creator B")).toBeNull());
    expect(within(bar).getByRole("button", { name: "Creator A" })).toBeInTheDocument();

    // A changed range and bucket too.
    fireEvent.click(within(bar).getByRole("button", { name: "Date range" }));
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-10-01" } });
    fireEvent.keyDown(document, { key: "Escape" });
    const trendTabs = screen.getByRole("group", { name: "Earnings trends granularity" });
    fireEvent.click(within(trendTabs).getByRole("button", { name: "Week" }));
    expect(within(trendTabs).getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
    expect(within(bar).getByRole("button", { name: "Date range" }).textContent).not.toBe(rangeLabel);

    // analytics-creator-reports#37: Reset puts the default range, every Creator and Day back.
    fireEvent.click(within(bar).getByRole("button", { name: "Reset" }));
    expect(within(bar).getByRole("button", { name: "Date range" }).textContent).toBe(rangeLabel);
    expect(within(bar).getByRole("button", { name: "Creator" })).toBeInTheDocument();
    expect(within(trendTabs).getByRole("button", { name: "Day" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("Creator B")).toBeInTheDocument();
  });

  it("keeps Ingest health, All messages… and the per-model KPI cards in the Inflowwww extras overflow", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    const ingest = (id: string, pausedUntil: string | null) => ({
      account_id: id, display_name: id, last_scan_at: "2026-10-15T01:00:00Z", current_status: "ok", last_error: null,
      consecutive_failures: 0, paused_until: pausedUntil, rows_inserted_total: 3, rows_patched_total: 0,
      fully_backfilled: true, minutes_since_scan: 60, tier: "green",
    });
    // acct-b is paused for another hour, so its row offers resume.
    ingestRows = [ingest("acct-a", null), ingest("acct-b", "2026-10-15T03:00:00Z")];
    renderWithProviders(<StatsReport view="creator" />);
    const extras = await screen.findByRole("button", { name: "Inflowwww extras" });
    expect(extras).toHaveAttribute("title", "Inflowwww extras");
    expect(screen.queryByText("Ingest health")).toBeNull();
    expect(screen.queryByRole("link", { name: "All messages…" })).toBeNull();

    fireEvent.click(extras);
    const panel = screen.getByRole("region", { name: "Inflowwww extras" });
    // Each extra is labelled.
    expect(within(panel).getAllByTitle("Inflowwww extra").length).toBeGreaterThanOrEqual(3);
    expect(within(panel).getByRole("link", { name: "All messages…" }))
      .toHaveAttribute("href", "/analytics/message-dashboard?tab=all");
    // No 7d / 30d shortcuts: they were the date range's own Last 7 / 30 days.
    expect(within(panel).queryByRole("button", { name: "7d" })).toBeNull();
    expect(await within(panel).findByRole("heading", { name: "Per-model KPIs" })).toBeInTheDocument();

    // Ingest health's pause, resume and re-sync post as they do today.
    fireEvent.click(await within(panel).findByRole("button", { name: /Ingest health/ }));
    fireEvent.click(await within(panel).findByRole("button", { name: "pause 1h" }));
    await waitFor(() => expect(posted()).toContain("/admin/ingest/transactions/acct-a/pause"));
    fireEvent.click(within(panel).getByRole("button", { name: "resume" }));
    await waitFor(() => expect(posted()).toContain("/admin/ingest/transactions/acct-b/resume"));
    await waitFor(() => expect(within(panel).getAllByRole("button", { name: "re-sync" })[0]).toBeEnabled());
    fireEvent.click(within(panel).getAllByRole("button", { name: "re-sync" })[0]);
    await waitFor(() => expect(posted()).toContain("/admin/ingest/transactions/acct-a/run"));
  });
});

/**
 * The Overview's sections (docs/infloww-layouts/analytics-creator-reports.md, ticket 21): Earnings summary, Earnings
 * trends, the channel row (Earnings by channel beside Earnings breakdown), then Creator statistics, each wired to the
 * revenue read or Not wired. The clock is Thu 15 Oct 2026 02:00Z in a UTC browser with no report time zone, so the
 * default window, the last 7 days through today (#21), is Fri 9 Oct through Thu 15 Oct, and the 7 days before it run
 * Fri 2 Oct through Thu 8 Oct. The figures are gross, so each test turns "Show net earnings" off first. Each
 * expectation cites the capture's Item ID.
 */
describe("StatsReport Creator reports Overview", () => {
  const ZERO_KIND = { ppv: 0, post: 0, tip: 0, subscription: 0, rebill: 0, custom: 0 };
  const creator = (id: string, name: string, cents: number) => ({
    account_id: id, display_name: name,
    revenue_by_kind: { ...ZERO_KIND, ppv: cents }, pending_by_kind: ZERO_KIND,
    total_revenue_cents: cents, pending_revenue_cents: 0, pending_clears_by: null,
    messages_sent: 0, ppv_conversions: 0, new_subs_count: 0, active_subs_count: null, ltv_cents: null, arpu_cents: null,
  });
  const kindRow = (kind: string, cents: number) => ({ day: null, kind, total_cents: cents, count: 1 });
  const dayRow = (day: string, cents: number, byKind?: [string, number][]) => ({
    day, kind: null, total_cents: cents, count: 1,
    ...(byKind ? { by_kind: byKind.map(([kind, c]) => ({ kind, total_cents: c, count: 1 })) } : {}),
  });
  // The selected window's kinds: Subscriptions $150 (subscription + rebill), Messages $80, Posts $20, Tips $30,
  // Streams $10, so Total earnings $290.
  const CURRENT = [kindRow("subscription", 10000), kindRow("rebill", 5000), kindRow("ppv", 8000),
    kindRow("ppv_post", 2000), kindRow("tip", 3000), kindRow("tip_stream", 1000)];
  // The window before: Subscriptions $100, Messages $100, Posts $20, no Tips and no Streams, so Total $220.
  const PRIOR = [kindRow("subscription", 10000), kindRow("ppv", 10000), kindRow("ppv_post", 2000)];
  const PRIOR_FROM = "2026-10-02T00:00:00.000Z";
  /** Answers the kind read by window (the selected one or the one before), the day read with `days`. */
  const mockRevenue = (days: unknown[] = [], hours: unknown[] = []) => {
    revenueFor = (q) => {
      if (q.get("group_by") === "day") return jsonRes({ rows: days });
      if (q.get("group_by") === "hour") return jsonRes({ rows: hours });
      return jsonRes({ rows: q.get("from") === PRIOR_FROM ? PRIOR : CURRENT });
    };
  };
  const before = (a: HTMLElement, b: HTMLElement) =>
    expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const section = (name: string) => screen.getByRole("region", { name });
  /** Every revenue read sent so far, as its query parameters. */
  const revenue = () => fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/stats/revenue")
    .map((u) => Object.fromEntries(u.searchParams));
  /** A summary tile's figures: its value, then its growth. */
  const figures = (tile: HTMLElement) => within(tile).getAllByRole("definition").map((d) => d.textContent);
  /** The bars of a chart, each as `<label>: <amount>`. */
  const bars = (name: string) => within(section(name)).getAllByRole("img").map((b) => b.getAttribute("aria-label"));
  const pickRange = (from: string, to: string) => {
    fireEvent.click(screen.getByRole("button", { name: "Date range" }));
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: from } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: to } });
    fireEvent.keyDown(document, { key: "Escape" });
  };

  it("shows every Overview section by its capture label, in the capture's order", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    mockRevenue();
    renderWithProviders(<StatsReport view="creator" />);
    // analytics-creator-reports#42: Earnings summary, Earnings trends, the channel row, Creator statistics.
    const summary = await screen.findByRole("heading", { name: "Earnings summary" }); // analytics-creator-reports#46
    const trends = screen.getByRole("heading", { name: "Earnings trends" }); // analytics-creator-reports#61
    const channel = screen.getByRole("heading", { name: "Earnings by channel" }); // analytics-creator-reports#70
    const breakdown = screen.getByRole("heading", { name: "Earnings breakdown" }); // analytics-creator-reports#77
    const stats = screen.getByText("Creator statistics"); // analytics-creator-reports#87
    before(summary, trends);
    before(trends, channel);
    before(channel, breakdown);
    before(breakdown, stats);
    // The tooltips, verbatim: analytics-creator-reports#46, #61, #70.
    expect(within(section("Earnings summary"))
      .getByTitle("An overview of total earnings based on your managed creators during this period")).toBeInTheDocument();
    expect(within(section("Earnings trends"))
      .getByTitle("Sales growth and trends of all earnings from your managed creators")).toBeInTheDocument();
    expect(within(section("Earnings by channel"))
      .getByTitle("Track trends and growth of your managed creators’ earning channels")).toBeInTheDocument();
    // analytics-creator-reports#50: the seven tiles, in order (the hidden cell between Messages and Tips is not one).
    expect(within(section("Earnings summary")).getAllByRole("group").map((t) => t.getAttribute("aria-label")))
      .toEqual(["Total earnings", "Subscriptions", "Posts", "Messages", "Tips", "Referrals", "Streams"]);
    // Earnings by channel is one of Infloww's sections: nothing above it is titled Inflowwww extra.
    expect(channel.closest('[title="Inflowwww extra"]')).toBeNull();
  });

  it("fills Earnings summary from the revenue-by-kind read, with each tile's growth against the window before", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    mockRevenue();
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const tile = (name: string) => within(section("Earnings summary")).getByRole("group", { name });
    // analytics-creator-reports#55, #58 to #60: the value, then the change unsigned to two decimals with its arrow;
    // "0.00%" when flat, "-" with nothing before.
    await waitFor(() => expect(figures(tile("Total earnings"))).toEqual(["$290.00", "31.82%"]));
    expect(within(tile("Total earnings")).getByRole("img", { name: "rising" })).toBeInTheDocument();
    expect(figures(tile("Subscriptions"))).toEqual(["$150.00", "50.00%"]);
    expect(figures(tile("Messages"))).toEqual(["$80.00", "20.00%"]);
    expect(within(tile("Messages")).getByRole("img", { name: "falling" })).toBeInTheDocument();
    expect(figures(tile("Posts"))).toEqual(["$20.00", "0.00%"]);
    expect(within(tile("Posts")).queryByRole("img")).toBeNull();
    expect(figures(tile("Tips"))).toEqual(["$30.00", "-"]);
    expect(figures(tile("Streams"))).toEqual(["$10.00", "-"]);
    // Referrals is OnlyFans' own read (`/admin/stats/referrals`), none here.
    expect(figures(tile("Referrals"))[0]).toBe("$0.00");
  });

  it("buckets the rows by Hour, Day, Week and Month under the capture's limits", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    mockRevenue([dayRow("2026-08-20", 7000), dayRow("2026-10-01", 1000), dayRow("2026-10-02", 2000),
      dayRow("2026-10-08", 4000), dayRow("2026-10-14", 500)],
    [dayRow("2026-10-13T09:00", 1500), dayRow("2026-10-14T15:00", 2500)]);
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const tabs = await screen.findByRole("group", { name: "Earnings trends granularity" });
    const tab = (name: string) => within(tabs).getByRole("button", { name });
    // analytics-creator-reports#65: Hour / Day / Week / Month, Day the default.
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Hour", "Day", "Week", "Month"]);
    expect(tab("Day")).toHaveAttribute("aria-pressed", "true");
    // The 7-day default rules Hour out (#28, #29).
    for (const g of [tab("Hour"), within(screen.getByRole("group", { name: "Earnings by channel granularity" }))
      .getByRole("button", { name: "Hour" })]) {
      expect(g).toBeDisabled();
      expect(g).toHaveAttribute("title", "Date range must be 2 days or less for this option");
    }

    // Tue 13 Oct to Wed 14 Oct, 2 days: Hour or Day; Hour reads the local hours, a bar per hour.
    pickRange("2026-10-13", "2026-10-14");
    await waitFor(() => expect(tab("Hour")).toBeEnabled());
    expect(tab("Week")).toBeDisabled();
    fireEvent.click(tab("Hour"));
    await waitFor(() => expect(revenue().some((r) => r.group_by === "hour" && r.by_kind === "true"
      && r.from === "2026-10-13T00:00:00.000Z" && r.to === "2026-10-14T23:59:59.999Z")).toBe(true));
    await waitFor(() => expect(bars("Earnings trends")).toHaveLength(48));
    expect(bars("Earnings trends").slice(0, 2)).toEqual(["Oct 13 12 AM: $0.00", "Oct 13 1 AM: $0.00"]);
    expect(bars("Earnings trends")[9]).toBe("Oct 13 9 AM: $15.00");
    expect(bars("Earnings trends")[39]).toBe("Oct 14 3 PM: $25.00");

    // Thu 1 Oct to Wed 14 Oct, 14 days: Day or Week (analytics-creator-reports#29).
    pickRange("2026-10-01", "2026-10-14");
    await waitFor(() => expect(bars("Earnings trends")).toHaveLength(14));
    expect(bars("Earnings trends").slice(0, 3)).toEqual(["Oct 1: $10.00", "Oct 2: $20.00", "Oct 3: $0.00"]);
    expect(bars("Earnings trends")[13]).toBe("Oct 14: $5.00");
    expect(tab("Month")).toBeDisabled();
    expect(tab("Month")).toHaveAttribute("title", "Date range must be more than 62 days for this option"); // #28
    fireEvent.click(tab("Week"));
    // Weeks run seven days from the range's first day.
    expect(bars("Earnings trends")).toEqual(["Oct 1: $30.00", "Oct 8: $45.00"]);

    // Sat 1 Aug to Wed 14 Oct, 75 days: Week or Month; Day moves off.
    pickRange("2026-08-01", "2026-10-14");
    await waitFor(() => expect(tab("Day")).toBeDisabled());
    expect(tab("Day")).toHaveAttribute("title", "Date range must be 31 days or less for this option"); // #28
    fireEvent.click(tab("Month"));
    expect(bars("Earnings trends")).toEqual(["Aug 26: $70.00", "Sep 26: $0.00", "Oct 26: $75.00"]);

    // Sun 4 Oct to Wed 14 Oct, 11 days: Day only, and the chosen Month moves to Day.
    pickRange("2026-10-04", "2026-10-14");
    await waitFor(() => expect(tab("Day")).toHaveAttribute("aria-pressed", "true"));
    expect(tab("Week")).toBeDisabled();
    expect(tab("Week")).toHaveAttribute("title", "Date range must be between 14 to 365 days for this option"); // #28
  });

  it("draws Earnings by channel and Earnings breakdown from the revenue read and the referrals read", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    mockRevenue([dayRow("2026-10-01", 4000, [["subscription", 1000], ["rebill", 1000], ["tip", 2000]])]);
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    // analytics-creator-reports#74: the day read splits each day by kind.
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => {
      const q = new URL(String(u), "http://relay.test").searchParams;
      return q.get("group_by") === "day" && q.get("by_kind") === "true";
    })).toBe(true));
    const chan = section("Earnings by channel");
    // analytics-creator-reports#74, #75: a line per channel, every channel when none is picked.
    await waitFor(() => expect(within(chan).getAllByRole("img").map((l) => l.getAttribute("aria-label")))
      .toEqual(["Subscription", "Tips", "Posts", "Messages", "Referrals", "Streams"]));
    // analytics-creator-reports#71: the Channels pick, Referrals among them.
    fireEvent.click(within(chan).getByRole("button", { name: "Channels" }));
    expect(screen.getByRole("checkbox", { name: "Referrals" })).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Tips" }));
    expect(within(chan).getAllByRole("img").map((l) => l.getAttribute("aria-label"))).toEqual(["Tips"]);

    // analytics-creator-reports#75, #85: the donut's legend, share and amount of the kind read's channels.
    const legend = within(section("Earnings breakdown")).getByRole("list", { name: "Earnings breakdown legend" });
    await waitFor(() => expect(within(legend).getAllByRole("listitem").map((r) => r.textContent)).toEqual([
      "Subscription51.72%$150.00", "Tips10.34%$30.00", "Posts6.90%$20.00", "Messages27.59%$80.00",
      "Referrals0.00%$0.00", "Streams3.45%$10.00",
    ]));
  });

  it("keeps the Inventory's breakdown rows as an Inflowwww extra: Gross earnings from the read, the net rows behind the switch, the rest Not wired", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    mockRevenue();
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const ledger = await screen.findByRole("region", { name: "Earnings ledger" });
    expect(ledger).toHaveAttribute("title", "Inflowwww extra");
    const row = (name: string) => within(ledger).getByRole("group", { name });
    await waitFor(() => expect(row("Gross earnings")).toHaveTextContent("$290.00"));
    // Refunds sums the per-model read's reversals, none here; no read carries chargebacks.
    expect(row("Refunds")).toHaveTextContent("$0.00");
    for (const name of ["Chargeback ratio"]) {
      const v = within(row(name)).getByRole("button", { name });
      expect(v).toBeDisabled();
      expect(v).toHaveAttribute("title", "not wired");
      expect(row(name)).not.toHaveTextContent("$");
    }
    // Platform fee, VAT collected and Net earnings read OF's own net, fee and VAT only while "Show net earnings" is
    // on; off, no net read is made.
    for (const name of ["Platform fee", "VAT collected", "Net earnings"]) {
      const v = within(row(name)).getByRole("button", { name });
      expect(v).toBeDisabled();
      expect(v).toHaveAttribute("title", "Turn on Show net earnings");
      expect(row(name)).not.toHaveTextContent("$");
    }
  });

  it("shows the empty state with no Creator and no revenue", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    // As the bundle prints them: the tiles' zeros with no growth, and blank charts with no wording.
    const summary = await screen.findByRole("region", { name: "Earnings summary" });
    await waitFor(() => expect(figures(within(summary).getByRole("group", { name: "Total earnings" })))
      .toEqual(["$0.00", "-"]));
    for (const name of ["Subscriptions", "Posts", "Messages", "Tips", "Streams"]) {
      expect(figures(within(summary).getByRole("group", { name }))).toEqual(["$0.00", "-"]);
    }
    expect(screen.queryByText("No creators in this selection")).toBeNull();
    // analytics-creator-reports#84: the donut's empty ring.
    expect(within(section("Earnings breakdown")).getByRole("img", { name: "No earnings" })).toBeInTheDocument();
    // No other section invents a zero.
    for (const name of ["Earnings trends", "Earnings by channel", "Earnings breakdown", "Creator statistics", "Earnings ledger"]) {
      expect(section(name)).not.toHaveTextContent("$0.00");
    }
  });

  it("shows the loading wording, then the error wording when the revenue read fails", async () => {
    creators = [creator("acct-a", "Creator A", 1200)];
    const held: ((r: Response) => void)[] = [];
    revenueFor = () => new Promise<Response>((res) => { held.push(res); });
    renderWithProviders(<StatsReport view="creator" />);
    expect(await within(await screen.findByRole("region", { name: "Earnings trends" }))
      .findByText("Loading earnings trend…")).toBeInTheDocument();
    expect(within(section("Earnings summary")).getByText("Loading…")).toBeInTheDocument();

    revenueFor = () => jsonRes({ detail: "boom" }, 500);
    for (const res of held) res(jsonRes({ detail: "boom" }, 500));
    expect(await within(section("Earnings trends")).findByText("Earnings trend unavailable")).toBeInTheDocument();
    expect(within(section("Earnings by channel")).getByText("Earnings by channel unavailable")).toBeInTheDocument();
    expect(within(section("Earnings summary")).getByText("Earnings data unavailable")).toBeInTheDocument();
    expect(figures(within(section("Earnings summary")).getByRole("group", { name: "Total earnings" })))
      .toEqual(["-", "-"]);
  });
});

/** A per-model row: Creator A sells across the kinds, Creator B sold nothing in the window. */
const ZERO_KINDS = { ppv: 0, post: 0, tip: 0, subscription: 0, rebill: 0, custom: 0 };
const perModelRow = (id: string, name: string, over: Record<string, unknown> = {}) => ({
  account_id: id, display_name: name, revenue_by_kind: ZERO_KINDS, pending_by_kind: ZERO_KINDS,
  total_revenue_cents: 0, total_net_revenue_cents: 0, net_missing_count: 0, pending_revenue_cents: 0,
  pending_clears_by: null, messages_sent: 0, ppv_conversions: 0, new_subs_count: 0, active_subs_count: null,
  ltv_cents: null, arpu_cents: null, ...over,
});
// Subscriptions $100 + rebills $50, Tips $30, Messages $60, Posts $10: Total earnings $250.
const CREATOR_A = perModelRow("acct-a", "Creator A", {
  revenue_by_kind: { ...ZERO_KINDS, subscription: 10000, rebill: 5000, tip: 3000, ppv: 6000, post: 1000 },
  total_revenue_cents: 25000, new_subs_count: 4, messages_sent: 120, active_subs_count: 50,
  ppvs_sent: 30, fans_chatted: 40, avg_reply_seconds: 185,
});
const CREATOR_B = perModelRow("acct-b", "Creator B");
/** A rendered table's rows, each as its cells' text. */
const tableRows = (table: HTMLElement) =>
  within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));
/** Lends jsdom object URLs for one test and hands back the last CSV written. */
function captureCsv() {
  const out: { blob: Blob | null } = { blob: null };
  const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  URL.createObjectURL = vi.fn((b: Blob) => { out.blob = b; return "blob:creator-reports"; });
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  onTestFinished(() => { URL.createObjectURL = saved.create; URL.revokeObjectURL = saved.revoke; click.mockRestore(); });
  return out;
}
/** The default columns' CSV header (analytics-creator-reports#111 onward, those shown by default). */
const CSV_HEADER = "Creator,Total subscription earnings,Tips,Message,Engagement earnings ratio,Total earnings,Contribution %," +
  "OF ranking,Fans with renew on,Profile visitors,New subscribers,Subscriber renewals,New subscriber LTV," +
  "New subscriber conversion,Active fans,Number of spenders,Avg spend per spender,Avg earnings per fan,Reply time," +
  "Fans chatted,Messages sent,PPVs sent";
// Dollars and percentages are numbers (W5 5.9), so a spreadsheet sums them.
const ROW_A = "Creator A,150,30,60,60,250,100,,,,4,,22.5,,50,,,,3m 05s,40,120,30";
/** Opens the Export pop-up in `region` and downloads with what is ticked after `pick` (W5 5.9). */
async function exportFrom(region: HTMLElement, pick: string[] = []) {
  fireEvent.click(within(region).getByRole("button", { name: "Export" }));
  const dialog = within(region).getByRole("dialog", { name: "Export" });
  for (const label of pick) fireEvent.click(within(dialog).getByLabelText(label));
  fireEvent.click(within(dialog).getByRole("button", { name: "Download" }));
  await waitFor(() => expect(within(region).queryByRole("dialog")).toBeNull());
}

/**
 * Creator statistics (docs/infloww-layouts/analytics-creator-reports.md #87 to #153, ticket 22): the title and
 * Export, the notice, the four stat cards, Custom metrics and the table of the capture's columns, each read from the
 * per-model read or Not wired. The default window is Thu 8 Oct through Wed 14 Oct, 7 days (168 hours); the figures
 * are gross, so the tests that read them turn "Show net earnings" off first.
 */
describe("StatsReport Creator reports Creator statistics", () => {
  const stats = () => screen.getByRole("region", { name: "Creator statistics" });
  const card = (name: string) => within(stats()).getByRole("group", { name });

  it("shows the capture's title, Export, notice and stat cards, with Refunded Not wired", async () => {
    creators = [CREATOR_A, CREATOR_B];
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    // analytics-creator-reports#87, #88: the title, then Export at its right.
    const title = await screen.findByRole("heading", { level: 2, name: "Creator statistics" });
    const exp = within(stats()).getByRole("button", { name: "Export" });
    expect(title.compareDocumentPosition(exp) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // analytics-creator-reports#94, #98: the notice's two lines and its UTC chip.
    expect(within(stats()).getByText("Percentage change is calculated based on the change in value in the selected time "
      + "frame against the same time frame immediately before it.")).toBeInTheDocument();
    expect(within(stats()).getByText(/is available in UTC\+00:00 only, due to OnlyFans limitations/)).toBeInTheDocument();
    // analytics-creator-reports#101: the four stat cards in order, each with its tooltip verbatim.
    const cards = within(stats()).getByRole("list", { name: "Creator statistics cards" });
    expect(within(cards).getAllByRole("group").map((c) => c.getAttribute("aria-label")))
      .toEqual(["Creators", "Message earnings", "Total earnings", "Refunded"]);
    for (const [name, tip] of [
      ["Creators", "Total number of creators managed by your team"],
      ["Message earnings", "Earnings from creators’ messages during the selected time frame"],
      ["Total earnings", "Earnings from all creators’ subscriptions, tips, posts, messages, streams and referrals during the selected time frame"],
      ["Refunded", "Amount of refunds during the selected time frame"],
    ]) expect(within(card(name)).getByTitle(tip)).toBeInTheDocument();
    await waitFor(() => expect(card("Creators")).toHaveTextContent("2"));
    expect(card("Message earnings")).toHaveTextContent("$60.00");
    expect(card("Total earnings")).toHaveTextContent("$250.00");
    // Refunded sums the per-model read's reversals (`refunded_cents`), none here.
    expect(card("Refunded")).toHaveTextContent("$0.00");
    // Ours: Hide $0 creators and Export CSV sit on Creator performance, as the Clone puts them.
    expect(screen.queryByRole("checkbox", { name: "Hide $0 creators" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });

  it("shows the capture's default columns in order, each read from the per-model read or Not wired", async () => {
    creators = [CREATOR_A, CREATOR_B];
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const table = await within(await screen.findByRole("region", { name: "Creator statistics" })).findByRole("table");
    // analytics-creator-reports#111 to #146, those shown by default, in the capture's order; the UTC chip (#98) on
    // the columns that carry it.
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Creator", // #111
      "Total subscription earnings", // #112
      "Tips", // #115
      "Message", // #116
      "Engagement earnings ratio", // #117
      "Total earnings", // #120
      "Contribution %", // #123
      "OF rankingUTC+00:00", // #124
      "Fans with renew onUTC+00:00", // #126
      "Profile visitorsUTC+00:00", // #128
      "New subscribersUTC+00:00", // #131
      "Subscriber renewalsUTC+00:00", // #132
      "New subscriber LTV", // #133
      "New subscriber conversionUTC+00:00", // #134
      "Active fansUTC+00:00", // #135
      "Number of spenders", // #137
      "Avg spend per spender", // #138
      "Avg earnings per fan", // #141
      "Reply time", // #143
      "Fans chatted", // #144
      "Messages sent", // #145
      "PPVs sent", // #146
    ]);
    // analytics-creator-reports#147: "-" for a value the read lacks (here the OF statistics and spender figures the
    // fixture leaves out). Engagement earnings ratio is messages and tips over subscriptions ($90 / $150),
    // Contribution % the Creator's share of the Agency's $250, New subscriber LTV messages and tips over new
    // subscribers ($90 / 4); Reply time the average wait (185 s), with none "-".
    await waitFor(() => expect(tableRows(table)).toEqual([
      ["Creator A", "$150.00", "$30.00", "$60.00", "60.00%", "$250.00", "100.00%", "-", "-", "-", "4", "-", "$22.50",
        "-", "50", "-", "-", "-", "3m 05s", "40", "120", "30"],
      ["Creator B", "$0.00", "$0.00", "$0.00", "-", "$0.00", "0.00%", "-", "-", "-", "0", "-", "-",
        "-", "-", "-", "-", "-", "-", "0", "0", "0"],
    ]));
    // The columns with no relay field carry the house Not wired marker; the rest have none.
    for (const name of ["OF ranking", "Avg earnings per fan"]) {
      const marker = within(table).getByRole("button", { name });
      expect(marker).toBeDisabled();
      expect(marker).toHaveAttribute("title", "not wired");
    }
    for (const name of ["Fans with renew on", "Profile visitors", "Subscriber renewals", "New subscriber conversion",
      "Number of spenders", "Avg spend per spender", "Reply time", "Fans chatted", "PPVs sent"]) {
      expect(within(table).queryByRole("button", { name })).toBeNull();
    }
  });

  it("adds a column from Custom metrics in the capture's order, Refunds from the per-model read", async () => {
    creators = [{ ...CREATOR_A, refunded_cents: 1200 }];
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const table = await within(await screen.findByRole("region", { name: "Creator statistics" })).findByRole("table");
    // analytics-creator-reports#105: "Custom metrics" opens "Creator report metrics".
    fireEvent.click(within(stats()).getByRole("button", { name: "Custom metrics" }));
    const metrics = screen.getByRole("group", { name: "Creator report metrics" });
    fireEvent.click(within(metrics).getByRole("checkbox", { name: "Avg hourly earnings" })); // #121
    fireEvent.click(within(metrics).getByRole("checkbox", { name: "Refunds" })); // #122
    const headers = () => within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers().slice(5, 9)).toEqual(["Total earnings", "Avg hourly earnings", "Refunds", "Contribution %"]);
    // Avg hourly earnings: Total earnings over the window's hours, $250 / 168.
    await waitFor(() => expect(tableRows(table)[0].slice(5, 9)).toEqual(["$250.00", "$1.49", "$12.00", "100.00%"]));
  });

  it("Export writes the columns on screen", async () => {
    const csv = captureCsv();
    creators = [CREATOR_A];
    renderWithProviders(<StatsReport view="creator" />);
    await showGross();
    const table = await within(await screen.findByRole("region", { name: "Creator statistics" })).findByRole("table");
    await waitFor(() => expect(tableRows(table)).toHaveLength(1));
    await exportFrom(stats());
    expect(await csv.blob!.text()).toBe(`${CSV_HEADER}\n${ROW_A}`);
  });

  it("shows the capture's empty states with no Creator: No data, and no stat card invents a zero", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    // analytics-creator-reports#148: "No data" when there are no rows.
    expect(await within(await screen.findByRole("region", { name: "Creator statistics" })).findByText("No data"))
      .toBeInTheDocument();
    for (const name of ["Creators", "Message earnings", "Total earnings"]) {
      expect(card(name)).toHaveTextContent(/-$/);
    }
    expect(stats()).not.toHaveTextContent("$0");
    expect(within(stats()).queryByText("You have reached the end of the page")).toBeNull();
  });

  it("says the end of the page is reached under more than 20 rows", async () => {
    creators = Array.from({ length: 21 }, (_, i) => perModelRow(`acct-${i}`, `Creator ${i}`));
    renderWithProviders(<StatsReport view="creator" />);
    // analytics-creator-reports#151.
    expect(await within(await screen.findByRole("region", { name: "Creator statistics" }))
      .findByText("You have reached the end of the page")).toBeInTheDocument();
    expect(tableRows(within(stats()).getByRole("table"))).toHaveLength(21);
  });
});

/**
 * The Creator performance tab (docs/infloww-layouts/analytics-creator-reports.md #18, #27, #154 to #174, ticket 22):
 * a creator list at the left and, for the one picked, Earnings, Earnings breakdown, Earnings heatmap and Chargebacks.
 * The filter bar swaps Creator tag and Creator for the "Shown by" select.
 */
describe("StatsReport Creator reports Creator performance", () => {
  const kindRow = (kind: string, cents: number) => ({ day: null, kind, total_cents: cents, count: 1 });
  const dayRow = (day: string, cents: number, byKind: [string, number][]) => ({
    day, kind: null, total_cents: cents, count: 1, by_kind: byKind.map(([kind, c]) => ({ kind, total_cents: c, count: 1 })),
  });
  /** Every revenue read sent so far, as its query parameters. */
  const revenue = () => fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/stats/revenue")
    .map((u) => Object.fromEntries(u.searchParams));
  const section = (name: string) => screen.getByRole("region", { name });
  const bars = () => within(section("Earnings")).getAllByRole("img").map((b) => b.getAttribute("aria-label"));
  const openPerformance = async () => {
    window.history.replaceState(null, "", "/analytics/creator-reports?tab=performance");
    renderWithProviders(<StatsReport view="creator" />);
    await waitFor(() => expect(screen.getByRole("tab", { name: "Creator performance" }))
      .toHaveAttribute("aria-selected", "true"));
  };
  const pickRange = (from: string, to: string) => {
    fireEvent.click(screen.getByRole("button", { name: "Date range" }));
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: from } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: to } });
    fireEvent.keyDown(document, { key: "Escape" });
  };
  /** Creator A's reads: the window's kinds (Subscriptions $150, Tips $30, Messages $60, Posts $10) against the window
   *  before the default one (Fri 2 Oct through Thu 8 Oct: Subscriptions $100, Messages $60), and one day split by
   *  kind. The figures are gross, so the tests that read them turn "Show net earnings" off first. */
  const mockCreatorA = () => {
    revenueFor = (q) => {
      if (q.get("account_id") !== "acct-a") return jsonRes({ rows: [] });
      if (q.get("group_by") === "day") {
        return jsonRes({ rows: [dayRow("2026-10-01", 4000, [["subscription", 1500], ["tip", 2000], ["ppv", 500]])] });
      }
      return jsonRes({ rows: q.get("to") === "2026-10-08T23:59:59.999Z" ? [kindRow("subscription", 10000), kindRow("ppv", 6000)]
        : [kindRow("subscription", 10000), kindRow("rebill", 5000), kindRow("tip", 3000), kindRow("ppv", 6000),
          kindRow("ppv_post", 1000)] });
    };
  };

  it("shows the capture's four sections in order, Earnings heatmap and Chargebacks Not wired", async () => {
    creators = [CREATOR_A];
    mockCreatorA();
    await openPerformance();
    // analytics-creator-reports#154, #155: Earnings, Earnings breakdown, Earnings heatmap, Chargebacks.
    const heads = ["Earnings", "Earnings breakdown", "Earnings heatmap", "Chargebacks"]
      .map((name) => screen.getByRole("heading", { name }));
    for (let i = 1; i < heads.length; i++) {
      expect(heads[i - 1].compareDocumentPosition(heads[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // The tooltips, verbatim (#155, #164, #168).
    for (const [name, tip] of [
      ["Earnings", "Sales growth and trends of all Creator earnings"],
      ["Earnings breakdown", "A detailed view of Creator earnings broken down by channel"],
      ["Earnings heatmap", "Heat intensity shows the number of PPVs bought per time slot, identifying top performing days and hours within a week"],
      ["Chargebacks", "Growth and trends of earnings refunded from the Creator"],
    ]) expect(within(section(name)).getByTitle(tip)).toBeInTheDocument();
    // #168 reads the weekday x hour read, #170 the reversed sales.
    for (const name of ["Earnings heatmap", "Chargebacks"]) {
      expect(await within(section(name)).findByRole("img", { name: `${name} chart` })).toBeInTheDocument();
    }
    // The Overview's sections and the per-model KPI cards are not on this tab.
    expect(screen.queryByRole("heading", { name: "Earnings summary" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Per-model KPIs" })).toBeNull();
  });

  it("swaps Creator tag and Creator for the Shown by select, Day the default", async () => {
    creators = [CREATOR_A];
    mockCreatorA();
    await openPerformance();
    const bar = screen.getByRole("group", { name: "Filters" });
    // analytics-creator-reports#18: date range, Shown by, Show net earnings, Reset.
    expect(within(bar).queryByRole("button", { name: "Creator tag" })).toBeNull();
    expect(within(bar).queryByRole("button", { name: "Creator" })).toBeNull();
    const shownBy = within(bar).getByRole("combobox", { name: "Shown by" });
    const order = [within(bar).getByRole("button", { name: "Date range" }), shownBy,
      within(bar).getByRole("switch", { name: "Show net earnings" }), within(bar).getByRole("button", { name: "Reset" })];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // analytics-creator-reports#27: the four choices, Day the default.
    const options = within(shownBy).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((o) => o.textContent)).toEqual(["Shown by hour", "Shown by day", "Shown by week", "Shown by month"]);
    expect(shownBy).toHaveValue("day");
    expect(options[0]).toBeDisabled();
    expect(options[0]).toHaveAttribute("title", "Date range must be 2 days or less for this option");
    // #28, #29: the 7-day default allows Day only.
    expect(options[2]).toBeDisabled();
    expect(options[2]).toHaveAttribute("title", "Date range must be between 14 to 365 days for this option");
    expect(options[3]).toBeDisabled();
    expect(options[3]).toHaveAttribute("title", "Date range must be more than 62 days for this option");
  });

  it("lists the Creators, reads the picked one's revenue, and draws its Earnings by channel and bucket", async () => {
    creators = [CREATOR_A, perModelRow("acct-c", "Creator C", { total_revenue_cents: 500 })];
    mockCreatorA();
    await openPerformance();
    await showGross();
    // analytics-creator-reports#156: the creator list; the first is picked.
    const list = screen.getByRole("list", { name: "Creators" });
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Creator A", "Creator C"]);
    expect(within(list).getByRole("button", { name: "Creator A" })).toHaveAttribute("aria-pressed", "true");
    pickRange("2026-10-01", "2026-10-03");
    await waitFor(() => expect(revenue().some((r) => r.account_id === "acct-a" && r.group_by === "day"
      && r.by_kind === "true" && r.from === "2026-10-01T00:00:00.000Z")).toBe(true));
    // analytics-creator-reports#161: All by default, a bar per bucket.
    const channels = screen.getByRole("group", { name: "Earnings channel" });
    expect(within(channels).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["All", "Subscriptions", "Tips", "Posts", "Messages", "Referrals", "Streams"]);
    expect(within(channels).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(bars()).toEqual(["Oct 1: $40.00", "Oct 2: $0.00", "Oct 3: $0.00"]));
    fireEvent.click(within(channels).getByRole("button", { name: "Tips" }));
    expect(bars()).toEqual(["Oct 1: $20.00", "Oct 2: $0.00", "Oct 3: $0.00"]);
    // Referrals is OnlyFans' own read for the picked Creator.
    expect(within(channels).getByRole("button", { name: "Referrals" })).toBeEnabled();

    // analytics-creator-reports#27: Shown by week rolls the days into weeks from the range's first day.
    pickRange("2026-10-01", "2026-10-14");
    fireEvent.change(screen.getByRole("combobox", { name: "Shown by" }), { target: { value: "week" } });
    await waitFor(() => expect(bars()).toEqual(["Oct 1: $20.00", "Oct 8: $0.00"]));

    // Picking Creator C reads its revenue.
    fireEvent.click(within(list).getByRole("button", { name: "Creator C" }));
    expect(within(list).getByRole("button", { name: "Creator C" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(revenue().some((r) => r.account_id === "acct-c")).toBe(true));
  });

  it("breaks the picked Creator's earnings down by channel, each with its growth on the window before", async () => {
    creators = [CREATOR_A];
    mockCreatorA();
    await openPerformance();
    await showGross();
    // analytics-creator-reports#164 to #167: the donut's legend and the growth column.
    const legend = within(section("Earnings breakdown")).getByRole("list", { name: "Earnings breakdown legend" });
    await waitFor(() => expect(within(legend).getAllByRole("listitem").map((r) => r.textContent)).toEqual([
      "Subscription$150.0060.00%", "Tips$30.0012.00%", "Posts$10.004.00%", "Messages$60.0024.00%",
      "Referrals$0.000.00%", "Streams$0.000.00%",
    ]));
    const growth = within(section("Earnings breakdown")).getByRole("list", { name: "Earnings growth" });
    // #166: each row's count, then its change.
    expect(within(growth).getAllByRole("listitem").map((r) => r.textContent)).toEqual([
      "$150.0050.00%Subscription", "$30.00-Tips", "$10.00-Posts", "$60.000.00%Messages", "$0.00-Referrals", "$0.00-Streams",
    ]);
  });

  it("Hide $0 creators hides the zero-revenue Creator, and Export CSV writes the listed rows' visible columns", async () => {
    const csv = captureCsv();
    creators = [CREATOR_A, CREATOR_B];
    mockCreatorA();
    await openPerformance();
    await showGross();
    // Ours (the capture has neither, its Notes), labelled.
    const tools = screen.getByRole("group", { name: "Creator list tools" });
    expect(tools).toHaveAttribute("title", "Inflowwww extra");
    const hide = within(tools).getByRole("checkbox", { name: "Hide $0 creators" });
    expect(hide).toBeChecked();
    const list = screen.getByRole("list", { name: "Creators" });
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Creator A"]);
    expect(within(tools).getByText("1 zero-revenue creator hidden")).toBeInTheDocument();

    fireEvent.click(within(tools).getByRole("button", { name: "Export CSV" }));
    expect(await csv.blob!.text()).toBe(`${CSV_HEADER}\n${ROW_A}`);

    fireEvent.click(hide);
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Creator A", "Creator B"]);
    fireEvent.click(within(tools).getByRole("button", { name: "Export CSV" }));
    expect((await csv.blob!.text()).split("\n")[2]).toBe("Creator B,0,0,0,,0,0,,,,0,,,,,,,,,0,0,0");

    // Net, as the export pop-up writes it: the header first, no note lines; a cell with no net read empty.
    fireEvent.click(screen.getByRole("switch", { name: "Show net earnings" }));
    fireEvent.click(within(tools).getByRole("button", { name: "Export CSV" }));
    expect((await csv.blob!.text()).split("\n")[0]).toBe(CSV_HEADER);
  });

  it("shows each section's empty state with no Creator", async () => {
    await openPerformance();
    // Ours, labelled: the list's wording; Earnings is a blank chart with none.
    expect(await within(screen.getByRole("list", { name: "Creators" })).findByText("No creators in this selection"))
      .toHaveAttribute("title", "Inflowwww extra");
    expect(within(section("Earnings")).queryByText("No creators in this selection")).toBeNull();
    expect(within(section("Earnings breakdown")).getByRole("img", { name: "No earnings" })).toBeInTheDocument();
    for (const name of ["Earnings", "Earnings breakdown", "Earnings heatmap", "Chargebacks"]) {
      expect(section(name)).not.toHaveTextContent("$");
    }
    expect(revenue().some((r) => r.account_id)).toBe(false);
  });

  it("shows the retry box in place of a block whose read failed, and Retry reads again", async () => {
    creators = [CREATOR_A];
    revenueFor = () => jsonRes({ detail: "boom" }, 500);
    await openPerformance();
    // analytics-creator-reports#172: the retry box's text and button.
    const earnings = section("Earnings");
    expect(await within(earnings).findByText("Request failed")).toBeInTheDocument();
    expect(within(section("Earnings breakdown")).getByText("Request failed")).toBeInTheDocument();
    const sent = revenue().filter((r) => r.account_id === "acct-a").length;
    mockCreatorA();
    fireEvent.click(within(earnings).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(revenue().filter((r) => r.account_id === "acct-a").length).toBeGreaterThan(sent));
    await waitFor(() => expect(within(section("Earnings")).queryByText("Request failed")).toBeNull());
  });
});

/**
 * "Show net earnings" (docs/infloww-layouts/analytics-creator-reports.md #30 to #36, ticket 23): on, every money figure
 * with a net read shows OnlyFans' own post-fee net (`include_net=true`, `net_cents`; the per-model read's
 * `total_net_revenue_cents`), and every figure with none shows the Not wired marker; nothing is a ratio of gross.
 */
describe("StatsReport Creator reports Show net earnings", () => {
  type Row = { day: string | null; kind: string | null; total_cents: number; count: number; net_cents: number;
    net_missing_count: number; by_kind?: Row[] };
  const kindRow = (kind: string, gross: number, net: number, missing = 0): Row =>
    ({ day: null, kind, total_cents: gross, count: 1, net_cents: net, net_missing_count: missing });
  // Gross: Subscriptions $150 (subscription + rebill), Messages $80, Posts $20, Tips $30, Streams $10, so $290.
  // OF's net: Subscriptions $120, Messages $64, Posts $16, Tips $24, Streams $8, so $232; two PPV sales have no net yet.
  const KINDS = [kindRow("subscription", 10000, 8000), kindRow("rebill", 5000, 4000), kindRow("ppv", 8000, 6400, 2),
    kindRow("ppv_post", 2000, 1600), kindRow("tip", 3000, 2400), kindRow("tip_stream", 1000, 800)];
  // One day in the default window (Fri 9 Oct through Thu 15 Oct).
  const DAYS: Row[] = [{ day: "2026-10-10", kind: null, total_cents: 29000, count: 6, net_cents: 23200,
    net_missing_count: 2, by_kind: KINDS }];
  /** The relay's answer: `net_cents` and `net_missing_count` only when the read asks for them. */
  const shape = (rows: Row[], net: boolean): unknown[] => rows.map(({ net_cents, net_missing_count, by_kind, ...r }) => ({
    ...r, ...(net ? { net_cents, net_missing_count } : {}), ...(by_kind ? { by_kind: shape(by_kind, net) } : {}),
  }));
  // Creator A's gross is $250 (CREATOR_A); OF's net total for it is $200.
  const NET_A = { ...CREATOR_A, total_net_revenue_cents: 20000, net_missing_count: 1, pending_revenue_cents: 500,
    ltv_cents: 1000, arpu_cents: 300 };
  const revenue = () => fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://relay.test"))
    .filter((u) => u.pathname === "/admin/stats/revenue")
    .map((u) => Object.fromEntries(u.searchParams));
  const section = (name: string) => screen.getByRole("region", { name });
  const tile = (name: string) => within(section("Earnings summary")).getByRole("group", { name });
  const value = (t: HTMLElement) => within(t).getAllByRole("definition")[0].textContent;
  const netSwitch = () => within(screen.getByRole("group", { name: "Filters" })).getByRole("switch", { name: "Show net earnings" });
  const table = () => within(section("Creator statistics")).getByRole("table");
  const MISSING = "2 sales in this period have no net figure from OnlyFans yet, so net earnings leave them out.";
  beforeEach(() => {
    creators = [NET_A];
    revenueFor = (q) => {
      const rows = q.get("group_by") === "day" ? DAYS : KINDS;
      return jsonRes({ rows: shape(rows, q.get("include_net") === "true") });
    };
  });

  it("on at load, sends include_net=true on the day and kind reads and shows OF's own net; off, gross", async () => {
    renderWithProviders(<StatsReport view="creator" />);
    // analytics-creator-reports#33: on by default, so every read asks for the net from the first.
    await waitFor(() => expect(value(tile("Total earnings"))).toBe("$232.00"));
    expect(netSwitch()).toHaveAttribute("aria-checked", "true");
    expect(revenue().every((r) => r.include_net === "true")).toBe(true);
    // The day read keeps `by_kind=true` for Earnings by channel; the kind read serves the tiles and the donut.
    expect(revenue().map((r) => `${r.group_by} ${r.by_kind ?? ""}`)).toEqual(expect.arrayContaining(["day true", "kind "]));
    expect(value(tile("Subscriptions"))).toBe("$120.00");
    expect(value(tile("Messages"))).toBe("$64.00");
    expect(value(tile("Posts"))).toBe("$16.00");
    expect(value(tile("Tips"))).toBe("$24.00");
    expect(value(tile("Streams"))).toBe("$8.00");
    expect(within(section("Earnings trends")).getAllByRole("img").map((b) => b.getAttribute("aria-label")))
      .toContain("Oct 10: $232.00");
    const legend = within(section("Earnings breakdown")).getByRole("list", { name: "Earnings breakdown legend" });
    expect(within(legend).getAllByRole("listitem")[0]).toHaveTextContent("Subscription51.72%$120.00");

    // Creator statistics: Total is the per-model read's net total; the per-kind money columns have no net read.
    await waitFor(() => expect(tableRows(table())[0].slice(0, 7))
      .toEqual(["Creator A", "-", "-", "-", "60.00%", "$200.00", "100.00%"]));
    for (const name of ["Total subscription earnings", "Tips", "Message", "New subscriber LTV"]) {
      const cell = within(table()).getByRole("button", { name: `Creator A ${name}` });
      expect(cell).toBeDisabled();
      expect(cell).toHaveAttribute("title", "not wired");
    }
    expect(within(section("Creator statistics")).getByRole("group", { name: "Total earnings" })).toHaveTextContent("$200.00");
    const message = within(within(section("Creator statistics")).getByRole("group", { name: "Message earnings" }))
      .getByRole("button", { name: "Message earnings" });
    expect(message).toBeDisabled();
    expect(message).toHaveAttribute("title", "not wired");
    // Ours, from Custom metrics: Pending revenue, LTV and ARPU have no net read either.
    fireEvent.click(within(section("Creator statistics")).getByRole("button", { name: "Custom metrics" }));
    const metrics = screen.getByRole("group", { name: "Creator report metrics" });
    for (const name of ["Pending revenue", "LTV", "ARPU"]) {
      fireEvent.click(within(metrics).getByRole("checkbox", { name }));
      const cell = within(table()).getByRole("button", { name: `Creator A ${name}` });
      expect(cell).toBeDisabled();
      expect(cell).toHaveAttribute("title", "not wired");
    }

    fireEvent.click(netSwitch());
    expect(netSwitch()).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(value(tile("Total earnings"))).toBe("$290.00"));
    expect(value(tile("Subscriptions"))).toBe("$150.00");
    expect(tableRows(table())[0].slice(0, 7))
      .toEqual(["Creator A", "$150.00", "$30.00", "$60.00", "60.00%", "$250.00", "100.00%"]);
    expect(tableRows(table())[0].slice(-3)).toEqual(["$5.00", "$10.00", "$3.00"]);
    expect(screen.queryByText(MISSING)).toBeNull();
  });

  it("discloses the sales with no net, shows Net earnings with its VAT line, and exports net with the empty cells", async () => {
    const csv = captureCsv();
    renderWithProviders(<StatsReport view="creator" />);
    expect(await screen.findByText(MISSING)).toBeInTheDocument();

    const ledger = section("Earnings ledger");
    const row = (name: string) => within(ledger).getByRole("group", { name });
    await waitFor(() => expect(row("Net earnings")).toHaveTextContent("$232.00"));
    expect(row("Gross earnings")).toHaveTextContent("$290.00");
    expect(within(ledger).getByText("OnlyFans' net is gross less its fee; VAT is not deducted.")).toBeInTheDocument();

    await waitFor(() => expect(tableRows(table())[0][5]).toBe("$200.00"));
    // The Export pop-up starts at the page's Net, with the Custom metrics pick: the money with no net read is empty.
    await exportFrom(section("Creator statistics"));
    expect(await csv.blob!.text()).toBe(`${CSV_HEADER}\nCreator A,,,,60,200,100,,,,4,,,,50,,,,3m 05s,40,120,30`);
  });

  it("exports all data fields with a net read, and each Creator's net by day from one read per Creator", async () => {
    const csv = captureCsv();
    renderWithProviders(<StatsReport view="creator" />);
    await waitFor(() => expect(tableRows(table())[0][5]).toBe("$200.00"));
    const before = revenue().length;
    await exportFrom(section("Creator statistics"), ["All data fields", "Display by day"]);
    const lines = (await csv.blob!.text()).split("\n");
    // Total: every column with a net read, none Not wired; a blank line, then By day.
    expect(lines[0]).toBe("Total");
    const head = lines[1].split(",");
    expect(head).toEqual(expect.arrayContaining(["Creator", "Total earnings", "Avg hourly earnings", "PPV conversions"]));
    expect(head).not.toContain("Tips");
    expect(head).not.toContain("OF ranking");
    expect(lines.slice(3, 5)).toEqual(["", "By day"]);
    expect(lines[5]).toBe("Creator,Day,Total earnings,Subscription,Tips,Posts,Messages,Streams");
    // The default window's seven days; OF's net by channel on the one with sales.
    expect(lines.slice(6)).toHaveLength(7);
    expect(lines).toContain("Creator A,2026-10-09,0,0,0,0,0,0");
    expect(lines).toContain("Creator A,2026-10-10,232,120,24,16,64,8");
    const byDay = revenue().slice(before);
    expect(byDay).toEqual([expect.objectContaining({ group_by: "day", by_kind: "true", account_id: "acct-a",
      include_net: "true" })]);
  });
});
