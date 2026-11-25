import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import type { OFChatItem } from "@/lib/relay";
import {
  GROUP_CHANNEL_NAME, GROUP_HEARTBEAT_MS, GROUP_TAB_KEY_PREFIX, type GroupChannelMessage,
} from "@/lib/groupChannel";

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
vi.mock("@/hooks/useIsDesktop", () => ({ useIsDesktop: () => renders.desktop }));

import GroupChatPage from "./page";

const ACCOUNT = "100000001";
const FAN = 200000001;
const mountedTabId = () => sessionStorage.getItem("chatterly:group-tab-id") ?? "";
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
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

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
    await write([row(FAN, FAN, 1)]);
    expect(document.title).toBe("(1) Group chat · Inflowwww");
    const after = renders.fanList;
    const pane = renders.pane;
    for (let i = 0; i < 50; i++) await write([row(300000000 + i, 300000000 + i, 10 + i), row(FAN, FAN, 1)]);
    expect(renders.fanList).toBe(after);
    expect(renders.pane).toBe(pane);
    await write([row(FAN, Number(ACCOUNT), 99)]);
    expect(document.title).toBe("Group chat · Inflowwww");
  });

  it("acks every add truthfully, including ones that queue behind another", async () => {
    const seeded = [1, 2, 3, 4, 5, 6].map((i) => `${ACCOUNT}:${200000000 + i}`).join(",");
    window.history.replaceState(null, "", `/group?slots=${seeded}`);
    renderWithProviders(<GroupChatPage />);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(6));
    const tabId = mountedTabId();

    vi.spyOn(window, "focus").mockImplementation(() => {});
    const sender = new BroadcastChannel(GROUP_CHANNEL_NAME);
    const acks = new Map<string, boolean>();
    sender.onmessage = (e: MessageEvent<GroupChannelMessage>) => {
      if (e.data?.type === "add-ack") acks.set(e.data.reqId, e.data.ok);
    };
    const add = (reqId: string, fanId: number | string) => sender.postMessage(
      { type: "add", tabId, reqId, accountId: ACCOUNT, fanId },
    );
    try {
      add("bad", "abc");
      add("a", 300000001);
      add("b", 300000002);
      add("c", 300000003);
      add("dup", "200000001");
      await waitFor(() => expect(acks.size).toBe(5));
      expect(Object.fromEntries(acks)).toEqual({ bad: false, a: true, b: true, c: false, dup: true });
      await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(8));
    } finally {
      sender.close();
    }
  });

  it.each<[string, number, number]>([
    ["older tab reloaded keeps the fan", 1000, 1],
    ["younger tab reloaded yields him", 3000, 0],
  ])("%s", async (_name, ownAge, panes) => {
    sessionStorage.setItem("chatterly:group-tab-id", "me");
    sessionStorage.setItem("chatterly:group-tab-created-at", String(ownAge));
    sessionStorage.setItem("chatterly:group-slots", JSON.stringify([{ accountId: ACCOUNT, fanId: FAN }]));
    localStorage.setItem(GROUP_TAB_KEY_PREFIX + "other", JSON.stringify(
      { tabId: "other", createdAt: 2000, heartbeat: Date.now(), slots: [{ accountId: ACCOUNT, fanId: String(FAN) }] }));
    window.history.replaceState(null, "", "/group");
    renderWithProviders(<GroupChatPage />);
    await waitFor(() => expect(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me")).not.toBeNull());
    expect(screen.queryAllByTestId("pane")).toHaveLength(panes);
    expect(JSON.parse(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me") ?? "{}").createdAt).toBe(ownAge);
  });

  it.each<[string, number, number]>([
    ["stale older tab reloaded yields to the younger holder", 60_000, 0],
    ["quick older tab reload keeps the fan", 1000, 1],
  ])("%s", async (_name, sinceBeat, panes) => {
    sessionStorage.setItem("chatterly:group-tab-id", "me");
    sessionStorage.setItem("chatterly:group-tab-created-at", "1000");
    sessionStorage.setItem("chatterly:group-tab-last-beat", String(Date.now() - sinceBeat));
    sessionStorage.setItem("chatterly:group-slots", JSON.stringify([{ accountId: ACCOUNT, fanId: FAN }]));
    localStorage.setItem(GROUP_TAB_KEY_PREFIX + "other", JSON.stringify(
      { tabId: "other", createdAt: 2000, heartbeat: Date.now(), slots: [{ accountId: ACCOUNT, fanId: String(FAN) }] }));
    window.history.replaceState(null, "", "/group");
    renderWithProviders(<GroupChatPage />);
    await waitFor(() => expect(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me")).not.toBeNull());
    expect(screen.queryAllByTestId("pane")).toHaveLength(panes);
    const mine = JSON.parse(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me") ?? "{}");
    expect(mine.slots).toHaveLength(panes);
    if (panes === 0) expect(mine.createdAt).toBeGreaterThan(2000);
    else expect(mine.createdAt).toBe(1000);
    expect(Number(sessionStorage.getItem("chatterly:group-tab-last-beat"))).toBeGreaterThan(Date.now() - 1000);
  });

  it.each<[string, number, number]>([
    ["an older tab holds him too: this (younger) tab drops him on its next beat", 1000, 0],
    ["a younger tab holds him too: this tab keeps him", 5000, 1],
  ])("%s", async (_name, otherAge, panes) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      sessionStorage.setItem("chatterly:group-tab-id", "me");
      sessionStorage.setItem("chatterly:group-tab-created-at", "3000");
      sessionStorage.setItem("chatterly:group-slots", JSON.stringify([{ accountId: ACCOUNT, fanId: FAN }]));
      window.history.replaceState(null, "", "/group");
      renderWithProviders(<GroupChatPage />);
      await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(1));
      localStorage.setItem(GROUP_TAB_KEY_PREFIX + "other", JSON.stringify(
        { tabId: "other", createdAt: otherAge, heartbeat: Date.now(), slots: [{ accountId: ACCOUNT, fanId: String(FAN) }] }));
      await act(async () => { await vi.advanceTimersByTimeAsync(GROUP_HEARTBEAT_MS + 10); });
      expect(screen.queryAllByTestId("pane")).toHaveLength(panes);
      const mine = JSON.parse(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me") ?? "{}").slots;
      expect(mine).toHaveLength(panes);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each<[string, "interval" | "visibilitychange", boolean, number]>([
    ["stale older tab yields to the younger holder (interval)", "interval", true, 0],
    ["stale older tab yields to the younger holder (visibilitychange)", "visibilitychange", true, 0],
    ["stale tab keeps a fan nobody else holds", "interval", false, 1],
  ])("%s", async (_name, wake, held, panes) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      sessionStorage.setItem("chatterly:group-tab-id", "me");
      sessionStorage.setItem("chatterly:group-tab-created-at", "1000");
      sessionStorage.setItem("chatterly:group-slots", JSON.stringify([{ accountId: ACCOUNT, fanId: FAN }]));
      window.history.replaceState(null, "", "/group");
      renderWithProviders(<GroupChatPage />);
      await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(1));
      vi.setSystemTime(Date.now() + 60_000);
      if (held) localStorage.setItem(GROUP_TAB_KEY_PREFIX + "other", JSON.stringify(
        { tabId: "other", createdAt: 5000, heartbeat: Date.now(), slots: [{ accountId: ACCOUNT, fanId: String(FAN) }] }));
      await act(async () => {
        if (wake === "visibilitychange") document.dispatchEvent(new Event("visibilitychange"));
        else await vi.advanceTimersByTimeAsync(GROUP_HEARTBEAT_MS + 10);
      });
      expect(screen.queryAllByTestId("pane")).toHaveLength(panes);
      const mine = JSON.parse(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "me") ?? "{}");
      expect(mine.slots).toHaveLength(panes);
      expect(mine.createdAt).toBeGreaterThan(5000);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a freshly opened tab does not inherit a copied tab id", async () => {
    sessionStorage.setItem("chatterly:group-tab-id", "opener");
    sessionStorage.setItem("chatterly:group-tab-created-at", "1000");
    renderWithProviders(<GroupChatPage />);
    await screen.findByTestId("pane");
    const id = mountedTabId();
    expect(id).not.toBe("opener");
    await waitFor(() => expect(localStorage.getItem(GROUP_TAB_KEY_PREFIX + id)).not.toBeNull());
    expect(localStorage.getItem(GROUP_TAB_KEY_PREFIX + "opener")).toBeNull();
    expect(JSON.parse(localStorage.getItem(GROUP_TAB_KEY_PREFIX + id) ?? "{}").createdAt).toBeGreaterThan(1000);
  });

  it("acks a slotless replace ok:false and ignores garbage", async () => {
    renderWithProviders(<GroupChatPage />);
    await screen.findByTestId("pane");
    const tabId = mountedTabId();
    vi.spyOn(window, "focus").mockImplementation(() => {});
    const sender = new BroadcastChannel(GROUP_CHANNEL_NAME);
    const acks = new Map<string, boolean>();
    sender.onmessage = (e: MessageEvent<GroupChannelMessage>) => {
      if (e.data?.type === "add-ack") acks.set(e.data.reqId, e.data.ok);
    };
    try {
      for (const junk of [null, "add", 7, { type: "add" }, { type: "add", tabId, reqId: 5 }]) {
        sender.postMessage(junk);
      }
      sender.postMessage({ type: "replace", tabId, reqId: "rep" });
      sender.postMessage({ type: "add", tabId, reqId: "bad", accountId: ACCOUNT, fanId: { n: 1 } });
      sender.postMessage({ type: "add", tabId, reqId: "ok", accountId: ACCOUNT, fanId: "900234567890123456" });
      await waitFor(() => expect(acks.size).toBe(3));
      expect(Object.fromEntries(acks)).toEqual({ rep: false, bad: false, ok: true });
      await waitFor(() => expect(screen.getAllByTestId("pane").map((p) => p.dataset.fan))
        .toEqual([`number:${FAN}`, "string:900234567890123456"]));
    } finally {
      sender.close();
    }
  });

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
