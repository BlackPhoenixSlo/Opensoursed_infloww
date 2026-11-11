/**
 * The Home page (`/`) header's gaps, split from page.render.test.tsx (its harness, trimmed): Referrals that could
 * not be read (Total marked partial, never $0), Employee sales' answer without a daily series (the retry box), and
 * the browser's zone sent as `tz` when no report time zone is saved. `fetch` is mocked by URL.
 *
 * The fixture zone is Pacific/Honolulu (UTC-10:00, no daylight saving). Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ scope: { kind: "all" }, accountId: null }) }));
vi.mock("@/contexts/UserContext", async (orig) => {
  const value = () => ({ user: { user_id: "owner-1", username: "owner" }, loading: false, logout: vi.fn() });
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: value, useOptionalUser: value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = () => ({ chatter: null, logout: vi.fn() });
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: value, useOptionalChatter: value };
});
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null, clear: vi.fn() }) }));

import HomePage from "@/app/page";
import { REFERRALS_FAILED, TOTAL_PARTIAL } from "@/components/home/netMissingNote";

const HONOLULU = "Pacific/Honolulu";
const WEDNESDAY = "2026-10-14T12:00:00Z";
/** One tip: $12.50 gross, $10 net. */
const TIP = { day: null, kind: "tip", total_cents: 1250, count: 1 };
const PER_EMPLOYEE_ROWS = [
  { employee_id: 7, display_name: "Fixture Chatter One", messages_sent: 9, ppv_conversions: 2, revenue_cents: 4200,
    revenue_by_kind: { ppv: 3000, tip: 1200 } },
];

let fetchMock: ReturnType<typeof vi.fn>;
let applied: () => Promise<Response>;
/** The answer to `GET /admin/stats/referrals`. */
let referrals: () => Promise<Response>;
/** The answer to `GET /admin/stats/per-employee`. */
let perEmployee: () => Promise<Response>;

const appliedRes = (reportTz: string | null) => jsonRes({
  preferences: { tz: null, report_tz: reportTz, week_start: "sunday" },
  messaging: { ai_translation: true },
  permissions: { enforced: false, pages: null, scope: "all" },
});

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(WEDNESDAY));
  applied = async () => appliedRes(HONOLULU);
  referrals = async () => jsonRes({ rows: [], unavailable: [] });
  perEmployee = async () => jsonRes({ series: [], employees: [], attribution_fallback: null });
  fetchMock = vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://localhost");
    if (u.pathname === "/admin/settings/applied") return applied();
    if (u.pathname === "/admin/stats/revenue" && u.searchParams.get("status") === "reversed") return jsonRes({ rows: [] });
    if (u.pathname === "/admin/stats/revenue" && u.searchParams.get("group_by") === "kind") {
      const net = u.searchParams.get("include_net") === "true";
      return jsonRes({ rows: [net ? { ...TIP, net_cents: 1000, net_missing_count: 0 } : TIP] });
    }
    if (u.pathname === "/admin/stats/revenue") return jsonRes({ rows: [] });
    if (u.pathname === "/admin/stats/referrals") return referrals();
    if (u.pathname === "/admin/stats/per-employee") return perEmployee();
    if (u.pathname === "/admin/shifts") return jsonRes({ occurrences: [] });
    if (u.pathname === "/admin/shifts/clocked-in") return jsonRes({ time_tracking_enabled: false, clocked_in: [] });
    if (u.pathname === "/admin/shifts/timesheet") return jsonRes({ rows: [] });
    if (u.pathname === "/admin/shifts/me") return jsonRes({ accounts: [], occurrences: [], open_clocks: [], reminder: null });
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const tile = (key: string) => document.querySelector<HTMLElement>(`[data-control="${key}"]`)!;
const figure = (key: string) => tile(key).querySelector("[data-figure]")?.textContent ?? null;
const perEmployeeReads = () => fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
  .filter((u) => u.pathname === "/admin/stats/per-employee");

describe("Referrals that could not be read", () => {
  it.each([
    ["the read fails", async () => jsonRes({ detail: "OnlyFans down" }, 500)],
    ["every Creator fails", async () => jsonRes({ rows: [], unavailable: ["a1", "a2"] })],
  ])("when %s, Referrals shows -, not $0, and Total is marked partial", async (_name, answer) => {
    referrals = answer;
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(figure("total")).toBe("$10"));
    await waitFor(() => expect(figure("referrals")).toBe("-"));
    expect(tile("referrals")).toHaveAttribute("title", REFERRALS_FAILED);
    const marker = tile("total").querySelector("[data-partial]");
    expect(marker).toHaveAttribute("aria-label", TOTAL_PARTIAL);
    expect(marker).toHaveTextContent("*");
  });

  it("referrals that answered, then failed on a refetch, leave Total: the sales alone, Referrals -, marked (#43)", async () => {
    let failing = false;
    referrals = async () => (failing ? jsonRes({ detail: "OnlyFans down" }, 500)
      : jsonRes({ rows: [{ account_id: "a1", total_cents: 500, by_day: [] }], unavailable: [] }));
    const { queryClient } = renderWithProviders(<HomePage />);
    await waitFor(() => expect(figure("total")).toBe("$15"));
    failing = true;
    await act(() => queryClient.refetchQueries({ queryKey: ["stats", "referrals"] }));
    await waitFor(() => expect(figure("total")).toBe("$10"));
    expect(figure("referrals")).toBe("-");
    expect(tile("referrals")).toHaveAttribute("title", REFERRALS_FAILED);
    expect(tile("total").querySelector("[data-partial]")).toHaveAttribute("aria-label", TOTAL_PARTIAL);
  });

  it("a window OnlyFans truly paid no referrals in shows $0 and no partial marker", async () => {
    referrals = async () => jsonRes({ rows: [{ account_id: "a1", total_cents: 0, by_day: [] }], unavailable: [] });
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(figure("total")).toBe("$10"));
    await waitFor(() => expect(figure("referrals")).toBe("$0"));
    expect(tile("referrals")).not.toHaveAttribute("title");
    expect(tile("total").querySelector("[data-partial]")).toBeNull();
  });
});

describe("Employee sales' read", () => {
  const card = () => tile("employeeSales");
  const ranking = () => Array.from(card().querySelectorAll('[data-testid="sales-point"]'));

  // Ticket 28: an answer without a `series` array (the Route walk's `[]`) is never a crash, and never reads as a
  // window with no sales: it is the retry box.
  it.each([["[]", []], ["{}", {}], ["rows only", { employees: PER_EMPLOYEE_ROWS, attribution_fallback: null }]])(
    "an answer of %s with no series array shows the retry box, not empty axes", async (_name, body) => {
      perEmployee = async () => jsonRes(body);
      renderWithProviders(<HomePage />);
      expect(await within(card()).findByText(/Couldn't load Employee sales: the answer has no daily series/))
        .toBeInTheDocument();
      expect(within(card()).queryByRole("img", { name: "No employee sales in this period" })).toBeNull();
      expect(ranking()).toEqual([]);
    });

  it("sends the browser's zone as tz when no report time zone is saved, and keys the read by it", async () => {
    applied = async () => appliedRes(null);
    const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const { queryClient } = renderWithProviders(<HomePage />);
    await waitFor(() => expect(perEmployeeReads().length).toBeGreaterThan(0));
    expect(perEmployeeReads()[0].searchParams.get("tz")).toBe(browser);
    const key = queryClient.getQueryCache().getAll().map((q) => q.queryKey)
      .find((k) => k[0] === "dashboard" && k[1] === "per-employee");
    expect(key?.[key.length - 1]).toBe(browser);
  });
});
