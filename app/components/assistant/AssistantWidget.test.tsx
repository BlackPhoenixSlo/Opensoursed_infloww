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
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted with the vi.mock factories below — anything they close over has to
// be, or it is still in its TDZ when the mocked module is first imported.
const { relayPost, relayGet, nav, scope, employee, roster } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  nav: { pathname: "/" },
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

vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => employee }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.list }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";

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

  it("focuses the composer from the Ask a question card", async () => {
    await openPanel();
    await userEvent.click(screen.getByRole("button", { name: /Ask a question/ }));
    expect(document.activeElement).toBe(screen.getByPlaceholderText("Ask a question…"));
  });
});
