/**
 * useUnsendMessage — the unsent bubble must not come back on reload.
 *
 * Clicking unsend dropped the row from ["messages", …] and called OF, but the
 * DB-seed cache (useChatMessagesLocal) kept it —
 * and ChatSurface re-hydrates that seed into the thread on every mount. The
 * bubble reappeared as an EMPTY locked shell, since seed rows carry no media
 * and a PPV's mirror body is blank. (The relay flips `messages.is_unsent` on
 * the same DELETE; this is the in-session half of the same fix.)
 */
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { seedKey } from "@/hooks/useChatMessagesLocal";
import { NOT_CONFIRMED, useUnsendMessage } from "@/hooks/useUnsendMessage";
import type { OFMessage } from "@/lib/relay";

vi.mock("@/lib/relay", () => ({
  relay: { delete: vi.fn() },
  RelayError: class RelayError extends Error {},
}));

import { relay } from "@/lib/relay";
const relayDelete = relay.delete as unknown as Mock;

const ACCT = "acct1";
const FAN = 42;
const MID = 10977996348669;
// The seed module owns the key shape; spell it out here and the test would
// keep passing after a rename that broke the real prune.
const SEED_KEY = [...seedKey(ACCT, FAN), 30] as const;

function msg(id: number): OFMessage {
  return {
    id, text: "", fromUser: { id: 7 }, createdAt: "2026-08-27T11:03:04.000Z",
    media: [], price: 200,
  } as unknown as OFMessage;
}

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function seedRows() {
  return { messages: [{ message_id: MID }, { message_id: MID - 1 }], limit: 30, next_before_id: null };
}

beforeEach(() => {
  // gcTime: Infinity — these caches have no observers (we write them with
  // setQueryData), and a 0 gcTime evicts them mid-assertion.
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  relayDelete.mockReset();
});

const seedIds = () =>
  (client.getQueryData<{ messages: { message_id: number }[] }>(SEED_KEY)?.messages ?? [])
    .map((r) => r.message_id);

describe("useUnsendMessage", () => {
  it("drops the row from the DB-seed cache too", async () => {
    client.setQueryData(["messages", ACCT, FAN], [msg(MID - 1), msg(MID)]);
    client.setQueryData(SEED_KEY, seedRows());
    relayDelete.mockResolvedValue({ success: true });

    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    await act(async () => { await result.current.unsendOne(msg(MID)); });

    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id)))
      .toEqual([MID - 1]);
    // Pre-fix this still held MID — ChatSurface's seed hydration painted it
    // back on the next mount as an empty $200 shell.
    expect(seedIds()).toEqual([MID - 1]);
  });

  it("leaves the seed alone when OF refuses (bubble is still live)", async () => {
    client.setQueryData(["messages", ACCT, FAN], [msg(MID)]);
    client.setQueryData(SEED_KEY, seedRows());
    relayDelete.mockRejectedValue(new Error("older than 24h"));

    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    await act(async () => {
      await expect(result.current.unsendOne(msg(MID))).rejects.toThrow();
    });

    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id)))
      .toEqual([MID]);
    expect(seedIds()).toEqual([MID, MID - 1]);
  });

  it.each([
    ["success: false", { success: false }],
    ["{}", {}],
    ["no body", null],
  ])("a 2xx without OF's success: true (%s) throws and keeps the bubble and the seed", async (_, reply) => {
    client.setQueryData(["messages", ACCT, FAN], [msg(MID)]);
    client.setQueryData(SEED_KEY, seedRows());
    relayDelete.mockResolvedValue(reply);

    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    await act(async () => {
      await expect(result.current.unsendOne(msg(MID))).rejects.toThrow(NOT_CONFIRMED);
    });

    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id)))
      .toEqual([MID]);
    expect(seedIds()).toEqual([MID, MID - 1]);
  });

  // W30 W4: restoring the whole snapshot revived B, which OF had unsent meanwhile.
  it("a refused unsend puts back only its own bubble, in place; a concurrent unsend that OF took stays gone", async () => {
    const [A, B, C] = [MID, MID - 1, MID - 2];
    client.setQueryData(["messages", ACCT, FAN], [msg(C), msg(A), msg(B)]);
    let refuseA!: (e: Error) => void;
    relayDelete.mockImplementation((path: string) =>
      path.endsWith(`/${A}`) ? new Promise((_, no) => (refuseA = no)) : Promise.resolve({ success: true }));

    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    await act(async () => {
      const a = result.current.unsendOne(msg(A));
      await result.current.unsendOne(msg(B));
      refuseA(new Error("older than 24h"));
      await expect(a).rejects.toThrow();
    });

    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id)))
      .toEqual([C, A]);
  });

  // W30 final [codex+deepseek]: a refetch mid-DELETE swaps in fresh objects; the re-insert looked its neighbour up by reference.
  it("a refused unsend goes back before its neighbour even after a refetch replaced the cached objects", async () => {
    const [A, B, C, D] = [1, 2, 3, 4];
    client.setQueryData(["messages", ACCT, FAN], [msg(A), msg(B), msg(C), msg(D)]);
    let refuse!: (e: Error) => void;
    relayDelete.mockImplementation(() => new Promise((_, no) => (refuse = no)));

    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    await act(async () => {
      const b = result.current.unsendOne(msg(B));
      client.setQueryData(["messages", ACCT, FAN], [msg(A), msg(C), msg(D)]);   // the refetch: new objects
      refuse(new Error("older than 24h"));
      await expect(b).rejects.toThrow();
    });

    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id)))
      .toEqual([A, B, C, D]);
  });

  // W30 S1: only the mirror menu guarded the DELETE; ChatSurface and UnsendMessageButton (each its own hook) sent another.
  it("a second hook instance on the same QueryClient shares the DELETE in flight (and its refusal); another QueryClient sends its own", async () => {
    client.setQueryData(["messages", ACCT, FAN], [msg(MID)]);
    const answers: ((r: unknown) => void)[] = [];
    relayDelete.mockImplementation(() => new Promise((r) => answers.push(r)));
    const other = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const a = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper }).result;
    const b = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper }).result;
    const c = renderHook(() => useUnsendMessage(ACCT, FAN), {
      wrapper: ({ children }) => <QueryClientProvider client={other}>{children}</QueryClientProvider>,
    }).result;
    await act(async () => {
      const one = a.current.unsendOne(msg(MID));
      const two = b.current.unsendOne({ id: String(MID) } as unknown as OFMessage);
      expect(relayDelete).toHaveBeenCalledTimes(1);
      const three = c.current.unsendOne(msg(MID));
      expect(relayDelete).toHaveBeenCalledTimes(2);
      answers[0]({ success: false });
      answers[1]({ success: true });
      await expect(one).rejects.toThrow(NOT_CONFIRMED);
      await expect(two).rejects.toThrow(NOT_CONFIRMED);
      await expect(three).resolves.toEqual({ success: true });
    });
  });

  it.each(["0", "000", "abc", "", "-1", -1, 0, 2 ** 53])("never DELETEs an invalid id %j", async (id) => {
    client.setQueryData(["messages", ACCT, FAN], [msg(MID)]);
    const { result } = renderHook(() => useUnsendMessage(ACCT, FAN), { wrapper });
    let resp: unknown;
    await act(async () => { resp = await result.current.unsendOne({ id } as unknown as OFMessage); });
    expect(resp).toBeNull();
    expect(relayDelete).not.toHaveBeenCalled();
    expect(client.getQueryData<OFMessage[]>(["messages", ACCT, FAN])?.map((m) => Number(m.id))).toEqual([MID]);
  });
});
