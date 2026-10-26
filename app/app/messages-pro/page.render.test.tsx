/**
 * The Messages Pro page: seam 2 of docs/spec/phase-01-window-chrome-tabs.md
 * (Testing Decisions). The index page and the Deep link page render with the
 * real `MessagesPro`, the real Fan List and the real scope and flags
 * providers. The relay client is mocked by path through the shared harness
 * (`components/chat/composerTestHarness.tsx`), `EventSource` and `matchMedia`
 * are stubbed, the user / chatter / Employee contexts are fixed as
 * `windowed.test.tsx` fixes them (with a fixed Employee), and the Thread
 * (`ChatSurface`) is a marker naming its Creator and Fan id: the Thread is
 * another Region, and only the selection is under test here. Every later
 * Phase 1 ticket adds its cases here.
 *
 * Fixture identifiers are invented (this repo mirrors to a public one).
 */
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("@/components/chat/composerTestHarness")).mockRelayModule(await orig()));

// The setup file's router, with spies a case can read: a Fan tab click must
// not navigate.
const router = vi.hoisted(() => ({
  push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn(),
}));
// The path `usePathname` reports: "/" unless a case renders through the app
// shell, which reads it to tell a Messages Pro route.
const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// An owner signed in, no chatter, and a fixed Employee at the keyboard.
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

// The Thread, as a marker naming the Creator and Fan it was opened for, and
// the Chat header's real "Open in new tab" beside it. `data-chat` says
// whether it was handed a Fan List row (with its last message) or the Deep
// link's thin chat.
vi.mock("@/components/chat/ChatSurface", async () => {
  const { OpenInNewTabButton } = await import("@/components/chat/FanTabs");
  return {
    ChatSurface: ({ accountId, fanId, chat }: {
      accountId: string; fanId: number | string; chat: { withUser?: { name?: string }; lastMessage?: unknown };
    }) => (
      <>
        <section aria-label="Thread" data-chat={chat.lastMessage ? "row" : "deep-link"}>
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
import { resetRosterCountsModuleState } from "@/hooks/useRosterCounts";
import {
  expectDomOrder, observerStub, relayGet, relayPost, resetComposerHarness, routeRelay, tooltipOf,
} from "@/components/chat/composerTestHarness";
import { SETTINGS_KEY as RAIL_SETTINGS_KEY } from "@/lib/moneyRailStorage";
import { openNotification } from "@/lib/notificationLink";
import type { OFMessage } from "@/lib/relay";
import MessagesProPage from "./page";
import DeepLinkPage from "./[accountId]/[fanId]/page";

/* ── fixtures: two Creators, four Fans ─────────────────────────────────── */

const ACCOUNT_ID = "100000001";
const OTHER_ACCOUNT_ID = "100000002";
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const account = (id: string, name: string) => ({
  id, nickname: name, name, platform: "onlyfans", color: "#e8618c",
  has_session: true, session_dead_at: null, created_at: ago(43_200), last_used_at: ago(5),
});
const ACCOUNTS = [account(ACCOUNT_ID, "Test Creator"), account(OTHER_ACCOUNT_ID, "Other Creator")];
/** Unread conversations per Creator, as the roster counts report them. */
const COUNTS = {
  [ACCOUNT_ID]: { unread: 2, owe_reply: 0 },
  [OTHER_ACCOUNT_ID]: { unread: 5, owe_reply: 1 },
};
const FANS = [
  { id: 200000001, name: "Fixture Fan One", username: "fixturefanone" },
  { id: 200000002, name: "Fixture Fan Two", username: "fixturefantwo" },
  { id: 200000003, name: "Fixture Fan Three", username: "fixturefanthree" },
];
/** Only the other Creator's. */
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
/** Each Creator's Fan List: the first Creator has Fans One to Three, the other
 *  Fan Three and Fan Four. */
const CHATS = FANS.map(chatOf);
const OTHER_CHATS = [FANS[2], FAN_FOUR].map(chatOf);
/** Presence a case sets before it renders, as the chat rows carry it: the
 *  Fans whose row says online, and each Fan's `lastSeen`. Empty unless a case
 *  fills it. */
const PRESENCE = { online: new Set<number>(), lastSeen: new Map<number, string>() };

/** The relay as these cases need it, by path and Creator. */
function serveFixture() {
  // Before "/admin/accounts", which would match it too. Distinct unread totals.
  routeRelay("/admin/accounts/roster-counts", () => ({ counts: COUNTS }));
  routeRelay("/admin/accounts", () => ({ accounts: ACCOUNTS, active_account_id: ACCOUNT_ID }));
  // The trailing "?" keeps the Thread and folder routes out of this one.
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
  // The Deep link's profile lookup and the Fan List's enrichment.
  routeRelay("/api/of/v2/users/list", (path) => {
    const ids = new URLSearchParams(path.split("?")[1]).getAll("ids").flatMap((v) => v.split(","));
    return Object.fromEntries([...FANS, FAN_FOUR].filter((f) => ids.includes(String(f.id))).map((f) => [String(f.id), fanUser(f)]));
  });
}

/* ── jsdom gaps ─────────────────────────────────────────────────────────── */

/** `matchMedia` for a viewport `width` px wide: 1440 is the desktop every case
 *  starts at, 390 a phone. */
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
// For the whole file, outside vi.stubGlobal: a scope change schedules the SSE
// bus's reconnect 50ms out (lib/events.ts setScope), which may fire after a
// case's teardown and read `EventSource.OPEN`.
Object.defineProperty(globalThis, "EventSource", { value: FakeEventSource, configurable: true, writable: true });

beforeEach(() => {
  resetComposerHarness();
  // The roster counts' 8s refresh cooldown is module state: no case inherits
  // another's.
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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/* ── render ─────────────────────────────────────────────────────────────── */

/** Changes this window's scope as any scope switcher does (`useScope`), so a
 *  case does not depend on which control Phase 1 gives the switch. */
function ScopeSwitch() {
  const { setScope } = useScope();
  return (
    <button type="button" onClick={() => setScope({ kind: "model", accountId: OTHER_ACCOUNT_ID })}>
      Scope to Other Creator
    </button>
  );
}

/** The page Next routes `url` to, the index or a Deep link, under the
 *  providers; inside
 *  `AppShell`, within the providers as `app/layout.tsx` places it, when
 *  `shell` is set. */
function pageTree(url: string, shell = false) {
  window.history.replaceState(null, "", url);
  const link = /^\/messages-pro\/([^/]+)\/([^/?]+)/.exec(url);
  // Already fulfilled, as React's `use` marks a settled thenable, so the page
  // reads its params on first render (as windowed.test.tsx does).
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

/** A window opened at `url`. */
const renderPage = (url: string) => renderWithProviders(pageTree(url));

/** A client-side navigation to `url`: the providers stay mounted, so the scope
 *  already holds the saved Creator when the page mounts (as windowed.test.tsx's
 *  `navigateTo`). */
function navigateTo(rendered: ReturnType<typeof renderPage>, url: string) {
  rendered.rerender(pageTree(url));
}

/** The Thread marker's text, exactly; null with no Thread open. */
const threadText = () => screen.queryByRole("region", { name: "Thread" })?.textContent ?? null;
/** Every Fan List row naming `f`; a Fan tab with the same name is not one. */
const rowsOf = (f: (typeof FANS)[number]) =>
  screen.queryAllByText(f.name).filter((el) => !el.closest('[role="tablist"]')).map((el) => el.closest("button")!);
/** The one Fan List row naming `f`; throws on none or more than one. */
const row = (f: (typeof FANS)[number]) => {
  const rows = rowsOf(f);
  if (rows.length !== 1) throw new Error(`expected one Fan List row for ${f.name}, found ${rows.length}`);
  return rows[0];
};
/** Every Fan List row, by Fan name, in document order. */
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

  it("Deep link route: the page opens with the link's Creator and Fan in the Thread", async () => {
    // The saved scope and the active account name the first Creator; the link
    // names the other, so only the link can put it in the Thread, and the
    // arrival selection has to survive the scope moving off the saved Creator.
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const link = `/messages-pro/${OTHER_ACCOUNT_ID}/200000003`;

    async function expectArrived() {
      expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000003`);
      // Still there once the link's Creator's Fan List has loaded and marks the Fan.
      await vi.waitFor(() => expect(row(FANS[2])).toHaveAttribute("aria-current", "true"));
      expect(threadText()).toBe(`Creator ${OTHER_ACCOUNT_ID}, Fan 200000003`);
    }

    // A window opened straight at the link.
    const first = renderPage(link);
    await expectArrived();
    first.unmount();

    // From the index page, already scoped to the saved Creator, into the link.
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

    /** Each Creator's tab (name and unread total, in the relay's order),
     *  "+ Add a Creator", SFW, Home in the Fan tabs row under them, then the
     *  Fan List buttons; the tab of `scoped` is the selected one. */
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
      // The roster rail is gone from Messages Pro.
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
    // The Employee's last blurred variant, which the top bar's SFW restores too.
    window.localStorage.setItem("chatterly:blur-mode-last", "constant");
    renderPage("/messages-pro");
    const sfw = within(screen.getByRole("region", { name: "Window header" })).getByRole("switch", { name: "SFW" });
    expect(sfw).toHaveAttribute("aria-checked", "false");

    await userEvent.click(sfw);
    expect(readBlurMode()).toBe("constant");
    expect(sfw).toHaveAttribute("aria-checked", "true");

    // Another control (the app top bar's SFW, the chat gear) turns blur off.
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
    // Empty: the row holds only Home and the Fan tabs strip, and the strip holds nothing.
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
    // Our mark comes first, the way back to the Dashboard; All Models right after it.
    const home = header.getByRole("link", { name: "Dashboard" });
    expect(headerEl.firstElementChild).toBe(home);
    expect(home).toHaveAttribute("href", "/");
    expect(home.nextElementSibling).toBe(allModels);
    expect(tooltipOf(allModels)).toBe("Inflowwww extra — All Models\nAll models");
    const test = await header.findByRole("tab", { name: "Test Creator 2 unread" });
    expectDomOrder([allModels, test]);
    // Group chat stays in the Chat header's Extras overflow (the extras audit's
    // assertion 6); the Creator tabs and All Models pick the scope.
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
    // The Creator just picked was warmed then (each refresh is cooldown-guarded).
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

    // Scope the other Creator: the scope guard clears the Thread.
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
    // The URL does not change, through history or the router.
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
    // Open the other Creator's Fan, so the tab is not the open one.
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
    // Clicking the active tab keeps the Thread on the row it was opened with.
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
    // The last tab is the open conversation.
    await userEvent.click(await screen.findByText("Fixture Fan One"));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(fanTabsStrip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    expect(fanTabNames()).toEqual([]);

    // The last tab is not the open conversation.
    await userEvent.click(row(FANS[0]));
    await userEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
    await userEvent.click(row(FANS[1]));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    await userEvent.click(fanTabsStrip().getByRole("button", { name: "Close Fixture Fan One" }));
    expect(threadText()).toBeNull();
    expect(screen.getByText("Select any conversation to start")).toBeInTheDocument();
    // The row stays, holding only Home and the empty strip.
    const fanTabsRow = screen.getByRole("region", { name: "Fan tabs" });
    expect(fanTabsRow.childElementCount).toBe(2);
    expect(within(fanTabsRow).getByRole("tablist", { name: "Fan tabs strip" })).toBeEmptyDOMElement();
  });

  /** The fixed Employee's stored Creator tabs (Contracts: Creator tabs storage). */
  const CREATOR_TABS_KEY = "chatterly:creator-tabs:v1:300000001";
  /** The Window header's Creator tabs, in strip order. */
  const creatorTabs = () => within(screen.getByRole("region", { name: "Window header" })).queryAllByRole("tab");

  it("?account=<id> opens on that Creator: its tab is active and the Fan List shows its rows, while the saved scope stays", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderPage(`/messages-pro?window=1&account=${OTHER_ACCOUNT_ID}`);

    expect(await screen.findByRole("heading", { level: 2, name: "Other Creator" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan Three", "Fixture Fan Four"]));
    expect(await creatorTab(/^Other Creator/)).toHaveAttribute("aria-selected", "true");
    expect(await creatorTab(/^Test Creator/)).toHaveAttribute("aria-selected", "false");
    // Not saved: the Employee's other windows keep their scope.
    expect(window.localStorage.getItem("chatterly:scope")).toBe(`model:${ACCOUNT_ID}`);

    // Applied once: a switch made after landing stands, and is saved as in-app.
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
    /** The window at `url`, once its Creators and Fan List have loaded. */
    async function windowAt(url: string) {
      window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
      window.localStorage.setItem(CREATOR_TABS_KEY, stored);
      const rendered = renderPage(url);
      await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
      const testTab = await creatorTab(/^Test Creator 2 unread$/);
      expect(testTab).toHaveAttribute("aria-selected", "true");
      const seen = {
        heading: screen.getByRole("heading", { level: 2 }).textContent,
        // Only the Test Creator's: the other's stays closed.
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

  /* ── Online Fans (ticket 78) ─────────────────────────────────────────── */

  const onlineFans = () => screen.getByRole("button", { name: "Online Fans" });

  it("\"Online Fans\" sits between the Fan List header and its filters, sets aria-pressed and narrows the list to online Fans; pressing it again restores every row", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    PRESENCE.online.add(FANS[0].id); // the row says online
    PRESENCE.lastSeen.set(FANS[2].id, ago(1)); // seen a minute ago
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
    // The clock stands still, so "4m59s ago" stays 4m59s ago however long the
    // render takes; it stops at the real time, so the fixture rows' message
    // times stay in the past.
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

  /* ── Online Fans: the Creator's online list (ticket 79) ──────────────── */

  const ONLINE_LIST = "/api/of/v2/subscribers?";
  const onlineListReads = () => relayGet.mock.calls.filter(([path]) => path.includes(ONLINE_LIST));

  it("\"Online Fans\" keeps a Fan on the Creator's online list even though its row does not say online", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    // No row says online and no Fan has a lastSeen: only the list names Fan Two.
    routeRelay(ONLINE_LIST, (_path, ctx) =>
      ({ list: ctx?.accountId === ACCOUNT_ID ? [fanUser(FANS[1])] : [], hasMore: false }));
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    expect(onlineListReads()).toEqual([]);
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan Two"]));

    // One read, for the scoped Creator: active, online, one page of 50.
    expect(onlineListReads()).toHaveLength(1);
    const [path, ctx] = onlineListReads()[0];
    expect(Object.fromEntries(new URLSearchParams(path.split("?")[1]))).toEqual({ type: "active", online: "1", limit: "50" });
    expect(ctx?.accountId).toBe(ACCOUNT_ID);
    expect(tooltipOf(onlineFans())).toBeNull();
  });

  it("\"Online Fans\" falls back to the row rule when the online list fails, with the tooltip \"Online list unavailable\"; under All Models the list is not read", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    PRESENCE.online.add(FANS[0].id); // the row says online
    routeRelay(ONLINE_LIST, () => Promise.reject(new Error("HTTP 502")));
    const scoped = renderPage("/messages-pro");

    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One", "Fixture Fan Two", "Fixture Fan Three"]));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(tooltipOf(onlineFans())).toBe("Online list unavailable"));
    expect(listedFans()).toEqual(["Fixture Fan One"]);
    expect(onlineListReads()).toHaveLength(1);
    scoped.unmount();

    // All Models: the row rule alone, and no read.
    relayGet.mockClear();
    window.localStorage.setItem("chatterly:scope", "all");
    renderPage("/messages-pro");
    expect(await screen.findByRole("heading", { level: 2, name: "All Models" })).toBeInTheDocument();
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Four"));
    await userEvent.click(onlineFans());
    await vi.waitFor(() => expect(listedFans()).toEqual(["Fixture Fan One"]));
    expect(onlineListReads()).toEqual([]);
    expect(tooltipOf(onlineFans())).toBeNull();
  });

  /* ── Notifications (ticket 80) ───────────────────────────────────────── */

  const NOTIF_COUNT = "/api/of/v2/users/notifications/count";
  const countReads = () => relayGet.mock.calls.filter(([path]) => path.includes(NOTIF_COUNT));
  /** The count reads for one Creator. The Notifications button and that
   *  Creator's tab share one cache entry, so one read serves both. */
  const countReadsFor = (accountId: string) => countReads().filter(([, ctx]) => ctx?.accountId === accountId);
  /** The Fan List's Notifications button; its name ends with the badge's
   *  number while the badge shows. */
  const notifications = () => screen.getByRole("button", { name: /^Notifications\b/ });
  /** Each Creator's OnlyFans notification count, `all` first. */
  const serveCounts = (all: Record<string, number>) =>
    routeRelay(NOTIF_COUNT, (_path, ctx) => ({ all: all[ctx?.accountId ?? ""] ?? 0, subscribed: 1, purchases: 0, tip: 0 }));

  it("\"Notifications\" sits beside Online Fans, and its badge shows `all` from the count route for the scoped Creator, following a scope change; each Creator tab shows its own count in teal (page-parity 07 SH6)", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    serveCounts({ [ACCOUNT_ID]: 7, [OTHER_ACCOUNT_ID]: 120 });
    renderPage("/messages-pro");

    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 7"));
    expectDomOrder([onlineFans(), notifications(), screen.getByRole("group", { name: "Inbox, settings and sort" })]);
    // One read per Creator: the button and the tabs share it.
    expect(countReadsFor(ACCOUNT_ID)).toHaveLength(1);
    // The Creator tab badges, "7" and "99+" (capped), on the teal.
    const tabCounts = () => within(screen.getByRole("tablist", { name: "Creator tabs" }))
      .queryAllByText("notifications").map((sr) => sr.parentElement!);
    await vi.waitFor(() => expect(tabCounts().map((b) => b.textContent)).toEqual(["7 notifications", "99+ notifications"]));
    for (const b of tabCounts()) expect(b).toHaveClass("bg-[var(--inf-online,var(--color-ok))]");

    await userEvent.click(screen.getByRole("button", { name: "Scope to Other Creator" }));
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 120"));
    expect(countReadsFor(OTHER_ACCOUNT_ID)).toHaveLength(1);
  });

  it("\"Notifications\" hides its badge at zero, on a failed read and under All Models, where the count is not read", async () => {
    // One route whose reply each window below swaps.
    let reply: () => unknown = () => ({ all: 0, subscribed: 0, purchases: 0, tip: 0 });
    routeRelay(NOTIF_COUNT, () => reply());
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    const zero = renderPage("/messages-pro");
    await vi.waitFor(() => expect(countReadsFor(ACCOUNT_ID)).toHaveLength(1));
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan One"));
    expect(notifications()).toHaveAccessibleName("Notifications");
    zero.unmount();

    // A re-read that fails after a good one: the old count is not kept.
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
    // The Creator tabs read their own counts; the button shows none of them.
    await vi.waitFor(() => expect(within(screen.getByRole("tablist", { name: "Creator tabs" })).getAllByText("notifications").length).toBeGreaterThan(0));
    expect(notifications()).toHaveAccessibleName("Notifications");
  });

  it("clicking \"Notifications\" opens the bell's panel and filters for the scoped Creator; closing it reads the count again", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    serveCounts({ [ACCOUNT_ID]: 3 });
    routeRelay("/api/of/v2/users/notifications?", (_path, ctx) => ctx?.accountId === ACCOUNT_ID
      ? [{ id: 900000001, type: "subscribed", text: "subscribed to your profile", createdAt: ago(3), user: fanUser(FANS[1]) }]
      : []);
    renderPage("/messages-pro");
    await vi.waitFor(() => expect(notifications()).toHaveAccessibleName("Notifications 3"));
    expect(screen.queryByText("subscribed to your profile")).toBeNull();

    await userEvent.click(notifications());
    expect(await screen.findByText("subscribed to your profile")).toBeInTheDocument();
    // The bell's own filters ("All" is the Fan List's chip too) and its settings.
    for (const name of ["Subscriptions", "Purchases", "Tips", "Comments", "Likes", "Toast settings"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    const listReads = relayGet.mock.calls.filter(([path]) => path.includes("/api/of/v2/users/notifications?"));
    expect(listReads.map(([, ctx]) => ctx?.accountId)).toEqual([ACCOUNT_ID]);

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText("subscribed to your profile")).toBeNull();
    await vi.waitFor(() => expect(countReadsFor(ACCOUNT_ID)).toHaveLength(2));
  });

  /* ── The Buys & tips switch (TODO.md B1) ─────────────────────────────── */

  /** The "Notif" switch that ends the Fan List header. */
  const railSwitch = () => screen.getByRole("switch", { name: "Buys & tips" });
  /** The Buys & tips rail's header toggle: present while the rail is. */
  const railShown = () => screen.queryByRole("button", { name: /Buys & tips/ }) !== null;
  /** The rail's stored settings' surfaces. */
  const storedSurfaces = () => JSON.parse(window.localStorage.getItem(RAIL_SETTINGS_KEY) ?? "null")?.surfaces;
  /** The page at /messages-pro (the rail's "inbox" surface) with the rail, as the root layout mounts it. */
  const renderWithRail = () => {
    nav.pathname = "/messages-pro";
    return renderWithProviders(<>{pageTree("/messages-pro")}<MoneyRail /></>);
  };

  it("a \"Notif\" (Buys & tips) switch ends the Fan List header, after \"+\", on with the rail shown; off hides the rail on this page, on brings it back, and Notifications still opens its panel", async () => {
    window.localStorage.setItem("chatterly:scope", `model:${ACCOUNT_ID}`);
    renderWithRail();
    await vi.waitFor(() => expect(railSwitch()).toBeEnabled());

    const header = within(screen.getByRole("group", { name: "Fan List header" }));
    expect(header.getByRole("switch", { name: "Buys & tips" })).toHaveTextContent("Notif");
    expectDomOrder([header.getByRole("button", { name: "New" }), railSwitch(), onlineFans()]);
    expect(railSwitch()).toHaveAttribute("aria-checked", "true");
    expect(tooltipOf(railSwitch())).toBe("Buys & tips notifications panel shown: click to hide it on this page");
    await vi.waitFor(() => expect(railShown()).toBe(true));

    await userEvent.click(railSwitch());
    expect(railSwitch()).toHaveAttribute("aria-checked", "false");
    expect(tooltipOf(railSwitch())).toBe("Buys & tips notifications panel hidden: click to show it on this page");
    await vi.waitFor(() => expect(railShown()).toBe(false));
    // Hidden on this surface only: the pop-out and group tab keep it.
    expect(storedSurfaces()).toEqual(["popup", "group"]);

    await userEvent.click(notifications());
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Toast settings" })).toBeInTheDocument());

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

    // Another tab (or the rail's ⚙ there) shows it everywhere.
    window.localStorage.setItem(RAIL_SETTINGS_KEY, JSON.stringify({ ...JSON.parse(window.localStorage.getItem(RAIL_SETTINGS_KEY)!), surfaces: null }));
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: RAIL_SETTINGS_KEY })); });
    expect(railSwitch()).toHaveAttribute("aria-checked", "true");
    await vi.waitFor(() => expect(railShown()).toBe(true));
  });

  /* ── A notification opens a Fan tab (ticket 81) ──────────────────────── */

  /** The fixed Employee's stored Fan tabs (Contracts: Fan tabs storage). */
  const FAN_TABS_KEY = "chatterly:fan-tabs:v1:300000001";
  /** The scoped Creator's notifications: one about Fan Two. */
  const serveNotificationAboutFanTwo = () => routeRelay("/api/of/v2/users/notifications?", (_path, ctx) =>
    ctx?.accountId === ACCOUNT_ID
      ? [{ id: 900000002, type: "tip", text: "sent you a tip", createdAt: ago(2), user: fanUser(FANS[1]) }]
      : []);
  /** The open panel's row about Fan Two. */
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

    // Another Fan, then the same notification: its tab is reused, not doubled.
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

    // A money toast (a tip, a purchase) refreshes the Fan's Thread in place too.
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
    // The panel's row names the Fan too: the Fan List's is the other one.
    const listRow = rowsOf(FANS[1]).filter((el) => el !== notificationButton);
    expect(listRow).toHaveLength(1);
    expect(listRow[0]).toHaveAttribute("aria-current", "true");
    expect(fanTabNames()).toHaveLength(100);
    expect(fanTabNames()).not.toContain("Fixture Fan Two");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    // In the panel, which stays open beside the row.
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
    // Arriving from another window with ?fanTab.
    expect(await screen.findByText("Fan tab limit reached (100)")).toHaveAttribute("role", "status");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    first.unmount();

    renderPage("/messages-pro");
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Two"));
    expect(screen.queryByText("Fan tab limit reached (100)")).toBeNull();
    // A toast here (another window's click lands the same way, through its handle).
    act(() => openNotification(`/messages-pro/${ACCOUNT_ID}/200000002?fanTab=Fixture+Fan+Two`));
    expect(threadText()).toBe(`Creator ${ACCOUNT_ID}, Fan 200000002`);
    expect(fanTabNames()).not.toContain("Fixture Fan Two");
    expect(window.localStorage.getItem(FAN_TABS_KEY)).toBe(seed);
    expect(screen.getByText("Fan tab limit reached (100)")).toHaveAttribute("role", "status");
  });

  /* ── A message notification's quick reply (ticket 83) ────────────────── */

  /** The other Creator's notifications under All Models: a message from Fan
   *  Four. The first Creator has none, so the reply's account can only be the
   *  notification's Creator. */
  const serveMessageFromFanFour = () => routeRelay("/api/of/v2/users/notifications?", (_path, ctx) =>
    ctx?.accountId === OTHER_ACCOUNT_ID
      ? [{ id: 900000003, type: "message", text: "sent you a message", createdAt: ago(1), user: fanUser(FAN_FOUR) }]
      : []);
  const THREAD_OF_FAN_FOUR = `/api/of/v2/chats/${FAN_FOUR.id}/messages`;
  /** Opens the panel and the Reply field of the message notification. */
  async function openReply() {
    // A case's send reply is its own: the harness clears calls, not replies.
    onTestFinished(() => { relayPost.mockReset(); });
    window.localStorage.setItem("chatterly:scope", "all");
    serveMessageFromFanFour();
    const { queryClient } = renderPage("/messages-pro");
    // A closed field leaves the Fan's messages cached, as the app's week-long
    // gcTime does (components/providers.tsx); the test client's is shorter.
    queryClient.setQueryDefaults(["messages"], { gcTime: Infinity });
    await vi.waitFor(() => expect(listedFans()).toContain("Fixture Fan Four"));
    await userEvent.click(notifications());
    await screen.findByText("sent you a message");
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    /** Fan Four's message cache under the other Creator, as the Thread reads it. */
    const fanFourMessages = () =>
      queryClient.getQueryData<OFMessage[]>(["messages", OTHER_ACCOUNT_ID, FAN_FOUR.id]) ?? [];
    return { field: screen.getByRole("textbox", { name: "Reply to Fixture Fan Four" }), fanFourMessages };
  }

  it("a message notification's Reply posts the text to the Fan's chat messages route as the notification's Creator, then clears and reads \"Sent\"", async () => {
    const { field } = await openReply();
    // Opening the field mounts the Fan's message hook, read as its Creator.
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
    // Text only, with the Creator in X-Account-Id (relay.ts) and the Employee.
    expect(sends[0]).toEqual([
      THREAD_OF_FAN_FOUR,
      { text: "Fixture quick reply", locked_text: false, price: 0, media_files: [] },
      { accountId: OTHER_ACCOUNT_ID, employeeId: 300000001 },
    ]);
    // A reply opens no Thread and adds no Fan tab.
    expect(threadText()).toBeNull();
    expect(fanTabNames()).toEqual([]);

    // Reply again closes the field, and with it the Fan's message hook.
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    expect(screen.queryByRole("textbox", { name: "Reply to Fixture Fan Four" })).toBeNull();
  });

  it("a rejected Reply keeps the text and shows the error, with no \"Sent\", and leaves no failed bubble in the Fan's messages", async () => {
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
    // The field is the one place to retry: the Thread's Retry belongs to
    // another instance of the send hook, which never saw this send.
    expect(fanFourMessages().filter((m) => m._failed || m.text === "Fixture quick reply")).toEqual([]);
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
    // A new field is a new instance of the send hook over the same cache.
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

  /* ── A Fan tab closed in another window, at every width (ticket 128) ── */

  /** The stored Fan tab of `f`, the scoped Creator's (Contracts). */
  const storedTab = (f: (typeof FANS)[number]) => ({ accountId: ACCOUNT_ID, fanId: String(f.id), name: f.name });
  /** Another window writes this Employee's Fan tabs: a `storage` event here. */
  const otherWindowWritesFanTabs = (tabs: ReturnType<typeof storedTab>[]) =>
    act(() => {
      window.localStorage.setItem(FAN_TABS_KEY, JSON.stringify(tabs));
      window.dispatchEvent(new StorageEvent("storage", { key: FAN_TABS_KEY, newValue: JSON.stringify(tabs) }));
    });

  /** A window `width` px wide with Fans One, Two and Three in Fan tabs and
   *  Fan One open in the Thread from its Fan List row. */
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
    // The last remaining tab, not the next one.
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

/* ── the page through the app shell (look-and-feel ticket 135) ──────────── */

describe("the Messages Pro page through the app shell", () => {
  /** The page at `url` inside `AppShell`, as the app's layout renders it. */
  function renderInShell(url: string) {
    nav.pathname = url.split("?")[0];
    return renderWithProviders(pageTree(url, true));
  }

  // Messages Pro is a window of its own (ADR-0002): the app's chrome is never
  // around it, at any width, on the index or a Deep link, with or without
  // the old `?window=1`.
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
