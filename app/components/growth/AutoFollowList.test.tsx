/**
 * The Auto-follow list (Infloww parity, page-parity 13): one row per creator with its counts
 * and switch, the "Creator:" / "Auto-follow:" filters with Reset, the empty table, and the
 * details view a row click opens.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});

import AutoFollowList, { formatFollowedAt } from "@/components/growth/AutoFollowList";
import { relay, type AccountMeta } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const ACCOUNTS = [
  { id: "a1", nickname: "Alice", has_session: true },
  { id: "a2", nickname: "Bella", has_session: true },
] as unknown as AccountMeta[];

const STATS = {
  rows: [
    { account_id: "a1", on: true, total: 42, today: 3, yesterday: 5, d7: 11, d30: 30,
      last_followed_at: "2026-10-18T09:05:00" },
    { account_id: "a2", on: false, total: 0, today: 0, yesterday: 0, d7: 0, d30: 0,
      last_followed_at: null },
  ],
};

const RECORDS = {
  total: 1,
  rows: [{ fan_id: 777, name: "Rob", username: "rob1", avatar_url: null,
    total_spend_cents: 12345, expires_at: null, followed_at: "2026-10-17T20:00:00",
    follow_count: 2 }],
};

let client: QueryClient;

beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  relayGet.mockReset(); relayPost.mockReset();
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/auto-follow/stats")) return Promise.resolve(STATS);
    if (p.startsWith("/admin/auto-follow/records")) return Promise.resolve(RECORDS);
    return Promise.resolve({});
  });
  relayPost.mockResolvedValue({ action: "parked" });
});
afterEach(() => cleanup());

function mount(accounts: AccountMeta[] = ACCOUNTS) {
  render(<QueryClientProvider client={client}><AutoFollowList accounts={accounts} /></QueryClientProvider>);
}

/** Click `combobox`, then its option. */
function choose(combobox: HTMLElement, option: string) {
  fireEvent.click(combobox);
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
}

describe("AutoFollowList", () => {
  it("lists each creator with Infloww's columns and counts", async () => {
    mount();
    await waitFor(() => expect(screen.getByText("42")).toBeTruthy());
    for (const h of ["Creator name", "Total follows", "Today", "Yesterday", "7 days",
      "30 days", "Last followed", "Action"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeTruthy();
    }
    const row = within(screen.getByTestId("af-row-a1"));
    for (const v of ["3", "5", "11", "30"]) expect(row.getByText(v)).toBeTruthy();
    expect(row.getByText(formatFollowedAt("2026-10-18T09:05:00"))).toBeTruthy();
    expect(screen.getByText("Automatically follow fans whose subscriptions have expired")).toBeTruthy();
  });

  it("formats the follow time as MMMM DD, YYYY hh:mm A", () => {
    expect(formatFollowedAt(null)).toBe("-");
    expect(formatFollowedAt("2026-10-18T09:05:00")).toMatch(/^[A-Z][a-z]+ \d\d, \d{4} \d\d:\d\d (AM|PM)$/);
  });

  it("the switch flips the account's auto_follow kind, without opening details", async () => {
    mount();
    const sw = await screen.findByRole("switch", { name: "Auto-follow Alice" });
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));
    fireEvent.click(sw);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/automation-rules/switch", { account_id: "a1", kind: "auto_follow", enable: false }));
    expect(screen.queryByText("Details")).toBeNull();
  });

  it("filters by creator and by on/off under Infloww's labels, and Reset clears both", async () => {
    mount();
    await screen.findByTestId("af-row-a2");
    expect(screen.getByText("Creator:")).toBeTruthy();
    expect(screen.getByText("Auto-follow:")).toBeTruthy();
    choose(screen.getByRole("combobox", { name: "Auto-follow" }), "On");
    expect(screen.queryByTestId("af-row-a2")).toBeNull();
    expect(screen.getByTestId("af-row-a1")).toBeTruthy();
    choose(screen.getByRole("combobox", { name: "Creator" }), "Bella");
    expect(screen.getByText("No data")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByTestId("af-row-a1")).toBeTruthy();
    expect(screen.getByTestId("af-row-a2")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Creator" }).textContent).toContain("All creators");
    expect(screen.getByRole("combobox", { name: "Auto-follow" }).textContent).toContain("All");
  });

  it("with no creators draws the page and the table's empty state", async () => {
    mount([]);
    expect(screen.getByText("Automatically follow fans whose subscriptions have expired")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Creator name" })).toBeTruthy();
    expect(screen.getByText("No data")).toBeTruthy();
  });

  it("a row click opens the details view of the fans followed, sortable", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("af-row-a1"));
    await waitFor(() => expect(screen.getByText("Rob")).toBeTruthy());
    expect(screen.getByText("Details")).toBeTruthy();
    for (const h of ["Fans name", "Total spend", "Expiry date", "Follow date", "Actions"]) {
      expect(screen.getByRole("columnheader", { name: new RegExp(h) })).toBeTruthy();
    }
    expect(screen.getByText("$123")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Chat with Rob" }).getAttribute("href"))
      .toBe("/messages-pro/a1/777");
    const first = String(relayGet.mock.calls.find((c) => String(c[0]).startsWith("/admin/auto-follow/records"))![0]);
    expect(first).toContain("account_id=a1");
    expect(first).toContain("sort=followed_at");

    fireEvent.click(screen.getByRole("button", { name: /Total spend/ }));
    await waitFor(() => expect(relayGet.mock.calls.some((c) =>
      String(c[0]).includes("sort=spend") && String(c[0]).includes("order=desc"))).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Auto-Follow" }));
    expect(await screen.findByTestId("af-row-a1")).toBeTruthy();
  });
});
