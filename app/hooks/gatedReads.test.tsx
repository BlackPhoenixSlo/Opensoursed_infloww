import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));
vi.mock("@/contexts/UserContext", () => ({
  useOptionalUser: () => ({ user: { user_id: "owner-A" }, loading: false }),
}));

import { useAllChatFolders, useChatFolders } from "@/hooks/useChatFolders";
import { useChatPinned } from "@/hooks/useChatPinned";
import { useFanChatMedia } from "@/hooks/useFanChatMedia";
import { useTemplates } from "@/hooks/useTemplates";
import { relay } from "@/lib/relay";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  client.setQueryData(["accounts", "owner-A"], {
    accounts: [{ id: "of1", platform: "onlyfans" }, { id: "fs1", platform: "fansly" }],
    active_account_id: null,
  });
  vi.mocked(relay.get).mockResolvedValue({ list: [] });
});
afterEach(() => {
  cleanup();
  vi.mocked(relay.get).mockReset();
});

const FAN = "900539700124344321";
const HOOKS: [string, (accountId: string) => unknown][] = [
  ["useChatPinned", (a) => useChatPinned(a, FAN)],
  ["useFanChatMedia", (a) => useFanChatMedia(a, FAN)],
  ["useTemplates", (a) => useTemplates(a)],
  ["useChatFolders", (a) => useChatFolders(a)],
  ["useAllChatFolders", (a) => useAllChatFolders(a)],
];

describe.each(HOOKS)("%s asks only for a Creator whose Platform backs it", (_, use) => {
  it.each<[string, string, number]>([
    ["an OnlyFans Creator", "of1", 1],
    ["a Fansly Creator", "fs1", 0],
    ["an absent Creator", "nope", 0],
  ])("%s (%s) sends %i", async (_label, accountId, calls) => {
    renderHook(() => use(accountId), { wrapper });
    if (calls) await waitFor(() => expect(relay.get).toHaveBeenCalledTimes(calls));
    else {
      await new Promise((r) => setTimeout(r, 20));
      expect(relay.get).not.toHaveBeenCalled();
    }
  });
});
