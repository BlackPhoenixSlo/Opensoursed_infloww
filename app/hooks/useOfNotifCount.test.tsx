import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn(async (_path: string, _opts?: unknown): Promise<unknown> => ({ all: 4 }));
const post = vi.fn(async (..._a: unknown[]): Promise<unknown> => ({ counters: { all: 0 } }));
vi.mock("@/lib/relay", () => ({
  relay: { get: (path: string, opts?: unknown) => get(path, opts), post: (...a: unknown[]) => post(...a) },
}));

import { makeTestQueryClient } from "@/test-utils";
import { armRead, resetReadGate } from "@/lib/ofReadGate";
import { holdLease } from "@/lib/viewLease";
import { dispatchNotifArrived } from "@/lib/notifSettings";
import { useMarkAllOfNotifsRead, useOfNotifCount } from "./useOfNotifCount";

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

describe("useMarkAllOfNotifsRead: a cached 0 by its ask time (W30-mu #49)", () => {
  beforeEach(() => { resetReadGate(); get.mockClear(); post.mockClear(); });
  afterEach(() => { resetReadGate(); });
  const sleep = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

  it("a 0 asked before an arrival and answered after it is written too: it may predate the arrival", async () => {
    const off = holdLease("strip", ["7"]);
    let answer!: (v: unknown) => void;
    get.mockImplementationOnce(() => new Promise((r) => { answer = r; }));
    const qc = makeTestQueryClient();
    const { result } = renderHook(() => ({ count: useOfNotifCount("7"), mark: useMarkAllOfNotifsRead() }), {
      wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    await sleep(5);
    act(() => dispatchNotifArrived());
    await sleep(5);
    await act(async () => { answer({ all: 0 }); });
    await waitFor(() => expect(qc.getQueryData(["of-notif-count", "7"])).toBe(0));
    await act(async () => { await result.current.mark.markAll(["7"]); });
    expect(post).toHaveBeenCalledTimes(1);
    off();
  });
});
