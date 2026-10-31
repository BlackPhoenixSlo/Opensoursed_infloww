/**
 * useToggleMessageFlag — the like/pin toggle body.
 *
 * A wrong id here likes or pins a DIFFERENT message, so: only a real message
 * id reaches the wire, the flip is optimistic and reverts on failure, and each
 * wrapper's request (method, URL, body, opts) and invalidation are pinned so
 * they cannot drift apart while sharing one body.
 */
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useLikeMessage } from "@/hooks/useLikeMessage";
import { useTogglePinMessage } from "@/hooks/useTogglePinMessage";
import { useToggleMessageFlag, type MessageFlagSpec } from "@/hooks/useToggleMessageFlag";
import type { OFMessage } from "@/lib/relay";

vi.mock("@/lib/relay", () => ({
  relay: { post: vi.fn(), delete: vi.fn() },
}));

import { relay } from "@/lib/relay";
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

const ACCT = "acct1";
const FAN = 42;
const KEY = ["messages", ACCT, FAN] as const;
// A Fansly snowflake past 2^53: Number() would round it to another message.
const SNOWFLAKE = "900715634200489987";

const SPEC: MessageFlagSpec = { field: "isLiked", label: "test", path: (id) => `/flag/${id}` };

function msg(id: number | string, flags: Partial<OFMessage> = {}): OFMessage {
  return { id, text: "", fromUser: { id: 7 }, createdAt: "2026-08-27T11:03:04.000Z", media: [], ...flags } as unknown as OFMessage;
}

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const cached = () => client.getQueryData<OFMessage[]>(KEY) ?? [];
const flagOf = (id: number | string, field: "isLiked" | "isPinned") =>
  cached().find((m) => String(m.id) === String(id))?.[field];

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  relayPost.mockReset();
  relayDelete.mockReset();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("useToggleMessageFlag", () => {
  it.each([
    ["number id", 10977996348669],
    ["snowflake string", SNOWFLAKE],
  ])("valid %s → request sent with the exact id + optimistic flip", async (_name, id) => {
    client.setQueryData(KEY, [msg(id)]);
    let resolve!: () => void;
    relayPost.mockReturnValue(new Promise<void>((r) => { resolve = r; }));

    const { result } = renderHook(() => useToggleMessageFlag(ACCT, FAN, SPEC), { wrapper });
    let done!: Promise<void>;
    act(() => { done = result.current.toggle(msg(id)); });
    // Flipped before the wire answers.
    expect(flagOf(id, "isLiked")).toBe(true);
    expect(relayPost).toHaveBeenCalledWith(`/flag/${String(id)}`, undefined, { accountId: ACCT });
    await act(async () => { resolve(); await done; });
    expect(flagOf(id, "isLiked")).toBe(true);
  });

  it.each(["0", "000", "abc", "", "-1", "1.5", "1e21", -5, 0, 2 ** 53])(
    "invalid id %j → no request, no flip",
    async (id) => {
      client.setQueryData(KEY, [msg(id)]);
      const { result } = renderHook(() => useToggleMessageFlag(ACCT, FAN, SPEC), { wrapper });
      await act(async () => { await result.current.toggle(msg(id)); });
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();
      expect(flagOf(id, "isLiked")).toBeUndefined();
    },
  );

  it("no account or fan → no request", async () => {
    for (const [a, f] of [[null, FAN], [ACCT, null]] as const) {
      const { result } = renderHook(() => useToggleMessageFlag(a, f, SPEC), { wrapper });
      await act(async () => { await result.current.toggle(msg(5)); });
    }
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("error → the optimistic flip is rolled back, nothing invalidated", async () => {
    client.setQueryData(KEY, [msg(5, { isLiked: true })]);
    relayDelete.mockRejectedValue(new Error("404"));
    const inval = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useToggleMessageFlag(ACCT, FAN, { ...SPEC, invalidates: () => ["x"] }), { wrapper });
    await act(async () => { await result.current.toggle(msg(5, { isLiked: true })); });
    expect(relayDelete).toHaveBeenCalledWith("/flag/5", { accountId: ACCT });
    expect(flagOf(5, "isLiked")).toBe(true);
    expect(inval).not.toHaveBeenCalled();
  });
});

describe("wrapper request shapes", () => {
  it("useLikeMessage: POST/DELETE /messages/{id}/like, flips isLiked, no extra invalidation", async () => {
    client.setQueryData(KEY, [msg(SNOWFLAKE)]);
    relayPost.mockResolvedValue(undefined);
    relayDelete.mockResolvedValue(undefined);
    const inval = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useLikeMessage(ACCT, FAN), { wrapper });

    await act(async () => { await result.current.toggle(msg(SNOWFLAKE)); });
    expect(relayPost.mock.calls).toEqual([[`/api/of/v2/messages/${SNOWFLAKE}/like`, undefined, { accountId: ACCT }]]);
    expect(flagOf(SNOWFLAKE, "isLiked")).toBe(true);

    await act(async () => { await result.current.toggle(msg(SNOWFLAKE, { isLiked: true })); });
    expect(relayDelete.mock.calls).toEqual([[`/api/of/v2/messages/${SNOWFLAKE}/like`, { accountId: ACCT }]]);
    expect(flagOf(SNOWFLAKE, "isLiked")).toBe(false);
    expect(inval).not.toHaveBeenCalled();
  });

  it("useTogglePinMessage: POST/DELETE /messages/{id}/pin/user/{fan}, flips isPinned, invalidates chat-pinned", async () => {
    client.setQueryData(KEY, [msg(SNOWFLAKE)]);
    relayPost.mockResolvedValue(undefined);
    relayDelete.mockResolvedValue(undefined);
    const inval = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useTogglePinMessage(ACCT, FAN), { wrapper });

    await act(async () => { await result.current.toggle(msg(SNOWFLAKE)); });
    expect(relayPost.mock.calls).toEqual([[`/api/of/v2/messages/${SNOWFLAKE}/pin/user/${FAN}`, undefined, { accountId: ACCT }]]);
    expect(flagOf(SNOWFLAKE, "isPinned")).toBe(true);
    expect(flagOf(SNOWFLAKE, "isLiked")).toBeUndefined();

    await act(async () => { await result.current.toggle(msg(SNOWFLAKE, { isPinned: true })); });
    expect(relayDelete.mock.calls).toEqual([[`/api/of/v2/messages/${SNOWFLAKE}/pin/user/${FAN}`, { accountId: ACCT }]]);
    expect(flagOf(SNOWFLAKE, "isPinned")).toBe(false);
    expect(inval.mock.calls).toEqual([
      [{ queryKey: ["chat-pinned", ACCT, String(FAN)] }],
      [{ queryKey: ["chat-pinned", ACCT, String(FAN)] }],
    ]);
  });

  it("useTogglePinMessage: a failed pin reverts and does not invalidate", async () => {
    client.setQueryData(KEY, [msg(5)]);
    relayPost.mockRejectedValue(new Error("500"));
    const inval = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useTogglePinMessage(ACCT, FAN), { wrapper });
    await act(async () => { await result.current.toggle(msg(5)); });
    expect(flagOf(5, "isPinned")).toBe(false);
    expect(inval).not.toHaveBeenCalled();
  });
});
