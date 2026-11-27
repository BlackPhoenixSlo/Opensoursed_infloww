import { sendKey, withRetainedOp } from "@/lib/opId";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useSendMessage } from "@/hooks/useSendMessage";
import { rosterCountsKey, resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import { relay, RelayError, type OFChatItem, type VaultMedia } from "@/lib/relay";
import { sendStash } from "@/lib/sendStash";
import { UNCERTAIN_REASON } from "@/lib/sendFailure";

vi.mock("@/lib/relay", () => ({
  relay: { get: vi.fn(), post: vi.fn(() => Promise.resolve({ id: 999, media: [] })) },
  RelayError: class RelayError extends Error {
    constructor(public status = 0, public body: unknown = null) { super(`relay ${status}`); }
  },
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

describe("useSendMessage sends one X-Op-Id per action", () => {
  const msgPosts = () => vi.mocked(relay.post).mock.calls.filter(([p]) => String(p) === `/api/of/v2/chats/${FAN}/messages`);
  const opIds = () => msgPosts().map(([, , ctx]) => ctx?.opId);
  const render = (handle = stubHandle()) => renderHook(
    () => useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: 100, fromUserName: "you", hookHandle: handle }),
    { wrapper },
  ).result;

  it("mints the id before the upload lands and the POST after it carries that id", async () => {
    let land!: (m: VaultMedia[]) => void;
    const done = new Promise<VaultMedia[]>((r) => { land = r; });
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    const result = render();
    let tempId = 0;
    await act(async () => {
      tempId = (await result.current.send({ text: "pic", uploads: [{ file, previewUrl: null, done, cancel: () => {} }] }))!.tempId;
    });
    const minted = sendStash.get(tempId)?.opId;
    expect(minted).toMatch(/^[0-9a-f-]{36}$/);
    expect(msgPosts()).toHaveLength(0);
    await act(async () => { land([{ id: 5, type: "photo", files: null }]); await done; });
    await act(async () => { await Promise.resolve(); });
    expect(opIds()).toEqual([minted]);
  });

  it("two sends carry two different ids", async () => {
    const result = render();
    await act(async () => { await result.current.send({ text: "one" }); });
    await act(async () => { await result.current.send({ text: "two" }); });
    const [a, b] = opIds();
    expect(a).toBeTruthy();
    expect(b).toBeTruthy();
    expect(a).not.toBe(b);
  });

  it("bubble Retry after a definite failure resubmits the same id", async () => {
    const result = render();
    vi.mocked(relay.post).mockRejectedValueOnce(new RelayError(400, { detail: { message: "no" } }));
    let tempId = 0;
    await act(async () => { tempId = (await result.current.send({ text: "again" }))!.tempId; });
    await act(async () => { await result.current.retry(tempId); });
    const [first, second] = opIds();
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  it.each([
    ["a 502 the relay marked uncertain", () => new RelayError(502, { detail: { upstream_status: 502, op_state: "uncertain" } })],
    ["a resubmit the relay answers op_uncertain", () => new RelayError(409, { detail: { error: "op_uncertain", op_id: "x" } })],
  ])("%s: one POST, shown as uncertain, never re-sent", async (_label, err) => {
    vi.useFakeTimers();
    try {
      const handle = stubHandle();
      const result = render(handle);
      vi.mocked(relay.post).mockRejectedValueOnce(err());
      let failure: unknown;
      await act(async () => { failure = (await result.current.send({ text: "maybe" }))!.failure; });
      expect(failure).toEqual({ reason: UNCERTAIN_REASON, uncertain: true });
      expect(handle.failLocal).toHaveBeenCalledWith(expect.any(Number), expect.objectContaining({ uncertain: true }));
      await act(async () => { await vi.runAllTimersAsync(); });
      expect(msgPosts()).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

it("clears a reconciled optimistic bubble without inventing a receipt", async () => {
  const hookHandle = stubHandle();
  const { result } = renderHook(
    () => useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: 100, fromUserName: "you", hookHandle }),
    { wrapper },
  );
  vi.mocked(relay.post).mockResolvedValueOnce({ status: "reconciled" });
  await act(async () => { await result.current.send({ text: "already delivered" }); });
  expect(hookHandle.dropLocal).toHaveBeenCalledOnce();
  expect(hookHandle.reconcileLocal).not.toHaveBeenCalled();
  expect(hookHandle.failLocal).not.toHaveBeenCalled();
});

describe.each([
  ["native", `/api/of/v2/chats/${FAN}/messages/scheduled`, 60],
  ["near-term", "/api/of/v2/scheduled-sends", 5],
] as const)("%s schedule op ids", (_kind, path, delay) => {
  const schedPosts = () => vi.mocked(relay.post).mock.calls
    .filter(([p]) => p === path).map(([, , ctx]) => ctx?.opId);
  const at = new Date(Date.now() + delay * 60_000).toISOString();

  it("a resubmit of the same schedule after a failure reuses the op; the next schedule gets a new one", async () => {
    const { result } = renderHook(
      () => useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: 100, fromUserName: "you", hookHandle: stubHandle() }),
      { wrapper },
    );
    vi.mocked(relay.post).mockRejectedValueOnce(new Error("timeout"));
    await expect(act(() => result.current.send({ text: "later", scheduledAt: at }))).rejects.toThrow();
    await act(async () => { await result.current.send({ text: "later", scheduledAt: at }); });
    await act(async () => { await result.current.send({ text: "later", scheduledAt: at }); });
    const [a, b, c] = schedPosts();
    expect(a).toMatch(/^[0-9a-f-]{36}$/);
    expect(b).toBe(a);
    expect(c).toBeTruthy();
    expect(c).not.toBe(a);
  });
});


it("retries a lost native schedule response on the native route after the cutoff", async () => {
  const now = Date.now();
  const clock = vi.spyOn(Date, "now").mockReturnValue(now);
  try {
    const { result } = renderHook(
      () => useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: 100, fromUserName: "you", hookHandle: stubHandle() }),
      { wrapper },
    );
    const draft = { text: "later", scheduledAt: new Date(now + 16 * 60_000).toISOString() };
    vi.mocked(relay.post).mockRejectedValueOnce(new Error("timeout"));
    await expect(act(() => result.current.send(draft))).rejects.toThrow("timeout");
    clock.mockReturnValue(now + 2 * 60_000);
    await act(async () => { await result.current.send(draft); });
    const [first, retry] = vi.mocked(relay.post).mock.calls;
    expect(first[0]).toBe(`/api/of/v2/chats/${FAN}/messages/scheduled`);
    expect(retry).toEqual(first);
  } finally {
    clock.mockRestore();
  }
});

it("retains the mirror send op when another chat sends before retry", async () => {
  const ops = { current: null };
  const pathA = "/api/of/v2/chats/1/messages";
  const pathB = "/api/of/v2/chats/2/messages";
  const body = { text: "same draft" };
  const submit = (path: string) => withRetainedOp(ops, sendKey(ACCT, path, body), (opId) =>
    relay.post(path, body, { accountId: ACCT, opId }));
  vi.mocked(relay.post).mockRejectedValueOnce(new Error("timeout"));
  await expect(submit(pathA)).rejects.toThrow("timeout");
  await submit(pathB);
  await submit(pathA);
  const [first, other, retry] = vi.mocked(relay.post).mock.calls;
  expect(other[2]?.opId).not.toBe(first[2]?.opId);
  expect(retry).toEqual(first);
});
