import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { createElement, type ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import { useSaveAccountConfig, type BrainConfig } from "@/hooks/useAccountConfig";
import { relay } from "@/lib/relay";

const relayPut = relay.put as unknown as Mock;
const CONFIG = { persona: "Mia", model: "m", daily_cost_cap_cents: 100 } as unknown as BrainConfig;

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: new QueryClient() }, children);
}

afterEach(() => relayPut.mockReset());

describe("useSaveAccountConfig", () => {
  it.each([
    ["a brain Save omits the cap", undefined, { persona: "Mia", model: "m" }],
    ["the spend-limit card sends it", { cap: true }, { persona: "Mia", model: "m", daily_cost_cap_cents: 100 }],
  ])("%s", async (_name, opts, sent) => {
    relayPut.mockResolvedValue({ account_id: "acc1", config: CONFIG });
    const { result } = renderHook(() => useSaveAccountConfig("acc1", opts), { wrapper });
    await result.current.mutateAsync(CONFIG);
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config", { account_id: "acc1", config: sent }, { cellAccountId: "acc1" }]);
  });
});
