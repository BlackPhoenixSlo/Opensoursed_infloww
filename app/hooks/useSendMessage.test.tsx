import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useSendMessage } from "@/hooks/useSendMessage";
import { rosterCountsKey, resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import { relay, type OFChatItem } from "@/lib/relay";

vi.mock("@/lib/relay", () => ({
  relay: { get: vi.fn(), post: vi.fn(() => Promise.resolve({ id: 999, media: [] })) },
  RelayError: class RelayError extends Error {},
}));
vi.mock("@/lib/events", () => ({
  eventBus: { isConnected: () => false, onStateChange: () => () => {} },
}));
vi.mock("@/lib/perfLog", () => ({
  perfOpId: () => "op", perfLog: () => {}, perfDelivered: () => {}, perfError: () => {},
}));
vi.mock("@/contexts/EmployeeContext", () => ({
  useEmployee: () => ({ current: null }),
}));

const ACCT = "acct1";
const FAN = 42;
const OTHER = 7;

function chatRow(fanId: number): OFChatItem {
  return {
    withUser: { id: fanId, name: `fan${fanId}` },
    __accountId: ACCT,
    hasUnread: true,
    unreadMessagesCount: 1,
    lastMessage: {
      id: 1,
      text: "old",
      fromUser: { id: fanId },
      createdAt: "2026-06-04T00:00:00.000Z",
    },
  };
}

type Page = { rows: OFChatItem[]; hasMore: boolean };
type Infinite = { pages: Page[]; pageParams: unknown[] };
const infinite = (rows: OFChatItem[]): Infinite => ({
  pages: [{ rows, hasMore: false }],
  pageParams: [undefined],
});

const KEY_UNFILTERED = ["chats", "all", ACCT, null, null, null, 30] as const;
const KEY_FILTERED_PRESENT = ["chats", "all", ACCT, "unread", null, null, 30] as const;
const KEY_FILTERED_ABSENT = ["chats", "all", ACCT, "ppv", null, null, 30] as const;

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

type Handle = Parameters<typeof useSendMessage>[0]["hookHandle"];
function stubHandle(): Handle {
  return {
    appendLocal: vi.fn(),
    reconcileLocal: vi.fn(),
    failLocal: vi.fn(),
    dropLocal: vi.fn(),
  } as unknown as Handle;
}

const rowIds = (inf: Infinite | undefined) =>
  (inf?.pages[0].rows ?? []).map((r) => r.withUser.id);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("useSendMessage chat-list cache scoping", () => {
  it("lifts the row to the top of the UNFILTERED cache but patches filtered caches in place", async () => {
    client.setQueryData(KEY_UNFILTERED, infinite([chatRow(OTHER), chatRow(FAN)]));
    client.setQueryData(KEY_FILTERED_PRESENT, infinite([chatRow(OTHER), chatRow(FAN)]));
    client.setQueryData(KEY_FILTERED_ABSENT, infinite([chatRow(OTHER)]));

    const { result } = renderHook(
      () =>
        useSendMessage({
          accountId: ACCT,
          fanId: FAN,
          fromUserId: 100,
          fromUserName: "you",
          hookHandle: stubHandle(),
        }),
      { wrapper },
    );

    await act(async () => { await result.current.send({ text: "hi there" }); });

    const unfiltered = client.getQueryData<Infinite>(KEY_UNFILTERED)!;
    expect(rowIds(unfiltered)).toEqual([FAN, OTHER]);
    const lifted = unfiltered.pages[0].rows[0];
    expect(lifted.lastMessage?.text).toBe("hi there");
    expect(lifted.hasUnread).toBe(false);
    expect(lifted.unreadMessagesCount).toBe(0);

    const filtered = client.getQueryData<Infinite>(KEY_FILTERED_PRESENT)!;
    expect(rowIds(filtered)).toEqual([OTHER, FAN]);
    const patched = filtered.pages[0].rows.find((r) => r.withUser.id === FAN)!;
    expect(patched.lastMessage?.text).toBe("hi there");
    expect(patched.hasUnread).toBe(false);

    const absent = client.getQueryData<Infinite>(KEY_FILTERED_ABSENT)!;
    expect(rowIds(absent)).toEqual([OTHER]);
    expect(absent.pages[0].rows[0].lastMessage?.text).toBe("old");
  });

  it("does not bleed the patch into another account's chat-list cache", async () => {
    const KEY_OTHER_ACCT = ["chats", "all", "acct2", null, null, null, 30] as const;
    const otherRow: OFChatItem = { ...chatRow(FAN), __accountId: "acct2" };
    client.setQueryData(KEY_UNFILTERED, infinite([chatRow(FAN)]));
    client.setQueryData(KEY_OTHER_ACCT, infinite([otherRow]));

    const { result } = renderHook(
      () =>
        useSendMessage({
          accountId: ACCT,
          fanId: FAN,
          fromUserId: 100,
          fromUserName: "you",
          hookHandle: stubHandle(),
        }),
      { wrapper },
    );

    await act(async () => { await result.current.send({ text: "scoped" }); });

    expect(
      client.getQueryData<Infinite>(KEY_UNFILTERED)!.pages[0].rows[0].lastMessage?.text,
    ).toBe("scoped");
    expect(
      client.getQueryData<Infinite>(KEY_OTHER_ACCT)!.pages[0].rows[0].lastMessage?.text,
    ).toBe("old");
  });
});

describe("useSendMessage leaves the cached count to the Relay", () => {
  const rosterReads = () => vi.mocked(relay.get).mock.calls.map(([p]) => String(p)).filter((p) => p.includes("roster-counts"));

  it("a send, a failed send and its retry: roster-counts untouched, no roster-counts request", async () => {
    resetRosterCountsModuleState();
    const counts = { counts: { [ACCT]: { unread: 3, owe_reply: 1 } } };
    client.setQueryData(KEY_UNFILTERED, infinite([chatRow(FAN)]));
    client.setQueryData(rosterCountsKey("anon"), counts);
    const { result } = renderHook(
      () => useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: 100, fromUserName: "you", hookHandle: stubHandle() }),
      { wrapper },
    );

    await act(async () => { await result.current.send({ text: "hi" }); });
    vi.mocked(relay.post).mockRejectedValueOnce(new Error("OF said no"));
    let failed = 0;
    await act(async () => { failed = (await result.current.send({ text: "again" }))?.tempId ?? 0; });
    await act(async () => { await result.current.retry(failed); });
    await act(async () => { await Promise.resolve(); });

    expect(client.getQueryData(rosterCountsKey("anon"))).toBe(counts);
    expect(rosterReads()).toEqual([]);
  });
});

describe("useSendMessage scheduled-send failure surfacing", () => {
  it.each([
    ["near-term (our executor queue)", 5 * 60_000],
    ["long-delay (OF's native queue)", 60 * 60_000],
  ])("rejects when the %s enqueue fails", async (_label, delayMs) => {
    const { relay } = await import("@/lib/relay");
    (relay.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("Fansly scheduled sends support text and GIFs for now"),
    );

    const { result } = renderHook(
      () =>
        useSendMessage({
          accountId: ACCT,
          fanId: FAN,
          fromUserId: 100,
          fromUserName: "you",
          hookHandle: stubHandle(),
        }),
      { wrapper },
    );

    await expect(
      act(async () => {
        await result.current.send({
          text: "unlock me",
          price: 20,
          scheduledAt: new Date(Date.now() + delayMs).toISOString(),
        });
      }),
    ).rejects.toThrow(/Fansly scheduled sends/);
  });

  it("still resolves when the enqueue succeeds", async () => {
    const { result } = renderHook(
      () =>
        useSendMessage({
          accountId: ACCT,
          fanId: FAN,
          fromUserId: 100,
          fromUserName: "you",
          hookHandle: stubHandle(),
        }),
      { wrapper },
    );

    await expect(
      act(async () => {
        await result.current.send({
          text: "in a bit",
          scheduledAt: new Date(Date.now() + 5 * 60_000).toISOString(),
        });
      }),
    ).resolves.toBeUndefined();
  });
});
