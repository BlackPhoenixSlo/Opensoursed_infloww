/**
 * Fan reports' frame (page-parity 29): the creator column lists the Creators beside the report and picks the first
 * (Infloww reports one Creator at a time, with no "All creators" row, owner P2-5); Total fans is Not wired; the per-fan data sits under an "Inflowwww extras" heading.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});
const ACCOUNTS = [
  { id: "7", nickname: "Mia", has_session: true, is_active: true },
  { id: "8", nickname: "Zoe", has_session: true, is_active: true },
];
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ isPending: false, data: { accounts: ACCOUNTS } }),
  useActiveAccounts: () => ACCOUNTS,
}));
/** The Agency's saved report time zone; null is none saved. */
const prefs = vi.hoisted(() => ({ reportTz: "UTC" as string | null }));
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({
    isPending: false, data: { preferences: { report_tz: prefs.reportTz, week_start: "monday" } },
  }),
  useWeekStart: () => "monday",
}));
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => ({}) }));
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));
vi.mock("@/components/stats/UserDataTab", () => ({
  default: ({ accountId }: { accountId: string }) => <div>User data for {accountId}</div>,
}));

import FanReport from "@/components/stats/FanReport";
import { relay } from "@/lib/relay";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.unstubAllEnvs();
  prefs.reportTz = "UTC";
});

const BODY = { top_fans: [], traffic: [], growth: [] };

function renderPage() {
  const get = relay.get as unknown as Mock;
  get.mockImplementation(async (path: string) => (path.startsWith("/admin/stats/fan-report") ? BODY : { all: 0 }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><FanReport /></QueryClientProvider>);
  const reads = () => get.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith("/admin/stats/fan-report"));
  return reads;
}

describe("FanReport", () => {
  it("lists the Creators in the column and reports the first", async () => {
    const reads = renderPage();
    const column = within(screen.getByRole("complementary", { name: "Creators" }));
    const rows = column.getAllByTestId("of-creator-row").map((r) => r.textContent);
    // Each Creator row starts with its avatar's initial.
    expect(rows).toEqual(["MMia", "ZZoe"]);
    await waitFor(() => expect(reads().at(-1)).toContain("account_id=7"));
    expect(column.getByRole("button", { name: /Mia/ })).toHaveAttribute("aria-current", "true");

    fireEvent.click(column.getByRole("button", { name: /Zoe/ }));
    await waitFor(() => expect(reads().at(-1)).toContain("account_id=8"));
  });

  it("offers no All creators pick, in the column or the phone select", async () => {
    const reads = renderPage();
    await waitFor(() => expect(reads().length).toBeGreaterThan(0));
    expect(reads().every((p) => p.includes("account_id="))).toBe(true);
    fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.queryByRole("option", { name: /All creators/ })).toBeNull();
  });

  it("marks Total fans Not wired and keeps the column's Creator's per-fan data under the extras heading", async () => {
    renderPage();
    const card = await screen.findByRole("region", { name: "Total fans (growth & trends)" });
    expect(within(card).getByTestId("total-fans-not-wired")).toHaveAttribute("title", "not wired");
    const extras = screen.getByRole("region", { name: "Inflowwww extras" });
    expect(within(extras).getByText("User data for 7")).toBeInTheDocument();
    // One creator picker: the column's.
    expect(within(extras).queryByRole("combobox")).toBeNull();
  });

  it("counts the days in UTC when no report time zone is saved, as the read groups New fans", async () => {
    // A New York browser: its local days would cut the window 4 hours off the read's UTC days.
    vi.stubEnv("TZ", "America/New_York");
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-21T02:00:00Z") });
    prefs.reportTz = null;
    const reads = renderPage();
    await waitFor(() => expect(reads().length).toBeGreaterThan(0));
    const q = new URLSearchParams(reads().at(-1)!.split("?")[1]);
    // Today in UTC is 21 Oct (still 20 Oct in New York): 30 UTC days through it.
    expect(q.get("from")).toBe("2026-09-22T00:00:00.000Z");
    expect(q.get("to")).toBe("2026-10-21T23:59:59.999Z");
    expect(screen.getAllByText("UTC+00:00").length).toBeGreaterThan(0);
  });
});
