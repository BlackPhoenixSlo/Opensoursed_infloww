import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, nav, who } = vi.hoisted(() => ({
  relayGet: vi.fn(),
  nav: { pathname: "/", search: "" },
  who: { chatter: false },
}));

let cachedSearch = { key: "\u0000", value: new URLSearchParams() };
function searchParams() {
  if (cachedSearch.key !== nav.search) cachedSearch = { key: nav.search, value: new URLSearchParams(nav.search) };
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
      post: ok, patch: ok, put: ok, delete: ok, uploadFile: ok, uploadForm: ok,
    },
  };
});

vi.mock("@/contexts/UserContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/UserContext")>();
  const owner = { user: { username: "owner" }, logout: vi.fn() };
  const none = { user: null, logout: vi.fn() };
  const value = () => (who.chatter ? none : owner);
  return { ...actual, useUser: value, useOptionalUser: value };
});
vi.mock("@/contexts/ChatterContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/ChatterContext")>();
  const none = { chatter: null, logout: vi.fn() };
  const chatter = { chatter: { chatter_id: "ch-1", username: "chatter", display_name: "Chatter" }, logout: vi.fn() };
  const value = () => (who.chatter ? chatter : none);
  return { ...actual, useChatter: value, useOptionalChatter: value };
});
vi.mock("@/contexts/EmployeeContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/EmployeeContext")>();
  const value = { current: null, hydrated: true, pickedId: null, clear: vi.fn() };
  return { ...actual, useEmployee: () => value };
});

import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { streamUp } from "@/components/chat/composerTestHarness";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { eventBus } from "@/lib/events";
import { resetPlatformForTests, setPlatform } from "@/lib/platform";
import AppShell from "@/components/shell/AppShell";
import MessagesProLayout from "./layout";
import MessagesProPage from "./page";
import DeepLinkPage from "./[accountId]/[fanId]/page";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

const OF_ID = "100000001";
const OF_FAN = { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" };
const OF_TEXT = "OnlyFans fixture opener";
const FY_ID = "900000000000000010";
const FY_FAN = { id: "900000000000000011", name: "Fansly Fixture Fan", username: "fanslyfixturefan" };
const FY_TEXT = "Fansly fixture opener";

const OF_ACCOUNT = {
  id: OF_ID, nickname: "Olive Fixture", name: "Olive Fixture", platform: "onlyfans", color: "#e8618c",
  has_session: true, session_dead_at: null, created_at: ago(43_200), last_used_at: ago(5),
};
const FY_ACCOUNT = { ...OF_ACCOUNT, id: FY_ID, nickname: "Nova Fixture", name: "Nova Fixture", platform: "fansly" };

const fanUser = (f: { id: number | string; name: string; username: string }) =>
  ({ ...f, avatar: null, customNickname: null, displayName: null });
const chatOf = (f: typeof OF_FAN | typeof FY_FAN, messageId: number | string, text: string) => ({
  withUser: fanUser(f),
  lastMessage: { id: messageId, text, fromUser: fanUser(f), createdAt: ago(60), mediaCount: 0, isFree: true, isTip: false, isOpened: true },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
});
const messageOf = (id: number | string, text: string, f: typeof OF_FAN | typeof FY_FAN, creator: { id: number | string }) => ({
  id, text, fromUser: fanUser(f), toUser: creator, createdAt: ago(30), isFree: true, isOpened: true, isTip: false,
  price: 0, media: [], mediaCount: 0, isLiked: false, isPinned: false,
});

const CHATTER_ROWS = [
  { account_id: FY_ID, nickname: "Nova Fixture", color: "#0ea5e9", owner_id: "o", owner_username: "owner", is_active: true, platform: "fansly" },
  { account_id: OF_ID, nickname: "Olive Fixture", color: "#e8618c", owner_id: "o", owner_username: "owner", is_active: true },
  { account_id: "100000009", nickname: "Watcher Fixture", color: null, owner_id: "o", owner_username: "owner", is_active: true, role: "watcher" },
];

async function fixture(path: string, opts?: { accountId?: string }): Promise<unknown> {
  const [p, qs = ""] = String(path).split("?");
  if (p === "/admin/accounts") return { accounts: [OF_ACCOUNT, FY_ACCOUNT], active_account_id: OF_ID };
  if (p === "/admin/settings/applied") {
    return {
      preferences: { tz: null, report_tz: null, week_start: "monday" }, messaging: { ai_translation: true },
      permissions: { enforced: false, pages: null, scope: "all" }, flags: {},
    };
  }
  if (p === "/api/of/v2/chats") {
    const q = new URLSearchParams(qs);
    const first = (q.get("offset") ?? "0") === "0" && !q.get("filter") && !q.get("query") && !q.get("list_id");
    if (!first) return { list: [], hasMore: false };
    return { list: [opts?.accountId === FY_ID ? chatOf(FY_FAN, "900000000000000101", FY_TEXT) : chatOf(OF_FAN, 800000001, OF_TEXT)], hasMore: false };
  }
  if (p === `/api/of/v2/chats/${OF_FAN.id}/messages`) {
    return { list: [messageOf(900000001, OF_TEXT, OF_FAN, { id: Number(OF_ID) })], hasMore: false };
  }
  if (p === `/api/of/v2/chats/${FY_FAN.id}/messages`) {
    return { list: [messageOf("900000000000000101", FY_TEXT, FY_FAN, { id: FY_ID })], hasMore: false };
  }
  if (p === `/api/of/v2/users/${OF_FAN.id}`) return fanUser(OF_FAN);
  if (p === `/api/of/v2/users/${FY_FAN.id}`) return fanUser(FY_FAN);
  return { list: [], items: [], rows: [], hasMore: false, next_cursor: null };
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
  who.chatter = false;
  nav.pathname = "/";
  nav.search = "";
  window.history.replaceState(null, "", "/");
  relayGet.mockReset();
  relayGet.mockImplementation(fixture);
  window.localStorage.clear();
  resetPlatformForTests();
  setPlatform("onlyfans");
  stubViewport(1440);
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("IntersectionObserver", NoopObserver);
  vi.stubGlobal("ResizeObserver", NoopObserver);
  streamUp(eventBus);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetPlatformForTests();
});

function signInChatter() {
  who.chatter = true;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).startsWith("/chatter/me/accounts")
    ? { ok: true, status: 200, json: async () => CHATTER_ROWS }
    : { ok: false, status: 404, json: async () => ({}) })));
}

function routePage(pathname: string) {
  const deepLink = /^\/messages-pro\/([^/]+)\/([^/]+)$/.exec(pathname);
  if (!deepLink) return <MessagesProPage />;
  const value = { accountId: deepLink[1], fanId: deepLink[2] };
  const params = Object.assign(Promise.resolve(value), { status: "fulfilled", value });
  return <DeepLinkPage params={params} />;
}

function routeTree(url: string, page = routePage(url.split("?")[0])) {
  const [pathname, search = ""] = url.split("?");
  nav.pathname = pathname;
  nav.search = search;
  window.history.replaceState(null, "", url);
  return (
    <ScopeProvider>
      <AppShell>
        <MessagesProLayout>{page}</MessagesProLayout>
      </AppShell>
    </ScopeProvider>
  );
}

const renderRoute = (url: string, page?: React.ReactNode) => renderWithProviders(routeTree(url, page as never), makeTestQueryClient());

const tabs = () => within(screen.getByRole("tablist", { name: "Creator tabs" }));
const tabOf = (name: string) => tabs().getByRole("tab", { name: new RegExp(name) });

function ShellProbe() {
  return <ul aria-label="Shell creators">{usePlatformAccounts().map((a) => <li key={a.id}>{a.nickname}</li>)}</ul>;
}

describe("Combined Messages Pro", () => {
  it("owner, switch on OnlyFans: both Creators' tabs, the badge on the Fansly one only, and each Thread its own Platform's rich text", async () => {
    renderRoute("/messages-pro");
    await vi.waitFor(() => expect(tabs().getAllByRole("tab")).toHaveLength(2));
    expect(within(tabOf("Nova Fixture")).getByTestId("platform-logo-fansly")).toBeInTheDocument();
    expect(within(tabOf("Olive Fixture")).queryByTestId(/^platform-logo-/)).toBeNull();
    expect(await screen.findByText(FY_TEXT)).toBeInTheDocument();
    expect(screen.getByText(OF_TEXT)).toBeInTheDocument();
    cleanup();

    renderRoute(`/messages-pro/${FY_ID}/${FY_FAN.id}`);
    expect(await screen.findByRole("toolbar", { name: "Composer toolbar" })).toBeInTheDocument();
    await vi.waitFor(() => expect(tabs().getAllByRole("tab")).toHaveLength(2));
    expect(screen.queryByRole("button", { name: "Aa" })).toBeNull();
    cleanup();

    act(() => setPlatform("fansly"));
    renderRoute(`/messages-pro/${OF_ID}/${OF_FAN.id}`);
    expect(await screen.findByRole("button", { name: "Aa" })).toBeInTheDocument();
  });

  it("the Creator picker lists both, the Fansly row badged", async () => {
    renderRoute("/messages-pro");
    await vi.waitFor(() => expect(tabs().getAllByRole("tab")).toHaveLength(2));
    await userEvent.click(screen.getByRole("button", { name: /Add a Creator/ }));
    const picker = within(screen.getByRole("region", { name: "Creator picker" }));
    const rows = picker.getAllByRole("button");
    expect(rows).toHaveLength(2);
    const row = (name: string) => rows.find((r) => r.textContent?.includes(name))!;
    expect(within(row("Nova Fixture")).getByTestId("platform-logo-fansly")).toBeInTheDocument();
    expect(within(row("Olive Fixture")).queryByTestId(/^platform-logo-/)).toBeNull();
  });

  it("phone: the scope select lists both, the Fansly option badged", async () => {
    stubViewport(390);
    renderRoute("/messages-pro");
    await userEvent.click(await screen.findByRole("combobox", { name: "Creator" }));
    const options = await screen.findAllByRole("option");
    const nova = options.find((o) => o.textContent?.includes("Nova Fixture"))!;
    const olive = options.find((o) => o.textContent?.includes("Olive Fixture"))!;
    expect(within(nova).getByTestId("platform-logo-fansly")).toBeInTheDocument();
    expect(within(olive).queryByTestId(/^platform-logo-/)).toBeNull();
  });

  it("chatter: a granted Fansly Creator and a legacy OnlyFans row are tabs, the watcher is not", async () => {
    signInChatter();
    renderRoute(`/messages-pro/${FY_ID}/${FY_FAN.id}`);
    await vi.waitFor(() => expect(tabs().getAllByRole("tab").map((t) => t.getAttribute("title")?.split(" — ")[0]))
      .toEqual(["Nova Fixture", "Olive Fixture"]));
    expect(within(tabOf("Nova Fixture")).getByTestId("platform-logo-fansly")).toBeInTheDocument();
    expect(within(tabOf("Olive Fixture")).queryByTestId(/^platform-logo-/)).toBeNull();
    expect(await screen.findByRole("toolbar", { name: "Composer toolbar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aa" })).toBeNull();
  });

  it("a switch in the main window leaves the window's Creator alone; the main shell lists only the switch's Platform", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${OF_ID}`);
    renderRoute("/messages-pro");
    await vi.waitFor(() => expect(tabOf("Olive Fixture")).toHaveAttribute("aria-selected", "true"));
    act(() => setPlatform("fansly"));
    await new Promise((r) => setTimeout(r, 50));
    expect(tabOf("Olive Fixture")).toHaveAttribute("aria-selected", "true");
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${OF_ID}`);
    cleanup();

    act(() => setPlatform("onlyfans"));
    renderRoute("/", <ShellProbe />);
    const shell = within(await screen.findByRole("list", { name: "Shell creators" }));
    await vi.waitFor(() => expect(shell.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Olive Fixture"]));
  });
});
