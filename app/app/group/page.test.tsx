/**
 * /group under a DM flood: one layout is mounted (a hidden Fan List and a
 * hidden copy of the active pane still rendered on every live message), and
 * a chats-cache write re-renders the page only when the unresponded count
 * it shows changes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import type { OFChatItem } from "@/lib/relay";
import { GROUP_CHANNEL_NAME, type GroupChannelMessage } from "@/lib/groupChannel";

const renders = vi.hoisted(() => ({ fanList: 0, pane: 0, desktop: true }));
vi.mock("@/components/chat/FanList", () => ({
  FanList: () => { renders.fanList += 1; return <div data-testid="fan-list" />; },
}));
vi.mock("@/components/group/GroupPane", () => ({
  GroupPane: ({ fanId }: { fanId: number | string }) => {
    renders.pane += 1;
    return <div data-testid="pane" data-fan={`${typeof fanId}:${fanId}`} />;
  },
}));
vi.mock("@/hooks/useInboxRealtime", () => ({ useInboxRealtime: () => {} }));
vi.mock("@/hooks/useIsDesktop", () => ({ useIsDesktop: () => renders.desktop }));

import GroupChatPage from "./page";

const ACCOUNT = "100000001";
const FAN = 200000001;
const row = (fanId: number, fromId: number, id: number) => ({
  withUser: { id: fanId, name: `Fan ${fanId}`, username: `fan${fanId}` },
  lastMessage: { id, text: "hi", fromUser: { id: fromId }, createdAt: new Date().toISOString() },
  __accountId: ACCOUNT,
}) as OFChatItem;

beforeEach(() => {
  renders.fanList = 0; renders.pane = 0; renders.desktop = true;
  sessionStorage.clear();
  window.history.replaceState(null, "", `/group?add=${ACCOUNT}:${FAN}`);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("/group", () => {
  it.each([true, false])("mounts one Fan List and one pane (desktop=%s)", async (desktop) => {
    renders.desktop = desktop;
    renderWithProviders(<GroupChatPage />);
    await screen.findAllByTestId("pane");
    expect(screen.getAllByTestId("fan-list")).toHaveLength(1);
    expect(screen.getAllByTestId("pane")).toHaveLength(1);
  });

  it("re-renders on a chats write only when the unresponded count changes", async () => {
    const { queryClient: qc } = renderWithProviders(<GroupChatPage />);
    await screen.findByTestId("pane");
    const write = async (rows: OFChatItem[]) => {
      await act(async () => {
        qc.setQueryData(["chats", "all", "recent"], { pages: [{ rows }], pageParams: [0] });
        await Promise.resolve();
      });
    };
    // The slotted Fan wrote last: the count goes 0 -> 1, one re-render.
    await write([row(FAN, FAN, 1)]);
    expect(document.title).toBe("(1) Group chat · Inflowwww");
    const after = renders.fanList;
    // 50 DMs from other Fans: the count holds, so neither the list nor the pane re-renders.
    const pane = renders.pane;
    for (let i = 0; i < 50; i++) await write([row(300000000 + i, 300000000 + i, 10 + i), row(FAN, FAN, 1)]);
    expect(renders.fanList).toBe(after);
    expect(renders.pane).toBe(pane);
    // The Creator answers: 1 -> 0.
    await write([row(FAN, Number(ACCOUNT), 99)]);
    expect(document.title).toBe("Group chat · Inflowwww");
  });

  // Two `add` broadcasts back to back into a tab with room for exactly two:
  // both land, so both acks must say ok — an ok:false made the sender open
  // an overflow tab holding a fan this tab already took. The third is
  // refused, and a re-add of a held fan under the other id shape is ok
  // without taking a slot.
  it("acks every add truthfully, including ones that queue behind another", async () => {
    sessionStorage.setItem("chatterly:group-tab-id", "tab-under-test");
    const seeded = [1, 2, 3, 4, 5, 6].map((i) => `${ACCOUNT}:${200000000 + i}`).join(",");
    window.history.replaceState(null, "", `/group?slots=${seeded}`);
    renderWithProviders(<GroupChatPage />);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(6));

    vi.spyOn(window, "focus").mockImplementation(() => {});
    const sender = new BroadcastChannel(GROUP_CHANNEL_NAME);
    const acks = new Map<string, boolean>();
    sender.onmessage = (e: MessageEvent<GroupChannelMessage>) => {
      if (e.data?.type === "add-ack") acks.set(e.data.reqId, e.data.ok);
    };
    const add = (reqId: string, fanId: number | string) => sender.postMessage(
      { type: "add", tabId: "tab-under-test", reqId, accountId: ACCOUNT, fanId },
    );
    try {
      add("bad", "abc");
      add("a", 300000001);
      add("b", 300000002);
      add("c", 300000003);
      add("dup", "200000001");
      await waitFor(() => expect(acks.size).toBe(5));
      // A malformed add is refused out loud (no ack made the sender wait out
      // its 400 ms timeout and then open an overflow tab).
      expect(Object.fromEntries(acks)).toEqual({ bad: false, a: true, b: true, c: false, dup: true });
      await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(8));
    } finally {
      sender.close();
    }
  });

  // A reload restores the slots from sessionStorage — Fansly's string ids
  // too (a `typeof fanId !== "number"` filter dropped them on every reload).
  it("restores a string (Fansly) fan id on reload", async () => {
    const snow = "900234567890123456";
    sessionStorage.setItem("chatterly:group-slots", JSON.stringify([
      { accountId: ACCOUNT, fanId: FAN }, { accountId: ACCOUNT, fanId: snow }, { accountId: ACCOUNT, fanId: "abc" },
    ]));
    window.history.replaceState(null, "", "/group");
    renderWithProviders(<GroupChatPage />);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(2));
    expect(screen.getAllByTestId("pane").map((p) => p.dataset.fan)).toEqual([`number:${FAN}`, `string:${snow}`]);
    expect(JSON.parse(sessionStorage.getItem("chatterly:group-slots") ?? "[]")).toEqual([
      { accountId: ACCOUNT, fanId: FAN }, { accountId: ACCOUNT, fanId: snow },
    ]);
  });
});
