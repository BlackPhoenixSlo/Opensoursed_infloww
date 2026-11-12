/**
 * useGrowth — a Growth page refreshes itself while viewed (docs/spec/phase-03-smaller-cuts.md): the relay's hourly
 * background prewarm only walks links with a List (LINK_PREWARM_SCOPE), so the trial links, promotions, OF tracking
 * links and their earnings refetch every GROWTH_VIEWED_REFRESH_MS (an hour) while idle, and the two lists with
 * figures every 15 s while the relay says a refresh is running.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import {
  GROWTH_VIEWED_REFRESH_MS,
  useOfTrackingEarnings,
  useOfTrackingLinks,
  usePromotions,
  useTrialLinks,
} from "@/hooks/useGrowth";
import { relay } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

let refreshing = false;
const calls = (path: string) => relayGet.mock.calls.filter(([u]) => String(u).startsWith(path)).length;

async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  refreshing = false;
  relayGet.mockReset();
  relayGet.mockImplementation(async (url: string) => {
    if (url.startsWith("/admin/of-tracking-links/earnings")) return { available: true, links: [] };
    if (url.startsWith("/admin/of-tracking-links")) return { links: [], username: null, url_verified: true, of_available: true };
    if (url.startsWith("/admin/promotions")) return { campaigns: [], of_available: true, metrics_refreshing: refreshing };
    return { links: [], of_available: true, sources: [], tags: [], metrics_updated_at: null, metrics_refreshing: refreshing };
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

function renderGrowth() {
  return renderHook(() => {
    useTrialLinks("acc1");
    usePromotions("acc1");
    useOfTrackingLinks("acc1");
    useOfTrackingEarnings("acc1");
  }, { wrapper });
}

const ROUTES = ["/admin/trial-links", "/admin/promotions", "/admin/of-tracking-links?", "/admin/of-tracking-links/earnings"];

describe("Growth refreshes itself while viewed", () => {
  it("names the hourly interval", () => {
    expect(GROWTH_VIEWED_REFRESH_MS).toBe(3_600_000);
  });

  it("idle: every list and the earnings read refetch once an hour, not sooner", async () => {
    renderGrowth();
    await advance(0);
    expect(ROUTES.map(calls)).toEqual([1, 1, 1, 1]);
    await advance(GROWTH_VIEWED_REFRESH_MS - 1_000);
    expect(ROUTES.map(calls)).toEqual([1, 1, 1, 1]);
    await advance(1_000);
    expect(ROUTES.map(calls)).toEqual([2, 2, 2, 2]);
    await advance(GROWTH_VIEWED_REFRESH_MS);
    expect(ROUTES.map(calls)).toEqual([3, 3, 3, 3]);
  });

  it("while the relay refreshes: the trial links and promotions every 15 s, then hourly once it is done", async () => {
    refreshing = true;
    renderGrowth();
    await advance(0);
    await advance(15_000);
    expect(ROUTES.map(calls)).toEqual([2, 2, 1, 1]);
    await advance(15_000);
    expect(ROUTES.map(calls)).toEqual([3, 3, 1, 1]);
    refreshing = false;
    await advance(15_000);                      // this read says done
    expect(ROUTES.map(calls)).toEqual([4, 4, 1, 1]);
    await advance(15_000);
    expect(ROUTES.map(calls)).toEqual([4, 4, 1, 1]);
    await advance(GROWTH_VIEWED_REFRESH_MS);
    expect(ROUTES.map(calls).slice(0, 2)).toEqual([5, 5]);
  });
});
