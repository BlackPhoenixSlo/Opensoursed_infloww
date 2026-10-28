/** OF Manager's page header and creator column (Infloww's, docs/infloww-of-manager-rea.md §1.5, §1.7). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));
const nav = vi.hoisted(() => ({ path: "/of-manager/home", search: "" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.path, useSearchParams: () => new URLSearchParams(nav.search) }));
// Messages Pro's FanDrawer stands in as its props (FanInsights.test.tsx covers the drawer itself).
vi.mock("@/components/chat/FanDrawer", () => ({
  FanDrawer: (p: { pinned?: boolean; accountId: string; fanId: number | string; chat: { withUser: { id: number | string; name?: string } }; onClose: () => void }) => (
    <aside aria-label="Fan insights" data-pinned={String(!!p.pinned)} data-account={p.accountId} data-fan={String(p.fanId)}>
      {p.chat.withUser.name ?? "bare"}
      <button type="button" onClick={p.onClose}>Close insights</button>
    </aside>
  ),
}));
// Messages Pro's Scripts picker stands in as a button picking one script.
const SCRIPT = vi.hoisted(() => ({ source: "local", text: "Script hi", displayText: "Script hi", mediaCount: 1, price: 0, lockedText: false, isWelcome: false, media: [{ id: 61, type: "photo" }], previews: [], taggedUsers: [] }));
vi.mock("@/components/chat/TemplatePicker", () => ({
  TemplatePicker: (p: { accountId: string; onPick(t: unknown): void }) => <button type="button" data-account={p.accountId} onClick={() => p.onPick(SCRIPT)}>Scripts</button>,
}));
const media = vi.hoisted(() => ({ desktop: true }));
vi.stubGlobal("matchMedia", (q: string) => ({ matches: media.desktop, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
vi.mock("@/components/ui/AccountAvatarPicture", () => ({ AccountAvatarPicture: () => null }));
// The `account` blob holds each creator's Tag (useCreatorProfiles); every other read is the notification count.
const TAGS = { tab: "account", config: { creators: { profiles: { "2": { tag: "VIP" } } } } };
const get = vi.fn(async (path: string, _opts?: unknown): Promise<unknown> => (path === "/admin/settings/account" ? TAGS : { all: 250 }));
vi.mock("@/lib/relay", () => ({ relay: { get: (path: string, opts?: unknown) => get(path, opts) }, RelayError: class extends Error {} }));
let accounts: { id: string; nickname: string; has_session: boolean; session_dead_at?: string }[] = [];
let granted: Set<string> | null = null;
vi.mock("@/components/shell/useGrantedPages", () => ({ useGrantedPages: () => granted }));
let rosterCounts: Record<string, { unread: number; owe_reply: number }> = {};
vi.mock("@/hooks/useRosterCounts", () => ({ useRosterCounts: () => rosterCounts }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ isSuccess: true, data: { accounts } }),
  useActiveAccounts: () => accounts,
}));

import { renderWithProviders } from "@/test-utils";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { chatDraftKey } from "@/lib/ofMirrorChat";
import { CreatorColumn } from "./CreatorColumn";
import { OfManagerChrome } from "./OfManagerChrome";

const ui = () => renderWithProviders(<ScopeProvider><OfManagerChrome><p>OF view</p></OfManagerChrome></ScopeProvider>);

beforeEach(() => { localStorage.clear(); granted = null; rosterCounts = {}; nav.path = "/of-manager/home"; nav.search = ""; media.desktop = true; });
afterEach(() => { cleanup(); get.mockClear(); });

describe("OfManagerChrome", () => {
  it("heads the page with the section and lists the creators with their OF notification count", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    ui();
    expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument();
    expect(screen.getAllByTestId("of-creator-row")).toHaveLength(2);
    await waitFor(() => expect(screen.getAllByText("99+")).toHaveLength(2));
    expect(get).toHaveBeenCalledWith("/api/of/v2/users/notifications/count", { accountId: "1" });
    expect(screen.getByText("OF view")).toBeInTheDocument();
  });

  it("a row with unread chats shows Infloww's red unread chip beside the notification count; none at 0", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    rosterCounts = { "1": { unread: 3, owe_reply: 1 }, "2": { unread: 0, owe_reply: 4 } };
    ui();
    const chip = screen.getByLabelText("3 unread chats");
    expect(chip).toHaveTextContent("3");
    expect(chip).toHaveClass("bg-[#FF7C71]", "rounded-[22px]", "text-white");
    expect(screen.getByTitle("asdf")).toContainElement(chip);
    expect(screen.getAllByLabelText(/unread chats/)).toHaveLength(1);
    await waitFor(() => expect(screen.getAllByText("99+")).toHaveLength(2));
  });

  it("picks a creator as the scope and filters by search once typing stops", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    ui();
    fireEvent.click(screen.getByTitle("jade"));
    expect(screen.getByTitle("jade")).toHaveAttribute("aria-current", "true");
    expect(localStorage.getItem("chatterly:scope")).toBe("model:2");
    fireEvent.change(screen.getByLabelText("Search creators"), { target: { value: "asd" } });
    expect(screen.getAllByTestId("of-creator-row")).toHaveLength(2);
    await waitFor(() => expect(screen.getAllByTestId("of-creator-row")).toHaveLength(1));
  });

  it("labels a logged-out creator and reads no OF count for it", async () => {
    accounts = [
      { id: "1", nickname: "asdf", has_session: true, session_dead_at: "2026-10-19T00:00:00Z" },
      { id: "3", nickname: "kim", has_session: true },
    ];
    ui();
    const [dead, live] = screen.getAllByTestId("of-creator-row");
    expect(dead).toHaveTextContent("Disconnected");
    expect(dead).toHaveAttribute("title", "asdf · Disconnected");
    expect(live).toHaveAttribute("title", "kim");
    await waitFor(() => expect(live).toHaveTextContent("99+"));
    // The OF count reads only; the column's Tags read (the `account` blob) is not an OF call.
    const ofCounts = get.mock.calls.filter(([path]) => path === "/api/of/v2/users/notifications/count");
    expect(ofCounts.map((c) => (c[1] as { accountId: string }).accountId)).toEqual(["3"]);
  });

  it("collapses to the 70px strip, unfiltered and kept across loads, and Search expands it", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    ui();
    fireEvent.change(screen.getByLabelText("Search creators"), { target: { value: "asd" } });
    await waitFor(() => expect(screen.getAllByTestId("of-creator-row")).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Collapse creators"));
    expect(screen.getAllByTestId("of-creator-row")).toHaveLength(2);
    const column = screen.getByTestId("of-creator-column");
    expect(column).toHaveClass("w-[70px]");
    expect(localStorage.getItem("chatterly:ofm:column-collapsed")).toBe("1");
    expect(screen.getAllByTestId("of-creator-row")[0]).not.toHaveTextContent("asdf");
    expect(within(column).queryByText("All creators")).toBeNull();
    cleanup();
    ui();
    expect(screen.getByTestId("of-creator-column")).toHaveAttribute("data-collapsed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Search creators" }));
    expect(screen.getByTestId("of-creator-column")).not.toHaveAttribute("data-collapsed");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search creators" })).toHaveFocus());
    expect(localStorage.getItem("chatterly:ofm:column-collapsed")).toBeNull();
  });

  it("warms a live creator's users/me after a 150ms hover or focus, not a passing one's or a dead one's", async () => {
    accounts = [
      { id: "1", nickname: "asdf", has_session: true },
      { id: "2", nickname: "jade", has_session: true, session_dead_at: "x" },
      { id: "3", nickname: "kim", has_session: true },
      { id: "4", nickname: "lu", has_session: true },
    ];
    ui();
    const meFor = (id: string) => get.mock.calls.some((c) => c[0] === "/api/of/v2/users/me" && (c[1] as { accountId: string }).accountId === id);
    fireEvent.mouseEnter(screen.getByTitle("asdf"));
    fireEvent.mouseEnter(screen.getByTitle("jade · Disconnected"));
    fireEvent.focus(screen.getByTitle("kim"));
    fireEvent.blur(screen.getByTitle("kim"));
    fireEvent.focus(screen.getByTitle("lu"));
    await waitFor(() => expect(meFor("1") && meFor("4")).toBe(true));
    await new Promise((r) => setTimeout(r, 200));
    expect(meFor("2")).toBe(false);
    expect(meFor("3")).toBe(false);
  });

  it("/ focuses Search only with nothing focused, arrows walk the rows and Enter picks one", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    ui();
    const search = screen.getByRole("textbox", { name: "Search creators" });
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    fireEvent.keyDown(outside, { key: "/" });
    expect(outside).toHaveFocus();
    outside.remove();
    fireEvent.keyDown(document.body, { key: "/" });
    expect(search).toHaveFocus();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(screen.getByTitle("asdf")).toHaveFocus();
    fireEvent.keyDown(screen.getByTitle("asdf"), { key: "ArrowDown" });
    expect(screen.getByTitle("jade")).toHaveFocus();
    fireEvent.keyDown(screen.getByTitle("jade"), { key: "ArrowDown" });
    expect(screen.getByTitle("jade")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTitle("jade")).toHaveAttribute("aria-current", "true");
    expect(localStorage.getItem("chatterly:scope")).toBe("model:2");
    fireEvent.keyDown(screen.getByTitle("jade"), { key: "ArrowUp" });
    fireEvent.keyDown(screen.getByTitle("asdf"), { key: "ArrowUp" });
    expect(search).toHaveFocus();
  });

  it("offers each Tag as a creator group that narrows the rows", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    ui();
    fireEvent.click(screen.getByRole("button", { name: "All creators" }));
    fireEvent.click(await screen.findByRole("button", { name: "VIP" }));
    expect(screen.getAllByTestId("of-creator-row")).toHaveLength(1);
    expect(screen.getByTitle("jade")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "VIP" }));
    fireEvent.click(screen.getByRole("button", { name: "All creators" }));
    expect(screen.getAllByTestId("of-creator-row")).toHaveLength(2);
  });

  it("shows Infloww's empty state with Link account when no creator is linked", () => {
    accounts = [];
    ui();
    expect(screen.queryByText("OF view")).not.toBeInTheDocument();
    expect(screen.getByText(/You have not yet tied a creator/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link account" })).toHaveAttribute("href", "/creators");
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("no creators renders the data illustration above the text and a 32px Link account", () => {
    accounts = [];
    ui();
    const text = screen.getByText(/You have not yet tied a creator/);
    const art = text.parentElement!.querySelector('[data-empty-art="data"]')!;
    expect(art).toBeInTheDocument();
    expect(art.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(text.querySelector("br")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Link account" })).toHaveClass("h-8");
  });

  it("a chatter sees the no-permission text, not the link", () => {
    accounts = [];
    granted = new Set(["/", "/messages-pro"]);
    ui();
    expect(screen.queryByRole("link", { name: "Link account" })).not.toBeInTheDocument();
    expect(screen.getByText(/you don't have permission for this page/)).toBeInTheDocument();
  });

  it("a creator with session_dead_at shows the expired state, not the mirror", () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true, session_dead_at: "2026-10-19T00:00:00Z" }];
    ui();
    expect(screen.getByText("OF view")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("asdf · Disconnected"));
    expect(screen.queryByText("OF view")).not.toBeInTheDocument();
    expect(screen.getByTestId("of-session-gone")).toHaveTextContent("This creator's OnlyFans connection has expired.");
    expect(screen.getByRole("link", { name: "Go To Creators Management" })).toHaveAttribute("href", "/creators");
  });

  it("shows fullscreen and reload only for one picked creator with a live session", () => {
    accounts = [
      { id: "1", nickname: "asdf", has_session: true },
      { id: "2", nickname: "dead", has_session: true, session_dead_at: "2026-10-19T00:00:00Z" },
      { id: "3", nickname: "none", has_session: false },
    ];
    ui();
    expect(screen.queryByLabelText("Fullscreen")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reload")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("dead · Disconnected"));
    expect(screen.queryByLabelText("Reload")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("none · Disconnected"));
    expect(screen.queryByLabelText("Reload")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("asdf"));
    expect(screen.getByLabelText("Fullscreen")).toBeInTheDocument();
    expect(screen.getByLabelText("Reload")).toBeInTheDocument();
  });

  it("ignores a second reload within 2s", () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }];
    localStorage.setItem("chatterly:scope", "model:1");
    const now = vi.spyOn(Date, "now").mockReturnValue(10_000);
    ui();
    const first = screen.getByText("OF view");
    fireEvent.click(screen.getByLabelText("Reload"));
    const second = screen.getByText("OF view");
    expect(second).not.toBe(first);
    now.mockReturnValue(11_000);
    fireEvent.click(screen.getByLabelText("Reload"));
    expect(screen.getByText("OF view")).toBe(second);
    now.mockReturnValue(12_500);
    fireEvent.click(screen.getByLabelText("Reload"));
    expect(screen.getByText("OF view")).not.toBe(second);
    now.mockRestore();
  });

  it("column No data shows the illustration", async () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }];
    ui();
    fireEvent.change(screen.getByLabelText("Search creators"), { target: { value: "zzz" } });
    const column = screen.getByTestId("of-creator-column");
    await waitFor(() => expect(column.querySelector('[data-empty-art="data"]')).toBeInTheDocument());
    expect(column).toHaveTextContent("No data");
  });

  it("Pop out opens this page in its own window on the picked creator, which that window takes without saving", () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    ui();
    expect(screen.queryByRole("button", { name: "Pop out" })).toBeNull(); // All creators: no view tools
    fireEvent.click(screen.getByTitle("jade"));
    fireEvent.click(screen.getByRole("button", { name: "Pop out" }));
    expect(open).toHaveBeenLastCalledWith("/of-manager/home?account=2", "_blank", "popup");
    open.mockRestore();
    cleanup();

    localStorage.setItem("chatterly:scope", "model:1");
    window.history.replaceState(null, "", "/of-manager/home?account=2");
    try {
      ui();
      expect(screen.getByTitle("jade")).toHaveAttribute("aria-current", "true");
      expect(localStorage.getItem("chatterly:scope")).toBe("model:1");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});

describe("OfManagerChrome Fan insights", () => {
  const chatPage = (search = "?chat=42") => { nav.path = "/of-manager/messages/chat"; nav.search = search; };
  beforeEach(() => { accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }]; });

  it("pins Messages Pro's Fan insights beside an open chat of one creator, with the chat row from the chats cache", () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    const { queryClient } = ui();
    const aside = screen.getByRole("complementary", { name: "Fan insights" });
    expect(aside).toHaveAttribute("data-pinned", "true");
    expect(aside).toHaveAttribute("data-account", "1");
    expect(aside).toHaveAttribute("data-fan", "42");
    expect(aside).toHaveTextContent("bare");
    // Messages Pro's Infloww palette: the wrapper re-declares --inf-insights for the drawer.
    expect((aside.closest(".absolute") as HTMLElement).style.getPropertyValue("--inf-insights")).toBe("#0d0d0d");
    expect(screen.getByText("OF view")).toBeInTheDocument();
    act(() => queryClient.setQueryData(["chats", "model", "1", null, null, null, 20], {
      pages: [{ rows: [{ __accountId: "1", withUser: { id: 42, name: "Fan Forty-Two" } }], hasMore: false }], pageParams: [0],
    }));
    expect(screen.getByRole("complementary", { name: "Fan insights" })).toHaveTextContent("Fan Forty-Two");
  });

  it("shows no Fan insights without ?chat=, off the chat page, or in All creators", () => {
    chatPage("");
    localStorage.setItem("chatterly:scope", "model:1");
    ui();
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    expect(screen.queryByLabelText("Fan insights")).toBeNull();
    cleanup();
    nav.path = "/of-manager/messages"; nav.search = "?chat=42";
    ui();
    expect(screen.queryByLabelText("Fan insights")).toBeNull();
    cleanup();
    chatPage();
    localStorage.setItem("chatterly:scope", "all");
    ui();
    expect(screen.queryByLabelText("Fan insights")).toBeNull();
  });

  it("the header toggle hides and shows the column and keeps the choice", () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    ui();
    const toggle = screen.getByRole("button", { name: "Fan insights" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle);
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(localStorage.getItem("oi:ofm:insights")).toBe("0");
    cleanup();
    ui();
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fan insights" }));
    expect(screen.getByRole("complementary", { name: "Fan insights" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close insights" }));
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    expect(localStorage.getItem("oi:ofm:insights")).toBe("0");
  });

  it("lies over the view's right edge and marks the OF page to leave it the room, unmarked once hidden", () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    renderWithProviders(<ScopeProvider><OfManagerChrome><iframe title="OF view" /></OfManagerChrome></ScopeProvider>);
    const page = () => (screen.getByTitle("OF view") as HTMLIFrameElement).contentDocument!.documentElement;
    const aside = screen.getByRole("complementary", { name: "Fan insights" });
    expect(aside.closest(".absolute")).toHaveClass("absolute", "right-0");
    expect(aside.closest(".absolute")!.parentElement).toContainElement(screen.getByTitle("OF view"));
    expect(page()).toHaveAttribute("data-oi-insights");
    fireEvent.click(screen.getByRole("button", { name: "Fan insights" }));
    expect(page()).not.toHaveAttribute("data-oi-insights");
  });

  it("is the chat's one Fan insights, with the chat the mirror's page reads when the chats cache has no row", async () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    get.mockImplementation(async (path: string) => (path === "/api/of/v2/chats/42" ? { withUser: { id: 42, name: "Mirror Fan" } } : { all: 250 }));
    ui();
    expect(await screen.findByText("Mirror Fan")).toBeInTheDocument();
    expect(screen.getAllByRole("complementary", { name: "Fan insights" })).toHaveLength(1);
    expect(get).toHaveBeenCalledWith("/api/of/v2/chats/42", { accountId: "1" });
    get.mockImplementation(async (path: string) => (path === "/admin/settings/account" ? TAGS : { all: 250 }));
  });

  it("a script picked over the column goes on the chat's draft", () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    sessionStorage.clear();
    ui();
    fireEvent.click(screen.getByRole("button", { name: "Scripts" }));
    expect(JSON.parse(sessionStorage.getItem(chatDraftKey("1", "42"))!)).toMatchObject({ text: "Script hi", media_files: [61] });
  });

  it("a frame mid-swap (a document with no <html> yet) is skipped, not a TypeError", () => {
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    const blank = document.createElement("iframe");
    Object.defineProperty(blank, "contentDocument", { value: { documentElement: null } });
    const Swap = () => <div ref={(el) => { if (el && !el.contains(blank)) el.appendChild(blank); }} />;
    expect(() => renderWithProviders(<ScopeProvider><OfManagerChrome><Swap /></OfManagerChrome></ScopeProvider>)).not.toThrow();
    expect(() => fireEvent.click(screen.getByRole("button", { name: "Fan insights" }))).not.toThrow();
  });

  it("below lg the toggle opens the slide-over, closed by default", () => {
    media.desktop = false;
    chatPage();
    localStorage.setItem("chatterly:scope", "model:1");
    ui();
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fan insights" }));
    expect(screen.getByRole("complementary", { name: "Fan insights" })).toHaveAttribute("data-pinned", "false");
    fireEvent.click(screen.getByRole("button", { name: "Close insights" }));
    expect(screen.queryByRole("complementary", { name: "Fan insights" })).toBeNull();
    expect(localStorage.getItem("oi:ofm:insights")).toBeNull();
  });
});

describe("CreatorColumn s4s", () => {
  it("shows the S4S tag and the new-request count, no All creators menu, and reads no OF notification count", () => {
    accounts = [{ id: "1", nickname: "asdf", has_session: true }, { id: "2", nickname: "jade", has_session: true }];
    const onChange = vi.fn();
    renderWithProviders(
      <CreatorColumn variant="s4s" accounts={accounts.map((a) => ({ ...a, is_active: true, proxy_down: false }))} value="1" onChange={onChange}
        marks={{ "1": { optedIn: true, pending: 2 }, "2": { optedIn: false, pending: 0 } }} />,
    );
    const [one, two] = screen.getAllByTestId("of-creator-row");
    expect(one).toHaveAttribute("aria-current", "true");
    expect(one).toHaveTextContent("S4S");
    expect(screen.getByLabelText("2 new requests")).toHaveTextContent("2");
    expect(two).not.toHaveTextContent("S4S");
    expect(screen.queryByText("All creators")).toBeNull();
    fireEvent.click(two);
    expect(onChange).toHaveBeenCalledWith("2");
    expect(get).not.toHaveBeenCalled();
  });
});
