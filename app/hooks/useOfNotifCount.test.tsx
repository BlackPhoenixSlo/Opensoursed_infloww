import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn(async (_path: string, _opts?: unknown) => ({ all: 4 }));
vi.mock("@/lib/relay", () => ({ relay: { get: (path: string, opts?: unknown) => get(path, opts) } }));

import { makeTestQueryClient } from "@/test-utils";
import { armRead, resetReadGate } from "@/lib/ofReadGate";
import { holdLease } from "@/lib/viewLease";
import { useOfNotifCount } from "./useOfNotifCount";

function mount(accountId: string | null) {
  const qc = makeTestQueryClient();
  return renderHook(() => useOfNotifCount(accountId), {
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
  });
}

const turn = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("useOfNotifCount lease gate", () => {
  beforeEach(() => { resetReadGate(); get.mockClear(); });
  afterEach(() => { resetReadGate(); });

  it("an unleased Creator reads nothing until armed (its creator_warmed), then reads", async () => {
    const { result } = mount("7");
    await turn();
    expect(get).not.toHaveBeenCalled();
    await act(async () => { armRead("7"); });
    await waitFor(() => expect(result.current.count).toBe(4));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("a leased Creator reads at once", async () => {
    const off = holdLease("strip", ["7"]);
    const { result } = mount("7");
    await waitFor(() => expect(result.current.count).toBe(4));
    off();
  });

  it("null (a Dead-session Creator) reads nothing, even past the fallback", async () => {
    resetReadGate(0);
    mount(null);
    await turn();
    await turn();
    expect(get).not.toHaveBeenCalled();
  });
});
