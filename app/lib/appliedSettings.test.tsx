import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
let scope: string | null = null;
vi.mock("@/lib/relay", () => ({ relay: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: scope }) }));
vi.mock("@/hooks/useEmployeeKey", () => ({ usePrincipalId: () => "u1" }));

import { prefetchAppliedSettings, useAppliedSettings } from "./appliedSettings";

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
};

describe("prefetchAppliedSettings", () => {
  afterEach(() => { get.mockReset(); scope = null; vi.useRealTimers(); });

  it("the first unscoped fetch takes the early read, once; the next fetch reads again", async () => {
    get.mockResolvedValueOnce({ early: true }).mockResolvedValue({ early: false });
    prefetchAppliedSettings();
    const a = renderHook(() => useAppliedSettings(), { wrapper: wrap() });
    await waitFor(() => expect(a.result.current.data).toEqual({ early: true }));
    expect(get).toHaveBeenCalledTimes(1);
    const b = renderHook(() => useAppliedSettings(), { wrapper: wrap() });
    await waitFor(() => expect(b.result.current.data).toEqual({ early: false }));
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("a Creator in scope reads its own; an early read older than 10 s is not used", async () => {
    get.mockResolvedValueOnce({ early: true }).mockResolvedValue({ scoped: true });
    prefetchAppliedSettings();
    scope = "7";
    const a = renderHook(() => useAppliedSettings(), { wrapper: wrap() });
    await waitFor(() => expect(a.result.current.data).toEqual({ scoped: true }));
    expect(get).toHaveBeenLastCalledWith("/admin/settings/applied", { accountId: "7" });

    vi.useFakeTimers({ now: 0, toFake: ["Date"] });
    get.mockReset();
    get.mockResolvedValueOnce({ early: true }).mockResolvedValue({ early: false });
    prefetchAppliedSettings();
    vi.setSystemTime(10_001);
    scope = null;
    const b = renderHook(() => useAppliedSettings(), { wrapper: wrap() });
    await waitFor(() => expect(b.result.current.data).toEqual({ early: false }));
  });
});
