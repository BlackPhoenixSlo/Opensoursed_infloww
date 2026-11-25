import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, nav } = vi.hoisted(() => {
  const nav = { pathname: "/", search: "" };
  return { relayGet: vi.fn(), nav };
});

let cachedSearch = { key: "\u0000", value: new URLSearchParams() };
function searchParams() {
  if (cachedSearch.key !== nav.search) {
    cachedSearch = { key: nav.search, value: new URLSearchParams(nav.search) };
  }
  return cachedSearch.value;
}
const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => nav.pathname,
  useSearchParams: () => searchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

vi.mock("@/lib/relay", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/relay")>();
  const ok = vi.fn(async () => ({}));
  return {
    ...actual,
    relay: {
      get: (...args: unknown[]) => relayGet(...args),
      post: ok,
      patch: ok,
      put: ok,
      delete: ok,
      uploadFile: ok,
      uploadForm: ok,
    },
  };
});

vi.mock("@/contexts/UserContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/UserContext")>();
  const value = { user: { username: "owner" }, logout: vi.fn() };
  return { ...actual, useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/ChatterContext")>();
  const value = { chatter: null, logout: vi.fn() };
  return { ...actual, useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/EmployeeContext")>();
  const value = { current: null, hydrated: true, pickedId: null, clear: vi.fn() };
  return { ...actual, useEmployee: () => value };
});

import type { QueryClient } from "@tanstack/react-query";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { streamUp } from "@/components/chat/composerTestHarness";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { eventBus } from "@/lib/events";
import AppShell from "@/components/shell/AppShell";
import MessagesProLayout from "./layout";
import MessagesProPage from "./page";
import DeepLinkPage from "./[accountId]/[fanId]/page";


const ACCOUNT_ID = "100000001";
const CREATOR = { id: 100000001, name: "Test Creator", username: "testcreator", avatar: null };
const FANS = [
  { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" },
  { id: 200000002, name: "Fixture Fan Two", username: "fixturefantwo" },
  { id: 200000003, name: "Fixture Fan Three", username: "fixturefanthree" },
];
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const fanUser = (f: (typeof FANS)[number]) => ({ ...f, avatar: null, customNickname: null, displayName: null });

const THREAD_TEXT = "Fixture thread opener";
const THREAD = [
  {
    id: 900000001, text: THREAD_TEXT, fromUser: fanUser(FANS[0]), toUser: CREATOR,
    createdAt: ago(30), isFree: true, isOpened: true, isTip: false, price: 0,
    media: [], mediaCount: 0, isLiked: false, isPinned: false,
  },
];
const PINNED_TEXT = "Fixture pinned message";
const PINNED_THREAD = [
  {
    id: 900000002, text: PINNED_TEXT, fromUser: fanUser(FANS[1]), toUser: CREATOR,
    createdAt: ago(20), isFree: true, isOpened: true, isTip: false, price: 0,
    media: [], mediaCount: 0, isLiked: false, isPinned: true,
  },
];
const CHATS = FANS.map((f, i) => ({
  withUser: fanUser(f),
  lastMessage: {
    id: 800000000 + i, text: `Hello from ${f.name}`, fromUser: fanUser(f), createdAt: ago(60 + i),
    mediaCount: 0, isFree: true, isTip: false, isOpened: true,
  },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
}));
const ACCOUNT = {
  id: ACCOUNT_ID, nickname: "Test Creator", name: "Test Creator", platform: "onlyfans",
  color: "#e8618c", has_session: true, session_dead_at: null, created_at: ago(43_200), last_used_at: ago(5),
};

function fanRecord(f: (typeof FANS)[number]) {
  return {
    account_id: ACCOUNT_ID, fan_id: f.id, of_username: f.username, of_display_name: f.name,
    custom_nickname: null, generated_nickname: null, real_name: null, his_age: null, home_country: null,
    home_city: null, hobbies: null, fetishes: null, self_description: null, description: null, notes: null,
    subscription_status: null, subscribed_at: null, language: null, language_source: null,
    avatar_url: null, tags: [], lifetime_spend_cents: 0, bought_amount: 0,
    last_message_received_at: ago(30), source: "test", is_followed: false, created_at: ago(43_200), updated_at: ago(30),
  };
}

async function fixture(path: string): Promise<unknown> {
  const [p] = String(path).split("?");
  if (p === "/admin/accounts") return { accounts: [ACCOUNT], active_account_id: ACCOUNT_ID };
  if (p === "/api/of/v2/chats") {
    const q = new URLSearchParams(String(path).split("?")[1] ?? "");
    const first = (q.get("offset") ?? "0") === "0" && !q.get("filter") && !q.get("query") && !q.get("list_id");
    return { list: first ? CHATS : [], hasMore: false };
  }
  const messages = /^\/api\/of\/v2\/chats\/(\d+)\/messages$/.exec(p);
  if (messages) {
    const list = messages[1] === String(FANS[0].id) ? THREAD : messages[1] === String(FANS[1].id) ? PINNED_THREAD : [];
    return { list, hasMore: false };
  }
  if (p === "/api/of/v2/users/list") {
    const q = new URLSearchParams(String(path).split("?")[1] ?? "");
    const ids = q.getAll("ids").flatMap((v) => v.split(","));
    return Object.fromEntries(FANS.filter((f) => ids.includes(String(f.id))).map((f) => [String(f.id), fanUser(f)]));
  }
  const ofUser = /^\/api\/of\/v2\/users\/(\d+)$/.exec(p);
  const ofUserFan = ofUser && FANS.find((f) => String(f.id) === ofUser[1]);
  if (ofUserFan) return fanUser(ofUserFan);
  const fanPath = new RegExp(`^/admin/fans/${ACCOUNT_ID}/(\\d+)(/ppv-history)?$`).exec(p);
  if (fanPath?.[2]) {
    return { items: [], summary: { count: 0, max_cents: 0, avg_cents: 0, tips_cents: 0, messages_cents: 0, posts_cents: 0 } };
  }
  const fan = fanPath && FANS.find((f) => String(f.id) === fanPath[1]);
  if (fan) return fanRecord(fan);
  return { list: [], items: [], rows: [], hasMore: false, next_cursor: null };
}


const SCOPE_KEY = "chatterly:scope";
const OTHER_ACCOUNT_ID = "100000002";
const OTHER_ACCOUNT = { ...ACCOUNT, id: OTHER_ACCOUNT_ID, nickname: "Other Creator", name: "Other Creator", color: "#4a90d9" };
const OTHER_FAN = { id: 200000009, name: "Other Creator Fan", username: "othercreatorfan" };
const OTHER_CHATS = [{
  ...CHATS[0],
  withUser: fanUser(OTHER_FAN),
  lastMessage: { ...CHATS[0].lastMessage, id: 800000009, text: `Hello from ${OTHER_FAN.name}`, fromUser: fanUser(OTHER_FAN) },
}];

async function twoCreatorFixture(path: string, opts?: { accountId?: string }): Promise<unknown> {
  const [p, qs = ""] = String(path).split("?");
  if (p === "/admin/accounts") return { accounts: [ACCOUNT, OTHER_ACCOUNT], active_account_id: ACCOUNT_ID };
  if (p === "/api/of/v2/chats" && opts?.accountId === OTHER_ACCOUNT_ID) {
    const q = new URLSearchParams(qs);
    const first = (q.get("offset") ?? "0") === "0" && !q.get("filter") && !q.get("query") && !q.get("list_id");
    return { list: first ? OTHER_CHATS : [], hasMore: false };
  }
  return fixture(path);
}


function stubViewport(width: number) {
  window.matchMedia = ((query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    const matches = (!min || width >= Number(min[1])) && (!max || width <= Number(max[1])) && !!(min || max);
    return {
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    };
  }) as unknown as typeof window.matchMedia;
}
const DESKTOP = 1440;

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}
class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = 0;
  onopen: unknown = null;
  onmessage: unknown = null;
  onerror: unknown = null;
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
Object.defineProperty(globalThis, "EventSource", { value: FakeEventSource, configurable: true, writable: true });

beforeEach(() => {
  nav.pathname = "/";
  nav.search = "";
  window.history.replaceState(null, "", "/");
  relayGet.mockReset();
  relayGet.mockImplementation(fixture);
  window.localStorage.clear();
  stubViewport(DESKTOP);
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("IntersectionObserver", NoopObserver);
  vi.stubGlobal("ResizeObserver", NoopObserver);
  streamUp(eventBus);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function routePage(pathname: string) {
  const deepLink = /^\/messages-pro\/([^/]+)\/([^/]+)$/.exec(pathname);
  if (!deepLink) return <MessagesProPage />;
  const value = { accountId: deepLink[1], fanId: deepLink[2] };
  const params = Object.assign(Promise.resolve(value), { status: "fulfilled", value });
  return <DeepLinkPage params={params} />;
}

function routeTree(url: string) {
  const [pathname, search = ""] = url.split("?");
  nav.pathname = pathname;
  nav.search = search;
  window.history.replaceState(null, "", url);
  return (
    <ScopeProvider>
      <AppShell>
        <MessagesProLayout>{routePage(pathname)}</MessagesProLayout>
      </AppShell>
    </ScopeProvider>
  );
}

function renderRoute(url: string, client?: QueryClient) {
  return renderWithProviders(routeTree(url), client);
}

function navigateTo(rendered: ReturnType<typeof renderRoute>, url: string) {
  rendered.rerender(routeTree(url));
}

function expectNoAppChrome(container: HTMLElement) {
  expect(container.querySelector("#app-sidebar")).toBeNull();
  expect(screen.queryByRole("button", { name: "Toggle sidebar" })).toBeNull();
}

function expectNoPinnedColumn() {
  expect(screen.queryByRole("complementary", { name: "Pinned messages" })).toBeNull();
}

function threadHeader() {
  return screen.getByRole("button", { name: "Fan insights" }).closest("header")!;
}

function rowOf(f: (typeof FANS)[number]) {
  return screen.getAllByText(f.name).map((el) => el.closest("[data-chat-row]")).find(Boolean)!;
}

function messageCalls(f: (typeof FANS)[number]) {
  return relayGet.mock.calls.map(([path]) => String(path)).filter((p) => p.startsWith(`/api/of/v2/chats/${f.id}/messages`));
}

describe("the Messages Pro route", () => {
  it("without window=1: still its own window, no app sidebar or top bar; lists the Fans, and opens a Fan's Thread", async () => {
    const { container } = renderRoute("/messages-pro");

    expectNoAppChrome(container);

    for (const f of FANS) expect(await screen.findByText(f.name)).toBeInTheDocument();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();

    const row = screen.getByText(FANS[0].name).closest("button");
    expect(row).not.toBeNull();
    await userEvent.click(row!);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expect(relayGet.mock.calls.map(([path]) => String(path))).toContainEqual(
      expect.stringContaining(`/api/of/v2/chats/${FANS[0].id}/messages`),
    );
    expect(screen.queryByText("Select any conversation to start")).toBeNull();

    expect((await screen.findAllByRole("textbox", { name: "Nickname" })).length).toBeGreaterThan(0);
    expect(relayGet.mock.calls.map(([path]) => String(path))).toContain(`/admin/fans/${ACCOUNT_ID}/${FANS[0].id}`);
    expectNoPinnedColumn();
  });

  it("the selected Fan's row is marked aria-current and scrolled into view once per selection", async () => {
    renderRoute("/messages-pro");
    const scroll = vi.mocked(Element.prototype.scrollIntoView);
    const scrollsOf = (row: Element) => scroll.mock.calls.filter((_, i) => scroll.mock.contexts[i] === row);

    for (const f of FANS) expect(await screen.findByText(f.name)).toBeInTheDocument();
    for (const f of FANS) expect(rowOf(f)).not.toHaveAttribute("aria-current");

    await userEvent.click(rowOf(FANS[0]));
    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expect(rowOf(FANS[0])).toHaveAttribute("aria-current", "true");
    for (const f of FANS.slice(1)) expect(rowOf(f)).not.toHaveAttribute("aria-current");
    expect(scrollsOf(rowOf(FANS[0]))).toEqual([[{ block: "nearest" }]]);

    await userEvent.click(screen.getByRole("button", { name: "Fan insights" }));
    await userEvent.click(rowOf(FANS[0]));
    expect(rowOf(FANS[0])).toHaveAttribute("aria-current", "true");
    expect(scrollsOf(rowOf(FANS[0]))).toHaveLength(1);

    await userEvent.click(rowOf(FANS[1]));
    expect(await screen.findByText(PINNED_TEXT)).toBeInTheDocument();
    expect(rowOf(FANS[1])).toHaveAttribute("aria-current", "true");
    for (const f of [FANS[0], FANS[2]]) expect(rowOf(f)).not.toHaveAttribute("aria-current");
    expect(scrollsOf(rowOf(FANS[1]))).toEqual([[{ block: "nearest" }]]);
    expect(scrollsOf(rowOf(FANS[0]))).toHaveLength(1);
  });

  it("windowed: no app sidebar or top bar, lists the Fans, and opens a Fan's Thread", async () => {
    const { container } = renderRoute("/messages-pro?window=1");

    expectNoAppChrome(container);
    for (const f of FANS) expect(await screen.findByText(f.name)).toBeInTheDocument();

    const row = screen.getByText(FANS[0].name).closest("button");
    expect(row).not.toBeNull();
    await userEvent.click(row!);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expectNoAppChrome(container);

    const toggle = screen.getByRole("button", { name: "Fan insights" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();
    expectNoPinnedColumn();

    const home = within(screen.getByRole("region", { name: "Fan tabs" })).getByRole("link", { name: "Home" });
    expect(home).toHaveAttribute("href", "/messages-pro");
    await userEvent.click(home);
    expect(screen.queryByText(THREAD_TEXT)).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    expectNoAppChrome(container);
  });

  it("windowed Deep link: a Deep link URL with window=1 renders without the app sidebar", async () => {
    const { container } = renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}?window=1`);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expectNoAppChrome(container);
    expectNoPinnedColumn();
  });

  it("Deep link without window=1 (a notification, an old bookmark): the same window layout, no app sidebar", async () => {
    const { container } = renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expectNoAppChrome(container);
    expectNoPinnedColumn();
    expect(within(screen.getByRole("region", { name: "Fan tabs" })).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/messages-pro");
  });

  it("Deep link: a Pinned message shows in the Thread's pinned bar, and the bar opens the popover", async () => {
    renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[1].id}`);

    expect(await screen.findByText(PINNED_TEXT)).toBeInTheDocument();
    expectNoPinnedColumn();

    const bar = screen.getByText("1 pinned message").closest("button");
    expect(bar).not.toBeNull();
    expect(screen.queryByRole("dialog", { name: "Pinned messages" })).toBeNull();

    await userEvent.click(bar!);
    const popover = await screen.findByRole("dialog", { name: "Pinned messages" });
    expect(popover).toHaveTextContent(PINNED_TEXT);
  });

  it("Deep link: the Fan is selected, its row marked and scrolled, its Thread open with Fan insights closed", async () => {
    renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);
    const scroll = vi.mocked(Element.prototype.scrollIntoView);

    for (const f of FANS) expect(await screen.findByText(`Hello from ${f.name}`)).toBeInTheDocument();
    expect(rowOf(FANS[0])).toHaveAttribute("aria-current", "true");
    for (const f of FANS.slice(1)) expect(rowOf(f)).not.toHaveAttribute("aria-current");
    expect(scroll.mock.contexts.filter((el) => el === rowOf(FANS[0]))).toHaveLength(1);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    expect(threadHeader()).toHaveTextContent(FANS[0].name);
    const toggle = screen.getByRole("button", { name: "Fan insights" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();

    await userEvent.click(rowOf(FANS[1]));
    expect(await screen.findByText(PINNED_TEXT)).toBeInTheDocument();
    expect(threadHeader()).toHaveTextContent(FANS[1].name);
    expect(screen.getByRole("button", { name: "Fan insights" })).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();
    expect(rowOf(FANS[1])).toHaveAttribute("aria-current", "true");
    expect(rowOf(FANS[0])).not.toHaveAttribute("aria-current");
  });

  it("Deep link, invalid: a malformed fan id shows \"Invalid fan id\" and no Thread", async () => {
    renderRoute(`/messages-pro/${ACCOUNT_ID}/not-a-fan`);

    expect(await screen.findByText("Invalid fan id: not-a-fan")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fan insights" })).toBeNull();
    expect(screen.queryByText("Select any conversation to start")).toBeNull();
    expect(relayGet.mock.calls.map(([path]) => String(path))).not.toContainEqual(
      expect.stringMatching(/^\/api\/of\/v2\/chats\/[^/?]+\/messages/),
    );
  });

  it("Deep link before the list: with the Fan List pending, the Thread shows the Fan from the profile lookup", async () => {
    relayGet.mockImplementation((path: string) =>
      String(path).split("?")[0] === "/api/of/v2/chats" ? new Promise(() => {}) : fixture(path),
    );
    const { container } = renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    await vi.waitFor(() => expect(threadHeader()).toHaveTextContent(FANS[0].name));
    expect(container.querySelectorAll("[data-chat-row]")).toHaveLength(0);
    expect(screen.queryByText(`Hello from ${FANS[0].name}`)).toBeNull();
  });

  it("Deep link scope: the Fan List is the link's Creator's and the Fan selected, while the saved scope stays the other Creator", async () => {
    relayGet.mockImplementation(twoCreatorFixture);
    window.localStorage.setItem(SCOPE_KEY, `model:${OTHER_ACCOUNT_ID}`);
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    onTestFinished(() => setItem.mockRestore());
    const busScope = vi.spyOn(eventBus, "setScope");
    onTestFinished(() => busScope.mockRestore());
    const scopeWrites = () => setItem.mock.calls.filter(([key]) => key === SCOPE_KEY);
    const link = `/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`;

    async function expectArrived() {
      for (const f of FANS) expect(await screen.findByText(`Hello from ${f.name}`)).toBeInTheDocument();
      expect(screen.queryByText(`Hello from ${OTHER_FAN.name}`)).toBeNull();
      expect(rowOf(FANS[0])).toHaveAttribute("aria-current", "true");
      expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
      expect(threadHeader()).toHaveTextContent(FANS[0].name);
      await vi.waitFor(() => expect(busScope).toHaveBeenLastCalledWith(`model:${ACCOUNT_ID}`));
      expect(window.localStorage.getItem(SCOPE_KEY)).toBe(`model:${OTHER_ACCOUNT_ID}`);
      expect(scopeWrites()).toEqual([]);
    }

    const first = renderRoute(link);
    await expectArrived();
    first.unmount();

    busScope.mockClear();
    const rendered = renderRoute("/messages-pro");
    expect(await screen.findByText(`Hello from ${OTHER_FAN.name}`)).toBeInTheDocument();
    navigateTo(rendered, link);
    await expectArrived();

    await userEvent.click(screen.getByRole("tab", { name: "Other Creator" }));
    expect(await screen.findByText(`Hello from ${OTHER_FAN.name}`)).toBeInTheDocument();
    expect(scopeWrites()).toEqual([[SCOPE_KEY, `model:${OTHER_ACCOUNT_ID}`]]);
  });

  it("Deep link, Fan not in the list: the Thread still shows the Fan, no row is marked, and no further pages are fetched", async () => {
    relayGet.mockImplementation(async (path: string) => {
      const answer = await fixture(path);
      if (String(path).split("?")[0] !== "/api/of/v2/chats") return answer;
      const { list } = answer as { list: typeof CHATS };
      return { list: list.filter((c) => c.withUser.id !== FANS[0].id), hasMore: true };
    });
    const { container } = renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);

    for (const f of FANS.slice(1)) expect(await screen.findByText(`Hello from ${f.name}`)).toBeInTheDocument();
    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    await vi.waitFor(() => expect(threadHeader()).toHaveTextContent(FANS[0].name));
    expect(container.querySelectorAll("[data-chat-row]")).toHaveLength(2);
    expect(container.querySelectorAll("[data-chat-row][aria-current]")).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "All Models" })).toBeNull();
    expect(window.localStorage.getItem(SCOPE_KEY)).toBeNull();

    await new Promise((r) => setTimeout(r, 50));
    const pages = relayGet.mock.calls
      .map(([path]) => String(path))
      .filter((p) => p.startsWith("/api/of/v2/chats?"))
      .map((p) => new URLSearchParams(p.split("?")[1]).get("offset"));
    expect(pages.length).toBeGreaterThan(0);
    expect(pages.filter((o) => o !== "0")).toEqual([]);
  });

  it("Deep link with msg: selecting another Fan removes msg before that Fan's Thread asks for messages, and it asks once", async () => {
    const searchAtFirstAsk: string[] = [];
    relayGet.mockImplementation((path: string) => {
      const p = String(path);
      if (p.startsWith(`/api/of/v2/chats/${FANS[1].id}/messages`)) {
        searchAtFirstAsk.push(window.location.search);
        return Promise.resolve(p.includes("before_id=") ? { list: [], hasMore: false } : { list: PINNED_THREAD, hasMore: true });
      }
      return fixture(path);
    });
    renderRoute(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}?foo=1&msg=900000099#h`);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    fireEvent.click(await screen.findByText(`Hello from ${FANS[1].name}`));

    expect(await screen.findByText(PINNED_TEXT)).toBeInTheDocument();
    expect(searchAtFirstAsk[0]).toBe("?foo=1");
    expect(window.location.pathname).toBe(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);
    expect(window.location.search).toBe("?foo=1");
    expect(window.location.hash).toBe("#h");
    await new Promise((r) => setTimeout(r, 50));
    expect(messageCalls(FANS[1])).toHaveLength(1);
  });

  it("Deep link refresh (spec case 5): refresh=media refetches the Thread and the Fan's money data once, then leaves the URL", async () => {
    const fan = FANS[0];
    const client = makeTestQueryClient();
    client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, gcTime: Infinity } });
    const emptyMedia = { pages: [{ list: [], hasMore: false }], pageParams: [null] };
    client.setQueryData(["messages", ACCOUNT_ID, fan.id], THREAD);
    client.setQueryData(["of-user", ACCOUNT_ID, fan.id], fanUser(fan));
    client.setQueryData(["of-user", ACCOUNT_ID, fan.id, "full"], fanUser(fan));
    client.setQueryData(["fan", ACCOUNT_ID, fan.id], fanRecord(fan));
    client.setQueryData(["fan-chat-media", ACCOUNT_ID, fan.id, true, 20, true], emptyMedia);
    client.setQueryData(["fan-chat-media", ACCOUNT_ID, fan.id, false, 20, true], emptyMedia);
    client.setQueryData(["fan-ppv-history", ACCOUNT_ID, fan.id, 12], {
      items: [], summary: { count: 0, max_cents: 0, avg_cents: 0, tips_cents: 0, messages_cents: 0, posts_cents: 0 },
    });
    client.setQueryData(["last-purchases", ACCOUNT_ID], []);

    const paths = () => relayGet.mock.calls.map(([path]) => String(path));
    const fetches = () => ({
      thread: messageCalls(fan).length,
      profile: paths().filter((p) => p === `/api/of/v2/users/list?ids=${fan.id}&view=m`).length,
      fullProfile: paths().filter((p) => p === `/api/of/v2/users/${fan.id}`).length,
      fan: paths().filter((p) => p === `/admin/fans/${ACCOUNT_ID}/${fan.id}`).length,
      media: paths().filter((p) => p.startsWith(`/api/of/v2/chats/${fan.id}/media`)).length,
      ppvHistory: paths().filter((p) => p.startsWith(`/admin/fans/${ACCOUNT_ID}/${fan.id}/ppv-history`)).length,
      purchases: paths().filter((p) => p.startsWith("/api/of/v2/payouts/transactions")).length,
    });
    const link = `/messages-pro/${ACCOUNT_ID}/${fan.id}`;

    const first = renderRoute(`${link}?window=1&foo=1&refresh=media#h`, client);

    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    await vi.waitFor(() => expect(fetches()).toMatchObject({ thread: 1, profile: 0, fullProfile: 1, fan: 1 }));
    expect(fetches()).toMatchObject({ media: 0, ppvHistory: 0, purchases: 0 });
    expect(window.location.pathname).toBe(link);
    expect(window.location.search).toBe("?window=1&foo=1");
    expect(window.location.hash).toBe("#h");

    const toggle = screen.getByRole("button", { name: "Fan insights" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(await screen.findByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();
    await vi.waitFor(() => expect(fetches()).toMatchObject({ media: 1, ppvHistory: 1, purchases: 1 }));

    await new Promise((r) => setTimeout(r, 50));
    const once = { thread: 1, profile: 0, fullProfile: 1, fan: 1, media: 1, ppvHistory: 1, purchases: 1 };
    expect(fetches()).toEqual(once);

    first.unmount();
    renderRoute(`${link}${window.location.search}${window.location.hash}`, client);
    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(fetches()).toEqual(once);
    expect(window.location.search).toBe("?window=1&foo=1");
  });

  it("Fan pop-out: the Chat header has no \"↗ pop out\" but \"Open in new tab\", and the selected Fan's row opens its Deep link from \"Open in a new window\" (ADR-0002, amended)", async () => {
    const windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);
    onTestFinished(() => windowOpen.mockRestore());
    renderRoute("/messages-pro");

    await userEvent.click((await screen.findByText(FANS[0].name)).closest("button")!);
    expect(await screen.findByText(THREAD_TEXT)).toBeInTheDocument();

    const header = within(threadHeader());
    expect(header.queryByText(/pop out/)).toBeNull();
    expect(header.getByRole("button", { name: "Open in new tab" })).toBeInTheDocument();

    fireEvent.contextMenu(rowOf(FANS[0]));
    await userEvent.click(screen.getByRole("button", { name: "Open in a new window" }));
    expect(windowOpen).toHaveBeenCalledTimes(1);
    expect(windowOpen.mock.calls[0][0]).toBe(`/messages-pro/${ACCOUNT_ID}/${FANS[0].id}`);
    expectNoPinnedColumn();
  });

  it("the Window header has no Scope switcher, Errors or \"+\" Extras overflow, as Infloww's (TODO.md B2)", async () => {
    relayGet.mockImplementation((path: string) => String(path).startsWith("/admin/errors")
      ? Promise.resolve({ count: 1, since_hours: 24, list: [] })
      : fixture(path));
    renderWithProviders(routeTree("/messages-pro"));
    for (const f of FANS) expect(await screen.findByText(f.name)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 1200));
    const header = within(screen.getByRole("region", { name: "Window header" }));
    expect(header.queryAllByTitle(/Scope switcher|Error badge/)).toHaveLength(0);
    expect(header.queryByRole("button", { name: EXTRAS_OVERFLOW_LABEL })).toBeNull();
    expect(screen.queryByRole("button", { name: "Recent errors" })).toBeNull();
  });

  it("an old window=1 on a route that is not Messages Pro keeps the app chrome", () => {
    nav.pathname = "/analytics/fan-reports";
    nav.search = "window=1";
    const { container } = renderWithProviders(
      <ScopeProvider>
        <AppShell>page</AppShell>
      </ScopeProvider>,
    );

    expect(container.querySelector("#app-sidebar")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Toggle sidebar" })).toBeInTheDocument();
  });
});
