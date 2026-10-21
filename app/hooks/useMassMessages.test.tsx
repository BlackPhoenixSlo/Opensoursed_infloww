/**
 * useMassMessages — the owner's sent list on a cold load. The Creators list
 * loads first (accountIds = []), then the per-Creator queries start and
 * resolve; the merged `rows` must fill once they do, not stay at the empty
 * list computed while the Creators were loading.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
// eventBus.on records each handler so a test fires SSE frames synchronously.
type Handler = (env: Record<string, unknown>) => void;
const handlers = new Map<string, Set<Handler>>();
vi.mock("@/lib/events", () => ({
  eventBus: {
    on(type: string, fn: Handler) {
      if (!handlers.has(type)) handlers.set(type, new Set());
      handlers.get(type)!.add(fn);
      return () => handlers.get(type)?.delete(fn);
    },
    onStateChange(fn: (connected: boolean) => void) {
      stateListeners.add(fn);
      return () => stateListeners.delete(fn);
    },
  },
}));
const stateListeners = new Set<(connected: boolean) => void>();
const fire = (type: string, env: Record<string, unknown>) =>
  act(() => handlers.get(type)?.forEach((fn) => fn(env)));

import { useMassMessages, useMassQueueProgress } from "@/hooks/useMassMessages";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

afterEach(() => {
  cleanup();
  relayGet.mockReset();
  relayPost.mockReset();
});

function render(initial: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(({ ids }: { ids: string[] }) => useMassMessages(ids), {
    wrapper,
    initialProps: { ids: initial },
  });
}

function itemsFor(path: string) {
  const acct = new URLSearchParams(path.split("?")[1]).get("account_id");
  if (acct === "acct-1") return { items: [{ id: 11, date: "2026-10-01T10:00:00Z", text: "older" }] };
  if (acct === "acct-2") return { items: [{ id: 22, date: "2026-10-02T10:00:00Z", text: "newer" }] };
  return { items: [] };
}

describe("useMassMessages", () => {
  it("fills the rows once the per-Creator queries resolve after the Creators list loads", async () => {
    relayGet.mockImplementation(async (path: string) => itemsFor(path));
    const { result, rerender } = render([]);
    expect(result.current.rows).toEqual([]);

    rerender({ ids: ["acct-1", "acct-2"] });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await waitFor(() => expect(result.current.rows.map((r) => r.id)).toEqual([22, 11]));
    expect(result.current.rows.map((r) => r.__accountId)).toEqual(["acct-2", "acct-1"]);
  });

  it("keeps the same rows reference across re-renders when no query's data changed", async () => {
    relayGet.mockImplementation(async (path: string) => itemsFor(path));
    const { result, rerender } = render(["acct-1"]);
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    const first = result.current.rows;
    rerender({ ids: ["acct-1"] });
    expect(result.current.rows).toBe(first);
  });
});

describe("useMassQueueProgress", () => {
  it("tracks a listed Creator's queue from its updates, and its finish drops it and refreshes that Creator", async () => {
    relayPost.mockResolvedValue({ account_id: "acct-1", days_back: 30, items: [], written: 1 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) =>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useMassQueueProgress(["acct-1"], 30), { wrapper });

    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 7, total: -1, pending: 23 } });
    expect(result.current).toEqual([{ queueId: 7, accountId: "acct-1" }]);
    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 7, total: 23, pending: 5 } });
    expect(result.current).toEqual([{ queueId: 7, accountId: "acct-1" }]);
    // Another Creator's queue is not ours to show.
    fire("chat_queue_update", { __account_id: "acct-9", chat_queue_update: { id: 8, total: 3, pending: 1 } });
    expect(result.current).toHaveLength(1);

    fire("chat_queue_finish", { __account_id: "acct-1", chat_queue_finish: { id: 7, total: 23, pending: 0 } });
    expect(result.current).toEqual([]);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/admin/mass-messages/refresh?account_id=acct-1&days_back=30&limit=100", undefined));

    // A cancelled queue is dropped without a refresh.
    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 9, total: 4, pending: 4 } });
    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 9, isCanceled: true } });
    expect(result.current).toEqual([]);
    expect(relayPost).toHaveBeenCalledTimes(1);

    // A resync or a lost stream may have hidden a finish frame: forget what was in flight.
    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 10 } });
    fire("resync", {});
    expect(result.current).toEqual([]);
    fire("chat_queue_update", { __account_id: "acct-1", chat_queue_update: { id: 11 } });
    act(() => stateListeners.forEach((fn) => fn(false)));
    expect(result.current).toEqual([]);
  });
});
