/**
 * useFanVaultHistory — the response is normalised once, here, so every reader
 * (MessageList's BOUGHT badge, the Composer's attachment badges) can index
 * `data.by_media[id]` without guarding: a `/admin/vault/fan-history` reply
 * that lacks `by_media` arrives as an empty map, not undefined.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;

afterEach(() => {
  cleanup();
  relayGet.mockReset();
});

function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(() => useFanVaultHistory("acct-1", 42), { wrapper });
}

describe("useFanVaultHistory", () => {
  it("a reply without by_media resolves to an empty by_media map", async () => {
    relayGet.mockResolvedValue({});
    const { result } = render();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.by_media).toEqual({});
  });

  it("keeps the entries of a full reply", async () => {
    const entry = { send_count: 1, last_sent_at: null, last_price_cents: 0, was_purchased: true,
                    last_purchase_at: null, total_paid_cents: 500 };
    relayGet.mockResolvedValue({ by_media: { "601": entry } });
    const { result } = render();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.by_media["601"]).toEqual(entry);
  });
});
