import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { AccountMeta } from "@/lib/relay";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));
vi.mock("@/lib/relay", async (orig) => ({
  SALARY_FREQUENCIES: (await orig<typeof import("@/lib/relay")>()).SALARY_FREQUENCIES,
  relay: { get: relayGet, post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
  proxyImage: (u: string) => u,
  proxyScrubFrame: (u: string) => u,
}));

const ACCOUNTS: AccountMeta[] = [
  { id: "of-1", nickname: "Olive", is_active: true, proxy_down: false },
  { id: "fl-1", nickname: "Fern", platform: "fansly", is_active: true, proxy_down: false },
];
const LOADED = { isPending: false, isLoading: false, isError: false, data: { accounts: ACCOUNTS, active_account_id: null } };
const DISABLED = { isPending: true, isLoading: false, isError: false, fetchStatus: "idle", data: undefined };
let accountsQ: object = LOADED;
vi.mock("@/hooks/useAccounts", () => ({
  useAccountLabel: (id?: string | null) => id ?? "",
  useAccounts: () => accountsQ,
}));
vi.mock("@/hooks/useFan", () => ({
  useFan: () => ({ data: { id: 7, tags: [], custom_nickname: null, notes: null }, isLoading: false, update: { mutate: vi.fn(), isPending: false } }),
}));
vi.mock("@/hooks/useMassExclude", () => ({
  useMassExclude: () => ({ isOn: false, isLoading: false, toggle: vi.fn() }),
}));
vi.mock("@/hooks/useFanPpvHistory", () => ({
  useFanPpvHistory: () => ({ data: { items: [], summary: { max_cents: 0, avg_cents: 0 } }, isLoading: false }),
}));
vi.mock("@/hooks/useFanChatMedia", () => ({
  useFanChatMedia: () => ({ data: { pages: [] }, isLoading: false, fetchNextPage: vi.fn(), hasNextPage: false }),
}));
vi.mock("./PersonaClaims", () => ({ PersonaClaims: () => null }));

import { FanDrawer } from "./FanDrawer";

const CHAT = {
  withUser: { id: 7, name: "Fan Seven", username: "fan7", avatar: null, displayName: "", notice: "" },
} as never;

const transactionReads = () => relayGet.mock.calls
  .filter(([path]) => String(path).startsWith("/api/of/v2/payouts/transactions"))
  .map(([, ctx]) => (ctx as { accountId?: string } | undefined)?.accountId);

let qc: QueryClient;
function Wrap({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  accountsQ = LOADED;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  relayGet.mockReset();
  relayGet.mockImplementation((path: string) => Promise.resolve(
    path.startsWith("/api/of/v2/payouts/transactions") ? { list: [], hasMore: false } : {},
  ));
});
afterEach(() => { cleanup(); qc.clear(); window.localStorage.clear(); });

describe("FanDrawer fan activity in a mixed OnlyFans + Fansly scope", () => {
  it("reads per-account transactions for the OnlyFans Creator's Fan and never for the Fansly Creator's", async () => {
    render(<FanDrawer open onClose={vi.fn()} accountId="fl-1" fanId={7} chat={CHAT} />, { wrapper: Wrap });
    render(<FanDrawer open onClose={vi.fn()} accountId="of-1" fanId={7} chat={CHAT} />, { wrapper: Wrap });
    await screen.findAllByText("Fan Seven");

    await waitFor(() => expect(transactionReads()).toContain("of-1"));
    expect(transactionReads()).toEqual(["of-1"]);
  });

  it("still reads when the accounts query is disabled (no principal), not waiting on it forever", async () => {
    accountsQ = DISABLED;
    render(<FanDrawer open onClose={vi.fn()} accountId="of-1" fanId={7} chat={CHAT} />, { wrapper: Wrap });
    await screen.findByText("Fan Seven");

    await waitFor(() => expect(transactionReads()).toEqual(["of-1"]));
  });
});
