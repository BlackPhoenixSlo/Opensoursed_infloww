import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const platform = vi.hoisted(() => ({
  current: "onlyfans" as "onlyfans" | "fansly",
  byId: {} as Record<string, "onlyfans" | "fansly" | null>,
}));
vi.mock("@/hooks/useCan", async () => {
  const { can } = await import("@/lib/platform");
  const of = (id: unknown) => (typeof id === "string" && id in platform.byId ? platform.byId[id] : platform.current);
  return {
    useCan: (id: unknown, cap: Parameters<typeof can>[1]) => can(of(id), cap),
    useAccountPlatform: (id: string | null | undefined) => (id ? of(id) : null),
  };
});
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { relay, type AccountMeta, type OFChatItem } from "@/lib/relay";
import { UNREAD_VIEW_MAX_AGE_MS } from "@/lib/chatsCache";
import { PLATFORM_KEY, resetPlatformForTests, setPlatform } from "@/lib/platform";
import { renderWithProviders, settled } from "@/test-utils";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useInboxRealtime } from "@/hooks/useInboxRealtime";
import { PREFETCH_IDLE_TIMEOUT_MS, PREFETCH_QUIET_MS } from "@/hooks/useUnreadMessagesPrefetch";
import { emitEvent, observerStub, relayGet, relayPost, resetComposerHarness, routeRelay, tooltipOf } from "./composerTestHarness";
import { FanList, SEARCH_DEBOUNCE_MS, type FanListSelection } from "./FanList";
import { ROW_RENDER_STEP } from "./fanListPaging";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("@/lib/perfLog");
vi.mock("@/lib/events", async () => (await import("./composerTestHarness")).mockEventsModule());
vi.mock("@/hooks/useDeferredMount", () => ({ useDeferredMount: () => true }));
const rowRenders = vi.hoisted(() => new Map<string, number>());
vi.mock("@/lib/chatDrafts", async (orig) => {
  const real = await orig<typeof import("@/lib/chatDrafts")>();
  return {
    ...real,
    useChatDraftText: (...args: Parameters<typeof real.useChatDraftText>) => {
      const fan = String(args[1]);
      rowRenders.set(fan, (rowRenders.get(fan) ?? 0) + 1);
      return real.useChatDraftText(...args);
    },
  };
});
vi.mock("@/contexts/ScopeContext", () => ({
  useScope: () => ({
    scope: scopeKind === "all" ? { kind: "all" } : { kind: "model", accountId: scopeCreator },
    setScope: vi.fn(),
    accountId: scopeCreator,
    eventScope: "all",
  }),
}));
vi.mock("@/hooks/useAccounts", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useAccounts")>()),
  useActiveAccounts: () => ACCOUNTS,
  usePlatformAccounts: () => ACCOUNTS,
  useAccountLabel: (accountId?: string | null) => (accountId === ACCOUNT_ID ? "Test Creator" : ""),
}));
vi.mock("@/components/shell/useIsChatterOnly", () => ({ useIsChatterOnly: () => chatterOnly }));
vi.mock("@/contexts/UserContext", async (orig) => {
  const value = { user: { username: "owner" }, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = { chatter: null, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (orig) => {
  const value = { current: null, clear: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/EmployeeContext")>()), useEmployee: () => value };
});
vi.mock("@/components/compose/LazyMassMessageComposer", async () => ({
  LazyMassMessageComposer: (await import("@/components/compose/MassMessageComposer")).MassMessageComposer,
}));

let chatterOnly = false;
let scopeKind: "model" | "all" = "model";
let ACCOUNTS: AccountMeta[] = [];


const ACCOUNT_ID = "100000001";
const CREATOR_ACCOUNT: AccountMeta = { id: ACCOUNT_ID, nickname: "Test Creator", color: "#e8618c", is_active: true, proxy_down: false };
const OTHER_ACCOUNT: AccountMeta = { id: "100000002", nickname: "Other Creator", color: "#6a8cf0", is_active: true, proxy_down: false };
let scopeCreator = ACCOUNT_ID;
const CREATOR = { id: Number(ACCOUNT_ID), name: "Test Creator", username: "testcreator" };
const FANS = [
  { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" },
  { id: 200000002, name: "Fixture Fan Two", username: "fixturefantwo" },
  { id: 200000003, name: "Fixture Fan Three", username: "fixturefanthree" },
];
const FAN_FOUR = { id: 200000004, name: "Fixture Fan Four", username: "fixturefanfour" };
const FAN_FIVE = { id: 200000005, name: "Fixture Fan Five", username: "fixturefanfive" };
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

const CHATS = FANS.map((f, i) => {
  const fanWroteLast = i < 2;
  return {
    withUser: { ...f, avatar: null },
    lastMessage: { id: 800000000 + i, text: `Hello from ${f.name}`, fromUser: fanWroteLast ? f : CREATOR, createdAt: ago(60 + i) },
    hasUnread: fanWroteLast,
    unreadMessagesCount: fanWroteLast ? 1 : 0,
  } as OFChatItem;
});

function serveChats(list: OFChatItem[] | (() => OFChatItem[])) {
  routeRelay("/api/of/v2/chats?", (path) => {
    const offset = new URLSearchParams(path.split("?")[1]).get("offset") ?? "0";
    return { list: offset === "0" ? (typeof list === "function" ? list() : list) : [], hasMore: false };
  });
}

function serveFolders(lists: Array<{ id: number; name: string; pinned: boolean }>) {
  routeRelay("/api/of/v2/chats/folders", () => ({
    list: lists.map((l) => ({ id: l.id, name: l.name, type: "custom", isPinnedToChat: l.pinned, usersCount: 5 })),
    hasMore: false,
  }));
}

function serveChatsSearchable(list: OFChatItem[] | (() => OFChatItem[])) {
  routeRelay("/api/of/v2/chats?", (path) => {
    const params = new URLSearchParams(path.split("?")[1]);
    const query = (params.get("query") ?? "").toLowerCase();
    const hits = (typeof list === "function" ? list() : list).filter((c) => String(c.withUser.name).toLowerCase().includes(query));
    return { list: (params.get("offset") ?? "0") === "0" ? hits : [], hasMore: false };
  });
}

function serveTransactions(rows: Array<{ fan: (typeof FANS)[number]; description: string; status: string }>) {
  routeRelay("/api/of/v2/payouts/transactions", () => ({
    list: rows.map((r, i) => ({
      id: `tx-${i}`, amount: 25, createdAt: ago(24 * 60 + i), description: `${r.description}${r.fan.name}`,
      status: r.status, user: { id: r.fan.id },
    })),
    hasMore: false,
  }));
}

function renderFanList(props: Partial<Parameters<typeof FanList>[0]> = {}) {
  return renderWithProviders(
    <FanList selected={null} onSelect={vi.fn()} {...props} />,
    new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
}

function InboxRealtime() {
  useInboxRealtime();
  return null;
}

function withRealtime() {
  return (
    <>
      <InboxRealtime />
      <FanList selected={null} onSelect={vi.fn()} />
    </>
  );
}

function fanWrites(fan: (typeof FANS)[number], id: number, text: string, createdAt: string) {
  act(() => emitEvent("api2_chat_message", {
    __account_id: scopeCreator,
    api2_chat_message: { id, text, fromUser: { id: fan.id, name: fan.name }, createdAt },
  }));
}

const rowOf = (name: string) => screen.findByRole("button", { name: new RegExp(name) });
const fire = (name: string) => within(screen.getByRole("button", { name: new RegExp(name) }))
  .queryByRole("img", { name: "Bought a PPV within 7 days" });
const header = () => screen.getByRole("group", { name: "Fan List header" });
const newMenu = () => screen.getByRole("region", { name: "New" });
const filterRow = () => screen.getByRole("group", { name: "Inbox, settings and sort" });
const openSettings = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(within(filterRow()).getByRole("button", { name: "Inbox settings" }));
const rowOrder = () => screen.getAllByRole("button", { name: /Fixture Fan (One|Two|Three|Four|Five)/ })
  .map((row) => /Fixture Fan (One|Two|Three|Four|Five)/.exec(row.textContent ?? "")?.[0]);
function serveSplit(group_count: number, assignments: Record<string, number>) {
  routeRelay("/admin/split-inbox?", (path) => ({
    account_id: new URLSearchParams(path.split("?")[1]).get("account_id"),
    config: { group_count, assignments },
  }));
}
function serveSavableSplit(group_count: number, assignments: Record<string, number>) {
  let stored = { group_count, assignments };
  routeRelay("/admin/split-inbox?", () => ({ account_id: ACCOUNT_ID, config: stored }));
  return vi.mocked(relay.put).mockReset().mockImplementation(async (_path, body) => {
    stored = (body as { config: typeof stored }).config;
    return { account_id: ACCOUNT_ID, config: stored };
  });
}
async function saveSplit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Save" }));
  await vi.waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}
const shownFans = () => screen.queryAllByRole("button", { name: /Fixture Fan (One|Two|Three|Four|Five)/ })
  .map((row) => /Fixture Fan (One|Two|Three|Four|Five)/.exec(row.textContent ?? "")?.[0]);
async function chooseInbox(user: ReturnType<typeof userEvent.setup>, entry: string, label = "All inboxes") {
  await user.click(within(filterRow()).getByRole("button", { name: label }));
  await user.click(await within(screen.getByRole("region", { name: "Inboxes" })).findByRole("button", { name: entry }));
}
const answered = (fan: { id: number; name: string; username: string }, minutesAgo: number) => ({
  withUser: { ...fan, avatar: null },
  lastMessage: { id: 800000100 + fan.id % 1000, text: `Hello from ${fan.name}`, fromUser: CREATOR, createdAt: ago(minutesAgo) },
  hasUnread: false,
  unreadMessagesCount: 0,
}) as OFChatItem;
const pageUrl = (offset: number) => `/api/of/v2/chats?limit=25&offset=${offset}&order=recent`;

const PRE_RESTYLE_URLS = [
  "/admin/accounts",
  "/admin/chats/recent?limit=25&account_id=100000001",
  "/admin/fans/100000001/by-ids?ids=200000001%2C200000002%2C200000003",
  "/admin/fans/100000001/spend-batch?ids=200000001%2C200000002%2C200000003",
  "/admin/split-inbox?account_id=100000001",
  "/api/of/v2/chats/folders?limit=50",
  "/api/of/v2/chats?limit=25&offset=0&order=recent",
  "/api/of/v2/payouts/transactions?limit=50&offset=0",
  "/api/of/v2/users/list?ids=200000001&ids=200000002&ids=200000003&view=m",
  "/api/of/v2/users/me",
];
const UNREAD_WARM_URLS = [
  "/api/of/v2/chats/200000001/messages?limit=30&order=desc&peek=1",
  "/api/of/v2/chats/200000002/messages?limit=30&order=desc&peek=1",
];
const LOAD_URLS = [...PRE_RESTYLE_URLS, ...UNREAD_WARM_URLS].sort();
const chatRequests = () => relayGet.mock.calls
  .filter(([path]) => path.startsWith("/api/of/v2/chats?"))
  .map((call) => [call[0], (call as unknown[])[3]]);

beforeEach(() => {
  chatterOnly = false;
  scopeKind = "model";
  scopeCreator = ACCOUNT_ID;
  ACCOUNTS = [CREATOR_ACCOUNT];
  resetComposerHarness();
  vi.stubGlobal("IntersectionObserver", observerStub);
  Element.prototype.scrollIntoView = vi.fn();
  document.title = "Before the Fan List";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  platform.current = "onlyfans";
  platform.byId = {};
  window.localStorage.removeItem(PLATFORM_KEY);
  resetPlatformForTests();
});

describe("FanList", () => {
  it("renders at most ROW_RENDER_STEP rows, with a footer that shows the rest a step at a time", async () => {
    const many = Array.from({ length: ROW_RENDER_STEP + 50 }, (_, i) => {
      const fan = { id: 300000000 + i, name: `Crowd Fan ${i}`, username: `crowdfan${i}`, avatar: null };
      return {
        withUser: fan,
        lastMessage: { id: 900000000 + i, text: `hi ${i}`, fromUser: fan, createdAt: ago(10 + i) },
        hasUnread: false,
        unreadMessagesCount: 0,
      } as OFChatItem;
    });
    serveChats(many);
    renderFanList();

    const more = await screen.findByRole("button", { name: "Show 50 more" });
    const rows = () => document.querySelectorAll("[data-chat-row]").length;
    expect(rows()).toBe(ROW_RENDER_STEP);
    await userEvent.setup().click(more);
    expect(rows()).toBe(ROW_RENDER_STEP + 50);
    expect(screen.queryByRole("button", { name: /^Show \d+ more$/ })).toBeNull();
  });

  it("marks the selected Fan's row aria-current, and no other row", async () => {
    serveChats(CHATS);
    const selected: FanListSelection = { accountId: ACCOUNT_ID, fanId: FANS[1].id, chat: CHATS[1] };
    renderFanList({ selected });

    expect(await rowOf("Fixture Fan Two")).toHaveAttribute("aria-current", "true");
    expect(await rowOf("Fixture Fan One")).not.toHaveAttribute("aria-current");
    expect(await rowOf("Fixture Fan Three")).not.toHaveAttribute("aria-current");
  });

  it("puts the count of chats needing attention in the tab title", async () => {
    serveChats(CHATS);
    renderFanList();

    await rowOf("Fixture Fan Three");
    expect(document.title).toBe("(2) Inbox · Inflowwww");
  });

  it("counts the unread chats of the All set on the Unread chip, and leaves All without a badge", async () => {
    const restricted = {
      withUser: { id: 200000004, name: "Fixture Fan Four", username: "fixturefanfour", avatar: null, isRestricted: true, badgeExcluded: true },
      lastMessage: { id: 800000003, text: "Hello from Fixture Fan Four", fromUser: { id: 200000004 }, createdAt: ago(63) },
      hasUnread: true,
      unreadMessagesCount: 1,
    } as OFChatItem;
    routeRelay("filter=pinned", () => ({ list: [], hasMore: false }));
    serveChats([CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2], restricted]);
    const user = userEvent.setup();
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));

    await rowOf("Fixture Fan Three");
    expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(document.title).toBe("(2) Inbox · Inflowwww");

    await user.click(screen.getByRole("button", { name: "Pinned" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();
  });

  it("on another chip (Pinned), a live patch of All's cache re-counts the Unread chip (W30-mu #20)", async () => {
    routeRelay("filter=pinned", () => ({ list: [], hasMore: false }));
    serveChats([CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2]]);
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, qc);
    await rowOf("Fixture Fan Three");
    expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pinned" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    const allKey = ["chats", "model", ACCOUNT_ID, null, null, null, 25];
    act(() => {
      qc.setQueryData(allKey, (d: { pages: { rows: OFChatItem[] }[] }) => ({
        ...d,
        pages: d.pages.map((pg) => ({ ...pg, rows: pg.rows.map((c) => c.withUser.id === FANS[1].id
          ? { ...c, hasUnread: true, unreadMessagesCount: 1 } : c) })),
      }));
    });
    expect(await screen.findByRole("button", { name: "Unread 2" })).toBeInTheDocument();
  });

  it("a chat read elsewhere leaves the Unread badge once the Unread list, read live and complete, no longer holds it, on every chip after; All's cache is left alone", async () => {
    routeRelay("filter=unread", () => ({ list: [], hasMore: false }));
    routeRelay("filter=pinned", () => ({ list: [], hasMore: false }));
    serveChats([CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2]]);
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, qc);
    await rowOf("Fixture Fan Three");
    expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unread 1" }));
    expect(await screen.findByRole("button", { name: "Unread" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fixture Fan/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All" }));
    await rowOf("Fixture Fan One");
    const allKey = ["chats", "model", ACCOUNT_ID, null, null, null, 25];
    const fanOne = () => (qc.getQueryData(allKey) as { pages: { rows: OFChatItem[] }[] }).pages[0].rows
      .find((c) => c.withUser.id === FANS[0].id);
    expect(fanOne()?.hasUnread).toBe(true);
    expect(screen.getByRole("button", { name: "Unread" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pinned" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Unread" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All" }));
    await rowOf("Fixture Fan One");

    scopeCreator = OTHER_ACCOUNT.id;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Unread 1" })).toBeInTheDocument();
    scopeCreator = ACCOUNT_ID;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Unread" })).toBeInTheDocument();

    act(() => {
      qc.setQueryData(allKey, (d: { pages: { rows: OFChatItem[] }[] }) => ({
        ...d,
        pages: d.pages.map((pg) => ({ ...pg, rows: pg.rows.map((c) => c.withUser.id === FANS[1].id
          ? { ...c, hasUnread: true, unreadMessagesCount: 1, lastMessage: { ...c.lastMessage!, createdAt: new Date().toISOString() } }
          : c) })),
      }));
    });
    expect(await screen.findByRole("button", { name: "Unread 1" })).toBeInTheDocument();

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    try {
      act(() => {
        qc.setQueryData(allKey, (d: { pages: { rows: OFChatItem[] }[] }) => ({
          ...d,
          pages: d.pages.map((pg) => ({ ...pg, rows: pg.rows.map((c) => c.withUser.id === FANS[2].id
            ? { ...c, isMutedNotifications: !c.isMutedNotifications } : c) })),
        }));
      });
      act(() => { vi.advanceTimersByTime(UNREAD_VIEW_MAX_AGE_MS - 1_000); });
      expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(1_000); });
      expect(screen.getByRole("button", { name: "Unread 2" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a search drops the remembered Unread view: the badge counts the searched All set", async () => {
    routeRelay("filter=unread", () => ({ list: [], hasMore: false }));
    serveChats([CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2]]);
    const user = userEvent.setup();
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await rowOf("Fixture Fan Three");
    await user.click(screen.getByRole("button", { name: "Unread 1" }));
    expect(await screen.findByRole("button", { name: "Unread" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All" }));
    await rowOf("Fixture Fan One");
    expect(screen.getByRole("button", { name: "Unread" })).toBeInTheDocument();

    await user.click(within(header()).getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByPlaceholderText("Search…"), { target: { value: "Fixture" } });
    expect(await screen.findByRole("button", { name: "Unread 1" })).toBeInTheDocument();
  });

  it("an Unread list with pages left keeps the badge on the All set", async () => {
    routeRelay("filter=unread", () => ({ list: [], hasMore: true }));
    serveChats([CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2]]);
    const user = userEvent.setup();
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await rowOf("Fixture Fan Three");

    await user.click(screen.getByRole("button", { name: "Unread 1" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Unread 1" })).toBeInTheDocument();
  });

  describe("the Relay's Unread totals (watched-creator-refresher Phase 2)", () => {
    const freshness = (aid: string, n?: number, ago = 30_000) => ({
      account_id: aid, boot: 1000, seq: 1, now: Date.now(), at: Date.now() - ago, cycle_s: 120, live: "up",
      live_since: Date.now() - 60_000, values: n === undefined ? {} : { unread_total: { n, at: Date.now() - ago } },
    });
    const accountsAnswer = (totals: Record<string, number | undefined>, ago?: Record<string, number>) => ({
      accounts: ACCOUNTS.map((a) => ({ ...a, has_session: true, freshness: freshness(a.id, totals[a.id], ago?.[a.id]) })),
      active_account_id: null,
    });
    function serveBothCreators() {
      routeRelay("/api/of/v2/chats?", (path, ctx) => {
        if ((new URLSearchParams(path.split("?")[1]).get("offset") ?? "0") !== "0") return { list: [], hasMore: false };
        if (path.includes("filter=unread")) return { list: ctx?.accountId === ACCOUNT_ID ? [CHATS[0]] : [], hasMore: false };
        return ctx?.accountId === ACCOUNT_ID
          ? { list: CHATS, hasMore: false }
          : { list: [{ ...CHATS[0], withUser: { ...FAN_FIVE, avatar: null } }], hasMore: false };
      });
    }
    function persistedClient(totals: Record<string, number | undefined>) {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      qc.setQueryData(["accounts", "anon"], accountsAnswer(totals), { updatedAt: 1 });
      return qc;
    }
    function holdAccounts(totals: Record<string, number | undefined>) {
      let release!: () => void;
      const answered = new Promise<void>((r) => { release = r; });
      routeRelay("/admin/accounts", () => answered.then(() => accountsAnswer(totals)));
      return () => act(() => release());
    }

    beforeEach(() => {
      scopeKind = "all";
      ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    });

    it("the badge is Σ the held totals over the stale All flags; the Unread chip's rows stay #881's live list", async () => {
      routeRelay("/admin/accounts", () => accountsAnswer({ [ACCOUNT_ID]: 7, [OTHER_ACCOUNT.id]: 3 }));
      serveBothCreators();
      const user = userEvent.setup();
      renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
      await rowOf("Fixture Fan Five");

      expect(await screen.findByRole("button", { name: "Unread 10" })).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Unread 10" }));
      await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan One"]));
      expect(screen.getByRole("button", { name: "Unread 10" })).toBeInTheDocument();
    });

    it("a Creator without a total counts by today's rule over its own rows", async () => {
      routeRelay("/admin/accounts", () => accountsAnswer({ [ACCOUNT_ID]: 7 }));
      serveBothCreators();
      renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
      await rowOf("Fixture Fan Five");

      expect(await screen.findByRole("button", { name: "Unread 8" })).toBeInTheDocument();
    });

    it("totals on in the persisted copy: no number over the rows' flags until the network answer is seeded", async () => {
      const release = holdAccounts({ [ACCOUNT_ID]: 7, [OTHER_ACCOUNT.id]: 3 });
      serveBothCreators();
      renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, persistedClient({ [ACCOUNT_ID]: 2, [OTHER_ACCOUNT.id]: 2 }));
      await rowOf("Fixture Fan Five");
      await settled();

      expect(screen.getByRole("button", { name: "Unread" })).toBeInTheDocument();
      await release();
      expect(await screen.findByRole("button", { name: "Unread 10" })).toBeInTheDocument();
    });

    it("single-Creator scope with a late source: the chip carries the age and its one-Creator title (Phase 3 story 5)", async () => {
      scopeKind = "model";
      routeRelay("/admin/accounts", () => accountsAnswer({ [ACCOUNT_ID]: 7, [OTHER_ACCOUNT.id]: 3 }, { [ACCOUNT_ID]: 330_000 }));
      serveChats(CHATS);
      renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));

      const chip = await screen.findByRole("button", { name: "Unread 7 as of 5 min" });
      expect(chip).toHaveAttribute("title", "As of 5 min ago: not refreshed within its 2 min Cycle");
    });

    it("totals off in the persisted copy: today's number at once, before the network answer", async () => {
      holdAccounts({});
      serveBothCreators();
      renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, persistedClient({}));
      await rowOf("Fixture Fan Five");

      expect(await screen.findByRole("button", { name: "Unread 3" })).toBeInTheDocument();
    });
  });

  it("leaves the tab title alone with setTabTitle off", async () => {
    serveChats(CHATS);
    renderFanList({ setTabTitle: false });

    await rowOf("Fixture Fan Three");
    expect(document.title).toBe("Before the Fan List");
  });

  it("explains a failed chat request", async () => {
    routeRelay("/api/of/v2/chats?", () => Promise.reject(new Error("upstream 401")));
    renderFanList();

    expect(await screen.findByText("This account's OnlyFans session expired.")).toBeInTheDocument();
  });

  it("closes the settings menu on Escape and on a pointer-down outside it, not on one inside it", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await openSettings(user);
    fireEvent.pointerDown(screen.getByText("Keep fan info panel open"));
    expect(screen.getByText("Mark all as read")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Mark all as read")).not.toBeInTheDocument();

    await openSettings(user);
    expect(screen.getByText("Mark all as read")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("Mark all as read")).not.toBeInTheDocument();

    await openSettings(user);
    await openSettings(user);
    expect(screen.queryByText("Mark all as read")).not.toBeInTheDocument();
  });

  it("each settings control changes its own setting", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    await openSettings(user);
    const box = (name: string) => screen.getByRole("checkbox", { name });
    const checked = () => [
      box("Keep fan info panel open"), box("Blur images till hover"),
      box("Blur images constant"), box("Compact media previews"),
    ].map((el) => (el as HTMLInputElement).checked);
    expect(checked()).toEqual([true, false, false, true]);

    await user.click(box("Keep fan info panel open"));
    expect(checked()).toEqual([false, false, false, true]);
    await user.click(box("Blur images till hover"));
    expect(checked()).toEqual([false, true, false, true]);
    await user.click(box("Blur images constant"));
    expect(checked()).toEqual([false, false, true, true]);
    await user.click(box("Compact media previews"));
    expect(checked()).toEqual([false, false, true, false]);

    await user.keyboard("{Escape}");
    const sortControl = () => within(filterRow()).getByRole("button", { name: /^Sort: / });
    expect(sortControl()).toHaveAccessibleName("Sort: Newest first");
    expect(sortControl()).toHaveAttribute("aria-pressed", "false");
    await user.click(sortControl());
    await user.click(within(screen.getByRole("region", { name: "Sort" })).getByRole("button", { name: "Amount spent" }));
    expect(sortControl()).toHaveAccessibleName("Sort: Amount spent");
    expect(sortControl()).toHaveAttribute("aria-pressed", "true");
    await user.click(sortControl());
    await user.click(within(screen.getByRole("region", { name: "Sort" })).getByRole("button", { name: "Newest first" }));
    expect(sortControl()).toHaveAccessibleName("Sort: Newest first");
  });

  it("keeps \"Spend + unread on top\" across a remount, and reads \"Newest first\" with nothing stored", async () => {
    const user = userEvent.setup();
    const sortControl = () => within(filterRow()).getByRole("button", { name: /^Sort: / });
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(sortControl()).toHaveAccessibleName("Sort: Newest first");

    await user.click(sortControl());
    await user.click(screen.getByRole("button", { name: /^Spend \+ unread on top/ }));
    expect(sortControl()).toHaveAccessibleName("Sort: Spend + unread on top");

    cleanup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(sortControl()).toHaveAccessibleName("Sort: Spend + unread on top");
  });

  it("marks every unread chat of the Creator read in one OF write once confirmed, and nothing when cancelled", async () => {
    const user = userEvent.setup();
    serveSplit(1, {});
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await openSettings(user);
    await user.click(screen.getByText("Mark all as read"));
    expect(confirm).toHaveBeenCalledWith("Mark 2 chats as read?");
    expect(screen.queryByText("Mark all as read")).not.toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await openSettings(user);
    await user.click(screen.getByText("Mark all as read"));
    await vi.waitFor(() => expect(relayPost.mock.calls).toEqual([
      ["/api/of/v2/chats/mark-as-read", undefined, { accountId: ACCOUNT_ID }],
    ]));
  });

  it("marks only loaded chats while split config is pending", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("confirm", () => true);
    routeRelay("/admin/split-inbox?", () => new Promise(() => {}));
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    await openSettings(user);
    await user.click(screen.getByText("Mark all as read"));
    await vi.waitFor(() => expect(relayPost.mock.calls.map(([path]) => path)).toEqual([
      `/api/of/v2/chats/${FANS[0].id}/mark-as-read`,
      `/api/of/v2/chats/${FANS[1].id}/mark-as-read`,
    ]));
  });

  it("\"Mark all as read\" counts a chat unread by its count alone, and with chats left to load marks each loaded one unpaced", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const page = [
      { ...CHATS[0], hasUnread: false, unreadMessagesCount: 2 },
      { ...CHATS[1], hasUnread: false, unreadMessagesCount: 3 },
      CHATS[2],
    ];
    routeRelay("/api/of/v2/chats?", () => ({ list: page, hasMore: true }));
    renderFanList();
    await rowOf("Fixture Fan Three");

    await openSettings(user);
    expect(screen.getByRole("button", { name: /Mark all as read/ })).toBeEnabled();
    await user.click(screen.getByText("Mark all as read"));
    expect(confirm).toHaveBeenCalledWith("Mark 2 chats as read?");
    await vi.waitFor(() => expect(relayPost.mock.calls.map(([path]) => path)).toEqual([
      `/api/of/v2/chats/${FANS[0].id}/mark-as-read`,
      `/api/of/v2/chats/${FANS[1].id}/mark-as-read`,
    ]));
  });

  it("the filter row's refresh icon asks the relay for the chat list past its cache, as the header's ↻ did, and Search asks for the typed name", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    relayGet.mockClear();

    expect(filterRow()).toContainElement(screen.getByRole("button", { name: "Refresh inbox" }));
    expect(filterRow()).toContainElement(screen.getByRole("button", { name: "Inbox settings" }));
    await user.click(within(filterRow()).getByRole("button", { name: "Refresh inbox" }));
    await vi.waitFor(() => expect(chatRequests()).toEqual([
      ["/api/of/v2/chats?limit=25&offset=0&order=recent", { refresh: true }],
    ]));

    relayGet.mockClear();
    await user.click(within(header()).getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByPlaceholderText("Search…"), { target: { value: "Two" } });
    await vi.waitFor(() => expect(chatRequests()).toEqual([
      ["/api/of/v2/chats?limit=25&offset=0&order=recent&query=Two", { refresh: false }],
    ]));
  });

  it("the refresh icon re-reads the roster counts once the refreshed list is in, so the badges follow it", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    try {
      await user.click(within(filterRow()).getByRole("button", { name: "Refresh inbox" }));
      await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["roster-counts"] }));
    } finally {
      invalidate.mockRestore();
    }
  });

  it("a chip asks the relay for its filter, and the filter row's pencil opens the folder picker until Done", async () => {
    const user = userEvent.setup();
    serveFolders([{ id: 700000001, name: "Fixture Folder", pinned: false }]);
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    relayGet.mockClear();

    await user.click(screen.getByRole("button", { name: "Unread 2" }));
    await vi.waitFor(() => expect(chatRequests()).toEqual([
      ["/api/of/v2/chats?limit=25&offset=0&order=recent&filter=unread", { refresh: false }],
    ]));

    await user.click(await within(filterRow()).findByRole("button", { name: "Pin lists as chips" }));
    expect(screen.getByText("Pin folders to chat sidebar")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText("Pin folders to chat sidebar")).not.toBeInTheDocument();
  });

  it("Owe reply is the chip after All, its count shown before and while it is on, and there is no \"+\"", async () => {
    const excluded = {
      withUser: { ...FAN_FOUR, avatar: null, badgeExcluded: true },
      lastMessage: { id: 800000004, text: "Hello from Fixture Fan Four", fromUser: FAN_FOUR, createdAt: ago(63) },
      hasUnread: false,
      unreadMessagesCount: 0,
    } as OFChatItem;
    const user = userEvent.setup();
    serveChats([CHATS[0], { ...CHATS[1], withUser: { ...CHATS[1].withUser, isRestricted: true } }, CHATS[2], excluded]);
    renderFanList();
    await rowOf("Fixture Fan Three");
    const chips = within(screen.getByRole("group", { name: "Fan List filters" })).getAllByRole("button");
    expect(chips.slice(0, 2).map((b) => b.textContent)).toEqual(["All", "Owe reply 2"]);
    expect(screen.queryByRole("button", { name: "Inflowwww extras" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Owe reply 2" }));

    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(await rowOf("Fixture Fan One")).toBeInTheDocument();
    expect(await rowOf("Fixture Fan Two")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fixture Fan Four/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Owe reply 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("2 owed · scanned all 4")).toBeInTheDocument();
  });

  it("All Models keeps filling Owe reply while a Creator's pages fail", async () => {
    scopeKind = "all";
    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    routeRelay("/api/of/v2/chats?", (path, ctx) => {
      if (ctx?.accountId === OTHER_ACCOUNT.id) throw new Error("upstream 429");
      const offset = Number(new URLSearchParams(path.split("?")[1]).get("offset"));
      return offset === 0
        ? { list: [CHATS[0]], hasMore: true }
        : { list: [CHATS[1]], hasMore: false };
    });
    const user = userEvent.setup();
    renderFanList();
    await rowOf("Fixture Fan One");

    await user.click(screen.getByRole("button", { name: "Owe reply 1" }));

    expect(await rowOf("Fixture Fan Two")).toBeInTheDocument();
    expect(chatRequests().map(([path]) => path)).toEqual([pageUrl(0), pageUrl(0), pageUrl(25), pageUrl(25)]);
  });

  it("shows the owe dot only while Owe reply is the active filter", async () => {
    const chats = [CHATS[0], { ...CHATS[1], hasUnread: false, unreadMessagesCount: 0 }, CHATS[2]];
    const oweDots = () => screen.queryAllByRole("img", { name: "Read · awaiting your reply" });
    const user = userEvent.setup();
    serveChats(chats);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(oweDots()).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Owe reply 2" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(oweDots()).toHaveLength(1);
    within(await rowOf("Fixture Fan Two")).getByRole("img", { name: "Read · awaiting your reply" });
  });

  it("shows the \"All inboxes\" selector for one Creator and in All Models", async () => {
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();

    cleanup();
    scopeKind = "all";
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();
    expect(within(filterRow()).getByRole("button", { name: "Inbox settings" })).toBeInTheDocument();
  });

  it("with a folder chip active, unpinning that folder through the folder picker returns the chips to All", async () => {
    const user = userEvent.setup();
    const lists = [{ id: 700000001, name: "Fixture Folder", pinned: true }];
    serveFolders(lists);
    vi.mocked(relay.patch).mockImplementationOnce(async (path, body) => {
      expect(path).toBe("/api/of/v2/lists/700000001/pin-chat");
      lists[0].pinned = (body as { pinned: boolean }).pinned;
      return {};
    });
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await user.click(await screen.findByRole("button", { name: "Folder Fixture Folder" }));
    expect(await screen.findByRole("button", { name: "Folder Fixture Folder 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "Pin lists as chips" }));
    await user.click(screen.getByRole("checkbox", { name: /^Fixture Folder/ }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /^Folder Fixture Folder/ })).not.toBeInTheDocument());
    expect(lists[0].pinned).toBe(false);
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("shows no folder chip and no pencil in All Models", async () => {
    scopeKind = "all";
    serveFolders([{ id: 700000001, name: "Fixture Folder", pinned: true }]);
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    expect(screen.queryByRole("button", { name: /Fixture Folder|Lists|Pin lists/ })).not.toBeInTheDocument();
    expect(relayGet.mock.calls.filter(([path]) => path.startsWith("/api/of/v2/chats/folders"))).toEqual([]);
  });

  it("a Fansly Creator keeps All, Owe reply and Unread, never reads its folders, and its New menu offers only Post", async () => {
    const user = userEvent.setup();
    platform.current = "fansly";
    serveFolders([{ id: 700000001, name: "Fixture Folder", pinned: true }]);
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    const chips = within(screen.getByRole("group", { name: "Fan List filters" })).getAllByRole("button");
    expect(chips.map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual(["All", "Owe reply 2", "Unread 2"]);
    expect(within(filterRow()).queryByRole("button", { name: "Pin lists as chips" })).toBeNull();
    expect(relayGet.mock.calls.filter(([path]) => path.startsWith("/api/of/v2/chats/folders"))).toEqual([]);

    await user.click(within(header()).getByRole("button", { name: "New" }));
    expect(within(newMenu()).getAllByText(/\S/, { selector: "button, a" }).map((e) => e.textContent)).toEqual(["Post"]);
  });

  it("a Creator switch that hides the active chip shows All, and no list request carries the hidden filter", async () => {
    const user = userEvent.setup();
    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    platform.byId = { [OTHER_ACCOUNT.id]: "fansly" };
    serveChats(CHATS);
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");
    await user.click(screen.getByRole("button", { name: "Pinned" }));
    await vi.waitFor(() => expect(chatRequests().map(([p]) => p)).toContain(
      "/api/of/v2/chats?limit=25&offset=0&order=recent&filter=pinned",
    ));
    relayGet.mockClear();

    scopeCreator = OTHER_ACCOUNT.id;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true"));
    await vi.waitFor(() => expect(chatRequests().length).toBeGreaterThan(0));
    expect(chatRequests().map(([p]) => p).filter((p) => String(p).includes("filter="))).toEqual([]);
    expect(screen.queryByRole("button", { name: /^Pinned/ })).toBeNull();
  });

  it("All Models in Fansly mode shows no gated chip and no mass row", async () => {
    const user = userEvent.setup();
    setPlatform("fansly");
    scopeKind = "all";
    ACCOUNTS = [{ ...CREATOR_ACCOUNT, platform: "fansly" }, { ...OTHER_ACCOUNT, platform: "fansly" }];
    serveChats([]);
    renderFanList();
    const chips = within(await screen.findByRole("group", { name: "Fan List filters" })).getAllByRole("button");
    expect(chips.map((b) => (b.textContent ?? "").replace(/\s*\d+$/, ""))).toEqual(["All", "Owe reply", "Unread"]);
    await user.click(within(header()).getByRole("button", { name: "New" }));
    expect(within(newMenu()).getAllByText(/\S/, { selector: "button, a" }).map((e) => e.textContent)).toEqual(["Post"]);
  });

  it("an OnlyFans Creator not loaded yet keeps Pinned, With Tips and Priority, and a picked Pinned stays once she loads", async () => {
    const user = userEvent.setup();
    platform.byId = { [ACCOUNT_ID]: null };
    serveChats(CHATS);
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");
    for (const name of ["Pinned", "With Tips", "Priority"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pinned" }));

    platform.byId = { [ACCOUNT_ID]: "onlyfans" };
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(chatRequests().map(([p]) => p)).toContain(
      "/api/of/v2/chats?limit=25&offset=0&order=recent&filter=pinned",
    ));
    expect(screen.getByRole("button", { name: /^Pinned/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("All Models with no accounts loaded yet keeps Pinned, With Tips and Priority, and a picked Pinned stays once they fill in", async () => {
    const user = userEvent.setup();
    scopeKind = "all";
    ACCOUNTS = [];
    serveChats(CHATS);
    const { rerender } = renderFanList();
    const chipRow = await screen.findByRole("group", { name: "Fan List filters" });
    for (const name of ["Pinned", "With Tips", "Priority"]) expect(within(chipRow).getByRole("button", { name })).toBeInTheDocument();
    await user.click(within(chipRow).getByRole("button", { name: "Pinned" }));

    ACCOUNTS = [CREATOR_ACCOUNT];
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await rowOf("Fixture Fan Three");
    expect(screen.getByRole("button", { name: /^Pinned/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  });

  it("the header shows the Creator's name and the search icon, and reads \"All Models\" in all scope", async () => {
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(within(header()).getByRole("heading")).toHaveTextContent(/^Test Creator$/);
    expect(header()).toHaveTextContent(/^Test Creator$/);
    expect(within(header()).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Gallery", "Search", "New"]);

    cleanup();
    scopeKind = "all";
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(within(header()).getByRole("heading")).toHaveTextContent(/^All Models$/);
    expect(header()).toHaveTextContent(/^All Models$/);
  });

  it("the header's gallery is disabled with no Fan open, and with one open opens that Fan's Chat gallery, asking the relay for nothing until clicked (ticket 138)", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    const gallery = within(header()).getByRole("button", { name: "Gallery" });
    expect(gallery).toBeDisabled();
    expect(tooltipOf(gallery)).toBe("Open a conversation to browse its media");
    await user.click(gallery);
    expect(screen.queryByRole("dialog", { name: "Chat gallery" })).not.toBeInTheDocument();

    cleanup();
    resetComposerHarness();
    vi.stubGlobal("IntersectionObserver", observerStub);
    serveChats(CHATS);
    routeRelay(`/api/of/v2/chats/${FANS[1].id}/media?`, () => ({ list: [], hasMore: false }));
    const selected: FanListSelection = { accountId: ACCOUNT_ID, fanId: FANS[1].id, chat: CHATS[1] };
    renderFanList({ selected });
    await rowOf("Fixture Fan Three");
    const requested = () => [...new Set([...relayGet.mock.calls, ...relayPost.mock.calls].map(([path]) => path))].sort();
    await vi.waitFor(() => expect(requested()).toEqual(LOAD_URLS));
    const open = within(header()).getByRole("button", { name: "Gallery" });
    expect(open).toBeEnabled();
    expect(tooltipOf(open)).toBe("Chat gallery");
    await user.click(open);
    expect(screen.getByRole("dialog", { name: "Chat gallery" })).toBeInTheDocument();
    await vi.waitFor(() => expect(relayGet.mock.calls
      .filter(([path]) => path.startsWith(`/api/of/v2/chats/${FANS[1].id}/media?`))
      .map((call) => ((call as unknown[])[1] as { accountId?: string } | undefined)?.accountId)).toEqual([ACCOUNT_ID]));
  });

  it("on a Fansly Creator the header has no Gallery, with or without a Fan open", async () => {
    platform.current = "fansly";
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(within(header()).queryByRole("button", { name: "Gallery" })).toBeNull();

    cleanup();
    resetComposerHarness();
    vi.stubGlobal("IntersectionObserver", observerStub);
    serveChats(CHATS);
    renderFanList({ selected: { accountId: ACCOUNT_ID, fanId: FANS[1].id, chat: CHATS[1] } });
    await rowOf("Fixture Fan Three");
    expect(within(header()).queryByRole("button", { name: "Gallery" })).toBeNull();
    expect(within(header()).getByRole("button", { name: "Search" })).toBeInTheDocument();
  });

  it("the header's Chat gallery stays on the Fan it was opened for when the open Fan changes or closes (ticket 138)", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    for (const fan of [FANS[1], FANS[2]]) routeRelay(`/api/of/v2/chats/${fan.id}/media?`, () => ({ list: [], hasMore: false }));
    const fanA: FanListSelection = { accountId: ACCOUNT_ID, fanId: FANS[1].id, chat: CHATS[1] };
    const fanB: FanListSelection = { accountId: ACCOUNT_ID, fanId: FANS[2].id, chat: CHATS[2] };
    const { rerender } = renderFanList({ selected: fanA });
    await rowOf("Fixture Fan Three");
    await user.click(within(header()).getByRole("button", { name: "Gallery" }));
    expect(screen.getByRole("dialog", { name: "Chat gallery" })).toBeInTheDocument();
    const mediaOf = (fan: (typeof FANS)[number]) =>
      relayGet.mock.calls.filter(([path]) => path.startsWith(`/api/of/v2/chats/${fan.id}/media?`));
    await vi.waitFor(() => expect(mediaOf(FANS[1])).toHaveLength(1));

    rerender(<FanList selected={fanB} onSelect={vi.fn()} />);
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Chat gallery" })).toBeInTheDocument();
    expect(mediaOf(FANS[1])).toHaveLength(1);
    rerender(<FanList selected={fanB} onSelect={vi.fn()} />);
    await rowOf("Fixture Fan Three");
    expect(screen.getByRole("dialog", { name: "Chat gallery" })).toBeInTheDocument();
    expect(mediaOf(FANS[1])).toHaveLength(1);
    expect(mediaOf(FANS[2])).toEqual([]);
  });

  it("the search icon opens the input row with focus in it, typing narrows the rows by name, and Escape closes the row", async () => {
    const user = userEvent.setup();
    serveChatsSearchable(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(screen.queryByPlaceholderText("Search…")).not.toBeInTheDocument();

    const search = within(header()).getByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("aria-expanded", "false");
    await user.click(search);
    expect(search).toHaveAttribute("aria-expanded", "true");
    const input = screen.getByPlaceholderText("Search…");
    expect(input).toHaveFocus();

    await user.type(input, "Two");
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Fixture Fan One/ })).not.toBeInTheDocument();
    expect(await rowOf("Fixture Fan Two")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByPlaceholderText("Search…")).not.toBeInTheDocument();
    expect(search).toHaveAttribute("aria-expanded", "false");
    expect(search).toHaveFocus();
    expect(await rowOf("Fixture Fan One")).toBeInTheDocument();
    expect(await rowOf("Fixture Fan Three")).toBeInTheDocument();

    await user.click(search);
    await user.type(screen.getByPlaceholderText("Search…"), "T");
    await user.clear(screen.getByPlaceholderText("Search…"));
    expect(screen.queryByPlaceholderText("Search…")).not.toBeInTheDocument();
    expect(search).toHaveAttribute("aria-expanded", "false");
  });

  it("a name typed fast is one search: the box's text, trimmed, once typing rests SEARCH_DEBOUNCE_MS", async () => {
    const user = userEvent.setup();
    serveChatsSearchable(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    await user.click(within(header()).getByRole("button", { name: "Search" }));

    await user.type(screen.getByPlaceholderText("Search…"), "  Fan Two ");
    const searches = () => chatRequests().map(([path]) => new URLSearchParams(String(path).split("?")[1]).get("query"))
      .filter((q) => q !== null);
    expect(searches()).toEqual([]);
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    expect(await rowOf("Fixture Fan Two")).toBeInTheDocument();
    expect(searches()).toEqual(["Fan Two"]);
    await new Promise((r) => setTimeout(r, SEARCH_DEBOUNCE_MS * 2));
    expect(searches()).toEqual(["Fan Two"]);
  });

  it("a search still in flight when the box holds another is aborted, and the newer one's rows show", async () => {
    const user = userEvent.setup();
    const queryOf = (path: string) => new URLSearchParams(path.split("?")[1]).get("query");
    routeRelay("/api/of/v2/chats?", (path) => queryOf(path) === "Fan" ? new Promise(() => {}) : {
      list: CHATS.filter((c) => String(c.withUser.name).toLowerCase().includes((queryOf(path) ?? "").toLowerCase())),
      hasMore: false,
    });
    renderFanList();
    await rowOf("Fixture Fan Three");
    await user.click(within(header()).getByRole("button", { name: "Search" }));
    const input = screen.getByPlaceholderText("Search…");

    await user.type(input, "Fan");
    const first = () => relayGet.mock.calls.find(([path]) => path.startsWith("/api/of/v2/chats?") && queryOf(path) === "Fan");
    await vi.waitFor(() => expect(first()).toBeDefined());
    const signal = first()![2];
    expect(signal?.aborted).toBe(false);

    await user.type(input, " Th");
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Two/ })).not.toBeInTheDocument());
    expect(await rowOf("Fixture Fan Three")).toBeInTheDocument();
    expect(signal?.aborted).toBe(true);
  });

  it("a list without a search is not aborted when it is switched away from", async () => {
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    const listCalls = relayGet.mock.calls.filter(([path]) => path.startsWith("/api/of/v2/chats?"));
    expect(listCalls.length).toBeGreaterThan(0);
    expect(listCalls.every((call) => call[2] === undefined)).toBe(true);
  });

  it("the header's \"+\" opens the New menu: \"Mass message\", \"Message online fans\" and \"Post\", in that order", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");
    expect(screen.queryByRole("region", { name: "New" })).not.toBeInTheDocument();

    const plus = within(header()).getByRole("button", { name: "New" });
    expect(plus).toHaveAttribute("aria-expanded", "false");
    await user.click(plus);
    expect(plus).toHaveAttribute("aria-expanded", "true");
    const rows = within(newMenu()).getAllByText(/\S/, { selector: "button, a" });
    expect(rows.map((r) => r.textContent)).toEqual(["Mass message", "Message online fans", "Post"]);
    expect(within(newMenu()).queryByRole("separator")).not.toBeInTheDocument();
  });

  it("\"Mass message\" opens the mass-message composer for the Creator in scope with its all-models switch, and \"Message online fans\" opens it in online mode", async () => {
    const user = userEvent.setup();
    ACCOUNTS = [OTHER_ACCOUNT, CREATOR_ACCOUNT];
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await user.click(within(header()).getByRole("button", { name: "New" }));
    await user.click(within(newMenu()).getByRole("button", { name: "Mass message" }));
    expect(await screen.findByRole("heading", { name: "New mass message" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "New" })).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Test Creator")).toHaveValue(ACCOUNT_ID);
    expect(screen.getByRole("checkbox", { name: /^Broadcast from ALL models/ })).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "New mass message" })).not.toBeInTheDocument();

    await user.click(within(header()).getByRole("button", { name: "New" }));
    await user.click(within(newMenu()).getByRole("button", { name: "Message online fans" }));
    expect(await screen.findByRole("heading", { name: "New Mass Online message" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "New mass message" })).not.toBeInTheDocument();

    cleanup();
    scopeKind = "all";
    serveChats(CHATS);
    renderFanList();
    await screen.findAllByRole("button", { name: /Fixture Fan Three/ });
    await user.click(within(header()).getByRole("button", { name: "New" }));
    await user.click(within(newMenu()).getByRole("button", { name: "Mass message" }));
    expect(await screen.findByRole("heading", { name: "New mass message" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Other Creator")).toHaveValue(OTHER_ACCOUNT.id);
  });

  it("\"Post\" goes to OF Manager's New post page", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await user.click(within(header()).getByRole("button", { name: "New" }));
    const post = within(newMenu()).getByRole("link", { name: "Post" });
    expect(post).toHaveAttribute("href", "/of-manager/new-post");
    expect(post).toHaveAttribute("target", "_blank");
  });

  it("the New menu ends at \"Post\", with no divider and no Broadcast link", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await user.click(within(header()).getByRole("button", { name: "New" }));
    const rows = within(newMenu()).getAllByText(/\S/, { selector: "button, a" });
    expect(rows.map((r) => r.textContent)).toEqual(["Mass message", "Message online fans", "Post"]);
    expect(within(newMenu()).queryAllByRole("separator")).toHaveLength(0);
    expect(within(newMenu()).queryByRole("link", { name: "Broadcast" })).not.toBeInTheDocument();
  });

  it("🔥 end to end: a recent \"Payment for message from\" row lights its Fan's row, and a tip or an undone PPV does not", async () => {
    serveChats(CHATS);
    serveTransactions([
      { fan: FANS[0], description: "Payment for message from ", status: "done" },
      { fan: FANS[1], description: "Tip from ", status: "done" },
      { fan: FANS[2], description: "Payment for message from ", status: "undo" },
    ]);
    renderFanList();

    await vi.waitFor(() => expect(fire("Fixture Fan One")).toBeInTheDocument());
    expect(fire("Fixture Fan Two")).not.toBeInTheDocument();
    expect(fire("Fixture Fan Three")).not.toBeInTheDocument();
  });

  it("🔥 also lights for a \"Message from\" row, and not for a PPV pending return", async () => {
    serveChats(CHATS);
    serveTransactions([
      { fan: FANS[0], description: "Message from ", status: "done" },
      { fan: FANS[1], description: "Payment for message from ", status: "pending_return" },
    ]);
    renderFanList();

    await vi.waitFor(() => expect(fire("Fixture Fan One")).toBeInTheDocument());
    expect(fire("Fixture Fan Two")).not.toBeInTheDocument();
    expect(fire("Fixture Fan Three")).not.toBeInTheDocument();
  });

  it("shows spend-batch's known zero as \"$0\", a spender's Total spend in the pill under the avatar, and nothing for a Fan spend-batch has no entry for", async () => {
    serveChats(CHATS);
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => ({
      spend: {
        [FANS[0].id]: { spend_cents: 1_248_000, last_purchase_at: null, subscription_status: "active", expired_at: null },
        [FANS[1].id]: { spend_cents: 0, last_purchase_at: null, subscription_status: "active", expired_at: null },
      },
    }));
    renderFanList();

    const two = await rowOf("Fixture Fan Two");
    await vi.waitFor(() => expect(within(two).getByText("$0", { exact: true })).toBeInTheDocument());
    expect(within(await rowOf("Fixture Fan One")).getByText("$12.5k", { exact: true })).toBeInTheDocument();
    expect(within(await rowOf("Fixture Fan Three")).queryByText(/^\$/)).not.toBeInTheDocument();
  });

  it("a recent buy in the ledger without a spend-batch entry keeps the photo and no pill, and the pill appears under the photo once spend-batch answers", async () => {
    serveChats(CHATS.map((c, i) => (i === 2 ? { ...c, withUser: { ...c.withUser, avatar: "https://example.invalid/fan-three.jpg" } } : c)));
    serveTransactions([{ fan: FANS[2], description: "Payment for message from ", status: "done" }]);
    let answer: (body: unknown) => void = () => {};
    const held = new Promise((resolve) => { answer = resolve; });
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => held);
    renderFanList();

    await vi.waitFor(() => expect(fire("Fixture Fan Three")).toBeInTheDocument());
    const three = await rowOf("Fixture Fan Three");
    expect(within(three).getByRole("presentation")).toBeInTheDocument();
    expect(within(three).queryByText(/^\$/)).not.toBeInTheDocument();

    answer({ spend: { [FANS[2].id]: { spend_cents: 0, last_purchase_at: null, subscription_status: "active", expired_at: null } } });
    await vi.waitFor(() => expect(within(screen.getByRole("button", { name: /Fixture Fan Three/ })).getByText("$25", { exact: true })).toBeInTheDocument());
    expect(within(screen.getByRole("button", { name: /Fixture Fan Three/ })).getByRole("presentation")).toBeInTheDocument();
  });
  it("an empty response shows \"No conversations found\", with no Refresh button of its own", async () => {
    serveChats([]);
    renderFanList();

    expect(await screen.findByText("No conversations found")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Refresh/ }))
      .toEqual([within(filterRow()).getByRole("button", { name: "Refresh inbox" })]);
  });

  it("with more pages to load, the list ends in \"Load more conversations\" with the loaded count in its tooltip, and clicking it requests the next page", async () => {
    const user = userEvent.setup();
    const fanFour = {
      withUser: { id: 200000004, name: "Fixture Fan Four", username: "fixturefanfour", avatar: null },
      lastMessage: { id: 800000003, text: "Hello from Fixture Fan Four", fromUser: CREATOR, createdAt: ago(90) },
      hasUnread: false,
      unreadMessagesCount: 0,
    } as OFChatItem;
    routeRelay("/api/of/v2/chats?", (path) => (new URLSearchParams(path.split("?")[1]).get("offset") === "0"
      ? { list: CHATS, hasMore: true }
      : { list: [fanFour], hasMore: false }));
    renderFanList();

    await rowOf("Fixture Fan Three");
    const loadMore = screen.getByRole("button", { name: "Load more conversations" });
    expect(tooltipOf(loadMore)).toBe("3 chats loaded");
    relayGet.mockClear();
    await user.click(loadMore);

    await vi.waitFor(() => expect(chatRequests()).toEqual([
      ["/api/of/v2/chats?limit=25&offset=25&order=recent", { refresh: false }],
    ]));
    expect(await rowOf("Fixture Fan Four")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more conversations" })).not.toBeInTheDocument();
  });

  it("a page of All still loading when Unread is picked never lands in Unread's list", async () => {
    const user = userEvent.setup();
    let answerPageTwo: (page: { list: OFChatItem[]; hasMore: boolean }) => void = () => {};
    routeRelay("/api/of/v2/chats?", (path) => {
      const params = new URLSearchParams(path.split("?")[1]);
      if (params.get("filter") === "unread") return { list: [CHATS[0]], hasMore: false };
      return params.get("offset") === "0"
        ? { list: CHATS, hasMore: true }
        : new Promise((resolve) => { answerPageTwo = resolve; });
    });
    renderFanList();
    await rowOf("Fixture Fan Three");
    await user.click(screen.getByRole("button", { name: "Load more conversations" }));
    await vi.waitFor(() => expect(chatRequests().map(([p]) => p)).toContain(pageUrl(25)));

    await user.click(screen.getByRole("button", { name: "Unread 2" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    await act(async () => answerPageTwo({ list: [answered(FAN_FOUR, 90)], hasMore: false }));
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(shownFans()).toEqual(["Fixture Fan One"]);
  });

  it("a page of All still loading when Unread is picked is on All's list once All is picked again", async () => {
    const user = userEvent.setup();
    let answerPageTwo: (page: { list: OFChatItem[]; hasMore: boolean }) => void = () => {};
    routeRelay("/api/of/v2/chats?", (path) => {
      const params = new URLSearchParams(path.split("?")[1]);
      if (params.get("filter") === "unread") return { list: [CHATS[0]], hasMore: false };
      return params.get("offset") === "0"
        ? { list: CHATS, hasMore: true }
        : new Promise((resolve) => { answerPageTwo = resolve; });
    });
    renderFanList();
    await rowOf("Fixture Fan Three");
    await user.click(screen.getByRole("button", { name: "Load more conversations" }));
    await vi.waitFor(() => expect(chatRequests().map(([p]) => p)).toContain(pageUrl(25)));

    await user.click(screen.getByRole("button", { name: "Unread 2" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Fixture Fan Three/ })).not.toBeInTheDocument());
    await act(async () => answerPageTwo({ list: [answered(FAN_FOUR, 90)], hasMore: false }));
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(await rowOf("Fixture Fan Four")).toBeInTheDocument();
  });

  it("another Creator whose first page is still loading shows none of the Creator left behind's rows", async () => {
    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    routeRelay("/api/of/v2/chats?", (_path, ctx) => (ctx?.accountId === OTHER_ACCOUNT.id
      ? new Promise(() => {})
      : { list: CHATS, hasMore: false }));
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");

    scopeCreator = OTHER_ACCOUNT.id;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(relayGet.mock.calls.some(([p, c]) =>
      p.startsWith("/api/of/v2/chats?") && c?.accountId === OTHER_ACCOUNT.id)).toBe(true));
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(shownFans()).toEqual([]);
  });

  it("All Models: when the set of models changes, the new list waits for a scroll before paging, as any new list does", async () => {
    scopeKind = "all";
    routeRelay("/api/of/v2/chats?", (path) => (new URLSearchParams(path.split("?")[1]).get("offset") === "0"
      ? { list: CHATS, hasMore: true }
      : { list: [], hasMore: true }));
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");
    const reachEnd = () => {
      const [cb] = observerStub.mock.calls.at(-1) as unknown as [IntersectionObserverCallback];
      act(() => cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    };
    const pagedOn = () => chatRequests().filter(([path]) => !String(path).includes("offset=0"));

    const sentinel = (observerStub.mock.results.at(-1)!.value as { observe: { mock: { calls: unknown[][] } } })
      .observe.mock.calls[0][0] as HTMLElement;
    const scroller = sentinel.parentElement!;
    Object.defineProperty(scroller, "scrollTop", { configurable: true, value: 40 });
    fireEvent.scroll(scroller);
    reachEnd();
    await vi.waitFor(() => expect(pagedOn()).not.toEqual([]));

    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    relayGet.mockClear();
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(chatRequests()).not.toEqual([]));
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    reachEnd();
    await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
    expect(pagedOn()).toEqual([]);
  });

  it("rendering the fixture rows asks the relay for the same URLs as before the row restyle, and none naming a read row's Fan until a row is hovered or pressed", async () => {
    serveChats(CHATS);
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => ({
      spend: { [FANS[0].id]: { spend_cents: 4_500, last_purchase_at: null, subscription_status: "active", expired_at: null } },
    }));
    renderFanList();
    await rowOf("Fixture Fan Three");
    await vi.waitFor(() => expect(within(screen.getByRole("button", { name: /Fixture Fan One/ })).getByText("$45", { exact: true })).toBeInTheDocument());

    const requested = () => [...new Set([...relayGet.mock.calls, ...relayPost.mock.calls].map(([path]) => path))].sort();
    const fanIds = FANS.map((f) => String(f.id));
    await vi.waitFor(() => expect(requested().filter((path) => fanIds.filter((id) => path.includes(id)).length === 1)).toEqual(UNREAD_WARM_URLS));
    expect(requested()).toEqual(LOAD_URLS);

    fireEvent.pointerDown(screen.getByRole("button", { name: /Fixture Fan Three/ }));
    await vi.waitFor(() => expect(requested().filter((path) => path.includes(fanIds[2]) && !path.includes(fanIds[0])).length).toBeGreaterThan(0));
  });

  function serveUnreadFans(name: string, firstId: number, n: number, { restrictFirst = false } = {}) {
    const fans = Array.from({ length: n }, (_, i) => ({
      id: firstId + i, name: `${name} ${i + 1}`, username: `${name.replace(/ /g, "").toLowerCase()}${i + 1}`,
    }));
    serveChats(fans.map((f, i) => ({
      withUser: { ...f, avatar: null, isRestricted: restrictFirst && i === 0, badgeExcluded: restrictFirst && i === 0 },
      lastMessage: { id: 600_000_000 + f.id, text: `Hello from ${f.name}`, fromUser: f, createdAt: ago(10 + i) },
      hasUnread: true,
      unreadMessagesCount: 1,
    } as OFChatItem)));
    return fans;
  }
  const spend = (cents: number) => ({ spend_cents: cents, last_purchase_at: null, subscription_status: "active", expired_at: null });
  const warmed = () => relayGet.mock.calls.map(([path]) => /\/chats\/(\d+)\/messages/.exec(path)?.[1]).filter(Boolean);

  it("warms the top unread threads in the order the sort shows, skipping a Fan we restricted", async () => {
    localStorage.setItem("chatterly:chat-sort-mode", "spend");
    const fans = serveUnreadFans("Sorted Fan", 200000101, 9, { restrictFirst: true });
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => ({ spend: { [fans[8].id]: spend(9_900) } }));
    renderFanList();
    await rowOf("Sorted Fan 9");

    await vi.waitFor(() => expect(warmed()).toContain(String(fans[8].id)));
    expect(warmed()).not.toContain(String(fans[0].id));
  });

  it("a spend sort warms nothing until spend has landed, then only the order it settles on", async () => {
    localStorage.setItem("chatterly:chat-sort-mode", "spend");
    const fans = serveUnreadFans("Spender", 200000201, 5);
    let answer: (body: unknown) => void = () => {};
    const held = new Promise((resolve) => { answer = resolve; });
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => held);
    renderFanList();
    await rowOf("Spender 5");
    await vi.waitFor(() => expect(relayGet.mock.calls.some(([path]) => path.includes("/payouts/transactions"))).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(warmed()).toEqual([]);

    answer({ spend: { [fans[4].id]: spend(9_900), [fans[3].id]: spend(5_000) } });
    await vi.waitFor(() => expect(warmed()).toHaveLength(3));
    await new Promise((r) => setTimeout(r, 50));
    expect(warmed()).toEqual([fans[4], fans[3], fans[0]].map((f) => String(f.id)));
  });

  it("a spend re-key does not abort an idle tier's warm in flight, and an activity refetch does not hold the next", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    localStorage.setItem("chatterly:chat-sort-mode", "spend");
    const fans = serveUnreadFans("Spender", 200000301, 5);
    const spendBody = { spend: { [fans[4].id]: spend(9_900), [fans[3].id]: spend(5_000) } };
    let spendReads = 0;
    let answerSpend = (_body: unknown) => {};
    routeRelay(`/admin/fans/${ACCOUNT_ID}/spend-batch`, () => (spendReads++ === 0
      ? spendBody
      : new Promise((r) => { answerSpend = r; })));
    let activityReads = 0;
    routeRelay("/api/of/v2/payouts/transactions", () => (activityReads++ === 0
      ? { list: [], hasMore: false }
      : new Promise(() => {})));
    let land = (_body: unknown) => {};
    routeRelay(`/chats/${fans[1].id}/messages`, () => new Promise((r) => { land = r; }));
    const { queryClient } = renderWithProviders(withRealtime());
    await rowOf("Spender 5");
    await vi.waitFor(() => expect(warmed()).toHaveLength(3));

    await act(async () => { await vi.advanceTimersByTimeAsync(PREFETCH_QUIET_MS + PREFETCH_IDLE_TIMEOUT_MS + 100); });
    await vi.waitFor(() => expect(warmed()).toContain(String(fans[1].id)));
    const warm = relayGet.mock.calls.find(([path]) => path.includes(`/chats/${fans[1].id}/messages`))?.[2] as AbortSignal;

    fanWrites(FAN_FOUR, 800000040, "Hello from Fixture Fan Four", new Date().toISOString());
    await vi.waitFor(() => expect(spendReads).toBe(2));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(warm.aborted).toBe(false);
    await act(async () => { answerSpend(spendBody); });

    void queryClient.invalidateQueries({ queryKey: ["last-purchases"] });
    await vi.waitFor(() => expect(activityReads).toBe(2));
    await act(async () => { land({ list: [], hasMore: false }); });
    await vi.waitFor(() => expect(warmed()).toContain(String(fans[2].id)));
    expect(warm.aborted).toBe(false);
  });

  it("pressing a row warms its thread over what is cached, on the user lane (the click's start), as a peek: a paged history stays", async () => {
    serveChats(CHATS);
    const fan = FANS[2];
    routeRelay(`/api/of/v2/chats/${fan.id}/messages`, () => ({
      list: [{ id: 900, text: "newest", fromUser: { id: fan.id }, createdAt: ago(1) }], hasMore: true,
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = ["messages", ACCOUNT_ID, fan.id];
    client.setQueryData(key, [{ id: 10, text: "paged older", fromUser: { id: fan.id }, createdAt: ago(600) }],
      { updatedAt: Date.now() - 60_000 });
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, client);

    fireEvent.pointerDown(await rowOf("Fixture Fan Three"));
    await vi.waitFor(() => expect(client.getQueryData<{ id: number }[]>(key)?.map((m) => m.id)).toEqual([10, 900]));
    const press = relayGet.mock.calls.find(([path]) => path.includes(`/chats/${fan.id}/messages`));
    expect(press?.[1]).toMatchObject({ priority: undefined });
    expect(press?.[0]).toContain("peek=1");
  });

  it("resting the pointer on a row warms its thread on the background lane, as a peek (a hover is not a click)", async () => {
    serveChats(CHATS);
    const fan = FANS[2];
    routeRelay(`/api/of/v2/chats/${fan.id}/messages`, () => ({ list: [], hasMore: false }));
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />);

    fireEvent.mouseEnter(await rowOf("Fixture Fan Three"));
    await vi.waitFor(() => expect(relayGet.mock.calls.find(([path]) => path.includes(`/chats/${fan.id}/messages`))?.[1])
      .toMatchObject({ priority: "background" }));
    expect(relayGet.mock.calls.filter(([path]) => path.includes(`/chats/${fan.id}/messages`)).map(([path]) => path))
      .toEqual([`/api/of/v2/chats/${fan.id}/messages?limit=30&order=desc&peek=1`]);
  });

  it("pressing a row and then clicking it reads its thread once: the opened chat joins the press's warm-up", async () => {
    serveChats(CHATS);
    const fan = FANS[2];
    const lands: Array<(body: unknown) => void> = [];
    routeRelay(`/api/of/v2/chats/${fan.id}/messages`, () => new Promise((r) => { lands.push(r); }));
    function Thread({ sel }: { sel: FanListSelection }) {
      useChatMessages({ accountId: sel.accountId, fanId: sel.fanId });
      return null;
    }
    function Inbox() {
      const [sel, setSel] = useState<FanListSelection | null>(null);
      return (
        <>
          <FanList selected={sel} onSelect={setSel} />
          {sel && <Thread sel={sel} />}
        </>
      );
    }
    renderWithProviders(<Inbox />);

    const row = await rowOf("Fixture Fan Three");
    fireEvent.pointerDown(row);
    fireEvent.click(row);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    lands.forEach((land) => land({ list: [{ id: 900, text: "newest", fromUser: { id: fan.id }, createdAt: ago(1) }], hasMore: false }));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(relayGet.mock.calls.filter(([path]) => path.includes(`/chats/${fan.id}/messages`))).toHaveLength(1);
  });

  it("a cold load shows six skeleton rows until the chats arrive", async () => {
    let answer: (body: unknown) => void = () => {};
    const held = new Promise((resolve) => { answer = resolve; });
    routeRelay("/api/of/v2/chats?", () => held);
    renderFanList();

    const skeleton = await screen.findByRole("list", { name: "Loading conversations" });
    expect(within(skeleton).getAllByRole("listitem")).toHaveLength(6);

    answer({ list: CHATS, hasMore: false });
    await rowOf("Fixture Fan Three");
    expect(screen.queryByRole("list", { name: "Loading conversations" })).not.toBeInTheDocument();
  });

  it("the gear offers no Focus mode, and the rows follow the live order cut by Online Fans: a Fan's new message moves its row at once, with no \"new messages\" banner", async () => {
    const user = userEvent.setup();
    serveChats(CHATS);
    const online = new Set([String(FANS[0].id), String(FANS[2].id)]);
    renderWithProviders(
      <>
        <InboxRealtime />
        <FanList selected={null} onSelect={vi.fn()} onlineOnly onlineIds={online} />
      </>,
    );
    await rowOf("Fixture Fan Three");
    expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Three"]);

    await openSettings(user);
    const menu = screen.getByRole("region", { name: "Inbox settings" });
    expect(within(menu).getAllByRole("checkbox").map((b) => b.closest("label")?.textContent)).toEqual([
      "Keep fan info panel open", "Blur images till hover", "Blur images constant", "Compact media previews",
    ]);
    expect(within(menu).queryByText(/Focus|Pause incoming|Hide chats with muted|Only in All/)).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    fanWrites(FANS[2], 800000010, "Are you there?", new Date().toISOString());
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Three", "Fixture Fan One"]));
    expect(within(await rowOf("Fixture Fan Three")).getByText("Are you there?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new messages/ })).not.toBeInTheDocument();
  });

  describe("choosing a group in \"All inboxes\"", () => {
    it("choosing \"Inbox 2\" leaves only that group's rows and the selector reads it; \"All inboxes\" brings every row back", async () => {
      serveSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2 });
      serveChats(CHATS);
      const user = userEvent.setup();
      renderFanList();
      await rowOf("Fixture Fan Three");

      await chooseInbox(user, "Inbox 2");
      await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]));
      expect(within(filterRow()).getByRole("button", { name: "Inbox 2" })).toBeInTheDocument();

      await chooseInbox(user, "All inboxes", "Inbox 2");
      await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
      expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();
    });

    it("in All Models, \"Inbox 1\" is group 1 of every Creator's own split, not a set of Creators", async () => {
      scopeKind = "all";
      ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
      const splits: Record<string, { group_count: number; assignments: Record<string, number> }> = {
        [ACCOUNT_ID]: { group_count: 2, assignments: { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2 } },
        [OTHER_ACCOUNT.id]: { group_count: 3, assignments: { [FAN_FOUR.id]: 2, [FAN_FIVE.id]: 1 } },
      };
      routeRelay("/admin/split-inbox?", (path) => {
        const aid = new URLSearchParams(path.split("?")[1]).get("account_id")!;
        return { account_id: aid, config: splits[aid] };
      });
      routeRelay("/api/of/v2/chats?", (path, ctx) => ({
        list: (new URLSearchParams(path.split("?")[1]).get("offset") ?? "0") !== "0" ? []
          : ctx?.accountId === OTHER_ACCOUNT.id ? [answered(FAN_FOUR, 30), answered(FAN_FIVE, 40)] : CHATS,
        hasMore: false,
      }));
      const user = userEvent.setup();
      renderFanList();
      await rowOf("Fixture Fan Five");

      await chooseInbox(user, "Inbox 1");
      await vi.waitFor(() => expect(shownFans().sort()).toEqual(["Fixture Fan Five", "Fixture Fan One"]));
      await chooseInbox(user, "Inbox 2", "Inbox 1");
      await vi.waitFor(() => expect(shownFans().sort())
        .toEqual(["Fixture Fan Four", "Fixture Fan Three", "Fixture Fan Two"]));
      await chooseInbox(user, "Inbox 3", "Inbox 2");
      await vi.waitFor(() => expect(shownFans()).toEqual([]));
    });

    it("with no match on the first page, the list keeps asking the relay for pages until the group's Fan beyond page one shows", async () => {
      serveSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 1, [FANS[2].id]: 1, [FAN_FOUR.id]: 2 });
      let answerPageTwo: (body: unknown) => void = () => {};
      const pageTwo = new Promise((resolve) => { answerPageTwo = resolve; });
      routeRelay("/api/of/v2/chats?", (path) => (new URLSearchParams(path.split("?")[1]).get("offset") === "0"
        ? { list: CHATS, hasMore: true }
        : pageTwo));
      const user = userEvent.setup();
      renderFanList();
      await rowOf("Fixture Fan Three");
      expect(chatRequests()).toEqual([[pageUrl(0), { refresh: false }]]);

      await chooseInbox(user, "Inbox 2");

      await vi.waitFor(() => expect(chatRequests()).toHaveLength(2));
      expect(screen.queryByRole("button", { name: /Fixture Fan/ })).not.toBeInTheDocument();
      expect(screen.queryByText("No conversations found")).not.toBeInTheDocument();
      answerPageTwo({ list: [answered(FAN_FOUR, 90)], hasMore: false });
      expect(await rowOf("Fixture Fan Four")).toBeInTheDocument();
      expect(rowOrder()).toEqual(["Fixture Fan Four"]);
      expect(chatRequests()).toEqual([[pageUrl(0), { refresh: false }], [pageUrl(25), { refresh: false }]]);
    });

    it("when nothing matches, the list scans up to Owe reply's cap, then shows \"No conversations found\" with \"Load more conversations\" under it while more chats exist", async () => {
      const pageFans = (offset: number) => Array.from({ length: 25 }, (_, i) => ({
        id: 300000000 + offset + i, name: `Paged Fan ${offset + i}`, username: `pagedfan${offset + i}`,
      }));
      const inboxOne: Record<string, number> = {};
      for (let offset = 0; offset < 300; offset += 25) for (const f of pageFans(offset)) inboxOne[f.id] = 1;
      serveSplit(2, inboxOne);
      routeRelay("/api/of/v2/chats?", (path) => {
        const offset = Number(new URLSearchParams(path.split("?")[1]).get("offset"));
        return { list: pageFans(offset).map((f) => answered(f, 60 + offset)), hasMore: true };
      });
      const user = userEvent.setup();
      renderFanList();
      await screen.findByText("Paged Fan 24");
      const layout = [
        vi.spyOn(HTMLElement.prototype, "offsetParent", "get").mockReturnValue(document.body),
        vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600),
        vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(0),
      ];
      try {
        await chooseInbox(user, "Inbox 2");

        expect(await screen.findByText("No conversations found")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Load more conversations" })).toBeInTheDocument();
        const [reachedEnd] = observerStub.mock.calls.at(-1) as unknown as [IntersectionObserverCallback];
        act(() => reachedEnd([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
        await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
        expect(chatRequests()).toEqual([0, 25, 50, 75].map((o) => [pageUrl(o), { refresh: false }]));
      } finally {
        layout.forEach((spy) => spy.mockRestore());
      }
    });

    it.each([25, 0])("caps a bound inbox scan when each empty page reports scanned=%i", async (scanned) => {
      routeRelay("/admin/split-inbox?", () => ({
        account_id: ACCOUNT_ID, config: { group_count: 2, assignments: {} }, my_group: 2,
      }));
      routeRelay("/api/of/v2/chats?", (path) => ({
        list: [], scanned,
        hasMore: Number(new URLSearchParams(path.split("?")[1]).get("offset")) < 125,
      }));
      renderFanList();
      await screen.findByText("No conversations found");
      expect(chatRequests()).toEqual([0, 25, 50, 75].map((o) => [pageUrl(o), { refresh: false }]));
    });

    it("a page that fails ends the fill: it is asked for once, and the load error shows", async () => {
      serveSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 1, [FANS[2].id]: 1 });
      routeRelay("/api/of/v2/chats?", (path) => (new URLSearchParams(path.split("?")[1]).get("offset") === "0"
        ? { list: CHATS, hasMore: true }
        : new Promise((_, reject) => setTimeout(() => reject(new Error("upstream 401")), 20))));
      const user = userEvent.setup();
      renderFanList();
      await rowOf("Fixture Fan Three");

      await chooseInbox(user, "Inbox 2");

      expect(await screen.findByText("This account's OnlyFans session expired.")).toBeInTheDocument();
      await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
      expect(chatRequests()).toEqual([[pageUrl(0), { refresh: false }], [pageUrl(25), { refresh: false }]]);
    });
  });

  it("with a group chosen, \"Mark all as read\" marks only that group's unread chats, and is disabled in a group with none", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    serveSplit(3, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 3 });
    serveChats(CHATS);
    renderFanList();
    await rowOf("Fixture Fan Three");

    await chooseInbox(user, "Inbox 3");
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Three"]));
    await openSettings(user);
    expect(screen.getByRole("button", { name: /Mark all as read/ })).toBeDisabled();
    await user.keyboard("{Escape}");

    await chooseInbox(user, "Inbox 2", "Inbox 3");
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Two"]));
    await openSettings(user);
    await user.click(screen.getByText("Mark all as read"));

    expect(confirm).toHaveBeenCalledWith("Mark 1 chat as read?");
    await vi.waitFor(() => expect(relayPost.mock.calls.map(([path]) => path)).toEqual([
      `/api/of/v2/chats/${FANS[1].id}/mark-as-read`,
    ]));
  });

  it("the group ANDs with Unread, so only the group's unread rows show, and the Unread badge count does not change with the group", async () => {
    serveSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2 });
    routeRelay("filter=unread", () => ({ list: [CHATS[0], CHATS[1]], hasMore: false }));
    serveChats(CHATS);
    const user = userEvent.setup();
    renderWithProviders(<FanList selected={null} onSelect={vi.fn()} />, new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await rowOf("Fixture Fan Three");

    await chooseInbox(user, "Inbox 2");
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]));
    expect(screen.getByRole("button", { name: "Unread 2" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unread 2" }));
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Two"]));
    expect(screen.getByRole("button", { name: "Unread 2" })).toBeInTheDocument();
  });

  it("in a chatter-only session the group entries are offered and filter the rows, with no \"Split Inbox settings\"; changing the Creator returns the selector to \"All inboxes\"", async () => {
    chatterOnly = true;
    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    serveSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2, [FAN_FOUR.id]: 1, [FAN_FIVE.id]: 2 });
    const otherChats = [answered(FAN_FIVE, 10), answered(FAN_FOUR, 11)];
    serveChats(() => (scopeCreator === ACCOUNT_ID ? CHATS : otherChats));
    const user = userEvent.setup();
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");

    await user.click(within(filterRow()).getByRole("button", { name: "All inboxes" }));
    const menu = screen.getByRole("region", { name: "Inboxes" });
    await vi.waitFor(() => expect(within(menu).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["All inboxes", "Inbox 1", "Inbox 2"]));
    await user.click(within(menu).getByRole("button", { name: "Inbox 2" }));
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]));

    scopeCreator = OTHER_ACCOUNT.id;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Five", "Fixture Fan Four"]));
    expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();
    scopeCreator = ACCOUNT_ID;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();
  });

  it("an owner moves Fan One to \"Inbox 2\" and saves; \"Inbox 2\" then shows Fan One, and \"Inbox 1\" does not", async () => {
    const put = serveSavableSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2 });
    serveChats(CHATS);
    const user = userEvent.setup();
    renderFanList();
    await rowOf("Fixture Fan Three");

    await chooseInbox(user, "Split Inbox settings");
    const reassign = await screen.findByRole("region", { name: "Reassign fans to different groups" });
    expect(within(reassign).getAllByRole("combobox").map((s) => s.getAttribute("aria-label")))
      .toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    await user.selectOptions(within(reassign).getByRole("combobox", { name: "Fixture Fan One" }), "Inbox 2");
    await saveSplit(user);
    expect(put).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 2, assignments: { [FANS[0].id]: 2, [FANS[1].id]: 2, [FANS[2].id]: 2 }, chatter_groups: {} },
    });

    await chooseInbox(user, "Inbox 2");
    await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    await chooseInbox(user, "Inbox 1", "Inbox 2");
    expect(await screen.findByText("No conversations found")).toBeInTheDocument();
    expect(shownFans()).toEqual([]);
  });

  it("with \"Inbox 3\" selected, saving a count of 2 returns the selector to \"All inboxes\", and \"Inbox 1\" and \"Inbox 2\" between them show every loaded Fan exactly once", async () => {
    const put = serveSavableSplit(3, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 3 });
    serveChats(CHATS);
    const user = userEvent.setup();
    renderFanList();
    await rowOf("Fixture Fan Three");
    await chooseInbox(user, "Inbox 3");
    await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan Three"]));

    await chooseInbox(user, "Split Inbox settings", "Inbox 3");
    const dialog = await screen.findByRole("dialog", { name: "Split Inbox settings" });
    await user.selectOptions(await within(dialog).findByRole("combobox", { name: "Choose the number of groups" }), "2");
    await saveSplit(user);
    expect(put).toHaveBeenCalledWith("/admin/split-inbox", {
      account_id: ACCOUNT_ID,
      config: { group_count: 2, assignments: { [FANS[0].id]: 1, [FANS[1].id]: 2 }, chatter_groups: {} },
    });

    await vi.waitFor(() => expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument());
    await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));

    await chooseInbox(user, "Inbox 1");
    await vi.waitFor(() => expect(shownFans()).toContain("Fixture Fan One"));
    const inboxOne = shownFans();
    await chooseInbox(user, "Inbox 2", "Inbox 1");
    await vi.waitFor(() => expect(shownFans()).toContain("Fixture Fan Two"));
    const inboxTwo = shownFans();
    expect([...inboxOne, ...inboxTwo].sort()).toEqual(["Fixture Fan One", "Fixture Fan Three", "Fixture Fan Two"]);
  });

  it("with \"Inbox 2\" chosen, the dialog names a Fan in Inbox 1 by its profile, as its row does", async () => {
    routeRelay(`/admin/fans/${ACCOUNT_ID}/by-ids`, () => ({
      fans: { [FANS[0].id]: { id: FANS[0].id, name: FANS[0].name, username: FANS[0].username, avatar: null, customNickname: null } },
    }));
    serveSavableSplit(2, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 2 });
    const unnamed = {
      withUser: { id: FANS[0].id, avatar: null },
      lastMessage: { id: 800000300, text: "Hi there", fromUser: { id: FANS[0].id }, createdAt: ago(59) },
      hasUnread: true,
      unreadMessagesCount: 1,
    } as OFChatItem;
    serveChats([unnamed, CHATS[1], CHATS[2]]);
    const user = userEvent.setup();
    renderFanList();
    await rowOf("Fixture Fan One");

    await chooseInbox(user, "Inbox 2");
    await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]));
    await chooseInbox(user, "Split Inbox settings", "Inbox 2");
    const reassign = await screen.findByRole("region", { name: "Reassign fans to different groups" });
    expect(within(reassign).getAllByRole("combobox").map((s) => s.getAttribute("aria-label")))
      .toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
  });

  it("once a saved count of 2 has reset \"Inbox 3\" to \"All inboxes\", saving 3 again leaves the selector on \"All inboxes\"", async () => {
    const put = serveSavableSplit(3, { [FANS[0].id]: 1, [FANS[1].id]: 2, [FANS[2].id]: 3 });
    serveChats(CHATS);
    const user = userEvent.setup();
    renderFanList();
    await rowOf("Fixture Fan Three");
    await chooseInbox(user, "Inbox 3");
    await vi.waitFor(() => expect(shownFans()).toEqual(["Fixture Fan Three"]));
    const saveCount = async (label: string, count: string) => {
      await chooseInbox(user, "Split Inbox settings", label);
      const dialog = await screen.findByRole("dialog", { name: "Split Inbox settings" });
      await user.selectOptions(await within(dialog).findByRole("combobox", { name: "Choose the number of groups" }), count);
      await saveSplit(user);
    };

    await saveCount("Inbox 3", "2");
    await vi.waitFor(() => expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument());
    await saveCount("All inboxes", "3");
    expect(put).toHaveBeenCalledTimes(2);
    await user.click(within(filterRow()).getByRole("button", { name: "All inboxes" }));
    await within(screen.getByRole("region", { name: "Inboxes" })).findByRole("button", { name: "Inbox 3" });
    await user.keyboard("{Escape}");

    expect(within(filterRow()).getByRole("button", { name: "All inboxes" })).toBeInTheDocument();
    expect(shownFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
  });

  it("select mode counts only the picks on screen: a chip or Creator switch hides the others from the bar, and they return with their rows", async () => {
    ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
    routeRelay("filter=unread", () => ({ list: [CHATS[0], CHATS[1]], hasMore: false }));
    serveChats(() => (scopeCreator === ACCOUNT_ID ? CHATS : [answered(FAN_FIVE, 10), answered(FAN_FOUR, 11)]));
    const user = userEvent.setup();
    const { rerender } = renderFanList();
    await rowOf("Fixture Fan Three");
    const bar = () => within(screen.getByRole("toolbar", { name: "Selected chats" }));

    await openSettings(user);
    await user.click(screen.getByRole("button", { name: /Select chats/ }));
    await user.click(await rowOf("Fixture Fan One"));
    await user.click(await rowOf("Fixture Fan Three"));
    expect(bar().getByText("2 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Unread \d+$/ }));
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two"]));
    expect(bar().getByText("1 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All" }));
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(bar().getByText("2 selected")).toBeInTheDocument();

    scopeCreator = OTHER_ACCOUNT.id;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan Five", "Fixture Fan Four"]));
    expect(bar().getByText("0 selected")).toBeInTheDocument();
    scopeCreator = ACCOUNT_ID;
    rerender(<FanList selected={null} onSelect={vi.fn()} />);
    await vi.waitFor(() => expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(bar().getByText("2 selected")).toBeInTheDocument();
  });

  it("a live message re-renders its own row only, not every row in the list", async () => {
    serveChats(CHATS);
    renderWithProviders(withRealtime(), new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await rowOf("Fixture Fan Three");
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    rowRenders.clear();

    fanWrites(FANS[2], 800000020, "Only my row moves", new Date().toISOString());

    expect(within(await rowOf("Fixture Fan Three")).getByText("Only my row moves")).toBeInTheDocument();
    expect(rowRenders.get(String(FANS[2].id))).toBeGreaterThan(0);
    expect(rowRenders.get(String(FANS[0].id)) ?? 0).toBe(0);
    expect(rowRenders.get(String(FANS[1].id)) ?? 0).toBe(0);
  });

  describe("live messages while OF's chat list is still loading (the local seed on screen)", () => {
    const seedRow = (c: OFChatItem, accountId = ACCOUNT_ID) => ({ ...c, __accountId: accountId });
    function serveSeedOnly(list: OFChatItem[]) {
      routeRelay("/api/of/v2/chats?", () => new Promise(() => {}));
      routeRelay("/admin/chats/recent", () => ({ list, source: "local-db" }));
    }
    const expectRow = (name: string, preview: string, unread: number) => vi.waitFor(() => {
      const row = screen.getByRole("button", { name: new RegExp(name) });
      expect(within(row).getByText(preview)).toBeInTheDocument();
      expect(within(row).getByRole("img", { name: `Unread (${unread})` })).toBeInTheDocument();
      expect(rowOrder()[0]).toBe(name);
    });

    it("All Models: a burst from one Fan and from several Fans moves each row to the top, with its text and unread", async () => {
      scopeKind = "all";
      ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
      serveSeedOnly(CHATS.map((c) => seedRow(c)));
      renderWithProviders(withRealtime(), new QueryClient({ defaultOptions: { queries: { retry: false } } }));
      await rowOf("Fixture Fan Three");
      expect(rowOrder()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);

      const unread = new Map(CHATS.map((c) => [c.withUser.id, c.unreadMessagesCount ?? 0]));
      const t0 = Date.now();
      for (let i = 0; i < 30; i++) {
        const fan = FANS[[2, 2, 2, 1, 0][i % 5]];
        fanWrites(fan, 800000500 + i, `burst ${i}`, new Date(t0 + i).toISOString());
        unread.set(fan.id, (unread.get(fan.id) ?? 0) + 1);
        await expectRow(fan.name, `burst ${i}`, unread.get(fan.id)!);
      }
      fanWrites(FANS[0], 800000529, "burst 29", new Date(t0 + 29).toISOString());
      await expectRow(FANS[0].name, "burst 29", unread.get(FANS[0].id)!);

      act(() => emitEvent("api2_chat_message", {
        __account_id: OTHER_ACCOUNT.id,
        api2_chat_message: { id: 800000600, text: "first hello", fromUser: { id: FAN_FIVE.id, name: FAN_FIVE.name }, createdAt: new Date(t0 + 40).toISOString() },
      }));
      await expectRow(FAN_FIVE.name, "first hello", 1);
      expect(rowOrder()).toEqual(["Fixture Fan Five", "Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    });

    it("one Creator: its Fans' messages move its rows; another Creator's Fan stays out", async () => {
      ACCOUNTS = [CREATOR_ACCOUNT, OTHER_ACCOUNT];
      serveSeedOnly(CHATS.map((c) => seedRow(c)));
      renderWithProviders(withRealtime(), new QueryClient({ defaultOptions: { queries: { retry: false } } }));
      await rowOf("Fixture Fan Three");

      fanWrites(FANS[2], 800000700, "still here", new Date().toISOString());
      await expectRow(FANS[2].name, "still here", 1);
      act(() => emitEvent("api2_chat_message", {
        __account_id: OTHER_ACCOUNT.id,
        api2_chat_message: { id: 800000701, text: "wrong inbox", fromUser: { id: FAN_FIVE.id, name: FAN_FIVE.name }, createdAt: new Date().toISOString() },
      }));
      fanWrites(FANS[1], 800000702, "and me", new Date(Date.now() + 1).toISOString());
      await expectRow(FANS[1].name, "and me", 2);
      expect(screen.queryByText("wrong inbox")).not.toBeInTheDocument();
      expect(rowOrder()).toEqual(["Fixture Fan Two", "Fixture Fan Three", "Fixture Fan One"]);
    });
  });
});
