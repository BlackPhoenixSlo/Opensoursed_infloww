/**
 * warmUpMayRefetch — the warm-up's post-bust invalidation, run against a real
 * QueryClient: a chat list loading its next page keeps that page, and any
 * settled list (its next page landed, failed, or restored from the snapshot)
 * is refetched, so the badge and the list read the same window.
 */
import { describe, expect, it, vi } from "vitest";
import { dehydrate, hydrate, InfiniteQueryObserver, QueryClient } from "@tanstack/react-query";

vi.mock("@/hooks/useChatList", () => ({ prefetchModelChatList: vi.fn() }));
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCountActions: () => ({ refreshOne: vi.fn() }) }));

import { warmUpMayRefetch } from "./useCreatorWarmUp";

type Page = { offset: number; read: number; hasMore: boolean };
type Before = "next page in flight" | "next page landed" | "next page failed" | "restored from snapshot" | "plain refetch in flight";

const KEY = ["chats", "model", "acct-a", "all"];
const tick = () => new Promise((r) => setTimeout(r, 0));

async function warmUpAfter(before: Before) {
  let reads = 0;
  let failNext = before === "next page failed";
  const gates: Array<() => void> = [];
  // The one read held at the wire across the warm-up: the next page's, or the plain refetch's head.
  const heldRead = before === "next page in flight" ? 2 : before === "plain refetch in flight" ? 3 : 0;
  const options = {
    queryKey: KEY,
    initialPageParam: 0,
    staleTime: 30_000,
    retry: false,
    getNextPageParam: (last: Page, all: Page[]) => (last.hasMore ? all.length * 25 : undefined),
    queryFn: async ({ pageParam }: { pageParam: number }): Promise<Page> => {
      const read = ++reads;
      if (read === heldRead) await new Promise<void>((r) => gates.push(r));
      if (pageParam > 0 && failNext) {
        failNext = false;
        throw new Error("OF error");
      }
      return { offset: pageParam, read, hasMore: pageParam === 0 };
    },
  };
  let qc = new QueryClient();
  let observer = new InfiniteQueryObserver(qc, options);
  let unsubscribe = observer.subscribe(() => {});
  await vi.waitFor(() => expect(observer.getCurrentResult().data?.pages).toHaveLength(1));

  const nextPage = observer.fetchNextPage();
  if (before !== "next page in flight") await nextPage;
  if (before === "restored from snapshot") {
    const snapshot = JSON.parse(JSON.stringify(dehydrate(qc)));
    unsubscribe();
    qc = new QueryClient();
    hydrate(qc, snapshot);
    observer = new InfiniteQueryObserver(qc, options);
    unsubscribe = observer.subscribe(() => {});
  }
  if (before === "plain refetch in flight") void observer.refetch();
  await tick();

  const readsBefore = reads;
  const invalidated = qc.invalidateQueries({ queryKey: ["chats", "model", "acct-a"], predicate: warmUpMayRefetch });
  await tick();
  gates.splice(0).forEach((open) => open());
  await invalidated;
  await nextPage.catch(() => {});
  await vi.waitFor(() => expect(qc.getQueryState(KEY)?.fetchStatus).toBe("idle"));
  const pages = qc.getQueryData<{ pages: Page[] }>(KEY)?.pages ?? [];
  unsubscribe();
  return { offsets: pages.map((p) => p.offset), headRereadByWarmUp: pages[0].read > readsBefore };
}

describe("warmUpMayRefetch", () => {
  it.each<[Before, number[], boolean]>([
    ["next page in flight", [0, 25], false],
    ["next page landed", [0, 25], true],
    ["next page failed", [0], true],
    ["restored from snapshot", [0, 25], true],
    ["plain refetch in flight", [0, 25], true],
  ])("%s: pages %j, head re-read by the warm-up %s", async (before, offsets, reread) => {
    expect(await warmUpAfter(before)).toEqual({ offsets, headRereadByWarmUp: reread });
  });
});
