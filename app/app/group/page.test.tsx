/**
 * /group under a DM flood: one layout is mounted (a hidden Fan List and a
 * hidden copy of the active pane still rendered on every live message), and
 * a chats-cache write re-renders the page only when the unresponded count
 * it shows changes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import type { OFChatItem } from "@/lib/relay";

const renders = vi.hoisted(() => ({ fanList: 0, pane: 0, desktop: true }));
vi.mock("@/components/chat/FanList", () => ({
  FanList: () => { renders.fanList += 1; return <div data-testid="fan-list" />; },
}));
vi.mock("@/components/group/GroupPane", () => ({
  GroupPane: () => { renders.pane += 1; return <div data-testid="pane" />; },
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
afterEach(() => { cleanup(); });

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
});
