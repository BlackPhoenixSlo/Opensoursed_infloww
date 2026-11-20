/**
 * The OF Manager notifications page marks the model's notifications read the way OF web does: one
 * `POST /users/notifications/read` when the All tab opens (after its list answers), then the page's own tab counts
 * are re-read. Driven through the real useOfData with the Relay mocked at its module boundary.
 */
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
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
// One model in scope (`scope.accountId`), as the OF Manager page has it.
vi.mock("@/contexts/ScopeContext", () => ({
  useScope: () => ({ accountId: scope.accountId, scope: { kind: "model", accountId: scope.accountId } }),
  useEventScopeOverride: () => {},
  useDropWatcherScope: () => {},
}));
// An owner signed in (as ChatHeader.test.tsx stubs it): the page's chat-list hook reads the accounts.
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
    await waitFor(() => expect(countReads()).toHaveLength(2)); // the page's counts, re-read after the write
    for (let i = 0; i < 5; i++) rerender({ src: PAGE("notifications/index") });
    await flush();
    expect(writes()).toHaveLength(1);

    // Another model on the same page: its own one write.
    scope.accountId = "2";
    rerender({ src: PAGE("notifications/index") });
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1][2]).toEqual({ accountId: "2" });
    unmount();

    // A new open of the page: one more.
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
    expect(countReads()).toHaveLength(2); // the first page's one read, this page's one read: no re-read
    cleanup();

    relayPost.mockClear();
    relayGet.mockImplementation((path: string) =>
      path.startsWith("/api/of/v2/users/notifications?") ? new Promise(() => {}) : Promise.resolve({}));
    renderHook(() => useOfData(frame, PAGE("notifications/index")), { wrapper: ({ children }) => <QueryClientProvider client={(client = new QueryClient())}>{children}</QueryClientProvider> });
    await flush();
    expect(writes()).toHaveLength(0);
  });
});
