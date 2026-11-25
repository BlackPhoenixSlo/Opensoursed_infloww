import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { useVaultMediaByIds } from "@/hooks/useVaultMediaByIds";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const AID = "acct-1";

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const pending: Array<() => void> = [];

function meteredRelay() {
  const release = pending;
  let live = 0;
  let peak = 0;
  relayGet.mockImplementation((path: string) => {
    live += 1;
    peak = Math.max(peak, live);
    const id = Number(path.split("/").pop());
    return new Promise((resolve) => {
      release.push(() => {
        live -= 1;
        resolve({ id, type: "photo", files: {} });
      });
    });
  });
  return {
    get peak() {
      return peak;
    },
    get started() {
      return release.length;
    },
    async drain() {
      while (release.length) {
        release.splice(0).forEach((fn) => fn());
        await Promise.resolve();
        await Promise.resolve();
      }
    },
  };
}

beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  relayGet.mockReset();
});
afterEach(async () => {
  while (pending.length) {
    pending.splice(0).forEach((fn) => fn());
    await Promise.resolve();
    await Promise.resolve();
  }
  cleanup();
});

describe("useVaultMediaByIds concurrency", () => {
  it("does not release a whole library of ids at once", async () => {
    const meter = meteredRelay();
    const ids = Array.from({ length: 60 }, (_, i) => 5000 + i);

    renderHook(() => useVaultMediaByIds(AID, ids), { wrapper });

    await waitFor(() => expect(meter.started).toBeGreaterThan(0));
    await Promise.resolve();
    await Promise.resolve();

    expect(meter.peak).toBeLessThanOrEqual(6);
    expect(meter.peak).toBeGreaterThan(1);
  });

  it("still resolves every id once the queue drains", async () => {
    const meter = meteredRelay();
    const ids = [7001, 7002, 7003, 7004, 7005, 7006, 7007, 7008, 7009, 7010];

    const { result } = renderHook(() => useVaultMediaByIds(AID, ids), { wrapper });

    await waitFor(() => expect(meter.started).toBeGreaterThan(0));
    await meter.drain();

    await waitFor(() => {
      expect(Object.keys(result.current)).toHaveLength(ids.length);
    });
    expect(relayGet).toHaveBeenCalledTimes(ids.length);
  });

  it("releases the slot when a request rejects, so a 404 cannot wedge the queue", async () => {
    relayGet.mockRejectedValue(new Error("404"));
    const ids = Array.from({ length: 12 }, (_, i) => 8000 + i);

    renderHook(() => useVaultMediaByIds(AID, ids), { wrapper });

    await waitFor(() => {
      expect(relayGet).toHaveBeenCalledTimes(ids.length);
    });
  });
});
