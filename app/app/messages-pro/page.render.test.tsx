import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) =>
  (await import("@/components/chat/composerTestHarness")).mockRelayModule(await orig()));

const router = vi.hoisted(() => ({
  push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn(),
}));
const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

vi.mock("@/contexts/UserContext", async (orig) => {
  const value = { user: { username: "owner" }, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/UserContext")>()), useUser: () => value, useOptionalUser: () => value };
});
vi.mock("@/contexts/ChatterContext", async (orig) => {
  const value = { chatter: null, logout: vi.fn() };
  return { ...(await orig<typeof import("@/contexts/ChatterContext")>()), useChatter: () => value, useOptionalChatter: () => value };
});
vi.mock("@/contexts/EmployeeContext", async (orig) => {
  const employee: import("@/lib/relay").Employee = { id: 300000001, display_name: "Fixture Employee", color: null, is_active: true };
  const value: ReturnType<typeof import("@/contexts/EmployeeContext")["useEmployee"]> = {
    current: employee, roster: [employee], hydrated: true,
  };
  return { ...(await orig<typeof import("@/contexts/EmployeeContext")>()), useEmployee: () => value };
});

vi.mock("@/components/chat/ChatSurface", async () => {
  const { OpenInNewTabButton } = await import("@/components/chat/FanTabs");
  return {
    ChatSurface: ({ accountId, fanId, chat, prefetchWindowMs }: {
      accountId: string; fanId: number | string; chat: { withUser?: { name?: string }; lastMessage?: unknown };
      prefetchWindowMs?: number;
    }) => (
      <>
        <section aria-label="Thread" data-chat={chat.lastMessage ? "row" : "deep-link"} data-prefetch-window={prefetchWindowMs ?? "none"}>
          {`Creator ${accountId}, Fan ${fanId}`}
        </section>
        <OpenInNewTabButton accountId={accountId} fanId={fanId} name={chat.withUser?.name ?? ""} />
      </>
    ),
  };
});

import AppShell from "@/components/shell/AppShell";
import { MoneyRail } from "@/components/MoneyRail";
import { ScopeProvider, useScope } from "@/contexts/ScopeContext";
import { renderWithProviders } from "@/test-utils";
import { readBlurMode } from "@/hooks/useBlurMode";
import { UNREAD_WARM_REUSE_MS } from "@/hooks/useUnreadMessagesPrefetch";
import { resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import {
  expectDomOrder, observerStub, relayGet, relayPost, resetComposerHarness, routeRelay, streamUp, tooltipOf,
} from "@/components/chat/composerTestHarness";
import { SETTINGS_KEY as RAIL_SETTINGS_KEY } from "@/lib/moneyRailStorage";
import { eventBus } from "@/lib/events";
import { resetReadGate } from "@/lib/ofReadGate";
import { holdLease } from "@/lib/viewLease";
import { openNotification } from "@/lib/notificationLink";
import type { OFMessage } from "@/lib/relay";
import MessagesProPage from "./page";
import DeepLinkPage from "./[accountId]/[fanId]/page";


const ACCOUNT_ID = "100000001";
const OTHER_ACCOUNT_ID = "100000002";
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const account = (id: string, name: string) => ({
  id, nickname: name, name, platform: "onlyfans", color: "#e8618c",
  has_session: true, session_dead_at: null, created_at: ago(43_200), last_used_at: ago(5),
});
const ACCOUNTS = [account(ACCOUNT_ID, "Test Creator"), account(OTHER_ACCOUNT_ID, "Other Creator")];
const COUNTS = {
  [ACCOUNT_ID]: { unread: 2, owe_reply: 0 },
  [OTHER_ACCOUNT_ID]: { unread: 5, owe_reply: 0 },
};
const FANS = [
  { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" },
  { id: 200000002, name: "Fixture Fan Two", username: "fixturefantwo" },
  { id: 200000003, name: "Fixture Fan Three", username: "fixturefanthree" },
];
const FAN_FOUR = { id: 200000004, name: "Fixture Fan Four", username: "fixturefanfour" };
const fanUser = (f: (typeof FANS)[number]) => ({ ...f, avatar: null, customNickname: null, displayName: null });
const chatOf = (f: (typeof FANS)[number], i: number) => ({
  withUser: fanUser(f),
  lastMessage: {
    id: 800000000 + i, text: `Hello from ${f.name}`, fromUser: fanUser(f), createdAt: ago(60 + i),
    mediaCount: 0, isFree: true, isTip: false, isOpened: true,
  },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
});
const CHATS = FANS.map(chatOf);
const OTHER_CHATS = [FANS[2], FAN_FOUR].map(chatOf);
const PRESENCE = { online: new Set<number>(), lastSeen: new Map<number, string>() };

function serveFixture() {
  routeRelay("/admin/accounts/roster-counts", () => ({ counts: COUNTS }));
  routeRelay("/admin/accounts", () => ({ accounts: ACCOUNTS, active_account_id: ACCOUNT_ID }));
  routeRelay("/api/of/v2/chats?", (path, ctx) => {
    const offset = new URLSearchParams(path.split("?")[1]).get("offset") ?? "0";
    const list = (ctx?.accountId === OTHER_ACCOUNT_ID ? OTHER_CHATS : CHATS)
      .map((c) => ({
        ...c,
        withUser: { ...c.withUser, lastSeen: PRESENCE.lastSeen.get(c.withUser.id) ?? null },
        isOnline: PRESENCE.online.has(c.withUser.id),
      }));
    return { list: offset === "0" ? list : [], hasMore: false };
  });
  routeRelay("/api/of/v2/users/list", (path) => {
    const ids = new URLSearchParams(path.split("?")[1]).getAll("ids").flatMap((v) => v.split(","));
    return Object.fromEntries([...FANS, FAN_FOUR].filter((f) => ids.includes(String(f.id))).map((f) => [String(f.id), fanUser(f)]));
  });
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

let releaseLease: () => void = () => {};
beforeEach(() => {
  resetReadGate();
  releaseLease = holdLease("test", [ACCOUNT_ID, OTHER_ACCOUNT_ID]);
  resetComposerHarness();
  resetRosterCountsModuleState();
  PRESENCE.online.clear();
  PRESENCE.lastSeen.clear();
  for (const spy of Object.values(router)) spy.mockClear();
  nav.pathname = "/";
  serveFixture();
  window.history.replaceState(null, "", "/");
  stubViewport(1440);
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("IntersectionObserver", observerStub);
  vi.stubGlobal("ResizeObserver", observerStub);
  streamUp(eventBus);
});

afterEach(() => {
  cleanup();
  releaseLease();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});


function ScopeSwitch() {
  const { setScope } = useScope();
  return (
    <button type="button" onClick={() => setScope({ kind: "model", accountId: OTHER_ACCOUNT_ID })}>
      Scope to Other Creator
    </button>
  );
}

function pageTree(url: string, shell = false) {
  window.history.replaceState(null, "", url);
  const link = /^\/messages-pro\/([^/]+)\/([^/?]+)/.exec(url);
  const value = link && { accountId: link[1], fanId: link[2] };
  const page = value
    ? <DeepLinkPage params={Object.assign(Promise.resolve(value), { status: "fulfilled", value })} />
    : <MessagesProPage />;
  return (
    <ScopeProvider>
      {shell ? <AppShell><ScopeSwitch />{page}</AppShell> : <><ScopeSwitch />{page}</>}
    </ScopeProvider>
  );
}

const renderPage = (url: string) => renderWithProviders(pageTree(url));

function navigateTo(rendered: ReturnType<typeof renderPage>, url: string) {
  rendered.rerender(pageTree(url));
}

const threadText = () => screen.queryByRole("region", { name: "Thread" })?.textContent ?? null;
const rowsOf = (f: (typeof FANS)[number]) =>
  screen.queryAllByText(f.name).filter((el) => !el.closest('[role="tablist"]')).map((el) => el.closest("button")!);
const row = (f: (typeof FANS)[number]) => {
  const rows = rowsOf(f);
  if (rows.length !== 1) throw new Error(`expected one Fan List row for ${f.name}, found ${rows.length}`);
  return rows[0];
};
const listedFans = () =>
  [...FANS, FAN_FOUR].flatMap((f) => rowsOf(f).map((el) => ({ el, name: f.name })))
    .sort((a, b) => (a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
    .map((r) => r.name);
const fanTabsStrip = () => within(screen.getByRole("tablist", { name: "Fan tabs strip" }));
const fanTabNames = () => fanTabsStrip().queryAllByRole("tab").map((t) => t.textContent);
const creatorTab = (name: RegExp) =>
  within(screen.getByRole("region", { name: "Window header" })).findByRole("tab", { name });

describe("the Messages Pro page", () => {
  it("index route: the Fan List lists the fixture Fans, and clicking a row puts that Fan in the Thread", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");

    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expectDomOrder(FANS.map(row));
    expect(threadText()).toBeNull();

    await userEvent.click(row(FANS[1]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
  });

  it("the inbox Thread rides the unread warm: it is handed UNREAD_WARM_REUSE_MS (20 s) as its prefetch window, on the index and the Deep link route (fetch-diet 16)", async () => {
    expect(UNREAD_WARM_REUSE_MS).toBe(20_000);
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const first = renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan Two"));
    expect(screen.getByRole("region", { name: "Thread" })).toHaveAttribute("data-prefetch-window", "20000");
    first.unmount();

    renderPage(`/messages-pro/${ACCOUNT_ID}/200000003`);
    await vi.waitFor(() => expect(screen.getByRole("region", { name: "Thread" })).toHaveAttribute("data-prefetch-window", "20000"));
  });

  it("the Fan List's press warm-up skips a thread warmed inside UNREAD_WARM_REUSE_MS (17 s ago, past the 15 s default) and reads one warmed past it (23 s ago) (fetch-diet 16)", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const threadReads = (fanId: number) =>
      relayGet.mock.calls.filter(([path]) => path.startsWith(`/api/of/v2/chats/${fanId}/messages`));
    for (const f of FANS.slice(0, 2)) {
      routeRelay(`/api/of/v2/chats/${f.id}/messages`, () => ({ list: [], hasMore: false }));
    }
    const rendered = renderWithProviders(pageTree("/messages-pro"),
      new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await screen.findByText("Fixture Fan Three");
    const warmed = (f: (typeof FANS)[number], agoMs: number) => rendered.queryClient.setQueryData(
      ["messages", ACCOUNT_ID, f.id], [{ id: 700000000 + f.id % 10, text: "warmed", fromUser: { id: f.id }, createdAt: ago(2) }],
      { updatedAt: Date.now() - agoMs });
    warmed(FANS[0], 17_000);
    warmed(FANS[1], 23_000);
    relayGet.mockClear();

    await userEvent.click(row(FANS[0]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(threadReads(FANS[0].id)).toHaveLength(0);

    await userEvent.click(row(FANS[1]));
    await vi.waitFor(() => expect(threadReads(FANS[1].id)).toHaveLength(1));
  });

  it("Deep link route: the page opens with the link's Creator and Fan in the Thread", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const link = `/messages-pro/${OTHER_ACCOUNT_ID}/200000003`;

    async function expectArrived() {
      expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000003`);
      await vi.waitFor(() => expect(row(FANS[2])).toHaveAttribute("aria-current", "true"));
      expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000003`);
    }

    const first = renderPage(link);
    await expectArrived();
    first.unmount();

    const rendered = renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan One")).toBeInTheDocument();
    navigateTo(rendered, link);
    await expectArrived();
  });

  it("index route: switching the scope to another Creator clears the selection", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");

    await userEvent.click(await screen.findByText("Fixture Fan One"));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);

    await userEvent.click(screen.getByRole("button", { name: "Scope to Other Creator" }));
    expect(threadText()).toBeNull();
  });
  it("Home, the Creator tabs, Add a Creator, SFW, Online Fans and Notifications, in document order on the index route and the Deep link route; Home links to the inbox root, not the app; no roster", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);

    async function expectChromeInOrder(scoped: string) {
      const header = within(screen.getByRole("region", { name: "Window header" }));
      expect(header.queryByRole("link", { name: "Home" })).toBeNull();
      const home = within(screen.getByRole("region", { name: "Fan tabs" })).getByRole("link", { name: "Home" });
      expect(home).toHaveAttribute("href", "/messages-pro");
      const test = await header.findByRole("tab", { name: "Test Creator 2 unread" });
      const other = header.getByRole("tab", { name: "Other Creator 5 unread" });
      expect(header.getAllByRole("tab")).toEqual([test, other]);
      expectDomOrder([
        test,
        other,
        header.getByRole("button", { name: "Add a Creator" }),
        header.getByRole("switch", { name: "SFW" }),
        home,
        screen.getByRole("button", { name: "Online Fans" }),
        await screen.findByRole("button", { name: /^Notifications\b/ }),
      ]);
      await vi.waitFor(() => {
        expect(test).toHaveAttribute("aria-selected", String(scoped === ACCOUNT_ID));
        expect(other).toHaveAttribute("aria-selected", String(scoped === OTHER_ACCOUNT_ID));
      });
      expect(screen.queryByRole("button", { name: "Expand roster" })).toBeNull();
    }

    const first = renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    await expectChromeInOrder(ACCOUNT_ID);
    first.unmount();

    renderPage(`/messages-pro/${OTHER_ACCOUNT_ID}/200000003`);
    expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000003`);
    await expectChromeInOrder(OTHER_ACCOUNT_ID);
  });

  it("clicking a Creator tab switches the Fan List to that Creator and selects its tab", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Test Creator" })).toBeInTheDocument();

    const header = within(screen.getByRole("region", { name: "Window header" }));
    const other = await header.findByRole("tab", { name: "Other Creator 5 unread" });
    await userEvent.click(other);

    expect(await screen.findByRole("heading", { level: 2, name: "Other Creator" })).toBeInTheDocument();
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${OTHER_ACCOUNT_ID}`);
    expect(other).toHaveAttribute("aria-selected", "true");
    expect(header.getByRole("tab", { name: "Test Creator 2 unread" })).toHaveAttribute("aria-selected", "false");
  });

  it("Window header SFW: flipping it flips the shared blur store, and a chatterly-blur-mode-change event flips it back", async () => {
    window.localStorage.setItem("chatterly:blur-mode-last", "constant");
    renderPage("/messages-pro");
    const sfw = within(screen.getByRole("region", { name: "Window header" })).getByRole("switch", { name: "SFW" });
    expect(sfw).toHaveAttribute("aria-checked", "false");

    await userEvent.click(sfw);
    expect(readBlurMode()).toBe("constant");
    expect(sfw).toHaveAttribute("aria-checked", "true");

    window.localStorage.removeItem("chatterly:blur-mode");
    act(() => { window.dispatchEvent(new Event("chatterly-blur-mode-change")); });
    expect(sfw).toHaveAttribute("aria-checked", "false");
  });

  it("with no Fan selected the Thread reads the Clone's empty state under an empty Fan tabs row; at phone width neither top row renders", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const desktop = renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    const fanTabsRow = screen.getByRole("region", { name: "Fan tabs" });
    expect(fanTabsRow.childElementCount).toBe(2);
    expect(within(fanTabsRow).getByRole("tablist", { name: "Fan tabs strip" })).toBeEmptyDOMElement();
    desktop.unmount();

    stubViewport(390);
    renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Window header" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Fan tabs" })).toBeNull();
  });

  it("the Window header has no Extras overflow, All Models comes first in the Window header, and neither Group chat nor the scope switcher sits in the two top rows (TODO.md B2)", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    const headerEl = screen.getByRole("region", { name: "Window header" });
    const header = within(headerEl);
    const fanTabs = screen.getByRole("region", { name: "Fan tabs" });

    expect(header.queryByRole("button", { name: "Inflowwww extras" })).toBeNull();
    const allModels = header.getByRole("button", { name: "All Models" });
    const home = header.getByRole("link", { name: "Dashboard" });
    expect(headerEl.firstElementChild).toBe(home);
    expect(home).toHaveAttribute("href", "/");
    expect(home.nextElementSibling).toBe(allModels);
    expect(tooltipOf(allModels)).toBe("Inflowwww extra — All Models\nAll models");
    const test = await header.findByRole("tab", { name: "Test Creator 2 unread" });
    expectDomOrder([allModels, test]);
    for (const name of ["Group chat", "Scope switcher"]) {
      expect(headerEl).not.toHaveTextContent(name);
      expect(fanTabs).not.toHaveTextContent(name);
    }
  });

  it("All Models stays in the strip after a Creator tab is picked, and picking it scopes the page to every Creator and warms the others", async () => {
    window.localStorage.setItem("chatterly:scope", "all");
    renderPage("/messages-pro");
    const header = within(screen.getByRole("region", { name: "Window header" }));
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    expect(header.getByRole("button", { name: "All Models" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(await header.findByRole("tab", { name: "Test Creator 2 unread" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Test Creator" })).toBeInTheDocument();
    const allModels = header.getByRole("button", { name: "All Models" });
    expect(allModels).toHaveAttribute("aria-pressed", "false");
    relayGet.mockClear();

    await userEvent.click(allModels);
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    expect(window.localStorage.getItem("chatterly:scope")).toBe("all");
    expect(allModels).toHaveAttribute("aria-pressed", "true");
    await vi.waitFor(() => {
      const busts = relayGet.mock.calls.map(([path]) => path).filter((p) => p.includes("roster-counts?bust="));
      expect(busts).toContain(`/admin/accounts/roster-counts?bust=${OTHER_ACCOUNT_ID}`);
    });
  });

  it("a Fan tab of one Creator clicked while another Creator is scoped switches the Fan List to the tab's Creator and opens its Thread", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    expect(fanTabNames()).toEqual(["Fixture Fan One"]);

    await userEvent.click(await creatorTab(/^Other Creator/));
    expect(await screen.findByText("Fixture Fan Four")).toBeInTheDocument();
    expect(threadText()).toBeNull();
    const url = window.location.href;

    await userEvent.click(fanTabsStrip().getByRole("tab", { name: "Fixture Fan One" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Test Creator" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
    expect(row(FANS[0])).toHaveAttribute("aria-current", "true");
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan One" })).toHaveAttribute("aria-selected", "true");
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${ACCOUNT_ID}`);
    expect(window.location.href).toBe(url);
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("under All Models, a Fan tab click opens its Thread and leaves the scope at All Models", async () => {
    window.localStorage.setItem("chatterly:scope", "all");
    renderPage("/messages-pro");
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FAN_FOUR));
    expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000004`);

    await userEvent.click(fanTabsStrip().getByRole("tab", { name: "Fixture Fan One" }));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
    expect(screen.getByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    expect(row(FAN_FOUR)).toBeInTheDocument();
    expect(window.localStorage.getItem("chatterly:scope")).toBe("all");
  });

  it("a Fan List row click selects the Fan without adding a Fan tab and marks its tab active; switching Creator tabs leaves the Fan tabs strip as it was", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    expect(fanTabNames()).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    const tabOne = fanTabsStrip().getByRole("tab", { name: "Fixture Fan One" });

    await userEvent.click(row(FANS[1]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).toEqual(["Fixture Fan One"]);
    expect(tabOne).toHaveAttribute("aria-selected", "false");

    await userEvent.click(row(FANS[0]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
    expect(fanTabNames()).toEqual(["Fixture Fan One"]);
    expect(tabOne).toHaveAttribute("aria-selected", "true");
    const thread = screen.getByRole("region", { name: "Thread" });
    expect(thread).toHaveAttribute("data-chat", "row");
    await userEvent.click(tabOne);
    expect(screen.getByRole("region", { name: "Thread" })).toHaveAttribute("data-chat", "row");

    await userEvent.click(await creatorTab(/^Other Creator/));
    expect(await screen.findByText("Fixture Fan Four")).toBeInTheDocument();
    expect(fanTabNames()).toEqual(["Fixture Fan One"]);
    await userEvent.click(await creatorTab(/^Test Creator/));
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(fanTabNames()).toEqual(["Fixture Fan One"]);
  });

  it("✕ on the active Fan tab opens the last remaining tab's Thread", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[1]));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[2]));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[0]));
    expect(fanTabNames()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);

    await userEvent.click(fanTabsStrip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(fanTabNames()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000003`);
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan Three" })).toHaveAttribute("aria-selected", "true");
  });

  it("Ctrl+W closes the open Fan's tab and opens the last remaining one; with no tab for the open Fan it still claims the key (Electron's Ctrl+W would close the window) and changes nothing", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    const ctrlW = () => {
      const e = new KeyboardEvent("keydown", { key: "w", code: "KeyW", ctrlKey: true, bubbles: true, cancelable: true });
      act(() => { window.dispatchEvent(e); });
      return e.defaultPrevented;
    };
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[1]));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[0]));

    expect(ctrlW()).toBe(true);
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);

    await userEvent.click(row(FANS[2]));
    expect(ctrlW()).toBe(true);
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000003`);
  });

  it("Cmd+Shift+S and Ctrl+Shift+S flip the Window header's SFW", async () => {
    renderPage("/messages-pro");
    const sfw = within(screen.getByRole("region", { name: "Window header" })).getByRole("switch", { name: "SFW" });
    expect(sfw).toHaveAttribute("aria-checked", "false");
    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "S", code: "KeyS", metaKey: true, shiftKey: true })); });
    expect(sfw).toHaveAttribute("aria-checked", "true");
    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "S", code: "KeyS", ctrlKey: true, shiftKey: true })); });
    expect(sfw).toHaveAttribute("aria-checked", "false");
  });

  it("✕ on the last Fan tab, active or not, leaves the Thread on \"Select any conversation to start\"", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(fanTabsStrip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    expect(fanTabNames()).toEqual([]);

    await userEvent.click(row(FANS[0]));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[1]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    await userEvent.click(fanTabsStrip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    const fanTabsRow = screen.getByRole("region", { name: "Fan tabs" });
    expect(fanTabsRow.childElementCount).toBe(2);
    expect(within(fanTabsRow).getByRole("tablist", { name: "Fan tabs strip" })).toBeEmptyDOMElement();
  });

  const CREATOR_TABS_KEY = "chatterly:creator-tabs:v1:300000001";
  const creatorTabs = () => within(screen.getByRole("region", { name: "Window header" })).queryAllByRole("tab");

  it("?account=<id> opens on that Creator: its tab is active and the Fan List shows its rows, while the saved scope stays", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage(`/messages-pro?window=1&account=${OTHER_ACCOUNT_ID}`);

    expect(await screen.findByRole("heading", { level: 2, name: "Other Creator" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan Three", "Fixture Fan Four"]));
    expect(await creatorTab(/^Other Creator/)).toHaveAttribute("aria-selected", "true");
    expect(await creatorTab(/^Test Creator/)).toHaveAttribute("aria-selected", "false");
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${ACCOUNT_ID}`);

    window.localStorage.setItem("chatterly:scope", `model:${OTHER_ACCOUNT_ID}`);
    const testTab = await creatorTab(/^Test Creator/);
    await userEvent.click(testTab);
    expect(await screen.findByRole("heading", { level: 2, name: "Test Creator" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(testTab).toHaveAttribute("aria-selected", "true");
    expect(await creatorTab(/^Other Creator/)).toHaveAttribute("aria-selected", "false");
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${ACCOUNT_ID}`);
  });

  it("?account=<id> naming a Creator whose tab was stored as closed reopens and activates that tab", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    window.localStorage.setItem(CREATOR_TABS_KEY, JSON.stringify({ order: [], closed: [OTHER_ACCOUNT_ID] }));
    renderPage(`/messages-pro?window=1&account=${OTHER_ACCOUNT_ID}`);

    expect(await creatorTab(/^Other Creator/)).toHaveAttribute("aria-selected", "true");
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan Three", "Fixture Fan Four"]));
    expect(creatorTabs()).toEqual([await creatorTab(/^Test Creator 2 unread$/), await creatorTab(/^Other Creator 5 unread$/)]);
    expect(JSON.parse(window.localStorage.getItem(CREATOR_TABS_KEY)!)).toEqual({ order: [], closed: [] });
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${ACCOUNT_ID}`);
  });

  it("?account=<unknown id> leaves the window as it would open without the parameter", async () => {
    const stored = JSON.stringify({ order: [], closed: [OTHER_ACCOUNT_ID] });
    async function windowAt(url: string) {
      window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
      window.localStorage.setItem(CREATOR_TABS_KEY, stored);
      const rendered = renderPage(url);
      await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
      const testTab = await creatorTab(/^Test Creator 2 unread$/);
      expect(testTab).toHaveAttribute("aria-selected", "true");
      const seen = {
        heading: screen.getByRole("heading", { level: 2 }).textContent,
        onlyTestTab: creatorTabs().length === 1 && creatorTabs()[0] === testTab,
        thread: threadText(),
        savedScope: window.localStorage.getItem("chatterly:scope"),
        savedTabs: window.localStorage.getItem(CREATOR_TABS_KEY),
      };
      rendered.unmount();
      return seen;
    }

    const without = await windowAt("/messages-pro?window=1");
    expect(without).toEqual({
      heading: "Test Creator", onlyTestTab: true, thread: null,
      savedScope: `model:${ACCOUNT_ID}`, savedTabs: stored,
    });
    expect(await windowAt("/messages-pro?window=1&account=100000099")).toEqual(without);
  });


  const onlineFans = () => screen.getByRole("button", { name: "Online Fans" });

  it("\"Online Fans\" sits between the Fan List header and its filters, sets aria-pressed and narrows the list to online Fans; pressing it again restores every row", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    PRESENCE.online.add(FANS[0].id);
    PRESENCE.lastSeen.set(FANS[2].id, ago(1));
    renderPage("/messages-pro");

    const all = ["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"];
    await vi.waitFor(() => expect(listedFans()).toEqual(all));
    const button = onlineFans();
    expectDomOrder([
      screen.getByRole("group", { name: "Fan List header" }),
      button,
      screen.getByRole("group", { name: "Inbox, settings and sort" }),
    ]);
    expect(button).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Three"]));

    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(listedFans()).toEqual(all);
  });

  it("\"Online Fans\" keeps a Fan last seen 4m59s ago and drops one last seen 5m01s ago", async () => {
    const now = Date.now();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(now);
    PRESENCE.lastSeen.set(FANS[0].id, new Date(now - (4 * 60 + 59) * 1000).toISOString());
    PRESENCE.lastSeen.set(FANS[1].id, new Date(now - (5 * 60 + 1) * 1000).toISOString());
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One"]));
  });
  it("\"Online Fans\" with no Fan online says so in place of the rows", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual([]));
    expect(screen.getByText("No Fans online now")).toBeInTheDocument();
    expect(screen.queryByText("End of inbox.")).toBeNull();

    await userEvent.click(onlineFans());
    expect(screen.queryByText("No Fans online now")).toBeNull();
  });


  const ONLINE_LIST = "/api/of/v2/subscribers?";
  const onlineListReads = () => relayGet.mock.calls.filter(([path]) => path.includes(ONLINE_LIST));

  it("\"Online Fans\" keeps a Fan on the Creator's online list even though its row does not say online", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    routeRelay(ONLINE_LIST, (_path, ctx) =>
      ({ list: ctx?.accountId === ACCOUNT_ID ? [fanUser(FANS[1])] : [], hasMore: false }));
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(onlineListReads()).toEqual([]);
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan Two"]));

    expect(onlineListReads()).toHaveLength(1);
    const [path, ctx] = onlineListReads()[0];
    expect(Object.fromEntries(new URLSearchParams(path.split("?")[1]))).toEqual({ type: "active", online: "1", limit: "50" });
    expect(ctx?.accountId).toBe(ACCOUNT_ID);
    expect(tooltipOf(onlineFans())).toBe("Showing only fans online now: click to show all");
  });

  it("\"Online Fans\" falls back to the row rule when the online list fails, with the tooltip \"Online list unavailable\"; under All Models the list is not read", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    PRESENCE.online.add(FANS[0].id);
    routeRelay(ONLINE_LIST, () => Promise.reject(new Error("HTTP 502")));
    const scoped = renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(tooltipOf(onlineFans())).toBe("Online list unavailable"));
    expect(listedFans()).toEqual(["Fixture Fan One"]);
    expect(onlineListReads()).toHaveLength(1);
    scoped.unmount();

    relayGet.mockClear();
    window.localStorage.setItem("chatterly:scope", "all");
    renderPage("/messages-pro");
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Four"));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One"]));
    expect(onlineListReads()).toEqual([]);
    expect(tooltipOf(onlineFans())).toBe("Showing only fans online now: click to show all");
  });


  const NOTIF_COUNT = "/api/of/v2/users/notifications/count";
  const countReads = () => relayGet.mock.calls.filter(([path]) => path.includes(NOTIF_COUNT));
  const countReadsFor = (accountId: string) => countReads().filter(([, ctx]) => ctx?.accountId === accountId);
  const notifications = () => screen.getByRole("button", { name: /^Notifications\b/ });
  const serveCounts = (all: Record<string, number>) =>
    routeRelay(NOTIF_COUNT, (_path, ctx) => ({ all: all[ctx?.accountId ?? ""] ?? 0, subscribed: 1, purchases: 0, tip: 0 }));
  const NOTIF_READ = "/api/of/v2/users/notifications/read";
  const answerMarkRead = (all: number) => {
    relayPost.mockImplementation((path: string) => Promise.resolve(path === NOTIF_READ ? { counters: { all } } : {}));
    onTestFinished(() => { relayPost.mockReset(); relayPost.mockImplementation(() => Promise.resolve({})); });
  };
  const markReads = () => relayPost.mock.calls.filter(([path]) => path === NOTIF_READ);

  it("\"Notifications\" sits beside Online Fans, and its badge shows `all` from the count route for the scoped Creator, following a scope change; each Creator tab shows its own count in teal (page-parity 07 SH6)", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    serveCounts({ [ACCOUNT_ID]: 7, [OTHER_ACCOUNT_ID]: 120 });
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 7"));
    expectDomOrder([onlineFans(), notifications(), screen.getByRole("group", { name: "Inbox, settings and sort" })]);
    expect(countReadsFor(ACCOUNT_ID)).toHaveLength(1);
    const tabCounts = () => within(screen.getByRole("tablist", { name: "Creator tabs" }))
      .queryAllByText("notifications").map((sr) => sr.parentElement!);
    await vi.waitFor(() => expect(tabCounts().map((b) => b.textContent)).toEqual(["7 notifications", "99+ notifications"]));
    for (const b of tabCounts()) expect(b).toHaveClass("bg-[var(--inf-online,var(--color-ok))]");

    await userEvent.click(screen.getByRole("button", { name: "Scope to Other Creator" }));
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 120"));
    expect(countReadsFor(OTHER_ACCOUNT_ID)).toHaveLength(1);
  });

  it("\"Notifications\" hides its badge at zero and on a failed read; under All Models it sums the Creator tabs' cached counts", async () => {
    let reply: () => unknown = () => ({ all: 0, subscribed: 0, purchases: 0, tip: 0 });
    routeRelay(NOTIF_COUNT, () => reply());
    answerMarkRead(0);
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const zero = renderPage("/messages-pro");
    await vi.waitFor(() => expect(countReadsFor(ACCOUNT_ID)).toHaveLength(1));
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan One"));
    expect(notifications()).toHaveAccessibleName("Notifications");
    zero.unmount();

    relayGet.mockClear();
    reply = () => ({ all: 4, subscribed: 4, purchases: 0, tip: 0 });
    const failed = renderPage("/messages-pro");
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 4"));
    reply = () => Promise.reject(new Error("HTTP 502"));
    await userEvent.click(notifications());
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(countReadsFor(ACCOUNT_ID)).toHaveLength(2));
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications"));
    failed.unmount();

    relayGet.mockClear();
    reply = () => ({ all: 7, subscribed: 7, purchases: 0, tip: 0 });
    window.localStorage.setItem("chatterly:scope", "all");
    renderPage("/messages-pro");
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Four"));
    await vi.waitFor(() => expect(within(screen.getByRole("tablist", { name: "Creator tabs" })).getAllByText("notifications").length).toBeGreaterThan(0));
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 14"));
  });

  it("clicking \"Notifications\" opens the bell's panel and filters for the scoped Creator; closing it reads the count again", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    serveCounts({ [ACCOUNT_ID]: 3 });
    answerMarkRead(0);
    routeRelay("/api/of/v2/users/notifications?", (_path, ctx) => ctx?.accountId === ACCOUNT_ID
      ? [{ id: 900000001, type: "subscribed", text: "subscribed to your profile", createdAt: ago(3), user: fanUser(FANS[1]) }]
      : []);
    renderPage("/messages-pro");
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 3"));
    expect(screen.queryByText("subscribed to your profile")).toBeNull();

    await userEvent.click(notifications());
    expect(await screen.findByText("subscribed to your profile")).toBeInTheDocument();
    expect(markReads().map(([, , ctx]) => ctx?.accountId)).toEqual([ACCOUNT_ID]);
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications"));
    for (const name of ["Subscriptions", "Purchases", "Tips", "Comments", "Likes"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument();
    const listReads = relayGet.mock.calls.filter(([path]) => path.includes("/api/of/v2/users/notifications?"));
    expect(listReads.map(([, ctx]) => ctx?.accountId)).toEqual([ACCOUNT_ID]);

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText("subscribed to your profile")).toBeNull();
    await vi.waitFor(() => expect(countReadsFor(ACCOUNT_ID)).toHaveLength(2));
  });


  const railSwitch = () => screen.getByRole("switch", { name: "Buys & tips" });
  const railShown = () => screen.queryByRole("button", { name: /Buys & tips/ }) !== null;
  const storedSurfaces = () => JSON.parse(window.localStorage.getItem(RAIL_SETTINGS_KEY) ?? "null")?.surfaces;
  const renderWithRail = () => {
    nav.pathname = "/messages-pro";
    return renderWithProviders(<>{pageTree("/messages-pro")}<MoneyRail /></>);
  };

  it("a \"Notif\" (Buys & tips) switch sits in the Window header just before SFW (the far right), on with the rail shown; off hides the rail on this page, on brings it back, and Notifications still opens its panel", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderWithRail();
    await vi.waitFor(() => expect(railSwitch()).toBeEnabled());

    const header = within(screen.getByRole("region", { name: "Window header" }));
    expect(header.getByRole("switch", { name: "Buys & tips" })).toHaveTextContent("Notif");
    const switches = header.getAllByRole("switch");
    expect(switches.slice(-2)).toEqual([railSwitch(), header.getByRole("switch", { name: "SFW" })]);
    expect(within(screen.getByRole("group", { name: "Fan List header" })).queryByRole("switch")).toBeNull();
    expect(railSwitch()).toHaveAttribute("aria-checked", "true");
    expect(tooltipOf(railSwitch())).toBe("Buys & tips notifications panel shown: click to hide it on this page");
    await vi.waitFor(() => expect(railShown()).toBe(true));

    await userEvent.click(railSwitch());
    expect(railSwitch()).toHaveAttribute("aria-checked", "false");
    expect(tooltipOf(railSwitch())).toBe("Buys & tips notifications panel hidden: click to show it on this page");
    await vi.waitFor(() => expect(railShown()).toBe(false));
    expect(storedSurfaces()).toEqual(["popup", "group"]);

    await userEvent.click(notifications());
    await vi.waitFor(() => expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument());

    await userEvent.click(railSwitch());
    expect(railSwitch()).toHaveAttribute("aria-checked", "true");
    await vi.waitFor(() => expect(railShown()).toBe(true));
    expect(storedSurfaces()).toEqual(["inbox", "popup", "group"]);
  });

  it("the Buys & tips choice survives a reload, and follows the rail's settings written elsewhere", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const first = renderWithRail();
    await vi.waitFor(() => expect(railSwitch()).toBeEnabled());
    await userEvent.click(railSwitch());
    expect(railSwitch()).toHaveAttribute("aria-checked", "false");
    first.unmount();

    renderWithRail();
    await vi.waitFor(() => expect(railSwitch()).toBeEnabled());
    expect(railSwitch()).toHaveAttribute("aria-checked", "false");
    expect(railShown()).toBe(false);

    window.localStorage.setItem(RAIL_SETTINGS_KEY, JSON.stringify({ ...JSON.parse(window.localStorage.getItem(RAIL_SETTINGS_KEY)!), surfaces: null }));
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: RAIL_SETTINGS_KEY })); });
    expect(railSwitch()).toHaveAttribute("aria-checked", "true");
    await vi.waitFor(() => expect(railShown()).toBe(true));
  });

  it("at phone width there is no Notif switch: Messages Pro draws the rail from lg up only, so the switch did nothing there; a rail hidden here still comes back from Notifications", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    window.localStorage.setItem(RAIL_SETTINGS_KEY, JSON.stringify({ smallRows: 1, bigRows: 6, accounts: null, surfaces: ["popup", "group"] }));
    stubViewport(390);
    renderWithRail();
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Buys & tips" })).toBeNull();
    expect(railShown()).toBe(false);

    await userEvent.click(notifications());
    await userEvent.click(await screen.findByRole("button", { name: /rail is hidden here/ }));
    expect(storedSurfaces()).toEqual(["inbox", "popup", "group"]);
    await vi.waitFor(() => expect(railShown()).toBe(true));
    expect(screen.getByRole("button", { name: /Buys & tips/ }).closest(".fixed")).toHaveClass("hidden", "lg:flex");
  });


  const FAN_TABS_KEY = "chatterly:fan-tabs:v1:300000001";
  const serveNotificationAboutFanTwo = () => routeRelay("/api/of/v2/users/notifications?", (_path, ctx) =>
    ctx?.accountId === ACCOUNT_ID
      ? [{ id: 900000002, type: "tip", text: "sent you a tip", createdAt: ago(2), user: fanUser(FANS[1]) }]
      : []);
  const notificationRow = async () => (await screen.findByText("sent you a tip")).closest("button")!;

  it("a notification row about a Fan opens that Fan in a Fan tab in this window, and opening it again reuses the tab", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    serveNotificationAboutFanTwo();
    const windowOpen = vi.fn();
    vi.stubGlobal("open", windowOpen);
    renderPage("/messages-pro");
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Two"));
    expect(fanTabNames()).toEqual([]);

    await userEvent.click(notifications());
    await userEvent.click(await notificationRow());
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan Two" })).toHaveAttribute("aria-selected", "true");
    expect(windowOpen).not.toHaveBeenCalled();
    expect(screen.queryByText("Fan tab limit reached (100)")).toBeNull();

    await userEvent.click(row(FANS[0]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
    await userEvent.click(notifications());
    await userEvent.click(await notificationRow());
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(JSON.parse(window.localStorage.getItem(FAN_TABS_KEY)!)).toEqual([
      { accountId: ACCOUNT_ID, fanId: "200000002", name: "Fixture Fan Two" },
    ]);
  });

  it("a notification's link (?fanTab) opening the window adds the Fan's tab once and drops the parameter; a plain Deep link adds none", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const first = renderPage(`/messages-pro/${ACCOUNT_ID}/200000002?fanTab=Fixture+Fan+Two`);
    await vi.waitFor(() => expect(fanTabNames()).toEqual(["Fixture Fan Two"]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan Two" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toBe("");
    expect(JSON.parse(window.localStorage.getItem(FAN_TABS_KEY)!)).toEqual([
      { accountId: ACCOUNT_ID, fanId: "200000002", name: "Fixture Fan Two" },
    ]);
    first.unmount();

    renderPage(`/messages-pro/${ACCOUNT_ID}/200000001`);
    await vi.waitFor(() => expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`));
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
  });

  it("a notification clicked in this window (a toast) adds the Fan's tab in place, with no new window", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const windowOpen = vi.fn();
    vi.stubGlobal("open", windowOpen);
    const { queryClient } = renderPage("/messages-pro");
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Two"));
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    act(() => openNotification(`/messages-pro/${ACCOUNT_ID}/200000002?fanTab=Fixture+Fan+Two`));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(windowOpen).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/messages-pro");
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["messages", ACCOUNT_ID, 200000002] });

    act(() => openNotification(`/messages-pro/${ACCOUNT_ID}/200000002?refresh=media&fanTab=Fixture+Fan+Two`));
    expect(fanTabNames()).toEqual(["Fixture Fan Two"]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["messages", ACCOUNT_ID, 200000002] });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("at 100 Fan tabs a notification row still opens the Fan's Thread, adds no tab, and the panel says \"Fan tab limit reached (100)\"", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const seed = JSON.stringify(Array.from({ length: 100 }, (_, i) =>
      ({ accountId: ACCOUNT_ID, fanId: String(700000000 + i), name: `Fixture Seeded Fan ${i}` })));
    window.localStorage.setItem(FAN_TABS_KEY, seed);
    serveNotificationAboutFanTwo();
    renderPage("/messages-pro");
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Two"));
    expect(fanTabNames()).toHaveLength(100);

    await userEvent.click(notifications());
    const notificationButton = await notificationRow();
    await userEvent.click(notificationButton);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    const listRow = rowsOf(FANS[1]).filter((el) => el !== notificationButton);
    expect(listRow).toHaveLength(1);
    expect(listRow[0]).toHaveAttribute("aria-current", "true");
    expect(fanTabNames()).toHaveLength(100);
    expect(fanTabNames()).not.toContain("Fixture Fan Two");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    const notice = screen.getByText("Fan tab limit reached (100)");
    expect(notice).toHaveAttribute("role", "status");
    expect(notice.parentElement).toContainElement(screen.getByText("sent you a tip"));
  });

  it("at 100 Fan tabs a toast or another window's notification still opens the Thread, adds no tab, and says \"Fan tab limit reached (100)\"", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const seed = JSON.stringify(Array.from({ length: 100 }, (_, i) =>
      ({ accountId: ACCOUNT_ID, fanId: String(700000000 + i), name: `Fixture Seeded Fan ${i}` })));
    window.localStorage.setItem(FAN_TABS_KEY, seed);
    const first = renderPage(`/messages-pro/${ACCOUNT_ID}/200000001?fanTab=Fixture+Fan+One`);
    expect(await screen.findByText("Fan tab limit reached (100)")).toHaveAttribute("role", "status");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    first.unmount();

    renderPage("/messages-pro");
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Two"));
    expect(screen.queryByText("Fan tab limit reached (100)")).toBeNull();
    act(() => openNotification(`/messages-pro/${ACCOUNT_ID}/200000002?fanTab=Fixture+Fan+Two`));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).not.toContain("Fixture Fan Two");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    expect(screen.getByText("Fan tab limit reached (100)")).toHaveAttribute("role", "status");
  });


  const serveMessageFromFanFour = () => routeRelay("/api/of/v2/users/notifications?", (_path, ctx) =>
    ctx?.accountId === OTHER_ACCOUNT_ID
      ? [{ id: 900000003, type: "message", text: "sent you a message", createdAt: ago(1), user: fanUser(FAN_FOUR) }]
      : []);
  const THREAD_OF_FAN_FOUR = `/api/of/v2/chats/${FAN_FOUR.id}/messages`;
  async function openReply() {
    onTestFinished(() => { relayPost.mockReset(); });
    window.localStorage.setItem("chatterly:scope", "all");
    serveMessageFromFanFour();
    const { queryClient } = renderPage("/messages-pro");
    queryClient.setQueryDefaults(["messages"], { gcTime: Infinity });
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Four"));
    await userEvent.click(notifications());
    await screen.findByText("sent you a message");
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    const fanFourMessages = () =>
      queryClient.getQueryData<OFMessage[]>(["messages", OTHER_ACCOUNT_ID, FAN_FOUR.id]) ?? [];
    return { field: await screen.findByRole("textbox", { name: "Reply to Fixture Fan Four" }), fanFourMessages };
  }

  it("a message notification's Reply posts the text to the Fan's chat messages route as the notification's Creator, then clears and reads \"Sent\"", async () => {
    const { field } = await openReply();
    await vi.waitFor(() => expect(relayGet.mock.calls.filter(([path]) => path.startsWith(`${THREAD_OF_FAN_FOUR}?`))
      .map(([, ctx]) => ctx?.accountId)).toEqual([OTHER_ACCOUNT_ID]));
    relayPost.mockImplementation((path: string) => Promise.resolve(path === THREAD_OF_FAN_FOUR
      ? { id: 810000001, text: "Fixture quick reply", fromUser: { id: 100000002 }, createdAt: ago(0) }
      : {}));

    await userEvent.type(field, "Fixture quick reply");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await vi.waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    expect(field).toHaveValue("");
    const sends = relayPost.mock.calls.filter(([path]) => path === THREAD_OF_FAN_FOUR);
    expect(sends).toHaveLength(1);
    expect(sends[0]).toEqual([
      THREAD_OF_FAN_FOUR,
      { text: "Fixture quick reply", locked_text: false, price: 0, media_files: [] },
      { accountId: OTHER_ACCOUNT_ID, employeeId: 300000001 },
    ]);
    expect(threadText()).toBeNull();
    expect(fanTabNames()).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    expect(screen.queryByRole("textbox", { name: "Reply to Fixture Fan Four" })).toBeNull();
  });

  it("a rejected Reply keeps the text and shows the error, with no \"Sent\", and leaves its failed bubble in the Fan's messages", async () => {
    const { field, fanFourMessages } = await openReply();
    relayPost.mockImplementation((path: string) => path === THREAD_OF_FAN_FOUR
      ? Promise.reject(new Error("Fixture relay refused the send"))
      : Promise.resolve({}));

    await userEvent.type(field, "Fixture quick reply");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Fixture relay refused the send");
    expect(field).toHaveValue("Fixture quick reply");
    expect(screen.queryByText("Sent")).toBeNull();
    expect(relayPost.mock.calls.filter(([path]) => path === THREAD_OF_FAN_FOUR)).toHaveLength(1);
    expect(fanFourMessages().filter((m) => m._failed).map((m) => m.text)).toEqual(["Fixture quick reply"]);
  });

  it("replies from a reopened Reply field keep each reply in the Fan's messages", async () => {
    const { fanFourMessages } = await openReply();
    let serverId = 810000010;
    relayPost.mockImplementation((path: string, body?: unknown) => Promise.resolve(path === THREAD_OF_FAN_FOUR
      ? { id: ++serverId, text: (body as { text: string }).text, fromUser: { id: 100000002 }, createdAt: ago(0) }
      : {}));
    const reply = screen.getByRole("button", { name: "Reply" });
    const field = () => screen.getByRole("textbox", { name: "Reply to Fixture Fan Four" });

    await userEvent.type(field(), "Fixture first reply");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    await userEvent.click(reply);
    await userEvent.click(reply);
    await userEvent.type(field(), "Fixture second reply");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));

    expect(fanFourMessages().map((m) => [m.id, m.text])).toEqual([
      [810000011, "Fixture first reply"],
      [810000012, "Fixture second reply"],
    ]);
  });


  const storedTab = (f: (typeof FANS)[number]) => ({ accountId: ACCOUNT_ID, fanId: String(f.id), name: f.name });
  const otherWindowWritesFanTabs = (tabs: ReturnType<typeof storedTab>[]) =>
    act(() => {
      window.localStorage.setItem(FAN_TABS_KEY, JSON.stringify(tabs));
      window.dispatchEvent(new StorageEvent("storage", { key: FAN_TABS_KEY, newValue: JSON.stringify(tabs) }));
    });

  async function openFanOneWithTabs(width: number, fans = FANS) {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    window.localStorage.setItem(FAN_TABS_KEY, JSON.stringify(fans.map(storedTab)));
    stubViewport(width);
    renderPage("/messages-pro");
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000001`);
  }

  it("at phone width, another window closing the open Fan's tab moves the Thread to the last remaining tab; closing an inactive one changes nothing", async () => {
    await openFanOneWithTabs(390);
    expect(screen.queryByRole("region", { name: "Fan tabs" })).toBeNull();

    await otherWindowWritesFanTabs([storedTab(FANS[1]), storedTab(FANS[2])]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000003`);

    await otherWindowWritesFanTabs([storedTab(FANS[2])]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000003`);
  });

  it("at phone width, another window closing the last Fan tab clears the Thread to \"Select any conversation to start\"", async () => {
    await openFanOneWithTabs(390, [FANS[0]]);

    await otherWindowWritesFanTabs([]);
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
  });

  it("at desktop width, another window closing the open Fan's tab moves the Thread and the active tab to the last remaining tab", async () => {
    await openFanOneWithTabs(1440);
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan One" })).toHaveAttribute("aria-selected", "true");

    await otherWindowWritesFanTabs([storedTab(FANS[1]), storedTab(FANS[2])]);
    expect(fanTabNames()).toEqual(["Fixture Fan Two", "Fixture Fan Three"]);
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000003`);
    expect(fanTabsStrip().getByRole("tab", { name: "Fixture Fan Three" })).toHaveAttribute("aria-selected", "true");

    await otherWindowWritesFanTabs([]);
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
  });
});


describe("the Messages Pro page through the app shell", () => {
  function renderInShell(url: string) {
    nav.pathname = url.split("?")[0];
    return renderWithProviders(pageTree(url, true));
  }

  for (const url of ["/messages-pro", "/messages-pro?window=1", `/messages-pro/${ACCOUNT_ID}/200000002`]) {
    it(`at desktop ${url} has no Top bar, sidebar or app controls, in the Window header or anywhere`, async () => {
      window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
      renderInShell(url);
      const header = within(await screen.findByRole("region", { name: "Window header" }));
      expect(screen.queryByRole("banner")).toBeNull();
      expect(document.getElementById("app-sidebar")).toBeNull();
      expect(screen.queryByRole("button", { name: "Toggle sidebar" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Account menu" })).toBeNull();
      expect(header.queryByTitle("Your time zone")).toBeNull();
      expect(header.getByRole("switch", { name: "SFW" })).toBeInTheDocument();
    });
  }

  it("below lg the page fills the tab too: no Top bar and no Window header", async () => {
    stubViewport(390);
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderInShell("/messages-pro");
    expect(await screen.findByText("Fixture Fan Three")).toBeInTheDocument();
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("region", { name: "Window header" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Toggle sidebar" })).toBeNull();
  });
});
