/**
 * BalanceTab — the Your Balance Panel (docs/spec/settings-tabs/phase-05-billing-balance-about.md,
 * Testing Decisions). `useScope` is mocked as AssistantWidget.test.tsx does; the Relay is mocked at
 * `fetch` by URL and `X-Account-Id`, so every assertion about requests is an assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

const { scope, roster } = vi.hoisted(() => ({
  scope: { accountId: "acc1" as string | null },
  roster: { accounts: [] as Array<{ id: string; nickname: string; has_session: boolean }> },
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
// The panel's own Creator picker lists the session-backed Creators; none unless a test sets them.
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.accounts }));
vi.mock("@/components/ui/AccountAvatarPicture", () => ({ AccountAvatarPicture: () => null }));

import { jsonRes, renderWithProviders } from "@/test-utils";
import BalanceTab from "@/components/settings/BalanceTab";

const BALANCE = "/api/of/v2/payments/referrals/balance";
const PAYOUTS = "/api/of/v2/payouts/requests/referral?limit=10";
const LABELS = ["Total earnings", "Available to withdraw", "Pending earnings", "Withdrawn"];
const ACC1 = { referralEarnings: 120, availableEarnings: 80, pendingEarnings: 25, withdrawnEarnings: 15 };
const ACC2 = { referralEarnings: 7.5, availableEarnings: 3, pendingEarnings: 4.5, withdrawnEarnings: 0 };
const PAYOUT = { createdAt: "2026-01-15T12:00:00+00:00", amount: 15, state: "done" };

/** What each account's routes answer; a route left out never answers (the query stays loading). */
let replies: Record<string, Partial<Record<string, () => Response>>>;
let fetchMock: ReturnType<typeof vi.fn>;

const calls = () =>
  fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    account: new Headers(init?.headers).get("X-Account-Id"),
  }));

beforeEach(() => {
  scope.accountId = "acc1";
  roster.accounts = [];
  replies = {
    acc1: { [BALANCE]: () => jsonRes(ACC1), [PAYOUTS]: () => jsonRes({ list: [PAYOUT], marker: null }) },
    acc2: { [BALANCE]: () => jsonRes(ACC2), [PAYOUTS]: () => jsonRes({ list: [], marker: null }) },
  };
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const reply = replies[new Headers(init?.headers).get("X-Account-Id") ?? ""]?.[url];
    return reply ? Promise.resolve(reply()) : new Promise<Response>(() => {});
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The four cards as [label, amount] pairs. */
const cards = () => {
  const terms = screen.queryAllByRole("term").map((t) => t.textContent);
  const values = screen.queryAllByRole("definition").map((d) => d.textContent);
  return terms.map((t, i) => [t, values[i]]);
};
const dashes = LABELS.map((l) => [l, "—"]);
/** The payouts table's body rows' cells. */
const payoutRows = () =>
  within(screen.getByRole("table")).getAllByRole("row").slice(1)
    .map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));

describe("BalanceTab", () => {
  it("in Single-Creator scope shows the four cards in USD from exactly the two referral GETs, sent with X-Account-Id", async () => {
    renderWithProviders(<BalanceTab />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Your Balance$/);
    await waitFor(() => expect(cards()).toEqual([
      ["Total earnings", "$120"],
      ["Available to withdraw", "$80"],
      ["Pending earnings", "$25"],
      ["Withdrawn", "$15"],
    ]));
    expect(calls().sort((a, b) => a.url.localeCompare(b.url))).toEqual([
      { method: "GET", url: BALANCE, account: "acc1" },
      { method: "GET", url: PAYOUTS, account: "acc1" },
    ]);
  });

  it("shows \"—\" on every card while the balance loads", () => {
    replies.acc1 = {};
    renderWithProviders(<BalanceTab />);
    expect(cards()).toEqual(dashes);
  });

  it("switching the scope to a second account shows that account's values, never the first's", async () => {
    const { rerender } = renderWithProviders(<BalanceTab />);
    await waitFor(() => expect(cards()[0]).toEqual(["Total earnings", "$120"]));
    scope.accountId = "acc2";
    rerender(<BalanceTab />);
    expect(screen.queryByText("$120")).not.toBeInTheDocument();
    await waitFor(() => expect(cards()).toEqual([
      ["Total earnings", "$8"],
      ["Available to withdraw", "$3"],
      ["Pending earnings", "$5"],
      ["Withdrawn", "$0"],
    ]));
    expect(payoutRows()).toEqual([["No payouts"]]);
    expect(calls().filter((c) => c.account === "acc2").map((c) => c.url).sort()).toEqual([BALANCE, PAYOUTS]);
  });

  it("shows \"—\", never 0, on a card whose key is missing or not a number", async () => {
    replies.acc1[BALANCE] = () => jsonRes({ referralEarnings: 120, availableEarnings: 80, withdrawnEarnings: "15.00" });
    renderWithProviders(<BalanceTab />);
    await waitFor(() => expect(cards()[0]).toEqual(["Total earnings", "$120"]));
    expect(cards()).toEqual([
      ["Total earnings", "$120"],
      ["Available to withdraw", "$80"],
      ["Pending earnings", "—"],
      ["Withdrawn", "—"],
    ]);
  });

  it("lists the referral payouts as Date / Amount / Status with the raw state", async () => {
    renderWithProviders(<BalanceTab />);
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Date", "Amount", "Status"]);
    await waitFor(() => expect(payoutRows()).toEqual([["Jan 15, 2026", "$15", "done"]]));
    expect(screen.getByRole("heading", { name: "Transaction history" })).toBeInTheDocument();
    // Infloww's history colours: a done payout is "complete" #666.
    expect(screen.getByRole("cell", { name: "done" })).toHaveClass("text-[#666666]");
  });

  it("shows \"No payouts\" for an empty payout list", async () => {
    replies.acc1[PAYOUTS] = () => jsonRes({ list: [], marker: null });
    renderWithProviders(<BalanceTab />);
    await waitFor(() => expect(payoutRows()).toEqual([["No payouts"]]));
  });

  it.each([["{}", {}], ["{list: null}", { list: null }]])(
    "shows \"—\", not \"No payouts\", for a 200 payouts body without a list: %s",
    async (_name, body) => {
      replies.acc1[PAYOUTS] = () => jsonRes(body);
      const { queryClient } = renderWithProviders(<BalanceTab />);
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(queryClient.isFetching()).toBe(0);
      });
      expect(payoutRows()).toEqual([["—"]]);
    },
  );

  it("a failed balance query shows \"—\" on every card and the Relay error text under them", async () => {
    replies.acc1[BALANCE] = () => jsonRes({ detail: "synthetic relay failure" }, 502);
    renderWithProviders(<BalanceTab />);
    expect(await screen.findByRole("alert")).toHaveTextContent("synthetic relay failure");
    expect(cards()).toEqual(dashes);
  });

  it("in All-Creators scope shows the first Creator's balance, and its own picker switches Creators", async () => {
    scope.accountId = null;
    roster.accounts = [
      { id: "acc1", nickname: "isa", has_session: true },
      { id: "acc2", nickname: "Account 2", has_session: true },
    ];
    renderWithProviders(<BalanceTab />);
    await waitFor(() => expect(cards()[0]).toEqual(["Total earnings", "$120"]));
    const picker = screen.getByRole("combobox", { name: "Creator" });
    expect(picker).toHaveTextContent("isa");
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole("option", { name: /Account 2/ }));
    await waitFor(() => expect(cards()[0]).toEqual(["Total earnings", "$8"]));
    expect(screen.queryByText("$120")).not.toBeInTheDocument();
  });

  it("with no Creator at all says \"Select a creator to see its balance\" and never calls fetch", async () => {
    scope.accountId = null;
    renderWithProviders(<BalanceTab />);
    expect(screen.getByText("Select a creator to see its balance")).toBeInTheDocument();
    expect(cards()).toEqual([]);
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
