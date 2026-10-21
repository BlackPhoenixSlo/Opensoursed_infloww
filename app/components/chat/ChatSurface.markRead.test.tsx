/**
 * ChatSurface with markRead="afterFirstSend" (`markRead="afterFirstSend"` and the send callbacks):
 * opening a chat sends no read marker and no OF "seen"; the first send that
 * reaches OF sends both (OF's only while it shows the chat unread), once; a
 * scheduled or failed send sends neither. Every send reports its start, then
 * how it ended. Messages Pro's default still marks the chat read on open.
 *
 * The relay is mocked by URL (the Composer's Seam 1 harness); the session
 * contexts are stubbed as `ChatHeader.test.tsx` stubs them. Fixture
 * identifiers are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);
// jsdom has no EventSource.
vi.mock("@/lib/events", async (orig) => ({
  ...(await orig<typeof import("@/lib/events")>()),
  eventBus: { isConnected: () => false, isPaused: () => false, onStateChange: () => () => {}, on: () => () => {} },
}));
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: () => true }));
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

import { observerStub, pickSendAt, relayPost, resetComposerHarness, routeRelay } from "./composerTestHarness";
import type { OFChatItem } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { ChatSurface } from "./ChatSurface";

const ACCT = "100000001";
const FAN = 200000001;
const CHAT = {
  withUser: { id: FAN, name: "Fixture Fan One", username: "fixturefanone", avatar: null },
  hasUnread: true, unreadMessagesCount: 1, isOnline: false,
  canSendMessage: true, canNotSendReason: null,
} as unknown as OFChatItem;
const LOCAL_READ = `/admin/messages/${ACCT}/${FAN}/mark-read`;
const OF_READ = `/api/of/v2/chats/${FAN}/mark-as-read`;
const SEND = `/api/of/v2/chats/${FAN}/messages`;

const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts') as HTMLTextAreaElement;
const readPosts = () => relayPost.mock.calls.map(([p]) => p).filter((p) => p === LOCAL_READ || p === OF_READ);
const sendPosts = () => relayPost.mock.calls.filter(([p]) => p === SEND);

beforeEach(() => {
  resetComposerHarness();
  vi.stubGlobal("IntersectionObserver", observerStub);
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn(),
  }));
  relayPost.mockImplementation((path: string) =>
    Promise.resolve(path === SEND ? { id: 777, text: "sent", createdAt: new Date().toISOString() } : {}));
});
afterEach(() => {
  cleanup();
  relayPost.mockReset();
  relayPost.mockImplementation(() => Promise.resolve({}));
  vi.unstubAllGlobals();
});

function renderFocusSurface() {
  const log: string[] = [];
  const onSendStart = vi.fn(() => { log.push("start"); });
  const onSendSettled = vi.fn((s: string) => { log.push(s); });
  renderWithProviders(
    <ChatSurface
      accountId={ACCT} fanId={FAN} chat={CHAT} insightsOpenAtStart={false}
      markRead="afterFirstSend" onSendStart={onSendStart} onSendSettled={onSendSettled}
    />,
  );
  return { log };
}

describe('ChatSurface with markRead="afterFirstSend": read markers and send callbacks', () => {
  it("opening sends no read marker; the first sent message sends both, once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const { log } = renderFocusSurface();
      await screen.findByPlaceholderText('Press "/" + keyword to quickly search scripts');
      expect(readPosts()).toEqual([]);

      await user.type(textbox(), "hey{Enter}");
      await waitFor(() => expect(log).toEqual(["start", "sent"]));
      await waitFor(() => expect(readPosts().sort()).toEqual([OF_READ, LOCAL_READ].sort()));

      vi.advanceTimersByTime(3000);
      await user.type(textbox(), "again{Enter}");
      await waitFor(() => expect(log).toEqual(["start", "sent", "start", "sent"]));
      expect(readPosts()).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed send reports failed and marks nothing read", async () => {
    relayPost.mockImplementation((path: string) =>
      path === SEND ? Promise.reject(new Error("OF said no")) : Promise.resolve({}));
    const user = userEvent.setup();
    const { log } = renderFocusSurface();
    await user.type(textbox(), "hey{Enter}");
    await waitFor(() => expect(log).toEqual(["start", "failed"]));
    expect(readPosts()).toEqual([]);
  });

  it("a scheduled send reports scheduled and marks nothing read", async () => {
    const user = userEvent.setup();
    const { log } = renderFocusSurface();
    await user.type(textbox(), "later");
    await pickSendAt(user, 5);
    await user.type(textbox(), "{Enter}");
    await waitFor(() => expect(log).toEqual(["start", "scheduled"]));
    expect(relayPost.mock.calls.some(([p]) => p === "/api/of/v2/scheduled-sends")).toBe(true);
    expect(sendPosts()).toEqual([]);
    expect(readPosts()).toEqual([]);
  });

  it("Messages Pro's default marks the chat read on open", async () => {
    renderWithProviders(
      <ChatSurface accountId={ACCT} fanId={FAN} chat={CHAT} insightsOpenAtStart={false} />,
    );
    await waitFor(() => expect(readPosts().sort()).toEqual([OF_READ, LOCAL_READ].sort()));
  });
});

describe("ChatSurface: the local seed", () => {
  it("is not a read: the thread keeps its read time (none yet), so a reopen inside the fresh window still reads OF", async () => {
    routeRelay(`/admin/messages/${ACCT}/${FAN}?`, () => ({
      messages: [{
        account_id: ACCT, fan_id: FAN, message_id: 501, direction: "in", sender_name: "f", body: "from the mirror",
        media_count: 0, price_cents: null, is_tip: false, is_paid: null, is_unsent: false, purchased_at: null,
        created_at: new Date().toISOString(),
      }],
      limit: 30, next_before_id: null,
    }));
    routeRelay(`/api/of/v2/chats/${FAN}/messages?`, () => new Promise(() => {})); // OF's read, still on its way
    const { queryClient } = renderWithProviders(
      <ChatSurface accountId={ACCT} fanId={FAN} chat={CHAT} insightsOpenAtStart={false} markRead="afterFirstSend" />,
    );
    expect(await screen.findByText("from the mirror")).toBeInTheDocument();
    expect(queryClient.getQueryState(["messages", ACCT, FAN])?.dataUpdatedAt).toBe(0);
  });
});
