import type { ReactNode } from "react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePaged } from "./ofMirrorStats";
import type { Period } from "./ofMirrorStatsPeriod";
import { relay, RelayError } from "./relay";

let client: QueryClient;
let get: MockInstance;
const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const p = { start: new Date("2026-01-01T00:00:00Z"), end: new Date("2026-01-31T00:00:00Z") } as Period;
const route = (param: { offset: number }) => `/api/of/v2/payouts/transactions?offset=${param.offset}`;
const next = (_last: unknown, pages: unknown[]) => ({ offset: pages.length * 10 });
const pageTwo = () => get.mock.calls.filter((c) => String(c[0]).endsWith("offset=10")).length;
const flush = async (ms: number) => {
  for (let t = 0; t < ms; t += 250) await act(async () => void (await vi.advanceTimersByTimeAsync(250)));
};

beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient();
  get = vi.spyOn(relay, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("offset=0")) return { list: [{ id: 1, createdAt: "2026-11-01T00:00:00Z" }], hasMore: true };
    throw new RelayError(502, { detail: "upstream" });
  });
});
afterEach(() => {
  cleanup();
  get.mockRestore();
  client.clear();
  vi.useRealTimers();
});

describe("usePaged", () => {
  it("a failing next page is asked at most 3 times (1 + 2 retries), then paging stops until Retry", async () => {
    const { result } = renderHook(() => usePaged("a1", route, next, p, true), { wrapper });
    await flush(30_000);
    expect(pageTwo()).toBe(3);
    expect(result.current.error).toBe(true);
    expect(result.current.body?.more).toBeNull();
    expect(result.current.body?.stalled).toBe(true);
    await act(async () => void result.current.refetch());
    await flush(30_000);
    expect(pageTwo()).toBe(6);
    expect(get.mock.calls.filter((c) => String(c[0]).endsWith("offset=0")).length).toBe(1);
  });
});
