import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { relayGet, relayPost, scope } = vi.hoisted(() => ({
  relayGet: vi.fn(), relayPost: vi.fn(), scope: { accountId: "1" as string | null },
}));
vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: {
    get: (...a: unknown[]) => relayGet(...a),
    post: (...a: unknown[]) => relayPost(...a),
    delete: vi.fn(), put: vi.fn(), patch: vi.fn(),
  },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/contexts/ScopeContext", () => ({
  useScope: () => ({ accountId: scope.accountId, scope: { kind: "model", accountId: scope.accountId } }),
  useEventScopeOverride: () => {},
  useDropWatcherScope: () => {},
}));
vi.mock("@/hooks/useAccounts", async (original) => ({
  ...await original<typeof import("@/hooks/useAccounts")>(),
  useAccounts: () => ({ data: { accounts: [{ id: scope.accountId }] } }),
  usePlatformAccounts: () => [{ id: scope.accountId }],
}));
vi.mock("@/contexts/UserContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/UserContext")>();
  const value = { user: { user_id: "u-owner", username: "owner" }, loading: false, logout: vi.fn() };
  return { ...actual, useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/ChatterContext")>();
  const value = { chatter: null, loading: false, logout: vi.fn() };
  return { ...actual, useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/EmployeeContext")>();
  const value = { current: null, hydrated: true, pickedId: null, clear: vi.fn() };
  return { ...actual, useEmployee: () => value };
});

import { chatsQueryKey } from "@/hooks/useChatList";
import { CHATS } from "./ofMirrorData.fixtures";
import { useOfData } from "./ofMirrorData";
import { NOTIFICATION_COUNTS, NOTIFICATIONS } from "./ofMirrorFeedsNotifications";
import { NOTIF_READ_PATH } from "@/hooks/useOfNotifCount";

const PAGE = (p: string) => `/of-mirror/pages/${p}.html`;
let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const frame = { current: null };
const writes = () => relayPost.mock.calls.filter(([p]) => p === NOTIF_READ_PATH);
const countReads = () => relayGet.mock.calls.filter(([p]) => p === NOTIFICATION_COUNTS);
const flush = () => new Promise((r) => setTimeout(r, 30));

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  scope.accountId = "1";
  relayGet.mockReset().mockImplementation(async (path: string) =>
    path === NOTIFICATION_COUNTS ? { all: 4 } : path.startsWith("/api/of/v2/users/notifications?") ? { list: [] } : {});
  relayPost.mockReset().mockResolvedValue({ success: true, counters: { all: 0 } });
});
afterEach(() => cleanup());

describe("OF Manager notifications page: OF's mark-read", () => {
  it("the All tab sends exactly one mark-read per open per model, after its list answers, never per render or on a timer, then re-reads its tab counts", async () => {
    const { rerender, unmount } = renderHook(({ src }) => useOfData(frame, src), { wrapper, initialProps: { src: PAGE("notifications/index") } });
    await waitFor(() => expect(writes()).toEqual([[NOTIF_READ_PATH, undefined, { accountId: "1" }]]));
    const listAt = relayGet.mock.invocationCallOrder[relayGet.mock.calls.findIndex(([p]) => p === NOTIFICATIONS["notifications/index"])];
    expect(listAt).toBeLessThan(relayPost.mock.invocationCallOrder[0]);
    await waitFor(() => expect(countReads()).toHaveLength(2));
    for (let i = 0; i < 5; i++) rerender({ src: PAGE("notifications/index") });
    await flush();
    expect(writes()).toHaveLength(1);

    scope.accountId = "2";
    rerender({ src: PAGE("notifications/index") });
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1][2]).toEqual({ accountId: "2" });
    unmount();

    renderHook(() => useOfData(frame, PAGE("notifications/index")), { wrapper });
    await waitFor(() => expect(writes()).toHaveLength(3));
    await flush();
    expect(writes()).toHaveLength(3);
  });

  it("another tab, or a failed write, re-reads nothing; a list still loading sends nothing yet", async () => {
    renderHook(() => useOfData(frame, PAGE("notifications/tip")), { wrapper });
    await waitFor(() => expect(countReads()).toHaveLength(1));
    await flush();
    expect(writes()).toHaveLength(0);
    cleanup();

    relayPost.mockRejectedValue(new Error("upstream 502"));
    renderHook(() => useOfData(frame, PAGE("notifications/index")), { wrapper: ({ children }) => <QueryClientProvider client={(client = new QueryClient())}>{children}</QueryClientProvider> });
    await waitFor(() => expect(writes()).toHaveLength(1));
    await flush();
    expect(countReads()).toHaveLength(2);
    cleanup();

    relayPost.mockClear();
    relayGet.mockImplementation((path: string) =>
      path.startsWith("/api/of/v2/users/notifications?") ? new Promise(() => {}) : Promise.resolve({}));
    renderHook(() => useOfData(frame, PAGE("notifications/index")), { wrapper: ({ children }) => <QueryClientProvider client={(client = new QueryClient())}>{children}</QueryClientProvider> });
    await flush();
    expect(writes()).toHaveLength(0);
  });
});

describe("OF Manager chat paging", () => {
  it.each(["pointerdown", "wheel"])("loads one deep page per %s gesture across page renders", async (type) => {
    const iframe = document.body.appendChild(document.createElement("iframe"));
    const doc = iframe.contentDocument!;
    doc.body.innerHTML = '<div class="b-chats__scroller"><div class="b-chats__item"></div></div>';
    const box = doc.querySelector<HTMLElement>(".b-chats__scroller")!;
    box.checkVisibility = () => true;
    const key = chatsQueryKey("model", "1", { limit: 20 });
    client.setQueryData(key, {
      pages: [0, 20, 40, 60].map((offset) => ({ rows: [{ ...CHATS[0], withUser: { id: offset + 1 } }],
        moreAccounts: ["1"], hasMore: true, scanned: 20 })),
      pageParams: [0, 20, 40, 60],
    });
    const reads = () => relayGet.mock.calls.filter(([p]) => String(p).startsWith("/api/of/v2/chats?"));
    relayGet.mockImplementation(async (path: string) => {
      const offset = Number(new URLSearchParams(path.split("?")[1]).get("offset"));
      return { list: [{ ...CHATS[0], withUser: { id: offset + 1 } }], hasMore: true };
    });
    const send = () => box.dispatchEvent(type === "wheel"
      ? new WheelEvent("wheel", { deltaY: 10, bubbles: true })
      : new MouseEvent("pointerdown", { bubbles: true }));
    let now = 1000;
    const clock = vi.spyOn(performance, "now").mockImplementation(() => now);
    try {
      renderHook(() => useOfData({ current: iframe }, PAGE("messages/index")), { wrapper });
      act(() => { iframe.dispatchEvent(new Event("load")); });
      await waitFor(() => expect(box.querySelectorAll("[data-oi-chat]")).toHaveLength(4));
      expect(reads()).toHaveLength(0);
      act(() => {
        send();
        if (type === "pointerdown") box.dispatchEvent(new Event("scroll"));
      });
      await waitFor(() => expect(box.querySelectorAll("[data-oi-chat]")).toHaveLength(5));
      expect(reads()).toHaveLength(1);
      expect(reads()[0][1]).toMatchObject({ caller: "scroll", intent: "explicit" });
      if (type === "wheel") {
        now += 150;
        act(() => { send(); });
        expect(reads()).toHaveLength(1);
      }
    } finally {
      cleanup();
      iframe.remove();
      clock.mockRestore();
    }
  });
});
