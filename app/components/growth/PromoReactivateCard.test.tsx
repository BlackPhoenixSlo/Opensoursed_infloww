import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn() } };
});

import PromoReactivateCard, { keepLines } from "@/components/growth/PromoReactivateCard";
import type { PromoCampaign } from "@/hooks/useGrowth";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;

const promo = (over: Partial<PromoCampaign>): PromoCampaign => ({
  id: 1, of_promo_id: 501, name: "Promo", discount_percent: 50, price_cents: 0, subscribe_counts: 10,
  subscribe_days: 30, message: "", promo_type: "all", status: "active", subscriber_count: 0, auto_reactivate: false,
  reactivate_count: 0, last_reactivated_at: null, keep_blocked: null, keep_lines: [], created_at: null,
  source: "mirror", ...over,
});
const line = (lead: string | null, text: string, off = false, until: string | null = null) => ({ lead, text, off, until });
const RULE = { id: 9, kind: "promo_reactivate", is_enabled: true, every_seconds: 3600,
  payload: { dry_run: false }, last_run: null };

let client: QueryClient;
let campaigns: PromoCampaign[] = [];
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  get.mockReset();
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/promotions")) return Promise.resolve({ campaigns, of_available: true });
    if (path.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [RULE] });
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());

const mount = () => render(<QueryClientProvider client={client}><PromoReactivateCard accountId="a1" /></QueryClientProvider>);

describe("PromoReactivateCard", () => {
  it("a ticked campaign re-creates after it ends, with no warning", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true })];
    mount();
    const row = await screen.findByRole("region", { name: "Auto-activate campaign" });
    expect(await within(row).findByText("Keeping “Week” running")).toBeTruthy();
    expect(within(row).getByText(/Re-creates after it ends/)).toBeTruthy();
    expect(within(row).queryByRole("alert")).toBeNull();
  });

  it("Re-create at 90% filled on a cap of 10 or more re-creates early", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, preempt: true, subscribe_counts: 10 })];
    mount();
    const row = await screen.findByRole("region", { name: "Auto-activate campaign" });
    expect(await within(row).findByText(/Re-creates at 90% filled or shortly before it ends/)).toBeTruthy();
    expect(within(row).queryByText(/after it ends/)).toBeNull();
  });

  it.each<[string, Partial<PromoCampaign>]>([
    ["the second tick off", { preempt: false }],
    ["a cap under 10", { subscribe_counts: 9 }],
    ["unlimited claims", { subscribe_counts: 0 }],
    ["the server switch off", { keep_blocked: "switch" }],
    ["waiting", { keep_wait: "count_untrusted" }],
  ])("%s: re-creates after it ends", async (_name, over) => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, preempt: true, subscribe_counts: 50, ...over })];
    mount();
    const row = await screen.findByRole("region", { name: "Auto-activate campaign" });
    expect(await within(row).findByText(/Re-creates after it ends/)).toBeTruthy();
    expect(within(row).queryByText(/90% filled or shortly/)).toBeNull();
  });

  it("a waiting campaign says why in a line that wraps on a phone", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, preempt: true, subscribe_counts: 50, keep_wait: "clock",
      keep_blocked: "clock", keep_lines: [line("Waiting", "will re-create after it ends (OnlyFans' clock doesn't match ours)")] })];
    mount();
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("“Week”: Waiting: will re-create after it ends (OnlyFans' clock doesn't match ours)");
    expect(status.className).toContain("break-words");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a campaign Inflowwww turned off stays listed with the relay's reason, as an alert that wraps", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: false,
      keep_lines: [line("Keep running is off", "3 promos in a row … then tick Keep running again", true)] })];
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("“Week”: Keep running is off: 3 promos in a row … then tick Keep running again");
    expect(alert.className).toContain("break-words");
    expect(screen.getByText("No campaign is set to keep running")).toBeTruthy();
  });

  it("W30 F29 promises a check at least hourly, never a re-create within the hour", async () => {
    campaigns = [];
    mount();
    expect(await screen.findByText(/usually within minutes, checked at least hourly/)).toBeTruthy();
    expect(screen.queryByText(/at most an hour/)).toBeNull();
  });

  it("a row with no lines (an OnlyFans-only promo) says nothing", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, keep_lines: [] })];
    mount();
    expect(await screen.findByText("Keeping “Week” running")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each<[PromoCampaign["keep_lines"], { text: string; off: boolean }[]]>([
    [[], []],
    [[line("Not re-creating", "Tick Keep running again", true)], [{ text: "Not re-creating: Tick Keep running again", off: true }]],
    [[line("Paused", "the last re-create failed", false, "2099-01-02T10:05:00")],
      [{ text: expect.stringMatching(/^Paused until Jan 2, .+: the last re-create failed$/), off: false }]],
    [[line(null, "1 re-create left, then Keep running turns off")],
      [{ text: "1 re-create left, then Keep running turns off", off: false }]],
  ])("keepLines(%o)", (lines, want) => {
    expect(keepLines(promo({ keep_lines: lines }))).toEqual(want);
  });
});
