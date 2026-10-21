/**
 * Details' fan table over the relay's link_metrics fans read (synthetic fans): the "Since claim / Lifetime" toggle,
 * Infloww's columns and summary row, the link figures over the since-claim spend, the claim date (or first seen),
 * and "—" where a mode has no figure for a fan.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

/** Function permissions the role denies (`useActionAllowed`); none unless a case adds one. */
const denied = vi.hoisted(() => new Set<string>());
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: (action: string) => !denied.has(action) }));

import OfferClaimers from "@/components/growth/OfferClaimers";
import type { LinkFan, LinkFans, SpendBuckets } from "@/hooks/useGrowth";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;

function buckets(net: Partial<Record<"subs" | "posts" | "messages" | "streams" | "tips" | "other", number>>): SpendBuckets {
  const b = { net_missing_count: 0 } as Record<string, number>;
  let total = 0;
  for (const k of ["subs", "posts", "messages", "streams", "tips", "other"] as const) {
    const v = net[k] ?? 0;
    b[`${k}_net_cents`] = v;
    b[`${k}_cents`] = Math.round(v * 1.25);
    total += v;
  }
  b.total_net_cents = total;
  b.total_cents = Math.round(total * 1.25);
  return b as unknown as SpendBuckets;
}

const fan = (id: number, over: Partial<LinkFan>): LinkFan => ({
  fan_id: id, name: `Synth Fan ${id}`, username: `synth${id}`, subscribe_at: "2026-09-02T10:00:00Z",
  first_seen_at: "2026-09-03T08:00:00Z", since: buckets({}), lifetime: null, ...over,
});

const FANS: LinkFans = {
  fans: [
    fan(70000001, {
      since: buckets({ posts: 3840, messages: 1535 }),
      lifetime: { total_cents: 9900, subs_cents: 0, posts_cents: 6000, messages_cents: 3900, streams_cents: 0, tips_cents: 0 },
    }),
    fan(70000002, {
      name: "", since: buckets({ tips: 2000 }),
      lifetime: { total_cents: 2000, subs_cents: 0, posts_cents: 0, messages_cents: 0, streams_cents: 0, tips_cents: 2000 },
    }),
    fan(70000003, { lifetime: { total_cents: 0, subs_cents: 0, posts_cents: 0, messages_cents: 0, streams_cents: 0, tips_cents: 0 } }),
    // OnlyFans sent no subscribedOnData: no claim date, no figures.
    fan(70000004, { subscribe_at: null, since: null, lifetime: null }),
  ],
  ledger_since: "2026-08-20T00:00:00Z",
  walked_at: "2026-10-18T09:00:00Z",
  refreshing: false,
};

let client: QueryClient;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  get.mockReset();
  get.mockResolvedValue(FANS);
});
afterEach(() => { cleanup(); denied.clear(); vi.restoreAllMocks(); });

const mount = (kind: "trial" | "promo", ofId: number | null = 4242, extra: { campaignId?: number; count?: number } = {}) =>
  render(<QueryClientProvider client={client}><OfferClaimers accountId="a1" kind={kind} ofId={ofId} {...extra} /></QueryClientProvider>);
const rows = () => document.querySelectorAll("[data-fan-row]");
const cells = (i: number) => [...rows()[i].querySelectorAll("td")].map((c) => c.textContent);
const sum = () => [...document.querySelector("[data-fan-sum]")!.querySelectorAll("td")].map((c) => c.textContent);
const metrics = () => document.querySelector("[data-offer-metrics]")?.textContent;

describe("OfferClaimers", () => {
  it("reads the link's fans from the relay with the row's claim count", async () => {
    mount("trial", 4242, { count: 4 });
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(get).toHaveBeenCalledWith("/admin/link-metrics/fans?account_id=a1&kind=trial&of_id=4242&count=4");
  });

  it("shows Since claim by default: ledger net by kind, the claim date, and the summary row", async () => {
    mount("trial");
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(screen.getByRole("radio", { name: "Since claim" }).getAttribute("aria-checked")).toBe("true");
    expect(cells(0)).toEqual(["Synth Fan 70000001 @synth70000001", "Sep. 02, 2026", "$53.75", "$0.00", "$38.40", "$15.35", "$0.00", "$0.00"]);
    // No display name: the id.
    expect(cells(1)[0]).toBe("#70000002 @synth70000002");
    // No claim date from OnlyFans: first seen, and "—" rather than $0.
    expect(cells(3).slice(1)).toEqual(["Sep. 03, 2026 (first seen)", "—", "—", "—", "—", "—", "—"]);
    expect(sum()).toEqual(["Total", "$73.75", "$0.00", "$38.40", "$15.35", "$0.00", "$20.00"]);
    expect(metrics()).toBe("Earnings $73.75 · Fans who spent 2 · Spend/Claim 66.67%");
    expect(document.querySelector("[data-caveat]")?.textContent).toMatch(/since each fan claimed, which starts Aug\. 20, 2026; refunds and chargebacks/);
    expect(document.querySelector("[data-caveat]")?.textContent).toMatch(/re-subscribed/);
  });

  it("switches to Lifetime: OnlyFans' totals per fan, as read", async () => {
    mount("trial");
    await waitFor(() => expect(rows()).toHaveLength(4));
    fireEvent.click(screen.getByRole("radio", { name: "Lifetime" }));
    expect(screen.getByRole("radio", { name: "Lifetime" }).getAttribute("aria-checked")).toBe("true");
    expect(cells(0).slice(2)).toEqual(["$99.00", "$0.00", "$60.00", "$39.00", "$0.00", "$0.00"]);
    expect(cells(3).slice(2).every((c) => c === "—")).toBe(true);
    expect(sum()).toEqual(["Total", "$119.00", "$0.00", "$60.00", "$39.00", "$0.00", "$20.00"]);
    expect(document.querySelector("[data-caveat]")?.textContent).toMatch(/lifetime totals \(net\).*as read Oct\. 18, 2026/);
    // The link's figures stay the since-claim ones (they are the list's).
    expect(metrics()).toBe("Earnings $73.75 · Fans who spent 2 · Spend/Claim 66.67%");
  });

  it("adds an Other column only when some since-claim spend is outside the five kinds", async () => {
    get.mockResolvedValue({ ...FANS, fans: [fan(1, { since: buckets({ other: 500 }) })] });
    mount("trial");
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.getByRole("columnheader", { name: "Other" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Lifetime" }));
    expect(screen.queryByRole("columnheader", { name: "Other" })).toBeNull();
  });

  it("words a promotion's figure as Infloww's Revenue from N fans, with the campaign's re-arms folded in", async () => {
    mount("promo", 501, { campaignId: 7, count: 4 });
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(get).toHaveBeenCalledWith("/admin/link-metrics/fans?account_id=a1&kind=promo&of_id=501&campaign_id=7&count=4");
    expect(metrics()).toBe("Revenue $73.75 from 2 fans");
  });

  it("says so while a refresh holds OnlyFans and nothing is cached yet", async () => {
    get.mockResolvedValue({ ...FANS, fans: [], refreshing: true });
    mount("trial");
    await waitFor(() => expect(screen.getByText(/Reading OnlyFans/)).toBeTruthy());
  });

  it("offers Export fans unless the role denies Export CSV", async () => {
    mount("trial");
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(screen.getByRole("button", { name: "Export fans" })).toBeTruthy();
    cleanup();
    denied.add("export");
    mount("trial");
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(screen.queryByRole("button", { name: "Export fans" })).toBeNull();
  });

  it("reads nothing for an offer not linked to OnlyFans", () => {
    mount("trial", null);
    expect(screen.getByText(/Not linked to OnlyFans/)).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
  });
});
