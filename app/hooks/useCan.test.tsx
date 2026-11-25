import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

let mockUser: { user_id: string } | null = null;
vi.mock("@/contexts/UserContext", () => ({
  useOptionalUser: () => ({ user: mockUser, loading: false }),
}));

import { useAccountPlatform, useCan } from "@/hooks/useCan";
import { chatterAccountsQuery } from "@/lib/chatterAccounts";
import type { Capability, Platform } from "@/lib/platform";
import { relay } from "@/lib/relay";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  mockUser = null;
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("useAccountPlatform fetched"); }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.mocked(relay.get).mockReset();
});

describe("useAccountPlatform / useCan read the cached Creator list", () => {
  const owner = () => {
    mockUser = { user_id: "owner-A" };
    client.setQueryData(["accounts", "owner-A"], {
      accounts: [{ id: "of1", platform: "onlyfans" }, { id: "legacy" }, { id: "fs1", platform: "fansly" }],
      active_account_id: null,
      watchers: [{ id: "w1", role: "watcher" }],
    });
  };
  const chatterRow = (id: string, extra: Record<string, unknown> = {}) => ({
    account_id: id, nickname: id, color: null, owner_id: "o", owner_username: "o", is_active: true, ...extra,
  });
  const read = (id: string | null | undefined, cap: Capability = "pin_message") =>
    renderHook(() => ({ platform: useAccountPlatform(id), can: useCan(id, cap) }), { wrapper }).result.current;

  it.each<[string, string | null | undefined, Platform | null, boolean]>([
    ["an OnlyFans Creator", "of1", "onlyfans", true],
    ["a Creator saved before `platform`", "legacy", "onlyfans", true],
    ["a Fansly Creator", "fs1", "fansly", false],
    ["a watcher", "w1", "onlyfans", true],
    ["an absent Creator", "nope", null, false],
    ["no id", null, null, false],
    ["undefined id", undefined, null, false],
  ])("owner: %s", (_, id, platform, allowed) => {
    owner();
    expect(read(id)).toEqual({ platform, can: allowed });
  });

  it("an owner with a cold cache reads null and never fetches", () => {
    mockUser = { user_id: "owner-A" };
    expect(read("of1")).toEqual({ platform: null, can: false });
    expect(relay.get).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each<[string, string, Platform | null]>([
    ["a roster row with no `platform`", "c1", "onlyfans"],
    ["a Fansly roster row", "c2", "fansly"],
    ["an id outside the roster", "c9", null],
  ])("chatter: %s", (_, id, platform) => {
    client.setQueryData(chatterAccountsQuery.queryKey, [chatterRow("c1"), chatterRow("c2", { platform: "fansly" })]);
    expect(read(id).platform).toBe(platform);
  });

  it("a chatter with a cold roster reads null and never fetches", () => {
    expect(read("c1")).toEqual({ platform: null, can: false });
    expect(fetch).not.toHaveBeenCalled();
  });
});
