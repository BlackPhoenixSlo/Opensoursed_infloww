/**
 * AssistantWidget — the boundaries this component actually owns.
 *
 * The answers themselves are the server's job (service/tests/test_assistant_api.py
 * covers those). What can only go wrong HERE is the request shape — a `role`
 * field the server must never be handed, an account_id with no account behind it — and
 * the 200-always contract: a used-up cap comes back as `{answer, error:"cap"}`
 * and has to READ as an answer, because a bot that looks broken exactly when
 * someone needs config help is the failure mode the endpoint exists to avoid.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted with the vi.mock factories below — anything they close over has to
// be, or it is still in its TDZ when the mocked module is first imported.
const { relayPost, relayGet, nav, scope, employee, roster, signedIn } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  nav: { pathname: "/", pushed: [] as string[] },
  scope: { accountId: "1001" as string | null },
  employee: { current: { id: 7 } as { id: number } | null },
  // The OWNED accounts (useAccounts); `loaded` false = the query still loading,
  // in the hook's real chatter shape: `accounts: []`, isSuccess false, dataUpdatedAt 0.
  roster: {
    list: [] as Array<{ id: string; nickname?: string | null; has_session?: boolean; is_active?: boolean }>,
    loaded: true,
  },
  // A signed-in user (an owner) can ask about General; a chatter session can't.
  signedIn: { user: { username: "vaerunner" } as { username: string } | null },
}));

vi.mock("@/lib/relay", () => {
  class RelayError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown, message?: string) {
      super(message || `relay ${status}`);
      this.status = status;
      this.body = body;
    }
  }
  return {
    RelayError,
    relay: { post: (...a: unknown[]) => relayPost(...a), get: (...a: unknown[]) => relayGet(...a) },
  };
});

vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
// The router is the boundary: a link click records where it went and runs the
// caller's onClick, as next/link's does before its client-side push.
vi.mock("next/link", () => ({
  default: ({ href, onClick, children, ...rest }: { href: string; onClick?: (e: unknown) => void; children: React.ReactNode }) => (
    <a {...rest} href={href} onClick={(e) => { e.preventDefault(); nav.pushed.push(href); onClick?.(e); }}>{children}</a>
  ),
}));

vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => employee }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => (roster.loaded
    ? { data: { accounts: roster.list }, isSuccess: true, dataUpdatedAt: 1 }
    : { data: { accounts: [] }, isSuccess: false, dataUpdatedAt: 0 }),
}));
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => (signedIn.user ? { user: signedIn.user } : null) }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget, LAUNCHER_KEY } from "./AssistantWidget";
import { PageCreatorProvider, usePageCreator } from "@/contexts/PageCreatorContext";

const tree = () => <PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>;
let view: ReturnType<typeof renderWithProviders>;

/** The widget starts collapsed; every case here works in the open panel. */
async function openPanel() {
  view = renderWithProviders(tree());
  const bubble = await screen.findByRole("button", { name: "Help assistant" });
  await userEvent.click(bubble);
  return bubble;
}

/** The app's model switcher moves (ScopeContext). */
function switchApp(accountId: string | null) {
  scope.accountId = accountId;
  view.rerender(tree());
}

const focusButton = () => screen.getByRole("button", { name: /^Help bot focus:/ });

async function ask(question: string) {
  await userEvent.type(screen.getByPlaceholderText("Ask a question…"), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => {
  relayPost.mockReset();
  relayGet.mockReset();
  // GET /admin/errors?since_hours=24 — the Status card's source.
  relayGet.mockResolvedValue({ count: 0, since_hours: 24, list: [] });
  nav.pathname = "/";
  nav.pushed = [];
  scope.accountId = "1001";
  employee.current = { id: 7 };
  signedIn.user = { username: "vaerunner" };
  roster.list = [
    { id: "1001", nickname: "Blake1", has_session: true, is_active: true },
    { id: "1002", nickname: "Blake2", has_session: true, is_active: true },
  ];
  roster.loaded = true;
  window.localStorage.clear();
});
afterEach(cleanup);

describe("AssistantWidget", () => {
  it.each(["/messages-pro", "/messages-pro/1001/9001"])(
    "hides the launcher and an already-open panel on %s", async (path) => {
      const view = renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
      await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
      nav.pathname = path;
      view.rerender(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
      expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
      expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    },
  );

  it("starts collapsed and remembers being opened", async () => {
    const bubble = await openPanel();
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
    expect(window.localStorage.getItem("chatterly:assistant_open")).toBe("1");

    await userEvent.click(bubble);
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    expect(window.localStorage.getItem("chatterly:assistant_open")).toBe("0");
  });

  it("sends {question, account_id, thread_id} and NO role, focused on the switcher's model", async () => {
    relayPost.mockResolvedValue({ answer: "Growth → Profile promotion.", error: null });
    await openPanel();
    await ask("how do I set up auto posts?");

    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    const [path, body, ctx] = relayPost.mock.calls[0];
    expect(path).toBe("/admin/assistant/ask");
    expect(body).toEqual({ question: "how do I set up auto posts?", account_id: "1001", thread_id: expect.any(String) });
    // The server derives who is asking from the session — a role in the body
    // would be client-supplied theater, so it must not be there at all.
    expect(Object.keys(body as object)).not.toContain("role");
    expect(ctx).toMatchObject({ accountId: "1001", employeeId: 7 });
    // The model in play is on screen, not inferred.
    expect(focusButton().textContent).toBe("Blake1");
    // The answer renders, and its click path is a real destination rather than
    // a route to read and re-type. AnswerText.test.tsx owns the rendering
    // rules; what matters here is that the widget hands the answer to it.
    expect(await screen.findByRole("link", { name: /Profile promotion/ })).toBeTruthy();
  });

  it("renders a handled failure (cap/config/provider) as a normal answer", async () => {
    relayPost.mockResolvedValue({
      answer: "This account's AI budget is used up for today.",
      error: "cap",
    });
    await openPanel();
    await ask("anything");

    expect(
      await screen.findByText("This account's AI budget is used up for today."),
    ).toBeTruthy();
  });

  it("answers in the bubble when the request never reaches a verdict", async () => {
    relayPost.mockRejectedValue(new Error("relay 502"));
    await openPanel();
    await ask("anything");

    expect(await screen.findByText(/Couldn't reach the assistant/)).toBeTruthy();
  });

  it("keeps the composer live while an answer is in flight", async () => {
    // v2: an in-flight answer must not lock the textarea — a second question
    // can be typed and sent, and answers settle to their own turns by id.
    const settles: Array<(v: unknown) => void> = [];
    relayPost.mockImplementation(() => new Promise((res) => settles.push(res)));
    await openPanel();
    await ask("first question");

    const box = screen.getByPlaceholderText("Ask a question…");
    expect((box as HTMLTextAreaElement).disabled).toBe(false);
    await ask("second question");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(2));

    // Settle out of order — each answer lands on its own turn.
    settles[1]({ answer: "second answer", error: null });
    settles[0]({ answer: "first answer", error: null });
    expect(await screen.findByText("second answer")).toBeTruthy();
    expect(await screen.findByText("first answer")).toBeTruthy();
  });

  it("all-models scope is General: no account_id; a pick focuses a model and survives a collapse", async () => {
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    scope.accountId = null;
    const bubble = await openPanel();
    expect(focusButton().textContent).toBe("General");
    await ask("where is the vault?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    const [, body0, ctx0] = relayPost.mock.calls[0];
    expect(body0).toEqual({ question: "where is the vault?", thread_id: expect.any(String) });
    expect(ctx0).toMatchObject({ accountId: null });

    // Mid-chat, another focus is a new chat about it.
    await userEvent.click(focusButton());
    expect(screen.getByText("Picking another starts a new chat")).toBeTruthy();
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Blake2/ }));
    expect(screen.queryByText("where is the vault?")).toBeNull();
    expect(focusButton().textContent).toBe("Blake2");
    await ask("is my welcome on?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(2));
    const body1 = relayPost.mock.calls[1][1] as { account_id: string; thread_id: string };
    expect(body1.account_id).toBe("1002");
    expect(body1.thread_id).not.toBe((body0 as { thread_id: string }).thread_id);

    // The pick lives in the provider: a close/reopen keeps it and the chat.
    await userEvent.click(bubble);
    await userEvent.click(bubble);
    await ask("and the follow-up?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(3));
    expect(relayPost.mock.calls[2][1]).toMatchObject({ account_id: "1002", thread_id: body1.thread_id });
  });

  it("a chatter session has no General: all models falls back to the first account", async () => {
    signedIn.user = null;
    scope.accountId = null;
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    await openPanel();
    expect(focusButton().textContent).toBe("Blake1");
    await userEvent.click(focusButton());
    expect(screen.queryByRole("menuitemradio", { name: /General/ })).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    await ask("q");
    await waitFor(() => expect(relayPost.mock.calls[0][1]).toMatchObject({ account_id: "1001" }));
  });

  it("a page's own creator pick (Vault Pro's rail) is the app's model while that page is open", async () => {
    function Page({ focus }: { focus: string | null | undefined }) {
      usePageCreator(focus);
      return null;
    }
    const withPage = (focus?: string | null) => (
      <PageCreatorProvider><AssistantProvider><AssistantWidget />{focus !== undefined && <Page focus={focus} />}</AssistantProvider></PageCreatorProvider>
    );
    view = renderWithProviders(withPage("1002"));
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    expect(focusButton().textContent).toBe("Blake2");
    view.rerender(withPage("1001"));        // the rail moves
    expect(focusButton().textContent).toBe("Blake1");
    view.rerender(withPage(null));          // its "All" row
    expect(focusButton().textContent).toBe("General");
    view.rerender(withPage("1002"));
    view.rerender(withPage(undefined));     // leaving the page: the switcher again
    expect(focusButton().textContent).toBe("Blake1");
  });

  it("a page's pick of a session-dropped model (Vault Pro keeps one) stays focused, marked offline", async () => {
    roster.list = [...roster.list, { id: "1003", nickname: "Blake3", has_session: false, is_active: true }];
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    function Page() {
      usePageCreator("1003");
      return null;
    }
    view = renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /><Page /></AssistantProvider></PageCreatorProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    expect(focusButton().textContent).toBe("Blake3");
    await userEvent.click(focusButton());
    expect(screen.getByRole("menuitemradio", { name: /Blake3/ }).textContent).toMatch(/Offline/);
    expect(screen.getByRole("menuitemradio", { name: /Blake1/ }).textContent).not.toMatch(/Offline/);
    await userEvent.keyboard("{Escape}");
    await ask("why is he quiet?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    expect(relayPost.mock.calls[0][1]).toMatchObject({ account_id: "1003" });
  });

  it("an owner whose only model has no session still gets the focus line, not 'none connected'", async () => {
    roster.list = [{ id: "1003", nickname: "Blake3", has_session: false, is_active: false }];
    scope.accountId = null;
    await openPanel();
    expect(focusButton().textContent).toBe("General");
    expect(screen.queryByText(/No account connected yet/)).toBeNull();
  });

  it("a chatter cannot send General while the roster loads; once loaded it goes to the first account", async () => {
    signedIn.user = null;
    scope.accountId = null;
    roster.loaded = false;
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    await openPanel();
    await userEvent.type(screen.getByPlaceholderText("Ask a question…"), "q");
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/No account connected yet|No creator assigned/)).toBeNull();
    roster.loaded = true;
    view.rerender(tree());
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    expect(relayPost.mock.calls[0][1]).toMatchObject({ account_id: "1001" });
  });

  it("a chatter's loading roster (accounts: []) never turns the app's model into General", async () => {
    signedIn.user = null;
    scope.accountId = "1002";
    roster.loaded = false;
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    await openPanel();
    expect(screen.queryByText(/No account connected yet|No creator assigned/)).toBeNull();
    expect(screen.queryByRole("link", { name: /Add creator/ })).toBeNull();
    roster.loaded = true;
    view.rerender(tree());
    expect(focusButton().textContent).toBe("Blake2");
    await ask("first after load");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    expect(relayPost.mock.calls[0][1]).toMatchObject({ account_id: "1002" });
    expect(relayPost.mock.calls[0][2]).toMatchObject({ accountId: "1002" });
  });

  it("a chatter with no account gets neutral copy, never the 'Add creator' path", async () => {
    signedIn.user = null;
    scope.accountId = null;
    roster.list = [];
    await openPanel();
    expect(screen.getByText(/No creator assigned to you yet/)).toBeTruthy();
    expect(screen.queryByText(/No account connected yet/)).toBeNull();
    expect(screen.queryByRole("link", { name: /Creators → Manage creators/ })).toBeNull();
    // The server 401s a chatter's account-less ask: nothing to send.
    await userEvent.type(screen.getByRole("textbox"), "anything");
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("follows the app's model switcher until a chat starts, then offers the switch", async () => {
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    await openPanel();
    expect(focusButton().textContent).toBe("Blake1");
    switchApp("1002");
    expect(focusButton().textContent).toBe("Blake2");
    // A manual pick holds until the app switches again.
    await userEvent.click(focusButton());
    await userEvent.click(screen.getByRole("menuitemradio", { name: /General/ }));
    expect(focusButton().textContent).toBe("General");
    switchApp("1001");
    expect(focusButton().textContent).toBe("Blake1");

    // Started: the switch is held, the chat stays on its model…
    await ask("why is he quiet?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    switchApp("1002");
    expect(focusButton().textContent).toBe("Blake1");
    // …and offered as a new chat.
    await userEvent.click(screen.getByRole("button", { name: "Blake2 in app · New chat" }));
    expect(focusButton().textContent).toBe("Blake2");
    expect(screen.queryByText("why is he quiet?")).toBeNull();
    expect(screen.getByRole("heading", { name: /How can we help\?/ })).toBeTruthy();
  });

  it("dots the launcher when a reply lands while the panel is closed", async () => {
    let settle: (v: unknown) => void = () => {};
    relayPost.mockImplementation(() => new Promise((res) => { settle = res; }));
    const bubble = await openPanel();
    await ask("anything");
    await userEvent.click(bubble);
    expect(screen.queryByLabelText("New reply")).toBeNull();

    settle({ answer: "an answer", error: null });
    expect(await screen.findByLabelText("New reply")).toBeTruthy();

    // Opening the panel reads it.
    await userEvent.click(bubble);
    expect(screen.queryByLabelText("New reply")).toBeNull();
    expect(await screen.findByText("an answer")).toBeTruthy();
  });

  it("answers with no account at all: no account_id sent, the connect page linked", async () => {
    scope.accountId = null;
    roster.list = [];
    relayPost.mockResolvedValue({
      answer: "Connect one first: **Creators → Manage creators → Add creator**.",
      error: null,
    });
    await openPanel();

    // The hint above the composer is itself a link to the connect page.
    const hint = screen.getByRole("link", { name: /Creators → Manage creators/ });
    expect(hint.getAttribute("href")).toBe("/creators");
    expect(screen.queryByRole("button", { name: /^Help bot focus:/ })).toBeNull();

    await ask("how do I connect my OnlyFans account?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    const [, body, ctx] = relayPost.mock.calls[0];
    // Omitted, not null or "": the server reads a missing id as "no account yet".
    expect(body).toEqual({ question: "how do I connect my OnlyFans account?", thread_id: expect.any(String) });
    expect(ctx).toMatchObject({ accountId: null, employeeId: 7 });
    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: /Creators → Manage creators/ })).toHaveLength(2),
    );
    for (const a of screen.getAllByRole("link", { name: /Creators → Manage creators/ })) {
      expect(a.getAttribute("href")).toBe("/creators");
    }
  });

  it("hides the launcher and the dock on /help-center, where the page is the panel", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    nav.pathname = "/help-center";
    renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
    // render() flushes the hydration effect, so "open" has been read by now.
    expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
  });

  it("has no Status card, and no Earlier card with no earlier conversations", async () => {
    await openPanel();
    expect(screen.getByText("Ask a question")).toBeTruthy();
    expect(screen.queryByText(/Status:/)).toBeNull();
    expect(screen.queryByText("Earlier conversations")).toBeNull();
  });

  it("focuses the composer from the Ask a question card, without a scroll-into-view", async () => {
    await openPanel();
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    await userEvent.click(screen.getByRole("button", { name: /Ask a question/ }));
    expect(document.activeElement).toBe(screen.getByPlaceholderText("Ask a question…"));
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    focus.mockRestore();
  });

  it("a link click in the dock navigates and keeps the dock open, the page unlocked", async () => {
    relayPost.mockResolvedValue({ answer: "Open **Creators → Manage creators**.", error: null });
    await openPanel();
    await ask("add a creator?");
    await userEvent.click(await screen.findByRole("link", { name: "Creators → Manage creators" }));
    expect(nav.pushed).toEqual(["/creators"]);
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
    expect(document.body.style.position).toBe("");
  });

  describe("history", () => {
    const rows = [
      { id: 12, ts: new Date().toISOString(), question: "where are auto posts?", answer: "Growth → Auto Posts. Want the steps?", error: null, account_id: "1002", thread_id: "th-a" },
      { id: 11, ts: new Date(Date.now() - 3 * 86_400_000).toISOString(), question: "old q", answer: "old a", error: null, account_id: null, thread_id: "th-b" },
      // From before threads: grouped client-side.
      { id: 10, ts: new Date(Date.now() - 4 * 86_400_000).toISOString(), question: "capped", answer: "Cap used up.", error: "cap", account_id: "1001", thread_id: null },
    ];
    const earlierCard = () => screen.findByRole("button", { name: /^Earlier conversations\s*3 conversations/ });
    beforeEach(() => {
      relayGet.mockImplementation((path: string) => Promise.resolve(
        path.startsWith("/admin/assistant/history") ? { turns: rows } : { count: 0, since_hours: 24, list: [] },
      ));
    });
    const historyCalls = () => relayGet.mock.calls.filter(([p]) => String(p).startsWith("/admin/assistant/history"));

    it("loads once on the first open; earlier conversations sit in a list by day, never inline", async () => {
      const bubble = await openPanel();
      await userEvent.click(await earlierCard());
      expect(screen.queryByText("Growth → Auto Posts. Want the steps?")).toBeNull();
      const list = screen.getByRole("dialog", { name: "Earlier conversations" });
      expect(within(list).getByRole("region", { name: "Today" })).toBeTruthy();
      expect(within(list).getByText("where are auto posts?")).toBeTruthy();
      expect(within(list).getByText(/^Blake2 · 1 question · /)).toBeTruthy();
      expect(within(list).getByText(/^General · 1 question · /)).toBeTruthy();
      expect(historyCalls()).toHaveLength(1);
      expect(historyCalls()[0][0]).toBe("/admin/assistant/history?limit=500");

      await userEvent.click(bubble); // close
      await userEvent.click(bubble); // reopen: no second read
      await earlierCard();
      expect(historyCalls()).toHaveLength(1);
    });

    it("opening one shows it alone and continues it: its thread, its model", async () => {
      relayPost.mockResolvedValue({ answer: "Here are the steps.", error: null, id: 13 });
      await openPanel();
      await userEvent.click(await earlierCard());
      await userEvent.click(screen.getByRole("button", { name: /where are auto posts\?/ }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(screen.getByText("where are auto posts?")).toBeTruthy();
      expect(screen.queryByText("old q")).toBeNull();
      expect(focusButton().textContent).toBe("Blake2");
      await ask("yes");
      await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
      // No history in the body: the server reads the thread's turns.
      expect(relayPost.mock.calls[0][1]).toEqual({ question: "yes", account_id: "1002", thread_id: "th-a" });
      // The read is the asker's own across accounts: no account/employee header.
      expect(historyCalls()[0]).toHaveLength(1);
      // Back is a new chat, with the switcher's model again.
      await userEvent.click(screen.getByRole("button", { name: "New chat" }));
      expect(screen.queryByText("yes")).toBeNull();
      expect(focusButton().textContent).toBe("Blake2");
    });

    it("a turn asked while the history read failed shows once after the retry", async () => {
      let fail = true;
      relayGet.mockImplementation((path: string) => {
        if (!path.startsWith("/admin/assistant/history")) return Promise.resolve({ count: 0, since_hours: 24, list: [] });
        if (fail) return Promise.reject(new Error("relay 502"));
        // The retry already holds the row the ask wrote (id 20).
        return Promise.resolve({ turns: [{ id: 20, ts: new Date().toISOString(), question: "fresh q", answer: "fresh a", error: null, account_id: "1001", thread_id: "th-x" }, ...rows] });
      });
      relayPost.mockResolvedValue({ answer: "fresh a", error: null, id: 20 });
      const bubble = await openPanel();
      await waitFor(() => expect(historyCalls()).toHaveLength(1));
      await ask("fresh q");
      await screen.findByText("fresh a");
      fail = false;
      await userEvent.click(bubble);
      await userEvent.click(bubble);
      await waitFor(() => expect(historyCalls()).toHaveLength(2));
      await userEvent.click(await screen.findByRole("button", { name: "Earlier conversations" }));
      const list = screen.getByRole("dialog", { name: "Earlier conversations" });
      expect(within(list).getAllByText("fresh q")).toHaveLength(1);
      expect(within(list).getAllByRole("button", { name: /question/ })).toHaveLength(4);
    });

    it("a failed history read is no history, and the next open retries", async () => {
      relayGet.mockImplementation((path: string) => path.startsWith("/admin/assistant/history")
        ? Promise.reject(new Error("relay 401")) : Promise.resolve({ count: 0, since_hours: 24, list: [] }));
      const bubble = await openPanel();
      await waitFor(() => expect(historyCalls()).toHaveLength(1));
      expect(screen.queryByRole("button", { name: /Earlier conversations/ })).toBeNull();
      await userEvent.click(bubble);
      await userEvent.click(bubble);
      await waitFor(() => expect(historyCalls()).toHaveLength(2));
    });
  });
});

/** Phone width: matchMedia says "below the corner launcher's breakpoint", the
 *  viewport is 390×844, and a button's rect is where its inline style put it
 *  (jsdom has no layout). */
describe("AssistantWidget on a phone", () => {
  const real = { w: window.innerWidth, h: window.innerHeight, mm: window.matchMedia };
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 390 });
    Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 844 });
    window.matchMedia = ((q: string) => ({
      matches: q.includes("max-width"), media: q,
      addEventListener: () => {}, removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const left = parseFloat(this.style.left) || 0;
      const top = parseFloat(this.style.top) || 0;
      return { left, top, right: left + 48, bottom: top + 48, width: 48, height: 48, x: left, y: top, toJSON: () => ({}) } as DOMRect;
    });
  });
  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: real.w });
    Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: real.h });
    window.matchMedia = real.mm;
    vi.restoreAllMocks();
  });

  const render = () => renderWithProviders(<PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>);
  const stored = () => JSON.parse(window.localStorage.getItem(LAUNCHER_KEY) || "null");
  /** Press the launcher, move by (dx, dy) in two steps, release. */
  async function drag(el: HTMLElement, dx: number, dy: number) {
    const r = el.getBoundingClientRect();
    const x = r.left + 24, y = r.top + 24;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: el, coords: { clientX: x, clientY: y } },
      { target: el, coords: { clientX: x + dx / 2, clientY: y + dy / 2 } },
      { target: el, coords: { clientX: x + dx, clientY: y + dy } },
      { keys: "[/MouseLeft]", target: el },
    ]);
  }

  /** The default is tucked: tap its tab to get the icon out. */
  async function pullOut() {
    await userEvent.click(await screen.findByRole("button", { name: "Show help assistant" }));
    return screen.getByRole("button", { name: "Help assistant" });
  }

  it("starts tucked into the left edge above the composer: only the tab shows", async () => {
    render();
    const tab = await screen.findByRole("button", { name: "Show help assistant" });
    expect(tab.className).toContain("left-0");
    expect(tab.style.top).toBe(`${844 - 48 - 180}px`);
    expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
    expect(window.localStorage.getItem(LAUNCHER_KEY)).toBeNull();
  });

  it("ignores a v1 spot: the old key never moves the launcher out of its tucked default", async () => {
    window.localStorage.setItem("chatterly:assistant_launcher", JSON.stringify({ edge: "left", along: 12, tucked: false }));
    render();
    expect(await screen.findByRole("button", { name: "Show help assistant" })).toBeTruthy();
  });

  it("the tab pulls the icon out at the same height; a tap opens the full-screen sheet", async () => {
    render();
    const bubble = await pullOut();
    expect(bubble.style.left).toBe("12px");
    expect(bubble.style.top).toBe(`${844 - 48 - 180}px`);
    expect(stored()).toEqual({ edge: "left", along: 180, tucked: false });
    await userEvent.click(bubble);

    const box = screen.getByPlaceholderText("Ask a question…");
    const sheet = box.closest("[data-look='messenger']") as HTMLElement;
    expect(sheet.className).toContain("inset-x-0");
    expect(sheet.className).not.toContain("w-[400px]");
    // The sheet covers the launcher; its X is the way out, and brings it back.
    expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    expect(screen.getByRole("button", { name: "Help assistant" })).toBeTruthy();
  });

  it("the sheet locks the page under it and unlocks it on close, leaving other locks alone", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    document.body.style.paddingRight = "15px";       // another lock, from before
    render();
    const box = await screen.findByPlaceholderText("Ask a question…");
    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");
    // Pinned to the visual viewport through the boot script's vars, not inline styles.
    const sheet = box.closest("[data-look='messenger']") as HTMLElement;
    expect(sheet.className).toContain("top-[var(--vvt,0px)]");
    expect(sheet.getAttribute("style")).toBeNull();
    // 16px: iOS zooms into a smaller input on focus.
    expect(box.className).toContain("text-[16px]");
    document.body.style.touchAction = "none";        // another lock, taken meanwhile
    await userEvent.click(screen.getByRole("button", { name: "Close help" }));
    for (const p of ["position", "top", "left", "right", "width", "overflow"] as const) {
      expect(document.body.style[p]).toBe("");
    }
    expect(document.body.style.paddingRight).toBe("15px");
    expect(document.body.style.touchAction).toBe("none");
    expect(document.documentElement.style.overflow).toBe("");
    document.body.removeAttribute("style");
  });

  it("a tapped answer link navigates AND closes the sheet", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    relayPost.mockResolvedValue({ answer: "Open **Creators → Manage creators**.", error: null });
    render();
    await ask("add a creator?");
    await userEvent.click(await screen.findByRole("link", { name: "Creators → Manage creators" }));
    expect(nav.pushed).toEqual(["/creators"]);
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    expect(window.localStorage.getItem("chatterly:assistant_open")).toBe("0");
    expect(document.body.style.position).toBe("");
  });

  it("earlier conversations never bury the composer on the sheet: they open from the card", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    relayGet.mockImplementation((path: string) => Promise.resolve(path.startsWith("/admin/assistant/history")
      ? { turns: [{ id: 1, ts: new Date().toISOString(), question: "old q", answer: "old a", error: null, account_id: null, thread_id: "t1" }] }
      : { count: 0, since_hours: 24, list: [] }));
    render();
    const card = await screen.findByRole("button", { name: /^Earlier conversations\s*1 conversation · / });
    expect(screen.queryByText("old q")).toBeNull();
    await userEvent.click(card);
    await userEvent.click(screen.getByRole("button", { name: /old q/ }));
    expect(screen.getByText("old a")).toBeTruthy();
  });

  it("a drag moves it and snaps to the nearest edge, swallowing the release click", async () => {
    render();
    const bubble = await pullOut();
    await drag(bubble, 280, -300);

    // Dropped near the right side: snapped flush to it, panel NOT opened.
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    const moved = screen.getByRole("button", { name: "Help assistant" });
    expect(moved.style.left).toBe(`${390 - 48 - 12}px`);
    expect(stored()).toEqual({ edge: "right", along: 480, tucked: false });

    // The next real tap still opens it (the swallow is one-shot).
    await userEvent.click(moved);
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
  });

  it("a finger's tap jitter under 10px is a tap, not a drag", async () => {
    render();
    const bubble = await pullOut();
    const r = bubble.getBoundingClientRect();
    const x = r.left + 24, y = r.top + 24;
    await userEvent.pointer([
      { keys: "[TouchA>]", target: bubble, coords: { clientX: x, clientY: y } },
      { pointerName: "TouchA", target: bubble, coords: { clientX: x + 6, clientY: y + 5 } },
      { keys: "[/TouchA]", target: bubble },
    ]);
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
  });

  it("re-tucks when pushed past a side edge; the chevron tab pulls it back out", async () => {
    render();
    const bubble = await pullOut();
    await drag(bubble, -60, 0);

    expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
    let tab = screen.getByRole("button", { name: "Show help assistant" });
    expect(tab.className).toContain("left-0");
    expect(stored()).toEqual({ edge: "left", along: 180, tucked: true });

    // Out again, over to the right side, tucked there.
    await userEvent.click(tab);
    await drag(screen.getByRole("button", { name: "Help assistant" }), 390, 0);
    tab = screen.getByRole("button", { name: "Show help assistant" });
    expect(tab.className).toContain("right-0");
    expect(stored()).toEqual({ edge: "right", along: 180, tucked: true });

    await userEvent.click(tab);
    expect(screen.queryByRole("button", { name: "Show help assistant" })).toBeNull();
    expect(screen.getByRole("button", { name: "Help assistant" }).style.top).toBe(`${844 - 48 - 180}px`);
    expect(stored()).toEqual({ edge: "right", along: 180, tucked: false });
  });

  it("dots the default tab when a reply lands while it is tucked", async () => {
    let settle: (v: unknown) => void = () => {};
    relayPost.mockImplementation(() => new Promise((res) => { settle = res; }));
    render();
    await userEvent.click(await pullOut());
    await ask("anything");
    await userEvent.click(screen.getByRole("button", { name: "Close help" }));
    await drag(screen.getByRole("button", { name: "Help assistant" }), -60, 0);
    settle({ answer: "an answer", error: null });
    const dot = await screen.findByLabelText("New reply");
    expect(dot.closest("button")?.getAttribute("aria-label")).toBe("Show help assistant");
  });

  it("restores a tucked launcher from the last visit, unread dot on the tab", async () => {
    window.localStorage.setItem(LAUNCHER_KEY, JSON.stringify({ edge: "left", along: 300, tucked: true }));
    let settle: (v: unknown) => void = () => {};
    relayPost.mockImplementation(() => new Promise((res) => { settle = res; }));
    render();
    const tab = await screen.findByRole("button", { name: "Show help assistant" });
    expect(tab.className).toContain("left-0");

    // Ask from the sheet, close it, and let the answer land while tucked.
    fireEvent.click(tab);
    await userEvent.click(screen.getByRole("button", { name: "Help assistant" }));
    await ask("anything");
    await userEvent.click(screen.getByRole("button", { name: "Close help" }));
    settle({ answer: "an answer", error: null });
    expect(await screen.findByLabelText("New reply")).toBeTruthy();
  });
});

