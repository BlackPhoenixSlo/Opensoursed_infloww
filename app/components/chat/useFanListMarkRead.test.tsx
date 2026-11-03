/**
 * useFanListMarkRead — "Mark all as read" and its per-chat loop, against a
 * mocked relay. Fixture identifiers are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { isUnreadChat } from "@/lib/chatUnread";
import { useFanListMarkRead } from "./useFanListMarkRead";

vi.mock("@/lib/relay", () => ({ relay: { post: vi.fn() } }));
const post = vi.mocked(relay.post);

const A = "100000001";
const B = "100000002";
const unread = (accountId: string, fanId: number) => ({
  __accountId: accountId,
  withUser: { id: fanId, name: `Fan ${fanId}` },
  lastMessage: { fromUser: { id: fanId }, createdAt: "2026-11-02T10:00:00Z" },
  hasUnread: true,
  unreadMessagesCount: 1,
}) as unknown as OFChatItem;
// All Models: two Creators, two unread chats on A and one on B.
const ROWS = [unread(A, 200000001), unread(B, 200000002), unread(A, 200000003)];
// One Creator's (A's) unread chats.
const ROWS_A = [ROWS[0], ROWS[2]];
const LIST_KEY = ["chats", "all", `${A},${B}`, null, null, null, 25];

function setup(opts: { wholeCreator?: string | null; rows?: OFChatItem[] } = {}) {
  const rows = opts.rows ?? ROWS;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(LIST_KEY, { pages: [{ rows, hasMore: false }], pageParams: [0] });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useFanListMarkRead({
    markable: rows, wholeCreator: opts.wholeCreator ?? null,
  }), { wrapper });
  /** The cached rows still unread, as "accountId:fanId". */
  const stillUnread = () => (qc.getQueryData(LIST_KEY) as { pages: { rows: OFChatItem[] }[] }).pages[0].rows
    .filter(isUnreadChat).map((c) => `${c.__accountId ?? ""}:${c.withUser.id}`);
  return { ...hook, qc, stillUnread };
}

beforeEach(() => {
  post.mockReset();
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("alert", vi.fn());
  vi.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("useFanListMarkRead", () => {
  it("All Models: mark all as read posts one write per unread chat, on its own Creator (no per-Creator write)", async () => {
    post.mockResolvedValue({});
    const { result, stillUnread } = setup();
    await act(() => result.current.markAllRead());
    expect(confirm).toHaveBeenCalledWith("Mark 3 chats as read?");
    expect(post.mock.calls).toEqual([
      ["/api/of/v2/chats/200000001/mark-as-read", undefined, { accountId: A }],
      ["/api/of/v2/chats/200000002/mark-as-read", undefined, { accountId: B }],
      ["/api/of/v2/chats/200000003/mark-as-read", undefined, { accountId: A }],
    ]);
    expect(stillUnread()).toEqual([]);
    expect(alert).not.toHaveBeenCalled();
  });

  it("markingAll is true from the confirm until the last write answers", async () => {
    const answers: Array<() => void> = [];
    post.mockImplementation(() => new Promise((resolve) => { answers.push(() => resolve({})); }));
    const { result } = setup();
    expect(result.current.markingAll).toBe(false);
    let done!: Promise<void>;
    act(() => { done = result.current.markAllRead(); });
    for (let i = 0; i < 3; i++) {
      await waitFor(() => expect(answers).toHaveLength(i + 1));
      expect(result.current.markingAll).toBe(true);
      await act(async () => { answers[i](); });
    }
    await act(() => done);
    expect(result.current.markingAll).toBe(false);
  });

  it("a Creator whose writes fail keeps its rows unread; the rest are cleared and the miss is reported", async () => {
    post.mockImplementation(async (_path, _body, opts) => {
      if ((opts as { accountId: string }).accountId === B) throw new Error("OF 500");
      return {};
    });
    const { result, stillUnread } = setup();
    await act(() => result.current.markAllRead());
    expect(stillUnread()).toEqual([`${B}:200000002`]);
    expect(alert).toHaveBeenCalledWith("Marked 2 of 3; 1 failed.");
    expect(result.current.markingAll).toBe(false);
  });

  it("one Creator with every unread chat loaded: one OF write marks them all", async () => {
    post.mockResolvedValue({});
    const { result, stillUnread } = setup({ wholeCreator: A, rows: ROWS_A });
    await act(() => result.current.markAllRead());
    expect(post.mock.calls).toEqual([["/api/of/v2/chats/mark-as-read", undefined, { accountId: A }]]);
    expect(stillUnread()).toEqual([]);
    expect(alert).not.toHaveBeenCalled();
  });

  it("one Creator whose one OF write fails: every row stays unread and all of them are reported", async () => {
    post.mockRejectedValue(new Error("OF 500"));
    const { result, stillUnread } = setup({ wholeCreator: A, rows: ROWS_A });
    await act(() => result.current.markAllRead());
    expect(post).toHaveBeenCalledTimes(1);
    expect(stillUnread()).toEqual([`${A}:200000001`, `${A}:200000003`]);
    expect(alert).toHaveBeenCalledWith("Marked 0 of 2; 2 failed.");
    expect(result.current.markingAll).toBe(false);
  });

  it("a row with no Creator is not written and counts as failed; the others are marked", async () => {
    post.mockResolvedValue({});
    const orphan = { ...unread(A, 200000009), __accountId: undefined } as unknown as OFChatItem;
    const { result, stillUnread } = setup({ rows: [ROWS[0], orphan] });
    await act(() => result.current.markAllRead());
    expect(post.mock.calls).toEqual([["/api/of/v2/chats/200000001/mark-as-read", undefined, { accountId: A }]]);
    expect(stillUnread()).toEqual([":200000009"]);
    expect(alert).toHaveBeenCalledWith("Marked 1 of 2; 1 failed.");
  });

  it("cancelled at the confirm: no write", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const { result } = setup();
    await act(() => result.current.markAllRead());
    expect(post).not.toHaveBeenCalled();
    expect(result.current.markingAll).toBe(false);
  });
});
