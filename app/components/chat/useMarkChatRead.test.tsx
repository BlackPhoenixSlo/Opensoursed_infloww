/** useMarkChatRead x a chat-list read in flight: the read predates the mark, so it must not paint the dot back. */
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";

vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCountActions: () => ({ patchLocal: vi.fn() }) }));
vi.mock("@/lib/relay", () => ({ relay: { post: vi.fn(async () => ({ cleared: true })) } }));

import type { OFChatItem } from "@/lib/relay";
import { useMarkChatRead } from "./useMarkChatRead";

type Page = { rows: OFChatItem[]; hasMore: boolean };
const KEY = ["chats", "model", "acct-a", null, null, null, 25];
const unread = { __accountId: "acct-a", withUser: { id: 7 }, hasUnread: true, unreadMessagesCount: 2 } as unknown as OFChatItem;

afterEach(cleanup);

describe("useMarkChatRead", () => {
  it("drops a chat-list refetch in flight, so its older rows do not bring the blue dot back", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let answer: ((p: Page) => void) | null = null;
    const opts = {
      queryKey: KEY,
      initialPageParam: 0,
      getNextPageParam: () => undefined,
      queryFn: () => (answer ? new Promise<Page>((r) => { answer = r; }) : Promise.resolve({ rows: [unread], hasMore: false })),
    };
    await client.fetchInfiniteQuery(opts);
    // A Refresh is out: OF answers after the mark, still from before it.
    answer = () => {};
    void client.refetchQueries({ queryKey: KEY });
    await waitFor(() => expect(client.getQueryState(KEY)?.fetchStatus).toBe("fetching"));

    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    renderHook(() => useMarkChatRead({ accountId: "acct-a", fanId: 7, hasUnread: true, markRead: "onOpen" }), { wrapper });
    const row = () => client.getQueryData<InfiniteData<Page>>(KEY)!.pages[0].rows[0];
    await waitFor(() => expect(row().hasUnread).toBe(false));

    (answer as (p: Page) => void)({ rows: [unread], hasMore: false });
    await new Promise((r) => setTimeout(r, 20));
    expect(row().hasUnread).toBe(false);
    expect(row().unreadMessagesCount).toBe(0);
  });
});
