import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { relayPost, relayGet, signedIn, hub } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  signedIn: { user: { username: "owner", user_id: "u1" } as { username: string; user_id?: string } | null },
  hub: { configured: true, unread: 0, messages: [] as Array<{ id: number; from: string; text: string; at: string }> },
}));

vi.mock("@/lib/relay", () => ({
  RelayError: class extends Error {},
  relay: { post: (...a: unknown[]) => relayPost(...a), get: (...a: unknown[]) => relayGet(...a), put: vi.fn() },
  relayFile: vi.fn(),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: () => {} }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 7 } }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ data: { accounts: [] }, isSuccess: true, dataUpdatedAt: 1 }),
}));
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => (signedIn.user ? { user: signedIn.user } : null) }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";
import { SUPPORT_EMPTY } from "./SupportPanel";
import { SUPPORT_POLL_MS } from "./supportReducer";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";

const tree = () => <PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>;
const unreadCalls = () => relayGet.mock.calls.filter(([p]) => p === "/admin/support/unread").length;

beforeEach(() => {
  relayPost.mockReset();
  relayGet.mockReset();
  hub.configured = true;
  hub.unread = 0;
  hub.messages = [];
  signedIn.user = { username: "owner", user_id: "u1" };
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/support/unread") {
      return Promise.resolve(hub.configured ? { configured: true, unread: hub.unread } : { configured: false });
    }
    if (path === "/admin/support/thread") return Promise.resolve({ configured: true, messages: hub.messages });
    return Promise.resolve({ count: 0, since_hours: 24, list: [], turns: [] });
  });
  relayPost.mockImplementation((path: string, body: { text?: string }) => {
    if (path === "/admin/support/read") { hub.unread = 0; return Promise.resolve({ configured: true, ok: true }); }
    if (path === "/admin/support/messages") {
      hub.messages = [...hub.messages, { id: hub.messages.length + 1, from: "me", text: body.text ?? "", at: "" }];
      return Promise.resolve({ configured: true, messages: hub.messages });
    }
    return Promise.resolve({});
  });
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function openHelp() {
  renderWithProviders(tree());
  await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
}

describe("Support tab", () => {
  it("is hidden when the hub is not configured", async () => {
    hub.configured = false;
    await openHelp();
    await waitFor(() => expect(unreadCalls()).toBe(1));
    expect(screen.queryByRole("button", { name: /^Support/ })).toBeNull();
  });

  it("asks nothing when signed out of a principal", async () => {
    signedIn.user = { username: "anon" };
    await openHelp();
    expect(unreadCalls()).toBe(0);
  });

  it("opens with the empty note, sends, and marks read", async () => {
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    expect(await screen.findByText(SUPPORT_EMPTY)).toBeInTheDocument();
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/support/read", {}));
    const box = screen.getByRole("textbox", { name: "Message Support" });
    await userEvent.type(box, "Need bulk tags{Shift>}{Enter}{/Shift}please{Enter}");
    await screen.findByText(/Need bulk tags/);
    expect(relayPost).toHaveBeenCalledWith("/admin/support/messages", { text: "Need bulk tags\nplease" });
    expect(box).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Back to help" }));
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();
  });

  it("renders markup in a message as text", async () => {
    hub.messages = [{ id: 1, from: "support", text: "<img src=x onerror=alert(1)> thanks", at: "" }];
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    expect(await screen.findByText("<img src=x onerror=alert(1)> thanks")).toBeInTheDocument();
    expect(document.querySelector("[data-support] img")).toBeNull();
  });

  it("an unread reply puts a dot on the closed launcher and clears once opened", async () => {
    hub.unread = 1;
    hub.messages = [{ id: 1, from: "me", text: "hi", at: "" }, { id: 2, from: "support", text: "On it", at: "" }];
    renderWithProviders(tree());
    expect(await screen.findByLabelText("New reply")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Help assistant" }));
    await userEvent.click(await screen.findByRole("button", { name: "Support (new reply)" }));
    expect(await screen.findByText("On it")).toBeInTheDocument();
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/support/read", {}));
    await userEvent.click(screen.getByRole("button", { name: "Back to help" }));
    expect(screen.getByRole("button", { name: "Support" })).toBeInTheDocument();
  });

  it("polls every 60 s only while visible and configured", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const tick = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); await new Promise((r) => setTimeout(r, 0)); });
    renderWithProviders(tree());
    await tick(0);
    expect(unreadCalls()).toBe(1);
    await tick(SUPPORT_POLL_MS - 1);
    expect(unreadCalls()).toBe(1);
    await tick(1);
    expect(unreadCalls()).toBe(2);
    const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await tick(SUPPORT_POLL_MS * 3);
    expect(unreadCalls()).toBe(2);
    vis.mockRestore();
    hub.configured = false;
    await tick(SUPPORT_POLL_MS);
    expect(unreadCalls()).toBe(3);
    await tick(SUPPORT_POLL_MS * 3);
    expect(unreadCalls()).toBe(3);
  });
});
