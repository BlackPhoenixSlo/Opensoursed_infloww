/**
 * FanListBulkBar — the Fan List's select mode bar (W4 4.4).
 *
 * The relay client is mocked at its module boundary, as ChatHeader.test.tsx
 * mocks it, and the lists read is stubbed. Fixture identifiers are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayPost, relayDelete } = vi.hoisted(() => ({ relayPost: vi.fn(), relayDelete: vi.fn() }));

vi.mock("@/lib/relay", () => ({
  relay: {
    get: vi.fn(),
    post: (...args: unknown[]) => relayPost(...args),
    delete: (...args: unknown[]) => relayDelete(...args),
  },
}));

/** Function permissions the role denies (`useActionAllowed`); none unless a case adds one. */
const denied = vi.hoisted(() => new Set<string>());
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: (action: string) => !denied.has(action) }));

vi.mock("@/hooks/useChatFolders", () => ({
  useAllChatFolders: () => ({
    data: [
      { id: 900000001, name: "Fixture VIPs", canAddUsers: true },
      { id: 900000002, name: "Fixture Built-in", canAddUsers: false },
    ],
    isLoading: false, isError: false, isSuccess: true,
  }),
}));

import type { OFChatItem } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { FanListBulkBar } from "./FanListBulkBar";

const ACCOUNT_ID = "100000001";
const chat = (id: number, unread: boolean) => ({
  withUser: { id, name: `Fixture Fan ${id}`, username: `fan${id}` },
  hasUnread: unread,
  unreadMessagesCount: unread ? 1 : 0,
  __accountId: ACCOUNT_ID,
}) as OFChatItem;
const READ = chat(200000001, false);
const UNREAD = chat(200000002, true);

let confirm: MockInstance<typeof window.confirm>;

beforeEach(() => {
  relayPost.mockReset().mockResolvedValue({});
  relayDelete.mockReset().mockResolvedValue({});
  confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
});

afterEach(() => {
  confirm.mockRestore();
  cleanup();
  denied.clear();
});

function renderBar(props: Partial<Parameters<typeof FanListBulkBar>[0]> = {}) {
  const cb = {
    onSelectAll: vi.fn(), onPickOnly: vi.fn(), onDone: vi.fn(),
    markChatsRead: vi.fn<(rows: OFChatItem[]) => Promise<OFChatItem[]>>().mockResolvedValue([]),
  };
  const { queryClient } = renderWithProviders(
    <FanListBulkBar picked={[READ, UNREAD]} shownCount={5} listsAccountId={ACCOUNT_ID} {...cb} {...props} />,
  );
  return { ...cb, invalidate: vi.spyOn(queryClient, "invalidateQueries") };
}

const bar = () => within(screen.getByRole("toolbar", { name: "Selected chats" }));
const invalidatedKeys = (spy: ReturnType<typeof renderBar>["invalidate"]) =>
  spy.mock.calls.map(([f]) => (f as { queryKey: unknown[] }).queryKey);

describe("FanListBulkBar", () => {
  it("shows the count; Select all while some rows are unpicked, Clear selection once all are", async () => {
    const user = userEvent.setup();
    const cb = renderBar();
    expect(bar().getByText("2 selected")).toBeInTheDocument();
    await user.click(bar().getByRole("button", { name: "Select all" }));
    expect(cb.onSelectAll).toHaveBeenCalledTimes(1);

    cleanup();
    const cb2 = renderBar({ shownCount: 2 });
    await user.click(bar().getByRole("button", { name: "Clear selection" }));
    expect(cb2.onPickOnly).toHaveBeenCalledWith([]);
  });

  it("Mark as read hands FanList's loop the unread picks only; all read says so and sends nothing", async () => {
    const user = userEvent.setup();
    const COUNT_ONLY = { ...chat(200000003, false), unreadMessagesCount: 2 } as OFChatItem;
    const cb = renderBar({ picked: [READ, UNREAD, COUNT_ONLY] });
    await user.click(bar().getByRole("button", { name: "Mark as read" }));
    expect(await bar().findByText(/Marked 2 chats as read/)).toBeInTheDocument();
    expect(cb.markChatsRead).toHaveBeenCalledWith([UNREAD, COUNT_ONLY]);
    expect(cb.onPickOnly).not.toHaveBeenCalled();

    cleanup();
    const cb2 = renderBar({ picked: [READ] });
    await user.click(bar().getByRole("button", { name: "Mark as read" }));
    expect(await bar().findByText(/Already read/)).toBeInTheDocument();
    expect(cb2.markChatsRead).not.toHaveBeenCalled();
  });

  it("a failed mark-as-read leaves only that row picked", async () => {
    const user = userEvent.setup();
    const UNREAD2 = chat(200000003, true);
    const cb = renderBar({ picked: [READ, UNREAD, UNREAD2] });
    cb.markChatsRead.mockResolvedValueOnce([UNREAD]);
    await user.click(bar().getByRole("button", { name: "Mark as read" }));
    expect(await bar().findByText(/Marked 1 of 2; 1 failed, still selected/)).toBeInTheDocument();
    expect(cb.onPickOnly).toHaveBeenCalledWith([UNREAD]);
  });

  it("Add to lists offers only lists that take users and adds every pick in one POST", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.click(bar().getByRole("button", { name: /Add to lists/ }));
    const menu = within(screen.getByRole("region", { name: "Add to lists" }));
    expect(menu.queryByRole("button", { name: "Fixture Built-in" })).toBeNull();
    await user.click(menu.getByRole("button", { name: "Fixture VIPs" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith(
      "/api/of/v2/lists/users", { "900000001": [READ.withUser.id, UNREAD.withUser.id] }, { accountId: ACCOUNT_ID }));
    expect(await bar().findByText(/Added 2 Fans to "Fixture VIPs"/)).toBeInTheDocument();
  });

  it("All Models (no scoped Creator) does not offer Add to lists", () => {
    renderBar({ listsAccountId: null });
    expect(bar().queryByRole("button", { name: /Add to lists/ })).toBeNull();
  });

  it("a role denied Delete chats is not offered Delete", () => {
    denied.add("delete-chat");
    renderBar();
    expect(bar().queryByRole("button", { name: "Delete" })).toBeNull();
    expect(bar().getByRole("button", { name: "Mark as read" })).toBeInTheDocument();
  });

  it("Delete asks first; declined calls nothing, accepted DELETEs each picked chat, drops its thread and clears the selection", async () => {
    const user = userEvent.setup();
    const cb = renderBar();
    await user.click(bar().getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(relayDelete).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await user.click(bar().getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledTimes(2));
    expect(relayDelete).toHaveBeenNthCalledWith(1, `/api/of/v2/chats/${READ.withUser.id}`, { accountId: ACCOUNT_ID });
    expect(relayDelete).toHaveBeenNthCalledWith(2, `/api/of/v2/chats/${UNREAD.withUser.id}`, { accountId: ACCOUNT_ID });
    expect(await bar().findByText(/Deleted 2 conversations/)).toBeInTheDocument();
    expect(cb.onPickOnly).toHaveBeenCalledWith([]);
    expect(invalidatedKeys(cb.invalidate)).toEqual(expect.arrayContaining([
      ["messages", ACCOUNT_ID, READ.withUser.id], ["messages", ACCOUNT_ID, UNREAD.withUser.id], ["chats"],
    ]));
  });

  it("a failed delete is counted on the status line, stays picked, and keeps its thread cached", async () => {
    const user = userEvent.setup();
    confirm.mockReturnValue(true);
    relayDelete.mockRejectedValueOnce(new Error("upstream 502: fixture"));
    const cb = renderBar();
    await user.click(bar().getByRole("button", { name: "Delete" }));
    expect(await bar().findByText(/Deleted 1 of 2; 1 failed, still selected/)).toBeInTheDocument();
    expect(cb.onPickOnly).toHaveBeenCalledWith([READ]);
    const keys = invalidatedKeys(cb.invalidate);
    expect(keys).toContainEqual(["messages", ACCOUNT_ID, UNREAD.withUser.id]);
    expect(keys).not.toContainEqual(["messages", ACCOUNT_ID, READ.withUser.id]);
  });

  it("a row with no Creator stamp is never sent and counts as failed", async () => {
    const user = userEvent.setup();
    confirm.mockReturnValue(true);
    const bare = { ...READ, __accountId: undefined } as OFChatItem;
    const cb = renderBar({ picked: [bare, UNREAD] });
    await user.click(bar().getByRole("button", { name: "Delete" }));
    expect(await bar().findByText(/Deleted 1 of 2; 1 failed/)).toBeInTheDocument();
    expect(relayDelete).toHaveBeenCalledTimes(1);
    expect(cb.onPickOnly).toHaveBeenCalledWith([bare]);
  });
});
