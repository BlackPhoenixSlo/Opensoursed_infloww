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
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted with the vi.mock factories below — anything they close over has to
// be, or it is still in its TDZ when the mocked module is first imported.
const { relayPost, relayGet, nav, scope, employee, roster } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  nav: { pathname: "/", pushed: [] as string[] },
  scope: { accountId: "1001" as string | null },
  employee: { current: { id: 7 } as { id: number } | null },
  roster: { list: [] as Array<{ id: string; nickname?: string | null }> },
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
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.list }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget, LAUNCHER_KEY } from "./AssistantWidget";

/** The widget starts collapsed; every case here works in the open panel. */
async function openPanel() {
  renderWithProviders(<AssistantProvider><AssistantWidget /></AssistantProvider>);
  const bubble = await screen.findByRole("button", { name: "Help assistant" });
  await userEvent.click(bubble);
  return bubble;
}

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
  roster.list = [
    { id: "1001", nickname: "Blake1" },
    { id: "1002", nickname: "Blake2" },
  ];
  window.localStorage.clear();
});
afterEach(cleanup);

describe("AssistantWidget", () => {
  it("starts collapsed and remembers being opened", async () => {
    const bubble = await openPanel();
    expect(screen.getByPlaceholderText("Ask a question…")).toBeTruthy();
    expect(window.localStorage.getItem("chatterly:assistant_open")).toBe("1");

    await userEvent.click(bubble);
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
    expect(window.localStorage.getItem("chatterly:assistant_open")).toBe("0");
  });

  it("sends {question, account_id} and NO role, scoped to the picked account", async () => {
    relayPost.mockResolvedValue({ answer: "Growth → Profile promotion.", error: null });
    await openPanel();
    await ask("how do I set up auto posts?");

    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    const [path, body, ctx] = relayPost.mock.calls[0];
    expect(path).toBe("/admin/assistant/ask");
    expect(body).toEqual({ question: "how do I set up auto posts?", account_id: "1001" });
    // The server derives who is asking from the session — a role in the body
    // would be client-supplied theater, so it must not be there at all.
    expect(Object.keys(body as object)).not.toContain("role");
    expect(ctx).toMatchObject({ accountId: "1001", employeeId: 7 });
    // Under a scoped model the switcher IS the picker — the widget must not
    // grow a second one that could disagree with it.
    expect(
      screen.queryByLabelText("Account the help bot answers about"),
    ).toBeNull();
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

  it("unlocks in all-models scope with a visible account picker", async () => {
    // The product's DEFAULT scope is "all models". The composer must work
    // there — the server still gets exactly one account_id, chosen in the
    // inline picker (defaulting to the first live account), never null.
    relayPost.mockResolvedValue({ answer: "ok", error: null });
    scope.accountId = null;
    const bubble = await openPanel();

    const picker = screen.getByLabelText(
      "Account the help bot answers about",
    ) as HTMLSelectElement;
    expect(picker.value).toBe("1001");
    await ask("is my welcome on?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    expect(relayPost.mock.calls[0][1]).toMatchObject({ account_id: "1001" });
    expect(relayPost.mock.calls[0][2]).toMatchObject({ accountId: "1001" });

    // Re-picking re-scopes the next question…
    await userEvent.selectOptions(picker, "1002");
    await ask("is my welcome on?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(2));
    expect(relayPost.mock.calls[1][1]).toMatchObject({ account_id: "1002" });

    // …and the pick survives collapsing the panel: it lives in the gate, so a
    // close/reopen must not silently re-bill to the first account in the list.
    await userEvent.click(bubble);
    await userEvent.click(bubble);
    await ask("is my welcome on?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(3));
    expect(relayPost.mock.calls[2][1]).toMatchObject({ account_id: "1002" });
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
    expect(screen.queryByLabelText("Account the help bot answers about")).toBeNull();

    await ask("how do I connect my OnlyFans account?");
    await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
    const [, body, ctx] = relayPost.mock.calls[0];
    // Omitted, not null or "": the server reads a missing id as "no account yet".
    expect(body).toEqual({ question: "how do I connect my OnlyFans account?" });
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
    renderWithProviders(<AssistantProvider><AssistantWidget /></AssistantProvider>);
    // render() flushes the hydration effect, so "open" has been read by now.
    expect(screen.queryByRole("button", { name: "Help assistant" })).toBeNull();
    expect(screen.queryByPlaceholderText("Ask a question…")).toBeNull();
  });

  it("shows All Systems Operational when the error log is empty", async () => {
    await openPanel();
    expect(await screen.findByText("Status: All Systems Operational")).toBeTruthy();
    expect(relayGet.mock.calls[0][0]).toBe("/admin/errors?since_hours=24&limit=50");
  });

  it("shows a Partial Outage with the 24h error count", async () => {
    relayGet.mockResolvedValue({ count: 2, since_hours: 24, list: [] });
    await openPanel();
    expect(await screen.findByText("Status: Partial Outage (2 errors in 24h)")).toBeTruthy();
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
      { id: 12, ts: new Date().toISOString(), question: "where are auto posts?", answer: "Growth → Auto Posts. Want the steps?", error: null, model: "m" },
      { id: 11, ts: new Date(Date.now() - 3 * 86_400_000).toISOString(), question: "old q", answer: "old a", error: null, model: "m" },
      { id: 10, ts: new Date(Date.now() - 4 * 86_400_000).toISOString(), question: "capped", answer: "Cap used up.", error: "cap", model: "m" },
    ];
    beforeEach(() => {
      relayGet.mockImplementation((path: string) => Promise.resolve(
        path.startsWith("/admin/assistant/history") ? { turns: rows } : { count: 0, since_hours: 24, list: [] },
      ));
    });
    const historyCalls = () => relayGet.mock.calls.filter(([p]) => String(p).startsWith("/admin/assistant/history"));

    it("loads once on the first open and shows earlier turns, by day, open in the dock", async () => {
      const bubble = await openPanel();
      const earlier = await screen.findByRole("button", { name: "Earlier (3)" });
      expect(earlier.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByText("where are auto posts?")).toBeTruthy();
      expect(screen.getByText("Today")).toBeTruthy();
      expect(historyCalls()).toHaveLength(1);
      expect(historyCalls()[0][0]).toBe("/admin/assistant/history?limit=50");

      await userEvent.click(bubble); // close
      await userEvent.click(bubble); // reopen: no second read
      await screen.findByRole("button", { name: "Earlier (3)" });
      expect(historyCalls()).toHaveLength(1);
    });

    it("sends the last answered turns (no error ones) as history, oldest first", async () => {
      relayPost.mockResolvedValue({ answer: "Here are the steps.", error: null });
      await openPanel();
      await screen.findByRole("button", { name: "Earlier (3)" });
      await ask("yes");
      await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(1));
      expect(relayPost.mock.calls[0][1]).toEqual({
        question: "yes", account_id: "1001",
        history: [
          { question: "old q", answer: "old a" },
          { question: "where are auto posts?", answer: "Growth → Auto Posts. Want the steps?" },
        ],
      });
      await screen.findByText("Here are the steps.");
      await ask("and then?");
      await waitFor(() => expect(relayPost).toHaveBeenCalledTimes(2));
      expect((relayPost.mock.calls[1][1] as { history: unknown[] }).history).toEqual([
        { question: "old q", answer: "old a" },
        { question: "where are auto posts?", answer: "Growth → Auto Posts. Want the steps?" },
        { question: "yes", answer: "Here are the steps." },
      ]);
    });

    it("a failed history read is no history, and the next open retries", async () => {
      relayGet.mockImplementation((path: string) => path.startsWith("/admin/assistant/history")
        ? Promise.reject(new Error("relay 401")) : Promise.resolve({ count: 0, since_hours: 24, list: [] }));
      const bubble = await openPanel();
      await waitFor(() => expect(historyCalls()).toHaveLength(1));
      expect(screen.queryByRole("button", { name: /Earlier/ })).toBeNull();
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

  const render = () => renderWithProviders(<AssistantProvider><AssistantWidget /></AssistantProvider>);
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

  it("the sheet locks the page under it and unlocks it on close", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    render();
    await screen.findByPlaceholderText("Ask a question…");
    expect(document.body.style.position).toBe("fixed");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");
    // 16px: iOS zooms into a smaller input on focus.
    expect(screen.getByPlaceholderText("Ask a question…").className).toContain("text-[16px]");
    await userEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(document.body.getAttribute("style")).toBeNull();
    expect(document.documentElement.style.overflow).toBe("");
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
    expect(document.body.getAttribute("style")).toBeNull();
  });

  it("earlier turns sit collapsed under Earlier on the sheet", async () => {
    window.localStorage.setItem("chatterly:assistant_open", "1");
    relayGet.mockImplementation((path: string) => Promise.resolve(path.startsWith("/admin/assistant/history")
      ? { turns: [{ id: 1, ts: new Date().toISOString(), question: "old q", answer: "old a", error: null, model: "m" }] }
      : { count: 0, since_hours: 24, list: [] }));
    render();
    const earlier = await screen.findByRole("button", { name: "Earlier (1)" });
    expect(earlier.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("old q")).toBeNull();
    await userEvent.click(earlier);
    expect(screen.getByText("old q")).toBeTruthy();
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

