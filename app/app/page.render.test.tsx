/**
 * Seam 1 of docs/spec/infloww-parity-round-2/phase-01-dashboard.md: the Home
 * page (`/`), rendered with `fetch` mocked by URL, so every assertion is about
 * the rendered text or the requests sent. Ticket 24 starts it with the KPI
 * header (its control catalogue against the Layout capture on disk, the period
 * tabs and `?window=`, Total earnings) and the period-window table cases;
 * ticket 25 adds the Net / Gross switch and the channel tiles; ticket 26 wires
 * Employee sales to the per-employee read. Page-parity ticket 01 moves it onto
 * ticket 00's primitives (the `IfSelect` earnings select, the `IfSegmented`
 * period strip, `EmptyState`) and wires Scheduled hours to the Timesheet.
 *
 * The fixture zone is Pacific/Honolulu: west of UTC (UTC-10:00, the Inventory's
 * example label) and without daylight saving, so every instant below is fixed.
 * Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

// An owner session. The scope (ScopeContext): all Creators unless a case
// picks one.
let scope: { kind: "all" } | { kind: "model"; accountId: string } = { kind: "all" };
vi.mock("@/contexts/ScopeContext", () => ({
  useScope: () => ({ scope, accountId: scope.kind === "model" ? scope.accountId : null }),
}));
// An owner session unless a case signs in a chatter.
let session: { user: { user_id: string; username: string } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", async (orig) => {
  const value = () => ({ user: session.user, loading: false, logout: vi.fn() });
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: value, useOptionalUser: value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = () => ({ chatter: session.chatter, logout: vi.fn() });
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: value, useOptionalChatter: value };
});
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null, clear: vi.fn() }) }));
// The Per-model KPIs cards' insides are their own: a stub here that shows the window it was given.
vi.mock("@/components/stats/PerModelKpiGrid", () => ({
  default: ({ from, to }: { from: string | null; to: string | null }) => (
    <div data-testid="per-model-kpis-stub" data-from={from ?? ""} data-to={to ?? ""} />
  ),
}));

import HomePage from "@/app/page";
import { DASHBOARD_HEADER, type DashboardControl } from "@/components/home/dashboardControls";
import { REFERRALS_UNAVAILABLE, TILE_ICON } from "@/components/home/DashboardHeader";
import { periodWindow, type Period } from "@/lib/dateRange";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

const HONOLULU = "Pacific/Honolulu";
// Wednesday 2026-10-14 02:00 in Honolulu (12:00Z).
const WEDNESDAY = "2026-10-14T12:00:00Z";

/** The revenue-by-kind answer in Gross: a tip and a sale ingest could not classify. */
const BY_KIND = {
  rows: [
    { day: null, kind: "tip", total_cents: 1250, count: 1 },
    { day: null, kind: "unknown", total_cents: 500, count: 1 },
  ],
};
/** The same answer with `include_net=true`: the Relay adds `net_cents` and `net_missing_count` to each row. */
const BY_KIND_NET = {
  rows: [
    { day: null, kind: "tip", total_cents: 1250, count: 1, net_cents: 1000, net_missing_count: 0 },
    { day: null, kind: "unknown", total_cents: 500, count: 1, net_cents: 400, net_missing_count: 0 },
  ],
};
const TOTAL_NET = "$14.00";

let fetchMock: ReturnType<typeof vi.fn>;
/** Each answer to `GET /admin/stats/revenue?group_by=kind`, in turn, told whether the read asked for Net; the last
 *  repeats. */
let revenue: Array<(net: boolean) => Promise<Response>>;
const byBasis = (gross: unknown, net: unknown) => async (isNet: boolean) => jsonRes(isNet ? net : gross);
let applied: () => Promise<Response>;
/** Each answer to `GET /admin/stats/per-employee`, in turn; the last repeats. */
let perEmployee: Array<() => Promise<Response>>;
/** The answer to `GET /admin/shifts/timesheet`. */
let timesheet: () => Promise<Response>;
/** The answer to `GET /admin/stats/referrals`: none unless a case says so, so Total earnings is the sales alone. */
let referrals: () => Promise<Response>;

const appliedRes = () => jsonRes({
  preferences: { tz: null, report_tz: HONOLULU, week_start: "sunday" },
  messaging: { ai_translation: true },
  permissions: { enforced: false, pages: null, scope: "all" },
});

beforeEach(() => {
  scope = { kind: "all" };
  session = { user: { user_id: "owner-1", username: "owner" }, chatter: null };
  timesheet = async () => jsonRes({ rows: [] });
  referrals = async () => jsonRes({ rows: [], unavailable: [] });
  window.history.replaceState(null, "", "/");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(WEDNESDAY));
  revenue = [byBasis(BY_KIND, BY_KIND_NET)];
  applied = async () => appliedRes();
  perEmployee = [async () => jsonRes(PER_EMPLOYEE)];
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://localhost");
    if (u.pathname === "/admin/settings/applied") return applied();
    if (u.pathname === "/admin/stats/revenue" && u.searchParams.get("group_by") === "kind") {
      return (revenue.length > 1 ? revenue.shift()! : revenue[0])(u.searchParams.get("include_net") === "true");
    }
    if (u.pathname === "/admin/stats/revenue") return jsonRes({ rows: [] });
    if (u.pathname === "/admin/stats/referrals") return referrals();
    if (u.pathname === "/admin/stats/per-employee") {
      return (perEmployee.length > 1 ? perEmployee.shift()! : perEmployee[0])();
    }
    if (u.pathname === "/admin/shifts/clocked-in") return jsonRes({ time_tracking_enabled: false, clocked_in: [] });
    if (u.pathname === "/admin/shifts/timesheet") return timesheet();
    if (u.pathname === "/admin/shifts/me") {
      return jsonRes({ accounts: [], occurrences: [], open_clocks: [], reminder: null });
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

/** The header's revenue reads, as URLs, with the init each was sent with. */
const revenueReads = () => fetchMock.mock.calls
  .map(([url, init]) => ({ url: new URL(String(url), "http://localhost"), init: init as RequestInit }))
  .filter(({ url }) => url.pathname === "/admin/stats/revenue" && url.searchParams.get("group_by") === "kind");

/** The header's per-employee reads, as URLs, with the init each was sent with. */
const perEmployeeReads = () => fetchMock.mock.calls
  .map(([url, init]) => ({ url: new URL(String(url), "http://localhost"), init: init as RequestInit }))
  .filter(({ url }) => url.pathname === "/admin/stats/per-employee");

const lastWindow = () => {
  const reads = revenueReads();
  const q = reads[reads.length - 1].url.searchParams;
  return [q.get("from"), q.get("to")];
};

/** A period tab: a radio of the `IfSegmented` strip; `aria-checked` marks the active one. */
const tab = (name: string) => screen.getByRole("radio", { name });
const totalTile = () => document.querySelector<HTMLElement>('[data-control="total"]')!;
/** Total earnings' figure as read ("$17.50"; the sign is its own 25px span), or null while none shows. */
const figure = () => totalTile().querySelector("[data-figure]")?.textContent ?? null;
const shows = (text: string) => waitFor(() => expect(figure()).toBe(text));
const tile = (key: string) => document.querySelector<HTMLElement>(`[data-control="${key}"]`)!;
/** A channel tile's figure as read ("$30.00"), or null while none shows. */
const channelFigure = (key: string) => tile(key).querySelector("[data-figure]")?.textContent ?? null;
/** The wired channel tiles, in catalogue order. */
const CHANNELS = ["subscriptions", "tips", "posts", "messages", "streams"] as const;
const channelFigures = () => Object.fromEntries(CHANNELS.map((k) => [k, channelFigure(k)]));
/** The Net / Gross select: the `IfSelect` combobox inside its catalogue slot. */
const basis = () => within(tile("basis")).getByRole("combobox", { name: "Earnings" });
/** Opens the select and picks an option by its label. */
const pickBasis = (value: "Gross" | "Net") => {
  fireEvent.click(basis());
  fireEvent.click(screen.getByRole("option", { name: `${value} earnings` }));
};
const netNote = () => document.querySelector<HTMLElement>("[data-net-missing]");
/** A card's grid cell. */
const cell = (id: string) => document.querySelector<HTMLElement>(`[data-testid="dashboard-grid"] > [data-card="${id}"]`)!;
const follows = (a: Node, b: Node) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

async function mountHome() {
  renderWithProviders(<HomePage />);
  await waitFor(() => expect(revenueReads().length).toBeGreaterThan(0));
}

describe("the KPI header's control catalogue matches the Layout capture on disk", () => {
  const capture = readFileSync(resolve(__dirname, "../../docs/infloww-layouts/dashboard.md"), "utf-8");
  const rowOf = (id: string) => capture.split("\n").find((l) => l.startsWith(`| ${id} |`));
  const inventory = readFileSync(resolve(__dirname, "../../docs/infloww-screens.md"), "utf-8");
  const dashboard = inventory.slice(inventory.indexOf("### 3.1 Dashboard"), inventory.indexOf("### 3.2 "));

  it.each(DASHBOARD_HEADER.map((c) => [c.key, c] as [string, DashboardControl]))(
    "%s: its Items row carries every label in its Value and every cited source",
    (_key, c) => {
      const row = rowOf(c.id);
      expect(row, `${c.id} is not an Items row`).toBeTruthy();
      const value = row!.split("|")[4];
      for (const label of c.labels) expect(value).toContain(label);
      const sources = row!.split("|")[5].split(";").map((s) => s.trim());
      for (const s of c.sources) expect(sources).toContain(s);
    },
  );

  it.each(DASHBOARD_HEADER.map((c) => [c.key, c] as [string, DashboardControl]))(
    "%s: its Inventory tag is one §3.1 cites",
    (_key, c) => {
      if (c.inventory !== null) expect(dashboard).toContain(c.inventory);
    },
  );
});

describe("the Dashboard opens on the KPI header (ticket 24)", () => {
  it("renders every catalogue control in catalogue order with its verbatim labels, the period tabs over the grid", async () => {
    await mountHome();
    const rendered = Array.from(document.querySelectorAll<HTMLElement>("[data-control]"));
    const toolbar = screen.getByTestId("dashboard-toolbar");
    const tabKeys: string[] = DASHBOARD_HEADER.filter((c) => c.kind === "tab").map((c) => c.key);
    expect(rendered.filter((el) => toolbar.contains(el)).map((el) => el.dataset.control)).toEqual(tabKeys);
    expect(rendered.filter((el) => !toolbar.contains(el)).map((el) => el.dataset.control))
      .toEqual(DASHBOARD_HEADER.map((c) => c.key).filter((k) => !tabKeys.includes(k)));
    for (const c of DASHBOARD_HEADER) {
      const el = rendered.find((r) => r.dataset.control === c.key)!;
      if (c.kind === "switch") {
        fireEvent.click(within(el).getByRole("combobox"));
        expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(c.labels);
        fireEvent.keyDown(within(el).getByRole("combobox"), { key: "Escape" });
      } else if (c.key.endsWith("Tip")) {
        expect(el).toHaveAttribute("title", c.labels[0]);
      } else {
        expect(el.textContent).toContain(c.labels[0]);
      }
    }
    // The header is the first card on the page: My shifts follows it.
    const title = rendered.find((el) => el.dataset.control === "title")!;
    expect(follows(title, cell("my-shifts"))).toBe(true);
  });

  it("every control is wired; Referrals reads OnlyFans' figure over the window's days, and Total adds it", async () => {
    referrals = async () => jsonRes({
      rows: [{ account_id: "a1", total_cents: 250, by_day: [] }, { account_id: "a2", total_cents: 100, by_day: [] }],
      unavailable: [],
    });
    await mountHome();
    expect(DASHBOARD_HEADER.filter((c) => !c.wired)).toEqual([]);
    await shows("$17.50");
    expect(channelFigure("referrals")).toBe("$3.50");
    expect(tile("referrals")).not.toHaveAttribute("title");
    const read = fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
      .find((u) => u.pathname === "/admin/stats/referrals")!;
    // This week in Honolulu, Sunday 11 through Saturday 17, with no account_id: the header is Agency-wide.
    expect(Object.fromEntries(read.searchParams)).toEqual({ from: "2026-10-11", to: "2026-10-17" });
  });

  it("every channel tile draws its icon in the mapped colour on a 10% circle, and Total its OnlyFans mark", async () => {
    await mountHome();
    for (const [k, { rgb }] of Object.entries(TILE_ICON)) {
      const circle = tile(k).querySelector<HTMLElement>(`[data-icon="${k}"]`)!;
      expect(circle, k).toHaveStyle({ background: `rgba(${rgb}, 0.1)` });
      expect(circle.querySelector("svg"), k).toHaveStyle({ color: `rgb(${rgb})` });
    }
    expect(totalTile().querySelector('[data-icon="total"] svg')).not.toBeNull();
  });

  it("the earnings select opens on Enter and lists Gross then Net, Net picked", async () => {
    await mountHome();
    fireEvent.keyDown(basis(), { key: "Enter" });
    const list = screen.getByRole("listbox");
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["Gross earnings", "Net earnings"]);
    expect(within(list).getByRole("option", { name: "Net earnings" })).toHaveAttribute("aria-selected", "true");
  });

  it("names the report time zone the windows use", async () => {
    await mountHome();
    const label = document.querySelector('[data-control="timeZone"]')!;
    await waitFor(() => expect(label.textContent).toBe("UTC-10:00"));
  });

  it("opens on This week and Net earnings, the capture's defaults, and reads Total earnings in Net", async () => {
    await mountHome();
    expect(tab("This week")).toHaveAttribute("aria-checked", "true");
    expect(basis()).toBeEnabled();
    expect(basis()).toHaveTextContent("Net earnings");
    expect(lastWindow()).toEqual(["2026-10-11T10:00:00.000Z", "2026-10-18T09:59:59.999Z"]);
    expect(revenueReads()[0].url.searchParams.get("include_net")).toBe("true");
    await shows(TOTAL_NET);
  });

  it("a tab click writes ?window= without a history entry and reads that period", async () => {
    await mountHome();
    await shows(TOTAL_NET);
    const depth = window.history.length;
    fireEvent.click(tab("Today"));
    expect(window.location.search).toBe("?window=today");
    expect(window.history.length).toBe(depth);
    expect(tab("Today")).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(lastWindow()).toEqual(["2026-10-14T10:00:00.000Z", "2026-10-15T09:59:59.999Z"]));
    fireEvent.click(tab("This month"));
    expect(window.location.search).toBe("?window=month");
    await waitFor(() => expect(lastWindow()).toEqual(["2026-10-01T10:00:00.000Z", "2026-11-01T09:59:59.999Z"]));
    fireEvent.click(tab("Last month"));
    expect(window.location.search).toBe("?window=lastMonth");
    await waitFor(() => expect(lastWindow()).toEqual(["2026-09-01T10:00:00.000Z", "2026-10-01T09:59:59.999Z"]));
  });

  it("a seeded ?window= opens that tab", async () => {
    window.history.replaceState(null, "", "/?window=yesterday");
    await mountHome();
    expect(tab("Yesterday")).toHaveAttribute("aria-checked", "true");
    // The exact query string service/tests/test_dashboard_reads.py calls for Yesterday.
    expect(revenueReads().map(({ url }) => url.search)).toEqual([
      "?from=2026-10-13T10%3A00%3A00.000Z&to=2026-10-14T09%3A59%3A59.999Z&group_by=kind&include_net=true",
    ]);
  });

  it("an unknown ?window= opens the default tab", async () => {
    window.history.replaceState(null, "", "/?window=fortnight");
    await mountHome();
    expect(tab("This week")).toHaveAttribute("aria-checked", "true");
    expect(lastWindow()).toEqual(["2026-10-11T10:00:00.000Z", "2026-10-18T09:59:59.999Z"]);
  });

  it("waits for the Applied settings before it fires a read", async () => {
    let answer!: () => void;
    applied = () => new Promise((done) => { answer = () => done(appliedRes()); });
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/settings/applied")))
      .toBe(true));
    expect(revenueReads()).toHaveLength(0);
    expect(within(totalTile()).getByRole("status", { name: "Loading Total earnings" })).toBeInTheDocument();
    answer();
    await waitFor(() => expect(revenueReads()).toHaveLength(1));
    expect(lastWindow()).toEqual(["2026-10-11T10:00:00.000Z", "2026-10-18T09:59:59.999Z"]);
  });

  it("with one Creator picked in the top bar, the header's reads carry no account_id", async () => {
    scope = { kind: "model", accountId: "1000001" };
    await mountHome();
    fireEvent.click(tab("Yesterday"));
    await waitFor(() => expect(revenueReads()).toHaveLength(2));
    await waitFor(() => expect(perEmployeeReads()).toHaveLength(2));
    for (const { url, init } of [...revenueReads(), ...perEmployeeReads()]) {
      expect(url.searchParams.has("account_id")).toBe(false);
      expect(new Headers(init.headers).has("X-Account-Id")).toBe(false);
    }
  });

  it("Total earnings shimmers in its figure's slot, never the last period's figure, while the next loads", async () => {
    let answer!: () => void;
    revenue = [
      byBasis(BY_KIND, BY_KIND_NET),
      () => new Promise((done) => { answer = () => done(jsonRes({ rows: [BY_KIND_NET.rows[0]] })); }),
    ];
    await mountHome();
    await shows(TOTAL_NET);
    fireEvent.click(tab("Today"));
    await waitFor(() => expect(revenueReads()).toHaveLength(2));
    // The bundle prints "$0.00" while loading (#37); a shimmer bar with no text stands in.
    expect(within(totalTile()).getByRole("status", { name: "Loading Total earnings" })).toHaveTextContent(/^$/);
    expect(figure()).toBeNull();
    answer();
    await shows("$10.00");
  });

  it("a failed read swaps the tiles for the error state with Retry, and Retry reads again", async () => {
    revenue = [async () => jsonRes({ detail: "relay down" }, 500), byBasis(BY_KIND, BY_KIND_NET)];
    await mountHome();
    expect(await screen.findByText(/Couldn't load Total earnings/)).toBeInTheDocument();
    expect(figure()).toBeNull();
    for (const k of CHANNELS) expect(document.querySelector(`[data-control="${k}"]`), k).toBeNull();
    fireEvent.click(within(totalTile()).getByRole("button", { name: "Retry" }));
    await shows(TOTAL_NET);
    expect(revenueReads()).toHaveLength(2);
  });
});

/** Every sales kind the Relay records (`transaction_ingest.KIND_CATALOG`) plus `unknown`, one row each. */
const ALL_KINDS = {
  rows: [
    { day: null, kind: "subscription", total_cents: 2000, count: 1 },
    { day: null, kind: "tip", total_cents: 1250, count: 1 },
    { day: null, kind: "rebill", total_cents: 1000, count: 1 },
    { day: null, kind: "ppv_message", total_cents: 700, count: 1 },
    { day: null, kind: "ppv_stream", total_cents: 600, count: 1 },
    { day: null, kind: "unknown", total_cents: 500, count: 1 },
    { day: null, kind: "ppv_post", total_cents: 400, count: 1 },
    { day: null, kind: "custom", total_cents: 300, count: 1 },
    { day: null, kind: "tip_post", total_cents: 250, count: 1 },
    { day: null, kind: "tip_stream", total_cents: 150, count: 1 },
  ],
};
/** The same sales with their net figures; the stream tip has none yet. */
const ALL_KINDS_NET = {
  rows: [
    { day: null, kind: "subscription", total_cents: 2000, count: 1, net_cents: 1600, net_missing_count: 0 },
    { day: null, kind: "tip", total_cents: 1250, count: 1, net_cents: 1000, net_missing_count: 0 },
    { day: null, kind: "rebill", total_cents: 1000, count: 1, net_cents: 800, net_missing_count: 0 },
    { day: null, kind: "ppv_message", total_cents: 700, count: 1, net_cents: 560, net_missing_count: 0 },
    { day: null, kind: "ppv_stream", total_cents: 600, count: 1, net_cents: 480, net_missing_count: 0 },
    { day: null, kind: "unknown", total_cents: 500, count: 1, net_cents: 400, net_missing_count: 0 },
    { day: null, kind: "ppv_post", total_cents: 400, count: 1, net_cents: 320, net_missing_count: 0 },
    { day: null, kind: "custom", total_cents: 300, count: 1, net_cents: 240, net_missing_count: 0 },
    { day: null, kind: "tip_post", total_cents: 250, count: 1, net_cents: 200, net_missing_count: 0 },
    { day: null, kind: "tip_stream", total_cents: 150, count: 1, net_cents: 0, net_missing_count: 1 },
  ],
};
/** Hand sums of ALL_KINDS by the spec's channel mapping. */
const ALL_GROSS = {
  total: "$71.50",
  channels: { subscriptions: "$30.00", tips: "$15.00", posts: "$4.00", messages: "$10.00", streams: "$7.50" },
};
const ALL_NET = {
  total: "$56.00",
  channels: { subscriptions: "$24.00", tips: "$12.00", posts: "$3.20", messages: "$8.00", streams: "$4.80" },
};

describe("the channel tiles and the Net / Gross switch (ticket 25)", () => {
  it("each channel tile sums its sales kinds, in Gross and in Net", async () => {
    revenue = [byBasis(ALL_KINDS, ALL_KINDS_NET)];
    await mountHome();
    await shows(ALL_NET.total);
    expect(channelFigures()).toEqual(ALL_NET.channels);
    pickBasis("Gross");
    await shows(ALL_GROSS.total);
    expect(channelFigures()).toEqual(ALL_GROSS.channels);
  });

  it("an unknown sale counts in Total earnings and in no channel tile", async () => {
    revenue = [byBasis(
      { rows: [
        { day: null, kind: "ppv_message", total_cents: 700, count: 1 },
        { day: null, kind: "unknown", total_cents: 500, count: 1 },
      ] },
      { rows: [
        { day: null, kind: "ppv_message", total_cents: 700, count: 1, net_cents: 560, net_missing_count: 0 },
        { day: null, kind: "unknown", total_cents: 500, count: 1, net_cents: 400, net_missing_count: 0 },
      ] },
    )];
    await mountHome();
    await shows("$9.60");
    expect(channelFigures()).toEqual(
      { subscriptions: "$0.00", tips: "$0.00", posts: "$0.00", messages: "$5.60", streams: "$0.00" },
    );
    pickBasis("Gross");
    await shows("$12.00");
    expect(channelFigures()).toEqual(
      { subscriptions: "$0.00", tips: "$0.00", posts: "$0.00", messages: "$7.00", streams: "$0.00" },
    );
    // Nothing on the card says the tiles add up to Total earnings.
    const card = totalTile().closest("section")!;
    expect(card.textContent).not.toMatch(/\b(sum|add up|of total|breakdown)\b/i);
  });

  it("Referrals is the same in both modes, and a Creator OnlyFans could not answer for is $0.00, titled why", async () => {
    revenue = [byBasis(ALL_KINDS, ALL_KINDS_NET)];
    referrals = async () => jsonRes({ rows: [{ account_id: "a1", total_cents: 500, by_day: [] }], unavailable: ["a2"] });
    await mountHome();
    await shows("$61.00");
    for (const mode of ["Net", "Gross"] as const) {
      pickBasis(mode);
      await shows(mode === "Net" ? "$61.00" : "$76.50");
      expect(tile("referrals")).toHaveAttribute("title", REFERRALS_UNAVAILABLE);
      expect(tile("referrals").textContent).toBe("$5.00Referrals");
    }
  });

  it("Net sends include_net=true, Gross sends the ticket-24 read unchanged, and switching back restores each", async () => {
    revenue = [byBasis(ALL_KINDS, ALL_KINDS_NET)];
    await mountHome();
    await shows(ALL_NET.total);
    pickBasis("Gross");
    expect(basis()).toHaveTextContent("Gross earnings");
    await shows(ALL_GROSS.total);
    expect(revenueReads().map(({ url }) => url.search)).toEqual([
      "?from=2026-10-11T10%3A00%3A00.000Z&to=2026-10-18T09%3A59%3A59.999Z&group_by=kind&include_net=true",
      "?from=2026-10-11T10%3A00%3A00.000Z&to=2026-10-18T09%3A59%3A59.999Z&group_by=kind",
    ]);
    pickBasis("Net");
    await shows(ALL_NET.total);
    expect(channelFigures()).toEqual(ALL_NET.channels);
    pickBasis("Gross");
    await shows(ALL_GROSS.total);
    expect(channelFigures()).toEqual(ALL_GROSS.channels);
  });

  it("Net says how many of the window's sales have no net figure yet; Gross does not", async () => {
    revenue = [byBasis(ALL_KINDS, ALL_KINDS_NET)];
    await mountHome();
    await shows(ALL_NET.total);
    expect(netNote()?.textContent).toBe("1 sale in this period has no net figure from OnlyFans yet, so Net leaves it out.");
    expect(netNote()).toHaveAttribute("title", "Inflowwww extra");
    pickBasis("Gross");
    await shows(ALL_GROSS.total);
    expect(netNote()).toBeNull();
  });

  it("the disclosure counts every row's missing nets, and is absent when none is missing", async () => {
    revenue = [byBasis(BY_KIND, {
      rows: [
        { day: null, kind: "tip", total_cents: 1250, count: 3, net_cents: 300, net_missing_count: 2 },
        { day: null, kind: "unknown", total_cents: 500, count: 1, net_cents: 0, net_missing_count: 1 },
      ],
    })];
    await mountHome();
    await shows("$3.00");
    expect(netNote()?.textContent).toBe("3 sales in this period have no net figure from OnlyFans yet, so Net leaves them out.");
    cleanup();
    revenue = [byBasis(BY_KIND, BY_KIND_NET)];
    await mountHome();
    await shows(TOTAL_NET);
    expect(netNote()).toBeNull();
  });

  it("each channel tile shimmers in its figure's slot while the read is pending, never a figure", async () => {
    let answer!: () => void;
    revenue = [() => new Promise((done) => { answer = () => done(jsonRes(ALL_KINDS_NET)); })];
    await mountHome();
    for (const k of CHANNELS) {
      expect(channelFigure(k), k).toBeNull();
      // The bundle prints "$0.00" while loading (#50); a shimmer bar with no text stands in.
      expect(within(tile(k)).getByRole("status"), k).toHaveTextContent(/^$/);
    }
    answer();
    await shows(ALL_NET.total);
    expect(channelFigures()).toEqual(ALL_NET.channels);
  });

  it("a failed read shows one Retry for the whole tiles row, and Retry brings every channel back", async () => {
    revenue = [async () => jsonRes({ detail: "relay down" }, 500), byBasis(ALL_KINDS, ALL_KINDS_NET)];
    await mountHome();
    await screen.findByText(/Couldn't load Total earnings/);
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    fireEvent.click(within(totalTile()).getByRole("button", { name: "Retry" }));
    await shows(ALL_NET.total);
    expect(channelFigures()).toEqual(ALL_NET.channels);
    expect(revenueReads()).toHaveLength(2);
  });

  it("a window with no sales shows $0.00 in every channel tile and no disclosure", async () => {
    revenue = [byBasis({ rows: [] }, { rows: [] })];
    await mountHome();
    await shows("$0.00");
    expect(channelFigures()).toEqual(
      { subscriptions: "$0.00", tips: "$0.00", posts: "$0.00", messages: "$0.00", streams: "$0.00" },
    );
    expect(netNote()).toBeNull();
  });

  // Ticket 28's recheck: the bundle formats every header figure with two decimals and a thousands separator
  // (`getHomePageMoneyFormat`, `precision:2`, index.9f50f370.js @11227188), so $1,000 and up keep their cents.
  it("figures of $1,000 and up keep two decimals and the thousands separator, as the bundle's", async () => {
    const big = { rows: [
      { day: null, kind: "tip", total_cents: 125000, count: 1 },
      { day: null, kind: "ppv_message", total_cents: 980050, count: 1 },
    ] };
    revenue = [byBasis(big, big)];
    await mountHome();
    pickBasis("Gross");
    await shows("$11,050.50");
    expect(channelFigure("tips")).toBe("$1,250.00");
    expect(channelFigure("messages")).toBe("$9,800.50");
  });

  // Ticket 28: the Route walk's mock answers an unlisted read with `[]`; an answer without a `rows` array must read
  // as a window with no sales, never crash the header (or send the crash report).
  it.each([["[]", []], ["{}", {}]])("an answer of %s with no rows array shows $0.00, not a crash", async (_name, body) => {
    revenue = [byBasis(body, body)];
    await mountHome();
    await shows("$0.00");
    expect(channelFigures()).toEqual(
      { subscriptions: "$0.00", tips: "$0.00", posts: "$0.00", messages: "$0.00", streams: "$0.00" },
    );
    expect(netNote()).toBeNull();
  });

  // Ticket 11's Settings walk: its generic mock answers the Applied settings without `preferences`. The header must
  // fall back to the browser's zone and a Monday week start, never crash.
  it("an Applied settings answer with no preferences still shows the header, not a crash", async () => {
    applied = async () => jsonRes({ messaging: { ai_translation: true } });
    await mountHome();
    await shows(TOTAL_NET);
  });
});

describe("the Dashboard body: the capture's blocks, then one labelled extra (ticket 27)", () => {
  it("puts My shifts on the left across the right column's rows and the clocked-in card beside it (capture #64, #65, #75)", async () => {
    await mountHome();
    const left = cell("my-shifts");
    expect(follows(screen.getByRole("region", { name: "Creator earnings overview" }), left)).toBe(true);
    expect(cell("earnings")).toHaveClass("md:col-span-12");
    expect(within(left).getByRole("region", { name: "My shifts" })).toBeInTheDocument();
    // #67: from `md` the card is `position:absolute` at full height in a cell spanning the right column's three rows,
    // so it takes their height (jsdom does no layout; the shot checks it).
    expect(left).toHaveClass("md:relative", "md:row-span-3", "md:col-span-4", "xl:col-span-3");
    expect(within(left).getByRole("region", { name: "My shifts" })).toHaveClass("md:absolute", "md:inset-0");
    const right = cell("clocked-in");
    expect(right).toHaveClass("md:col-span-8", "xl:col-span-9");
    expect(within(right).getByRole("region", { name: "Current clocked-in employees" })).toBeInTheDocument();
    expect(left.nextElementSibling).toBe(right);
    expect(screen.getByTestId("dashboard-grid")).toHaveClass("md:grid-cols-12", "md:grid-flow-row-dense");
  });

  it("puts Scheduled hours in the right column after the clocked-in card, with the empty state (capture #86, #87, #92)", async () => {
    await mountHome();
    const card = within(cell("scheduled-hours")).getByRole("region", { name: "Scheduled hours" });
    expect(cell("scheduled-hours")).toHaveClass("md:col-span-8", "xl:col-span-9");
    expect(within(card).getByTitle("Number of hours worked based on shift schedule")).toBeInTheDocument();
    expect(await within(card).findByText("No data")).toBeInTheDocument();
    expect(follows(screen.getByRole("region", { name: "Current clocked-in employees" }), card)).toBe(true);
  });

  it("draws one Scheduled hours bar per Employee from the Timesheet's scheduled minutes, over the header's period", async () => {
    timesheet = async () => jsonRes({ rows: [
      { key: "7", display_name: "Fixture Chatter One", scheduled_shifts: 2, shifts_worked: 1, scheduled_minutes: 600,
        worked_minutes: 300, recorded_earnings_cents: 0, open_now: false, employee_id: 7, group_name: null },
      { key: "8", display_name: "Fixture Chatter Two", scheduled_shifts: 1, shifts_worked: 0, scheduled_minutes: 150,
        worked_minutes: 0, recorded_earnings_cents: 0, open_now: false, employee_id: 8, group_name: null },
      { key: "9", display_name: "Fixture Chatter Three", scheduled_shifts: 0, shifts_worked: 0, scheduled_minutes: 0,
        worked_minutes: 0, recorded_earnings_cents: 0, open_now: false, employee_id: 9, group_name: null },
    ] });
    await mountHome();
    const card = screen.getByRole("region", { name: "Scheduled hours" });
    await waitFor(() => expect(card.querySelectorAll("[data-employee]")).toHaveLength(2));
    const bars = Array.from(card.querySelectorAll<HTMLElement>("[data-employee]"), (r) => ({
      name: r.querySelector("[data-name]")?.textContent,
      hours: r.querySelector("[data-hours]")?.textContent,
      width: r.querySelector<HTMLElement>("[data-bar]")?.style.width,
    }));
    expect(bars).toEqual([
      { name: "Fixture Chatter One", hours: "10h", width: "100%" },
      { name: "Fixture Chatter Two", hours: "2.5h", width: "25%" },
    ]);
    const read = fetchMock.mock.calls.map(([u]) => new URL(String(u), "http://localhost"))
      .find((u) => u.pathname === "/admin/shifts/timesheet")!;
    expect(Object.fromEntries(read.searchParams)).toEqual({
      from: "2026-10-11T10:00:00.000Z", to: "2026-10-18T09:59:59.999Z", group: "employee",
    });
  });

  it("has no Scheduled hours card and sends no Timesheet read for a chatter session", async () => {
    session = { user: null, chatter: { username: "chatter_one" } };
    await mountHome();
    await shows(TOTAL_NET);
    expect(screen.queryByRole("region", { name: "Scheduled hours" })).toBeNull();
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/admin/shifts/timesheet"))).toBe(false);
  });

  it("puts only the Per-model KPIs cards under the extras label, last on the page after the shift cards", async () => {
    await mountHome();
    const extras = screen.getAllByRole("region", { name: EXTRA_LABEL });
    expect(extras).toHaveLength(1);
    const [extra] = extras;
    expect(within(extra).getByRole("heading", { name: EXTRA_LABEL })).toHaveAttribute("title", EXTRA_LABEL);
    expect(follows(cell("scheduled-hours"), extra)).toBe(true);
    expect(cell("per-model")).toBe(extra.parentElement);
    expect(cell("per-model").nextElementSibling).toBeNull();
    const kpis = await within(extra).findByTestId("per-model-kpis-stub");
    expect(extra.children).toHaveLength(2);
    expect(extra.nextElementSibling).toBeNull();
    expect(screen.queryByText(/Total revenue · all models/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Creator reports" })).toBeNull();
    expect([kpis.dataset.from, kpis.dataset.to]).toEqual(lastWindow());
  });

  it("reads the Per-model KPIs over the header's period when a tab is picked", async () => {
    await mountHome();
    await screen.findByTestId("per-model-kpis-stub");
    fireEvent.click(tab("This month"));
    const [from, to] = periodWindow("month", HONOLULU, "sunday");
    await waitFor(() => {
      const kpis = screen.getByTestId("per-model-kpis-stub");
      expect([kpis.dataset.from, kpis.dataset.to]).toEqual([from, to]);
    });
  });

  it("shows no developer strip and no status card", async () => {
    await mountHome();
    await screen.findByTestId("per-model-kpis-stub");
    for (const gone of [/Chatting as/, /^switch$/, /\+ Add Model/, /^scope:$/, /Inflowwww is live/, /Relay \/health/]) {
      expect(screen.queryByText(gone), String(gone)).toBeNull();
    }
    expect(screen.queryByRole("link", { name: /Add Model/ })).toBeNull();
  });
});

describe("periodWindow: a capture tab, the report time zone and the week start give [from, to]", () => {
  // Saturday 2026-10-31 19:00 in Honolulu: already Sunday 2026-11-01 in UTC.
  const MONTH_END = "2026-11-01T05:00:00Z";

  it.each<[string, string, Period, "monday" | "sunday", [string, string]]>([
    ["yesterday, west of UTC", WEDNESDAY, "yesterday", "monday",
      ["2026-10-13T10:00:00.000Z", "2026-10-14T09:59:59.999Z"]],
    ["today, west of UTC", WEDNESDAY, "today", "monday",
      ["2026-10-14T10:00:00.000Z", "2026-10-15T09:59:59.999Z"]],
    ["this week from Monday", WEDNESDAY, "week", "monday",
      ["2026-10-12T10:00:00.000Z", "2026-10-19T09:59:59.999Z"]],
    ["this week from Sunday", WEDNESDAY, "week", "sunday",
      ["2026-10-11T10:00:00.000Z", "2026-10-18T09:59:59.999Z"]],
    ["this month", WEDNESDAY, "month", "monday",
      ["2026-10-01T10:00:00.000Z", "2026-11-01T09:59:59.999Z"]],
    ["today on the month's last day, already next month in UTC", MONTH_END, "today", "monday",
      ["2026-10-31T10:00:00.000Z", "2026-11-01T09:59:59.999Z"]],
    ["this month on its last day, already next month in UTC", MONTH_END, "month", "monday",
      ["2026-10-01T10:00:00.000Z", "2026-11-01T09:59:59.999Z"]],
    ["this week from Sunday, ending on the month's last day", MONTH_END, "week", "sunday",
      ["2026-10-25T10:00:00.000Z", "2026-11-01T09:59:59.999Z"]],
    ["yesterday across the month boundary in UTC", MONTH_END, "yesterday", "sunday",
      ["2026-10-30T10:00:00.000Z", "2026-10-31T09:59:59.999Z"]],
    ["last month: the whole calendar month before this one", WEDNESDAY, "lastMonth", "monday",
      ["2026-09-01T10:00:00.000Z", "2026-10-01T09:59:59.999Z"]],
    ["last month on this month's last day, already next month in UTC", MONTH_END, "lastMonth", "monday",
      ["2026-09-01T10:00:00.000Z", "2026-10-01T09:59:59.999Z"]],
    ["last month in January: December of the year before", "2027-01-15T22:00:00Z", "lastMonth", "monday",
      ["2026-12-01T10:00:00.000Z", "2027-01-01T09:59:59.999Z"]],
  ])("%s", (_name, now, period, weekStart, want) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(now));
    expect(periodWindow(period, HONOLULU, weekStart)).toEqual(want);
  });

  it("UTC itself cuts days at UTC midnight", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(WEDNESDAY));
    expect(periodWindow("today", "UTC", "monday")).toEqual(["2026-10-14T00:00:00.000Z", "2026-10-14T23:59:59.999Z"]);
  });
});

/** The per-employee answer, ranked by the Relay (revenue, highest first), the "Unattributed" bucket among them. */
const PER_EMPLOYEE = {
  employees: [
    { employee_id: 7, display_name: "Fixture Chatter One", messages_sent: 9, ppv_conversions: 2, revenue_cents: 4200,
      revenue_by_kind: { ppv: 3000, tip: 1200 } },
    { employee_id: null, display_name: "Unattributed", messages_sent: 0, ppv_conversions: 1, revenue_cents: 1250,
      revenue_by_kind: { ppv: 0, tip: 1250 } },
    { employee_id: 8, display_name: "Fixture Chatter Two", messages_sent: 3, ppv_conversions: 0, revenue_cents: 0,
      revenue_by_kind: { ppv: 0, tip: 0 } },
  ],
  attribution_fallback: null,
};

describe("Employee sales reads the per-employee figures for the selected window (ticket 26)", () => {
  const card = () => tile("employeeSales");
  /** Each ranked row as read: "<name> <figure>". */
  const ranking = () => Array.from(card().querySelectorAll<HTMLElement>("[data-employee]"),
    (r) => `${r.querySelector("[data-name]")?.textContent} ${r.querySelector("[data-figure]")?.textContent}`);
  const ranked = (want: string[]) => waitFor(() => expect(ranking()).toEqual(want));
  const WANT = ["Fixture Chatter One $42.00", "Unattributed $12.50", "Fixture Chatter Two $0.00"];

  it("ranks every Employee, Unattributed included, as the Relay credits them, in the capture's 350px card", async () => {
    await mountHome();
    await ranked(WANT);
    expect(card()).not.toBeDisabled();
    expect(card()).not.toHaveAttribute("title", "not wired");
    expect(card().querySelector("[data-chart]")).toHaveClass("h-[350px]");
    // Each row's tooltip is the capture's first point line (#84), labelled as part of the ranking: no "Growth:" or
    // "From …:" lines.
    expect(card().querySelector("[data-employee]")).toHaveAttribute("title", "Inflowwww extra · Earnings: $42.00");
    // The ranking stands in for the capture's daily line, so it is labelled as ours.
    expect(card().querySelector("[data-chart]")).toHaveAttribute("title", "Inflowwww extra");
  });

  it("reads the period's from/to with no account_id, and a tab click reads the new period", async () => {
    window.history.replaceState(null, "", "/?window=yesterday");
    await mountHome();
    await ranked(WANT);
    // The exact query string service/tests/test_dashboard_reads.py calls for Yesterday.
    expect(perEmployeeReads().map(({ url }) => url.search)).toEqual([
      "?from=2026-10-13T10%3A00%3A00.000Z&to=2026-10-14T09%3A59%3A59.999Z",
    ]);
    fireEvent.click(tab("This month"));
    await waitFor(() => expect(perEmployeeReads()).toHaveLength(2));
    expect(perEmployeeReads()[1].url.search).toBe(
      "?from=2026-10-01T10%3A00%3A00.000Z&to=2026-11-01T09%3A59%3A59.999Z");
    // The switch does not drive Employee sales: the bundle's read takes no basis.
    pickBasis("Gross");
    await shows("$17.50");
    expect(perEmployeeReads()).toHaveLength(2);
  });

  it("spins while a period loads, never the last period's ranking", async () => {
    let answer!: () => void;
    perEmployee = [
      async () => jsonRes(PER_EMPLOYEE),
      () => new Promise((done) => {
        answer = () => done(jsonRes({ ...PER_EMPLOYEE, employees: [PER_EMPLOYEE.employees[1]] }));
      }),
    ];
    await mountHome();
    await ranked(WANT);
    fireEvent.click(tab("Today"));
    await waitFor(() => expect(perEmployeeReads()).toHaveLength(2));
    // The bundle's `Spin` (#85): a spinner in the 350px box, no line.
    expect(within(card()).getByRole("status", { name: "Loading Employee sales" })).toHaveClass("h-[350px]");
    expect(within(card()).getByRole("status")).toHaveTextContent(/^$/);
    expect(ranking()).toEqual([]);
    answer();
    await ranked(["Unattributed $12.50"]);
  });

  it("shows the capture's retry box on an error, and Retry reads again", async () => {
    perEmployee = [async () => jsonRes({ detail: "relay down" }, 500), async () => jsonRes(PER_EMPLOYEE)];
    await mountHome();
    const error = await within(card()).findByText(/Couldn't load Employee sales/);
    expect(error.closest("[data-retry]")).toHaveClass("min-h-[300px]");
    expect(ranking()).toEqual([]);
    fireEvent.click(within(card()).getByRole("button", { name: "Retry" }));
    await ranked(WANT);
    expect(perEmployeeReads()).toHaveLength(2);
  });

  it("sits in the right column, after the clocked-in card and before Scheduled hours (capture #79)", async () => {
    await mountHome();
    expect(within(cell("employee-sales")).getByRole("region", { name: "Employee sales" })).toBe(card());
    expect(cell("employee-sales")).toHaveClass("md:col-span-8", "xl:col-span-9");
    expect(follows(screen.getByRole("region", { name: "Current clocked-in employees" }), card())).toBe(true);
    expect(follows(card(), screen.getByRole("region", { name: "Scheduled hours" }))).toBe(true);
    // The earnings card keeps the capture's 16px to the cards under it (#11): the grid's gap.
    expect(screen.getByTestId("dashboard-grid")).toHaveClass("gap-4");
  });

  it("a window with no Employee sales draws the bundle's bare axes: dashed rules at 0 … 1", async () => {
    perEmployee = [async () => jsonRes({ employees: [], attribution_fallback: null })];
    await mountHome();
    const axes = await within(card()).findByRole("img", { name: "No employee sales in this period" });
    expect(Array.from(axes.querySelectorAll("text"), (t) => t.textContent)).toEqual(["1", "0.8", "0.6", "0.4", "0.2", "0"]);
    expect(axes.querySelectorAll("line[stroke-dasharray]")).toHaveLength(6);
    expect(ranking()).toEqual([]);
  });

  // Ticket 28: an answer without an `employees` array (the Route walk's `[]`) reads as no sales, never a crash.
  it.each([["[]", []], ["{}", {}]])("an answer of %s with no employees array draws the empty axes, not a crash", async (_name, body) => {
    perEmployee = [async () => jsonRes(body)];
    await mountHome();
    expect(await within(card()).findByRole("img", { name: "No employee sales in this period" })).toBeInTheDocument();
    expect(ranking()).toEqual([]);
  });
});

describe("Home: the static card set and per-card permissions", () => {
  const shownCards = () => Array.from(screen.getByTestId("dashboard-grid").children, (c) => (c as HTMLElement).dataset.card);
  const DEFAULT = ["earnings", "my-shifts", "clocked-in", "employee-sales", "scheduled-hours", "per-model"];

  it("draws the old Dashboard's card set in its order, with no Customize", async () => {
    await mountHome();
    expect(shownCards()).toEqual(DEFAULT);
    expect(screen.queryByRole("button", { name: "Customize" })).toBeNull();
  });

  it("a card the session's role hides is neither drawn nor read", async () => {
    session = { user: null, chatter: { username: "chatter_one" } };
    applied = async () => jsonRes({ ...(await appliedRes().json()), permissions: {
      enforced: true, pages: ["/"], scope: "self", denied_cards: ["/#card-earnings", "/#card-employee-sales"] } });
    renderWithProviders(<HomePage />);
    // The owner-only cards (Current clocked-in employees, Scheduled hours) take no cell for a chatter either.
    await waitFor(() => expect(shownCards()).toEqual(["my-shifts", "per-model"]));
    await screen.findByTestId("per-model-kpis-stub");
    expect(revenueReads()).toHaveLength(0);
    expect(perEmployeeReads()).toHaveLength(0);
  });

  it("the period tabs sit over the grid, so a session whose role hides the earnings card still picks the period", async () => {
    session = { user: null, chatter: { username: "chatter_one" } };
    applied = async () => jsonRes({ ...(await appliedRes().json()), permissions: {
      enforced: true, pages: ["/"], scope: "self", denied_cards: ["/#card-earnings"] } });
    renderWithProviders(<HomePage />);
    const stub = await screen.findByTestId("per-model-kpis-stub");
    expect(document.querySelector('[data-control="title"]')).toBeNull();
    const toolbar = screen.getByTestId("dashboard-toolbar");
    expect(within(toolbar).getByRole("radio", { name: "This week" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(toolbar).getByRole("radio", { name: "This month" }));
    await waitFor(() => expect([stub.dataset.from, stub.dataset.to]).toEqual(periodWindow("month", HONOLULU, "sunday")));
  });
});
