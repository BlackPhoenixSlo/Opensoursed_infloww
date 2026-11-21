/**
 * PromoReactivateCard (Keep running's status row, docs/spec/phase-01-promo-preempt.md): ticked campaigns read
 * "Re-creates after it ends"; a campaign Inflowwww turned off stays listed with its reason (`keep_warning`) and who
 * fixes it; a held one says why (`keep_blocked`). With Re-create at 90% filled (`preempt`, cap 10 or more) it reads
 * "Re-creates at 90% filled or shortly before it ends" unless the server switch is off or it waits (`keep_wait`).
 */
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
  reactivate_count: 0, last_reactivated_at: null, keep_warning: null, keep_blocked: null, created_at: null,
  source: "mirror", ...over,
});
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
      keep_blocked: "clock" })];
    mount();
    const line = await screen.findByRole("status");
    expect(line.textContent).toBe("“Week”: Waiting: will re-create after it ends (OnlyFans' clock doesn't match ours)");
    expect(line.className).toContain("break-words");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each<[string, RegExp]>([
    ["breaker", /3 promos in a row got no new claims or never went live — check the offer, then tick Keep running again/],
    ["create_unknown", /never showed up — check the promos on OnlyFans, then tick Keep running again/],
    ["price_free", /the page is free — set a subscription price on OnlyFans/],
    ["captcha", /asked for a captcha/],
    ["rate_limited", /refused two promo creates in a row/],
    ["create_refused", /refused the promo create — check the offer/],
    ["deactivated", /this Creator is deactivated/],
    ["limit_reached", /the free trial used up its Re-create limit — tick Keep running again to set a new one/],
    ["limit_needed", /this free trial has no Offer limit \(or was ticked under an older rule\) — set an Offer limit if it has none, then tick Keep running again/],
    ["kept_duplicate", /only one can be — tick Keep running again on the one you want/],
  ])("a campaign Inflowwww turned off (%s) stays listed with its reason and who fixes it", async (warning, text) => {
    campaigns = [promo({ name: "Week", auto_reactivate: false, keep_warning: warning })];
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("“Week”: Keep running is off:");
    expect(alert.textContent).toMatch(text);
    expect(alert.className).toContain("break-words");   // wraps on a 390 px phone
    expect(screen.getByText("No campaign is set to keep running")).toBeTruthy();
  });

  it("a fenced ticked campaign names the owner as the fix, as an alert that wraps", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, keep_blocked: "fence" })];
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("“Week”: Not re-creating: This server is not set to create promos — ask the owner to set it up");
    expect(alert.className).toContain("break-words");
  });

  it("a create OnlyFans has not shown yet holds a ticked campaign, nothing to fix", async () => {
    campaigns = [promo({ name: "Week", auto_reactivate: true, keep_blocked: "unknown" })];
    mount();
    const held = await screen.findByRole("status");
    expect(held.textContent).toContain("“Week”: Paused: waiting for OnlyFans to show the last re-create");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each<[Partial<PromoCampaign>, { text: string; off: boolean }[]]>([
    [{}, []],
    [{ keep_warning: "something_new" }, [{ text: "Keep running is off: tick Keep running again", off: true }]],
    [{ keep_blocked: "unknown" }, [{ text: expect.stringMatching(/^Paused: waiting/), off: false }]],
    [{ keep_blocked: "backoff", keep_blocked_until: "2099-01-02T10:05:00" },
      [{ text: expect.stringMatching(/^Paused until Jan 2, .+: the last re-create failed, so Inflowwww waits/), off: false }]],
    [{ keep_blocked: "budget", keep_blocked_until: null },
      [{ text: expect.stringMatching(/^Paused: 3 re-creates this hour \(or 8 today\)/), off: false }]],
    [{ auto_reactivate: true, keep_blocked: "fence" },
      [{ text: "Not re-creating: This server is not set to create promos — ask the owner to set it up", off: true }]],
    [{ auto_reactivate: true, keep_blocked: "retick" }, [{ text: "Not re-creating: Tick Keep running again", off: true }]],
    [{ auto_reactivate: true, recreates_left: 1 }, [{ text: "1 re-create left, then Keep running turns off", off: false }]],
    [{ auto_reactivate: true, recreates_left: 3 }, [{ text: "3 re-creates left, then Keep running turns off", off: false }]],
    [{ auto_reactivate: false, recreates_left: 3 }, []],
    [{ auto_reactivate: true, preempt: true, keep_blocked: "switch" },
      [{ text: "Re-create at 90% filled is off on this server — ask the owner", off: false }]],
    [{ auto_reactivate: true, preempt: true, keep_blocked: "switch", subscribe_counts: 9 }, []],
    // "clock" is the waiting line's reason, never a second line.
    [{ auto_reactivate: true, keep_blocked: "clock", keep_wait: "clock" },
      [{ text: "Waiting: will re-create after it ends (OnlyFans' clock doesn't match ours)", off: false }]],
    ...([
      ["count_untrusted", "the claim count isn't reliable yet"],
      ["end_unconfirmed", "OnlyFans' end time isn't confirmed yet"],
      ["second_live", "another promo is live too"],
      ["breaker_hold", "the last re-create hasn't shown up on OnlyFans yet"],
      ["backoff", "the last re-create failed"],
      ["budget", "3 re-creates this hour (or 8 today) reached"],
      ["no_recovery_slot", "keeping a re-create spare in case one fails"],
      ["cooldown", "the last re-create was moments ago"],
    ] as const).map(([wait, why]): [Partial<PromoCampaign>, { text: string; off: boolean }[]] =>
      [{ auto_reactivate: true, keep_wait: wait }, [{ text: `Waiting: will re-create after it ends (${why})`, off: false }]]),
    [{ auto_reactivate: true, keep_wait: "something_new" }, [{ text: "Waiting: will re-create after it ends", off: false }]],
  ])("keepLines(%o)", (over, want) => {
    expect(keepLines(promo(over))).toEqual(want);
  });
});
