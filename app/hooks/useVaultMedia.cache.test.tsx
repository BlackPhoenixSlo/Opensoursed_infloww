/**
 * REGRESSION PROBE — "vault positions are not cached any more".
 *
 * Two independent breakages, asserted here against the REAL code:
 *
 *  1. Warm-prefetch key desync. `useVaultMedia` reads a 6-part key
 *     ["vault-media", aid, type, listId, sort, query] since e5e5ab9 (server-
 *     side sort + search), but both warmers (app/inbox/page.tsx:109 and
 *     components/chat/ChatList.tsx:148) still WRITE the old 4-part key.
 *     TanStack matches a query to its cache entry by exact key hash, so the
 *     prefetched page is never read → every picker open re-fetches from OF.
 *
 *  2. Identity wipe eats the per-fan picker position. `wipeIdentityStorage()`
 *     (UserContext.tsx:112) nukes every `chatterly:` key not on an exact-match
 *     preserve allowlist — which does not include `chatterly:vault-state:*`
 *     (the fan's saved folder/sort/type) or `chatterly:vault-mru:*`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { ReactNode } from "react";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn() } }));

import { useVaultMedia } from "@/hooks/useVaultMedia";
import { wipeIdentityStorage } from "@/contexts/UserContext";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const AID = "acct-1";
const PAGE_1 = { list: [{ id: 1 }, { id: 2 }], hasMore: false };

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  relayGet.mockReset();
  relayGet.mockResolvedValue(PAGE_1);
});
afterEach(() => { cleanup(); window.localStorage.clear(); });

/** Verbatim copy of the warmer in app/inbox/page.tsx:108-117 (and the
 *  identical one in ChatList.tsx:147-156) — the 4-part key. */
async function warmLikeInboxDoesToday(aid: string) {
  await client.prefetchInfiniteQuery({
    queryKey: ["vault-media", aid, "all", null],
    initialPageParam: 0,
    queryFn: () => relay.get("/api/of/v2/vault/media?limit=24&offset=0&type=all", { accountId: aid }),
    staleTime: 60_000,
  });
}

describe("vault-media warm prefetch", () => {
  it("BUG: the warmed page is NOT reused — the picker refetches on open", async () => {
    await warmLikeInboxDoesToday(AID);
    expect(relayGet).toHaveBeenCalledTimes(1);          // the warm fetch itself

    // Picker opens with its defaults (sort=newest, no search).
    const { result } = renderHook(
      () => useVaultMedia({ accountId: AID, type: "all", listId: null }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.items.length).toBe(2));

    // If the warm cache were being hit, this would still be 1.
    expect(relayGet.mock.calls.length).toBeGreaterThan(1);
    expect(client.getQueryData(["vault-media", AID, "all", null])).toBeDefined();      // warmed…
    expect(client.getQueryData(["vault-media", AID, "all", null, "newest", ""])).toBeDefined(); // …and separately refetched
  });

  it("CONTROL: warming the key the hook actually reads serves it with zero fetches", async () => {
    await client.prefetchInfiniteQuery({
      queryKey: ["vault-media", AID, "all", null, "newest", ""],   // the fixed key
      initialPageParam: 0,
      queryFn: () => relay.get("/api/of/v2/vault/media?limit=24&offset=0&type=all", { accountId: AID }),
      staleTime: 60_000,
    });
    relayGet.mockClear();

    const { result } = renderHook(
      () => useVaultMedia({ accountId: AID, type: "all", listId: null }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.items.length).toBe(2));
    expect(relayGet).not.toHaveBeenCalled();
  });
});

describe("per-fan picker position across an identity switch", () => {
  it("BUG: login/logout wipes chatterly:vault-state + vault-mru", () => {
    window.localStorage.setItem(
      `chatterly:vault-state:${AID}:99`,
      JSON.stringify({ listId: 4242, sort: "oldest", type: "video" }),
    );
    window.localStorage.setItem(`chatterly:vault-mru:${AID}:99`, JSON.stringify([4242]));
    window.localStorage.setItem("chatterly:theme", "dark");   // on the preserve list

    wipeIdentityStorage();   // runs on every login / register / logout / chatter-login

    expect(window.localStorage.getItem("chatterly:theme")).toBe("dark");           // survives
    expect(window.localStorage.getItem(`chatterly:vault-state:${AID}:99`)).toBeNull(); // gone
    expect(window.localStorage.getItem(`chatterly:vault-mru:${AID}:99`)).toBeNull();   // gone
  });
});
