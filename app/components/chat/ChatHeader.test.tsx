/**
 * ChatHeader — the Chat header Region of the Thread.
 *
 * Seam 1 of docs/spec/phase-03-chat-header-message-list.md (Testing
 * Decisions). Ticket 84 moved the header row out of ChatSurface unchanged;
 * these cases pin the callbacks the Thread hands it, so each later Chat header
 * ticket (85 to 96) can change one part of the row against a test.
 *
 * The relay client is mocked at its module boundary, as
 * `MoneyRail.render.test.tsx` mocks it, the session contexts are stubbed as
 * `windowed.test.tsx` stubs them. Fixture identifiers are invented. The Avatar menu's cases
 * and the verified badge's are in `ChatHeader.avatarMenu.test.tsx`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayGet, relayPost, relayDelete } = vi.hoisted(() => ({
  relayGet: vi.fn(), relayPost: vi.fn(), relayDelete: vi.fn(),
}));

vi.mock("@/lib/relay", async (importOriginal) => ({
  // The real `describeLoadError`, which the Chat gallery's error state reads.
  describeLoadError: (await importOriginal<typeof import("@/lib/relay")>()).describeLoadError,
  relay: {
    get: (...args: unknown[]) => relayGet(...args),
    post: (...args: unknown[]) => relayPost(...args),
    delete: (...args: unknown[]) => relayDelete(...args),
  },
  proxyImage: () => "",
}));

/** Function permissions the role denies (`useActionAllowed`); none unless a case adds one. */
const denied = vi.hoisted(() => new Set<string>());
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: (action: string) => !denied.has(action) }));

// An owner signed in, no chatter, no employee (as windowed.test.tsx stubs them).
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

import type { ComponentProps } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { OFChatItem } from "@/lib/relay";
import { applyTypingEvent } from "@/lib/fanTyping";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { MP } from "@/lib/messagesPro";
import { ChatHeader } from "./ChatHeader";

const ACCOUNT_ID = "100000001";
const FAN_ID = 200000001;
const AUTOMATION_RESTRICT = `/api/of/v2/automation-restrict/${FAN_ID}`;
const CHAT = {
  withUser: {
    id: FAN_ID, name: "Fixture Fan One", username: "fixturefanone",
    avatar: null, customNickname: null, displayName: null,
  },
  hasUnread: false, unreadMessagesCount: 0, isOnline: false,
  canSendMessage: true, canNotSendReason: null, isMutedNotifications: false,
} as unknown as OFChatItem;

type Props = ComponentProps<typeof ChatHeader>;

function renderHeader(over: Partial<Props> = {}, client?: QueryClient) {
  const props: Props = {
    accountId: ACCOUNT_ID,
    fanId: FAN_ID,
    chat: CHAT,
    name: "Fixture Fan One",
    username: "fixturefanone",
    findOpen: false,
    onToggleFind: vi.fn(),
    refreshing: false,
    onRefresh: vi.fn(),
    onOpenNotes: vi.fn(),
    onEditName: vi.fn(),
    insightsOpen: false,
    onToggleInsights: vi.fn(),
    extras: { focusMode: false, onToggleFocus: vi.fn() },
    ...over,
  };
  const utils = renderWithProviders(<ChatHeader {...props} />, client);
  const rerender = (next: Partial<Props>) => utils.rerender(<ChatHeader {...props} {...next} />);
  return { props, rerender };
}

/** The relay serves `routes` by exact path, `{}` elsewhere. */
const serve = (routes: Record<string, unknown> = {}) =>
  relayGet.mockImplementation(async (path: string) => {
    if (path === "/admin/accounts") return { accounts: [] };
    return path in routes ? routes[path] : {};
  });

/** Opens the Kebab menu and returns it, found through its "Hide chats" row. */
async function openKebab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "More actions" }));
  return (await screen.findByRole("button", { name: /Hide chats$/ })).parentElement!;
}

/** The Kebab row that opens the Chat header Extras overflow (ticket 140). */
const extrasRow = () => screen.getByRole("button", { name: "Inflowwww extras" });
/** The Extras overflow, the box that row names, or null while it is closed. */
const submenu = () => {
  const id = screen.queryByRole("button", { name: "Inflowwww extras" })?.getAttribute("aria-controls");
  return id ? document.getElementById(id) : null;
};
/** Opens the overflow through the Kebab menu's last row and returns it. */
async function openExtras(user: ReturnType<typeof userEvent.setup>) {
  await openKebab(user);
  await user.click(extrasRow());
  return submenu()!;
}

// Restrict and Block ask first; declined unless a case accepts.
let confirm: MockInstance<typeof window.confirm>;
beforeEach(() => {
  relayPost.mockReset().mockResolvedValue({});
  relayDelete.mockReset().mockResolvedValue({});
  relayGet.mockReset();
  serve();
  confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
});

const windowListeners: Array<(e: KeyboardEvent) => void> = [];
afterEach(() => {
  cleanup();
  denied.clear();
  vi.unstubAllGlobals();
  confirm.mockRestore();
  for (const fn of windowListeners.splice(0)) window.removeEventListener("keydown", fn);
});

describe("ChatHeader", () => {
  it("find, refresh and the Fan insights toggle call their callbacks; the toggle's aria-expanded follows insightsOpen", async () => {
    const user = userEvent.setup();
    const { props, rerender } = renderHeader();

    await user.click(screen.getByRole("button", { name: "Find" }));
    expect(props.onToggleFind).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(props.onRefresh).toHaveBeenCalledTimes(1);

    const toggle = screen.getByRole("button", { name: "Fan insights" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(props.onToggleInsights).toHaveBeenCalledTimes(1);

    rerender({ insightsOpen: true });
    expect(screen.getByRole("button", { name: "Fan insights" }))
      .toHaveAttribute("aria-expanded", "true");
  });

  it("the back control calls onBack, and the Fan insights toggle renders with or without onBack", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    renderHeader({ onBack });

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    // Infloww's "←" shows at every width (page-parity 07 CH6), so lg+ clears the open Fan too.
    expect(screen.getByRole("button", { name: "Back" })).not.toHaveClass("lg:hidden");
    expect(screen.getByRole("button", { name: "Back" }).querySelector("svg")).toHaveClass("lucide-arrow-left");
    expect(screen.getByRole("button", { name: "Fan insights" })).toBeInTheDocument();

    cleanup();
    renderHeader();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fan insights" })).toBeInTheDocument();
  });

  describe("right group (ticket 90)", () => {
    it('with 100 Fan tabs stored, "Open in new tab" is disabled with "Fan tab limit reached (100)"', async () => {
      // Seeded as FanTabs.test.tsx seeds the cap, under this owner's Employee key
      // (no Employee picked, so the signed-in user's id).
      const KEY = "chatterly:fan-tabs:v1:u-owner";
      window.localStorage.setItem(KEY, JSON.stringify(Array.from({ length: 100 }, (_, i) => (
        { accountId: ACCOUNT_ID, fanId: String(600 + i), name: `Fixture Fan ${600 + i}` }))));
      try {
        renderHeader();
        const button = screen.getByRole("button", { name: "Open in new tab" });
        await waitFor(() => expect(button).toBeDisabled());
        expect(button).toHaveAttribute("title", "Fan tab limit reached (100)");
      } finally {
        window.localStorage.removeItem(KEY);
      }
    });
  });

  describe("Kebab menu: message statistics and \"Inflowwww extras ▸\" (tickets 91, 140)", () => {
    it('the Kebab menu holds 📈\'s rows: "Mass message statistics" opens /growth/smart-messages?tab=mass in a new tab, and "Online fans message statistics" is Not wired and calls nothing', async () => {
      const user = userEvent.setup();
      renderHeader();
      const menu = within(await openKebab(user));
      const mass = menu.getByRole("link", { name: "Mass message statistics" });
      expect(mass).toHaveAttribute("href", "/growth/smart-messages?tab=mass");
      expect(mass).toHaveAttribute("target", "_blank");
      expect(mass).toHaveAttribute("rel", "noopener noreferrer");
      const online = menu.getByRole("button", { name: "Online fans message statistics" });
      expect(online).toHaveAttribute("aria-disabled", "true");
      expect(online).toHaveAttribute("title", "not wired");
      const gets = relayGet.mock.calls.length;
      await user.click(online);
      expect(relayGet).toHaveBeenCalledTimes(gets);
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();
    });

    it('"Inflowwww extras ▸" toggles the overflow beside the Kebab box; one Escape closes one layer, the submenu then the Kebab menu, and Find never hears it; a pointer-down in the submenu keeps both; one outside closes both', async () => {
      const user = userEvent.setup();
      // With Find open, an Escape closes a menu layer only: Find's panel
      // (ChatSearch) closes on a `window` Escape, stood in for here.
      const { props } = renderHeader({ findOpen: true });
      const findEscape = vi.fn();
      const onWindowKey = (e: KeyboardEvent) => { if (e.key === "Escape") findEscape(); };
      window.addEventListener("keydown", onWindowKey);
      windowListeners.push(onWindowKey);
      const kebabOpen = () => screen.queryByRole("button", { name: /Hide chats$/ }) !== null;

      const kebab = await openKebab(user);
      expect(extrasRow()).toHaveTextContent("Inflowwww extras ▸");
      expect(submenu()).toBeNull();
      await user.click(extrasRow());
      expect(extrasRow()).toHaveAttribute("aria-expanded", "true");
      expect(submenu()).toBeInTheDocument();
      expect(kebab).not.toContainElement(submenu());
      await user.click(extrasRow());
      expect(extrasRow()).toHaveAttribute("aria-expanded", "false");
      expect(submenu()).toBeNull();
      await user.click(extrasRow());
      await user.keyboard("{Escape}");
      expect(submenu()).toBeNull();
      expect(kebabOpen()).toBe(true);
      expect(extrasRow()).toHaveAttribute("aria-expanded", "false");
      await user.keyboard("{Escape}");
      expect(kebabOpen()).toBe(false);
      expect(findEscape).not.toHaveBeenCalled();
      expect(props.onToggleFind).not.toHaveBeenCalled();

      await user.pointer({ keys: "[MouseLeft]", target: await openExtras(user) });
      expect(submenu()).toBeInTheDocument();
      expect(kebabOpen()).toBe(true);
      await user.click(document.body);
      expect(submenu()).toBeNull();
      expect(kebabOpen()).toBe(false);
    });

    it("in focus mode on a phone the kebab stays visible, and the overflow's focus row turns focus off", async () => {
      const user = userEvent.setup();
      const onToggleFocus = vi.fn();
      renderHeader({ extras: { focusMode: true, onToggleFocus } });
      // Focus mode hides the icon row below lg (`hidden lg:flex`), never the kebab.
      expect(screen.getByRole("button", { name: "Find" }).parentElement).toHaveClass("hidden", "lg:flex");
      for (let el: HTMLElement | null = screen.getByRole("button", { name: "More actions" }); el && el.tagName !== "HEADER"; el = el.parentElement) {
        expect(el.className).not.toMatch(/(^|\s)hidden(\s|$)/);
      }
      const focus = within(await openExtras(user)).getByRole("button", { name: "Focus mode ON" });
      expect(focus).toHaveAttribute("aria-pressed", "true");
      await user.click(focus);
      expect(onToggleFocus).toHaveBeenCalledTimes(1);
    });
  });

  describe("Extras overflow (ticket 92)", () => {
    // Two queued sends to this Fan, seeded where the Scheduled row reads them.
    const SCHEDULED = [1, 2].map((id) => ({
      id, text: `Fixture queued send ${id}`, scheduledDate: "2026-11-01T10:00:00Z", price: 0, lockedText: false,
      mediaCount: 0, media: [], userIds: [FAN_ID], userLists: [], groups: [], __accountId: ACCOUNT_ID,
    }));
    const ROW = { ...CHAT, __accountId: ACCOUNT_ID } as unknown as OFChatItem;
    const seeded = () => {
      const client = makeTestQueryClient();
      // The house client collects unobserved data at once; these seeds must outlive the render.
      client.setDefaultOptions({ queries: { retry: false, gcTime: Infinity, staleTime: 0 } });
      client.setQueryData(["scheduled", ACCOUNT_ID], SCHEDULED);
      client.setQueryData(["chats", "fixture"], { pages: [{ rows: [ROW], hasMore: false }], pageParams: [null] });
      return client;
    };
    const EXTRA_ROWS = ["Scheduled 2", "Group chat", "Mark as unread", "Add to MASSdmEXCLUDE", "Focus mode"];

    it('the Kebab row is titled "Inflowwww extras"; the overflow\'s rows carry "Inflowwww extra" and hold no Persona, translate or "Restrict from automations" row', async () => {
      const user = userEvent.setup();
      renderHeader({}, seeded());
      const menu = within(await openExtras(user));
      expect(extrasRow()).toHaveAttribute("title", "Inflowwww extras");
      const rows = EXTRA_ROWS.map((name) => menu.getByRole("button", { name }));
      rows.slice(1).forEach((el, i) => {
        expect(rows[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      });
      expect(menu.getAllByRole("button")).toHaveLength(EXTRA_ROWS.length);
      expect(rows.map((row) => row.getAttribute("title"))).toEqual([
        "Inflowwww extra — Scheduled chip\n2 scheduled for this fan — click to view/cancel",
        "Inflowwww extra — Group chat\nAdd to group chat tab",
        "Inflowwww extra — Mark as unread",
        "Inflowwww extra — Mass exclude",
        "Inflowwww extra — Phone focus\nFocus mode — hide the AI status strip and header tools to give the conversation the full screen",
      ]);
      // Focus is the phone reading mode: below lg only.
      expect(menu.getByRole("button", { name: "Focus mode" })).toHaveClass("lg:hidden");
      expect(menu.queryByText(/translate|🌐/i)).toBeNull();
      expect(menu.queryByText(/automations|Auto-restricted|Persona/)).toBeNull();
    });

    it('with nothing seeded, the five rows show at once: "Scheduled …" while the queue loads, then "Scheduled 0", disabled, and no row moves', async () => {
      // The queue answers only when the case says so, so the loading row can be read.
      let answer: (v: { list: [] }) => void = () => {};
      const queue = new Promise<{ list: [] }>((resolve) => { answer = resolve; });
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (path.startsWith("/api/of/v2/schedules?")) return queue;
        return {};
      });
      const user = userEvent.setup();
      renderHeader();
      const menu = within(await openExtras(user));
      const order = (first: string) => [first, ...EXTRA_ROWS.slice(1)];
      const expectRows = (names: string[]) => {
        const rows = menu.getAllByRole("button");
        expect(rows).toHaveLength(5);
        names.forEach((name, i) => expect(rows[i]).toBe(menu.getByRole("button", { name })));
        return rows;
      };
      const loading = expectRows(order("Scheduled …"));
      expect(loading[0]).toBeDisabled();
      answer({ list: [] });
      await waitFor(() => expect(menu.getByRole("button", { name: "Scheduled 0" })).toBeInTheDocument());
      const loaded = expectRows(order("Scheduled 0"));
      expect(loaded[0]).toBeDisabled();
      expect(loaded.slice(1)).toEqual(loading.slice(1));

      // A failed queue request is not "nothing queued": it reads "—", disabled,
      // with the relay's error in its tooltip.
      cleanup();
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (path.startsWith("/api/of/v2/schedules?")) throw new Error("upstream 502: fixture queue down");
        return {};
      });
      renderHeader();
      const failed = await within(await openExtras(user)).findByRole("button", { name: "Scheduled —" });
      expect(failed).toBeDisabled();
      expect(failed).toHaveAttribute("title", "Inflowwww extra — Scheduled chip\nupstream 502: fixture queue down");
      expect(within(submenu()!).queryByRole("button", { name: "Scheduled 0" })).toBeNull();
      expect(within(submenu()!).getAllByRole("button")).toHaveLength(5);
    });

    it("the header row has no 🌐 translate, Scheduled chip or 👥 group, the Kebab menu no longer lists Mark as unread or the MASS toggle, and Mark as unread in the overflow makes its existing call and cache refresh", async () => {
      const user = userEvent.setup();
      const client = seeded();
      renderHeader({}, client);
      expect(screen.queryByText(/translate|🌐/i)).toBeNull();
      expect(screen.queryByText(/🕐|Scheduled/)).toBeNull();
      expect(screen.queryByText(/👥|group/i)).toBeNull();

      await openKebab(user);
      expect(screen.queryByRole("button", { name: /Mark as unread|MASSppvEXCLUDE|MASSdmEXCLUDE/ })).toBeNull();
      // The overflow opens from the Kebab menu's last row.
      await user.click(extrasRow());
      await user.click(within(submenu()!).getByRole("button", { name: "Mark as unread" }));
      await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(
        `/api/of/v2/chats/${FAN_ID}/mark-as-read`, { accountId: ACCOUNT_ID }));
      expect(await screen.findByText(/Marked unread/)).toBeInTheDocument();
      const chats = client.getQueryData<{ pages: { rows: OFChatItem[] }[] }>(["chats", "fixture"]);
      expect(chats?.pages[0].rows[0]).toMatchObject({ hasUnread: true, unreadMessagesCount: 1 });
    });
  });

  describe("presence line (ticket 85)", () => {
    const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
    const withSeen = (lastSeen: string | null, isOnline = false) => ({
      ...CHAT, isOnline, withUser: { ...CHAT.withUser, lastSeen },
    }) as unknown as OFChatItem;

    it('reads "Available now" when the conversation says the Fan is online', () => {
      renderHeader({ chat: withSeen(null, true) });
      expect(screen.getByText("Available now")).toBeInTheDocument();
    });

    it("draws the words in Infloww's grey, online or not, and the dot green online and grey offline (page-parity 07 CH8)", () => {
      const line = () => screen.getByText(/Available now|Offline/).parentElement!;
      const dot = () => line().querySelector("[aria-hidden]")!;
      renderHeader({ chat: withSeen(null, true) });
      expect(line()).toHaveClass("text-[var(--inf-presence-text,var(--color-fg-dim))]");
      expect(line()).not.toHaveClass("text-ok");
      expect(dot()).toHaveClass("bg-[var(--inf-presence-online,var(--color-ok))]");

      cleanup();
      renderHeader();
      expect(line()).toHaveClass("text-[var(--inf-presence-text,var(--color-fg-dim))]");
      expect(dot()).toHaveClass("bg-[var(--inf-offline,var(--color-fg-dim))]");
    });

    it('reads "Available now" for a Fan last seen 2 minutes ago', () => {
      renderHeader({ chat: withSeen(minutesAgo(2)) });
      expect(screen.getByText("Available now")).toBeInTheDocument();
    });

    it('reads "Last seen 1 h ago" for a Fan last seen an hour ago, from the cached OF user, with no new request', () => {
      const client = makeTestQueryClient();
      client.setQueryData(["of-user", ACCOUNT_ID, FAN_ID], { id: FAN_ID, lastSeen: minutesAgo(60) });
      renderHeader({}, client);
      expect(screen.getByText("Last seen 1 h ago")).toBeInTheDocument();
      expect(screen.queryByText("Available now")).not.toBeInTheDocument();
      expect(relayGet.mock.calls.map((c) => c[0])).not.toContainEqual(expect.stringContaining("/users/"));
    });

    it('reads "is typing…" while the Fan types, then the presence again once the Fan\'s message lands (04 M3)', () => {
      renderHeader();
      act(() => applyTypingEvent({ chat_typing: { fan_id: FAN_ID }, __account_id: ACCOUNT_ID }, "chat_typing"));
      expect(screen.getByText("is typing…")).toBeInTheDocument();
      expect(screen.queryByText("Offline")).not.toBeInTheDocument();
      act(() => applyTypingEvent({ api2_chat_message: { fromUser: { id: FAN_ID } }, __account_id: ACCOUNT_ID }, "api2_chat_message"));
      expect(screen.getByText("Offline")).toBeInTheDocument();
    });

    it('reads "Offline" when no last-seen time is known', () => {
      renderHeader();
      expect(screen.getByText("Offline")).toBeInTheDocument();
      expect(screen.queryByText(/Last seen/)).not.toBeInTheDocument();
      expect(screen.queryByText("Available now")).not.toBeInTheDocument();
    });
  });

  it('the name\'s tooltip reads "@<username> · <Creator>", and no second line shows it', async () => {
    relayGet.mockImplementation(async (path: string) => {
      if (path === "/admin/accounts") return { accounts: [{ id: ACCOUNT_ID, nickname: "Fixture Creator" }] };
      return {};
    });
    renderHeader();
    const name = screen.getByText("Fixture Fan One");
    await waitFor(() => expect(name).toHaveAttribute("title", "@fixturefanone · Fixture Creator"));
    expect(screen.queryByText(/@fixturefanone/)).not.toBeInTheDocument();
  });

  describe("icon row (tickets 86, 87, 88)", () => {
    const MUTE_ROUTE = `/api/of/v2/chats/${FAN_ID}/mute`;
    /** Every button whose accessible name is `label`, alone or after the Kebab row's glyph. */
    const named = (label: string) => screen.queryAllByRole("button", { name: new RegExp(`^\\W*${label}$`, "u") });

    it('line 1 holds back, "Avatar menu", "Edit name", "Open in new tab", "Refresh", "Fan insights" and "More actions", line 2 Priority, mute, Notes, Pinned chat, "Gallery" and "Find", in DOM order, and no Persona, "Inflowwww extras", "Message statistics" or "pop out" button shows (tickets 140, 141, 142)', () => {
      const button = (name: string) => (name === "Avatar menu" ? screen.getByTitle(name) : screen.getByRole("button", { name }));
      renderHeader({ onBack: vi.fn() });
      const lines = [1, 2].map((n) => document.querySelector<HTMLElement>(`[data-chat-header-line="${n}"]`)!);
      const want = [["Back", "Avatar menu", "Edit name", "Open in new tab", "Refresh", "Fan insights", "More actions"],
        ["Priority", "Mute notifications", "Notes", "Pinned chat", "Gallery", "Find"]];
      lines.forEach((line, i) => {
        const got = within(line).getAllByRole("button");
        expect(got).toHaveLength(want[i].length);
        want[i].forEach((name, j) => expect(got[j], name).toBe(button(name)));
      });
      // Line 2's buttons are 24px targets over the "Avatar menu" button (WCAG 2.5.8).
      within(lines[1]).getAllByRole("button").forEach((b) => expect(b).toHaveClass(...MP.chatHeader.lineTarget.split(" ")));
      expect(lines[0].compareDocumentPosition(lines[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.queryAllByRole("button", { name: /^(Persona|Inflowwww extras|Message statistics)$/ })).toHaveLength(0);
      expect(screen.queryByText(/pop out/)).not.toBeInTheDocument();
    });

    it('"Edit name" follows the name, outside the "Avatar menu" button, and calls onEditName once with no relay call and no Avatar menu (ticket 142)', async () => {
      const user = userEvent.setup();
      const { props } = renderHeader();
      const gets = relayGet.mock.calls.length;
      const pencil = screen.getByRole("button", { name: "Edit name" });
      expect(pencil).toHaveAttribute("title", "Edit name");
      expect(screen.getByTitle("Avatar menu")).not.toContainElement(pencil);
      await user.click(pencil);
      expect(props.onEditName).toHaveBeenCalledTimes(1);
      expect(screen.getByTitle("Avatar menu")).toHaveAttribute("aria-expanded", "false");
      expect(relayGet).toHaveBeenCalledTimes(gets);
      expect(relayPost).not.toHaveBeenCalled();
    });

    it("clicking Notes calls onOpenNotes once and makes no relay call (ticket 87)", async () => {
      const user = userEvent.setup();
      const { props } = renderHeader();
      const gets = relayGet.mock.calls.length;
      await user.click(screen.getByRole("button", { name: "Notes" }));
      expect(props.onOpenNotes).toHaveBeenCalledTimes(1);
      expect(props.onToggleInsights).not.toHaveBeenCalled();
      expect(relayGet).toHaveBeenCalledTimes(gets);
      expect(relayPost).not.toHaveBeenCalled();
    });

    it('Gallery opens "Chat gallery": one tile per media item, price tags on the paid ones, both directions and purchased or not (ticket 88)', async () => {
      // Synthetic chat media: a paid PPV with two files, a free item with
      // one, and a file with no URL (the Clone skips it, m.js:2629).
      const file = (n: number) => ({ thumb: { url: `https://cdn.example.test/m${n}.jpg` } });
      const page = {
        list: [
          { id: 11, text: "", price: 15, isFree: false, isOpened: true, isFromQueue: false, mediaCount: 2,
            createdAt: "2026-10-01T10:00:00Z", fromUser: { id: Number(ACCOUNT_ID) },
            media: [{ id: 101, type: "photo", files: file(1) }, { id: 102, type: "photo", files: file(2) }] },
          { id: 12, text: "", price: 0, isFree: true, isOpened: true, isFromQueue: false, mediaCount: 2,
            createdAt: "2026-10-02T10:00:00Z", fromUser: { id: FAN_ID },
            media: [{ id: 103, type: "photo", files: file(3) }, { id: 104, type: "photo", files: {} }] },
        ],
        hasMore: false,
      };
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (path.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`)) return page;
        return {};
      });
      // jsdom has no IntersectionObserver, which MediaTile's lazy path builds.
      vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
      const user = userEvent.setup();
      renderHeader();
      expect(screen.queryByRole("dialog", { name: "Chat gallery" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Gallery" }));
      const sheet = screen.getByRole("dialog", { name: "Chat gallery" });
      await waitFor(() => expect(within(sheet).getAllByRole("listitem")).toHaveLength(3));
      expect(within(sheet).getAllByText("$15.00")).toHaveLength(2);
      // The free item's tile carries no tag.
      expect(within(sheet).getAllByRole("listitem")[2]).toHaveTextContent(/^$/);
      expect(within(sheet).queryByText("$0.00")).not.toBeInTheDocument();

      const media = relayGet.mock.calls.map((c) => String(c[0])).filter((p) => p.includes("/media?"));
      expect(media).toHaveLength(1);
      const qs = new URLSearchParams(media[0].split("?")[1]);
      expect(qs.get("limit")).toBe("30");
      expect(qs.has("from_user")).toBe(false);
      expect(qs.has("purchased")).toBe(false);

      // It closes from its head.
      await user.click(within(sheet).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog", { name: "Chat gallery" })).not.toBeInTheDocument();

      // With Find open, one Escape closes the Gallery only: Find's panel
      // (ChatSearch) closes on a `window` Escape, stood in for here.
      cleanup();
      const { props } = renderHeader({ findOpen: true });
      const findEscape = vi.fn();
      const onWindowKey = (e: KeyboardEvent) => { if (e.key === "Escape") findEscape(); };
      window.addEventListener("keydown", onWindowKey);
      windowListeners.push(onWindowKey);
      await user.click(screen.getByRole("button", { name: "Gallery" }));
      expect(screen.getByRole("dialog", { name: "Chat gallery" })).toBeInTheDocument();
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog", { name: "Chat gallery" })).not.toBeInTheDocument();
      expect(findEscape).not.toHaveBeenCalled();
      expect(props.onToggleFind).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Find" })).toHaveAttribute("aria-expanded", "true");
    });

    // Synthetic Chat gallery pages for ticket 89's cases: one photo per item.
    const galleryItem = (id: number, mediaId: number) => ({
      id, text: "", price: 0, isFree: true, isOpened: true, isFromQueue: false, mediaCount: 1,
      createdAt: "2026-10-01T10:00:00Z", fromUser: { id: FAN_ID },
      media: [{ id: mediaId, type: "photo", files: { thumb: { url: `https://cdn.example.test/g${mediaId}.jpg` } } }],
    });
    const mediaCalls = () =>
      relayGet.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`))
        .map((p) => new URLSearchParams(p.split("?")[1]));
    const openGallery = async (user: ReturnType<typeof userEvent.setup>) => {
      vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
      renderHeader();
      await user.click(screen.getByRole("button", { name: "Gallery" }));
      return screen.getByRole("dialog", { name: "Chat gallery" });
    };

    it('Chat gallery: "Load more" requests the next page by last_id and appends its tiles (ticket 89)', async () => {
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (!path.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`)) return {};
        return new URLSearchParams(path.split("?")[1]).get("last_id") === "21"
          ? { list: [galleryItem(20, 120)], hasMore: false }
          : { list: [galleryItem(22, 122), galleryItem(21, 121)], hasMore: true, nextLastId: "21" };
      });
      const user = userEvent.setup();
      const sheet = await openGallery(user);
      await waitFor(() => expect(within(sheet).getAllByRole("listitem")).toHaveLength(2));
      expect(mediaCalls()).toHaveLength(1);
      expect(mediaCalls()[0].has("last_id")).toBe(false);

      await user.click(within(sheet).getByRole("button", { name: "Load more" }));
      await waitFor(() => expect(within(sheet).getAllByRole("listitem")).toHaveLength(3));
      expect(mediaCalls()).toHaveLength(2);
      expect(mediaCalls()[1].get("last_id")).toBe("21");
      // The relay reports no further page, so "Load more" goes.
      expect(within(sheet).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    });

    it('Chat gallery: a failed "Load more" keeps the loaded tiles and shows the relay\'s error under them (ticket 89)', async () => {
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (!path.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`)) return {};
        if (new URLSearchParams(path.split("?")[1]).has("last_id")) throw new Error("upstream 502: fixture page two down");
        return { list: [galleryItem(42, 142), galleryItem(41, 141)], hasMore: true, nextLastId: "41" };
      });
      const user = userEvent.setup();
      const sheet = await openGallery(user);
      await waitFor(() => expect(within(sheet).getAllByRole("listitem")).toHaveLength(2));

      await user.click(within(sheet).getByRole("button", { name: "Load more" }));
      const alert = await within(sheet).findByRole("alert");
      expect(alert).toHaveTextContent(/upstream 502: fixture page two down/);
      // The tiles that loaded stay, and the notice follows the grid.
      expect(within(sheet).getAllByRole("listitem")).toHaveLength(2);
      expect(within(sheet).getByRole("list").compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      // One "↻ Refresh", in the head.
      expect(within(sheet).getAllByRole("button", { name: "↻ Refresh" })).toHaveLength(1);
    });

    it('Chat gallery: an empty media list reads "No media in this chat" (ticket 89)', async () => {
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (path.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`)) return { list: [], hasMore: false };
        return {};
      });
      const user = userEvent.setup();
      const sheet = await openGallery(user);
      expect(await within(sheet).findByText("No media in this chat")).toBeInTheDocument();
      expect(within(sheet).queryByRole("listitem")).not.toBeInTheDocument();
      expect(within(sheet).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    });

    it('Chat gallery: a failed request shows the relay\'s error and "↻ Refresh", which requests the first page again (ticket 89)', async () => {
      let fail = true;
      relayGet.mockImplementation(async (path: string) => {
        if (path === "/admin/accounts") return { accounts: [] };
        if (!path.startsWith(`/api/of/v2/chats/${FAN_ID}/media?`)) return {};
        if (fail) throw new Error("upstream 502: fixture gateway down");
        return { list: [galleryItem(30, 130)], hasMore: false };
      });
      const user = userEvent.setup();
      const sheet = await openGallery(user);
      expect(await within(sheet).findByText(/upstream 502: fixture gateway down/)).toBeInTheDocument();
      // Nothing pretends to have loaded.
      expect(within(sheet).queryByRole("listitem")).not.toBeInTheDocument();
      expect(within(sheet).queryByText("No media in this chat")).not.toBeInTheDocument();
      expect(mediaCalls()).toHaveLength(1);

      fail = false;
      await user.click(within(sheet).getByRole("button", { name: "↻ Refresh" }));
      await waitFor(() => expect(within(sheet).getAllByRole("listitem")).toHaveLength(1));
      expect(mediaCalls()).toHaveLength(2);
      expect(mediaCalls()[1].has("last_id")).toBe(false);
      expect(within(sheet).queryByText(/upstream 502/)).not.toBeInTheDocument();
    });

    it('star and pin are Not wired: aria-disabled, titled "not wired", and a click calls no relay route', async () => {
      const user = userEvent.setup();
      renderHeader();
      for (const name of ["Priority", "Pinned chat"]) {
        const button = screen.getByRole("button", { name });
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(button).toHaveAttribute("title", "not wired");
        const gets = relayGet.mock.calls.length;
        await user.click(button);
        expect(relayGet).toHaveBeenCalledTimes(gets);
      }
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();
    });

    it("mute: the icon and the Kebab row share one state; a click on either POSTs, the next DELETEs, and both flip", async () => {
      const user = userEvent.setup();
      renderHeader();
      await user.click(screen.getByRole("button", { name: "More actions" }));
      expect(named("Mute notifications")).toHaveLength(2);
      expect(named("Unmute notifications")).toHaveLength(0);

      // Infloww's plain bell while unmuted, struck through once muted (page-parity 07 CH7).
      const glyph = (name: string) => screen.getByRole("button", { name }).querySelector("svg")!;
      expect(glyph("Mute notifications")).toHaveClass("lucide-bell");
      // The icon is named exactly; the Kebab row's name starts with its glyph.
      await user.click(screen.getByRole("button", { name: "Mute notifications" }));
      expect(relayPost).toHaveBeenCalledTimes(1);
      expect(relayPost.mock.calls[0][0]).toBe(MUTE_ROUTE);
      // A click outside the Kebab menu closes it, so it is opened again to read its row.
      await waitFor(() => expect(screen.getByRole("button", { name: "Unmute notifications" })).toBeInTheDocument());
      expect(glyph("Unmute notifications")).toHaveClass("lucide-bell-off");
      await user.click(screen.getByRole("button", { name: "More actions" }));
      expect(named("Unmute notifications")).toHaveLength(2);
      expect(named("Mute notifications")).toHaveLength(0);

      const kebabRow = named("Unmute notifications")
        .find((b) => b !== screen.getByRole("button", { name: "Unmute notifications" }))!;
      await user.click(kebabRow);
      expect(relayDelete).toHaveBeenCalledTimes(1);
      expect(relayDelete.mock.calls[0][0]).toBe(MUTE_ROUTE);
      await waitFor(() => expect(named("Mute notifications")).toHaveLength(2));
      expect(named("Unmute notifications")).toHaveLength(0);
      // The Kebab menu keeps its status line.
      expect(screen.getByText(/Notifications unmuted/)).toBeInTheDocument();
      expect(relayPost).toHaveBeenCalledTimes(1);
    });
  });

  describe("No AI strip (ticket 93)", () => {
    const relayWith = (restrict: { restricted: boolean; reason: string | null }) => serve({ [AUTOMATION_RESTRICT]: restrict });
    const asked = (part: string) => relayGet.mock.calls.some(([path]) => String(path).includes(part));

    it("there is no AI strip and no status request (it went with the legacy selling engine)", () => {
      relayWith({ restricted: false, reason: null });
      renderHeader();
      expect(screen.getByRole("button", { name: "Fan insights" })).toBeInTheDocument();
      expect(screen.queryByRole("note", { name: "AI status" })).toBeNull();
      expect(asked("/ai-status")).toBe(false);
    });

    it('the Kebab menu holds no "Restrict from automations" or "Auto-restricted" row', async () => {
      const user = userEvent.setup();
      relayWith({ restricted: true, reason: "muted_creator" });
      renderHeader();
      const menu = await openKebab(user);
      await waitFor(() => expect(asked(AUTOMATION_RESTRICT)).toBe(true));
      expect(within(menu).queryByText(/automations|Auto-restricted/)).toBeNull();
    });
  });
  describe("Restrict and Block confirm (ticket 94)", () => {
    const RESTRICT = `/api/of/v2/users/${FAN_ID}/restrict`;
    const BLOCK = `/api/of/v2/users/${FAN_ID}/block`;
    /** The OF user the relay serves for this Fan. */
    const relayWith = (ofUser: Record<string, unknown>) => serve({ [`/api/of/v2/users/${FAN_ID}`]: ofUser });

    it("Restrict and Block are the first two rows; Restrict asks first, a declined confirm makes no call, an accepted one POSTs the restrict route with ack=false and the status line drops \"Sent “.”\"; Lift restrict asks, then DELETEs", async () => {
      const user = userEvent.setup();
      relayWith({ id: FAN_ID });
      relayPost.mockResolvedValue({ ok: true, restricted: true, acked: true, hidden: true });
      renderHeader();
      const menu = await openKebab(user);
      const rows = within(menu).getAllByRole("button");
      expect(rows[0]).toHaveAccessibleName(/^\W*Restrict$/);
      expect(rows[1]).toHaveAccessibleName(/Block$/);

      await user.click(rows[0]);
      expect(confirm).toHaveBeenCalledTimes(1);
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();

      confirm.mockReturnValue(true);
      await user.click(rows[0]);
      expect(confirm).toHaveBeenCalledTimes(2);
      await waitFor(() => expect(relayPost).toHaveBeenCalledWith(`${RESTRICT}?ack=false`, undefined, { accountId: ACCOUNT_ID }));
      expect(relayPost).toHaveBeenCalledTimes(1);
      expect(await within(menu).findByText(/restricted on OnlyFans · chat hidden/)).toBeInTheDocument();
      expect(within(menu).queryByText(/Sent/)).toBeNull();

      cleanup();
      relayPost.mockClear();
      relayWith({ id: FAN_ID, isRestricted: true });
      confirm.mockClear().mockReturnValue(false);
      renderHeader();
      const lift = await within(await openKebab(user)).findByRole("button", { name: /^\W*Lift restrict$/ });
      await user.click(lift);
      expect(confirm).toHaveBeenCalledTimes(1);
      expect(relayDelete).not.toHaveBeenCalled();
      confirm.mockReturnValue(true);
      await user.click(lift);
      await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(RESTRICT, { accountId: ACCOUNT_ID }));
      expect(relayPost).not.toHaveBeenCalled();
      expect(await screen.findByText(/OnlyFans restrict lifted/)).toBeInTheDocument();
    });

    it("Block asks first, POSTs the block route and refreshes the Fan's OF user, then reads \"Unblock\", which asks and DELETEs; a declined confirm makes no call; a rejected call shows the relay's error in the menu", async () => {
      const user = userEvent.setup();
      relayWith({ id: FAN_ID });
      renderHeader();
      const menu = await openKebab(user);
      const block = within(menu).getByRole("button", { name: /Block$/ });
      await user.click(block);
      expect(confirm).toHaveBeenCalledTimes(1);
      expect(relayPost).not.toHaveBeenCalled();

      confirm.mockReturnValue(true);
      const userReads = () => relayGet.mock.calls.filter(([path]) => path === `/api/of/v2/users/${FAN_ID}`).length;
      await waitFor(() => expect(userReads()).toBe(1));
      await user.click(block);
      await waitFor(() => expect(relayPost).toHaveBeenCalledWith(BLOCK, undefined, { accountId: ACCOUNT_ID }));
      expect(await within(menu).findByRole("button", { name: /Unblock$/ })).toBeInTheDocument();
      expect(within(menu).queryByRole("button", { name: /\bBlock$/ })).toBeNull();
      expect(within(menu).getByText(/Blocked on OnlyFans/)).toBeInTheDocument();
      // The Fan's OF user is fetched again from the relay.
      await waitFor(() => expect(userReads()).toBe(2));

      // The row still reads "Unblock" when the menu is opened again.
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("button", { name: /Hide chat/ })).toBeNull());
      const again = await openKebab(user);
      expect(within(again).getByRole("button", { name: /Unblock$/ })).toBeInTheDocument();

      relayDelete.mockRejectedValueOnce(new Error("upstream 502: fixture unblock down"));
      await user.click(within(again).getByRole("button", { name: /Unblock$/ }));
      await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(BLOCK, { accountId: ACCOUNT_ID }));
      expect(await within(again).findByText(/upstream 502: fixture unblock down/)).toBeInTheDocument();
      expect(within(again).getByRole("button", { name: /Unblock$/ })).toBeInTheDocument();
      expect(confirm).toHaveBeenCalledTimes(3);
      expect(relayPost).toHaveBeenCalledTimes(1);
    });
  });

  describe("Kebab rows and Copy chat link (ticket 96)", () => {
    const HIDE = `/api/of/v2/chats/${FAN_ID}/hide`;
    beforeEach(() => { serve({ [AUTOMATION_RESTRICT]: { restricted: false, reason: null } }); });
    // Spied after `userEvent.setup()`, which installs its own clipboard.
    let writeText: MockInstance<Clipboard["writeText"]> | undefined;
    afterEach(() => writeText?.mockRestore());

    /** The Kebab menu's rows and dividers ("|"), in DOM order, by accessible name. */
    const layout = (menu: HTMLElement) => [...menu.querySelectorAll<HTMLElement>('button, a, [role="separator"]')]
      .map((el) => el.getAttribute("role") === "separator" ? "|" : (el.getAttribute("aria-label") ?? el.textContent ?? "").replace(/^\W+/u, ""));
    const STATS = ["|", "Mass message statistics", "Online fans message statistics"];

    it('the rows read Restrict, Block, Report, Hide chats, Delete conversation, Mute notifications, then "Copy chat link", then the two statistics rows, then "Inflowwww extras", each group after a divider; Report is Not wired and calls nothing', async () => {
      const user = userEvent.setup();
      const head = ["Restrict", "Block", "Report", "Hide chats", "Delete conversation", "Mute notifications", "|",
                    "Copy chat link", "Copy profile link", "Copy username"];
      renderHeader();
      const menu = await openKebab(user);
      expect(layout(menu)).toEqual([...head, ...STATS, "|", "Inflowwww extras"]);

      const report = within(menu).getAllByRole("button")[2];
      expect(report).toHaveAttribute("aria-disabled", "true");
      expect(report).toHaveAttribute("title", "not wired");
      const gets = relayGet.mock.calls.length;
      await user.click(report);
      expect(relayGet).toHaveBeenCalledTimes(gets);
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();
      expect(confirm).not.toHaveBeenCalled();
    });

    it("Hide chats POSTs the chat's hide route with no confirm and keeps the Thread open; a resolved call shows its success text, a rejected one the relay's error", async () => {
      const user = userEvent.setup();
      const onBack = vi.fn();
      renderHeader({ onBack });
      const menu = await openKebab(user);
      const hide = within(menu).getByRole("button", { name: /Hide chats$/ });
      await user.click(hide);
      await waitFor(() => expect(relayPost).toHaveBeenCalledWith(HIDE, undefined, { accountId: ACCOUNT_ID }));
      expect(await within(menu).findByText(/Chat hidden — returns on their next message/)).toBeInTheDocument();
      expect(confirm).not.toHaveBeenCalled();
      expect(onBack).not.toHaveBeenCalled();

      relayPost.mockRejectedValueOnce(new Error("upstream 502: fixture hide down"));
      await user.click(hide);
      await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(2));
      expect(await within(menu).findByText(/upstream 502: fixture hide down/)).toBeInTheDocument();
    });

    it("Delete conversation asks first; declined calls nothing, accepted DELETEs the chat route and the status line confirms it", async () => {
      const user = userEvent.setup();
      renderHeader();
      const menu = await openKebab(user);
      const del = within(menu).getByRole("button", { name: /Delete conversation$/ });
      await user.click(del);
      expect(confirm).toHaveBeenCalledTimes(1);
      expect(relayDelete).not.toHaveBeenCalled();

      confirm.mockReturnValue(true);
      await user.click(del);
      await waitFor(() => expect(relayDelete).toHaveBeenCalledWith(`/api/of/v2/chats/${FAN_ID}`, { accountId: ACCOUNT_ID }));
      expect(await within(menu).findByText(/Conversation deleted/)).toBeInTheDocument();
    });

    it("a role denied Delete chats gets no Delete conversation row", async () => {
      const user = userEvent.setup();
      denied.add("delete-chat");
      renderHeader();
      const menu = await openKebab(user);
      expect(within(menu).queryByRole("button", { name: /Delete conversation$/ })).toBeNull();
      expect(within(menu).getByRole("button", { name: /Hide chats$/ })).toBeInTheDocument();
    });

    it("a role denied Block or restrict fans gets neither the Restrict nor the Block row", async () => {
      const user = userEvent.setup();
      denied.add("block-fan");
      renderHeader();
      const menu = await openKebab(user);
      expect(within(menu).queryByRole("button", { name: /Restrict$/ })).toBeNull();
      expect(within(menu).queryByRole("button", { name: /Block$/ })).toBeNull();
      expect(within(menu).getByRole("button", { name: /Delete conversation$/ })).toBeInTheDocument();
    });

    it('"Copy chat link" writes the Deep link for this Creator and Fan, each part URL-encoded, and the status line confirms it', async () => {
      const user = userEvent.setup();
      writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
      renderHeader({ accountId: "fixture acct/1" });
      const menu = await openKebab(user);
      await user.click(within(menu).getByRole("button", { name: /Copy chat link$/ }));
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/messages-pro/fixture%20acct%2F1/200000001`);
      expect(await within(menu).findByText(/Chat link copied/)).toBeInTheDocument();
      expect(relayPost).not.toHaveBeenCalled();
    });

    it('"Copy profile link" writes the Fan\'s OF profile URL and "Copy username" the bare username, each confirmed on the status line, with no relay write', async () => {
      const user = userEvent.setup();
      writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
      renderHeader();
      const menu = await openKebab(user);
      await user.click(within(menu).getByRole("button", { name: /Copy profile link$/ }));
      expect(writeText).toHaveBeenLastCalledWith("https://onlyfans.com/fixturefanone");
      expect(await within(menu).findByText(/Profile link copied/)).toBeInTheDocument();
      await user.click(within(menu).getByRole("button", { name: /Copy username$/ }));
      expect(writeText).toHaveBeenLastCalledWith("fixturefanone");
      expect(await within(menu).findByText(/Username copied/)).toBeInTheDocument();
      expect(relayPost).not.toHaveBeenCalled();
      expect(relayDelete).not.toHaveBeenCalled();
    });

    it("with no username known yet the two copy rows are disabled", async () => {
      const user = userEvent.setup();
      const noName = { ...CHAT, withUser: { ...CHAT.withUser, username: undefined } } as unknown as OFChatItem;
      renderHeader({ chat: noName });
      const menu = await openKebab(user);
      expect(within(menu).getByRole("button", { name: /Copy profile link$/ })).toBeDisabled();
      expect(within(menu).getByRole("button", { name: /Copy username$/ })).toBeDisabled();
    });

    it('a refused clipboard write shows "Could not copy the chat link" on the status line, not the raw error', async () => {
      const user = userEvent.setup();
      writeText = vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("fixture: write refused"));
      renderHeader();
      const menu = await openKebab(user);
      await user.click(within(menu).getByRole("button", { name: /Copy chat link$/ }));
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(await within(menu).findByText("✗ Could not copy the chat link")).toBeInTheDocument();
      expect(within(menu).queryByText(/write refused|Chat link copied/)).toBeNull();
    });
  });
});
